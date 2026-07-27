"""Task SS · Feb 2026 — Admin-facing customer service credit endpoints.

Sits on top of the existing Phase 10 credits infrastructure
(``services/credits_apply.py`` + ``customers.credits_balance_cents``
+ inline ``customers.credits_ledger`` list). Adds:

* ``POST /api/customers/{cid}/credits`` — admin issues a credit
  (positive amount) OR a deduction (negative amount). Positive
  values credit the customer; negative values pull from the
  balance. A negative that would push the balance below zero is
  refused with 422 unless ``force_negative: true`` is set AND the
  caller is ``super_admin``.
* ``GET /api/customers/{cid}/credits`` — full ledger history
  (most-recent first) plus the current balance.
* ``POST /api/customers/{cid}/credits/{entry_id}/reverse`` — spins
  up a reversal entry with the opposite sign of the target entry,
  linking back via ``reverted_from_entry_id``. Idempotent per
  entry via the ``already_reverted`` guard.

Every mutation writes an audit row to ``ai_tool_calls``-adjacent
``credit_admin_audit`` collection for staff traceability.

Preview safety
--------------
* Endpoints refuse to touch a customer that isn't in the caller's
  tenant.
* Amount is capped at ± $100,000 per single admin issuance to
  catch obvious typos. The cap is intentionally loose — an admin
  can chain calls for larger corrections; the guard exists to
  prevent a stray zero from wrecking a balance in one keystroke.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter(tags=["Customer Credits (admin)"])

_KIND_VALUES = {"admin_manual", "invoice_refund", "reversal",
                     "auto_applied", "referral_reward", "other"}
_HARD_CAP_CENTS = 100_000 * 100        # ± $100,000


class CreditIssueIn(BaseModel):
    amount_cents: int = Field(..., description="Positive to add, negative to deduct.")
    kind: str = Field("admin_manual")
    note: str = Field(..., min_length=5, max_length=500)
    force_negative: bool = Field(
        False,
        description="Super_admin-only: allow the balance to go below zero.",
    )


class CreditRow(BaseModel):
    id: str
    delta_cents: int
    source: str
    kind: Optional[str] = None
    note: Optional[str] = None
    invoice_id: Optional[str] = None
    created_at: str
    created_by_user_id: Optional[str] = None
    reverted_from_entry_id: Optional[str] = None
    reverted: Optional[bool] = None


class LedgerResponse(BaseModel):
    balance_cents: int
    items: List[CreditRow]


# ─── Helpers ─────────────────────────────────────────────────────
async def _load_customer(tenant_id: str, cid: str) -> dict:
    doc = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "tenant_id": 1, "name": 1,
          "credits_balance_cents": 1, "credits_ledger": 1},
    )
    if not doc:
        raise HTTPException(404, "Customer not found")
    return doc


async def _audit(row: dict) -> None:
    row["created_at"] = row.get("created_at") or now_iso()
    try:
        await db.credit_admin_audit.insert_one(row)
    except Exception as exc:                                        # noqa: BLE001
        logger.warning("credit_admin_audit insert failed: %s", exc)


# ─── Endpoints ───────────────────────────────────────────────────
@router.get("/customers/{cid}/credits")
async def list_customer_credits(
    cid: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> LedgerResponse:
    doc = await _load_customer(tenant["id"], cid)
    items = list(doc.get("credits_ledger") or [])
    items.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return LedgerResponse(
        balance_cents=int(doc.get("credits_balance_cents") or 0),
        items=[CreditRow(**{k: v for k, v in row.items()
                                     if k in CreditRow.model_fields})
                  for row in items],
    )


@router.post("/customers/{cid}/credits", status_code=201)
async def issue_customer_credit(
    cid: str, body: CreditIssueIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if body.kind not in _KIND_VALUES:
        raise HTTPException(422, f"invalid kind — must be one of {sorted(_KIND_VALUES)}")
    amount = int(body.amount_cents)
    if amount == 0:
        raise HTTPException(422, "amount_cents must be non-zero")
    if abs(amount) > _HARD_CAP_CENTS:
        raise HTTPException(
            422, f"amount_cents ±{_HARD_CAP_CENTS} cap exceeded — "
                    "chain multiple issuances if you really need this.",
        )
    doc = await _load_customer(tenant["id"], cid)
    current = int(doc.get("credits_balance_cents") or 0)
    new_balance = current + amount
    if new_balance < 0:
        # Negative would push balance under zero — require
        # super_admin + force_negative.
        if not body.force_negative:
            raise HTTPException(
                422,
                f"deduction would push balance to {new_balance} cents "
                "(below zero). Set force_negative=true (super_admin only) "
                "if this is a legitimate correction.",
            )
        if user.get("role") != "super_admin":
            raise HTTPException(
                403, "only super_admin can force a negative balance",
            )
    entry = {
        "id": new_id(),
        "delta_cents": amount,
        "source": "admin_issued" if amount > 0 else "admin_deducted",
        "kind": body.kind,
        "note": body.note,
        "created_at": now_iso(),
        "created_by_user_id": user.get("id"),
    }
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"credits_balance_cents": new_balance},
          "$push": {"credits_ledger": entry}},
    )
    await _audit({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "acting_user_id": user.get("id"),
        "acting_user_role": user.get("role"),
        "action": "issue",
        "entry_id": entry["id"],
        "amount_cents": amount,
        "kind": body.kind,
        "balance_before_cents": current,
        "balance_after_cents": new_balance,
        "note": body.note,
    })
    return {"entry": entry, "balance_cents": new_balance}


@router.post("/customers/{cid}/credits/{entry_id}/reverse", status_code=201)
async def reverse_customer_credit(
    cid: str, entry_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    doc = await _load_customer(tenant["id"], cid)
    ledger = list(doc.get("credits_ledger") or [])
    target = next((e for e in ledger if e.get("id") == entry_id), None)
    if not target:
        raise HTTPException(404, "credit entry not found")
    if target.get("reverted"):
        raise HTTPException(409, "entry already reverted")
    if (target.get("source") or "").startswith("revert"):
        raise HTTPException(422, "cannot reverse a reversal entry")
    reversal_delta = -int(target.get("delta_cents") or 0)
    current = int(doc.get("credits_balance_cents") or 0)
    new_balance = current + reversal_delta
    if new_balance < 0 and user.get("role") != "super_admin":
        raise HTTPException(
            422,
            f"reversal would push balance to {new_balance} cents. "
            "Only super_admin can reverse into the negative.",
        )
    reversal = {
        "id": new_id(),
        "delta_cents": reversal_delta,
        "source": "revert",
        "kind": "reversal",
        "reverted_from_entry_id": entry_id,
        "note": f"Reversal of entry {entry_id}",
        "created_at": now_iso(),
        "created_by_user_id": user.get("id"),
    }
    # Mark the original entry reverted in-place + push the reversal.
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"],
          "credits_ledger.id": entry_id},
        {"$set": {"credits_balance_cents": new_balance,
                    "credits_ledger.$.reverted": True,
                    "credits_ledger.$.reverted_at": now_iso()}},
    )
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$push": {"credits_ledger": reversal}},
    )
    await _audit({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "acting_user_id": user.get("id"),
        "acting_user_role": user.get("role"),
        "action": "reverse",
        "entry_id": entry_id,
        "reversal_entry_id": reversal["id"],
        "amount_cents": reversal_delta,
        "balance_before_cents": current,
        "balance_after_cents": new_balance,
    })
    return {"entry": reversal, "balance_cents": new_balance}
