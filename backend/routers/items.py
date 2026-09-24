from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
# Bucket A2 · Feb-2026 — explicit model imports (was ``from models import *``).
from models import ItemIn
# Backlog #iii · Feb-2026 — rich suppliers[] validator + mirror rebuild.
from services.pricebook.cost import rebuild_mirrors

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# Backlog #iii · Feb-2026 — Rich multi-supplier subdoc validator.
#
# Validates the shape locked in models.ItemIn.suppliers[]. Rules:
#   1. ``supplier_name`` required + non-blank, ≤ 120 chars.
#   2. ``unit_cost``      optional; when set must be numeric ≥ 0.
#   3. ``supplier_sku`` / ``unit_size`` / ``notes`` optional strings.
#   4. ``id`` auto-stamped when missing (UUID).
#   5. ``last_updated`` auto-stamped when missing (ISO-8601 now).
#   6. Dedup on lower-cased ``supplier_name`` — the ``suppliers[]``
#      list is a set-by-name. Duplicate names → 400 friendly detail.
# ═══════════════════════════════════════════════════════════════════════
def _validate_suppliers(suppliers) -> List[dict]:
    if not suppliers:
        return []
    if not isinstance(suppliers, list):
        raise HTTPException(400, {"error": "suppliers_must_be_list"})
    seen: set = set()
    out: List[dict] = []
    default_last = now_iso()
    for row in suppliers:
        if not isinstance(row, dict):
            raise HTTPException(400, {"error": "supplier_row_must_be_object"})
        name = str(row.get("supplier_name") or "").strip()
        if not name:
            raise HTTPException(400, {
                "error": "supplier_name_required",
                "message": "Every supplier row needs a supplier_name",
            })
        if len(name) > 120:
            raise HTTPException(400, {
                "error": "supplier_name_too_long",
                "supplier_name": name[:120],
            })
        key = name.lower()
        if key in seen:
            raise HTTPException(400, {
                "error": "duplicate_supplier_name",
                "supplier_name": name,
            })
        seen.add(key)
        cost = row.get("unit_cost")
        if cost in (None, ""):
            cost_f = None
        else:
            try:
                cost_f = float(cost)
            except (TypeError, ValueError) as e:
                raise HTTPException(422, {
                    "error": "invalid_unit_cost",
                    "supplier_name": name,
                }) from e
            if cost_f < 0:
                raise HTTPException(422, {
                    "error": "invalid_unit_cost",
                    "supplier_name": name,
                    "message": "unit_cost must be ≥ 0",
                })
            cost_f = round(cost_f, 2)
        out.append({
            "id": str(row.get("id") or new_id()),
            "supplier_name": name,
            "supplier_sku": str(row.get("supplier_sku") or ""),
            "unit_cost": cost_f,
            "unit_size": str(row.get("unit_size") or ""),
            "last_updated": str(row.get("last_updated") or default_last),
            "notes": str(row.get("notes") or ""),
        })
    return out


# ----------------------- Price Book -----------------------
@router.get("/items")
async def list_items(user: dict = Depends(require_admin)):
    # BUG B fix (Feb-2026) — filter out soft-deleted rows.
    return await db.items.find(
        {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ).sort("name", 1).to_list(1000)


@router.post("/items")
async def create_item(body: ItemIn, user: dict = Depends(require_admin)):
    doc = body.dict()
    # Feb-2026 · Pricebook item_type — services carry NO supplier /
    # cost data. If the caller passes any such fields on a service
    # write, reject with 400 (fail-loud is nicer to the UI than a
    # silent scrub).
    item_type = (doc.get("item_type") or "product").lower()
    if item_type not in ("product", "service"):
        raise HTTPException(400, "item_type must be 'product' or 'service'")
    doc["item_type"] = item_type
    if item_type == "service":
        _SUPPLIER_FIELDS = ("supplier_prices", "supplier_id",
                             "wholesale_price", "labor_cost_default",
                             "income_category_id", "external_sku")
        offending = [f for f in _SUPPLIER_FIELDS
                     if doc.get(f) not in (None, [], "", 0, 0.0)]
        if offending:
            raise HTTPException(400, {
                "error": "services_cannot_have_supplier_pricing",
                "message": "services cannot have supplier pricing",
                "fields": offending,
            })
        # Safety-net scrub — force null so downstream reports don't
        # see stale supplier state on a service row.
        for f in _SUPPLIER_FIELDS:
            if f == "supplier_prices":
                doc[f] = []
            else:
                doc[f] = None
    # Feb-2026 · Service category enforcement on pricebook write.
    from routers.service_categories import (
        validate_service_category,
        resolve_chemicals_service_category_id,
    )
    tenant_id = user.get("tenant_id") or ""
    # Feb-2026 · Backlog #1 Part 2 — auto-stamp "Chemicals" service
    # category on pricebook items whose Taxonomy-A type is chemical
    # when the caller omitted ``service_category_id``. Respects an
    # explicit override — only fills the blank, never rewrites.
    item_type_cat = (doc.get("category") or "").strip().lower()
    if not doc.get("service_category_id") and item_type_cat == "chemical":
        chem_svc_id = await resolve_chemicals_service_category_id(tenant_id)
        if chem_svc_id:
            doc["service_category_id"] = chem_svc_id
    await validate_service_category(tenant_id, doc.get("service_category_id"))
    # Phase 56-b · Aug-2026 — Multi-supplier pricing validation.
    # (No-op for services — supplier_prices was scrubbed to [] above.)
    doc["supplier_prices"] = await _validate_supplier_prices(
        tenant_id, doc.get("income_category_id"), doc.get("supplier_prices"),
    )
    # Backlog #iii · Feb-2026 — Rich suppliers[] validation + mirror
    # regeneration. Services still have suppliers=[] scrubbed above.
    doc["suppliers"] = _validate_suppliers(doc.get("suppliers"))
    mirrors = rebuild_mirrors({"suppliers": doc["suppliers"]})
    if mirrors:
        # Overwrite the compact mirror + wholesale_price scalar so
        # downstream grandfathered consumers keep working.
        doc.update(mirrors)
    doc.update({"id": new_id(), "created_at": now_iso()})
    if tenant_id:
        doc["tenant_id"] = tenant_id
    await db.items.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _soft_delete_item(iid: str, actor_id: Optional[str], tenant_id: str) -> dict:
    # P57 · Feb-2026 — signature tightened (Commit 2). ``tenant_id``
    # is now positional-required and MUST be a non-empty string.
    # ``None`` and empty-string both raise ValueError at call time
    # so a future caller that forgets to propagate tenant scope
    # fails loudly instead of silently running cross-tenant (which
    # is what the pre-P57 optional-tenant + truthy-guard shape
    # allowed — see H7 flag in the P56 PRD section for the attack
    # narrative). Any future legitimate cross-tenant delete path
    # (migration / superadmin cleanup) MUST introduce its own
    # helper with an explicit name — do NOT relax this guard.
    if not tenant_id or not str(tenant_id).strip():
        raise ValueError(
            "_soft_delete_item requires a non-empty tenant_id; "
            f"got {tenant_id!r}. If you need a legitimate cross-"
            "tenant delete path, introduce a separate helper — "
            "do NOT relax this guard."
        )
    q: dict = {"id": iid, "tenant_id": tenant_id}
    row = await db.items.find_one(q, {"_id": 0})
    if not row:
        raise HTTPException(404, "Item not found")
    if row.get("deleted_at"):
        return {"ok": True, "id": iid, "already_deleted": True}
    # Phase 34 · Task KK · locked-state — refuse hard delete if the
    # item is referenced by an active invoice / estimate / autobilling
    # plan in the tenant. Deactivate is still allowed via PATCH.
    linked = 0
    try:
        for coll, key in [("quotes", "line_items.item_id"),
                            ("estimates", "line_items.item_id"),
                            ("billing_plans", "item_id")]:
            linked += await db[coll].count_documents({
                key: iid,
                "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
            })
            if linked:
                break
    except Exception:                                            # noqa: BLE001
        pass
    if linked:
        raise HTTPException(
            409,
            f"Item is used on {linked} active document(s) — deactivate via PATCH instead of deleting",
        )
    # P57 · Feb-2026 — internal write filter is unconditionally
    # tenant-scoped now that the signature guarantees a real
    # tenant_id. Defence in depth against a paid-transition-style
    # race between find_one + update_one.
    await db.items.update_one(
        {"id": iid, "tenant_id": tenant_id},
        {"$set": {"deleted_at": now_iso(),
                    "deleted_by_user_id": actor_id}},
    )
    return {"ok": True, "id": iid, "soft_deleted": True}


class ItemPatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    tax_rate: Optional[float] = None
    description: Optional[str] = None
    active: Optional[bool] = None
    sku: Optional[str] = None
    # Feb-2026 · Pricebook item_type patch. Flipping product → service
    # scrubs supplier fields to null. Flipping service → product
    # leaves them null (admin must repopulate).
    item_type: Optional[str] = None
    # Feb-2026 · Service category — patchable, validated below.
    service_category_id: Optional[str] = None
    # Feb-2026 · PB1 · Internal-only cost fields.
    #   ``wholesale_price``     — supplier cost per unit (COGS).
    #   ``labor_cost_default``  — labor cost per unit; used as the
    #                             per-line snapshot default when the
    #                             item is added to a new quote / invoice.
    # Both admin-gated and NEVER surfaced on customer-facing views.
    wholesale_price: Optional[float] = None
    labor_cost_default: Optional[float] = None
    # Phase 56-b · Aug-2026 — Multi-supplier pricing patch.
    income_category_id: Optional[str] = None
    supplier_prices: Optional[List[dict]] = None
    # Backlog #iii · Feb-2026 — Rich multi-supplier subdoc.
    suppliers: Optional[List[dict]] = None


# ═════════════════════════════════════════════════════════════════════════
# Phase 56-b · Aug-2026 — Multi-supplier pricing validators.
#
# Rules (locked in preflight §4):
#   1. Every ``supplier_prices[i].supplier_slug`` must reference a
#      non-deleted row in ``db.pricebook_suppliers`` on this tenant.
#      Unknown slugs → 400 ``unknown_supplier``.
#   2. Every supplier's ``income_category_id`` must equal the item's
#      ``income_category_id``. Mismatch → 400
#      ``supplier_income_category_mismatch``.
#   3. Empty ``supplier_prices=[]`` is legal (item has no prices).
#   4. Duplicates on the same slug → 400 ``duplicate_supplier_slug``
#      (defensive — prevents shadow-row bugs downstream).
#   5. ``cost_cents`` must be an int ≥ 0.
#
# Soft-deleted suppliers are IGNORED at validation time on WRITES —
# they'd be a mismatch (deleted row can't match a category). But
# EXISTING supplier_prices on an item are preserved on READS even if
# the supplier is later soft-deleted; the frontend renders a
# "(deleted supplier)" pill.
# ═════════════════════════════════════════════════════════════════════════
async def _validate_supplier_prices(
    tenant_id: str,
    income_category_id: Optional[str],
    supplier_prices: Optional[List[dict]],
) -> List[dict]:
    """Return a normalized list of ``{supplier_slug, cost_cents}`` docs
    or raise HTTPException(400) with a friendly ``detail`` payload."""
    if not supplier_prices:
        return []
    if not income_category_id:
        # Silent guard — items without an income_category cannot carry
        # supplier_prices. Reject early with a friendly detail rather
        # than half-persisting.
        raise HTTPException(400, {
            "error": "supplier_prices_without_income_category",
            "message": ("supplier_prices requires income_category_id "
                         "to be set on the item"),
        })

    seen: set = set()
    out: List[dict] = []
    for row in supplier_prices:
        slug = str((row or {}).get("supplier_slug") or "").strip().lower()
        if not slug:
            raise HTTPException(400, {"error": "invalid_supplier_slug",
                                        "message": "supplier_slug required"})
        if slug in seen:
            raise HTTPException(400, {"error": "duplicate_supplier_slug",
                                        "supplier_slug": slug})
        seen.add(slug)
        try:
            cents = int((row or {}).get("cost_cents") or 0)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, {"error": "invalid_cost_cents",
                                        "supplier_slug": slug}) from e
        if cents < 0:
            raise HTTPException(422, {"error": "invalid_cost_cents",
                                        "supplier_slug": slug,
                                        "message": "cost_cents must be ≥ 0"})

        sup = await db.pricebook_suppliers.find_one(
            {"tenant_id": tenant_id, "slug": slug,
              "deleted_at": {"$in": [None, ""]}},
            {"_id": 0, "slug": 1, "income_category_id": 1},
        )
        if not sup:
            raise HTTPException(400, {"error": "unknown_supplier",
                                        "supplier_slug": slug})
        if sup.get("income_category_id") != income_category_id:
            # Look up the expected category name to make the friendly
            # detail actionable (matches preflight lock).
            cat = await db.income_categories.find_one(
                {"tenant_id": tenant_id, "id": sup["income_category_id"]},
                {"_id": 0, "name": 1},
            ) or {}
            raise HTTPException(400, {
                "error": "supplier_income_category_mismatch",
                "supplier_slug": slug,
                "expected_category": cat.get("name") or sup["income_category_id"],
            })
        out.append({"supplier_slug": slug, "cost_cents": cents})
    return out


@router.patch("/items/{iid}", operation_id="pricebook.patch")
async def patch_item(iid: str, body: ItemPatch,
                       user: dict = Depends(require_admin)):
    """Phase 34 · Task KK · Feb 2026 — partial update of a pricebook
    item. Validates numeric ranges (unit_price ≥ 0, cost ≥ 0,
    tax_rate 0-100). Emits an ``audit_log`` row with the changed
    field set for later auditing."""
    row = await db.items.find_one({"id": iid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Item not found")
    if row.get("deleted_at"):
        raise HTTPException(409, "Item is archived — restore it first")
    upd = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not upd:
        raise HTTPException(400, "No fields to update")
    if "unit_price" in upd and upd["unit_price"] < 0:
        raise HTTPException(422, "unit_price must be ≥ 0")
    if "tax_rate" in upd and (upd["tax_rate"] < 0 or upd["tax_rate"] > 100):
        raise HTTPException(422, "tax_rate must be between 0 and 100")
    # PB1 · Feb-2026 — wholesale + labor cost validation.
    if "wholesale_price" in upd:
        try:
            wp = float(upd["wholesale_price"])
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "wholesale_price must be numeric") from e
        if wp < 0:
            raise HTTPException(422, "wholesale_price must be ≥ 0")
        upd["wholesale_price"] = wp
    if "labor_cost_default" in upd:
        try:
            lc = float(upd["labor_cost_default"])
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "labor_cost_default must be numeric") from e
        if lc < 0:
            raise HTTPException(422, "labor_cost_default must be ≥ 0")
        upd["labor_cost_default"] = lc
    # Feb-2026 · Service category — if the patch touches it, validate.
    if "service_category_id" in upd:
        from routers.service_categories import validate_service_category
        await validate_service_category(row.get("tenant_id") or user.get("tenant_id") or "",
                                          upd["service_category_id"])
    # Feb-2026 · item_type patch. Compute the effective type after
    # the patch applies, then reject any supplier field on a service.
    effective_type = (
        (upd.get("item_type") or row.get("item_type") or "product").lower()
    )
    if "item_type" in upd and effective_type not in ("product", "service"):
        raise HTTPException(400, "item_type must be 'product' or 'service'")
    upd["item_type"] = effective_type
    if effective_type == "service":
        _SUPPLIER_FIELDS = ("supplier_prices", "supplier_id",
                             "wholesale_price", "labor_cost_default",
                             "income_category_id", "external_sku")
        offending = [f for f in _SUPPLIER_FIELDS
                     if upd.get(f) not in (None, [], "", 0, 0.0)]
        if offending:
            raise HTTPException(400, {
                "error": "services_cannot_have_supplier_pricing",
                "message": "services cannot have supplier pricing",
                "fields": offending,
            })
        # Flipping product → service scrubs whatever supplier state
        # was on the row.
        for f in _SUPPLIER_FIELDS:
            if f == "supplier_prices":
                upd[f] = []
            else:
                upd[f] = None
    # Phase 56-b · Aug-2026 — Multi-supplier pricing patch validation.
    # If the caller sends supplier_prices, validate against the
    # income_category the item is (or is becoming) attached to. If
    # the patch also flips income_category_id, use the NEW value —
    # otherwise fall back to the row's existing value.
    if "supplier_prices" in upd:
        effective_cat = upd.get("income_category_id",
                                  row.get("income_category_id"))
        upd["supplier_prices"] = await _validate_supplier_prices(
            row.get("tenant_id") or user.get("tenant_id") or "",
            effective_cat, upd["supplier_prices"],
        )
    # Backlog #iii · Feb-2026 — Rich suppliers[] validation + mirror
    # rebuild. When the patch supplies ``suppliers``, we validate,
    # then regenerate the two compat mirrors (``wholesale_price``
    # scalar + ``supplier_prices[]`` compact) from the new rich shape
    # so downstream grandfathered readers stay in sync. If the caller
    # omits ``suppliers`` we do NOT touch either mirror — legacy
    # manual-pricing writes on ``supplier_prices[]`` round-trip.
    if "suppliers" in upd and effective_type != "service":
        upd["suppliers"] = _validate_suppliers(upd["suppliers"])
        mirrors = rebuild_mirrors({"suppliers": upd["suppliers"]})
        for k, v in mirrors.items():
            # Only overwrite when the mirror function returned a value.
            # Empty suppliers[] leaves mirrors alone.
            upd[k] = v
        # Empty-suppliers guardrail is enforced client-side (R4);
        # server allows the write regardless — historical snapshots
        # are immutable, so empty suppliers[] never affects them.
    upd["updated_at"] = now_iso()
    upd["updated_by_user_id"] = user.get("id")
    await db.items.update_one({"id": iid}, {"$set": upd})
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "pricebook.patch",
            "target_id": iid,
            "changed_fields": sorted(upd.keys()),
            "at": now_iso(),
        })
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"pricebook.patch audit failed: {e}")
    return await db.items.find_one({"id": iid}, {"_id": 0})


@router.delete("/items/{iid}")
async def delete_item(iid: str, user: dict = Depends(require_admin)):
    # BUG B fix — switched from hard delete to soft delete so history
    # rows (invoices/quotes referencing the item) stay intact.
    # P57 · Feb-2026 — pass tenant_id so cross-tenant deletes hit
    # the not-found branch. Before P57 a tenant-A admin could delete
    # a tenant-B item just by knowing (or brute-forcing) its uuid;
    # this call omitted the 3rd positional and _soft_delete_item's
    # optional-tenant guard silently ran cross-tenant.
    return await _soft_delete_item(iid, user.get("id"), user.get("tenant_id"))


# Alias per the Item 8 spec — same collection, different URL surface.
@router.delete("/pricebook/{iid}",
                operation_id="pricebook.delete")
async def delete_pricebook_item(iid: str, user: dict = Depends(require_admin)):
    # P57 · Feb-2026 — same fix as the sibling ``/items/{iid}``
    # DELETE above. Both endpoints route to _soft_delete_item and
    # both were pre-P57 cross-tenant vulnerable.
    return await _soft_delete_item(iid, user.get("id"), user.get("tenant_id"))


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task KK · Feb 2026 — Pricebook bulk soft-delete + Task EE
# query_selector filter shape. Same admin gate / 400-cap / audit rows.
# Locked-state: items referenced by active invoices/estimates/autobilling
# plans return in ``failed[]`` with a friendly reason.
# ═════════════════════════════════════════════════════════════════════════


class _PricebookBulkDeleteIn(BaseModel):
    ids: Optional[List[str]] = None
    query_selector: Optional[dict] = None
    exclude_ids: Optional[List[str]] = None


_PRICEBOOK_BULK_CAP = 400
_PRICEBOOK_SELECTOR_KEYS = {"category", "search", "active"}


async def _resolve_pricebook_ids(selector: dict, exclude: List[str], tenant_id: str) -> List[str]:
    # P57 · Feb-2026 — signature tightened (Commit 2). Sibling of
    # ``_soft_delete_item``'s tightening: helper that feeds the
    # primitive must enforce the same non-empty-tenant_id
    # invariant, otherwise the "make the wrong thing hard"
    # guarantee only lives on the leaf function. A future caller
    # that enumerates via this helper without tenant scope is now
    # a call-time ValueError, not a silent cross-tenant read.
    if not tenant_id or not str(tenant_id).strip():
        raise ValueError(
            "_resolve_pricebook_ids requires a non-empty "
            f"tenant_id; got {tenant_id!r}."
        )
    q: dict = {
        "tenant_id": tenant_id,
        "$or": [{"deleted_at": None},
                 {"deleted_at": {"$exists": False}}],
    }
    clean = {k: v for k, v in (selector or {}).items()
              if k in _PRICEBOOK_SELECTOR_KEYS}
    if clean.get("category"):
        q["category"] = clean["category"]
    if clean.get("active") is not None:
        q["active"] = bool(clean["active"])
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q["name"] = {"$regex": s, "$options": "i"}
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db.items.find(q, {"_id": 0, "id": 1}).limit(_PRICEBOOK_BULK_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


@router.post("/pricebook/bulk-delete",
              operation_id="pricebook.bulkDelete")
async def bulk_delete_pricebook(body: _PricebookBulkDeleteIn,
                                  user: dict = Depends(require_admin)):
    # P57 · Feb-2026 — bulk-delete now propagates tenant_id both
    # into the selector-based entry query AND every per-row
    # _soft_delete_item call. Pre-P57 both layers ran unscoped;
    # this call site was the original H7 flag surfaced during
    # the P56 grep pass.
    _tenant_id = user.get("tenant_id")
    if body.query_selector is not None:
        ids = await _resolve_pricebook_ids(
            body.query_selector, body.exclude_ids or [], _tenant_id,
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _PRICEBOOK_BULK_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_PRICEBOOK_BULK_CAP} rows per call")
    # Idempotency guard — collapse duplicate ids in the payload.
    ids = list(dict.fromkeys(ids))
    deleted: List[str] = []
    failed: List[dict] = []
    for iid in ids:
        try:
            r = await _soft_delete_item(iid, user.get("id"), _tenant_id)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": iid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                    # noqa: BLE001
            failed.append({"id": iid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# P56 · Feb-2026 — Pricebook Bulk-Update-Categories (P55 sync consumer).
#
# NOTE — Sibling ``bulk_delete_pricebook`` shape diverged materially
# from the P54/P55-consumer pattern (see P56 grep-pass Q1). We
# INTENTIONALLY do NOT mirror it here: the P54 shape wins for
# cross-file P55-consumer consistency. Namely:
#
#   * Request payload: bare ``ids`` list (no ``query_selector`` /
#     ``exclude_ids`` — the frontend already knows its checked-row
#     ids; the selector shape is a bulk-delete-only affordance).
#   * Batch cap: new in-file constant (100), matches the P54 cap
#     and reflects the P55 fan-out cost per row (each row fires
#     ``sync_pricebook_to_invoice_lines`` which touches every
#     linked unpaid invoice).
#   * Response: ``{updated, already_current, failed,
#     sync_result_summary, results: [{id, status, error?}]}`` —
#     same as ``bulk_activate_recurring`` / P54.
#   * Validation: inline HTTP 422 pattern with
#     ``{code, field, attempted, collection}`` (Q2/A · cross-file
#     P55-consumer consistency). NOT the ``validate_service_category``
#     HTTP 400 shape that the single-item PATCH still uses — the
#     PATCH's contract is preserved unchanged; only the new bulk
#     endpoint uses the 422 shape.
#   * Tenant scoping: explicit ``user.get("tenant_id")`` filter on
#     the per-row ``find_one`` (Q6/yes). Sibling bulk-delete's
#     pre-existing tenant-isolation gap is documented in the P56
#     PRD § "Pre-existing security defect flagged during P56 grep"
#     for a future dispatch (recommend name: P57 · Pricebook
#     bulk-delete tenant isolation).
# ═════════════════════════════════════════════════════════════════════════


class _PricebookBulkUpdateCategoriesIn(BaseModel):
    """P56 · Feb-2026 — Bulk category-edit payload for pricebook.

    Both category fields are ``Optional`` at the type level.
    Semantics for each field use Pydantic v2 ``model_fields_set``
    to distinguish JSON-absent from JSON-null:

      * field NOT in ``model_fields_set`` (JSON key absent)   → unchanged
      * field present with a non-empty string value           → validate + apply
      * field present with ``None`` or an empty string        → unchanged
    """
    ids: List[str]
    service_category_id: Optional[str] = None
    income_category_id: Optional[str] = None


# Batch cap for the P56 bulk endpoint. Kept adjacent to
# ``_PRICEBOOK_BULK_CAP`` so the per-endpoint constant pattern used
# by ``items.py`` is preserved. The 100 ceiling matches the P54
# cap and reflects the P55 fan-out cost per row (each bulk-update-
# categories row fires ``sync_pricebook_to_invoice_lines`` which
# walks every linked unpaid invoice for that item).
_PRICEBOOK_BULK_UPDATE_CATEGORIES_MAX = 100


@router.post("/pricebook/bulk-update-categories",
              operation_id="pricebook.bulkUpdateCategories")
async def bulk_update_categories_pricebook(
    body: _PricebookBulkUpdateCategoriesIn,
    user: dict = Depends(require_admin),
):
    """Phase P56 · Feb-2026 — Bulk-edit service + income category
    across many Pricebook items in one call. Consumes the P55
    ``sync_pricebook_to_invoice_lines`` orchestrator per updated
    row so every linked unpaid invoice line item picks up the new
    taxonomy id.

    Per-id status (mirrors P54 / bulk_activate_recurring
    honest-telemetry):
      * ``updated``          — every touched category field
        differed from the on-disk value; the write landed; the
        P55 sync fan-out fired successfully.
      * ``already_current``  — every incoming field already matched
        the on-disk value. Idempotent no-op: no write, no sync,
        no audit row.
      * ``failed``           — item not found under caller's tenant
        (out-of-tenant + typo + soft-deleted all land here), OR
        service item received an ``income_category_id`` (rejected
        per the item.py :367-378 single-item PATCH rule), OR the
        P55 sync raised ``CategorySyncNameLookupError``, OR a
        generic sync exception. Row's ``error`` field carries the
        specific string.

    Rejects with 400:
      * ``ids_empty`` when ``len(ids) == 0`` (post-dedupe).
      * ``batch_too_large`` when ``len(ids) > 100``.
      * ``no_category_fields_set`` when neither category field
        resolves to a non-empty value.

    Rejects with 422 (payload-level, before the per-row loop
    starts — mirrors P54 · Q2/A cross-file P55-consumer contract):
      * ``<field>_too_long`` when the id string is > 80 chars.
      * ``<field>_no_html`` when the id string contains ``<`` /
        ``>``.
      * ``service_category_invalid`` / ``income_category_invalid``
        when the id doesn't resolve to an active row on the
        caller's tenant. Payload: ``{code, field, attempted,
        collection}``.

    Response envelope (identical to P54 for cross-file P55-
    consumer consistency):
      ``{"updated": int, "already_current": int, "failed": int,
         "sync_result_summary": {"child_invoices_updated": int,
                                  "child_invoices_skipped_paid": int,
                                  "child_invoices_skipped_loop": int,
                                  "child_error_rows": int},
         "results": [{"id", "status", "error"?}]}``
    """
    tenant_id = (user.get("tenant_id") or "") or ""

    # Normalize + dedupe.
    ids_seen: set = set()
    ordered_ids: List[str] = []
    for iid in body.ids:
        if iid and iid not in ids_seen:
            ids_seen.add(iid)
            ordered_ids.append(iid)
    if not ordered_ids:
        raise HTTPException(400, {"error": "ids_empty"})
    if len(ordered_ids) > _PRICEBOOK_BULK_UPDATE_CATEGORIES_MAX:
        logger.warning(
            "[pricebook.bulk_update_categories.batch_too_large] "
            "tenant=%s received=%d cap=%d",
            tenant_id, len(ordered_ids),
            _PRICEBOOK_BULK_UPDATE_CATEGORIES_MAX,
        )
        raise HTTPException(400, {
            "error": "batch_too_large",
            "max": _PRICEBOOK_BULK_UPDATE_CATEGORIES_MAX,
            "received": len(ordered_ids),
        })

    # Pydantic v2 — distinguish JSON-absent from JSON-null.
    _sent_fields = body.model_fields_set

    _CATEGORY_KEYS = {
        "income_category_id": "income_categories",
        "service_category_id": "service_categories",
    }
    # Resolve up-front — mirrors the P54 endpoint's payload-level
    # rejection so the caller sees a 422 before the loop starts,
    # not deep into a partially-applied batch.
    resolved_by_field: dict = {}
    for _field, _coll in _CATEGORY_KEYS.items():
        if _field not in _sent_fields:
            continue
        _val = getattr(body, _field)
        if _val is None:
            continue
        _val = str(_val).strip()
        if not _val:
            continue
        if len(_val) > 80:
            raise HTTPException(
                422, {"error": f"{_field}_too_long", "max_len": 80},
            )
        if "<" in _val or ">" in _val:
            raise HTTPException(
                422, {"error": f"{_field}_no_html"},
            )
        _cat = await db[_coll].find_one(
            {"id": _val, "tenant_id": tenant_id,
              "is_archived": {"$ne": True}},
            {"_id": 0, "id": 1, "name": 1},
        )
        if not _cat:
            _code = ("service_category_invalid"
                     if _field == "service_category_id"
                     else "income_category_invalid")
            raise HTTPException(
                422,
                {"code": _code, "field": _field,
                  "attempted": _val, "collection": _coll},
            )
        resolved_by_field[_field] = _cat

    if not resolved_by_field:
        raise HTTPException(
            400, {"error": "no_category_fields_set",
                    "hint": ("at least one of ``service_category_id`` "
                            "or ``income_category_id`` must be "
                            "present with a non-empty value")},
        )

    # Import once — the P56 fan-out uses the new P55 direction
    # ``sync_pricebook_to_invoice_lines``. Origin marker
    # ``bulk_pricebook_edit`` is grep-verified NOT in
    # ``_SKIP_TABLE`` (guarded by
    # ``test_bulk_pricebook_edit_origin_not_in_skip_set``).
    from services.category_sync import (
        sync_pricebook_to_invoice_lines,
        CategorySyncNameLookupError,
    )

    updated_count = 0
    already_current_count = 0
    failed_count = 0
    child_updated = 0
    child_paid_skipped = 0
    child_loop_skipped = 0
    child_error_rows = 0
    results: List[dict] = []

    for iid in ordered_ids:
        item = await db.items.find_one(
            # Q6/yes — explicit tenant scope on the read filter.
            # Also excludes soft-deleted rows so a bulk edit on a
            # stale UI never re-touches an archived item.
            {"id": iid, "tenant_id": tenant_id,
              "$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
            {"_id": 0, "id": 1, "item_type": 1,
              "income_category_id": 1, "income_category_name": 1,
              "service_category_id": 1, "service_category_name": 1,
              "category": 1},
        )
        if not item:
            failed_count += 1
            results.append({
                "id": iid, "status": "failed", "error": "not_found",
            })
            continue

        # Q5/A — service items reject income_category_id per the
        # single-item PATCH rule at items.py :367-378. Honest
        # per-row telemetry: this row fails, the batch continues.
        effective_type = (
            (item.get("item_type") or "product").lower()
        )
        if (effective_type == "service"
                and "income_category_id" in resolved_by_field):
            failed_count += 1
            results.append({
                "id": iid, "status": "failed",
                "error": "services_cannot_have_income_category_id",
            })
            continue

        # Build the write set — idempotency guard: only include
        # fields whose resolved target differs from the current
        # on-disk value. Denorm name stays in lockstep with the id.
        # Legacy ``category`` scalar keeps lockstep with the modern
        # income_category_id (Q2 · P55 lockstep contract).
        updates: dict = {}
        for _field, _cat in resolved_by_field.items():
            _denorm = _field.replace("_id", "_name")
            if item.get(_field) != _cat["id"]:
                updates[_field] = _cat["id"]
            if item.get(_denorm) != _cat.get("name"):
                updates[_denorm] = _cat.get("name")
            if _field == "income_category_id":
                # Keep legacy scalar in lockstep.
                if item.get("category") != _cat["id"]:
                    updates["category"] = _cat["id"]

        if not updates:
            already_current_count += 1
            results.append({"id": iid, "status": "already_current"})
            continue

        updates["updated_at"] = now_iso()
        updates["updated_by_user_id"] = user.get("id")
        try:
            r = await db.items.update_one(
                {"id": iid, "tenant_id": tenant_id},
                {"$set": updates},
            )
        except Exception as _upd_exc:                             # noqa: BLE001
            failed_count += 1
            results.append({
                "id": iid, "status": "failed",
                "error": f"update_failed: {_upd_exc}",
            })
            continue

        if r.matched_count == 0:
            # Race — item deleted between find_one + update_one.
            failed_count += 1
            results.append({
                "id": iid, "status": "failed", "error": "not_found",
            })
            continue

        # Audit — mirror the sibling patch_item audit shape
        # (event ``pricebook.patch``, actor_user_id / actor_email,
        # target_id, changed_fields, at). Distinct collection
        # (``audit_log`` singular) from the recurring path's
        # ``audit_logs`` — kept orthogonal per audit-ledger
        # consumer contract. Fail-open on audit failure.
        try:
            await db.audit_log.insert_one({
                "id": new_id(),
                "actor_user_id": user.get("id"),
                "actor_email": user.get("email"),
                "action": "pricebook.patch",
                "target_id": iid,
                "changed_fields": sorted(updates.keys()),
                "at": now_iso(),
            })
        except Exception as _aud_exc:                              # noqa: BLE001
            logger.warning(
                "[pricebook.bulk_update_categories.audit] "
                "failed target=%s error=%s", iid, _aud_exc,
            )

        # P55 fan-out. Origin ``bulk_pricebook_edit`` — grep-
        # verified NOT in ``_SKIP_TABLE`` (test guard in the P56
        # backend suite). Fail-open below: the item's own write
        # already landed, so a sync failure classifies the row as
        # per-row failed (partial-apply state — same semantics as
        # P54).
        _sync_kwargs: dict = {"origin": "bulk_pricebook_edit"}
        if "income_category_id" in updates:
            _sync_kwargs["income_category_id"] = (
                updates["income_category_id"]
            )
        if "service_category_id" in updates:
            _sync_kwargs["service_category_id"] = (
                updates["service_category_id"]
            )
        try:
            _sync_result = await sync_pricebook_to_invoice_lines(
                tenant_id=tenant_id, item_id=iid,
                actor_id=user.get("id"),
                **_sync_kwargs,
            )
            child_updated += _sync_result.updated_count
            child_paid_skipped += _sync_result.skipped_paid_count
            child_loop_skipped += _sync_result.skipped_loop_count
            child_error_rows += len(_sync_result.errors_by_id)
        except CategorySyncNameLookupError as _cs_exc:
            failed_count += 1
            results.append({
                "id": iid, "status": "failed",
                "error": ("category_deleted_after_source_write "
                            f"({_cs_exc.category_id})"),
            })
            continue
        except Exception as _cs_exc:                             # noqa: BLE001
            logger.warning(
                "[category_sync.bulk_pricebook_edit.failed] "
                "item=%s error=%s", iid, _cs_exc,
            )
            failed_count += 1
            results.append({
                "id": iid, "status": "failed",
                "error": f"sync_failed: {_cs_exc}",
            })
            continue

        updated_count += 1
        results.append({"id": iid, "status": "updated"})

    return {
        "updated": updated_count,
        "already_current": already_current_count,
        "failed": failed_count,
        "sync_result_summary": {
            "child_invoices_updated": child_updated,
            "child_invoices_skipped_paid": child_paid_skipped,
            "child_invoices_skipped_loop": child_loop_skipped,
            "child_error_rows": child_error_rows,
        },
        "results": results,
    }

