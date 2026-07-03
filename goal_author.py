"""Phase 14 — self-authored goal daemon.

Ultron watches its own observation stream and PROPOSES goals for itself. This
is the JARVIS->Ultron jump: prior phases only execute goals they were given;
this one originates them.

Flow (called once per autonomous-loop cycle via `author(observation)`):
    detectors -> [GoalProposal]     (pure, see propose())
        -> dedup (cooldown + persisted keys)
        -> daily cap
        -> safety classify (GREEN/AMBER/RED); RED dropped
        -> GREEN & auto enabled -> create real goal (source="self_authored")
           GREEN & auto disabled, or AMBER -> park for approval + notify user

Everything is flag-gated by the caller (ULTRON_PHASE14_ENABLED). Auto-creation
of GREEN goals additionally requires ULTRON_PHASE14_AUTO_GREEN=1; default is to
park EVERYTHING for approval until the user trusts it.

Pure detectors live at the top; all I/O (goal store, state file, notifications)
is at the edges behind mockable seams.
"""
import json
import os
import re
import threading
import time
from collections import Counter
from typing import Any, Dict, List, Optional

from goal_author_types import GoalProposal, SafetyTier, _normalise


# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────
REPEATED_FAILURE_THRESHOLD = 3      # same subject failing N times -> investigate
KNOWLEDGE_GAP_THRESHOLD = 3         # topic recurs N times with no KB entry
MAX_SELF_GOALS_PER_DAY = 5          # hard cap on autonomous goal creation
DEDUP_COOLDOWN_SECONDS = 24 * 3600  # don't re-propose the same thing within 24h

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATE_PATH = os.path.join(_BASE_DIR, "goal_author_state.json")

# Words that must never appear in a self-authored goal's intent. If a proposal
# text trips this, it is classified RED and dropped — a belt-and-braces guard on
# top of category-based tiering.
_RED_PATTERNS = (
    "delete", "rm -rf", "remove file", "format", "wipe", "uninstall",
    "drop database", "sudo", "run_python", "run_code", "exec(", "shell",
    "self-modify", "self modify", "patch_file", "send money", "pay ", "payment",
    "purchase", "transfer funds", "email ", "sms ", "text message to",
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "with", "that", "this", "it",
    "as", "by", "from", "about", "into", "how", "what", "why", "when", "where",
    "you", "your", "i", "me", "my", "we", "our", "he", "she", "they", "them",
    "do", "does", "did", "can", "could", "will", "would", "should", "please",
    "want", "need", "get", "got", "make", "just", "like", "some", "more",
}

_lock = threading.RLock()


def _now() -> float:
    return time.time()


# ─────────────────────────────────────────────────────────────────────────────
# Detectors — PURE. Each takes the observation dict and returns 0..n proposals.
# ─────────────────────────────────────────────────────────────────────────────
def _detect_repeated_failure(obs: Dict[str, Any]) -> List[GoalProposal]:
    """obs['failure_counts'] = {subject: count}. A subject that keeps failing
    is worth investigating."""
    counts = obs.get("failure_counts") or {}
    out: List[GoalProposal] = []
    for subject, count in counts.items():
        if not subject or count < REPEATED_FAILURE_THRESHOLD:
            continue
        out.append(GoalProposal(
            title=f"Investigate repeated failures of '{subject}'",
            description=(
                f"'{subject}' has failed {count} times recently. Diagnose the "
                f"root cause and report findings (no changes without approval)."
            ),
            rationale=f"{count} failures of '{subject}' observed in recent history.",
            trigger="repeated_failure",
            subject=subject,
            priority="high",
            confidence=round(min(0.95, count / (count + 2.0)), 3),
            category="research",
        ))
    return out


def _extract_topics(texts: List[str]) -> List[str]:
    """Pull candidate topic tokens from free text (lowercased, de-stopworded)."""
    topics: List[str] = []
    for t in texts or []:
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", t or ""):
            lw = w.lower()
            if lw in _STOPWORDS:
                continue
            topics.append(lw)
    return topics


def _detect_knowledge_gap(obs: Dict[str, Any]) -> List[GoalProposal]:
    """obs['recent_topics'] = list[str] (raw texts OR tokens);
    obs['known_topics'] = iterable[str] already in the knowledge base.
    A topic that recurs but isn't known is a gap worth researching."""
    raw = obs.get("recent_topics") or []
    # Accept either pre-tokenised topics or raw utterances.
    tokens = _extract_topics(raw) if raw and any(" " in str(x) for x in raw) else \
        [_normalise(str(x)) for x in raw]
    known = {_normalise(str(x)) for x in (obs.get("known_topics") or [])}
    freq = Counter(t for t in tokens if t)
    out: List[GoalProposal] = []
    for topic, count in freq.items():
        if count < KNOWLEDGE_GAP_THRESHOLD or topic in known:
            continue
        out.append(GoalProposal(
            title=f"Research '{topic}' and add to knowledge base",
            description=(
                f"'{topic}' has come up {count} times recently but isn't in the "
                f"knowledge base. Research it and store a concise summary."
            ),
            rationale=f"'{topic}' recurred {count} times with no KB entry.",
            trigger="knowledge_gap",
            subject=topic,
            priority="medium",
            confidence=round(min(0.9, count / (count + 3.0)), 3),
            category="research",
        ))
    return out


_DETECTORS = (_detect_repeated_failure, _detect_knowledge_gap)


def propose(observation: Dict[str, Any]) -> List[GoalProposal]:
    """Run every detector over the observation. Pure — no side effects."""
    proposals: List[GoalProposal] = []
    for det in _DETECTORS:
        try:
            proposals.extend(det(observation or {}))
        except Exception:
            continue
    # Highest-confidence first so the daily cap keeps the best.
    proposals.sort(key=lambda p: p.confidence, reverse=True)
    return proposals


# ─────────────────────────────────────────────────────────────────────────────
# Safety classification (Tier-4 seed) — PURE.
# ─────────────────────────────────────────────────────────────────────────────
_CATEGORY_TIER = {
    "research": SafetyTier.GREEN,
    "replan": SafetyTier.GREEN,
    "cleanup": SafetyTier.AMBER,
    "automate": SafetyTier.AMBER,
}


def classify_safety(proposal: GoalProposal) -> SafetyTier:
    """Classify a proposal. A destructive keyword anywhere forces RED regardless
    of category."""
    blob = f"{proposal.title} {proposal.description} {proposal.subject}".lower()
    for pat in _RED_PATTERNS:
        if pat in blob:
            return SafetyTier.RED
    return _CATEGORY_TIER.get(proposal.category, SafetyTier.AMBER)


# ─────────────────────────────────────────────────────────────────────────────
# State: dedup cooldown + daily cap + pending-approval queue (persisted JSON)
# ─────────────────────────────────────────────────────────────────────────────
def _blank_state() -> Dict[str, Any]:
    return {"seen": {}, "created_today": {"date": "", "count": 0}, "pending": []}


def _load_state() -> Dict[str, Any]:
    with _lock:
        if not os.path.exists(_STATE_PATH):
            return _blank_state()
        try:
            with open(_STATE_PATH) as f:
                data = json.load(f)
            base = _blank_state()
            base.update(data or {})
            return base
        except Exception:
            return _blank_state()


def _save_state(state: Dict[str, Any]) -> None:
    with _lock:
        try:
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, _STATE_PATH)
        except Exception:
            pass


def _reset_for_test() -> None:
    with _lock:
        try:
            if os.path.exists(_STATE_PATH):
                os.remove(_STATE_PATH)
        except Exception:
            pass


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime(_now()))


def _remaining_today(state: Dict[str, Any]) -> int:
    ct = state.get("created_today") or {}
    if ct.get("date") != _today():
        return MAX_SELF_GOALS_PER_DAY
    return max(0, MAX_SELF_GOALS_PER_DAY - int(ct.get("count", 0)))


def _bump_created(state: Dict[str, Any]) -> None:
    ct = state.get("created_today") or {}
    if ct.get("date") != _today():
        ct = {"date": _today(), "count": 0}
    ct["count"] = int(ct.get("count", 0)) + 1
    state["created_today"] = ct


def _is_on_cooldown(state: Dict[str, Any], dedup_key: str) -> bool:
    ts = (state.get("seen") or {}).get(dedup_key)
    return ts is not None and (_now() - float(ts)) < DEDUP_COOLDOWN_SECONDS


# ── I/O seams (mockable in tests) ────────────────────────────────────────────
def _create_goal(p: GoalProposal) -> Dict[str, Any]:
    from decision_engine import create_goal
    return create_goal(
        title=p.title,
        description=p.description,
        priority=p.priority,
        source="self_authored",
        tags=["self_authored", p.trigger],
        success_criteria=p.rationale,
    )


def _notify(msg: str) -> None:
    try:
        from autonomous_loop import push_agent_suggestion
        push_agent_suggestion(msg, priority="normal")
    except Exception:
        pass


def _auto_green_enabled() -> bool:
    return os.environ.get("ULTRON_PHASE14_AUTO_GREEN", "0") == "1"


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────
def _process_proposals(proposals: List[GoalProposal], state: Dict[str, Any],
                       summary: Dict[str, int]) -> None:
    """Run proposals through dedup -> safety gate -> create/park. Mutates
    `state` and `summary`. Shared by author() and submit_proposals()."""
    for p in proposals:
        if _is_on_cooldown(state, p.dedup_key):
            summary["deduped"] += 1
            continue
        tier = classify_safety(p)
        if tier == SafetyTier.RED:
            summary["dropped_red"] += 1
            state.setdefault("seen", {})[p.dedup_key] = _now()
            continue

        # Any proposal we act on (create or park) is marked seen now.
        state.setdefault("seen", {})[p.dedup_key] = _now()

        if tier == SafetyTier.GREEN and _auto_green_enabled():
            if _remaining_today(state) <= 0:
                _park(state, p, tier)
                summary["parked"] += 1
                _notify(f"🤖 Ultron (capped) proposes: {p.title}")
                continue
            try:
                _create_goal(p)
                _bump_created(state)
                summary["created"] += 1
            except Exception:
                _park(state, p, tier)
                summary["parked"] += 1
        else:
            _park(state, p, tier)
            summary["parked"] += 1
            _notify(f"🤖 Ultron proposes ({tier.value}): {p.title} — "
                    f"{p.rationale} Approve?")


def author(observation: Dict[str, Any]) -> Dict[str, Any]:
    """Turn observations into self-authored goals / parked proposals.

    Returns a summary dict. Side effects: may create goals, park proposals,
    notify the user, and persist state.
    """
    summary = {"proposed": 0, "dropped_red": 0, "deduped": 0,
               "created": 0, "parked": 0}
    with _lock:
        state = _load_state()
        proposals = propose(observation or {})
        summary["proposed"] = len(proposals)
        _process_proposals(proposals, state, summary)
        _save_state(state)
    return summary


def submit_proposals(proposals: List[GoalProposal]) -> Dict[str, Any]:
    """Route externally-built proposals (e.g. from predictive_intervention)
    through the same dedup / safety / cap / park pipeline as author()."""
    summary = {"proposed": 0, "dropped_red": 0, "deduped": 0,
               "created": 0, "parked": 0}
    with _lock:
        state = _load_state()
        summary["proposed"] = len(proposals or [])
        _process_proposals(list(proposals or []), state, summary)
        _save_state(state)
    return summary


def _park(state: Dict[str, Any], p: GoalProposal, tier: SafetyTier) -> None:
    entry = p.to_dict()
    entry["tier"] = tier.value
    entry["parked_at"] = _now()
    pending = state.setdefault("pending", [])
    # Replace any existing pending entry with the same dedup_key.
    pending[:] = [e for e in pending if e.get("dedup_key") != p.dedup_key]
    pending.append(entry)


# ── Approval API (route/voice wiring is a later step) ────────────────────────
def list_pending() -> List[Dict[str, Any]]:
    return list(_load_state().get("pending", []))


def approve(dedup_key: str) -> Optional[Dict[str, Any]]:
    """Approve a parked proposal -> create the real goal. Returns the goal."""
    with _lock:
        state = _load_state()
        pending = state.get("pending", [])
        match = next((e for e in pending if e.get("dedup_key") == dedup_key), None)
        if match is None:
            return None
        goal = _create_goal(GoalProposal.from_dict(match))
        _bump_created(state)
        state["pending"] = [e for e in pending if e.get("dedup_key") != dedup_key]
        _save_state(state)
        return goal


def reject(dedup_key: str) -> bool:
    """Drop a parked proposal without creating a goal."""
    with _lock:
        state = _load_state()
        pending = state.get("pending", [])
        new_pending = [e for e in pending if e.get("dedup_key") != dedup_key]
        if len(new_pending) == len(pending):
            return False
        state["pending"] = new_pending
        _save_state(state)
        return True


# ── Voice decision NLU (pure) + handler ──────────────────────────────────────
_APPROVE_RE = re.compile(r"\b(approve|accept|confirm|go ahead|do it)\b", re.I)
_REJECT_RE = re.compile(r"\b(reject|dismiss|discard|decline|ignore|forget it)\b", re.I)
_PROPOSAL_CUE_RE = re.compile(r"\b(propos\w*|suggestion|that|it|goal|idea)\b", re.I)
_BARE_APPROVE = {"approve", "accept", "confirm", "yes", "do it", "go ahead"}
_BARE_REJECT = {"reject", "dismiss", "discard", "decline", "no", "ignore it"}


def match_proposal_command(text: str) -> Optional[str]:
    """Return 'approve' / 'reject' if the utterance is a proposal decision,
    else None. Conservative: needs a decision verb plus a referent cue (or an
    exact bare command) so it doesn't hijack normal conversation."""
    if not text:
        return None
    t = " ".join(text.strip().lower().split())
    has_cue = bool(_PROPOSAL_CUE_RE.search(t))
    if _APPROVE_RE.search(t) and (has_cue or t in _BARE_APPROVE):
        return "approve"
    if _REJECT_RE.search(t) and (has_cue or t in _BARE_REJECT):
        return "reject"
    return None


def handle_voice_decision(text: str) -> Optional[Dict[str, Any]]:
    """Approve/reject the MOST RECENT pending proposal by voice. Returns a
    result dict when it handled the utterance, else None (so the caller falls
    through to normal command parsing)."""
    cmd = match_proposal_command(text)
    if cmd is None:
        return None
    pending = list_pending()
    if not pending:
        return None
    latest = pending[-1]
    key = latest.get("dedup_key")
    if cmd == "approve":
        goal = approve(key)
        return {"decision": "approved", "title": latest.get("title"), "goal": goal}
    reject(key)
    return {"decision": "rejected", "title": latest.get("title")}
