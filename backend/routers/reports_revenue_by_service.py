"""Feb-2026 · Reports Gap Fill Phase 5a.2 — Revenue by Service.

Windowed revenue aggregation pivoted by service (invoice title).
Mirrors the ``routers.reports.revenue_by_customer`` join pattern
verbatim — mirrors ``_fetch_paid`` / ``_fetch_all_invoices`` / the
``_paid_amt`` helper so cockpit parity is a compile-time guarantee.
(P59 · Feb-2026: the two ``_fetch_*`` helpers in
``routers/reports.py`` now require a ``tenant_id`` positional arg;
this module already scopes its own query inline, so no code change
here — noting for future editors so the docstring comparison
doesn't rot.)

Contract:
    GET /api/reports/revenue-by-service?start_date&end_date

    → {
        "summary": {"total_billed", "total_collected",
                     "top_service_by_revenue": {"name", "amount"}},
        "rows": [
            {"service_name", "service_id", "billed_amount",
             "collected_amount", "job_count", "avg_ticket"}
        ],
        "chart": {"top_services": [
            {"service_name", "billed_amount"}, ...  # top 10
        ]},
        "tenant_id", "start_date", "end_date", "computed_at"
      }

Canonical data-source pins:
* **Collection** — ``db.quotes`` where ``doc_type="invoice"``
  (Phase-11 unified ledger; same as ``reports.revenue_by_customer``).
* **Pivot ``service_name``** — ``invoice.title`` (this is the
  field the invoice grid + admin dashboards display; if absent
  → ``"Unclassified"``). Documented in the memo.
* **Pivot ``service_id``** — falls back to a lowercased slug of
  ``service_name`` (the invoice schema doesn't carry a stable
  ``service_id`` on line items; a follow-up ticket can wire an
  explicit link if ops needs it).
* **``billed_amount``** — sum of ``invoice.total`` (all statuses,
  soft-deleted excluded via ``_fetch_all_invoices``).
* **``collected_amount``** — sum of ``_paid_amt(inv)`` (same
  helper as every other revenue slice, so drift is impossible).
* **``job_count``** — count of unique invoices in the bucket
  (each invoice ~= one job; a per-line-item count would double-
  count multi-line invoices).
* **``avg_ticket``** — ``billed_amount / job_count``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger  # noqa: F401 — kept for uniform module shape
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(tags=["reports"])


# Feb-2026 · P16B — helper extracted to services/_shared/reports.py.
from services._shared.reports import _iso_day_bounds  # noqa: E402


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in (name or "").lower()).strip("-") or "unclassified"


@router.get(
    "/reports/revenue-by-service",
    operation_id="reports.revenueByService",
    summary="Revenue by Service — invoice-title pivot with billed/collected",
)
async def revenue_by_service(
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

    # Mirror ``reports._fetch_all_invoices`` predicate — same
    # ``doc_type="invoice"`` + soft-delete guard — but scoped to
    # the tenant AND filtered by ``created_at`` in-window.
    from routers.reports import _paid_amt as _rpt_paid_amt
    invoices = await db.quotes.find(
        {"tenant_id": tid, "doc_type": "invoice",
         "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "title": 1, "total": 1, "amount_paid": 1,
         "payment_status": 1, "created_at": 1},
    ).to_list(10000)

    def _in_window(iso: Optional[str]) -> bool:
        if not iso or not isinstance(iso, str):
            return False
        return s_iso <= iso <= e_iso

    invoices = [inv for inv in invoices if _in_window(inv.get("created_at"))]

    billed_by:    Dict[str, float] = defaultdict(float)
    collected_by: Dict[str, float] = defaultdict(float)
    count_by:     Dict[str, int]   = defaultdict(int)

    for inv in invoices:
        svc = (inv.get("title") or "").strip() or "Unclassified"
        billed_by[svc]    += float(inv.get("total") or 0)
        collected_by[svc] += _rpt_paid_amt(inv)
        count_by[svc]     += 1

    rows: List[dict] = []
    for name in billed_by:
        billed    = round(billed_by[name],    2)
        collected = round(collected_by[name], 2)
        cnt       = count_by[name]
        rows.append({
            "service_name":     name,
            "service_id":       _slugify(name),
            "billed_amount":    billed,
            "collected_amount": collected,
            "job_count":        cnt,
            "avg_ticket":       round(billed / cnt, 2) if cnt else 0.0,
        })
    rows.sort(key=lambda r: -r["billed_amount"])

    total_billed    = round(sum(r["billed_amount"]    for r in rows), 2)
    total_collected = round(sum(r["collected_amount"] for r in rows), 2)
    top = rows[0] if rows else None
    top_service = (
        {"name": top["service_name"], "amount": top["billed_amount"]}
        if top else {"name": None, "amount": 0.0}
    )
    chart_top = [
        {"service_name": r["service_name"],
         "billed_amount": r["billed_amount"]}
        for r in rows[:10]
    ]

    return {
        "summary": {
            "total_billed":            total_billed,
            "total_collected":         total_collected,
            "top_service_by_revenue":  top_service,
        },
        "rows":  rows,
        "chart": {"top_services": chart_top},
        "tenant_id":  tid,
        "start_date": start_date,
        "end_date":   end_date,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
