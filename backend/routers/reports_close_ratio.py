"""Feb-2026 · Reports Gap Fill Phase 5b.1 — Close Ratio.

Windowed lead-pipeline close-rate view. Reuses the canonical lead
collection ``db.leads`` and the status enum at
``routers/leads.py:44`` (``closed_won`` / ``closed_lost``). Legacy
title-case variants ("Closed Won" / "Closed Lost") are normalized
on read so the numbers match regardless of when a lead was
stamped (pre- vs. post-``migrate_lead_statuses`` sweep).

Contract:
    GET /api/reports/close-ratio?start_date&end_date

    → {
        "summary": {"close_ratio_pct", "leads_created",
                     "leads_closed_won", "leads_closed_lost"},
        "rows": [
            {"month": "YYYY-MM", "leads_created", "closed_won",
             "closed_lost", "close_ratio_pct"}
        ],
        "chart": {"monthly_close_ratio":
            [{"month", "close_ratio_pct"}]},
        "tenant_id", "start_date", "end_date", "computed_at"
      }

Canonical pins:
* **Collection** — ``db.leads`` (same as ``routers.leads`` +
  ``routers.dashboard`` lead counters).
* **Won predicate** — status normalized to lower-case,
  underscores; row matches when in ``{"closed_won"}``.
* **Lost predicate** — same, ``{"closed_lost"}``.
* **Open leads** (any other status) — excluded from the ratio
  denominator per spec.
* **Window semantics** — the summary uses ``created_at`` to
  attribute leads to the window (the ratio measures the cohort of
  leads *born* in the window). Per-month rows also key off
  ``created_at``. This matches how "close ratio for last quarter"
  is usually reported: "of the leads we got last quarter, how
  many did we close?"
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger  # noqa: F401
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# Feb-2026 · P16B — helpers extracted to services/_shared/reports.py.
from services._shared.reports import (  # noqa: E402
    _iso_day_bounds,
    _norm_status,
)


@router.get(
    "/reports/close-ratio",
    operation_id="reports.closeRatio",
    summary="Close Ratio — lead-pipeline win rate by month",
)
async def close_ratio(
    start_date: str = Query(..., description="YYYY-MM-DD (inclusive)"),
    end_date:   str = Query(..., description="YYYY-MM-DD (inclusive)"),
    tenant_id: Optional[str] = Query(None,
        description="super_admin only — override tenant scope"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").strip().lower()
    if tenant_id and role != "super_admin":
        raise HTTPException(403, "tenant_id override requires super_admin")
    tid = (tenant_id or tenant["id"]).strip()
    if not tid:
        raise HTTPException(400, "tenant scope missing")

    s_iso, e_iso = _iso_day_bounds(start_date, end_date)

    leads = await db.leads.find(
        {"tenant_id": tid,
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "status": 1, "created_at": 1,
         "closed_at": 1},
    ).to_list(20000)

    per_month: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"leads_created": 0, "closed_won": 0, "closed_lost": 0},
    )
    total_created = 0
    total_won = 0
    total_lost = 0

    for L in leads:
        created = L.get("created_at")
        if not isinstance(created, str) or not (s_iso <= created <= e_iso):
            continue
        month = created[:7]
        per_month[month]["leads_created"] += 1
        total_created += 1
        status = _norm_status(L.get("status"))
        if status == "closed_won":
            per_month[month]["closed_won"] += 1
            total_won += 1
        elif status == "closed_lost":
            per_month[month]["closed_lost"] += 1
            total_lost += 1

    rows: List[dict] = []
    for month in sorted(per_month.keys()):
        won = per_month[month]["closed_won"]
        lost = per_month[month]["closed_lost"]
        denom = won + lost
        rate = round((won / denom) * 100, 1) if denom else 0.0
        rows.append({
            "month":            month,
            "leads_created":    per_month[month]["leads_created"],
            "closed_won":       won,
            "closed_lost":      lost,
            "close_ratio_pct":  rate,
        })

    denom_total = total_won + total_lost
    overall = round((total_won / denom_total) * 100, 1) if denom_total else 0.0

    return {
        "summary": {
            "close_ratio_pct":    overall,
            "leads_created":      total_created,
            "leads_closed_won":   total_won,
            "leads_closed_lost":  total_lost,
        },
        "rows": rows,
        "chart": {
            "monthly_close_ratio": [
                {"month": r["month"],
                  "close_ratio_pct": r["close_ratio_pct"]} for r in rows
            ],
        },
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
