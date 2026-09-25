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

# Statuses that count toward the per-tenant rate limit.  Both
# ``queued`` and ``processing`` are "in flight" for the purposes
# of the guard; terminal states (``preview_complete`` /
# ``failed`` / ``cancelled``) do not.
_IN_FLIGHT_STATUSES = (_STATUS_QUEUED, _STATUS_PROCESSING)


router = APIRouter(prefix="/api/imports", tags=["imports"])


# ─────────────────────────────────────────────────────────────
# Startup index ensure
# ─────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    """Called at server-startup. background=True so the create
    call does not block boot on large tenants."""
    try:
        await db.pending_import_customers.create_index(
            [("tenant_id", 1), ("batch_id", 1)],
            name="pending_import_customers_tenant_batch",
            background=True,
        )
        await db.pending_import_customers.create_index(
            [("tenant_id", 1), ("extracted_customer_name", 1)],
            name="pending_import_customers_tenant_name",
            background=True,
        )
        await db.import_batches.create_index(
            [("tenant_id", 1), ("status", 1), ("created_at", -1)],
            name="import_batches_tenant_status_created",
            background=True,
        )
        await db.import_batches.create_index(
            [("id", 1)], unique=True,
            name="import_batches_id_uniq",
            background=True,
        )
    except Exception as exc:                                       # noqa: BLE001
        logger.warning(f"[imports] index create skipped: {exc}")


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
