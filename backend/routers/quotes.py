# ruff: noqa: F401
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
import re

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import get_current_tenant
from emailer import send_invoice_reminder_email, send_estimate_reminder_email
# Feb-2026 · P5 — wildcard ``from models import *`` replaced with the
# concrete set actually used below. ``Any / Dict`` come from typing
# (added to the typing import above); ``BaseModel`` / ``re`` are not
# referenced by this router.
from models import (
    MaintBulkIn,
    QuoteIn,
    QuoteUpdate,
    RecordPaymentIn,
)

router = APIRouter()


# ----------------------- Quotes / Invoices -----------------------
def compute_totals(line_items: List[dict], tax_rate: float):
    subtotal = sum(li["quantity"] * li["unit_price"] for li in line_items)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    return round(subtotal, 2), tax, round(subtotal + tax, 2)


# ── Feb-2026 · Pricebook item_type enforcement on line-items.
# ────────────────────────────────────────────────────────────────
# Every line item that references a pricebook row via ``item_id`` (or
# ``pricebook_item_id``) is checked against the referenced item's
# ``item_type``:
#   • ``product`` → ``unit_price`` MUST equal the pricebook value.
#     Any drift → 400 (product prices are locked).
#   • ``service`` → ``unit_price`` may differ. Whenever it differs
#     from the pricebook value we stamp ``overridden_price=True`` on
#     the line for downstream reporting.
# Legacy rows without ``item_type`` on the referenced item are
# treated as ``product`` (matches the "default all existing rows to
# product" migration policy).
async def _enforce_item_type_price_lock(tenant_id: str,
                                          line_items: List[dict]) -> None:
    """Feb-2026 · Invoice inline edit + writeback — softened.

    The prior hard-lock (rejecting product-price drift with a 400
    ``product_price_locked``) blocked operators from creating
    invoices with overridden prices. Post-Feb-2026 the app supports
    per-line inline pricing overrides for BOTH products and
    services; the pricebook value is only a default, never a wall.

    This helper now:
      * Preserves the ``overridden_price=True`` stamping so profit
        reports can flag drift.
      * NEVER raises 400 for a diverging product price.
      * Still validates ``unit_price`` is numeric (fail-fast on
        malformed payloads).

    The strict lock is available via the ``STRICT_PRODUCT_PRICE_LOCK``
    env flag for anyone who explicitly wants the pre-Feb-2026 rule
    back. Default (missing / ``"0"``) keeps the softened behaviour.
    """
    import os as _os
    strict = _os.environ.get("STRICT_PRODUCT_PRICE_LOCK", "0") == "1"
    ids = {li.get("item_id") or li.get("pricebook_item_id")
            for li in line_items}
    ids.discard(None)
    if not ids:
        return
    rows = {}
    async for row in db.items.find(
        {"id": {"$in": list(ids)}, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "item_type": 1, "unit_price": 1, "name": 1},
    ):
        rows[row["id"]] = row
    for li in line_items:
        pid = li.get("item_id") or li.get("pricebook_item_id")
        if not pid or pid not in rows:
            li.setdefault("overridden_price", False)
            continue
        row = rows[pid]
        pb_type = (row.get("item_type") or "product").lower()
        try:
            line_up = float(li.get("unit_price") or 0)
            pb_up = float(row.get("unit_price") or 0)
        except (TypeError, ValueError) as e:
            raise HTTPException(422, "unit_price must be numeric") from e
        differs = abs(line_up - pb_up) > 0.005
        if strict and pb_type == "product" and differs:
            # Explicit opt-in strict mode — keep the legacy 400.
            raise HTTPException(400, {
                "error": "product_price_locked",
                "message": ("product prices are locked; convert the "
                             "pricebook item to a service if you need "
                             "custom pricing"),
                "item_id": pid,
                "item_name": row.get("name"),
                "pricebook_unit_price": pb_up,
                "attempted_unit_price": line_up,
            })
        # Softened path — record whether the operator overrode the
        # price, regardless of product vs service. Downstream reports
        # (Internal Margin, EBIT, Profit) still see the flag.
        li["overridden_price"] = bool(differs)


# ── PB1 · Feb-2026 · Line-item margin snapshot stamping.
# ────────────────────────────────────────────────────────────────
# Snapshots are IMMUTABLE once written. On every write path we look
# at each line and only fill the ``*_snapshot`` fields that are still
# missing / None. The retail snapshot always mirrors the ``unit_price``
# ─── PB1 snapshot helper ────────────────────────────────────────────
# Rule: retail_price_snapshot is copied from ``unit_price`` at line
# write-time (that's the price the customer sees on the invoice at
# THIS exact moment); wholesale + labor come from the linked pricebook
# ``item_id`` if present, defaulting to 0.
#
# Feb 2026 · Bug fix — retail snapshot is truly immutable once set,
# but wholesale + labor cost snapshots that are currently 0 or None
# are re-hydrated from the pricebook whenever we touch the line.
# Rationale: a 0 cost snapshot is indistinguishable from "never
# populated" and blocks the Internal Margin / EBIT / Profit report
# panels from working.  The pricebook is the source of truth for
# cost values; the invoice is the source of truth for the price the
# customer paid.
#
# Same rev also adds a NAME fallback for lines missing ``item_id``
# (manually-typed line matches an existing pricebook entry by name,
# same tenant) and enforces tenant scoping on the pricebook lookup.
#
# This function mutates each line dict in place and returns the list.
async def _stamp_line_snapshots(items: List[dict],
                                    tenant_id: Optional[str] = None) -> List[dict]:
    def _to_float_or_zero(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    # Batch-load only the items we actually reference to keep this O(N).
    ids = list({li.get("item_id") for li in items if li.get("item_id")})
    item_master: dict = {}
    if ids:
        _q: Dict[str, Any] = {"id": {"$in": ids}}
        if tenant_id:
            _q["tenant_id"] = tenant_id
        rows = await db.items.find(
            _q,
            # Backlog #iii · Feb-2026 — pull the rich ``suppliers[]``
            # subdoc so the wholesale snapshot can freeze the
            # ``effective_cost`` (min supplier cost) at write time.
            # Legacy ``wholesale_price`` scalar + ``supplier_prices[]``
            # compact mirror are also projected so the effective_cost
            # helper's fallback ladder works for grandfathered items.
            {"_id": 0, "id": 1, "name": 1, "wholesale_price": 1,
              "labor_cost_default": 1, "unit_price": 1,
              "suppliers": 1, "supplier_prices": 1, "tenant_id": 1},
        ).to_list(len(ids))
        item_master = {r["id"]: r for r in rows}

    # Feb 2026 · Name-fallback — for lines the operator manually
    # typed (no ``item_id``) but whose description (or legacy
    # ``name``) matches an existing pricebook entry in the same
    # tenant, hydrate item_id + costs.  ``LineItem.description`` is
    # the canonical customer-visible text; ``name`` is only a
    # transitional/writer-set field.
    def _line_text(li):
        return (li.get("description") or li.get("name") or "").strip()

    names_needing_resolve = list({
        _line_text(li)
        for li in items
        if not li.get("item_id") and _line_text(li)
    })
    name_master: dict = {}
    if names_needing_resolve and tenant_id:
        rx = [{"tenant_id": tenant_id,
                 "name": {"$regex": f"^{re.escape(n)}$",
                            "$options": "i"}}
               for n in names_needing_resolve]
        rows = await db.items.find(
            {"$or": rx},
            # Backlog #iii · Feb-2026 — same projection as the id-lookup
            # path so name-fallback resolution can compute effective_cost.
            {"_id": 0, "id": 1, "name": 1, "wholesale_price": 1,
              "labor_cost_default": 1, "unit_price": 1,
              "suppliers": 1, "supplier_prices": 1, "tenant_id": 1},
        ).to_list(len(names_needing_resolve))
        for r in rows:
            name_master[(r.get("name") or "").strip().lower()] = r

    for li in items:
        # retail_price_snapshot — write-once from unit_price.
        if li.get("retail_price_snapshot") is None:
            li["retail_price_snapshot"] = _to_float_or_zero(li.get("unit_price"))

        # Resolve pricebook master for THIS line.
        master = item_master.get(li.get("item_id") or "") or {}
        if not master:
            nm = _line_text(li).lower()
            master = name_master.get(nm) or {}
            # Backfill item_id on the line when we find a name match
            # so subsequent updates take the fast path.
            if master and master.get("id"):
                li["item_id"] = master["id"]

        # wholesale_price_snapshot — hydrate when None OR 0, given
        # the pricebook has a non-zero value.  Never overwrite a
        # non-zero snapshot (immutable once meaningfully set).
        # Backlog #iii · Feb-2026 — use ``effective_cost(item)`` as
        # the source of truth so ``min(item.suppliers[].unit_cost)``
        # (with legacy fallback ladder) drives COGS + EBIT + profit
        # report going forward. Historical snapshots stay immutable.
        current_ws = li.get("wholesale_price_snapshot")
        needs_ws = (current_ws is None or _to_float_or_zero(current_ws) == 0.0)
        if needs_ws:
            from services.pricebook.cost import effective_cost as _ec
            ec = _ec(master, log_warn=True)
            pb_ws = _to_float_or_zero(ec) if ec is not None else 0.0
            if pb_ws > 0 or current_ws is None:
                # Only write when we actually have a real value OR
                # the field was outright missing (default to 0).
                li["wholesale_price_snapshot"] = pb_ws

        # labor_cost_snapshot — same rules as wholesale.
        current_lc = li.get("labor_cost_snapshot")
        needs_lc = (current_lc is None or _to_float_or_zero(current_lc) == 0.0)
        if needs_lc:
            pb_lc = _to_float_or_zero(master.get("labor_cost_default"))
            if pb_lc > 0 or current_lc is None:
                li["labor_cost_snapshot"] = pb_lc

    return items


@router.get("/quotes")
async def list_quotes(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant),
                      doc_type: Optional[str] = None,
                      include_deleted: bool = False,
                      category: Optional[List[str]] = Query(None),
                      card_on_file: Optional[str] = Query(None),
                      # Feb-2026 · Item 2 — customer-scoped filter for
                      # the Invoices + Quotes list pages. Additive to
                      # every existing filter; tenant scope preserved.
                      customer_id: Optional[str] = Query(None)):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if user.get("role") == "customer":
        q["customer_id"] = user.get("customer_id")
    if doc_type:
        q["doc_type"] = doc_type
    # Feb-2026 · Item 2 — admin/super_admin/manager may narrow the list
    # to a single customer. If a customer-role user drove the request,
    # their own scope filter already set customer_id above; the admin
    # filter simply overrides it (harmless in the customer-role case
    # because the caller can't send a foreign id from a portal shell).
    if customer_id:
        q["customer_id"] = customer_id
    # Phase 14b · Feb-2026 — line-item category filter. Case-insensitive
    # union across every selected value; matches invoices where ANY
    # ``line_items[].category`` equals one of the caller's values.
    if category:
        cats = [c for c in (str(x).strip() for x in category) if c]
        if cats:
            q["line_items"] = {"$elemMatch": {"category": {
                "$in": [c for c in cats],
                # elemMatch doesn't support $regex $options directly per key;
                # implement CI via a $regex OR fallback below.
            }}}
            # Build a case-insensitive union using $or over the elemMatch shape
            # so exact-case AND lower/upper variants match.
            q.pop("line_items", None)
            q["$and"] = q.get("$and", []) + [{
                "$or": [
                    {"line_items": {"$elemMatch": {"category": {
                        "$regex": f"^{re.escape(c)}$",
                        "$options": "i"}}}}
                    for c in cats
                ]
            }]
    # Phase 34 · Task BB · Feb 2026 — bulk-select soft-delete.
    # Hide soft-deleted rows by default (`deleted_at` is None or
    # missing). Only super_admins can opt-in with ``include_deleted=1``.
    if not (include_deleted and (user.get("role") or "").lower() == "super_admin"):
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]

    # Phase 14b · Feb-2026 — card-on-file filter. Resolves customer_id
    # cohorts by cross-referencing the ``payment_methods`` collection.
    # Applied AFTER the base predicate so it composes with the other
    # filters cleanly. "any" (or unset) is a no-op.
    cof = (card_on_file or "any").strip().lower()
    if cof in ("yes", "no"):
        _now = datetime.now(timezone.utc)
        pm_q = {
            "tenant_id": tenant["id"],
            "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
        }
        active_ids: set = set()
        async for pm in db.payment_methods.find(pm_q,
                                                 {"_id": 0,
                                                  "customer_id": 1,
                                                  "exp_year": 1,
                                                  "exp_month": 1}):
            ey = pm.get("exp_year"); em = pm.get("exp_month")
            try:
                ey = int(ey) if ey else None
                em = int(em) if em else None
            except (TypeError, ValueError):
                ey = em = None
            if ey and em:
                if ey < _now.year: continue
                if ey == _now.year and em < _now.month: continue
            active_ids.add(pm.get("customer_id"))
        if cof == "yes":
            q["customer_id"] = {"$in": list(active_ids) or ["__no_matches__"]}
        else:
            q["customer_id"] = {"$nin": list(active_ids)}
    docs = await db.quotes.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@router.post("/quotes")
async def create_quote(body: QuoteIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")
    # Feb-2026 MP1.5 — property_id validation. Same rules as
    # POST /jobs: if the customer has exactly 1 active property, auto-
    # assign; if the caller sent an explicit id, verify it belongs to
    # this customer + tenant AND is still active. Leaving the field
    # null when the customer has multiple properties is allowed — that's
    # the "consolidated across properties" case (master_billing_mode
    # ``consolidated``).
    property_id = body.property_id
    if property_id:
        prop = await db.properties.find_one(
            {"id": property_id, "tenant_id": tenant["id"],
              "customer_id": body.customer_id},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
    else:
        active_props = await db.properties.find(
            {"tenant_id": tenant["id"], "customer_id": body.customer_id,
              "active": {"$ne": False}},
            {"_id": 0, "id": 1},
        ).to_list(10)
        if len(active_props) == 1:
            property_id = active_props[0]["id"]
    items = [li.dict() for li in body.line_items]
    # Feb-2026 · Pricebook item_type enforcement on line-item writes.
    # Products lock unit_price to the pricebook; services allow the
    # operator to override per-customer.
    await _enforce_item_type_price_lock(tenant["id"], items)
    # Feb-2026 · Income category enforcement — every line item on a
    # NEW invoice must carry a valid category (existing seed data is
    # grandfathered). Enforced only for invoices; quotes remain lenient.
    if body.doc_type == "invoice":
        from routers.income_categories import validate_line_item_categories
        await validate_line_item_categories(tenant["id"], items)
    # Phase K71 · Feb-2026 — Two-taxonomy validation for K71 line
    # items (service + income category). Legacy items missing both
    # K71 fields are grandfathered. Applied on both quotes AND
    # invoices — invoices additionally run the legacy income guard
    # above.
    from routers.income_categories import validate_line_item_k71_categories
    await validate_line_item_k71_categories(tenant["id"], items)
    # PB1 · Feb-2026 · Stamp immutable margin snapshots on every line.
    await _stamp_line_snapshots(items, tenant_id=tenant["id"])
    subtotal, tax, total = compute_totals(items, body.tax_rate)
    due_date = body.due_date
    if body.doc_type == "invoice" and not due_date:
        due_date = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    # Auto-fill terms from tenant defaults when the caller did not explicitly send one.
    terms = body.terms
    if terms is None:
        from routers.finances import get_terms_defaults
        defaults = await get_terms_defaults()
        terms = defaults["default_invoice_terms"] if body.doc_type == "invoice" else defaults["default_quote_terms"]
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "customer_name": customer["name"],
        "property_id": property_id,
        "title": body.title,
        "doc_type": body.doc_type,
        "line_items": items,
        "tax_rate": body.tax_rate,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "amount_paid": 0.0,
        "due_date": due_date,
        "status": "draft",
        "payment_status": "unpaid",
        "notes": body.notes,
        "terms": terms,
        "created_at": now_iso(),
        # Phase K79 · Feb-2026 — NEW quotes default to grouped
        # customer-facing display ON. Existing quotes are backfilled
        # to false by scripts/k79_customer_group_display_migration.py
        # so they keep the itemized view their author designed.
        "customer_group_display": (
            True if body.customer_group_display is None
            else bool(body.customer_group_display)
        ),
        "customer_group_descriptions": body.customer_group_descriptions or {},
    }
    # Phase 56.18 — assign human-readable invoice number on birth for
    # docs typed as invoice (quotes don't get one; see routers/
    # billing.py for master invoices).
    if body.doc_type == "invoice":
        from services.invoice_numbering import assign_invoice_number_if_missing
        await assign_invoice_number_if_missing(doc, tenant)
    await db.quotes.insert_one(doc)
    doc.pop("_id", None)
    # Feb-2026 · Invoice inline edit + pricebook writeback fan-out.
    # Runs AFTER the invoice save transaction has settled so a
    # later invoice-save failure never mutates the pricebook.
    if any(li.get("pricebook_writeback") for li in items):
        try:
            from services.pricebook.writeback import process_pricebook_writebacks
            wb_result = await process_pricebook_writebacks(
                tenant_id=tenant["id"],
                invoice_id=doc["id"],
                line_items=items,
                actor=user,
            )
            if wb_result.get("processed") or wb_result.get("errors"):
                doc["pricebook_writeback_result"] = wb_result
                logger.info(
                    "[pricebook_writeback] invoice=%s processed=%d "
                    "updated=%s created=%s warnings=%s errors=%s",
                    doc["id"], wb_result["processed"],
                    wb_result["updated"], wb_result["created"],
                    wb_result["warnings"], wb_result["errors"],
                )
        except Exception:                                        # noqa: BLE001
            logger.exception(
                "[pricebook_writeback] fan-out failed for invoice=%s",
                doc["id"],
            )
    # LZ2 · Feb 2026 — fire-and-forget request to Zapier to create a
    # Lumino payment link for this invoice. Fails open — never blocks
    # invoice creation. Zap will call back into
    # /api/webhooks/lumino/invoice-link-created (LZ1) with the URL.
    if body.doc_type == "invoice":
        try:
            from services.lumino_zapier_dispatcher import schedule_dispatch
            _cust = {}
            if doc.get("customer_id"):
                _cust = await db.customers.find_one(
                    {"id": doc["customer_id"]}, {"_id": 0}
                ) or {}
            if not _cust:
                _cust = {"id": doc.get("customer_id"),
                          "name": doc.get("customer_name"),
                          "email": doc.get("customer_email")}
            schedule_dispatch(doc, _cust, base_return_url="")
        except Exception:
            pass  # fail-open
    # Comms Phase 3 — invoice.created automation (only for docs that
    # actually landed as invoices; quotes stay quiet).
    try:
        if body.doc_type == "invoice":
            from services.automation_engine import emit as _emit
            await _emit(
                "invoice.created",
                {"invoice": doc, "customer": {"id": doc.get("customer_id"),
                                                 "name": doc.get("customer_name")}},
                tenant_id=tenant["id"],
                entity_kind="invoice", entity_id=doc["id"],
                customer_id=doc.get("customer_id"),
            )
    except Exception:
        pass
    # Feb-2026 · Marketing Slice M5c — drip event bus (invoice_sent).
    # P0 Fix 2a — pass the invoice id so the event ledger's unique
    # index dedupes retries against the same document.
    try:
        if body.doc_type == "invoice" and doc.get("customer_id"):
            from services.marketing.drip_events import on_event as _drip_on_event
            await _drip_on_event(
                "invoice_sent", tenant["id"], doc.get("customer_id"),
                meta={"invoice_id": doc.get("id")},
            )
    except Exception:
        pass
    # Feb 2026 · Phase 1 Custom Trigger Builder — schema-v2 emission.
    # Correlation key = invoice id so replays dedupe.
    try:
        if body.doc_type == "invoice" and doc.get("customer_id"):
            from services.marketing.event_dispatcher import emit_event
            await emit_event(
                event="invoice_sent",
                tenant_id=tenant["id"],
                entity_id=doc.get("id"),
                customer_id=doc.get("customer_id"),
                payload_extras={"invoice": doc,
                                  "correlation_id": doc.get("id")},
            )
    except Exception:
        pass
    return doc


@router.put(
    "/quotes/{qid}",
    responses={
        # Phase K80.b · Feb-2026 — Status-based mutation gate.
        409: {
            "description": (
                "Status-locked: PUT is denied when the doc's status is "
                "not draft (estimates also allow sent). Response body "
                "shape: `{ error: 'status_locked', current_status, "
                "doc_type, message }`."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "error": "status_locked",
                            "current_status": "paid",
                            "doc_type": "invoice",
                            "message": (
                                "This invoice is locked because its "
                                "status is 'paid'. Only draft invoices "
                                "accept full edits via PUT."
                            ),
                        }
                    }
                }
            },
        },
    },
)
async def update_quote(qid: str, body: QuoteUpdate,
                       request: Request,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Partial update of quote/invoice fields (title, notes, terms, tax_rate, due_date, line_items)."""
    existing = await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Not found")
    # Feb-2026 · Editable Sent Docs · Phase 1 — reject any attempt
    # to mutate a doc-number field BEFORE the status gate. Pydantic
    # ``QuoteUpdate`` drops unknown fields silently; peek at the raw
    # body so a client-side hack can't slip an ``invoice_number``
    # / ``quote_number`` past the schema.
    try:
        _raw_body = await request.json()
    except Exception:  # noqa: BLE001
        _raw_body = {}
    if isinstance(_raw_body, dict):
        for _immut in ("invoice_number", "quote_number", "doc_number"):
            if _immut in _raw_body and _raw_body[_immut] != existing.get(_immut):
                raise HTTPException(
                    400, f"{_immut} is immutable once assigned",
                )
    # Phase K80.b · Feb-2026 — Status-based mutation gate. Refuse a PUT
    # against a status that our product policy locks. The check runs
    # BEFORE body parsing so we never waste validation cycles on a
    # rejected write; audit-log fires before the 409 raises so denials
    # are always observable in ``db.audit_logs``.
    # NOTE: This is STRICTER than the existing PATCH gates (invoice
    # 'sent' locks here but PATCH allows sent + confirm_edit_sent).
    # PATCH policy is intentionally left alone in this phase — see
    # /app/memory/PHASE_K80B_PUT_STATUS_GATE.md for the follow-up
    # question on whether to align PATCH later.
    from services.quotes.status_gate import (
        assert_quote_mutable_for_put,
        audit_put_denial,
        is_quote_mutable_for_put,
    )
    # Feb-2026 · Editable Sent Docs · Phase 1 — honour the frontend
    # confirm-dialog ``acknowledged_lock_bypass`` flag. Pulled from
    # the body BEFORE the status gate so ``sent``/``accepted``/
    # ``paid`` docs unlock when the operator has acknowledged.
    _ack = bool(getattr(body, "acknowledged_lock_bypass", False))
    if not is_quote_mutable_for_put(existing, bypass_lock=_ack):
        await audit_put_denial(db, quote=existing, actor=user)
        assert_quote_mutable_for_put(existing, bypass_lock=_ack)  # raises 409
    upd = {k: v for k, v in body.dict().items() if v is not None}
    # Feb-2026 · Task 6 · Defect fix — coalesce write-side field
    # names so ``terms_and_conditions`` (matches the GET payload
    # shape) works as an alias for the legacy ``terms`` key. When
    # the caller sends the legacy form, log a WARN so the frontend
    # is nudged to migrate before the deprecation window closes.
    if "terms_and_conditions" in upd:
        upd["terms"] = upd.pop("terms_and_conditions")
    elif "terms" in upd:
        try:
            _raw_terms_present = isinstance(_raw_body, dict) and "terms" in _raw_body
        except Exception:  # noqa: BLE001
            _raw_terms_present = False
        if _raw_terms_present:
            logger.warning(
                "[quotes.update] DEPRECATED: caller sent ``terms`` on PUT "
                "/quotes/%s. Please migrate to ``terms_and_conditions`` — "
                "the legacy key will be removed after Feb-2026.",
                qid,
            )
    # Feb-2026 · Task 6 · Defect fix — surface silent unknown-key
    # drops. The PUT schema (``QuoteUpdate``) intentionally allows
    # Pydantic to drop keys it doesn't know about, but that's a
    # foot-gun for integrators. Peek at the raw JSON body and WARN
    # for anything that isn't a known schema field (or one of the
    # request-only bypass flags).
    if isinstance(_raw_body, dict):
        _known_keys = set(QuoteUpdate.model_fields.keys()) | {
            "invoice_number", "quote_number", "doc_number",
        }
        _unknown = [k for k in _raw_body.keys() if k not in _known_keys]
        if _unknown:
            logger.warning(
                "[quotes.update] unknown keys silently dropped on PUT "
                "/quotes/%s: %s. These fields are NOT persisted; check "
                "the QuoteUpdate schema for the canonical names.",
                qid, _unknown,
            )
    # Feb-2026 · Task 6 — Terms & Conditions 5000-char cap. Applies to
    # both estimates and invoices on PATCH so admin operators can't
    # blow past the render buffer / PDF layout budget.
    if "terms" in upd and isinstance(upd["terms"], str) and len(upd["terms"]) > 5000:
        raise HTTPException(
            400, "Terms & Conditions may not exceed 5000 characters",
        )
    # ``acknowledged_lock_bypass`` + ``edit_reason`` are request-only
    # flags — never persist them on the doc row.
    _edit_reason = upd.pop("edit_reason", None)
    upd.pop("acknowledged_lock_bypass", None)
    # Feb-2026 · Editable Sent Docs · Phase 1 — also reject any
    # ``quote_number`` mutation defensively (the schema doesn't
    # include the field but keeps drift-safe).
    if "quote_number" in upd and upd["quote_number"] != existing.get("quote_number"):
        raise HTTPException(400, "quote_number is immutable once assigned")
    upd.pop("quote_number", None)
    # Phase 56.18 — invoice_number is IMMUTABLE once assigned. Reject
    # any attempt to overwrite (defensive; `QuoteUpdate` shouldn't
    # accept it, but guard anyway in case an admin sends raw JSON).
    if "invoice_number" in upd and upd["invoice_number"] != existing.get("invoice_number"):
        raise HTTPException(400, "invoice_number is immutable once assigned")
    upd.pop("invoice_number", None)
    # Feb-2026 MP1.5 — property_id patch validation. Must reference an
    # active property belonging to this quote's customer + tenant.
    if "property_id" in upd and upd["property_id"]:
        prop = await db.properties.find_one(
            {"id": upd["property_id"], "tenant_id": tenant["id"],
              "customer_id": existing.get("customer_id")},
            {"_id": 0, "id": 1, "active": 1},
        )
        if not prop:
            raise HTTPException(400, "property_id not found for this customer")
        if prop.get("active") is False:
            raise HTTPException(400, "property_id refers to an inactive property")
    if "line_items" in upd:
        upd["line_items"] = [li if isinstance(li, dict) else li.dict() for li in upd["line_items"]]
        # PB1 · Feb-2026 · Preserve existing snapshots when updating.
        # For every incoming line, if it matches an existing line by
        # id (or same-index for legacy rows without id), inherit any
        # snapshot fields that are already stamped on the existing
        # doc — snapshots are IMMUTABLE. This overwrites any value
        # the caller supplied in the payload for those three fields,
        # which is the point: "immutable once set" means the API
        # never accepts an update to them.
        existing_lines = existing.get("line_items") or []
        existing_by_id = {li.get("id"): li for li in existing_lines if li.get("id")}
        # Feb 2026 · Bug fix — retail_price_snapshot IS truly immutable
        # (that's the price the customer saw), but cost snapshots
        # (wholesale + labor) that are 0/None are considered "never
        # populated" and are re-hydrated below by _stamp_line_snapshots.
        # Only preserve retail here.
        _IMMUTABLE_KEYS = ("retail_price_snapshot",)
        # Preserve non-zero cost snapshots (real historical values) but
        # allow 0/None to be re-hydrated.
        _COST_KEYS = ("wholesale_price_snapshot", "labor_cost_snapshot")
        for idx, new_li in enumerate(upd["line_items"]):
            match = existing_by_id.get(new_li.get("id"))
            if not match and idx < len(existing_lines):
                match = existing_lines[idx]
            if match:
                for k in _IMMUTABLE_KEYS:
                    if match.get(k) is not None:
                        new_li[k] = match[k]
                for k in _COST_KEYS:
                    _v = match.get(k)
                    try:
                        _f = float(_v) if _v is not None else 0.0
                    except (TypeError, ValueError):
                        _f = 0.0
                    if _v is not None and _f > 0:
                        # Real historical cost — preserve; snapshots
                        # are immutable ONCE MEANINGFULLY SET.
                        new_li[k] = match[k]
        # Feb-2026 · Pricebook item_type enforcement.
        await _enforce_item_type_price_lock(tenant["id"], upd["line_items"])
        # Phase K71 · Feb-2026 — K71 category two-taxonomy validation
        # on every PUT that carries a line_items array.
        from routers.income_categories import validate_line_item_k71_categories
        await validate_line_item_k71_categories(tenant["id"], upd["line_items"])
        await _stamp_line_snapshots(upd["line_items"], tenant_id=tenant["id"])
    if "line_items" in upd or "tax_rate" in upd:
        items = upd.get("line_items", existing.get("line_items", []))
        tax_rate = float(upd.get("tax_rate", existing.get("tax_rate", 0)) or 0)
        subtotal, tax, total = compute_totals(items, tax_rate)
        amount_paid = float(existing.get("amount_paid") or 0)
        upd.update({
            "tax_rate": tax_rate,
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "remaining_balance": round(max(total - amount_paid, 0.0), 2),
        })
    upd["updated_at"] = now_iso()
    # Feb-2026 · Editable Sent Docs · Phase 1 — snapshot the
    # pre-mutation state BEFORE persisting. Baseline is inserted
    # inside the helper on first edit of a doc. Best-effort; audit
    # write failures never break the parent write.
    from services.documents import (
        snapshot_before_mutation, invalidate_signature_if_present,
        has_signature,
    )
    _doc_type_for_version = ("invoice" if (existing.get("doc_type") == "invoice")
                              else "quote")
    _had_sig = await has_signature(doc_id=qid, tenant_id=tenant["id"])
    _content_fields_changing = any(
        k in upd for k in ("line_items", "tax_rate", "notes", "terms",
                             "title", "due_date")
    )
    _sig_will_invalidate = _had_sig and _content_fields_changing
    await snapshot_before_mutation(
        doc_type=_doc_type_for_version, doc_id=qid,
        tenant_id=tenant["id"], current_doc=existing,
        # Feb-2026 · Phase 2 — pass the merged post-mutation doc
        # so the write-time ``change_summary`` describes THIS edit
        # (line-item / money / notes deltas about to be applied).
        new_doc={**existing, **upd},
        saved_by_user=user,
        status_at_edit=(existing.get("status") or "draft"),
        reason=_edit_reason, lock_bypass_ack=_ack,
        signature_invalidated=_sig_will_invalidate,
    )
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": upd})
    if _sig_will_invalidate:
        await invalidate_signature_if_present(
            doc_type=_doc_type_for_version, doc_id=qid,
            tenant_id=tenant["id"], collection=db.quotes,
        )
    # Feb-2026 · Invoice inline edit + pricebook writeback fan-out.
    if "line_items" in upd and any(
        li.get("pricebook_writeback") for li in upd["line_items"]
    ):
        try:
            from services.pricebook.writeback import process_pricebook_writebacks
            wb_result = await process_pricebook_writebacks(
                tenant_id=tenant["id"],
                invoice_id=qid,
                line_items=upd["line_items"],
                actor=user,
            )
            if wb_result.get("processed") or wb_result.get("errors"):
                logger.info(
                    "[pricebook_writeback] invoice=%s (put) processed=%d "
                    "updated=%s created=%s warnings=%s errors=%s",
                    qid, wb_result["processed"],
                    wb_result["updated"], wb_result["created"],
                    wb_result["warnings"], wb_result["errors"],
                )
        except Exception:                                        # noqa: BLE001
            logger.exception(
                "[pricebook_writeback] fan-out failed for invoice=%s (put)",
                qid,
            )
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.get("/quotes/ready-to-schedule")
async def ready_to_schedule(admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Approved online estimates not yet turned into a scheduled job."""
    docs = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "quote", "status": "accepted",
         "scheduled_job_id": {"$in": [None, ""]}},
        {"_id": 0},
    ).sort("accepted_at", -1).to_list(500)
    # Include legacy accepted quotes that predate the scheduled_job_id field.
    extra = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "quote", "status": "accepted",
         "scheduled_job_id": {"$exists": False}},
        {"_id": 0},
    ).to_list(500)
    seen = {d["id"] for d in docs}
    docs.extend([e for e in extra if e["id"] not in seen])
    return [{
        "id": d["id"], "title": d.get("title", ""), "customer_id": d.get("customer_id"),
        "customer_name": d.get("customer_name", ""), "total": d.get("total", 0),
        "accepted_at": d.get("accepted_at"),
    } for d in docs]


@router.get("/quotes/{qid}")
async def get_quote(qid: str,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant),
                    # Feb-2026 · P2 Item 1 — super_admin escape hatch so
                    # the deletion audit / restore UX can preview a
                    # snapshot without having to reach into the audit
                    # collection twice.  Non-super callers can't set
                    # this — the guard below silently drops it.
                    include_deleted: bool = False):
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    role = (user.get("role") or "").lower()
    # Feb-2026 · P2 Item 1 — direct-link portal-leak guard. Soft-
    # deleted quotes / invoices MUST 404 for every caller except a
    # super_admin who explicitly opts in via ``?include_deleted=true``.
    q: Dict[str, Any] = {"id": qid, "tenant_id": tenant["id"]}
    if not (include_deleted and role == "super_admin"):
        q["$or"] = [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]
    doc = await db.quotes.find_one(q, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    return doc


@router.post("/quotes/{qid}/decision", deprecated=True)
async def customer_quote_decision(qid: str,
                                  decision: str = Query(...),
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    """DEPRECATED (Feb-2026, Phase A) — legacy customer approve/decline.

    This endpoint predates ``routers/estimate_viewer.py`` and does not
    populate ``decision``, ``accepted_by``, drip events, or admin
    notifications. New callers MUST use::

        POST /api/portal/quotes/via-token/{token}/approve
        POST /api/portal/quotes/via-token/{token}/decline
        POST /api/quotes/{qid}/accept    (auth'd)
        POST /api/quotes/{qid}/decline   (auth'd)

    Retained for one release cycle to avoid breaking pinned mobile
    clients. Slated for removal after Phase C ships.
    """
    from config import logger as _logger
    _logger.warning(
        "[phase-a] deprecated endpoint hit: POST /quotes/%s/decision "
        "decision=%s user=%s tenant=%s — migrate to /portal/quotes/"
        "via-token/{token}/approve or /decline.",
        qid, decision, user.get("id"), tenant.get("id"),
    )
    if user.get("role") != "customer":
        raise HTTPException(403, "Customers only")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")
    if doc.get("doc_type") != "quote":
        raise HTTPException(400, "Only estimates can be approved or declined")
    # Phase K71 · Feb-2026 — Save/Send gating on customer approval.
    if decision == "approve":
        from routers.income_categories import check_line_items_k71_gaps
        gaps = check_line_items_k71_gaps(doc.get("line_items") or [])
        if gaps:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "k71_missing_categories",
                    "error_code": "k71_missing_categories",
                    "line_indices": gaps,
                    "message": ("Set Service + Income category on every "
                                 "line item before approving."),
                },
            )
    status = "accepted" if decision == "approve" else "declined"
    upd = {"status": status}
    if status == "accepted":
        upd["accepted_at"] = now_iso()
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": upd})
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/quotes/{qid}/schedule")
async def schedule_from_estimate(qid: str, body: MaintBulkIn,
                                 admin: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Turn an approved estimate into a scheduled job in one tap."""
    try:
        datetime.fromisoformat(body.scheduled_date[:10])
    except (ValueError, TypeError):
        raise HTTPException(400, "scheduled_date must be YYYY-MM-DD")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Estimate not found")
    if doc.get("doc_type") != "quote" or doc.get("status") != "accepted":
        raise HTTPException(400, "Only approved estimates can be scheduled")
    if doc.get("scheduled_job_id"):
        raise HTTPException(400, "This estimate is already scheduled")
    customer = await db.customers.find_one(
        {"id": doc.get("customer_id"), "tenant_id": tenant["id"]}, {"_id": 0}
    )
    tech_name, tech_avatar = None, ""
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        tech_name = tech["name"] if tech else None
        tech_avatar = tech.get("avatar", "") if tech else ""
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "title": doc.get("title", "Service"), "customer_id": doc.get("customer_id"),
        "customer_name": doc.get("customer_name", ""), "technician_id": body.technician_id,
        "technician_name": tech_name, "technician_avatar": tech_avatar,
        "address": (customer or {}).get("address", ""), "service_type": doc.get("title", "Service"),
        "scheduled_date": body.scheduled_date, "notes": doc.get("notes", ""),
        "price": float(doc.get("total") or 0), "status": "pending", "photos": [],
        "from_estimate_id": qid, "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    job.pop("_id", None)
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"scheduled_job_id": job["id"], "status": "scheduled"}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Service scheduled",
                              f"Your approved estimate '{doc.get('title')}' is scheduled for {body.scheduled_date}.", job_id=job["id"])
    return job


@router.put("/quotes/{qid}/status")
async def update_quote_status(qid: str, status: str = Query(...),
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    # Phase K71 · Feb-2026 — Save/Send gating. Block draft→sent (and
    # any transition into ``sent``) on a quote/estimate whose line
    # items were touched by the K71 inline editor but are missing
    # a required category. Invoice send is already covered by the
    # create + PATCH validations upstream; only re-check for quotes
    # here.
    doc = await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"_id": 0, "doc_type": 1, "line_items": 1},
    )
    if doc and (status or "").lower() in ("sent", "accepted", "approved"):
        from routers.income_categories import check_line_items_k71_gaps
        gaps = check_line_items_k71_gaps(doc.get("line_items") or [])
        if gaps:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "k71_missing_categories",
                    "error_code": "k71_missing_categories",
                    "line_indices": gaps,
                    "message": ("Set Service + Income category on every "
                                 "line item before sending or approving."),
                },
            )
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]}, {"$set": {"status": status}}
    )
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/quotes/{qid}/send-reminder")
async def send_reminder(qid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Feb-2026 · P0 fix — Send-reminder now branches on ``doc_type``.

    * Invoice — payment-reminder shape (subject, body, "Pay Now"
      button, outstanding-balance copy).  Unchanged customer-facing
      contract.
    * Estimate / quote — review-reminder shape (subject, body,
      "Review Estimate" / "Review Quote" button pointing at the
      customer-facing magic-link viewer ``/e/estimate?token=…``).
      NEVER mentions "outstanding balance" / "amount due" /
      "Pay Now" — the customer owes NOTHING on an estimate.

    Before this fix, the estimate-side click routed through the
    invoice template and produced the "invoice Estimate has an
    outstanding balance of $X" copy that landed in prod on Feb-2026
    (see ``DIAG_ESTIMATE_INVOICE_REMINDER_BUG.md``).
    """
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    if not doc.get("customer_id"):
        raise HTTPException(400, "This document has no linked customer.")
    doc_type = str(doc.get("doc_type") or "invoice").lower()
    ts = now_iso()

    if doc_type in ("estimate", "quote"):
        # ── Estimate / quote review-reminder path ──────────────
        # These docs are awaiting a **decision**, not a payment.
        # Refusing after conversion (doc_type flips to invoice)
        # keeps this branch narrow.
        if doc.get("status") in ("approved", "declined"):
            raise HTTPException(
                400,
                f"This {doc_type} has already been "
                f"{doc.get('status')}.",
            )
        doc_type_label = "quote" if doc_type == "quote" else "estimate"
        # Mint a fresh magic-link token for the "Review" CTA. The
        # helper below is the same one ``GET /quotes/{qid}/magic-
        # link`` returns to the admin toolbar so tokens are
        # signature-compatible and share the 30-day TTL.
        from routers.estimate_viewer import _sign_estimate_token
        tok = _sign_estimate_token(qid, doc["customer_id"], tenant["id"])
        import os
        base = (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
        review_url = f"{base}/e/estimate?token={tok}" if base else ""
        display_number = (
            doc.get("invoice_number")
            or doc.get("doc_number")
            or f"#{qid[:8]}"
        )
        title = f"{doc_type_label.title()} review reminder"
        body = (
            f"{doc_type_label.title()} {display_number} is awaiting your "
            f"review. Please approve, request changes, or decline."
        )
        await notify_customer(doc["customer_id"], title, body, sms=True)
        email_sent = await send_estimate_reminder_email(
            doc, tenant, review_url,
        )
        count = int(doc.get("reminder_count") or 0) + 1
        await db.quotes.update_one(
            {"id": qid, "tenant_id": tenant["id"]},
            {"$set": {"last_reminder_at": ts, "reminder_count": count}},
        )
        try:
            await db.audit_events.insert_one({
                "id": new_id(),
                "event_type": f"{doc_type_label}_reminder_sent",
                "actor_user_id": user.get("id") or user.get("_id") or "unknown",
                "tenant_id": tenant["id"],
                "timestamp": ts,
                "payload": {
                    f"{doc_type_label}_id": qid,
                    "doc_number": display_number,
                    "customer_id": doc.get("customer_id"),
                    "customer_name": doc.get("customer_name"),
                    "email_sent": bool(email_sent),
                    "reminder_count": count,
                    "channel": "in_app+sms+email",
                    "review_url_minted": bool(review_url),
                },
            })
        except Exception as e:
            logger.warning(
                f"{doc_type_label}_reminder_sent audit write failed: {e}",
            )
        return {
            "ok": True, "email_sent": email_sent,
            "reminder_count": count, "last_reminder_at": ts,
            "doc_type": doc_type_label,
            "review_url_minted": bool(review_url),
        }

    # ── Invoice payment-reminder path (unchanged contract) ────────
    if doc.get("payment_status") == "paid":
        raise HTTPException(400, "This invoice is already paid.")
    balance = round(float(doc.get("total") or 0) - float(doc.get("amount_paid") or 0), 2)
    display_number = (
        doc.get("invoice_number")
        or doc.get("doc_number")
        or f"#{qid[:8]}"
    )
    title = "Payment reminder"
    body = (
        f"Invoice {display_number} has an outstanding balance of "
        f"${balance:,.2f}. Please pay at your earliest convenience."
    )
    await notify_customer(doc["customer_id"], title, body, sms=True)
    email_sent = await send_invoice_reminder_email(doc)
    count = int(doc.get("reminder_count") or 0) + 1
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"last_reminder_at": ts, "reminder_count": count}},
    )
    # R1.b · Feb-2026 — write an ``invoice_reminder_sent`` audit
    # event so downstream DSO / collections dashboards can count
    # the "touch" without re-scanning the quotes collection. Best-
    # effort: audit failures do NOT surface as reminder failures.
    try:
        await db.audit_events.insert_one({
            "id": new_id(),
            "event_type": "invoice_reminder_sent",
            "actor_user_id": user.get("id") or user.get("_id") or "unknown",
            "tenant_id": tenant["id"],
            "timestamp": ts,
            "payload": {
                "invoice_id": qid,
                "invoice_number": doc.get("invoice_number"),
                "customer_id": doc.get("customer_id"),
                "customer_name": doc.get("customer_name"),
                "balance": balance,
                "email_sent": bool(email_sent),
                "reminder_count": count,
                "channel": "in_app+sms+email",
            },
        })
    except Exception as e:
        logger.warning(f"invoice_reminder_sent audit write failed: {e}")
    return {"ok": True, "email_sent": email_sent, "reminder_count": count, "last_reminder_at": ts}


@router.get("/invoices/overview")
async def invoices_overview(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Admin AR dashboard: all outstanding invoices tagged pending / past_due / partial."""
    docs = await db.quotes.find(
        {"tenant_id": tenant["id"], "doc_type": "invoice"}, {"_id": 0}
    ).sort("due_date", 1).to_list(2000)
    today = datetime.now(timezone.utc).date().isoformat()
    cust_ids = list({d.get("customer_id") for d in docs if d.get("customer_id")})
    pm_map = {}
    if cust_ids:
        custs = await db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "default_payment_method_id": 1, "pm_brand": 1, "pm_last4": 1},
        ).to_list(2000)
        for c in custs:
            if c.get("default_payment_method_id"):
                last4 = c.get("pm_last4", "")
                pm_map[c["id"]] = f"{c.get('pm_brand', 'Card')} ••{last4}" if last4 else c.get("pm_brand", "On file")
    out = []
    summary = {
        "pending": {"count": 0, "amount": 0.0},
        "past_due": {"count": 0, "amount": 0.0},
        "partial": {"count": 0, "amount": 0.0},
        "outstanding": {"count": 0, "amount": 0.0},
        "failed": {"count": 0, "amount": 0.0},
    }
    for d in docs:
        total = float(d.get("total") or 0)
        paid = float(d.get("amount_paid") or 0)
        balance = round(total - paid, 2)
        is_paid = d.get("payment_status") == "paid" or balance <= 0.01
        if is_paid:
            continue
        due = d.get("due_date")
        past_due = bool(due and due < today)
        partial = paid > 0.009
        pending = (not past_due) and (not partial)
        charge_failed = bool(d.get("charge_failed"))
        row = {
            "id": d["id"], "title": d.get("title", ""), "customer_name": d.get("customer_name", ""),
            "customer_id": d.get("customer_id"), "total": total, "amount_paid": round(paid, 2),
            "balance": balance, "due_date": due, "status": d.get("status"),
            "payment_status": d.get("payment_status"), "created_at": d.get("created_at"),
            "past_due": past_due, "partial": partial, "pending": pending,
            "last_reminder_at": d.get("last_reminder_at"), "reminder_count": int(d.get("reminder_count") or 0),
            "has_payment_method": d.get("customer_id") in pm_map,
            "pm_label": pm_map.get(d.get("customer_id"), ""),
            "processing": d.get("payment_status") == "processing",
            "charge_failed": charge_failed,
            "charge_error": d.get("charge_error", "") if charge_failed else "",
            "charge_failed_at": d.get("charge_failed_at") if charge_failed else None,
            # Phase K47 · Feb-2026 — surface the denormalised view
            # aggregates so the invoices list "Viewed Nd ago" pill
            # renders without an extra roundtrip per row.
            "first_viewed_at": d.get("first_viewed_at"),
            "last_viewed_at": d.get("last_viewed_at"),
            "view_count": int(d.get("view_count") or 0),
        }
        out.append(row)
        summary["outstanding"]["count"] += 1
        summary["outstanding"]["amount"] += balance
        if past_due:
            summary["past_due"]["count"] += 1
            summary["past_due"]["amount"] += balance
        if partial:
            summary["partial"]["count"] += 1
            summary["partial"]["amount"] += balance
        if pending:
            summary["pending"]["count"] += 1
            summary["pending"]["amount"] += balance
        if charge_failed:
            summary["failed"]["count"] += 1
            summary["failed"]["amount"] += balance
    for k in summary:
        summary[k]["amount"] = round(summary[k]["amount"], 2)
    return {"summary": summary, "invoices": out}


@router.post("/quotes/{qid}/record-payment")
async def record_payment(qid: str, body: RecordPaymentIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Admin records a full or PARTIAL offline payment against an invoice."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    total = float(doc.get("total") or 0)
    paid = round(float(doc.get("amount_paid") or 0) + body.amount, 2)
    fully_paid = paid >= total - 0.01
    update = {
        "amount_paid": min(paid, total),
        "payment_status": "paid" if fully_paid else "partial",
        "charge_failed": False, "charge_error": "",
    }
    if fully_paid:
        update.update({"status": "accepted", "paid_at": now_iso(), "payment_method": "manual"})
    await db.quotes.update_one({"id": qid, "tenant_id": tenant["id"]}, {"$set": update})
    if doc.get("customer_id"):
        msg = ("Your payment was received in full. Thank you!" if fully_paid
               else f"A partial payment of ${body.amount:,.2f} was recorded. Remaining balance: ${max(total - paid, 0):,.2f}.")
        await notify_customer(doc["customer_id"], "Payment recorded", msg)
    # Comms Phase 3 — fire invoice.paid on the flip to fully-paid.
    if fully_paid:
        try:
            fresh = await db.quotes.find_one(
                {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
            from services.automation_engine import emit as _emit
            await _emit(
                "invoice.paid",
                {"invoice": fresh or {}, "customer": {"id": (fresh or {}).get("customer_id"),
                                                          "name": (fresh or {}).get("customer_name")}},
                tenant_id=tenant["id"],
                entity_kind="invoice", entity_id=qid,
                customer_id=(fresh or {}).get("customer_id"),
            )
        except Exception:
            pass
        # Feb 2026 · Phase 1 Custom Trigger Builder — schema-v2 emission.
        try:
            from services.marketing.event_dispatcher import emit_event
            fresh = await db.quotes.find_one(
                {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0}) or {}
            if fresh.get("customer_id"):
                await emit_event(
                    event="invoice_paid",
                    tenant_id=tenant["id"],
                    entity_id=qid,
                    customer_id=fresh.get("customer_id"),
                    payload_extras={"invoice": fresh,
                                      "correlation_id": qid},
                )
        except Exception:
            pass
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.post("/quotes/{qid}/pay")
async def pay_quote(qid: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    """Admin-only: record a manual/offline FULL payment (cash, check, external card)."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"payment_status": "paid", "status": "accepted",
                  "amount_paid": float(doc.get("total") or 0),
                  "paid_at": now_iso(), "payment_method": "manual",
                  "charge_failed": False, "charge_error": ""}},
    )
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Payment received",
                              f"Your payment for '{doc.get('title', 'invoice')}' was recorded. Thank you!")
    # Comms Phase 3 — invoice.paid on manual/offline full payment.
    try:
        fresh = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
        from services.automation_engine import emit as _emit
        await _emit(
            "invoice.paid",
            {"invoice": fresh or {}, "customer": {"id": (fresh or {}).get("customer_id"),
                                                      "name": (fresh or {}).get("customer_name")}},
            tenant_id=tenant["id"],
            entity_kind="invoice", entity_id=qid,
            customer_id=(fresh or {}).get("customer_id"),
        )
    except Exception:
        pass
    # Feb 2026 · Phase 1 Custom Trigger Builder — schema-v2 emission.
    try:
        from services.marketing.event_dispatcher import emit_event
        fresh = await db.quotes.find_one(
            {"id": qid, "tenant_id": tenant["id"]}, {"_id": 0}) or {}
        if fresh.get("customer_id"):
            await emit_event(
                event="invoice_paid",
                tenant_id=tenant["id"],
                entity_id=qid,
                customer_id=fresh.get("customer_id"),
                payload_extras={"invoice": fresh,
                                  "correlation_id": qid},
            )
    except Exception:
        pass
    return await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})



# ────────────────────────────── PDF export ───────────────────────────────────
@router.get("/quotes/{qid}/pdf")
async def quote_or_invoice_pdf(qid: str,
                               user: dict = Depends(get_current_user),
                               tenant: dict = Depends(get_current_tenant)):
    """Streams a printable PDF for a quote or invoice, including the terms section."""
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    if user.get("role") == "technician":
        raise HTTPException(403, "Not allowed")
    if user.get("role") == "customer" and doc.get("customer_id") != user.get("customer_id"):
        raise HTTPException(403, "Not allowed")

    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    is_invoice = doc.get("doc_type") == "invoice"
    label = "Invoice" if is_invoice else "Estimate"

    # Feb-2026 · Quote customer-view grouped-lock ship — customers
    # see the grouped-by-service-category layout on their PDF, not
    # the itemized 4-column table. Invoices are unaffected (grouped
    # layout is quote/estimate-only). Admin PDFs stay itemized so
    # ops can review the raw line items unchanged.
    # See /app/memory/FEATURE_QUOTE_CUSTOMER_VIEW_GROUPED.md.
    render_grouped = (
        (user.get("role") or "").lower() == "customer"
        and not is_invoice
    )
    grouped_data: dict = {}
    if render_grouped:
        try:
            from services.quotes.customer_view import (
                build_customer_view_payload,
            )
            svc_cats = await db.service_categories.find(
                {"tenant_id": tenant["id"]}, {"_id": 0},
            ).to_list(length=None)
            grouped_data = build_customer_view_payload(doc, svc_cats)
        except Exception:
            # Any failure → fall back to the itemized render below so
            # a bad service-categories fetch never blocks the PDF.
            render_grouped = False
            grouped_data = {}

    buf = BytesIO()
    pdf_doc = SimpleDocTemplate(buf, pagesize=letter, title=f"{label} {qid[:8]}")
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"<b>{label}</b>", styles["Title"]))
    story.append(Paragraph("Pool &amp; Landscaping of Vistancia", styles["Normal"]))
    story.append(Spacer(1, 12))

    header_rows = [
        [f"{label} #", qid[:8].upper()],
        ["Title", doc.get("title", "")],
        ["Customer", doc.get("customer_name", "")],
        ["Status", (doc.get("status") or "").title()],
    ]
    if is_invoice:
        header_rows.append(["Due", doc.get("due_date") or "—"])
        header_rows.append(["Payment", (doc.get("payment_status") or "unpaid").title()])
    header_rows.append(["Created", (doc.get("created_at") or "")[:10]])
    t = Table(header_rows, colWidths=[1.4 * inch, 5.0 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), rlcolors.HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 16))

    line_rows = [["Description", "Qty", "Unit", "Total"]]
    if render_grouped:
        # Feb-2026 · grouped-lock — replace the itemized rows with
        # per-service-category subtotals. The 4-column shape stays
        # (Description / Qty / Unit / Total) so the existing
        # styling doesn't have to shift: "Description" holds the
        # category label + description, Qty / Unit render as em-
        # dashes, Total holds the group subtotal.
        line_rows = [["Service", "", "", "Subtotal"]]
        for g in grouped_data.get("groups") or []:
            desc_label = g.get("label") or "—"
            desc_body = (g.get("description") or "").strip()
            desc_cell = (f"{desc_label}\n{desc_body}"
                          if desc_body else desc_label)
            line_rows.append([
                desc_cell, "—", "—",
                f"${float(g.get('subtotal') or 0):,.2f}",
            ])
    else:
        for li in (doc.get("line_items") or []):
            qty = float(li.get("quantity") or 0)
            unit = float(li.get("unit_price") or 0)
            line_rows.append([li.get("description", ""), f"{qty:g}", f"${unit:,.2f}", f"${qty * unit:,.2f}"])
    lt = Table(line_rows, colWidths=[3.6 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch])
    lt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), rlcolors.HexColor("#F4F4F5")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(lt)
    story.append(Spacer(1, 8))

    subtotal = float(doc.get("subtotal") or 0)
    tax_amt = float(doc.get("tax") or 0)
    total = float(doc.get("total") or 0)
    tot_rows = [
        ["Subtotal", f"${subtotal:,.2f}"],
        [f"Tax ({doc.get('tax_rate', 0)}%)", f"${tax_amt:,.2f}"],
        ["Total", f"${total:,.2f}"],
    ]
    tt = Table(tot_rows, colWidths=[5.0 * inch, 1.4 * inch])
    tt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, rlcolors.HexColor("#0284C7")),
        ("TEXTCOLOR", (0, -1), (-1, -1), rlcolors.HexColor("#0284C7")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tt)
    story.append(Spacer(1, 14))

    notes = (doc.get("notes") or "").strip()
    if notes:
        story.append(Paragraph("<b>Notes</b>", styles["Heading3"]))
        story.append(Paragraph(notes.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 10))

    terms_text = doc.get("terms")
    if not terms_text:
        try:
            from routers.finances import get_terms_defaults
            defaults = await get_terms_defaults()
            terms_text = defaults["default_invoice_terms"] if is_invoice else defaults["default_quote_terms"]
        except Exception:
            terms_text = ""
    if terms_text:
        story.append(Paragraph("<b>Terms &amp; Conditions</b>", styles["Heading3"]))
        story.append(Paragraph(terms_text.replace("\n", "<br/>"), styles["Normal"]))

    pdf_doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    filename = f"{label.lower()}-{qid[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Invoice/Quote bulk-select soft-delete.
# Mirrors the Phase 28 `_perform_soft_delete_job` pattern in routers/jobs.py.
# The invoice list page + Estimator list page + Payments ledger all gained
# checkbox-select + mass-delete UX; each surface hits its own bulk endpoint.
# ═════════════════════════════════════════════════════════════════════════
from pydantic import BaseModel as _BaseModelBB  # local alias — avoid model.py * import shadow


class _InvoiceBulkDeleteIn(_BaseModelBB):
    # Phase 34 · Task EE (extension) — invoices/payments accept
    # either explicit ``ids`` or the filter-selector shape.
    ids: Optional[List[str]] = None
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None


# Phase 34 · Task DD · Feb 2026 — cap raised 100 → 400 across all four
# bulk-delete surfaces (invoices, estimates, payments, leads). Kept as
# a local constant per router so a bad import can't accidentally drop
# the guard entirely.
_BULK_DELETE_CAP = 1000

_INVOICE_SELECTOR_KEYS = {"status", "search", "customer_id", "has_late_fee"}


async def _resolve_invoice_ids(selector: Dict[str, Any],
                                 exclude: List[str],
                                 tenant_id: str,
                                 doc_type: str = "invoice") -> List[str]:
    """Task EE — safely translate the invoices/payments frontend filter
    shape into a concrete list of quote ids. Whitelist-only. Always
    tenant-scoped, always excludes soft-deleted rows."""
    q: Dict[str, Any] = {"tenant_id": tenant_id, "doc_type": doc_type,
                            "$or": [{"deleted_at": None},
                                        {"deleted_at": {"$exists": False}}]}
    clean = {k: v for k, v in (selector or {}).items()
              if k in _INVOICE_SELECTOR_KEYS}
    if clean.get("status") and clean["status"] != "all":
        q["payment_status"] = clean["status"]
    if clean.get("customer_id"):
        q["customer_id"] = clean["customer_id"]
    if clean.get("has_late_fee"):
        q["line_items.is_late_fee"] = True
    if clean.get("search"):
        s = str(clean["search"]).strip()
        if s:
            q["$and"] = [{"$or": [
                {"title": {"$regex": s, "$options": "i"}},
                {"customer_name": {"$regex": s, "$options": "i"}},
                {"invoice_number": {"$regex": s, "$options": "i"}},
            ]}]
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db.quotes.find(q, {"_id": 0, "id": 1}).limit(_BULK_DELETE_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


async def _perform_soft_delete_quote(qid: str, user: dict, tenant: dict,
                                       deletion_reason: Optional[str] = None) -> dict:
    """Shared soft-delete helper for quotes/invoices. Enforces:
    * tenant scoping (row must belong to caller's tenant).
    * no re-delete (already soft-deleted rows return ``already_deleted=True``
      instead of raising).
    * audit row written best-effort to BOTH ``db.audit_log`` (legacy
      consumers) AND ``db.deletion_audit`` (Feb-2026 · Item 3 richer
      audit surface with snapshot + restore support).
    Called by both the single-invoice soft-delete + the bulk endpoint so
    behavior is identical.
    """
    doc = await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant["id"]},
        # Feb-2026 · Item 3 — full doc for the deletion_audit snapshot;
        # legacy code only projected a couple of fields, but we need the
        # whole row to support restore.
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Invoice not found")
    if doc.get("deleted_at"):
        return {"ok": True, "id": qid, "already_deleted": True}
    deleted_at = now_iso()
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": deleted_at,
                    "deleted_by_user_id": user.get("id"),
                    "deletion_reason": deletion_reason}},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "invoice.soft_delete",
            "target_id": qid,
            "target_doc_type": doc.get("doc_type") or "invoice",
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"invoice.soft_delete audit failed: {e}")
    # Feb-2026 · Item 3 — richer audit surface. Cascade is empty here
    # because the payment IS the invoice in this codebase's data model.
    try:
        from routers.deletion_audit import write_deletion_audit_entry
        await write_deletion_audit_entry(
            tenant_id=tenant["id"],
            resource_type="invoice",
            resource_id=qid,
            user=user,
            snapshot=doc,
            cascade_deleted_ids=[],
            deletion_reason=deletion_reason,
        )
    except Exception as e:
        logger.warning(f"deletion_audit invoice insert failed: {e}")
    return {"ok": True, "id": qid, "deleted_at": deleted_at}


@router.post("/invoices/{qid}/soft-delete",
              operation_id="invoices.softDelete")
async def soft_delete_invoice(qid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await _perform_soft_delete_quote(qid, user, tenant)


@router.post("/invoices/bulk-delete",
              operation_id="invoices.bulkDelete")
async def bulk_delete_invoices(body: _InvoiceBulkDeleteIn,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    """Bulk soft-delete invoices. See Task EE (extension) for the
    ``query_selector`` shape.

    Feb-2026 · P0 perf fix — this used to loop `for qid in ids: await
    _perform_soft_delete_quote(...)` which was O(N) with 3 DB
    round-trips per invoice. For N ≈ 400 that blew past the ingress
    30-60s timeout window. Replaced with a bulk-shaped path that
    does one ``find`` (id-only, non-deleted subset), one
    ``update_many`` for the soft-delete flip, and one ``insert_many``
    for audit rows. Same response shape as before so the FE is
    untouched.

    Feb-2026 · RBAC widening — super_admin / admin / manager may
    drive this endpoint (the previous ``require_admin`` gate also
    let ``owner`` through; the new bulk operations widened /
    tightened together per user dispatch — manager IN, owner OUT).
    """
    # RBAC — tighter than require_admin: super_admin/admin/manager only.
    role = (user or {}).get("role")
    if role not in {"super_admin", "admin", "manager"}:
        raise HTTPException(
            403, "bulk_delete_requires_admin_or_manager",
        )
    if body.query_selector is not None:
        ids = await _resolve_invoice_ids(
            body.query_selector, body.exclude_ids or [],
            tenant["id"], doc_type="invoice",
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _BULK_DELETE_CAP:
        raise HTTPException(400,
            f"too_many_ids: max_{_BULK_DELETE_CAP}_per_request")
    # De-dupe payload — matches the prior handler's idempotency shape.
    ids = list(dict.fromkeys(ids))

    # 1. Bulk-find the target rows for this tenant. We fetch three
    # fields per row so we can (a) mark "not found" ids, (b) mark
    # already-deleted rows without re-flipping them, (c) build a
    # correctly-typed audit row per invoice.
    rows: List[dict] = []
    async for row in db.quotes.find(
        {"tenant_id": tenant["id"], "id": {"$in": ids}},
        {"_id": 0, "id": 1, "deleted_at": 1, "doc_type": 1},
    ):
        rows.append(row)
    found_ids = {r["id"] for r in rows if r.get("id")}
    already_deleted_ids = {r["id"] for r in rows if r.get("deleted_at")}
    to_flip_rows = [r for r in rows
                     if r.get("id") and not r.get("deleted_at")]
    to_flip_ids = [r["id"] for r in to_flip_rows]

    # 2. Bulk-flip the non-already-deleted subset in ONE update.
    deleted_at = now_iso()
    if to_flip_ids:
        await db.quotes.update_many(
            {"tenant_id": tenant["id"], "id": {"$in": to_flip_ids}},
            {"$set": {"deleted_at": deleted_at,
                        "deleted_by_user_id": user.get("id")}},
        )

    # 3. Bulk-insert audit rows in ONE call. Best-effort — a failed
    # audit insert never blocks the delete.
    if to_flip_rows:
        try:
            await db.audit_log.insert_many([{
                "id": new_id(),
                "tenant_id": tenant["id"],
                "actor_user_id": user.get("id"),
                "actor_email": user.get("email"),
                "action": "invoice.soft_delete",
                "target_id": r["id"],
                "target_doc_type": r.get("doc_type") or "invoice",
                "at": deleted_at,
            } for r in to_flip_rows], ordered=False)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"invoice.bulk_soft_delete audit insert_many failed: "
                f"{type(e).__name__}: {e}"
            )

    # 4. Build the response — same shape as the prior handler so the
    # FE code path is unchanged.
    deleted = list(to_flip_ids)
    # Already-deleted rows return as {ok, already_deleted: true} in
    # the prior per-row path — preserve semantics: they count as
    # "deleted" (idempotent), but tagged for the UI's benefit.
    for aid in already_deleted_ids:
        deleted.append(aid)
    failed: List[dict] = [
        {"id": qid, "reason": "Invoice not found", "status_code": 404}
        for qid in ids if qid not in found_ids
    ]
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# Phase 34 · Task BB · Feb 2026 — Payments bulk-select soft-delete.
# Payments are stored as quotes with ``payment_status in {paid, partial,
# processing}`` — there is no separate collection. "Deleting" a payment
# reverts the row back to ``unpaid`` and zeroes ``amount_paid``, while
# tagging ``payment_deleted_at`` for the archive view. Stripe-linked
# rows (``payment_intent_id`` set) refuse deletion — those payouts
# have already cleared to the bank and reversing them is a Stripe
# operation the admin must run through the dashboard.
# ═════════════════════════════════════════════════════════════════════════
_STRIPE_LOCKED_METHODS = {"stripe", "card"}


async def _perform_delete_payment(pid: str, user: dict, tenant: dict,
                                    deletion_reason: Optional[str] = None,
                                    allow_stripe_override: bool = False) -> dict:
    """Revert a paid invoice back to ``unpaid`` — the "delete a payment"
    semantics on this platform.

    Feb-2026 · Item 3 behavior change: Stripe-linked / card-linked rows
    are NO LONGER blocked when invoked via the new
    ``DELETE /api/payments/{id}`` REST endpoint (super-admin/admin
    override — user explicitly decided to allow this per Item-3 spec).
    The audit entry stamps a ``stripe_reconciliation_note`` when the
    original row carried a Stripe / Lumino identifier so the ledger
    remains reconcilable.

    The legacy bulk-delete path leaves ``allow_stripe_override=False``
    so the existing Stripe safety-guard behavior is untouched for
    that surface.
    """
    doc = await db.quotes.find_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "Payment not found")
    if doc.get("payment_deleted_at"):
        return {"ok": True, "id": pid, "already_deleted": True}

    stripe_note: Optional[str] = None

    if not allow_stripe_override:
        # Legacy bulk path — hard-block Stripe / Lumino rows so batch
        # operations can't accidentally erase records still tracked
        # externally.
        if doc.get("payment_intent_id"):
            raise HTTPException(
                409, "Payment is linked to a cleared Stripe charge — reverse via Stripe dashboard",
            )
        if (doc.get("lumino_transaction_id")
                or doc.get("lumino_payment_session_id")
                or doc.get("lumino_subscription_id")):
            raise HTTPException(
                409, "Payment is linked to a Lumino transaction — reverse via the Lumino dashboard",
            )
        method = (doc.get("payment_method") or "").lower()
        if method in _STRIPE_LOCKED_METHODS and (doc.get("payment_status") or "").lower() == "paid":
            raise HTTPException(
                409, "Card/Stripe payments cannot be bulk-deleted — refund via the invoice detail page",
            )
    else:
        # Feb-2026 · Item 3 override — user decision: ALLOW delete for
        # Stripe-settled payments (no refund issued via API). Stamp a
        # reconciliation note so auditors see the disconnect.
        pi_id = doc.get("payment_intent_id")
        if pi_id:
            stripe_note = (
                f"Stripe payment {pi_id} deleted locally on "
                f"{now_iso()} — no refund issued via Stripe. "
                "Refund separately in Stripe dashboard if required."
            )
        elif (doc.get("lumino_transaction_id")
              or doc.get("lumino_payment_session_id")
              or doc.get("lumino_subscription_id")):
            lz_id = (doc.get("lumino_transaction_id")
                     or doc.get("lumino_payment_session_id")
                     or doc.get("lumino_subscription_id"))
            stripe_note = (
                f"Lumino payment {lz_id} deleted locally on "
                f"{now_iso()} — reverse separately in the Lumino "
                "dashboard if required."
            )

    if (doc.get("payment_status") or "").lower() == "unpaid":
        raise HTTPException(400, "Nothing to delete — this invoice has no recorded payment")

    deleted_at = now_iso()
    updates: Dict[str, Any] = {
        "payment_status": "unpaid",
        "amount_paid": 0.0,
        "paid_at": None,
        "payment_deleted_at": deleted_at,
        "payment_deleted_by_user_id": user.get("id"),
        "payment_deleted_prior_status": doc.get("payment_status"),
        "payment_deleted_prior_amount_paid": doc.get("amount_paid") or 0.0,
        "payment_deletion_reason": deletion_reason,
    }
    if stripe_note:
        updates["stripe_reconciliation_note"] = stripe_note
    await db.quotes.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    try:
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "actor_user_id": user.get("id"),
            "actor_email": user.get("email"),
            "action": "payment.soft_delete",
            "target_id": pid,
            "prior_status": doc.get("payment_status"),
            "prior_amount_paid": doc.get("amount_paid") or 0.0,
            "at": deleted_at,
        })
    except Exception as e:
        logger.warning(f"payment.soft_delete audit failed: {e}")
    # Feb-2026 · Item 3 — richer audit surface. Snapshot the pre-delete
    # doc so restore can put ``payment_status`` + ``amount_paid`` back.
    try:
        from routers.deletion_audit import write_deletion_audit_entry
        await write_deletion_audit_entry(
            tenant_id=tenant["id"],
            resource_type="payment",
            resource_id=pid,
            user=user,
            snapshot=doc,
            deletion_reason=deletion_reason,
            stripe_reconciliation_note=stripe_note,
        )
    except Exception as e:
        logger.warning(f"deletion_audit payment insert failed: {e}")
    return {"ok": True, "id": pid, "deleted_at": deleted_at,
              "stripe_reconciliation_note": stripe_note}


@router.post("/payments/bulk-delete",
              operation_id="payments.bulkDelete")
async def bulk_delete_payments(body: _InvoiceBulkDeleteIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    """Bulk-revert payment status on paid invoices. Financial-state
    guardrails match the single-record semantics — Stripe-linked
    payments refuse; the failures are surfaced in ``failed[]`` so
    admins see the count of "locked" rows without the whole batch
    aborting."""
    if body.query_selector is not None:
        ids = await _resolve_invoice_ids(
            body.query_selector, body.exclude_ids or [],
            tenant["id"], doc_type="invoice",
        )
    else:
        ids = list(body.ids or [])
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _BULK_DELETE_CAP:
        raise HTTPException(400, f"bulk-delete capped at {_BULK_DELETE_CAP} rows per call")
    ids = list(dict.fromkeys(ids))  # idempotency
    deleted: List[str] = []
    failed: List[dict] = []
    for pid in ids:
        try:
            r = await _perform_delete_payment(pid, user, tenant)
            deleted.append(r["id"])
        except HTTPException as e:
            failed.append({"id": pid, "reason": str(e.detail),
                              "status_code": e.status_code})
        except Exception as e:                                # noqa: BLE001
            failed.append({"id": pid, "reason": str(e), "status_code": 500})
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


# ═════════════════════════════════════════════════════════════════════════
# Feb-2026 · Item 3 — REST-canonical DELETE endpoints for invoices +
# payments. Thin wrappers over the existing soft-delete helpers, plus:
#   * ``deletion_reason`` query param carried into the audit entry
#   * ``DELETE /api/payments/{id}`` uses the Stripe-override path per
#     the user's explicit decision — allow the local delete + stamp
#     a reconciliation note.
# Gate: admin + super_admin only (no manager, no owner). Matches the
# user's Item-3 spec verbatim.
# ═════════════════════════════════════════════════════════════════════════
def _require_admin_or_super(user: dict) -> None:
    role = ((user or {}).get("role") or "").lower()
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_or_super_admin_only")


@router.delete("/invoices/{qid}", operation_id="invoices.delete")
async def delete_invoice(qid: str,
                          deletion_reason: Optional[str] = Query(None),
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    """REST-canonical soft-delete for an invoice. Cascade side-effect
    is inherent in this codebase — the payment IS the invoice row —
    so the audit entry lists cascade_deleted_ids=[]. Reads that need
    to un-apply the payment separately should call
    ``DELETE /api/payments/{id}`` first.
    """
    _require_admin_or_super(user)
    return await _perform_soft_delete_quote(
        qid, user, tenant, deletion_reason=deletion_reason,
    )


@router.delete("/payments/{qid}", operation_id="payments.delete")
async def delete_payment(qid: str,
                          deletion_reason: Optional[str] = Query(None),
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    """REST-canonical soft-delete for a payment. Reverts
    ``payment_status`` → ``unpaid`` and clears ``amount_paid``.
    Feb-2026 · Item 3 — Stripe-settled payments ARE deleted here (per
    user's explicit override); a reconciliation note is stamped on
    the row so the ledger stays auditable.
    """
    _require_admin_or_super(user)
    return await _perform_delete_payment(
        qid, user, tenant,
        deletion_reason=deletion_reason,
        allow_stripe_override=True,
    )
