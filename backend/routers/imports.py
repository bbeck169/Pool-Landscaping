"""Task H · Phase B2.B · Feb-2026 — Async PDF Invoice Importer router.

Two endpoints:

* ``POST /api/imports/pdf-invoice`` — accepts a multipart PDF
  upload, validates size/MIME/rate-limit synchronously, opens
  the PDF once to compute the page count, inserts a ``queued``
  batch row with the FINAL ``batch_id``, dispatches the
  extract+map+persist pipeline onto FastAPI ``BackgroundTasks``,
  and returns ``202 Accepted`` in ≪ 60s regardless of PDF size.

* ``GET /api/imports/pdf-invoice/{batch_id}`` — polls the batch
  row.  Returns ``404 batch_not_found`` on both "row does not
  exist" and "row exists but belongs to another tenant" so the
  poll surface cannot be used as a cross-tenant probe.  Response
  includes a computed ``progress_pct`` derived from the row's
  ``stage`` field so clients can render a live progress bar
  without an extra derived-field write.

Auth: ``require_admin`` (mirrors Task H0 § 3 role gate).
Tenant: ``get_current_tenant`` (strict multi-tenant isolation).

Rate limit: unchanged from H.1 — max 3 concurrent
``in_flight`` batches per tenant within a 5-min window.  The
``in_flight`` set now covers BOTH ``queued`` and ``processing``
so a fast client cannot burst past the guard by kicking off
several batches before the first BackgroundTask fires.

Status lifecycle:

* ``queued`` — inserted at kickoff time (before ``bg.add_task``
  fires).  Millisecond-brief in the FastAPI-BackgroundTasks era
  since the task starts immediately after the response returns;
  reserved for future migration to a real task queue (Celery /
  arq / RQ) where the ``queued`` window becomes meaningful.
* ``processing`` — pipeline started.  ``stage`` tracks live
  progress: ``segmentation`` → ``extraction N/M`` → ``mapping``
  → ``mapping N/M`` → ``persisting``.
* ``preview_complete`` — terminal success.  Carries the full
  extractor output + mapper previews.
* ``failed`` — terminal error.  Carries ``error`` string capped
  at 400 chars + PRESERVES whatever ``stage`` field the last
  successful progress update wrote (so admins see e.g.
  ``failed at extraction 20/48 -- <error>``).  Any
  ``partial_extracted_documents`` accumulated up to the failure
  point are also preserved via the extractor's per-segment
  progress-callback hook.
* ``cancelled`` — enum value reserved for the Task H.4 cancel
  endpoint.  NEVER emitted in Phase B2.B — kept in the enum so
  the client-side status-badge switch statement is exhaustive
  now and doesn't need retrofitting when H.4 lands.

Response payload cap (unchanged): mapper truncates
``line_items`` to 25 per doc for the wire payload; the full
un-truncated line-item lists live in
``import_batches.extracted_documents_full`` for the H.2 commit
path.
"""
from __future__ import annotations

import io
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF — used at kickoff to compute page_count
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)

from config import db
from services.imports.extraction_schema import ExtractedBatch, MapperReport
from services.imports.pdf_invoice_extractor import extract
from services.imports.pdf_mapper import map_extracted_to_quote_in
from utils import require_admin

# ``get_current_tenant`` mirrors the import shape used by
# ``routers/quotes.py``.
from routers.tenants import get_current_tenant


logger = logging.getLogger("routers.imports")

# ── H.1 spec constants (unchanged) ─────────────────────────────
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024        # 10 MB
_RATE_LIMIT_MAX_IN_FLIGHT = 3
_RATE_LIMIT_WINDOW = timedelta(minutes=5)

# ── B2.B status enum ────────────────────────────────────────────
_STATUS_QUEUED = "queued"
_STATUS_PROCESSING = "processing"
_STATUS_PREVIEW_COMPLETE = "preview_complete"
_STATUS_FAILED = "failed"
# TODO Task H.4 · cancel endpoint emits this status.
_STATUS_CANCELLED = "cancelled"
# Task H.2 · Feb-2026 — commit + rollback status enum extension.
# ``committing`` / ``rolling_back`` are transient guards used to
# prevent double-commit / double-rollback races on the same batch.
# Terminal states: ``committed`` / ``commit_failed`` /
# ``rolled_back`` / ``rollback_failed``.
_STATUS_COMMITTING = "committing"
_STATUS_COMMITTED = "committed"
_STATUS_COMMIT_FAILED = "commit_failed"
_STATUS_ROLLING_BACK = "rolling_back"
_STATUS_ROLLED_BACK = "rolled_back"
_STATUS_ROLLBACK_FAILED = "rollback_failed"

# Statuses that count toward the per-tenant rate limit.  Both
# ``queued`` and ``processing`` are "in flight" for the purposes
# of the guard; terminal states (``preview_complete`` /
# ``failed`` / ``cancelled`` / ``committed`` / ``rolled_back``)
# do not.  Task H.2 · commit/rollback transient states
# (``committing`` / ``rolling_back``) count as in-flight too so
# a client cannot double-drive the endpoint.
_IN_FLIGHT_STATUSES = (
    _STATUS_QUEUED, _STATUS_PROCESSING,
    _STATUS_COMMITTING, _STATUS_ROLLING_BACK,
)


router = APIRouter(prefix="/api/imports", tags=["imports"])


# ─────────────────────────────────────────────────────────────
# Startup index ensure
# ─────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    """Called at server-startup. background=True so the create
    call does not block boot on large tenants.

    Task H.2 · Feb-2026 — self-healing posture. Every index
    plan is applied via its own ``try/except`` so a single
    failure logs at WARN + keeps the loop going. The outer
    ``try`` from H.1 swallowed a single failure silently AND
    aborted every subsequent index — that's the drift observed
    during Phase H.2.A recon (live ``db.import_batches`` had
    only ``_id_`` even though the code declared four indexes).
    """

    async def _one(coll: str, keys, opts: dict) -> None:
        """Best-effort index creation with per-plan WARN
        logging.  Does NOT swallow the exception silently — every
        failure emits an observable log line per Phase H.2.B
        ruling §C."""
        try:
            await db[coll].create_index(keys, **opts)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[imports] index ensure failed on %s (%s): %s: %s",
                coll, opts.get("name"), type(exc).__name__, exc,
            )

    # ── H.1 indexes (retained) ─────────────────────────────
    await _one(
        "pending_import_customers",
        [("tenant_id", 1), ("batch_id", 1)],
        {"name": "pending_import_customers_tenant_batch", "background": True},
    )
    await _one(
        "pending_import_customers",
        [("tenant_id", 1), ("extracted_customer_name", 1)],
        {"name": "pending_import_customers_tenant_name", "background": True},
    )
    await _one(
        "import_batches",
        [("tenant_id", 1), ("status", 1), ("created_at", -1)],
        {"name": "import_batches_tenant_status_created", "background": True},
    )
    await _one(
        "import_batches",
        [("id", 1)],
        {"name": "import_batches_id_uniq", "unique": True, "background": True},
    )

    # ── H.2 new indexes ────────────────────────────────────
    # (tenant_id, import_batch_id) sparse partial — rollback
    # perf.
    await _one(
        "quotes",
        [("tenant_id", 1), ("import_batch_id", 1)],
        {
            "name": "quotes_tenant_import_batch",
            "background": True,
            "partialFilterExpression": {
                "import_batch_id": {"$exists": True},
            },
        },
    )
    # (tenant_id, customer_id, import_source_doc_number) sparse
    # partial — duplicate detection perf.
    await _one(
        "quotes",
        [("tenant_id", 1), ("customer_id", 1),
          ("import_source_doc_number", 1)],
        {
            "name": "quotes_tenant_customer_import_docnum",
            "background": True,
            "partialFilterExpression": {
                "import_source_doc_number": {"$exists": True},
            },
        },
    )
    # import_audit — per-batch lookup + reverse-chron dashboard.
    await _one(
        "import_audit",
        [("tenant_id", 1), ("batch_id", 1)],
        {"name": "import_audit_tenant_batch", "background": True},
    )
    await _one(
        "import_audit",
        [("tenant_id", 1), ("at", -1)],
        {"name": "import_audit_tenant_at_desc", "background": True},
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
async def _rate_limit_check(tenant_id: str) -> None:
    """H.1 spec §Rate-limit guard.  Counts ``in_flight`` rows
    within the 5-min window; anything older than the window is
    treated as abandoned and does NOT count.

    B2.B expansion: ``in_flight`` now covers BOTH ``queued`` and
    ``processing`` (was ``in_flight`` before)."""
    now = datetime.now(timezone.utc)
    cutoff = (now - _RATE_LIMIT_WINDOW).isoformat()
    in_flight = await db.import_batches.count_documents({
        "tenant_id": tenant_id,
        "status": {"$in": list(_IN_FLIGHT_STATUSES)},
        "created_at": {"$gt": cutoff},
    })
    if in_flight >= _RATE_LIMIT_MAX_IN_FLIGHT:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "import_in_flight",
                "message": (
                    f"{in_flight} imports already in-flight for this tenant "
                    f"(limit {_RATE_LIMIT_MAX_IN_FLIGHT}). Wait a moment or "
                    f"resubmit after 5 minutes."
                ),
            },
        )


def _poll_hint_seconds(page_count: int) -> int:
    """B2.B poll-hint heuristic per spec: small PDFs poll fast,
    large batches poll slower.  Bounded [3, 30]."""
    return min(30, max(3, int(page_count * 1.5)))


# ── Stage-to-progress-pct mapping ──────────────────────────────
# Weights: segmentation ≈ 5%, extraction ≈ 65%, mapping ≈ 15%,
# persisting ≈ 5%, buffer 10% at the tail.
_STAGE_WEIGHT = {
    "segmentation": (0, 5),      # 0-5%
    "extraction":   (5, 70),     # 5-70%
    "mapping":      (70, 85),    # 70-85%
    "persisting":   (85, 95),    # 85-95%
}


def _compute_progress_pct(status: Optional[str],
                            stage: Optional[str]) -> int:
    """Derive a 0-100 int from ``status`` + ``stage``.

    * Terminal states pin to 100 (``preview_complete``) or the
      last observable value on ``failed`` — for ``failed`` we
      compute from ``stage`` so admins see the failure point.
    * ``queued`` = 0.
    * ``processing`` uses the weight table + optional ``N/M``
      suffix on ``stage``."""
    if status == _STATUS_PREVIEW_COMPLETE:
        return 100
    if status in (None, _STATUS_QUEUED):
        return 0
    if status == _STATUS_CANCELLED:
        return 0
    # ``processing`` OR ``failed`` — derive from stage.
    if not stage:
        return 0
    stage_key = stage.split()[0]
    band = _STAGE_WEIGHT.get(stage_key)
    if band is None:
        return 0
    lo, hi = band
    # Optional "N/M" suffix.
    parts = stage.split()
    if len(parts) >= 2 and "/" in parts[1]:
        try:
            cur_s, tot_s = parts[1].split("/", 1)
            cur = int(cur_s)
            tot = int(tot_s)
            if tot > 0:
                frac = max(0.0, min(1.0, cur / tot))
                return int(lo + (hi - lo) * frac)
        except (ValueError, TypeError):
            pass
    return lo


def _sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Drop Mongo internals and stamp a computed ``progress_pct``
    onto the row before returning it to a client."""
    row = {k: v for k, v in row.items() if k != "_id"}
    row["progress_pct"] = _compute_progress_pct(
        row.get("status"), row.get("stage"),
    )
    return row


# ─────────────────────────────────────────────────────────────
# Background pipeline
# ─────────────────────────────────────────────────────────────
async def _run_pipeline(
    *,
    batch_id: str,
    tenant_id: str,
    source_filename: str,
    pdf_bytes: bytes,
    hint_doc_kind: Optional[str],
    user_id: Optional[str],
) -> None:
    """Runs the full extract + map + persist flow asynchronously.

    Any per-segment progress hint updates the row's ``stage``
    field; a top-level failure preserves the last successful
    ``stage`` / partial-documents fields so admins can diagnose
    "failed at extraction 20/48 -- <error>"."""
    start_ms = time.perf_counter()

    # Flip queued → processing + record extraction_started_at.
    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant_id},
        {"$set": {
            "status": _STATUS_PROCESSING,
            "stage": "segmentation",
            "extraction_started_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    async def _progress_cb(
        *, stage: str, current: Optional[int],
        total: Optional[int],
        partial_documents: Optional[List[Any]] = None,
    ) -> None:
        """Per-stage row updater.  Best-effort — the extractor
        swallows exceptions raised here so a Mongo blip never
        corrupts the extraction result."""
        stage_str = (
            f"{stage} {current}/{total}"
            if current is not None and total is not None
            else stage
        )
        update: Dict[str, Any] = {"stage": stage_str}
        if partial_documents is not None:
            update["partial_extracted_documents"] = [
                d.model_dump(mode="json") for d in partial_documents
            ]
            update["partial_extracted_document_count"] = len(partial_documents)
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": update},
        )

    try:
        # ── Extract ─────────────────────────────────────────
        batch: ExtractedBatch = await extract(
            pdf_bytes=pdf_bytes,
            tenant_id=tenant_id,
            source_filename=source_filename,
            hint_doc_kind=hint_doc_kind,
            db=db,
            batch_id=batch_id,
            progress_callback=_progress_cb,
        )

        # ── Map every document ─────────────────────────────
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"stage": "mapping"}},
        )
        mapper_previews: List[MapperReport] = []
        total_docs = len(batch.documents)
        for idx, doc in enumerate(batch.documents):
            report = await map_extracted_to_quote_in(
                doc, db=db, tenant_id=tenant_id,
                batch_id=batch.batch_id,
                operator_user={"id": user_id, "role": "admin"},
                source_doc_index=idx,
            )
            mapper_previews.append(report)
            if total_docs > 0:
                await db.import_batches.update_one(
                    {"id": batch_id, "tenant_id": tenant_id},
                    {"$set": {"stage": f"mapping {idx + 1}/{total_docs}"}},
                )

        # ── Persist final state ────────────────────────────
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"stage": "persisting"}},
        )
        duration_ms = int((time.perf_counter() - start_ms) * 1000)
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {
                "status": _STATUS_PREVIEW_COMPLETE,
                "stage": "done",
                "source_sha256": batch.source_sha256,
                "source_byte_count": batch.source_byte_count,
                "page_count": batch.page_count,
                "model_used": batch.model_used,
                "duration_ms": duration_ms,
                "extraction_started_at": batch.extraction_started_at.isoformat(),
                "extraction_finished_at": batch.extraction_finished_at.isoformat(),
                "warnings": batch.warnings,
                "extracted_documents_full": [
                    d.model_dump(mode="json") for d in batch.documents
                ],
                "mapper_previews": [
                    m.model_dump(mode="json") for m in mapper_previews
                ],
            }, "$unset": {
                # Partial fields are only relevant during
                # processing / failure states.
                "partial_extracted_documents": "",
                "partial_extracted_document_count": "",
            }},
        )

        logger.info(
            f"[pdf-import] async tenant={tenant_id} batch={batch_id} "
            f"file={source_filename!r} pages={batch.page_count} "
            f"docs={len(batch.documents)} model={batch.model_used} "
            f"duration_ms={duration_ms}"
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.exception(
            f"[pdf-import] async tenant={tenant_id} batch={batch_id} "
            f"pipeline failure: {exc}"
        )
        # Preserve whatever stage / partial-documents fields the
        # last successful progress update wrote; only stamp
        # status + error.  Admins polling should see
        # "failed at extraction 20/48 -- <error>".
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {
                "status": _STATUS_FAILED,
                "error": str(exc)[:400],
            }},
        )


# ─────────────────────────────────────────────────────────────
# Kickoff endpoint (POST → 202)
# ─────────────────────────────────────────────────────────────
@router.post("/pdf-invoice", status_code=202)
async def import_pdf_invoice(
    response: Response,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    hint_doc_kind: Optional[str] = Form(default=None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase B2.B — async kickoff.  See module doc.

    Returns ``202 Accepted`` with a kickoff envelope shaped
    as::

        {
          "batch_id": "<uuid>",
          "status": "queued",
          "poll_hint_seconds": <int in [3, 30]>,
          "poll_url": "/api/imports/pdf-invoice/{batch_id}",
          "async": true
        }
    """
    tenant_id = tenant["id"]

    # ── 415 MIME check ────────────────────────────────────
    content_type = (file.content_type or "").lower()
    if content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(
            status_code=415,
            detail={
                "error": "pdf_only",
                "message": (
                    f"File type {content_type!r} not accepted; only "
                    f"application/pdf uploads are supported."
                ),
            },
        )

    # ── 413 size cap ──────────────────────────────────────
    pdf_bytes = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "pdf_too_large",
                "message": (
                    f"File exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} "
                    f"MB Phase H.1 limit."
                ),
            },
        )

    # ── Rate-limit guard ──────────────────────────────────
    await _rate_limit_check(tenant_id)

    # ── Compute page_count for the poll hint ──────────────
    try:
        _pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = _pdf.page_count
        _pdf.close()
    except Exception as exc:                                       # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "error": "pdf_parse_failed",
                "message": f"Could not parse PDF: {str(exc)[:200]}",
            },
        )

    # ── Insert queued row with the FINAL batch_id ─────────
    batch_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    source_filename = file.filename or "upload.pdf"
    await db.import_batches.insert_one({
        "id": batch_id,
        "tenant_id": tenant_id,
        "status": _STATUS_QUEUED,
        "stage": None,
        "source_filename": source_filename,
        "page_count": page_count,
        "source_byte_count": len(pdf_bytes),
        "created_at": now_iso,
        "created_by": user.get("id"),
    })

    # ── Dispatch pipeline via BackgroundTasks ─────────────
    background_tasks.add_task(
        _run_pipeline,
        batch_id=batch_id,
        tenant_id=tenant_id,
        source_filename=source_filename,
        pdf_bytes=pdf_bytes,
        hint_doc_kind=hint_doc_kind,
        user_id=user.get("id"),
    )

    hint = _poll_hint_seconds(page_count)
    response.status_code = 202
    return {
        "batch_id": batch_id,
        "status": _STATUS_QUEUED,
        "poll_hint_seconds": hint,
        "poll_url": f"/api/imports/pdf-invoice/{batch_id}",
        "async": True,
    }


# ─────────────────────────────────────────────────────────────
# Poll endpoint (GET)
# ─────────────────────────────────────────────────────────────
@router.get("/pdf-invoice/{batch_id}")
async def get_pdf_invoice_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase B2.B — poll a batch's current status /
    progress.  Multi-tenant guard: cross-tenant matches surface
    as ``404 batch_not_found`` (not ``403``) so the poll surface
    cannot be used as a tenant-membership probe."""
    row = await db.import_batches.find_one(
        {"id": batch_id, "tenant_id": tenant["id"]},
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "batch_not_found",
                "message": (
                    f"No import batch with id={batch_id!r} for this tenant."
                ),
            },
        )
    return _sanitize_row(row)



# ═════════════════════════════════════════════════════════════
# Task H · Phase H.2 — Commit + rollback endpoints
# ═════════════════════════════════════════════════════════════
from pydantic import BaseModel  # noqa: E402

from services.imports.pdf_commit import (                          # noqa: E402
    DuplicateBatchError,
    UnresolvedCustomersError,
    check_duplicates,
    commit_batch,
    rollback_batch,
    write_import_audit,
    _DUP_SKIP,
    _DUP_INSERT_ANYWAY,
    _DUP_FAIL,
    _DUP_VALID,
)


class _CommitOptions(BaseModel):
    """Body for ``POST /api/imports/pdf-invoice/{batch_id}/commit``.

    * ``on_duplicate`` — one of ``"skip"`` (default) |
      ``"insert_anyway"`` | ``"fail"``.
    * ``notes`` — optional operator note surfaced on the
      ``import_audit`` row (max 500 chars).
    """
    on_duplicate: Optional[str] = _DUP_SKIP
    notes: Optional[str] = None


def _serialise_duplicates(dups) -> List[Dict[str, Any]]:
    return [{
        "source_doc_index": d.source_doc_index,
        "existing_quote_id": d.existing_quote_id,
        "doc_number": d.doc_number,
        "customer_id": d.customer_id,
    } for d in dups]


def _serialise_unresolved(unresolved) -> List[Dict[str, Any]]:
    return [{
        "source_doc_index": u.source_doc_index,
        "extracted_customer_name": u.extracted_customer_name,
        "pending_customer_id": u.pending_customer_id,
    } for u in unresolved]


@router.get("/pdf-invoice/{batch_id}/duplicates")
async def get_batch_duplicates(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase H.2 — pre-flight duplicate scan.

    Returns the list of previews that would collide with
    existing quotes on ``(tenant_id, customer_id, doc_type,
    import_source_doc_number)`` if the batch were committed
    right now. Read-only; no state change.

    Multi-tenant guard: cross-tenant matches surface as 404
    ``batch_not_found`` (same posture as the poll endpoint).
    """
    row = await db.import_batches.find_one(
        {"id": batch_id, "tenant_id": tenant["id"]},
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "batch_not_found",
                "message": (
                    f"No import batch with id={batch_id!r} for this tenant."
                ),
            },
        )
    previews = row.get("mapper_previews") or []
    duplicates = await check_duplicates(
        previews=previews, tenant_id=tenant["id"], db=db,
    )
    return {
        "batch_id": batch_id,
        "duplicate_count": len(duplicates),
        "duplicates": _serialise_duplicates(duplicates),
    }


@router.post("/pdf-invoice/{batch_id}/commit")
async def commit_pdf_invoice_batch(
    batch_id: str,
    options: Optional[_CommitOptions] = None,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase H.2 — materialise a preview_complete
    import batch into ``db.quotes``.

    Status machine::

        preview_complete → committing → committed
                                     ↘ commit_failed

    Preconditions:
      * Batch status MUST be ``preview_complete`` (400
        ``batch_wrong_status`` otherwise).
      * Zero ``PENDING::`` sentinels remain (400
        ``unresolved_customers`` otherwise).
      * Zero mapper ``errors`` entries — those previews are
        silently skipped inside :func:`commit_batch`.

    Optional body: ``{"on_duplicate": "skip"|"insert_anyway"|"fail",
    "notes": "..."}``.  Default ``on_duplicate="skip"``.

    Response shape::

        {
          "batch_id", "status": "committed",
          "quotes_created", "quotes_skipped_duplicates",
          "quotes_skipped_idempotent",
          "quote_ids": [...],
          "duplicates_detected": [...],
          "insert_errors": [...],
          "audit_id"
        }
    """
    opts = options or _CommitOptions()
    on_duplicate = opts.on_duplicate or _DUP_SKIP
    if on_duplicate not in _DUP_VALID:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_on_duplicate",
                "message": (
                    f"on_duplicate must be one of {sorted(_DUP_VALID)!r}; "
                    f"got {on_duplicate!r}."
                ),
            },
        )
    notes = (opts.notes or "")[:500] if opts.notes else None

    tenant_id = tenant["id"]

    # ── Status guard: flip preview_complete → committing atomically.
    guarded = await db.import_batches.find_one_and_update(
        {"id": batch_id, "tenant_id": tenant_id,
          "status": _STATUS_PREVIEW_COMPLETE},
        {"$set": {"status": _STATUS_COMMITTING,
                    "commit_started_at": datetime.now(timezone.utc).isoformat()}},
        return_document=True,
    )
    if guarded is None:
        # Either not found for this tenant OR in the wrong status.
        row = await db.import_batches.find_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"_id": 0, "status": 1},
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "batch_not_found",
                    "message": (
                        f"No import batch with id={batch_id!r} for this tenant."
                    ),
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "batch_wrong_status",
                "message": (
                    f"Batch {batch_id!r} is in status "
                    f"{row.get('status')!r}, expected "
                    f"{_STATUS_PREVIEW_COMPLETE!r}."
                ),
                "current_status": row.get("status"),
            },
        )

    # From here on, we own the ``committing`` transient state
    # and are responsible for flipping to ``committed`` or
    # ``commit_failed`` before returning.
    try:
        commit_result = await commit_batch(
            batch=guarded,
            tenant_id=tenant_id,
            operator=user,
            on_duplicate=on_duplicate,
            db=db,
        )
    except UnresolvedCustomersError as exc:
        # Reset batch to preview_complete so the operator can
        # resolve pendings via H.3 UI and retry.
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_PREVIEW_COMPLETE},
              "$unset": {"commit_started_at": ""}},
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unresolved_customers",
                "message": (
                    f"{len(exc.unresolved)} preview(s) still carry "
                    f"PENDING:: customer sentinels; resolve via the "
                    f"admin review UI before commit."
                ),
                "unresolved": _serialise_unresolved(exc.unresolved),
            },
        )
    except DuplicateBatchError as exc:
        # ``on_duplicate="fail"`` — no partial commit occurred.
        # Flip back to preview_complete so the operator can rerun
        # with ``skip`` or ``insert_anyway``.
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_PREVIEW_COMPLETE},
              "$unset": {"commit_started_at": ""}},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicates_detected",
                "message": (
                    f"{len(exc.duplicates)} duplicate(s) detected; "
                    f"rerun with on_duplicate=skip to skip or "
                    f"insert_anyway to force."
                ),
                "duplicates": _serialise_duplicates(exc.duplicates),
            },
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.exception(
            "[pdf-commit] tenant=%s batch=%s commit failed: %s",
            tenant_id, batch_id, exc,
        )
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_COMMIT_FAILED,
                        "commit_error": str(exc)[:400]}},
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "commit_failed",
                "message": str(exc)[:400],
            },
        )

    # ── Success — audit + flip to committed ────────────────
    audit_id = await write_import_audit(
        action="commit",
        batch=guarded,
        tenant_id=tenant_id,
        operator=user,
        commit_result=commit_result,
        options={"on_duplicate": on_duplicate},
        notes=notes,
        db=db,
    )

    committed_at = datetime.now(timezone.utc).isoformat()
    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant_id},
        {"$set": {
            "status": _STATUS_COMMITTED,
            "committed_at": committed_at,
            "committed_by_user_id": user.get("id"),
            "committed_quotes": commit_result.quote_ids,
            "commit_audit_id": audit_id,
        }, "$unset": {"commit_started_at": ""}},
    )

    return {
        "batch_id": batch_id,
        "status": _STATUS_COMMITTED,
        "quotes_created": commit_result.quotes_created,
        "quotes_skipped_duplicates": commit_result.quotes_skipped_duplicates,
        "quotes_skipped_idempotent": commit_result.quotes_skipped_idempotent,
        "quote_ids": commit_result.quote_ids,
        "duplicates_detected": _serialise_duplicates(
            commit_result.duplicates_detected,
        ),
        "insert_errors": commit_result.insert_errors,
        "audit_id": audit_id,
    }


@router.post("/pdf-invoice/{batch_id}/rollback")
async def rollback_pdf_invoice_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase H.2 — hard-delete every quote/invoice a
    prior commit inserted for this batch.

    Status machine::

        committed → rolling_back → rolled_back
                                ↘ rollback_failed

    Collision detection (Phase H.2.B ruling §G): if any quote's
    ``updated_at`` is greater than the batch's ``committed_at``,
    snapshot the full doc into the ``import_audit.collisions``
    array before deleting so audit-replay recovery remains
    possible.
    """
    tenant_id = tenant["id"]

    # ── Status guard: flip committed → rolling_back atomically.
    guarded = await db.import_batches.find_one_and_update(
        {"id": batch_id, "tenant_id": tenant_id,
          "status": _STATUS_COMMITTED},
        {"$set": {"status": _STATUS_ROLLING_BACK,
                    "rollback_started_at": datetime.now(timezone.utc).isoformat()}},
        return_document=True,
    )
    if guarded is None:
        row = await db.import_batches.find_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"_id": 0, "status": 1},
        )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "batch_not_found",
                    "message": (
                        f"No import batch with id={batch_id!r} for this tenant."
                    ),
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "batch_not_committed",
                "message": (
                    f"Batch {batch_id!r} is in status "
                    f"{row.get('status')!r}, expected "
                    f"{_STATUS_COMMITTED!r}."
                ),
                "current_status": row.get("status"),
            },
        )

    try:
        rollback_result = await rollback_batch(
            batch=guarded,
            tenant_id=tenant_id,
            operator=user,
            db=db,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.exception(
            "[pdf-commit] tenant=%s batch=%s rollback failed: %s",
            tenant_id, batch_id, exc,
        )
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_ROLLBACK_FAILED,
                        "rollback_error": str(exc)[:400]}},
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error": "rollback_failed",
                "message": str(exc)[:400],
            },
        )

    audit_id = await write_import_audit(
        action="rollback",
        batch=guarded,
        tenant_id=tenant_id,
        operator=user,
        rollback_result=rollback_result,
        db=db,
    )

    rolled_back_at = datetime.now(timezone.utc).isoformat()
    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant_id},
        {"$set": {
            "status": _STATUS_ROLLED_BACK,
            "rolled_back_at": rolled_back_at,
            "rolled_back_by_user_id": user.get("id"),
            "rollback_audit_id": audit_id,
        }, "$unset": {"rollback_started_at": ""}},
    )

    return {
        "batch_id": batch_id,
        "status": _STATUS_ROLLED_BACK,
        "quotes_deleted": rollback_result.quotes_deleted,
        "collision_count": rollback_result.collision_count,
        "audit_id": audit_id,
    }
