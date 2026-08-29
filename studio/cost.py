"""
studio/cost.py — Generation cost centre and budget enforcement.

Two rules the spec is emphatic about, encoded here:

1. **An estimate is never presented as a price.** Every estimate carries a
   `confidence` (`published` / `modelled` / `unknown`) and the basis it was
   computed from. When we do not know a provider's rate, `amount` is None and
   the UI shows "cost unknown" — not "$0.00", which reads as free.

2. **Actual cost is recorded only when the provider returns one.** The
   `usage_record` table keeps `estimated_cost` and `actual_cost` in separate
   columns; reports that mix them label which is which.

Budget enforcement is advisory-by-design at the data layer and enforced at
the dispatch layer: `check_budget()` returns a decision, and `jobs.py` refuses
to enqueue paid work when the decision blocks. A budget of 0 means "unset",
reported as such — never silently treated as unlimited.
"""

from __future__ import annotations

import datetime
from typing import Optional

from . import db
from .providers.base import CostEstimate, GenerationRequest

try:
    from config import STUDIO_MONTHLY_BUDGET
except ImportError:  # pragma: no cover
    STUDIO_MONTHLY_BUDGET = 0.0


def current_month() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")


# =============================================================================
# ESTIMATES
# =============================================================================

def estimate(kind: str, provider, request: GenerationRequest,
             quantity: int = 1) -> CostEstimate:
    """Ask the provider what a job will cost.

    We deliberately do not substitute a house average when the provider says
    it does not know: a made-up number would be worse than an honest blank,
    because the user would budget against it.
    """
    try:
        base = provider.estimate_cost(request)
    except Exception as exc:  # noqa: BLE001 - estimation must never break a job
        return CostEstimate(amount=None, confidence="unknown",
                            basis=f"estimation failed: {exc}")

    if base.amount is None or quantity <= 1:
        return base
    return CostEstimate(
        amount=round(base.amount * quantity, 4),
        currency=base.currency,
        confidence=base.confidence,
        basis=f"{base.basis} × {quantity}",
    )


def estimate_project(project_id: str, workspace: str) -> dict:
    """Estimate what generating every unstarted scene would cost.

    Returns both a total and an explicit count of scenes whose cost we could
    not determine, so the UI can say "at least $X, plus N scenes of unknown
    cost" instead of understating the bill.
    """
    from .providers import registry

    scenes = db.fetch_all(
        """SELECT s.* FROM scene s
           JOIN storyboard b ON b.id = s.storyboard_id
           WHERE s.project_id=? AND b.is_current=1 AND s.status != 'completed'
           ORDER BY s.idx""",
        (project_id,),
    )

    known_total = 0.0
    unknown = 0
    lines = []

    for scene in scenes:
        kind = "video" if scene["asset_type"] == "ai_video" else "image"
        if scene["asset_type"] not in ("ai_video", "ai_image"):
            continue  # stock / upload / text scenes cost nothing to generate
        try:
            provider = registry.resolve(kind, workspace)
        except registry.NoProviderAvailable:
            unknown += 1
            lines.append({"scene": scene["idx"], "kind": kind,
                          "amount": None, "reason": "no connected provider"})
            continue

        req = GenerationRequest(
            prompt=scene["generation_prompt"] or scene["visual_description"],
            duration_s=scene["duration_s"],
        )
        est = estimate(kind, provider, req)
        if est.amount is None:
            unknown += 1
        else:
            known_total += est.amount
        lines.append({"scene": scene["idx"], "kind": kind,
                      "provider": provider.name, "amount": est.amount,
                      "confidence": est.confidence, "reason": est.basis})

    return {
        "scenes_costed": len(lines),
        "known_total": round(known_total, 4),
        "unknown_count": unknown,
        # The honest headline: a floor, not a total, whenever anything is unknown.
        "is_complete": unknown == 0,
        "label": ("estimated total" if unknown == 0
                  else f"at least this much, plus {unknown} item(s) of unknown cost"),
        "currency": "USD",
        "lines": lines,
    }


# =============================================================================
# USAGE RECORDING
# =============================================================================

def record_usage(*, workspace: str, project_id: str = "", job_id: str = "",
                 provider: str = "", model: str = "", asset_type: str = "",
                 units: float = 1, unit_label: str = "",
                 estimated_cost: Optional[float] = None,
                 actual_cost: Optional[float] = None,
                 currency: str = "USD") -> str:
    """Append a usage row. Estimated and actual stay in separate columns."""
    record_id = db.new_id("use")
    db.insert("usage_record", {
        "id": record_id,
        "workspace": workspace,
        "project_id": project_id or None,
        "job_id": job_id or None,
        "provider": provider,
        "model": model,
        "asset_type": asset_type,
        "units": units,
        "unit_label": unit_label,
        "estimated_cost": estimated_cost,
        "actual_cost": actual_cost,
        "currency": currency,
        "ts": db.now(),
    })
    return record_id


def month_bounds(month: str) -> tuple[float, float]:
    year, mon = (int(p) for p in month.split("-"))
    start = datetime.datetime(year, mon, 1, tzinfo=datetime.timezone.utc)
    end = (datetime.datetime(year + (mon == 12), (mon % 12) + 1, 1,
                             tzinfo=datetime.timezone.utc))
    return start.timestamp(), end.timestamp()


def month_spend(workspace: str, month: str = "") -> dict:
    """What the workspace has spent this month.

    `confirmed` sums provider-reported actuals. `estimated_only` sums
    estimates for jobs whose provider never reported a real cost. They are
    reported separately because adding them would present a guess as spend.
    """
    month = month or current_month()
    start, end = month_bounds(month)

    rows = db.fetch_all(
        "SELECT actual_cost, estimated_cost FROM usage_record "
        "WHERE workspace=? AND ts>=? AND ts<?",
        (workspace, start, end),
    )

    confirmed = sum(r["actual_cost"] for r in rows if r["actual_cost"] is not None)
    estimated_only = sum(
        r["estimated_cost"] for r in rows
        if r["actual_cost"] is None and r["estimated_cost"] is not None
    )
    unpriced = sum(
        1 for r in rows
        if r["actual_cost"] is None and r["estimated_cost"] is None
    )

    return {
        "month": month,
        "confirmed": round(confirmed, 4),
        "estimated_only": round(estimated_only, 4),
        "unpriced_events": unpriced,
        "records": len(rows),
        "currency": "USD",
    }


# =============================================================================
# BUDGET
# =============================================================================

def get_budget(workspace: str, month: str = "") -> dict:
    month = month or current_month()
    row = db.fetch_one(
        "SELECT * FROM studio_budget WHERE workspace=? AND month=?",
        (workspace, month),
    )
    limit = row["limit_amount"] if row else float(STUDIO_MONTHLY_BUDGET or 0)
    spend = month_spend(workspace, month)

    # Spend against the budget counts confirmed cost plus estimates for
    # anything not yet priced — the conservative reading, so a user does not
    # blow through a limit on the technicality that costs are unconfirmed.
    used = spend["confirmed"] + spend["estimated_only"]

    return {
        "workspace": workspace,
        "month": month,
        "configured": limit > 0,
        "limit": round(limit, 2) if limit > 0 else None,
        "used": round(used, 4),
        "used_confirmed": spend["confirmed"],
        "used_estimated": spend["estimated_only"],
        "remaining": round(limit - used, 4) if limit > 0 else None,
        "unpriced_events": spend["unpriced_events"],
        "currency": "USD",
        "note": ("no monthly budget configured — spending is not capped"
                 if limit <= 0 else ""),
    }


def set_budget(workspace: str, amount: float, month: str = "") -> dict:
    month = month or current_month()
    existing = db.fetch_one(
        "SELECT workspace FROM studio_budget WHERE workspace=? AND month=?",
        (workspace, month))
    if existing:
        db.execute(
            "UPDATE studio_budget SET limit_amount=?, updated_at=? "
            "WHERE workspace=? AND month=?",
            (float(amount), db.now(), workspace, month))
    else:
        db.insert("studio_budget", {
            "workspace": workspace, "month": month,
            "limit_amount": float(amount), "currency": "USD",
            "updated_at": db.now(),
        })
    return get_budget(workspace, month)


def check_budget(workspace: str, incoming: Optional[float]) -> dict:
    """Decide whether a job of estimated cost `incoming` may proceed.

    `incoming=None` (unknown cost) does **not** block: refusing everything we
    cannot price would make unpriced providers unusable. It is flagged so the
    approval layer can require a human when the budget is tight.
    """
    budget = get_budget(workspace)

    if not budget["configured"]:
        return {"allowed": True, "reason": "no budget configured",
                "budget": budget, "requires_approval": False}

    if incoming is None:
        tight = budget["remaining"] is not None and budget["remaining"] < budget["limit"] * 0.1
        return {
            "allowed": True,
            "reason": "cost unknown for this provider; not counted against budget yet",
            "budget": budget,
            "requires_approval": tight,
        }

    projected = budget["used"] + incoming
    if projected > budget["limit"]:
        return {
            "allowed": False,
            "reason": (f"would exceed the {budget['month']} budget: "
                       f"${projected:.2f} projected against a ${budget['limit']:.2f} limit"),
            "budget": budget,
            "requires_approval": True,
        }
    return {"allowed": True, "reason": "within budget", "budget": budget,
            "requires_approval": False}


def cost_center(workspace: str, month: str = "") -> dict:
    """Everything the Cost Center screen needs."""
    month = month or current_month()
    start, end = month_bounds(month)

    by_provider = db.fetch_all(
        """SELECT provider, model, asset_type, COUNT(*) AS events,
                  SUM(COALESCE(actual_cost, 0)) AS confirmed,
                  SUM(CASE WHEN actual_cost IS NULL
                           THEN COALESCE(estimated_cost, 0) ELSE 0 END) AS estimated
           FROM usage_record
           WHERE workspace=? AND ts>=? AND ts<?
           GROUP BY provider, model, asset_type
           ORDER BY confirmed DESC, estimated DESC""",
        (workspace, start, end),
    )

    recent = db.fetch_all(
        """SELECT provider, model, asset_type, estimated_cost, actual_cost, ts,
                  project_id, job_id
           FROM usage_record WHERE workspace=? ORDER BY ts DESC LIMIT 50""",
        (workspace,),
    )

    return {
        "budget": get_budget(workspace, month),
        "by_provider": by_provider,
        "recent": recent,
        "disclaimer": ("Estimates are labelled as such and are not guaranteed "
                       "prices. Confirmed figures are those a provider actually "
                       "reported."),
    }
