"""Feb-2026 · Payments Summary tile.

Endpoint::

    GET /api/payments/summary

Re-implementation of the older ``payments.py`` router (retired during
the Feb-2026 Lumino experiment). Data now flows through the
Phase 47d Stripe restoration + ``db.quotes`` invoice rows —
``paid_from_intents`` / ``refunded_from_intents`` are the current
source of truth. The Admin Dashboard + InvoicesList expect this
endpoint. Aggregates directly from ``db.quotes`` where
``doc_type == 'invoice'`` (the canonical invoice collection).

Auth
----
* admin, super_admin, manager  → 200
* technician, customer, anon    → 403

Response
--------
::

    {
      "month_label":          "Feb 2026",
      "collected_this_month": <float USD>,
      "outstanding_total":    <float USD>,
      "outstanding_count":    <int>,
      "overdue": [
        { "id", "invoice_number", "customer_id", "customer_name",
          "total", "balance", "due_date", "status" }, ...
      ],
    }

Definitions
-----------
* **collected_this_month** — sum of ``amount_paid`` on non-deleted
  invoices whose ``paid_at`` falls in the current UTC calendar month
  (OR in the explicit ``[date_from, date_to]`` window when the
  TD-93 range params are set).
* **outstanding_total / _count** — non-deleted invoices with a positive
  balance (``total - amount_paid > 0``) and a "live" status
  (``sent``, ``accepted``, ``past_due``). Draft + paid excluded.
  When the TD-93 range params are set, additionally restricted to
  invoices whose ``date_field`` ∈ ``[date_from, date_to]`` (filter
  by invoice-date OR due-date-in-range with the current status
  gate intact — NOT a point-in-time balance-as-of-to
  reconstruction).
* **overdue** — subset of outstanding with ``status == 'past_due'``,
  most recent first, capped at 20 rows (dashboard slices to 4).

TD-93 · Feb-2026 — ``date_from`` / ``date_to`` / ``date_field``
params extend the three server-side stats so the Invoices page
can light up the "Collected in range" / "Outstanding (in range)"
/ "Overdue count (in range)" tiles under an operator-selected
window.  Aging buckets remain client-side (``InvoicesList.jsx``
derives them from the list rows and auto-reactivates with any
filter).  ``date_field`` whitelist: ``created_at`` (default) +
``due_date``; same enum as ``routers/quotes.py::list_quotes``.
Collected uses ``paid_at`` regardless of ``date_field`` (per audit
§6 — Collected is semantically about money-arrived, not
invoice-dated).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user

router = APIRouter()

_ALLOWED_ROLES = {"admin", "super_admin", "manager"}
_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
# TD-estimate-to-invoice-conversion-doctype-and-balance · Feb-2026 —
# Fix C. ``_LIVE_STATUSES`` previously omitted ``"issued"`` even though
# the canonical ``services/reporting/paid_date.py::OUTSTANDING_STATUS_FILTER``
# includes it, AND the native ``services/auto_invoice.py:253`` write
# path stamps ``status="issued"`` on job-complete auto-invoices. The
# drift meant every ``issued`` invoice was invisible to the
# ``/api/payments/summary`` Outstanding tile. Aligning the two
# filters surfaces real AR + fixes the operator-reported
# convert-to-invoice bug (converted rows now also carry
# ``status="issued"`` per the Fix B change in ``invoice_builder.py``).
_LIVE_STATUSES = {"issued", "sent", "accepted", "past_due"}
# TD-93 · Feb-2026 — same whitelist as
# ``routers/quotes.py::_LIST_QUOTES_DATE_FIELD_VALUES``.  Kept
# duplicated (not imported) so the summary endpoint has no
# cross-router import and can be unit-tested in isolation.
_SUMMARY_DATE_FIELD_VALUES = frozenset(["created_at", "due_date"])


def _month_label(dt: datetime) -> str:
    return f"{_MONTH_LABELS[dt.month - 1]} {dt.year}"


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _num(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


@router.get("/payments/summary", operation_id="payments.summary")
async def payments_summary(user: Dict[str, Any] = Depends(get_current_user),
                            # TD-93 · Feb-2026 — optional date-range
                            # params so the Invoices page can scope
                            # Collected / Outstanding / Overdue
                            # tiles to an operator-selected window.
                            # ``date_field`` enum: ``created_at``
                            # (default) | ``due_date``.  Semantics
                            # per audit §6 — Collected uses
                            # ``paid_at`` regardless of
                            # ``date_field``; Outstanding + Overdue
                            # use ``date_field`` with the current
                            # status gate intact (NOT a point-in-time
                            # balance-as-of-to reconstruction, which
                            # is a Reports surface).
                            date_from: Optional[str] = Query(None),
                            date_to: Optional[str] = Query(None),
                            date_field: Optional[str] = Query(None)):
    role = (user or {}).get("role") or ""
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, {"error": "forbidden"})

    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    # TD-21 coercion for direct-call tests (same pattern as
    # ``routers/quotes.py::list_quotes``).
    if not isinstance(date_from, str):
        date_from = None
    if not isinstance(date_to, str):
        date_to = None
    if not isinstance(date_field, str):
        date_field = None

    # TD-93 · Feb-2026 — validate ``date_field`` whitelist.  Falls
    # back to ``created_at`` when any range param is set and
    # ``date_field`` is omitted.
    _range_active = bool(date_from or date_to)
    _df = date_field or ("created_at" if _range_active else None)
    if _df is not None and _df not in _SUMMARY_DATE_FIELD_VALUES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_date_field",
                "message": (
                    "date_field must be one of "
                    f"{sorted(_SUMMARY_DATE_FIELD_VALUES)!r}, "
                    f"got {date_field!r}"
                ),
                "accepted_values": sorted(_SUMMARY_DATE_FIELD_VALUES),
            },
        )

    now_dt = datetime.now(timezone.utc)
    month_start = datetime(now_dt.year, now_dt.month, 1, tzinfo=timezone.utc)

    # TD-93 · Feb-2026 — resolve the Collected ``paid_at`` window.
    # When the range is active, Collected uses the explicit
    # ``[date_from, date_to]`` bounds (as datetimes); otherwise it
    # falls back to the current UTC month.
    collected_lower: Optional[datetime] = None
    collected_upper: Optional[datetime] = None
    if _range_active:
        if date_from:
            try:
                collected_lower = datetime.fromisoformat(
                    f"{date_from}T00:00:00+00:00"
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "invalid_date_range",
                        "message": f"date_from must be YYYY-MM-DD, got {date_from!r}",
                    },
                )
        if date_to:
            try:
                collected_upper = datetime.fromisoformat(
                    f"{date_to}T23:59:59.999999+00:00"
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error_code": "invalid_date_range",
                        "message": f"date_to must be YYYY-MM-DD, got {date_to!r}",
                    },
                )

    projection = {
        "_id": 0, "id": 1, "invoice_number": 1, "customer_id": 1,
        "customer_name": 1, "total": 1, "amount_paid": 1, "paid_at": 1,
        "due_date": 1, "status": 1, "deleted_at": 1, "doc_type": 1,
        "created_at": 1,
    }

    collected = 0.0
    outstanding_total = 0.0
    outstanding_count = 0
    overdue: List[Dict[str, Any]] = []

    async for inv in db.quotes.find(
        {"tenant_id": tenant_id, "doc_type": "invoice"},
        projection,
    ):
        if inv.get("deleted_at"):
            continue

        total = _num(inv.get("total"))
        paid = _num(inv.get("amount_paid"))
        balance = round(total - paid, 2)
        status = (inv.get("status") or "").lower()

        # ── Collected ──────────────────────────────────────────────
        paid_dt = _parse_iso(inv.get("paid_at"))
        if _range_active:
            # Range window — bounds are optional (open-ended range OK).
            if paid_dt is not None:
                lower_ok = (collected_lower is None
                            or paid_dt >= collected_lower)
                upper_ok = (collected_upper is None
                            or paid_dt <= collected_upper)
                if lower_ok and upper_ok:
                    collected += paid
        else:
            if paid_dt and paid_dt >= month_start:
                collected += paid

        # ── Outstanding + Overdue ──────────────────────────────────
        # TD-93 range filter: when active, only count invoices whose
        # ``date_field`` ∈ [from, to].  ``created_at`` uses full-day
        # expanded bounds; ``due_date`` lex-compares the raw
        # YYYY-MM-DD string.
        _in_date_range = True
        if _range_active:
            if _df == "created_at":
                _created = _parse_iso(inv.get("created_at"))
                if _created is None:
                    _in_date_range = False
                else:
                    if collected_lower is not None and _created < collected_lower:
                        _in_date_range = False
                    if collected_upper is not None and _created > collected_upper:
                        _in_date_range = False
            else:
                # ``due_date`` branch — raw YYYY-MM-DD lex-compare.
                _dd = inv.get("due_date")
                if not _dd or not isinstance(_dd, str):
                    _in_date_range = False
                else:
                    if date_from is not None and _dd < date_from:
                        _in_date_range = False
                    if date_to is not None and _dd > date_to:
                        _in_date_range = False

        if balance > 0 and status in _LIVE_STATUSES and _in_date_range:
            outstanding_total += balance
            outstanding_count += 1
            if status == "past_due":
                overdue.append({
                    "id": inv.get("id"),
                    "invoice_number": inv.get("invoice_number"),
                    "customer_id": inv.get("customer_id"),
                    "customer_name": inv.get("customer_name") or "",
                    "total": round(total, 2),
                    "balance": balance,
                    "due_date": inv.get("due_date"),
                    "status": status,
                })

    # Most-past-due first — sort by due_date ascending, missing dates last.
    overdue.sort(key=lambda r: r.get("due_date") or "9999")
    overdue = overdue[:20]

    return {
        "month_label": _month_label(now_dt),
        "collected_this_month": round(collected, 2),
        "outstanding_total": round(outstanding_total, 2),
        "outstanding_count": int(outstanding_count),
        "overdue": overdue,
        # TD-93 · Feb-2026 — echo the resolved range so the FE can
        # pick dynamic labels ("Collected in range" vs "Collected
        # this month") without re-deriving from the request state.
        "range_active": _range_active,
        "date_field": _df,
    }
