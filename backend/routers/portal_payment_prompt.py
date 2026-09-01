"""Phase K11 · Feb-2026 — Portal payment-method prompt evaluator.

Two portal-only endpoints:

  * ``GET  /portal/payment-method/prompt-status``  — returns
    ``{prompt_kind, expiring_cards, snoozed_until}`` for the current
    customer.  Never hits Stripe — reads the local
    ``payment_methods`` mirror the CRM already keeps in sync.

  * ``POST /portal/payment-method/prompt-snooze`` — 24-hour snooze
    of the MODAL for the given ``kind`` (``missing`` | ``expiring``).
    Banner still renders during the snooze window — matches the
    "1-day snooze, banner persists" spec.

Design notes
------------
* **Cards only.**  ACH mirror rows carry ``type != "card"`` and are
  ignored by K11 (per the spec's non-goal).
* **Expiring window: 30 days.**  Calendar-day arithmetic.  A card
  with ``(exp_year=2026, exp_month=10)`` counts as expiring on
  2026-09-10 (start-of-month semantics — a card is "expired" the
  first day of the month after its ``exp_month``).
* **Impersonation interlock.**  Snoozes fired by an impersonation
  JWT (``user.is_impersonated == True``) are still recorded but
  never affect the real customer's status.  We stamp the row with
  ``via_impersonation=true`` + ``acting_admin_id`` (K13 shape) so
  the audit trail is complete, and the ``prompt-status`` reader
  filters snooze rows to ``via_impersonation != true`` when serving
  a NON-impersonated session (i.e. the real customer's login).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso


router = APIRouter()


_EXPIRING_WINDOW_DAYS = 30
_SNOOZE_HOURS = 24


def _require_customer(user: dict) -> str:
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    return user["customer_id"]


def _first_of_next_month(exp_year: int, exp_month: int) -> date:
    """A card with exp_month = M / exp_year = Y is technically valid
    through the LAST day of that month; treat expiry as the first
    day of month M+1 for the "days until" calc."""
    year = int(exp_year)
    month = int(exp_month)
    if month == 12:
        year += 1
        month = 1
    else:
        month += 1
    return date(year, month, 1)


def _days_until_expiry(exp_year: Any, exp_month: Any) -> Optional[int]:
    try:
        exp_year = int(exp_year)
        exp_month = int(exp_month)
    except (TypeError, ValueError):
        return None
    today = datetime.now(timezone.utc).date()
    exp_date = _first_of_next_month(exp_year, exp_month)
    return (exp_date - today).days


def _card_row_summary(row: Dict[str, Any], days: int) -> Dict[str, Any]:
    return {
        "payment_method_id": row.get("provider_payment_method_id")
            or row.get("id"),
        "brand": row.get("brand") or "",
        "last4": row.get("last4") or "",
        "exp_month": row.get("exp_month"),
        "exp_year": row.get("exp_year"),
        "days_until_expiry": days,
    }


async def _load_active_cards(tenant_id: str,
                              customer_id: str) -> List[Dict[str, Any]]:
    """Cards-only, non-deleted mirror rows."""
    cursor = db.payment_methods.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
         "provider": "stripe",
         "$or": [{"type": "card"}, {"type": {"$exists": False}}],
         "deleted_at": {"$in": [None, False]},
        },
        {"_id": 0},
    )
    return [row async for row in cursor]


async def _read_snooze(customer_id: str,
                        prompt_kind: str,
                        impersonated: bool) -> Optional[Dict[str, Any]]:
    """Only NON-impersonated snoozes count against a real customer's
    modal.  When the current session IS impersonated we look for the
    admin's own recent snooze so the acting admin doesn't get spammed
    inside the same session either, but we scope it to their
    impersonator_id to keep customers isolated (see docstring)."""
    q: Dict[str, Any] = {"customer_id": customer_id, "kind": prompt_kind,
                          "expires_at": {"$gt": now_iso()}}
    if impersonated:
        q["via_impersonation"] = True
    else:
        q["via_impersonation"] = {"$ne": True}
    return await db.payment_prompt_snoozes.find_one(q, {"_id": 0},
                                                      sort=[("expires_at", -1)])


@router.get("/portal/payment-method/prompt-status")
async def prompt_status(user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    rows = await _load_active_cards(tenant["id"], cid)
    impersonated = bool(user.get("is_impersonated"))

    expiring: List[Dict[str, Any]] = []
    for row in rows:
        d = _days_until_expiry(row.get("exp_year"), row.get("exp_month"))
        if d is None:
            continue
        if d <= _EXPIRING_WINDOW_DAYS:
            expiring.append(_card_row_summary(row, d))

    if not rows:
        original_kind = "missing"
    elif expiring:
        original_kind = "expiring"
    else:
        original_kind = "none"

    if original_kind == "none":
        return {"prompt_kind": "none", "expiring_cards": [],
                 "snoozed_until": None,
                 "is_impersonated": impersonated}

    snooze = await _read_snooze(cid, original_kind, impersonated)
    if snooze:
        return {"prompt_kind": "none",
                 "expiring_cards": [] if original_kind == "missing"
                     else expiring,
                 "snoozed_until": snooze.get("expires_at"),
                 "original_prompt_kind": original_kind,
                 "is_impersonated": impersonated}

    return {"prompt_kind": original_kind,
             "expiring_cards": expiring if original_kind == "expiring" else [],
             "snoozed_until": None,
             "is_impersonated": impersonated}


class SnoozeBody(BaseModel):
    kind: str


@router.post("/portal/payment-method/prompt-snooze")
async def prompt_snooze(body: SnoozeBody,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    kind = (body.kind or "").lower().strip()
    if kind not in ("missing", "expiring"):
        raise HTTPException(422, "kind must be 'missing' or 'expiring'")
    impersonated = bool(user.get("is_impersonated"))
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=_SNOOZE_HOURS)).isoformat()
    doc: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "kind": kind,
        "snoozed_at": now.isoformat(),
        "expires_at": expires_at,
    }
    if impersonated:
        # K13 interlock — never lets an admin silence the real
        # customer's prompt on their next login.
        doc["via_impersonation"] = True
        doc["acting_admin_id"] = user.get("impersonator_id")
    await db.payment_prompt_snoozes.insert_one(doc)
    return {"snoozed_until": expires_at, "kind": kind,
             "via_impersonation": impersonated}
