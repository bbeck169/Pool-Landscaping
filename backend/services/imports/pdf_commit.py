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

    # ── Pre-flight: unresolved-customer gate ──────────────
    unresolved = collect_unresolved_customers(previews)
    if unresolved:
        # Not a CommitResult return — this is a caller-side
        # 400. Raise a plain ValueError for the router to
        # rewrap as HTTPException.
        raise UnresolvedCustomersError(unresolved)

    # ── Pre-flight: duplicate scan ─────────────────────────
    duplicates = await check_duplicates(
        previews=previews, tenant_id=tenant_id, db=db,
    )
    if on_duplicate == _DUP_FAIL and duplicates:
        raise DuplicateBatchError(duplicates)

    dup_by_idx = {d.source_doc_index: d for d in duplicates}

    # ── Idempotency: skip previews already inserted ───────
    already_inserted_indexes = set()
    async for row in db.quotes.find(
        {"tenant_id": tenant_id, "import_batch_id": batch_id},
        {"_id": 0, "import_source_doc_index": 1},
    ):
        idx = row.get("import_source_doc_index")
        if idx is not None:
            already_inserted_indexes.add(int(idx))

    # ── Build the doc list ────────────────────────────────
    to_insert: List[Dict[str, Any]] = []
    inserted_indexes: List[int] = []
    for preview in previews:
        source_doc_index = int(preview.get("source_doc_index", -1))
        if source_doc_index in already_inserted_indexes:
            continue
        if preview.get("mapped_target") != "quote_in":
            # payment_receipt / deferred_to_h4 — H.4's problem.
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

        to_insert.append(doc)
        inserted_indexes.append(source_doc_index)

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

    return CommitResult(
        quotes_created=len(inserted_ids),
        quotes_skipped_duplicates=quotes_skipped_duplicates,
        quotes_skipped_idempotent=quotes_skipped_idempotent,
        quote_ids=inserted_ids,
        duplicates_detected=list(duplicates),
        insert_errors=insert_errors,
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
        # Totals are set by _apply_totals below.
        "subtotal": 0.0,
        "tax": 0.0,
        "total": 0.0,
        "amount_paid": float(qi.get("amount_paid") or 0.0),
        "due_date": qi.get("due_date"),
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


def _apply_totals(doc: Dict[str, Any]) -> None:
    """Recompute subtotal / tax / total from the persisted
    line-item list.  Mirrors ``routers.quotes.compute_totals``
    without importing it (avoid circular imports at test time).
    """
    line_items = doc.get("line_items") or []
    subtotal = 0.0
    for li in line_items:
        try:
            qty = float(li.get("quantity") or 0)
            up = float(li.get("unit_price") or 0)
        except (TypeError, ValueError):
            qty = 0.0
            up = 0.0
        subtotal += qty * up
    tax_rate = float(doc.get("tax_rate") or 0.0)
    tax = round(subtotal * (tax_rate / 100.0), 2)
    total = round(subtotal + tax, 2)
    doc["subtotal"] = round(subtotal, 2)
    doc["tax"] = tax
    doc["total"] = total


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
