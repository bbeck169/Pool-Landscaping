"""Phase 11 · Feb-2026 — Recurring labor cost prorating helper.

Separated from the CRUD router so ``services.finance.ebit.compute_ebit``
can call it without pulling the FastAPI router module (which would
drag the whole HTTP layer into the EBIT compute path).

``compute_recurring_labor_cost`` walks every ``active`` entry in
``db.recurring_labor_costs`` for the tenant whose
``[start_date, end_date OR +∞]`` range INTERSECTS the EBIT window
``[window_start, window_end]`` and prorates its ``monthly_amount``
against the overlap in average-month-days (365.25 / 12 = 30.4375).

Prorating math (per entry):

    overlap_start = max(entry.start_date,   window_start)
    overlap_end   = min(entry.end_date or ∞, window_end)
    overlap_days  = (overlap_end - overlap_start).days + 1   # inclusive
    months_in_window = overlap_days / 30.4375
    cost_in_window   = monthly_amount * months_in_window

Edges:
    * ``entry.start_date > window_end``  → no overlap, skipped.
    * ``entry.end_date   < window_start`` → no overlap, skipped.
    * ``status == "inactive"`` → always 0.0 contribution. Returned
      in ``by_entry`` ONLY if the inactive entry's range intersected
      the window (for audit visibility); never when disjoint.

Decimal discipline mirrors Phase 10 ``services.labor_cost``:
``monthly_amount`` stored as str/Decimal on the doc, parsed through
``Decimal(str(raw))``, quantised to 2 places on the response
boundary. ``months_in_window`` kept as a 4-place Decimal so the
proration survives multi-month windows without drift.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional


# Average month length. Matches the brief's spec: 365.25 / 12.
# Decimal, not float, so proration stays lossless across long
# windows.
_AVG_DAYS_PER_MONTH = Decimal("30.4375")

_MONEY_Q = Decimal("0.01")
_MONTHS_Q = Decimal("0.0001")   # 4 places — fine for proration


def _to_decimal(v: Any) -> Decimal:
    if v is None:
        return Decimal(0)
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _parse_iso_date(s: Any) -> Optional[date]:
    """Permissive ISO-date parse. Accepts ``YYYY-MM-DD`` or a full
    ISO datetime (we slice to the first 10 chars). ``None``/junk → None."""
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def _quantise_money(d: Decimal) -> float:
    return float(d.quantize(_MONEY_Q, rounding=ROUND_HALF_UP))


def _quantise_months(d: Decimal) -> float:
    return float(d.quantize(_MONTHS_Q, rounding=ROUND_HALF_UP))


async def compute_recurring_labor_cost(
    tenant_id: str,
    start_date: str,
    end_date: str,
    *,
    db=None,
) -> Dict[str, Any]:
    """Return the prorated recurring-labor cost for the window.

    Shape:

    .. code-block:: python

        {
          "by_entry": [
            {
              "id":               str,
              "label":            str,
              "monthly_amount":   float,     # 2 places
              "months_in_window": float,     # 4 places
              "cost_in_window":   float,     # 2 places
              "status":           str,       # "active" | "inactive"
              "linked_user_id":   Optional[str],
            }, ...
          ],
          "total": float,                     # 2 places
          "range": {"start": str, "end": str},
        }

    The ``total`` sums only ``active`` entries' ``cost_in_window``
    (inactive entries always contribute 0). ``by_entry`` is sorted
    descending by ``cost_in_window`` so the biggest line items land
    at the top of the admin UI.
    """
    if db is None:
        from config import db as _global_db
        db = _global_db

    w_start = _parse_iso_date(start_date)
    w_end = _parse_iso_date(end_date)
    if w_start is None or w_end is None or w_end < w_start:
        return {
            "by_entry": [],
            "total":    0.0,
            "range":    {"start": start_date, "end": end_date},
        }

    # NOTE: we DELIBERATELY do NOT filter by ``status`` at the Mongo
    # level — a historical inactive entry whose range intersects the
    # window still appears in ``by_entry`` (with cost 0) for audit
    # visibility. The ``status`` branch inside the loop handles the
    # cost sign.
    cursor = db.recurring_labor_costs.find(
        {"tenant_id": tenant_id,
         "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "label": 1, "monthly_amount": 1,
         "start_date": 1, "end_date": 1, "status": 1,
         "linked_user_id": 1},
    )

    by_entry = []
    total = Decimal(0)

    async for e in cursor:
        e_start = _parse_iso_date(e.get("start_date"))
        if e_start is None:
            continue
        e_end = _parse_iso_date(e.get("end_date"))  # None = +∞
        # Short-circuit no-overlap cases.
        if e_start > w_end:
            continue
        if e_end is not None and e_end < w_start:
            continue

        overlap_start = max(e_start, w_start)
        overlap_end = min(e_end, w_end) if e_end is not None else w_end
        overlap_days = (overlap_end - overlap_start).days + 1
        if overlap_days <= 0:
            # Defensive — the two short-circuits above should
            # prevent this but we keep the guard for safety.
            continue

        monthly = _to_decimal(e.get("monthly_amount"))
        months = Decimal(overlap_days) / _AVG_DAYS_PER_MONTH

        status = (e.get("status") or "active").lower()
        if status == "active":
            cost = monthly * months
            total += cost
        else:
            cost = Decimal(0)

        by_entry.append({
            "id":               e.get("id"),
            "label":            e.get("label") or "",
            "monthly_amount":   _quantise_money(monthly),
            "months_in_window": _quantise_months(months),
            "cost_in_window":   _quantise_money(cost),
            "status":           status,
            "linked_user_id":   e.get("linked_user_id"),
        })

    by_entry.sort(key=lambda r: r["cost_in_window"], reverse=True)

    return {
        "by_entry": by_entry,
        "total":    _quantise_money(total),
        "range":    {"start": start_date, "end": end_date},
    }
