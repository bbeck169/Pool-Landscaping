"""Invoice edit · Feb-2026 — Admin-only PATCH endpoint with full audit
trail and Lumino re-fire on money-affecting changes.

Endpoints:
  • PATCH /api/quotes/{invoice_id}
  • GET   /api/quotes/{invoice_id}/edit-history

Invoices are stored in ``db.quotes`` (``doc_type == "invoice"``). Prior
to the Phase 11 (Feb-2026) refactor they could ALSO live in ``db.invoices``;
that ancillary collection is now retired. This router uses
``find_invoice_dual`` for backward compatibility but the shim now reads
only from ``db.quotes``.
and writes back to whichever collection the doc came from.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from services.invoice_lookup import find_invoice_dual
from utils import get_current_user

router = APIRouter()

# Money-affecting fields — changing any of these triggers Lumino
# link invalidation + re-fire.
_MONEY_FIELDS = {"line_items", "discount_amount", "discount_type",
                 "tax_rate", "currency"}

# Fields the audit-diff considers. Anything outside this set is
# silently ignored (defensive against random unknown keys in the body).
_EDITABLE_FIELDS = [
    "customer_id", "line_items", "discount_amount", "discount_type",
    "promo_code", "tax_rate", "due_date", "notes", "memo",
    "private_notes", "terms", "currency", "invoice_number",
    # K48 verify-hotfix · Feb-2026 — invoice-level Business Unit tag.
    # Money-NEUTRAL (subtotal / tax / total unchanged), so PATCH can
    # carry a BU-only payload without a ``line_items`` array.  Written
    # via ``$set`` alongside the paid/sent confirmation-flag flow.
    "business_unit",
    # INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID contract. The
    # dashboard drill-down modal writes the canonical ``business_unit_id``
    # FK alongside the denormalized ``business_unit`` name on every
    # Business Unit auto-save. Money-neutral; persisted via ``$set``.
    "business_unit_id",
]


class InvoiceEditBody(BaseModel):
    customer_id: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    discount_amount: Optional[float] = None
    discount_type: Optional[str] = None  # "percent" | "fixed"
    promo_code: Optional[str] = None
    tax_rate: Optional[float] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    memo: Optional[str] = None
    private_notes: Optional[str] = None
    terms: Optional[str] = None
    currency: Optional[str] = None
    invoice_number: Optional[str] = None
    # K48 verify-hotfix · Feb-2026 — invoice-level Business Unit tag
    # written by the Revenue-by-Category drill-down.  Money-neutral;
    # the router applies via ``$set`` and does NOT require a
    # ``line_items`` array to be resent.
    business_unit: Optional[str] = None
    # INCOME-DRILLDOWN-EDIT · Feb-2026 — paired-ID contract. Canonical
    # ``income_categories.id`` FK persisted alongside the denormalized
    # ``business_unit`` display name so the backend never has to
    # name-lookup on read. Money-neutral; ``$set`` write.
    business_unit_id: Optional[str] = None
    reason: Optional[str] = None
    confirm_edit_sent: Optional[bool] = None
    confirm_edit_paid_invoice_number: Optional[str] = None
    # Feb-2026 · Editable Sent Docs · Phase 1 — the frontend
    # confirm-dialog for ``sent`` / ``accepted`` / ``paid`` invoices
    # sets this to ``true``. When present, it acts as an alternative
    # authorization path to the legacy ``confirm_edit_sent`` and
    # ``confirm_edit_paid_invoice_number`` flags (both still honoured).
    acknowledged_lock_bypass: Optional[bool] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_staff(user: dict) -> None:
    role = (user or {}).get("role")
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


def _validate_line_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure each row has description + numeric quantity + numeric
    unit_price. Reject the whole batch on the first malformed row."""
    if not isinstance(items, list):
        raise HTTPException(400, "line_items must be a list")
    cleaned = []
    for i, li in enumerate(items):
        if not isinstance(li, dict):
            raise HTTPException(400, f"line_items[{i}] must be an object")
        desc = li.get("description")
        if not isinstance(desc, str) or not desc.strip():
            raise HTTPException(400, f"line_items[{i}].description required")
        try:
            qty = float(li.get("quantity"))
            price = float(li.get("unit_price"))
        except (TypeError, ValueError):
            raise HTTPException(400,
                                f"line_items[{i}].quantity/unit_price must be numeric")
        row = {"description": desc.strip(), "quantity": qty, "unit_price": price}
        if "tax_rate" in li and li["tax_rate"] is not None:
            try:
                row["tax_rate"] = float(li["tax_rate"])
            except (TypeError, ValueError):
                raise HTTPException(400,
                                    f"line_items[{i}].tax_rate must be numeric")
        # Phase K71 · Feb-2026 — long_description cap + K71 taxonomy
        # keys carried through untouched. Cap at 500 chars per spec.
        if "long_description" in li and li["long_description"] is not None:
            ld = li["long_description"]
            if not isinstance(ld, str):
                raise HTTPException(
                    400, f"line_items[{i}].long_description must be a string")
            if len(ld) > 500:
                raise HTTPException(
                    400,
                    f"line_items[{i}].long_description exceeds 500 characters"
                )
            row["long_description"] = ld
        # Preserve any extra client fields (e.g. item_id) untouched.
        for k, v in li.items():
            if k not in row and k not in ("description", "quantity",
                                            "unit_price", "tax_rate",
                                            "long_description"):
                row[k] = v
        cleaned.append(row)
    return cleaned


def _compute_totals(line_items: List[Dict[str, Any]],
                     tax_rate: float,
                     discount_amount: float,
                     discount_type: Optional[str]) -> Dict[str, float]:
    """Server-authoritative totals — never trust the client."""
    subtotal = sum((li.get("quantity") or 0) * (li.get("unit_price") or 0)
                   for li in (line_items or []))
    if discount_type == "percent":
        discount_value = subtotal * (float(discount_amount or 0) / 100.0)
    else:
        discount_value = float(discount_amount or 0)
    discounted_subtotal = max(subtotal - discount_value, 0.0)
    tax = round(discounted_subtotal * (float(tax_rate or 0) / 100.0), 2)
    total = round(discounted_subtotal + tax, 2)
    return {
        "subtotal": round(subtotal, 2),
        "discount_value": round(discount_value, 2),
        "tax": tax,
        "total": total,
    }


def _diff_fields(before: Dict[str, Any], after: Dict[str, Any],
                  fields: List[str]) -> Dict[str, Dict[str, Any]]:
    """Field-by-field before/after diff, only for fields that differ."""
    changed: Dict[str, Dict[str, Any]] = {}
    for f in fields:
        old = before.get(f)
        new = after.get(f)
        # Only record when the user actually set the field.
        if f not in after:
            continue
        if old != new:
            changed[f] = {"old": old, "new": new}
    return changed


async def _write_update(collection_name: str, invoice_id: str,
                         tenant_id: Optional[str],
                         upd: Dict[str, Any]) -> None:
    q = {"id": invoice_id}
    if tenant_id:
        q["tenant_id"] = tenant_id
    coll = db[collection_name]
    await coll.update_one(q, {"$set": upd})


async def _fetch_updated(collection_name: str,
                          invoice_id: str,
                          tenant_id: Optional[str]) -> Dict[str, Any]:
    q = {"id": invoice_id}
    if tenant_id:
        q["tenant_id"] = tenant_id
    return await db[collection_name].find_one(q, {"_id": 0}) or {}


@router.patch("/quotes/{invoice_id}")
async def patch_invoice(
    invoice_id: str,
    body: InvoiceEditBody = Body(...),
    user: dict = Depends(get_current_user),
):
    _require_staff(user)

    inv, collection = await find_invoice_dual(db, invoice_id)
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    status = (inv.get("status") or "").lower()

    # Feb-2026 · Editable Sent Docs · Phase 1 — confirm-dialog ack.
    _ack = bool(getattr(body, "acknowledged_lock_bypass", False))

    # ── Terminal statuses can never be edited ─────────────────────
    if status in ("void", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail={"error": "invoice_terminal", "status": status},
        )

    # ── Sent — requires acknowledgement ──────────────────────────
    #
    # Either the legacy ``confirm_edit_sent`` or the Phase 1
    # ``acknowledged_lock_bypass`` flag satisfies the guard.
    if status == "sent" and not (body.confirm_edit_sent or _ack):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "requires_confirmation",
                "warning": "This invoice was sent to the customer. "
                            "They may have already reviewed the old version.",
            },
        )

    # ── Accepted — requires acknowledgement (Phase 1) ────────────
    if status == "accepted" and not _ack:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "requires_confirmation",
                "warning": "This invoice was accepted by the customer. "
                            "Editing may create audit / bookkeeping issues.",
            },
        )

    # ── Paid — accepts EITHER typed invoice-number OR Phase 1 ack ─
    if status in ("paid", "partial"):
        if _ack:
            pass  # frontend confirm-dialog authorized the edit
        else:
            expected = inv.get("invoice_number") or ""
            submitted = body.confirm_edit_paid_invoice_number or ""
            if submitted != expected or not expected:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "paid_edit_requires_invoice_number",
                        "expected_invoice_number": expected,
                    },
                )

    # ── Extract & validate line_items early (before diff) ────────
    provided = body.dict(exclude_unset=True)
    if "line_items" in provided:
        provided["line_items"] = _validate_line_items(provided["line_items"])
        # Feb-2026 · Income category enforcement — every touched line
        # item must resolve to an active income_categories row.
        from routers.income_categories import validate_line_item_categories
        await validate_line_item_categories(inv.get("tenant_id") or "",
                                              provided["line_items"])
        # Phase K71 · Feb-2026 — Two-taxonomy validation for K71 line
        # items. Legacy items grandfathered (skipped when neither
        # K71 field is present).
        from routers.income_categories import validate_line_item_k71_categories
        await validate_line_item_k71_categories(
            inv.get("tenant_id") or "", provided["line_items"],
        )

    # ── Invoice number uniqueness within tenant ──────────────────
    tenant_id = inv.get("tenant_id")
    if "invoice_number" in provided:
        new_number = provided["invoice_number"]
        if new_number and new_number != inv.get("invoice_number"):
            # Phase 11 — single-collection scan; source of truth is quotes.
            conflict = None
            if tenant_id:
                conflict = await db.quotes.find_one(
                    {"tenant_id": tenant_id, "invoice_number": new_number,
                      "doc_type": "invoice", "id": {"$ne": invoice_id}},
                    {"_id": 0, "id": 1})
            else:
                conflict = await db.quotes.find_one(
                    {"invoice_number": new_number, "doc_type": "invoice",
                      "id": {"$ne": invoice_id}},
                    {"_id": 0, "id": 1})
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "invoice_number_conflict",
                            "field": "invoice_number"},
                )

    # ── Customer snapshot refresh (if customer_id changes) ───────
    customer_updates: Dict[str, Any] = {}
    if "customer_id" in provided:
        new_cid = provided["customer_id"]
        if new_cid and new_cid != inv.get("customer_id"):
            cust_q = {"id": new_cid}
            if tenant_id:
                cust_q["tenant_id"] = tenant_id
            cust = await db.customers.find_one(cust_q, {"_id": 0})
            if not cust:
                raise HTTPException(400, "customer_not_found")
            customer_updates = {
                "customer_id": new_cid,
                "customer_name": cust.get("name"),
                "customer_email": cust.get("email"),
                "customer_phone": cust.get("phone"),
            }

    # ── Build the "after" candidate ──────────────────────────────
    after = dict(inv)
    for k in _EDITABLE_FIELDS:
        if k in provided:
            after[k] = provided[k]
    after.update(customer_updates)

    # ── Diff before vs after for the audit log ───────────────────
    diff_fields = list(_EDITABLE_FIELDS)
    # Also record snapshot-refresh fields when customer changed.
    if customer_updates:
        for k in ("customer_name", "customer_email", "customer_phone"):
            if inv.get(k) != customer_updates.get(k):
                diff_fields.append(k)
    changed = _diff_fields(inv, after, diff_fields)

    # ── Recompute totals server-side if money touched ────────────
    money_changed = bool(_MONEY_FIELDS & set(changed.keys()))
    upd: Dict[str, Any] = {}
    for f in _EDITABLE_FIELDS:
        if f in provided:
            upd[f] = provided[f]
    upd.update(customer_updates)

    if money_changed or "line_items" in provided or "tax_rate" in provided \
       or "discount_amount" in provided or "discount_type" in provided:
        # Always recompute if any component fed into totals is being
        # touched, even if the user didn't change the effective value.
        items = provided.get("line_items", inv.get("line_items") or [])
        tax_rate = provided.get("tax_rate",
                                  inv.get("tax_rate") if inv.get("tax_rate") is not None else 0)
        discount_amount = provided.get(
            "discount_amount",
            inv.get("discount_amount") if inv.get("discount_amount") is not None else 0)
        discount_type = provided.get(
            "discount_type", inv.get("discount_type") or "fixed")
        totals = _compute_totals(items, float(tax_rate or 0),
                                  float(discount_amount or 0), discount_type)
        upd.update({
            "subtotal": totals["subtotal"],
            "tax": totals["tax"],
            "total": totals["total"],
            "discount_value": totals["discount_value"],
        })
        amount_paid = float(inv.get("amount_paid") or 0)
        upd["remaining_balance"] = round(max(totals["total"] - amount_paid, 0.0), 2)

    # ── No effective changes → early exit, no audit entry ────────
    if not changed:
        return {"ok": True, "changed": False, "invoice": inv}

    upd["updated_at"] = _now().isoformat()

    # ── Lumino side-effects on money-affecting edits ─────────────
    auto_effects: List[Dict[str, Any]] = []
    if money_changed and inv.get("lumino_payment_url"):
        upd["lumino_payment_url"] = None
        upd["lumino_payment_ref"] = None
        upd["lumino_link_created_at"] = None
        # Fire the Zap for a new link. Fail-open.
        try:
            from services.lumino_zapier_dispatcher import schedule_dispatch
            # Refresh customer for the payload (post-update view).
            cust: Dict[str, Any] = {}
            cid = customer_updates.get("customer_id") or inv.get("customer_id")
            if cid:
                cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
            if not cust:
                cust = {"id": cid,
                        "name": customer_updates.get("customer_name")
                                 or inv.get("customer_name"),
                        "email": customer_updates.get("customer_email")
                                  or inv.get("customer_email")}
            # Combine after-view with the update so the dispatcher sees
            # the fresh totals + cleared URL.
            fresh_inv = {**inv, **upd}
            correlation = uuid.uuid4().hex[:16]
            fresh_inv["_edit_correlation_id"] = correlation
            schedule_dispatch(fresh_inv, cust, base_return_url="")
            auto_effects.append({
                "kind": "lumino_link_cleared_and_refired",
                "correlation_id": correlation,
            })
        except Exception as exc:                                # noqa: BLE001
            logger.warning(
                "invoice_edit: lumino re-fire failed for %s: %s",
                invoice_id, type(exc).__name__,
            )
            auto_effects.append({
                "kind": "lumino_link_cleared_and_refire_failed",
                "error": type(exc).__name__,
            })

    # ── Persist the update ────────────────────────────────────────
    # Feb-2026 · Editable Sent Docs · Phase 1 — snapshot BEFORE the
    # write. Baseline is inserted inside the helper on first edit.
    # Best-effort; audit failure never breaks the parent write.
    from services.documents import (
        snapshot_before_mutation, invalidate_signature_if_present,
        has_signature,
    )
    _doc_type_for_version = ("invoice" if (inv.get("doc_type") == "invoice")
                              else "quote")
    _had_sig = await has_signature(doc_id=invoice_id, tenant_id=tenant_id)
    _content_fields_changing = any(
        k in provided for k in ("line_items", "tax_rate", "notes", "terms",
                                  "discount_amount", "due_date")
    )
    _sig_will_invalidate = _had_sig and _content_fields_changing
    await snapshot_before_mutation(
        doc_type=_doc_type_for_version, doc_id=invoice_id,
        tenant_id=tenant_id, current_doc=inv,
        # Feb-2026 · Phase 2 — merged post-mutation doc for the
        # write-time change_summary.
        new_doc={**inv, **upd},
        saved_by_user=user,
        status_at_edit=(status or "draft"),
        reason=body.reason, lock_bypass_ack=_ack,
        signature_invalidated=_sig_will_invalidate,
    )
    await _write_update(collection, invoice_id, tenant_id, upd)
    if _sig_will_invalidate:
        await invalidate_signature_if_present(
            doc_type=_doc_type_for_version, doc_id=invoice_id,
            tenant_id=tenant_id, collection=collection,
        )
        auto_effects.append({"kind": "signature_invalidated"})

    # ── Feb-2026 · Pricebook writeback fan-out (post-save) ────────
    if "line_items" in provided and any(
        li.get("pricebook_writeback") for li in provided["line_items"]
    ):
        try:
            from services.pricebook.writeback import process_pricebook_writebacks
            wb_result = await process_pricebook_writebacks(
                tenant_id=tenant_id or "",
                invoice_id=invoice_id,
                line_items=provided["line_items"],
                actor=user,
            )
            if wb_result.get("processed") or wb_result.get("errors"):
                logger.info(
                    "[pricebook_writeback] invoice=%s (patch) processed=%d "
                    "updated=%s created=%s warnings=%s errors=%s",
                    invoice_id, wb_result["processed"],
                    wb_result["updated"], wb_result["created"],
                    wb_result["warnings"], wb_result["errors"],
                )
        except Exception:                                        # noqa: BLE001
            logger.exception(
                "[pricebook_writeback] fan-out failed for invoice=%s (patch)",
                invoice_id,
            )

    # ── Persist the audit log entry ───────────────────────────────
    audit_doc = {
        "id": str(uuid.uuid4()),
        "invoice_id": invoice_id,
        "edited_at": _now(),
        "edited_by_user_id": user.get("id") or user.get("_id") or "",
        "edited_by_user_email": user.get("email") or "",
        "edited_by_role": user.get("role") or "",
        "invoice_status_at_edit": status or "draft",
        "changed_fields": changed,
        "auto_effects": auto_effects,
        "reason": body.reason,
        "tenant_id": tenant_id,
    }
    await db.invoice_edit_history.insert_one(dict(audit_doc))
    audit_doc.pop("_id", None)

    updated_full = await _fetch_updated(collection, invoice_id, tenant_id)

    return {
        "ok": True,
        "changed": True,
        "invoice": updated_full,
        "audit_id": audit_doc["id"],
    }


@router.get("/quotes/{invoice_id}/edit-history")
async def get_invoice_edit_history(
    invoice_id: str,
    user: dict = Depends(get_current_user),
):
    _require_staff(user)

    # Ensure the invoice exists (so a 404 vs 200-with-empty-array is
    # distinguishable — matches the rest of the API's shape).
    inv, _collection = await find_invoice_dual(db, invoice_id)
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    cursor = db.invoice_edit_history.find(
        {"invoice_id": invoice_id}, {"_id": 0},
    ).sort("edited_at", -1)
    rows = await cursor.to_list(500)
    # Normalize datetimes to ISO strings for the client.
    for r in rows:
        if isinstance(r.get("edited_at"), datetime):
            r["edited_at"] = r["edited_at"].isoformat()
    return {"items": rows, "total": len(rows)}
