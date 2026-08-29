"""
studio/prompts.py — Visual Prompt Engine.

Turns a plain scene description ("a person addicted to their phone") into a
prompt engineered for the *selected provider*.

Two axes, kept deliberately separate:

  STYLE PROFILES     what the shot should look like — realistic, cinematic,
                     animation, documentary, 3d, illustration. Provider-
                     independent vocabulary.
  PROVIDER ADAPTERS  how that vocabulary is serialised for a given model.
                     FLUX prefers flowing natural language; SDXL-family
                     models respond to comma-separated tag stacks; video
                     models want motion described separately from subject.

This split is what stops prompts being permanently hardcoded for one model,
which the spec calls out explicitly. Adding a provider means adding a
formatter, not rewriting the style vocabulary.

The Visual Bible (character and location references) is applied here too, so
recurring subjects carry consistent descriptions across scenes — with the
honest caveat that description-level consistency is not identity consistency
(see `consistency_warning`).
"""

from __future__ import annotations

from typing import Optional

from . import db

# =============================================================================
# STYLE PROFILES
# =============================================================================

STYLE_PROFILES: dict[str, dict] = {
    "cinematic": {
        "label": "Cinematic",
        "look": ["cinematic composition", "dramatic lighting",
                 "shallow depth of field", "anamorphic framing",
                 "film grain", "high dynamic range"],
        "camera": "35mm lens, cinematic color grading",
        "avoid": ["text overlay", "watermark", "distorted anatomy", "low resolution"],
    },
    "realistic": {
        "label": "Realistic",
        "look": ["hyper-realistic", "photographic detail", "natural lighting",
                 "realistic skin texture", "true-to-life color"],
        "camera": "50mm lens, documentary photography",
        "avoid": ["illustration", "cartoon", "over-saturated", "watermark"],
    },
    "documentary": {
        "label": "Documentary",
        "look": ["observational framing", "available light", "candid moment",
                 "muted natural palette", "handheld feel"],
        "camera": "24mm lens, vérité style",
        "avoid": ["staged pose", "artificial studio lighting", "watermark"],
    },
    "animated": {
        "label": "Animated",
        "look": ["stylised 2D animation", "clean linework", "bold flat color",
                 "expressive character design"],
        "camera": "graphic composition",
        "avoid": ["photorealism", "watermark", "muddy detail"],
    },
    "3d": {
        "label": "3D Render",
        "look": ["high-end 3D render", "physically based materials",
                 "global illumination", "subsurface scattering", "octane render"],
        "camera": "virtual 35mm camera",
        "avoid": ["flat shading", "low-poly artefacts", "watermark"],
    },
    "illustration": {
        "label": "Illustration",
        "look": ["editorial illustration", "textured brushwork",
                 "limited color palette", "strong silhouette"],
        "camera": "graphic poster composition",
        "avoid": ["photorealism", "watermark"],
    },
    "minimal": {
        "label": "Minimal",
        "look": ["minimalist composition", "generous negative space",
                 "single focal subject", "restrained palette", "soft even light"],
        "camera": "centred composition",
        "avoid": ["clutter", "busy background", "watermark"],
    },
    "dark": {
        "label": "Dark",
        "look": ["low-key lighting", "deep shadows", "high contrast",
                 "desaturated cold palette", "moody atmosphere"],
        "camera": "35mm lens, chiaroscuro lighting",
        "avoid": ["bright cheerful tone", "flat lighting", "watermark"],
    },
    "futuristic": {
        "label": "Futuristic",
        "look": ["near-future aesthetic", "volumetric light", "neon accents",
                 "sleek industrial design", "atmospheric haze"],
        "camera": "wide lens, sci-fi production design",
        "avoid": ["period costume", "rustic setting", "watermark"],
    },
}

DEFAULT_STYLE = "cinematic"


# =============================================================================
# PROVIDER FORMATTERS
# =============================================================================

def _format_natural(subject: str, style: dict, camera: str, extra: list[str]) -> str:
    """Flowing prose — what FLUX / DALL-E-class models respond to best.

    Written as sentences with connectives rather than a comma list, because
    these models parse descriptive language and a bare tag stack reads to them
    as a weaker, less specific instruction.
    """
    sentence = subject.rstrip(".")
    if extra:
        sentence += ". Featuring " + "; ".join(extra)
    sentence += ". Rendered with " + ", ".join(style["look"])
    if camera:
        sentence += f", camera movement: {camera}"
    if style.get("camera"):
        sentence += f", shot on {style['camera']}"
    return sentence + "."


def _format_tags(subject: str, style: dict, camera: str, extra: list[str]) -> str:
    """Comma-separated tag stack, subject first — SDXL-family convention."""
    tags = [subject.rstrip(".")]
    tags.extend(extra)
    if camera:
        tags.append(camera)
    tags.extend(style["look"])
    if style.get("camera"):
        tags.append(style["camera"])
    seen, out = set(), []
    for tag in tags:
        key = tag.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(tag.strip())
    return ", ".join(out)


def _format_motion(subject: str, style: dict, camera: str, extra: list[str]) -> str:
    """Video models: subject first, then motion, then look.

    Camera movement is stated as an explicit instruction because video models
    treat it as a distinct control rather than a stylistic adjective.
    """
    parts = [subject.rstrip(".")]
    parts.extend(extra)
    if camera:
        parts.append(f"Camera: {camera}")
    parts.append(", ".join(style["look"]))
    return ". ".join(p for p in parts if p).strip()


#: provider name -> formatter. Unknown providers fall back to natural
#: language, which is the most broadly accepted form.
_FORMATTERS = {
    "openai": _format_natural,
    "pollinations": _format_natural,
    "together": _format_tags,
    "replicate": _format_motion,
}


def _formatter_for(provider: str, kind: str):
    if kind == "video":
        return _FORMATTERS.get(provider, _format_motion)
    return _FORMATTERS.get(provider, _format_natural)


# =============================================================================
# VISUAL BIBLE
# =============================================================================

def load_references(project_id: str) -> list[dict]:
    return db.fetch_all(
        "SELECT * FROM visual_reference WHERE project_id=? ORDER BY kind, name",
        (project_id,), json_fields=("attributes", "reference_asset_ids"))


def _reference_clause(refs: list[dict], names: list[str]) -> list[str]:
    """Expand named characters/locations into their canonical descriptions."""
    if not names:
        return []
    wanted = {n.lower().strip() for n in names if n}
    clauses = []
    for ref in refs:
        if ref["name"].lower().strip() not in wanted:
            continue
        bits = [ref["description"].strip()] if ref["description"] else []
        attrs = ref.get("attributes") or {}
        for key in ("appearance", "clothing", "age", "lighting", "mood", "style"):
            val = attrs.get(key)
            if val:
                bits.append(f"{key}: {val}")
        if bits:
            clauses.append(f"{ref['name']} ({'; '.join(bits)})")
    return clauses


def consistency_warning(provider_name: str, provider) -> Optional[str]:
    """State plainly what the selected provider can and cannot guarantee.

    Description-level consistency (the Visual Bible repeating the same words)
    is not identity consistency. Only providers that document a reference
    mechanism get the softer message, and even they get "improves", not
    "guarantees".
    """
    if provider is not None and provider.supports("character_reference"):
        return ("This provider supports reference-guided generation, which "
                "improves but does not guarantee identity consistency across "
                "scenes. Review generated scenes before rendering.")
    return (f"'{provider_name}' offers no character-reference mechanism. The "
            f"Visual Bible keeps descriptions identical across scenes, but the "
            f"provider may still render the same character differently in each "
            f"shot. Visual continuity is not guaranteed.")


# =============================================================================
# PROMPT BUILDING
# =============================================================================

def build_prompt(*, description: str, style: str = DEFAULT_STYLE,
                 camera: str = "", provider: str = "", kind: str = "image",
                 project_id: str = "", character_refs: Optional[list] = None,
                 aspect_ratio: str = "16:9") -> dict:
    """Compose the final prompt for one scene.

    Returns the prompt, a negative prompt, and the decisions that produced
    them — the storyboard stores all three so a user can see *why* a prompt
    looks the way it does and edit any layer.
    """
    profile = STYLE_PROFILES.get(style, STYLE_PROFILES[DEFAULT_STYLE])

    extra: list[str] = []
    if project_id and character_refs:
        extra.extend(_reference_clause(load_references(project_id), character_refs))

    formatter = _formatter_for(provider, kind)
    prompt = formatter(description, profile, camera, extra)

    if aspect_ratio == "9:16":
        prompt += ", vertical composition framed for mobile"
    elif aspect_ratio == "1:1":
        prompt += ", square composition"

    return {
        "prompt": prompt,
        "negative_prompt": ", ".join(profile["avoid"]),
        "style": style,
        "style_label": profile["label"],
        "provider_format": getattr(formatter, "__name__", "").replace("_format_", ""),
        "applied_references": extra,
    }


def rewrite_for_provider(prompt_text: str, *, from_provider: str,
                         to_provider: str, kind: str = "image",
                         style: str = DEFAULT_STYLE) -> str:
    """Re-serialise an existing prompt for a different provider.

    Used when a scene is retried on another provider after a failure — the
    creative intent carries over, the formatting changes.
    """
    if from_provider == to_provider:
        return prompt_text
    profile = STYLE_PROFILES.get(style, STYLE_PROFILES[DEFAULT_STYLE])
    look_terms = {t.lower() for t in profile["look"]}
    # Strip the old provider's style scaffolding, keep the subject.
    kept = [seg.strip() for seg in prompt_text.split(",")
            if seg.strip() and seg.strip().lower() not in look_terms]
    subject = ", ".join(kept[:3]) if kept else prompt_text
    return _formatter_for(to_provider, kind)(subject, profile, "", [])


def list_styles() -> list[dict]:
    return [{"id": key, "label": val["label"], "look": val["look"]}
            for key, val in STYLE_PROFILES.items()]
