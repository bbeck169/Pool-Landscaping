"""Task H · Phase H.2 · Feb-2026 — PDF importer commit + rollback service.

Two public entry points (called from
``backend/routers/imports.py``):

  * :func:`commit_batch` — take a ``preview_complete`` import
    batch and materialise every mapper-produced ``QuoteIn``
    preview into ``db.quotes``.
  * :func:`rollback_batch` — hard-delete every quote/invoice
    a prior ``commit_batch`` inserted for the same
    ``import_batch_id`` and stamp an ``import_audit`` row.

Plus a pre-flight helper:

  * :func:`check_duplicates` — dry-run duplicate scan that both
    ``commit_batch(options.on_duplicate="fail")`` and
    ``GET /api/imports/pdf-invoice/{batch_id}/duplicates``
    reuse.

Semantics locked in Task H.2.A halt report + Phase H.2.B
rulings:

  §A · Customer-facing hook suppression
      ``create_quote`` fires FOUR customer-facing hooks after
      inserting an invoice: Lumino Zapier payment-link dispatch,
      ``automation_engine.emit("invoice.created")``, marketing
      drip event ``invoice_sent``, and the schema-v2 event
      dispatcher ``invoice_sent``.  For imported historicals we
      must NOT re-notify customers about an invoice from 2023.
      We bypass ``create_quote`` entirely and build the doc
      here so those hooks never fire.  Hook 1 (pricebook
      writeback) is data-integrity — it runs for lines that
      opt-in via ``pricebook_writeback=True``.

  §A · Extra field preservation
      * ``doc_number`` from ``quote_in`` becomes the persisted
        ``invoice_number`` — we NEVER auto-assign a new
        sequential number on imports.
      * ``payment_status`` preserved from ``quote_in`` when
        present; falls back to ``"unpaid"``.
      * ``paid_at`` preserved from
        ``mapper_report.pending_payment_actions[0]``.
      * ``status`` defaults to ``"sent"`` (historicals were
        sent to customers by definition), overridable via a
        ``quote_in.status`` if the mapper ever ships that
        field.

  §A · PENDING sentinel gate
      Commit refuses to run if any ``mapper_previews[*].quote_in.customer_id``
      still carries the ``PENDING::`` prefix.  400
      ``unresolved_customers`` with the list of
      ``(source_doc_index, extracted_customer_name)`` tuples.

  §C · Idempotency
      Every inserted quote carries ``import_batch_id`` +
      ``import_source_doc_index``.  On a re-run of commit
      (e.g. after a mid-flight crash), we skip previews whose
      ``(batch_id, source_doc_index)`` already exists in
      ``db.quotes``.

  §D · No Mongo transactions
      One ``insert_many(ordered=False)`` per commit batch.
      Errors surface via ``BulkWriteError.details`` — we
      sanitise into ``{source_doc_index, error_code, message}``
      tuples before returning.

  §F · Duplicate detection
      ``on_duplicate ∈ {"skip", "insert_anyway", "fail"}``:
        - ``skip`` (default) — drop the preview from the batch,
          record it in ``duplicates_detected``.
        - ``insert_anyway`` — insert regardless (admin override).
        - ``fail`` — dry-run duplicates first; if any hit, 409
          without inserting anything.

  §G · Rollback collision snapshotting
      If any quote about to be deleted has ``updated_at >
      commit_at`` (someone edited the imported invoice after
      commit), snapshot the FULL doc into the
      ``import_audit.collisions`` array before deleting.  Non-
      colliding rollbacks skip the snapshot to keep audit rows
      light.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import BulkWriteError

from utils import new_id


logger = logging.getLogger("imports.pdf_commit")


# ── Public status enum surface ─────────────────────────────
# Mirrors ``routers.imports._STATUS_*`` — duplicated locally to
# avoid a circular import (router imports us, we don't want to
# import router).
_STATUS_PREVIEW_COMPLETE = "preview_complete"
_STATUS_COMMITTING = "committing"
_STATUS_COMMITTED = "committed"
_STATUS_COMMIT_FAILED = "commit_failed"
_STATUS_ROLLING_BACK = "rolling_back"
_STATUS_ROLLED_BACK = "rolled_back"
_STATUS_ROLLBACK_FAILED = "rollback_failed"


# ── on_duplicate options ───────────────────────────────────
_DUP_SKIP = "skip"
_DUP_INSERT_ANYWAY = "insert_anyway"
_DUP_FAIL = "fail"
_DUP_VALID = frozenset({_DUP_SKIP, _DUP_INSERT_ANYWAY, _DUP_FAIL})


# ═════════════════════════════════════════════════════════════
# Public dataclasses
# ═════════════════════════════════════════════════════════════
@dataclass
class DuplicateWarning:
    """One preview that collides with an existing quote."""
    source_doc_index: int
    existing_quote_id: str
    doc_number: Optional[str]
    customer_id: str


@dataclass
class UnresolvedCustomer:
    """One preview that still carries a ``PENDING::`` sentinel."""
    source_doc_index: int
    extracted_customer_name: Optional[str]
    pending_customer_id: Optional[str]


@dataclass
class CommitResult:
    quotes_created: int
    quotes_skipped_duplicates: int
    quotes_skipped_idempotent: int
    quote_ids: List[str] = field(default_factory=list)
    duplicates_detected: List[DuplicateWarning] = field(default_factory=list)
    insert_errors: List[Dict[str, Any]] = field(default_factory=list)
    audit_id: Optional[str] = None
    # ═══════════════════════════════════════════════════════════
    # PDF Importer Sub-phase C · Feb-2026 — per-doc-type breakdown.
    # ``quotes_created`` above stays as the sum of invoices +
    # estimates for backward compat with routers.imports and the
    # audit trail. The fields below give the caller per-type
    # buckets so the commit response can render "3 invoices, 1
    # estimate, 2 payments (1 linked)" without re-scanning
    # ``mapper_previews``.
    # ═══════════════════════════════════════════════════════════
    invoices_created: int = 0
    estimates_created: int = 0
    payments_created: int = 0
    payments_updated: int = 0
    payments_unlinked: int = 0
    payment_ids: List[str] = field(default_factory=list)
    payment_errors: List[Dict[str, Any]] = field(default_factory=list)
    # FIN-PARITY-A · Feb-2026 — invoice reconciliation summaries.
    # One entry per payment that carried an ``invoice_id`` and
    # successfully reconciled. Shape matches
    # ``ReconcileResult.to_dict()`` for wire stability.
    reconciled_invoices: List[Dict[str, Any]] = field(default_factory=list)
    # Per-doc-type warnings (missing doc_date on invoice / missing
    # amount_paid on payment / unknown doc_kind / etc). Non-blocking
    # — surfaced to the operator via the commit response for
    # follow-up but the offending row still lands.
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    # ═══════════════════════════════════════════════════════════
    # Phase 33 Step B · Feb-2026 — PDF-import customer auto-create.
    #
    # ``auto_created_customers`` carries one entry per PENDING
    # sentinel resolved during commit — new ``db.customers`` row
    # inserted OR dedupe hit against an existing row (both DB-side
    # and in-batch). Shape mirrors
    # ``AutoCreatedCustomer.__dataclass_fields__`` for wire
    # stability.
    #
    # The commit path now raises ``UnresolvedCustomersError`` ONLY
    # for pending rows the auto-create helper could not resolve
    # (zero-signal rows: no name, no address, no phone). All other
    # PENDING sentinels are rewritten to real customer_ids before
    # the unresolved gate fires.
    # ═══════════════════════════════════════════════════════════
    auto_created_customers: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RollbackResult:
    quotes_deleted: int
    collision_count: int
    collision_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    audit_id: Optional[str] = None


# ═════════════════════════════════════════════════════════════
# Duplicate detection
# ═════════════════════════════════════════════════════════════
async def check_duplicates(
    *,
    previews: List[Dict[str, Any]],
    tenant_id: str,
    db,
) -> List[DuplicateWarning]:
    """Scan every mapper preview for a collision against
    ``db.quotes`` on ``(tenant_id, customer_id, doc_type,
    import_source_doc_number)``.

    Only invoices with a ``doc_number`` participate in dedup —
    a preview without ``doc_number`` can never collide.  Payment
    receipts (``mapped_target=deferred_to_h4``) are skipped
    entirely.
    """
    hits: List[DuplicateWarning] = []

    for preview in previews:
        if preview.get("mapped_target") != "quote_in":
            continue
        qi = preview.get("quote_in") or {}
        doc_number = qi.get("doc_number") or _extract_doc_number_from_title(
            qi.get("title"),
        )
        if not doc_number:
            continue
        customer_id = qi.get("customer_id") or ""
        if customer_id.startswith("PENDING::"):
            continue  # can't dedupe on a sentinel — separate gate
        existing = await db.quotes.find_one(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "doc_type": qi.get("doc_type") or "invoice",
                "import_source_doc_number": doc_number,
            },
            {"_id": 0, "id": 1},
        )
        if existing:
            hits.append(
                DuplicateWarning(
                    source_doc_index=int(preview.get("source_doc_index", -1)),
                    existing_quote_id=existing["id"],
                    doc_number=doc_number,
                    customer_id=customer_id,
                )
            )
    return hits


def _extract_doc_number_from_title(title: Optional[str]) -> Optional[str]:
    """Mapper writes ``"Import #<doc_number>"`` into ``title``
    when the extractor found a doc_number.  If we ever get here
    with no dedicated ``doc_number`` field on ``quote_in``, this
    helper is the fallback."""
    if not title or not title.startswith("Import #"):
        return None
    return title[len("Import #"):].strip() or None


# ═════════════════════════════════════════════════════════════
# Unresolved-customer gate (§A extra)
# ═════════════════════════════════════════════════════════════
def collect_unresolved_customers(
    previews: List[Dict[str, Any]],
) -> List[UnresolvedCustomer]:
    """Return every preview still carrying a ``PENDING::``
    customer_id.  Commit refuses to run when this list is
    non-empty."""
    out: List[UnresolvedCustomer] = []
    for preview in previews:
        if preview.get("mapped_target") != "quote_in":
            continue
        qi = preview.get("quote_in") or {}
        cid = qi.get("customer_id") or ""
        if not cid.startswith("PENDING::"):
            continue
        out.append(UnresolvedCustomer(
            source_doc_index=int(preview.get("source_doc_index", -1)),
            extracted_customer_name=qi.get("customer_name"),
            pending_customer_id=preview.get("pending_customer_id"),
        ))
    return out


# ═════════════════════════════════════════════════════════════
# Phase 33 Step C.1 · Feb-2026 — GET preview classification.
# ═════════════════════════════════════════════════════════════
async def classify_pending_for_preview(
    *,
    previews: List[Dict[str, Any]],
    tenant_id: str,
    db,
) -> Dict[str, List[Dict[str, Any]]]:
    """Dry-run classify every ``PENDING::<uuid>`` sentinel in a
    preview-complete batch as either ``will_auto_create`` or
    ``will_require_manual_review`` so the operator UI can render
    a "Will auto-create: N" badge BEFORE clicking Commit.

    No side-effects: pure read against ``pending_import_customers``.
    Mirrors the Step B classification rules exactly:

      * At least one of ``extracted_customer_name`` /
        ``extracted_address`` / ``extracted_phone`` is non-blank
        → ``will_auto_create`` (the commit path will materialise
        this pending into a real ``db.customers`` row via the
        dedupe-first auto-create helper).
      * All three identifying fields are blank, OR the pending
        row has been manually deleted since mapping →
        ``will_require_manual_review`` (the commit path raises
        400 ``manual_review_required`` listing these rows).

    Shape (both arrays carry the same per-row dict shape so the
    FE can render one unified table)::

        {
          "will_auto_create": [
            {
              "source_doc_index": 3,
              "pending_customer_id": "<uuid>",
              "extracted_name": "Acme Pools LLC",
              "extracted_address": "123 Pine Dr",
              "extracted_phone": "555-1234",
            },
            ...
          ],
          "will_require_manual_review": [
            {"source_doc_index": 7, "pending_customer_id": "<uuid>",
              "extracted_name": null, "extracted_address": null,
              "extracted_phone": null, "reason": "no_identifying_info"},
            ...
          ],
        }
    """
    # Walk BOTH quote_in and payment_in — mirror Step B's walk so
    # the dry-run never misses a sentinel the real auto-create
    # would resolve.
    ref_order: List[Tuple[str, int]] = []
    seen_pids: set = set()
    for preview in previews:
        source_doc_index = int(preview.get("source_doc_index", -1))
        for field_name in ("quote_in", "payment_in"):
            sub = preview.get(field_name) or {}
            cid = sub.get("customer_id") or ""
            if not (isinstance(cid, str) and cid.startswith("PENDING::")):
                continue
            pending_id = cid[len("PENDING::"):]
            if pending_id in seen_pids:
                continue
            seen_pids.add(pending_id)
            ref_order.append((pending_id, source_doc_index))

    if not ref_order:
        return {"will_auto_create": [], "will_require_manual_review": []}

    # One ``find`` with ``$in`` — bounded working set.
    pending_rows: Dict[str, Dict[str, Any]] = {}
    cursor = db.pending_import_customers.find(
        {"tenant_id": tenant_id,
          "id": {"$in": [pid for pid, _ in ref_order]}},
        {"_id": 0},
    )
    async for row in cursor:
        pending_rows[row["id"]] = row

    will_auto: List[Dict[str, Any]] = []
    manual: List[Dict[str, Any]] = []
    for pending_id, source_doc_index in ref_order:
        row = pending_rows.get(pending_id)
        if row is None:
            manual.append({
                "source_doc_index": source_doc_index,
                "pending_customer_id": pending_id,
                "extracted_name": None,
                "extracted_address": None,
                "extracted_phone": None,
                "reason": "pending_row_missing",
            })
            continue
        name = row.get("extracted_customer_name") or ""
        address = row.get("extracted_address") or ""
        phone = row.get("extracted_phone") or ""
        has_signal = bool((name or "").strip()
                            or (address or "").strip()
                            or (phone or "").strip())
        payload = {
            "source_doc_index": source_doc_index,
            "pending_customer_id": pending_id,
            "extracted_name": name or None,
            "extracted_address": address or None,
            "extracted_phone": phone or None,
        }
        if row.get("resolved_customer_id"):
            # Prior commit attempt already resolved — treat as
            # will_auto_create so the FE badge still counts it.
            payload["prior_resolved_customer_id"] = row[
                "resolved_customer_id"
            ]
            will_auto.append(payload)
        elif has_signal:
            will_auto.append(payload)
        else:
            payload["reason"] = "no_identifying_info"
            manual.append(payload)

    return {
        "will_auto_create": will_auto,
        "will_require_manual_review": manual,
    }


# ═════════════════════════════════════════════════════════════
# PDFI-PAID-B · Feb-2026 — paid-status validation helper.
# PDFI-PAID-C · Feb-2026 — auto-heal preamble.
# ═════════════════════════════════════════════════════════════
def _autoheal_paid_status(
    previews: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Auto-fill ``paid_at`` + ``amount_paid`` for ``is_paid=True``
    previews that are missing those fields but have a sensible
    fallback source available.

    Fallback sources (first-match-wins):
      * ``paid_at`` ← ``quote_in.doc_date`` → else ``quote_in.created_at``.
      * ``amount_paid`` ← ``quote_in.grand_total`` → else
        ``quote_in.total_due``.

    Rationale: historical paid invoices often carry a visible
    ``PAID`` watermark but no explicit payment-date / amount-paid
    line. The extractor is contractually allowed to return
    ``paid_at=None`` / ``amount_paid=None`` for such rows (prompt
    rule in ``pdf_invoice_extractor.py`` lines 215-219). Prior to
    this helper, commit rejected those rows with a hard 422 that
    the operator had to resolve one at a time via PATCH /preview.
    Auto-heal preserves operator intent (the invoice IS paid) and
    stamps the invoice's own ``doc_date`` as the payment date +
    the ``grand_total`` as the paid amount — the canonical
    historical-import interpretation.

    Mutates each healed preview's ``quote_in`` in place:
      * Writes the healed value onto ``paid_at`` / ``amount_paid``.
      * Appends to ``quote_in["_import_metadata"]["auto_healed_fields"]``
        (list of field names actually touched).
      * Mirrors the healed values onto the preview's
        ``payment_in`` dict (built by the mapper during preview)
        so the downstream ``db.payments`` write uses the healed
        values too.

    Returns the list of (preview, healed_fields) pairs for the
    audit log + the enriched 422 payload the router consumes
    when a row remains unhealable.
    """
    healed: List[Dict[str, Any]] = []
    for p in previews:
        qi = p.get("quote_in") or {}
        if qi.get("is_paid") is not True:
            continue
        row_healed: List[str] = []
        # paid_at — prefer doc_date → created_at
        if not qi.get("paid_at"):
            fallback = qi.get("doc_date") or qi.get("created_at")
            if fallback:
                fallback_iso = str(fallback)[:10]  # YYYY-MM-DD slice
                qi["paid_at"] = fallback_iso
                row_healed.append("paid_at")
                # Keep payment_in in sync so pdf_commit's payment
                # loop writes the healed value too.
                pi = p.get("payment_in") or None
                if isinstance(pi, dict) and not pi.get("paid_at"):
                    pi["paid_at"] = fallback_iso
                logger.info(
                    "pdf_import.commit.autoheal paid_at row=%s "
                    "source=%s value=%s",
                    p.get("source_doc_index"),
                    "doc_date" if qi.get("doc_date") else "created_at",
                    fallback_iso,
                )
        # amount_paid — prefer grand_total → total_due
        amt = qi.get("amount_paid")
        if amt in (None, 0, 0.0):
            fallback_amt = qi.get("grand_total")
            fallback_source = "grand_total"
            if fallback_amt in (None, 0, 0.0):
                fallback_amt = qi.get("total_due")
                fallback_source = "total_due"
            try:
                fallback_amt_f = (
                    float(fallback_amt) if fallback_amt is not None else 0.0
                )
            except (TypeError, ValueError):
                fallback_amt_f = 0.0
            if fallback_amt_f > 0:
                qi["amount_paid"] = fallback_amt_f
                row_healed.append("amount_paid")
                pi = p.get("payment_in") or None
                if isinstance(pi, dict) and (
                    pi.get("amount_paid") in (None, 0, 0.0)
                ):
                    pi["amount_paid"] = fallback_amt_f
                logger.info(
                    "pdf_import.commit.autoheal amount_paid row=%s "
                    "source=%s value=%s",
                    p.get("source_doc_index"), fallback_source,
                    fallback_amt_f,
                )
        if row_healed:
            # Attach provenance metadata — this surfaces on the
            # persisted invoice/payment doc so operators can audit
            # which rows the commit healed vs honored verbatim.
            meta = qi.setdefault("_import_metadata", {})
            prior = list(meta.get("auto_healed_fields") or [])
            # dedupe while preserving order
            seen = set(prior)
            for f in row_healed:
                if f not in seen:
                    prior.append(f)
                    seen.add(f)
            meta["auto_healed_fields"] = prior
            healed.append({
                "source_doc_index": p.get("source_doc_index"),
                "fields": list(row_healed),
            })
    return healed


def _validate_paid_status(
    previews: List[Dict[str, Any]],
) -> Optional[Tuple[str, List[int]]]:
    """Return ``(error_code, [doc_indices])`` on the first
    paid-status rule violation, else ``None``.

    Rules (both required when ``quote_in.is_paid is True``):
      * ``paid_at`` must be truthy — else ``paid_without_date``.
      * ``amount_paid`` must be > 0 — else
        ``paid_without_amount``.

    All indices for ONE error code are aggregated so the
    operator sees every offending row in a single 422 reply.

    PDFI-PAID-C · Feb-2026 — this gate now runs AFTER
    ``_autoheal_paid_status`` has had a chance to backfill
    ``paid_at`` + ``amount_paid`` from the row's own
    ``doc_date`` + ``grand_total``. Only rows the auto-heal
    pass could not rescue reach this error path.
    """
    without_date: List[int] = []
    without_amount: List[int] = []
    for p in previews:
        qi = p.get("quote_in") or {}
        if qi.get("is_paid") is not True:
            continue
        idx = int(p.get("source_doc_index", -1))
        if not qi.get("paid_at"):
            without_date.append(idx)
            continue  # don't double-report on the same row
        amt = qi.get("amount_paid")
        if amt in (None, 0, 0.0):
            without_amount.append(idx)
    if without_date:
        return ("paid_without_date", without_date)
    if without_amount:
        return ("paid_without_amount", without_amount)
    return None


def _build_paid_status_row_details(
    previews: List[Dict[str, Any]],
    err_code: str,
    idxs: List[int],
) -> List[Dict[str, Any]]:
    """Build the per-row details list for the structured 422
    payload. One row per offending doc_index with the specific
    field + reason + value + is_paid + invoice_number so the FE
    can render actionable per-row error UX without having to
    cross-reference the preview array.
    """
    _field = "paid_at" if err_code == "paid_without_date" else "amount_paid"
    idx_set = set(idxs)
    rows: List[Dict[str, Any]] = []
    for p in previews:
        src = int(p.get("source_doc_index", -1))
        if src not in idx_set:
            continue
        qi = p.get("quote_in") or {}
        rows.append({
            "row_index": src,
            "field": _field,
            "reason": "missing_and_unhealed",
            "value": qi.get(_field),
            "is_paid": qi.get("is_paid") is True,
            "invoice_number": qi.get("doc_number"),
        })
    return rows


# ═════════════════════════════════════════════════════════════
# Commit
# ═════════════════════════════════════════════════════════════
async def commit_batch(
    *,
    batch: Dict[str, Any],
    tenant_id: str,
    operator: Dict[str, Any],
    on_duplicate: str = _DUP_SKIP,
    db,
) -> CommitResult:
    """Materialise every eligible preview into ``db.quotes``.

    Assumes the caller has already:
      * validated the batch belongs to ``tenant_id``,
      * confirmed the batch status is ``preview_complete``,
      * flipped the status to ``committing`` via
        ``find_one_and_update`` with the source status as guard
        (or is willing to accept a stale write).

    Caller is responsible for flipping status → ``committed``
    on success or ``commit_failed`` on exception AFTER this
    function returns.
    """
    if on_duplicate not in _DUP_VALID:
        raise ValueError(
            f"on_duplicate must be one of {sorted(_DUP_VALID)!r}, "
            f"got {on_duplicate!r}"
        )

    batch_id = batch.get("id") or batch.get("batch_id")
    previews: List[Dict[str, Any]] = batch.get("mapper_previews") or []
    commit_at = datetime.now(timezone.utc).isoformat()

    # ── Phase 33 Step B · Feb-2026 — auto-create PENDING customers.
    # Walk every ``PENDING::<uuid>`` sentinel BEFORE the unresolved
    # gate fires. The helper mutates ``previews`` in-place: resolved
    # pending rows have their ``quote_in.customer_id`` /
    # ``payment_in.customer_id`` rewritten to real customer_ids so
    # the downstream duplicate scan + paid-status checks +
    # insert_many loop see a fully resolved batch. Only pending rows
    # with zero identifying info (name AND address AND phone all
    # blank) survive to raise ``UnresolvedCustomersError``.
    from services.imports.customer_autocreate import (
        auto_create_pending_customers,
    )
    autocreate_result = await auto_create_pending_customers(
        previews=previews, batch=batch, tenant_id=tenant_id,
        operator=operator, db=db,
    )

    # ── Pre-flight: unresolved-customer gate ──────────────
    unresolved = collect_unresolved_customers(previews)
    if unresolved:
        # Not a CommitResult return — this is a caller-side
        # 400. Raise a plain ValueError for the router to
        # rewrap as HTTPException.
        raise UnresolvedCustomersError(unresolved)

    # ── Pre-flight: duplicate scan (MOVED-UP · Phase 33 Step A)
    # Moved BEFORE paid-status validation so the latter can filter
    # out previews destined to be skipped by ``on_duplicate=skip``.
    # Previously, a duplicate preview carrying ``is_paid=True`` with
    # missing paid_at / amount_paid tripped the 422 gate even when
    # the operator selected Skip — breaking batches that would
    # otherwise commit cleanly.  Idempotency scan (quotes already
    # inserted with this batch_id) also contributes to the skip set
    # so a resumed commit never re-raises 422 on an already-landed
    # row.
    duplicates = await check_duplicates(
        previews=previews, tenant_id=tenant_id, db=db,
    )
    if on_duplicate == _DUP_FAIL and duplicates:
        raise DuplicateBatchError(duplicates)

    dup_by_idx = {d.source_doc_index: d for d in duplicates}

    # Idempotency scan — collect indices of previews already
    # inserted so they too are excluded from paid-status
    # validation and from the per-row commit loop below.
    already_inserted_indexes: set = set()
    async for row in db.quotes.find(
        {"tenant_id": tenant_id, "import_batch_id": batch_id},
        {"_id": 0, "import_source_doc_index": 1},
    ):
        idx = row.get("import_source_doc_index")
        if idx is not None:
            already_inserted_indexes.add(int(idx))

    # ── Pre-flight: PDFI-PAID-B paid-status validation ───
    # Scan quote_in.is_paid=True previews for the two required
    # follow-on fields; reject (and let the router roll the
    # batch back to preview_complete) if either is missing.
    #
    # Phase 33 Step A · Feb-2026 — filter out previews destined
    # to be skipped (duplicate + on_duplicate=skip, or already
    # inserted via idempotency) BEFORE validating so skip-selected
    # rows no longer trigger 422.
    #
    # PDFI-PAID-C · Feb-2026 — auto-heal pass runs first so
    # ``paid_at`` + ``amount_paid`` get backfilled from
    # ``doc_date`` + ``grand_total`` where available. Only
    # unhealable rows reach the validation error.
    skip_idx_set = set(already_inserted_indexes)
    if on_duplicate == _DUP_SKIP:
        skip_idx_set.update(dup_by_idx.keys())
    _validation_targets = [
        p for p in previews
        if int(p.get("source_doc_index", -1)) not in skip_idx_set
    ]
    _healed_summary = _autoheal_paid_status(_validation_targets)
    if _healed_summary:
        logger.info(
            "pdf_import.commit.autoheal.summary batch=%s healed_count=%d "
            "details=%r",
            batch.get("id") or batch.get("batch_id"),
            len(_healed_summary), _healed_summary,
        )
    paid_err = _validate_paid_status(_validation_targets)
    if paid_err is not None:
        err_code, idxs = paid_err
        row_details = _build_paid_status_row_details(
            _validation_targets, err_code, idxs,
        )
        raise PaidStatusValidationError(err_code, idxs, row_details)

    # ── Build the doc list ────────────────────────────────
    to_insert: List[Dict[str, Any]] = []
    inserted_indexes: List[int] = []
    warnings: List[Dict[str, Any]] = []
    invoices_planned = 0
    estimates_planned = 0
    for preview in previews:
        source_doc_index = int(preview.get("source_doc_index", -1))
        if source_doc_index in already_inserted_indexes:
            continue
        mapped_target = preview.get("mapped_target")
        # PDF-C · Feb-2026 — payment_in previews are handled below
        # in a separate loop; deferred_to_h4 previews stay skipped
        # (only reachable now when a payment receipt was too
        # malformed for the mapper to build a payment_in).
        if mapped_target != "quote_in":
            continue
        qi = preview.get("quote_in") or {}
        if not qi:
            continue
        # Duplicate policy branch:
        if source_doc_index in dup_by_idx:
            if on_duplicate == _DUP_SKIP:
                continue
            # insert_anyway falls through.

        # Late nutrient — filter previews with errors (mapper
        # emitted a hard error; refuse to persist).
        if preview.get("errors"):
            continue

        doc = _build_quote_doc_from_preview(
            preview=preview, batch=batch,
            tenant_id=tenant_id, operator=operator,
            commit_at=commit_at,
        )
        # Recompute totals from the persisted lines so the
        # invoice matches the extractor's line totals exactly
        # (we did NOT trust the extractor's grand_total).
        _apply_totals(doc)

        # PDF-MIRROR · Feb-2026 — Refuse to silently commit a $0
        # invoice. When ``_apply_totals`` couldn't derive a
        # non-zero total from EITHER the extractor's verbatim
        # values OR the line-item recompute, the doc is
        # flagged ``zero_total_unrecoverable`` and pushed to the
        # needs_review warnings bucket rather than into the
        # quotes collection. Operator resolves manually.
        if doc.get("total_source") == "zero_total_unrecoverable":
            warnings.append({
                "source_doc_index": source_doc_index,
                "doc_type": doc.get("doc_type"),
                "code": "needs_review",
                "reason": "zero_total_unrecoverable",
                "message": (
                    "Extractor produced no grand_total AND recompute "
                    "from line items yielded $0.00 — invoice needs "
                    "operator review before commit. NOT persisted."
                ),
            })
            continue

        # PDF-C · Feb-2026 — per-doc-type warn-on-missing-fields.
        # doc_date + total_due for invoices and estimates alike;
        # ruling #7 says warn, do NOT block.
        if not qi.get("doc_date"):
            warnings.append({
                "source_doc_index": source_doc_index,
                "doc_type": doc.get("doc_type"),
                "code": "doc_date_missing",
                "message": "doc_date missing — commit used now() fallback.",
            })
        if qi.get("total_due") in (None, 0, 0.0):
            warnings.append({
                "source_doc_index": source_doc_index,
                "doc_type": doc.get("doc_type"),
                "code": "total_due_missing",
                "message": (
                    "total_due missing or zero — line-item recompute "
                    "will drive the persisted total."
                ),
            })

        to_insert.append(doc)
        inserted_indexes.append(source_doc_index)
        # PDF-C · per-type planning bucket (finalised after
        # insert_many succeeds so counts always match reality).
        if doc.get("doc_type") == "invoice":
            invoices_planned += 1
        else:
            estimates_planned += 1

    # ── Bulk insert ───────────────────────────────────────
    insert_errors: List[Dict[str, Any]] = []
    inserted_ids: List[str] = []
    if to_insert:
        try:
            await db.quotes.insert_many(to_insert, ordered=False)
            inserted_ids = [d["id"] for d in to_insert]
        except BulkWriteError as exc:
            # Extract per-doc write errors + the ids that DID land.
            details = exc.details or {}
            n_inserted = int(details.get("nInserted", 0) or 0)
            write_errors = details.get("writeErrors") or []
            failed_indexes_in_batch = {
                int(we.get("index", -1)) for we in write_errors
                if we.get("index") is not None
            }
            for pos, doc in enumerate(to_insert):
                if pos in failed_indexes_in_batch:
                    continue
                inserted_ids.append(doc["id"])
            for we in write_errors:
                pos = we.get("index")
                doc_idx = (
                    inserted_indexes[pos]
                    if pos is not None and 0 <= pos < len(inserted_indexes)
                    else -1
                )
                insert_errors.append({
                    "source_doc_index": doc_idx,
                    "error_code": we.get("code"),
                    "message": (we.get("errmsg") or "")[:400],
                })
            logger.warning(
                "[pdf-commit] insert_many partial failure: "
                "tenant=%s batch=%s inserted=%d failed=%d",
                tenant_id, batch_id, n_inserted, len(write_errors),
            )

    # ── Fire pricebook writeback for opted-in lines ───────
    # Data-integrity hook (§A ruling keeps this on).  Runs
    # per-invoice so a single line failure does not stop the
    # whole batch.
    for doc in to_insert:
        if doc["id"] not in inserted_ids:
            continue
        if any(li.get("pricebook_writeback") for li in doc.get("line_items", [])):
            try:
                from services.pricebook.writeback import process_pricebook_writebacks
                await process_pricebook_writebacks(
                    tenant_id=tenant_id,
                    invoice_id=doc["id"],
                    line_items=doc["line_items"],
                    actor=operator,
                    origin="pdf_import_commit",
                )
            except Exception:                                      # noqa: BLE001
                logger.exception(
                    "[pdf-commit] pricebook writeback failed for "
                    "invoice=%s (data-integrity hook, non-fatal)",
                    doc["id"],
                )

    quotes_skipped_duplicates = (
        len(duplicates) if on_duplicate == _DUP_SKIP else 0
    )
    quotes_skipped_idempotent = len(already_inserted_indexes)

    # ═══════════════════════════════════════════════════════════
    # PDF Importer Sub-phase C · Feb-2026 — payment commit lane.
    #
    # Iterates previews with ``mapped_target == "payment_in"``
    # (see pdf_mapper._build_payment_in). Each becomes a row in
    # ``db.payments`` with best-effort ``invoice_id`` linking via
    # doc_number match on ``db.quotes``.
    #
    # Idempotency uses ``(tenant_id, import_batch_id,
    # import_source_doc_index)`` — a mid-flight crash + rerun
    # updates the existing row instead of duplicating. This
    # matches the invoice path's ``already_inserted_indexes``
    # convention but implemented as a per-row check because
    # payments live in a different collection.
    #
    # Errors are per-payment (partial success): a bad payment
    # doesn't take down invoice inserts, and vice versa. All
    # non-fatal issues land in ``warnings`` per ruling #7.
    # ═══════════════════════════════════════════════════════════
    payment_stats = await _commit_payment_previews(
        previews=previews,
        batch=batch, tenant_id=tenant_id,
        operator=operator, commit_at=commit_at,
        warnings=warnings, db=db,
    )

    # ─── Unknown / malformed doc_kind → error entry (per ruling #8) ───
    for preview in previews:
        target = preview.get("mapped_target")
        if target in ("quote_in", "payment_in", "deferred_to_h4", None):
            continue
        # Unrecognised mapped_target — shouldn't happen with the
        # current Literal enum but guardrail for hand-crafted or
        # forward-compat previews.
        idx = int(preview.get("source_doc_index", -1))
        warnings.append({
            "source_doc_index": idx,
            "doc_type": "unknown",
            "code": "unknown_mapped_target",
            "message": (
                f"unknown mapped_target={target!r}; row skipped "
                f"(neither quote_in nor payment_in)."
            ),
        })

    # ─── Per-doc-type finalised counts ───────────────────────
    # Only accept the plan counts up to how many rows actually
    # landed in db.quotes. If insert_many partial-failed, prefer
    # the invoice bucket to shrink first (writes are ordered,
    # invoice rows land in position 0..N first).
    actual_quotes_inserted = len(inserted_ids)
    invoices_created = min(invoices_planned, actual_quotes_inserted)
    estimates_created = actual_quotes_inserted - invoices_created

    return CommitResult(
        quotes_created=len(inserted_ids),
        quotes_skipped_duplicates=quotes_skipped_duplicates,
        quotes_skipped_idempotent=quotes_skipped_idempotent,
        quote_ids=inserted_ids,
        duplicates_detected=list(duplicates),
        insert_errors=insert_errors,
        # PDF-C per-type breakdown.
        invoices_created=invoices_created,
        estimates_created=estimates_created,
        payments_created=payment_stats["created"],
        payments_updated=payment_stats["updated"],
        payments_unlinked=payment_stats["unlinked"],
        payment_ids=payment_stats["ids"],
        payment_errors=payment_stats["errors"],
        # FIN-PARITY-A · Feb-2026 — surface reconciliation
        # summaries on the top-level commit response so the FE
        # can render "Invoice INV-42 updated: unpaid → paid".
        reconciled_invoices=payment_stats.get("reconciled_invoices", []),
        warnings=warnings,
        # Phase 33 Step B · Feb-2026 — PDF-import auto-create
        # summary. Serialised shape matches
        # ``AutoCreatedCustomer`` field order so the Step C.1
        # unified-payload wrapper can forward it verbatim.
        auto_created_customers=[
            {
                "source_doc_index": c.source_doc_index,
                "pending_customer_id": c.pending_customer_id,
                "extracted_name": c.extracted_name,
                "extracted_address": c.extracted_address,
                "extracted_phone": c.extracted_phone,
                "resolved_customer_id": c.resolved_customer_id,
                "action": c.action,
            }
            for c in autocreate_result.auto_created
        ],
    )


def _build_quote_doc_from_preview(
    *, preview: Dict[str, Any], batch: Dict[str, Any],
    tenant_id: str, operator: Dict[str, Any], commit_at: str,
) -> Dict[str, Any]:
    """Assemble the ``db.quotes`` document for one preview.

    Field semantics per Phase H.2.B ruling §A:
      * doc_number (from ``quote_in``) → invoice_number for
        invoices.  We do NOT auto-assign a sequential number.
      * status defaults to ``"sent"`` for imported historicals.
      * payment_status preserved from ``quote_in`` if present.
      * paid_at pulled from ``pending_payment_actions[0]`` if
        the mapper prepared a record_payment action.
    """
    qi = preview.get("quote_in") or {}
    line_items: List[Dict[str, Any]] = list(qi.get("line_items") or [])
    doc_type = qi.get("doc_type") or "invoice"
    doc_number = qi.get("doc_number") or _extract_doc_number_from_title(
        qi.get("title"),
    )

    doc_id = new_id()
    imported_at = commit_at

    doc: Dict[str, Any] = {
        "id": doc_id,
        "tenant_id": tenant_id,
        "customer_id": qi["customer_id"],
        "customer_name": qi.get("customer_name") or "",
        "property_id": qi.get("property_id"),
        "title": qi.get("title") or (
            f"Import #{doc_number}" if doc_number else "Imported document"
        ),
        "doc_type": doc_type,
        "line_items": line_items,
        "tax_rate": float(qi.get("tax_rate") or 0.0),
        # PDF-FIX-D · Feb-2026 — totals now sourced from the
        # extractor's verbatim values on ``quote_in`` when the
        # mapper stamped ``imported_totals_verbatim=True``.
        # ``_apply_totals`` (called below) gates its recompute
        # on that flag + values-present, so legacy paths that
        # emit None totals still fall through to line-item math
        # for backwards compat.  ``total`` sources from
        # grand_total (PDF-FIX-A priority) falling back to
        # total_due; both may be None if the PDF didn't print
        # them, in which case _apply_totals will recompute.
        "subtotal": (
            float(qi["subtotal"])
            if qi.get("subtotal") is not None else 0.0
        ),
        "tax": (
            float(qi["tax_total"])
            if qi.get("tax_total") is not None else 0.0
        ),
        "total": (
            float(qi["grand_total"])
            if qi.get("grand_total") is not None
            else (
                float(qi["total_due"])
                if qi.get("total_due") is not None else 0.0
            )
        ),
        # PDF-FIX-D · Feb-2026 — provenance flag from mapper.
        # Downstream (reports, tax recalculation, admin edits)
        # reads this to decide whether to re-derive totals or
        # trust the persisted values.
        "imported_totals_verbatim": bool(
            qi.get("imported_totals_verbatim")
        ),
        # PDF-MIRROR · Feb-2026 — sibling sentinel: line_items
        # were shaped by pdf_mapper._line_item_to_quote_shape
        # with every extractor field preserved (description
        # newlines, sku, line_total, tax_pct, tax_line).
        "line_items_preserved_verbatim": bool(
            qi.get("line_items_preserved_verbatim")
        ),
        "amount_paid": float(qi.get("amount_paid") or 0.0),
        "due_date": qi.get("due_date"),
        # PDF-MIRROR · Feb-2026 — historical-date preservation.
        # ``doc_date`` from the source PDF now lands on the
        # persisted quote doc explicitly (previously it was
        # only reachable via ``created_at`` after Task H0's
        # resolve_date_override coerced it). Nullable when the
        # extractor didn't capture one.
        "doc_date": qi.get("doc_date"),
        # PDF-MIRROR · Feb-2026 — provenance sentinels so audit /
        # reports can distinguish an extracted date from a
        # commit-time fallback without re-reading the source PDF.
        #   * ``extracted`` — value came from the extractor.
        #   * ``commit_time_fallback`` — commit stamped now()
        #     because the PDF didn't print one.
        "doc_date_source": (
            "extracted" if qi.get("doc_date") else "commit_time_fallback"
        ),
        "due_date_source": (
            "extracted" if qi.get("due_date") else "commit_time_fallback"
        ),
        # §A ruling: historicals default to sent, not draft.
        "status": qi.get("status") or "sent",
        # §A ruling: preserve extracted payment_status if present.
        "payment_status": qi.get("payment_status") or "unpaid",
        "notes": qi.get("notes") or "",
        "terms": qi.get("terms"),
        # created_at was resolved by pdf_mapper via
        # resolve_date_override before landing in the preview;
        # trust it as-is (fallback to now).
        "created_at": qi.get("created_at") or commit_at,
        "updated_at": commit_at,
        # Import provenance — sparse partial indexes key off these.
        "import_batch_id": batch.get("id") or batch.get("batch_id"),
        "import_source_doc_index": int(preview.get("source_doc_index", -1)),
        "import_source_doc_number": doc_number,
        "imported_from_pdf": True,
        "imported_at": imported_at,
        "imported_by_user_id": (operator or {}).get("id"),
        # Feb-2026 quotes shape mirrors — populated so downstream
        # readers (portal, PDF renderer) don't NPE.
        "sent_at": commit_at if doc_type == "invoice" else None,
        "last_viewed_at": None,
        "viewed_at": None,
        "last_reminder_at": None,
        "reminder_count": 0,
        "scheduled_job_id": None,
        "deleted_at": None,
        "has_declined_lines": False,
    }

    # §A ruling: doc_number → invoice_number for invoices.
    # Skip assign_invoice_number_if_missing entirely.
    if doc_type == "invoice" and doc_number:
        doc["invoice_number"] = doc_number

    # §A ruling: preserve paid_at from record_payment action.
    paid_at_iso = _extract_paid_at(preview)
    if paid_at_iso is not None:
        doc["paid_at"] = paid_at_iso

    # PDFI-PAID-C · Feb-2026 — propagate auto-heal provenance
    # from the preview onto the persisted invoice doc so admin
    # audit + operator UX can see which rows the commit path
    # healed (vs. honored verbatim).
    _ih_meta = qi.get("_import_metadata")
    if isinstance(_ih_meta, dict) and _ih_meta:
        doc["_import_metadata"] = dict(_ih_meta)

    return doc


def _extract_paid_at(preview: Dict[str, Any]) -> Optional[str]:
    """Return the ISO paid_at from the mapper's prepared
    record_payment action, if any."""
    actions = preview.get("pending_payment_actions") or []
    for act in actions:
        if act.get("kind") == "record_payment":
            paid_at = act.get("paid_at")
            if paid_at:
                return str(paid_at)
    return None


# ═════════════════════════════════════════════════════════════════════
# PDF Importer Sub-phase C · Feb-2026 — payment-commit helpers.
# ═════════════════════════════════════════════════════════════════════
async def _commit_payment_previews(
    *,
    previews: List[Dict[str, Any]],
    batch: Dict[str, Any],
    tenant_id: str,
    operator: Dict[str, Any],
    commit_at: str,
    warnings: List[Dict[str, Any]],
    db,
) -> Dict[str, Any]:
    """Materialise every ``mapped_target == "payment_in"`` preview
    into ``db.payments``. Best-effort ``invoice_id`` linking on
    doc_number match — unlinked payments still commit with a
    warning.

    Returns a summary dict::

        {
            "created": int,       # new rows
            "updated": int,       # idempotent re-commit hit
            "unlinked": int,      # committed w/o invoice_id link
            "ids": [str],         # ids of all successful rows
            "errors": [           # per-row failures
                {source_doc_index, error_code, message},
            ],
        }
    """
    batch_id = batch.get("id") or batch.get("batch_id")
    stats: Dict[str, Any] = {
        "created": 0, "updated": 0, "unlinked": 0,
        "ids": [], "errors": [],
        # FIN-PARITY-A · Feb-2026 — one ReconcileResult per
        # payment that carried a resolved ``invoice_id`` and
        # successfully reconciled. Unlinked payments (no
        # invoice_id) and reconcile failures (invoice missing
        # / cross-tenant) are excluded from this array — see
        # ``stats["errors"]`` for the failure trace.
        "reconciled_invoices": [],
    }

    for preview in previews:
        # PDFI-PAID-B · Feb-2026 — process every preview that
        # carries a ``payment_in`` dict, regardless of
        # ``mapped_target``:
        #   * payment_receipt docs land here via
        #     mapped_target == "payment_in" (PDF-C lane).
        #   * paid invoices (is_paid=True) land here via
        #     mapped_target == "quote_in" with an attached
        #     payment_in dict (PDFI-PAID-B lane).
        if not (preview.get("payment_in") or {}):
            continue
        if preview.get("errors"):
            # Mapper emitted a hard error — refuse to persist
            # (matches the invoice-path gate).
            continue
        source_doc_index = int(preview.get("source_doc_index", -1))
        pi = preview.get("payment_in") or {}
        if not pi:
            continue

        # Refuse to persist a PENDING:: customer_id (matches the
        # invoice path's unresolved-gate posture, but per-row so
        # the operator can resolve THIS payment via H.3 UI and
        # rerun without redoing the whole batch).
        cid = pi.get("customer_id") or ""
        if isinstance(cid, str) and cid.startswith("PENDING::"):
            stats["errors"].append({
                "source_doc_index": source_doc_index,
                "error_code": "unresolved_customer",
                "message": (
                    "payment references an unresolved customer "
                    "(PENDING:: sentinel); resolve via review UI + "
                    "rerun commit."
                ),
            })
            continue

        # Warn-on-missing per ruling #7.
        if pi.get("amount_paid") in (None, 0, 0.0):
            warnings.append({
                "source_doc_index": source_doc_index,
                "doc_type": "payment",
                "code": "amount_paid_missing",
                "message": (
                    "amount_paid missing on payment receipt — "
                    "row committed with amount=$0 placeholder."
                ),
            })
        paid_at_iso = pi.get("paid_at") or commit_at

        # Idempotency — did a prior commit already write this
        # (batch_id, source_doc_index) into payments?
        existing = await db.payments.find_one(
            {
                "tenant_id": tenant_id,
                "import_batch_id": batch_id,
                "import_source_doc_index": source_doc_index,
            },
            {"_id": 0, "id": 1},
        )

        # Best-effort invoice link on doc_number match (per
        # ruling #3). Tenant-scoped ALWAYS — an invoice from
        # another tenant cannot resolve here.
        doc_number = pi.get("doc_number")
        invoice_link: Optional[Dict[str, str]] = None
        if doc_number:
            invoice_link = await _find_invoice_for_payment(
                db=db, tenant_id=tenant_id,
                customer_id=cid, doc_number=doc_number,
            )
        linked = invoice_link is not None
        if not linked:
            stats["unlinked"] += 1
            warnings.append({
                "source_doc_index": source_doc_index,
                "doc_type": "payment",
                "code": "invoice_link_missing",
                "message": (
                    "no matching invoice for payment "
                    f"doc_number={doc_number!r} customer={cid!r}"
                    " — payment committed as unlinked."
                ),
            })

        payment_doc: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "customer_id": cid,
            "customer_name": pi.get("customer_name") or "",
            "amount": float(pi.get("amount_paid") or 0.0),
            # ``method`` is the ``db.payments`` field name; PDF
            # extractor uses ``payment_method`` — map both onto
            # the canonical field so downstream readers work.
            "method": pi.get("payment_method"),
            "payment_reference": pi.get("payment_reference"),
            "paid_at": paid_at_iso,
            "status": "succeeded",
            "invoice_number": doc_number,
            "invoice_id": (invoice_link or {}).get("id"),
            "notes": pi.get("notes"),
            # Import provenance.
            "import_batch_id": batch_id,
            "import_source_doc_index": source_doc_index,
            "imported_from_pdf": True,
            "imported_at": commit_at,
            "imported_by_user_id": (operator or {}).get("id"),
            "source": "pdf_import",
        }

        # PDFI-PAID-C · Feb-2026 — propagate auto-heal provenance
        # onto the persisted payment doc. The payment row is the
        # customer-visible artifact in the portal payment feed, so
        # the ``_import_metadata.auto_healed_fields`` list travels
        # with it alongside the invoice.
        _qi_for_meta = preview.get("quote_in") or {}
        _pi_meta = _qi_for_meta.get("_import_metadata")
        if isinstance(_pi_meta, dict) and _pi_meta:
            payment_doc["_import_metadata"] = dict(_pi_meta)

        try:
            if existing:
                # Idempotent re-commit — update the existing row
                # in place (per ruling #5).
                payment_doc["id"] = existing["id"]
                payment_doc["updated_at"] = commit_at
                await db.payments.update_one(
                    {
                        "tenant_id": tenant_id,
                        "id": existing["id"],
                    },
                    {"$set": {k: v for k, v in payment_doc.items()
                                 if k not in ("id",)}},
                )
                stats["updated"] += 1
                stats["ids"].append(existing["id"])
            else:
                payment_doc["id"] = new_id()
                payment_doc["created_at"] = commit_at
                payment_doc["updated_at"] = commit_at
                await db.payments.insert_one(payment_doc)
                stats["created"] += 1
                stats["ids"].append(payment_doc["id"])
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[pdf-commit] payment insert failed tenant=%s "
                "batch=%s idx=%s: %s",
                tenant_id, batch_id, source_doc_index, exc,
            )
            stats["errors"].append({
                "source_doc_index": source_doc_index,
                "error_code": type(exc).__name__,
                "message": str(exc)[:400],
            })
            # A failed insert can never leave a payment behind
            # that needs reconciliation — skip the reconcile step.
            continue

        # ═════════════════════════════════════════════════════════
        # FIN-PARITY-A · Feb-2026 — invoice reconciliation.
        #
        # After the payment row lands (create OR idempotent
        # update), recompute the linked invoice's amount_paid /
        # payment_status / status from the full sum of linked
        # payments in db.payments. Non-fatal: a reconcile failure
        # on one payment must not abort the batch commit — the
        # payment stays committed, the error is recorded, and the
        # next payment continues.
        #
        # Unlinked payments (invoice_id is None) skip
        # reconciliation entirely — they've already been logged
        # as ``invoice_link_missing`` in the warnings above.
        # ═════════════════════════════════════════════════════════
        linked_invoice_id = payment_doc.get("invoice_id")
        if linked_invoice_id:
            try:
                from services.imports.payment_reconciler import (
                    reconcile_invoice_after_payment,
                    InvoiceNotFoundError,
                )
                result = await reconcile_invoice_after_payment(
                    db=db,
                    tenant_id=tenant_id,
                    invoice_id=linked_invoice_id,
                    audit_source="pdf_import",
                    audit_actor=(operator or {}).get("id"),
                )
                stats["reconciled_invoices"].append(result.to_dict())
                if result.transitions:
                    logger.info(
                        "[pdf-commit] reconciled invoice=%s "
                        "tenant=%s transitions=%s",
                        linked_invoice_id, tenant_id,
                        result.transitions,
                    )
            except InvoiceNotFoundError as exc:
                # Race: the invoice_link we resolved earlier no
                # longer exists (soft-deleted between link + commit,
                # tenant boundary drift, etc.). Non-fatal.
                logger.error(
                    "[pdf-commit] reconcile skipped for missing "
                    "invoice=%s tenant=%s: %s",
                    linked_invoice_id, tenant_id, exc,
                )
                stats["errors"].append({
                    "source_doc_index": source_doc_index,
                    "error_code": "reconcile_invoice_not_found",
                    "message": (
                        f"payment committed but invoice "
                        f"{linked_invoice_id!r} not found in "
                        f"tenant — invoice totals NOT refreshed."
                    ),
                })
            except Exception as exc:  # noqa: BLE001
                # Any other reconcile failure — DO NOT roll back
                # the payment insert. Log ERROR + record the trace
                # so ops can hand-fix.
                logger.exception(
                    "[pdf-commit] reconcile failed for invoice=%s "
                    "tenant=%s: %s",
                    linked_invoice_id, tenant_id, exc,
                )
                stats["errors"].append({
                    "source_doc_index": source_doc_index,
                    "error_code": "reconcile_failed",
                    "message": (
                        f"payment committed but reconcile raised "
                        f"{type(exc).__name__}: {str(exc)[:280]} "
                        f"(invoice_id={linked_invoice_id!r})"
                    ),
                })

    return stats


async def _find_invoice_for_payment(
    *, db, tenant_id: str, customer_id: str, doc_number: str,
) -> Optional[Dict[str, str]]:
    """Best-effort invoice match for a payment. Tenant-scoped
    ALWAYS. Matches on either ``doc_number`` (H.1 preserved) or
    ``invoice_number`` (§A ruling: invoice-path invoices persist
    doc_number as invoice_number).

    Customer scoping is a soft AND — an exact customer_id match
    is preferred but a doc_number-only match still wins so we
    don't drop the link on a subtle customer-id disagreement
    (e.g., the payment landed against a merged customer).
    """
    # Preferred: exact tenant + customer + doc_number match.
    q_exact = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "doc_type": "invoice",
        "$or": [
            {"doc_number": doc_number},
            {"invoice_number": doc_number},
        ],
    }
    row = await db.quotes.find_one(q_exact, {"_id": 0, "id": 1})
    if row:
        return {"id": row["id"]}
    # Fallback: tenant + doc_number only. Customer may have been
    # merged since the invoice was imported.
    q_relaxed = {
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "$or": [
            {"doc_number": doc_number},
            {"invoice_number": doc_number},
        ],
    }
    row = await db.quotes.find_one(q_relaxed, {"_id": 0, "id": 1})
    if row:
        return {"id": row["id"]}
    return None


def _apply_totals(doc: Dict[str, Any]) -> None:
    """Recompute subtotal / tax / total from the persisted
    line-item list.  Mirrors ``routers.quotes.compute_totals``
    without importing it (avoid circular imports at test time).

    PDF-FIX-D · Feb-2026 — verbatim-preservation gate.  When
    the doc carries ``imported_totals_verbatim=True`` AND the
    extractor-authoritative values are present (non-zero
    subtotal + total, matching the ``qty × price`` math OR
    intentionally differing due to PDF discounts / rounding),
    the recompute is SKIPPED — the extractor's numbers land
    verbatim on Mongo.

    Legacy path (``imported_totals_verbatim`` absent / False,
    OR totals are 0.0 sentinel because the PDF didn't print
    them): recompute from line items — matches Sub-phase C
    behaviour and every pre-PDF-FIX-D test.

    PDF-MIRROR · Feb-2026 — additive ``total_source`` sentinel.
    Every branch of ``_apply_totals`` stamps the doc with one
    of three values so downstream readers (audit, needs-review
    filter, FE badge) can distinguish the origin:
      * ``verbatim`` — extractor produced a valid non-zero total
        and we trusted it (unchanged PDF-FIX-D path).
      * ``reconstructed_from_lines`` — recompute from line-items
        yielded a non-zero total (this is the new fallback for
        PDFs with only subtotals + tax lines but no explicit
        Total row).
      * ``zero_total_unrecoverable`` — everything came up 0.0.
        The commit-loop refuses to insert docs with this
        sentinel (see :func:`commit_batch`); the preview is
        flagged for operator review instead.
    """
    # PDF-FIX-D gate — trust the extractor's values when the
    # mapper stamped verbatim + a non-zero total is present.
    # ``subtotal == 0.0 and total == 0.0`` is the sentinel for
    # "no PDF totals available" — fall through to recompute.
    if (
        doc.get("imported_totals_verbatim") is True
        and (doc.get("total") or 0.0) != 0.0
    ):
        doc["total_source"] = "verbatim"
        return

    line_items = doc.get("line_items") or []
    subtotal = 0.0
    for li in line_items:
        try:
            qty = float(li.get("quantity") or 0)
            up = float(li.get("unit_price") or 0)
            # PDF-MIRROR · Feb-2026 — prefer the verbatim
            # ``line_total`` when present so recompute can
            # capture PDF-side discounts / rounding invisible
            # to the naive ``qty × up`` math. Falls through to
            # ``qty × up`` when the extractor didn't capture a
            # line total.
            lt = li.get("line_total")
            if lt is None:
                subtotal += qty * up
            else:
                subtotal += float(lt)
        except (TypeError, ValueError):
            continue
    tax_rate = float(doc.get("tax_rate") or 0.0)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    total = round(subtotal + tax, 2)
    doc["subtotal"] = round(subtotal, 2)
    doc["tax"] = tax
    doc["total"] = total
    if total == 0.0:
        # Nothing to persist — the caller will refuse to insert
        # this doc and route it to the needs_review bucket.
        doc["total_source"] = "zero_total_unrecoverable"
    else:
        doc["total_source"] = "reconstructed_from_lines"


# ═════════════════════════════════════════════════════════════
# Rollback
# ═════════════════════════════════════════════════════════════
async def rollback_batch(
    *,
    batch: Dict[str, Any],
    tenant_id: str,
    operator: Dict[str, Any],
    db,
) -> RollbackResult:
    """Hard-delete every quote/invoice tagged with this
    ``import_batch_id`` for the tenant.  Collision detection:
    if any doc's ``updated_at`` is strictly greater than the
    original commit timestamp on the batch row, snapshot the
    full doc into the result before deleting so the audit row
    can carry it forward for recovery-via-replay.

    Caller is responsible for status flips
    (``committed → rolling_back → rolled_back``).
    """
    batch_id = batch.get("id") or batch.get("batch_id")
    committed_at = batch.get("committed_at")

    # ── Load every imported doc for collision snapshotting ─
    q_filter = {"tenant_id": tenant_id, "import_batch_id": batch_id}
    imported_docs: List[Dict[str, Any]] = []
    async for row in db.quotes.find(q_filter, {"_id": 0}):
        imported_docs.append(row)

    collision_snapshots: List[Dict[str, Any]] = []
    if committed_at:
        for doc in imported_docs:
            updated_at = doc.get("updated_at")
            if updated_at and updated_at > committed_at:
                collision_snapshots.append(doc)

    # ── Delete ────────────────────────────────────────────
    result = await db.quotes.delete_many(q_filter)
    deleted = int(result.deleted_count or 0)

    return RollbackResult(
        quotes_deleted=deleted,
        collision_count=len(collision_snapshots),
        collision_snapshots=collision_snapshots,
    )


# ═════════════════════════════════════════════════════════════
# Audit-log writer
# ═════════════════════════════════════════════════════════════
async def write_import_audit(
    *,
    action: str,
    batch: Dict[str, Any],
    tenant_id: str,
    operator: Dict[str, Any],
    commit_result: Optional[CommitResult] = None,
    rollback_result: Optional[RollbackResult] = None,
    options: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
    db,
) -> str:
    """Insert one ``import_audit`` row.  Returns the row id.

    Fails LOUDLY (raises) — audit rows are non-optional per
    Phase H.2.B rulings, unlike the legacy quotes.py
    best-effort try/except audit writes.
    """
    row_id = new_id()
    at_iso = datetime.now(timezone.utc).isoformat()

    doc: Dict[str, Any] = {
        "id": row_id,
        "tenant_id": tenant_id,
        "batch_id": batch.get("id") or batch.get("batch_id"),
        "action": action,
        "operator_user_id": (operator or {}).get("id"),
        "operator_email": (operator or {}).get("email"),
        "at": at_iso,
        "source_filename": batch.get("source_filename"),
        "options": options or {},
        "notes": notes,
    }

    if commit_result is not None:
        doc.update({
            "quotes_created": commit_result.quotes_created,
            "quotes_skipped_duplicates": commit_result.quotes_skipped_duplicates,
            "quotes_skipped_idempotent": commit_result.quotes_skipped_idempotent,
            "quote_ids": list(commit_result.quote_ids),
            "duplicates_detected": [
                {
                    "source_doc_index": d.source_doc_index,
                    "existing_quote_id": d.existing_quote_id,
                    "doc_number": d.doc_number,
                    "customer_id": d.customer_id,
                }
                for d in commit_result.duplicates_detected
            ],
            "insert_errors": list(commit_result.insert_errors),
        })

    if rollback_result is not None:
        doc.update({
            "quotes_deleted": rollback_result.quotes_deleted,
            "collision_count": rollback_result.collision_count,
            "collisions": list(rollback_result.collision_snapshots),
        })

    await db.import_audit.insert_one(doc)
    return row_id


# ═════════════════════════════════════════════════════════════
# Public exception types (rewrapped as HTTPException by router)
# ═════════════════════════════════════════════════════════════
class UnresolvedCustomersError(Exception):
    """Raised when a batch still carries PENDING:: sentinels."""

    def __init__(self, unresolved: List[UnresolvedCustomer]) -> None:
        self.unresolved = unresolved
        super().__init__(f"{len(unresolved)} unresolved customers")


class DuplicateBatchError(Exception):
    """Raised when ``on_duplicate="fail"`` and duplicates exist."""

    def __init__(self, duplicates: List[DuplicateWarning]) -> None:
        self.duplicates = duplicates
        super().__init__(f"{len(duplicates)} duplicates detected")


class PaidStatusValidationError(Exception):
    """PDFI-PAID-B · Feb-2026 — raised when a batch carries
    ``quote_in.is_paid=True`` previews missing required
    paid-status fields (``paid_at`` or ``amount_paid``).

    PDFI-PAID-C · Feb-2026 — now carries a per-row ``rows``
    list (``row_index``, ``field``, ``reason``, ``value``,
    ``is_paid``, ``invoice_number``) so the router can rewrap
    into a structured 422 the frontend can render per-row
    without a cross-reference pass.

    Caught in ``routers.imports.commit_pdf_invoice_batch`` and
    rewrapped as HTTP 422 with error_code + doc_indices + rows
    in the detail body. Batch resets to ``preview_complete`` so
    the operator can patch via PATCH /preview and rerun commit.
    """

    def __init__(
        self,
        error_code: str,
        doc_indices: List[int],
        rows: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.error_code = error_code
        self.doc_indices = doc_indices
        self.rows = rows or []
        super().__init__(f"{error_code}: doc_indices={doc_indices}")
