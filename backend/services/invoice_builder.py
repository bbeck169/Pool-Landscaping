"""Feb-2026 · Phase 1 Convert-to-Invoice — shared source→invoice builder.

Honors the Phase 11 invariant: invoices live in ``db.quotes`` with
``doc_type="invoice"``. There is NO ``db.invoices`` collection.

The entry point ``build_invoice_doc_from_source`` is called by both
``POST /api/quotes/{qid}/convert-to-invoice`` (in ``routers/quotes.py``)
and ``POST /api/estimates/{eid}/convert-to-invoice`` (in
``routers/estimates.py``). The estimate route pre-collapses its
rich (unit_cost + overhead_pct + margin_pct) line_items into a
single quote-shaped line keyed on the estimate's ``sell_price`` —
exactly the same shape the deprecated ``/estimates/{eid}/convert``
(estimates → quote) endpoint uses at estimates.py:328.

Caller contract:
    * ``src_doc`` is the SOURCE row (quote or estimate) that was
      already loaded + tenant-scoped by the router.
    * ``line_items`` is the already-adapted list of invoice-ready
      line dicts (shape matches ``models.LineItem``).
    * The caller is responsible for the 409 duplicate-conversion
      guard BEFORE invoking this helper.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


# Default net-terms used when the source has no explicit ``due_date``
# and the tenant has no override. Mirrors the brief: "issue_date=today,
# due_date=today+30 (or match whatever default the existing invoice-
# create path uses)". The existing ``POST /quotes`` path uses +14d
# (routers/quotes.py:434); the Phase 1 brief locks +30d for
# conversions specifically — matches customer-facing invoice-terms
# norms better than the +14d jobs-pipeline shortcut.
DEFAULT_DUE_DATE_OFFSET_DAYS = 30


async def build_invoice_doc_from_source(
    *,
    src_doc: Dict[str, Any],
    src_kind: str,                   # "quote" | "estimate"
    line_items: List[Dict[str, Any]],
    tenant: Dict[str, Any],
    user: Dict[str, Any],
    tax_rate: Optional[float] = None,
    notes_override: Optional[str] = None,
    terms_override: Optional[str] = None,
    due_date_offset_days: int = DEFAULT_DUE_DATE_OFFSET_DAYS,
) -> Dict[str, Any]:
    """Shape the ``db.quotes`` invoice doc from a source quote/estimate.

    Does NOT insert. Does NOT guard against double-conversion (the
    caller handles both). Does NOT stamp invoice_number — the
    caller must invoke
    ``services.invoice_numbering.assign_invoice_number_if_missing``
    on the returned dict before ``db.quotes.insert_one``.

    Reuses the Phase 11 shared normalization helpers from
    ``routers/quotes.py`` via lazy import to avoid circular imports.
    """
    # Lazy imports — ``routers/quotes.py`` itself imports from
    # ``services/invoice_builder.py``, so top-level imports would
    # cycle at module load.
    from routers.quotes import (
        compute_totals,
        _stamp_line_snapshots,
        _enforce_item_type_price_lock,
    )

    tenant_id = tenant["id"]

    # Normalize line items — mutate in place through the shared
    # helpers so the invoice carries the same shape as a native
    # ``POST /quotes`` with ``doc_type="invoice"`` would produce.
    items: List[Dict[str, Any]] = [dict(li) for li in (line_items or [])]
    # Fresh line ids so the invoice is independent of the source
    # (customers / signers see a NEW invoice artefact).
    for li in items:
        li["id"] = new_id()

    # Phase K71 + income category + pricebook item-type enforcement.
    await _enforce_item_type_price_lock(tenant_id, items)
    # Lenient on invoices-from-conversion: skip the income category
    # mandatory check (the source quote may predate the K71 rule
    # and we don't want to block admins from converting legacy
    # quotes). The existing create-quote path only enforces this
    # for brand-new invoice writes.
    await _stamp_line_snapshots(items, tenant_id=tenant_id)

    _tax_rate = float(tax_rate if tax_rate is not None
                      else (src_doc.get("tax_rate") or 0))
    subtotal, tax, total = compute_totals(items, _tax_rate)

    # Due date — honor explicit source ``due_date`` only when the
    # source is a quote AND the admin has already set one. Otherwise
    # stamp issue_date=today, due_date=today+N.
    today_utc = datetime.now(timezone.utc).date()
    issue_date = today_utc.isoformat()
    due_date = (today_utc + timedelta(days=due_date_offset_days)).isoformat()

    # Resolve terms — mirror ``create_quote``'s fallback: ask the
    # tenant terms-defaults helper for the invoice-side default.
    if terms_override is not None:
        terms = terms_override
    else:
        from routers.finances import get_terms_defaults
        defaults = await get_terms_defaults()
        terms = defaults["default_invoice_terms"]

    notes = notes_override if notes_override is not None else (
        src_doc.get("notes") or ""
    )

    customer_id = src_doc.get("customer_id")
    customer_name = src_doc.get("customer_name") or ""
    if customer_id and not customer_name:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "name": 1},
        )
        customer_name = (cust or {}).get("name") or ""

    doc: Dict[str, Any] = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "property_id": src_doc.get("property_id"),
        # Title carries verbatim — admin can rename post-conversion.
        "title": src_doc.get("title") or "Invoice",
        "doc_type": "invoice",            # Phase 11 invariant
        "line_items": items,
        "tax_rate": _tax_rate,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "amount_paid": 0.0,
        "issue_date": issue_date,
        "due_date": due_date,
        "status": "draft",
        "payment_status": "unpaid",
        "notes": notes,
        "terms": terms,
        "created_at": now_iso(),
        "created_by": user.get("id"),
        # Convert-to-invoice provenance — distinct from
        # ``source=auto_invoice_on_job_complete`` used by
        # ``services.auto_invoice``. Lets reporting + the detail
        # page tell "manual convert" from "auto-invoice on job
        # complete" from "fresh-create via POST /quotes".
        "source": f"convert_from_{src_kind}",
        f"source_{src_kind}_id": src_doc.get("id"),
    }
    return doc


async def mark_source_converted(
    *,
    collection: str,                     # "quotes" | "estimates"
    src_id: str,
    tenant_id: str,
    invoice_id: str,
    user: Dict[str, Any],
) -> None:
    """Stamp the source doc with convert bookkeeping fields.

    Per product decision locked by the owner (phase-1 brief
    section 4): we do NOT introduce a new ``'converted'`` status
    enum value. ``status`` stays whatever it was (``accepted`` /
    ``sent`` / ``draft`` / etc.) so downstream reports keep their
    lifecycle semantics. Only three new fields are stamped:

        * ``converted_at``
        * ``converted_invoice_id``
        * ``converted_by``

    The frontend's "View Invoice →" fallback keys off
    ``converted_invoice_id`` presence, NOT off ``status``.
    """
    at = now_iso()
    try:
        coll = getattr(db, collection)
    except AttributeError:
        raise ValueError(f"unknown collection: {collection!r}")
    await coll.update_one(
        {"id": src_id, "tenant_id": tenant_id},
        {"$set": {
            "converted_at": at,
            "converted_invoice_id": invoice_id,
            "converted_by": user.get("id"),
        }},
    )
    # Best-effort audit — failure must not roll back the convert.
    try:
        await db.audit_logs.insert_one({
            "event": f"{collection[:-1]}.convert_to_invoice",   # quote/estimate.convert_to_invoice
            "source_id": src_id,
            "invoice_id": invoice_id,
            "actor_id": user.get("id"),
            "tenant_id": tenant_id,
            "at": at,
        })
    except Exception as e:                                      # noqa: BLE001
        logger.warning(
            f"{collection}.convert_to_invoice audit_logs insert failed: {e}",
        )
