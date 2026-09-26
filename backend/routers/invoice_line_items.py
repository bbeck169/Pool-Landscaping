"""MA0 · Feb-2026 — Discrete race-safe line-item append endpoint.

Prereq for MA1 (MARCO backend) whose ``handle_add_line_item`` calls
this endpoint to add a single line item without needing to
resend the entire ``line_items`` array (the pre-MA0 shape of
``PATCH /quotes/{id}`` at ``invoice_edit.py``).

Race-safety strategy
────────────────────
Two techs adding items simultaneously on the same invoice — both
pushes MUST land in order without either being lost. The pre-MA0
PATCH replaces the entire array via ``$set``, which loses one
writer's row under concurrent send. MA0 fixes this:

  1. ``$push`` the new row into ``line_items`` — atomic per doc,
     both concurrent writers succeed, order preserved by the
     server's arrival order.
  2. Re-read the doc post-push to get the final ``line_items``
     array.
  3. Recompute totals (subtotal / tax / discount_value / total /
     remaining_balance) via the shared ``_compute_totals`` helper
     from ``invoice_edit.py``.
  4. ``$set`` the recomputed totals + ``updated_at``.

Between steps 3 and 4 a third concurrent writer could land its
own push + recompute; the LAST writer's totals will be correct
against whatever ``line_items`` array is durably present. Line
items are never lost.

Auth: ``require_tech_or_above`` (matches C-series precedent).
Tenant scope: cross-tenant invoice_id → 404 (never leaks
existence — differs from 403 by design, since 403 tells the
attacker the ID exists in another tenant).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from routers.pool_calculators import require_tech_or_above
from routers.tenants import get_current_tenant
from routers.invoice_edit import _compute_totals
from utils import now_iso


router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Request model
# ═══════════════════════════════════════════════════════════════════
class LineItemAddBody(BaseModel):
    item_id: str = Field(..., description="Pricebook item id (db.items.id).")
    quantity: float = Field(..., ge=0, description="Numeric quantity (>= 0).")
    unit_price: Optional[float] = Field(
        None, description="Server accepts an override; otherwise falls back "
                          "to the pricebook item's ``price`` field.",
    )
    description: Optional[str] = Field(
        None, description="Server accepts an override; otherwise falls back "
                          "to the pricebook item's ``name`` field.",
    )


# ═══════════════════════════════════════════════════════════════════
# Endpoint
# ═══════════════════════════════════════════════════════════════════
@router.post("/invoices/{invoice_id}/line-items")
async def add_line_item(
    invoice_id: str,
    body: LineItemAddBody = Body(...),
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
):
    """Append a single line item to an invoice.

    Reads the item from ``db.items`` (tenant-scoped, active-only).
    Composes the row with the item's default ``name`` / ``price``
    unless the caller passed overrides in the body. Persists via
    atomic ``$push`` so concurrent adds never lose data.

    Returns the updated invoice doc (``line_items`` + refreshed
    totals) so the caller can display it without an extra fetch.
    """
    tenant_id = tenant["id"]

    # ── 1. Fetch the invoice (tenant-scoped) ──────────────────
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    if not inv:
        # Cross-tenant probes get 404, not 403 — never leak that the
        # ID exists in another tenant.
        raise HTTPException(status_code=404, detail="invoice_not_found")

    # ── 2. Fetch the pricebook item (tenant-scoped, active) ───
    item = await db.items.find_one(
        {"id": body.item_id, "tenant_id": tenant_id, "deleted_at": None},
        {"_id": 0},
    )
    if not item:
        # Try the ``deleted_at not set`` variant too — legacy items
        # never carried the field. This is the P34/Task-KK pattern.
        item = await db.items.find_one(
            {"id": body.item_id, "tenant_id": tenant_id,
             "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
            {"_id": 0},
        )
    if not item:
        raise HTTPException(
            status_code=422,
            detail={"error": "item_not_found",
                     "message": f"Pricebook item {body.item_id!r} not found in this tenant."},
        )

    # ── 3. Compose the new row ────────────────────────────────
    description = body.description
    if description is None or not description.strip():
        description = (item.get("name") or "").strip()
    if not description:
        raise HTTPException(
            status_code=422,
            detail="Item has no name and no description override was provided.",
        )
    unit_price = body.unit_price
    if unit_price is None:
        upstream = item.get("price")
        try:
            unit_price = float(upstream) if upstream is not None else 0.0
        except (TypeError, ValueError):
            unit_price = 0.0
    quantity = float(body.quantity or 0)
    row: Dict[str, Any] = {
        "description": description.strip(),
        "quantity": quantity,
        "unit_price": float(unit_price),
        "item_id": body.item_id,
    }
    # Carry through the two K71 taxonomy keys if the item has them —
    # keeps the added row consistent with rows the web UI would
    # produce via ``PATCH /quotes/{id}``.
    for k in ("category", "service_category"):
        if item.get(k):
            row[k] = item[k]

    # ── 4. Atomic push ────────────────────────────────────────
    push_now = now_iso()
    res = await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"$push": {"line_items": row},
         "$set": {"updated_at": push_now}},
    )
    if res.matched_count == 0:
        # Race: invoice was deleted between the read and the push.
        raise HTTPException(status_code=404, detail="invoice_not_found")

    # ── 5. Re-read → recompute totals → write totals ──────────
    inv2 = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    line_items = inv2.get("line_items") or []
    tax_rate = inv2.get("tax_rate")
    discount_amount = inv2.get("discount_amount")
    discount_type = inv2.get("discount_type") or "fixed"
    totals = _compute_totals(
        line_items,
        float(tax_rate or 0),
        float(discount_amount or 0),
        discount_type,
    )
    amount_paid = float(inv2.get("amount_paid") or 0)
    totals_upd: Dict[str, Any] = {
        "subtotal": totals["subtotal"],
        "tax": totals["tax"],
        "total": totals["total"],
        "discount_value": totals["discount_value"],
        "remaining_balance": round(max(totals["total"] - amount_paid, 0.0), 2),
        "updated_at": now_iso(),
    }
    await db.quotes.update_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"$set": totals_upd},
    )

    # ── 6. Fetch final + return ───────────────────────────────
    final = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0},
    )
    return final or {}
