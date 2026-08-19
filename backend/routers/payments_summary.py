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
  invoices whose ``paid_at`` falls in the current UTC calendar month.
* **outstanding_total / _count** — non-deleted invoices with a positive
  balance (``total - amount_paid > 0``) and a "live" status
  (``sent``, ``accepted``, ``past_due``). Draft + paid excluded.
* **overdue** — subset of outstanding with ``status == 'past_due'``,
  most recent first, capped at 20 rows (dashboard slices to 4).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import get_current_user

router = APIRouter()

_ALLOWED_ROLES = {"admin", "super_admin", "manager"}
_MONTH_LABELS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
_LIVE_STATUSES = {"sent", "accepted", "past_due"}


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
async def payments_summary(user: Dict[str, Any] = Depends(get_current_user)):
    role = (user or {}).get("role") or ""
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, {"error": "forbidden"})

    tenant_id = (user or {}).get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    now_dt = datetime.now(timezone.utc)
    month_start = datetime(now_dt.year, now_dt.month, 1, tzinfo=timezone.utc)

    projection = {
        "_id": 0, "id": 1, "invoice_number": 1, "customer_id": 1,
        "customer_name": 1, "total": 1, "amount_paid": 1, "paid_at": 1,
        "due_date": 1, "status": 1, "deleted_at": 1, "doc_type": 1,
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

        paid_dt = _parse_iso(inv.get("paid_at"))
        if paid_dt and paid_dt >= month_start:
            collected += paid

        if balance > 0 and status in _LIVE_STATUSES:
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
    }
