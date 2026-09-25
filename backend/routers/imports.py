"""Task H · Phase H.1 · Feb-2026 — PDF Invoice Importer router.

Single endpoint: ``POST /api/imports/pdf-invoice`` — accepts a
multipart PDF upload, runs the Commit-2 two-pass extractor +
Commit-3 mapper, returns an ``ExtractedBatch`` + per-doc
``MapperReport[]`` preview.  NO database writes to the
``quotes`` collection at this phase — H.2 will own that.

Auth: ``require_admin`` (mirrors Task H0 § 3 role gate).
Tenant: ``get_current_tenant`` (strict multi-tenant isolation).

Rate limit: at most 3 concurrent ``status=in_flight`` batches
per tenant within a 5-minute window.  Enforced via
``db.import_batches.count_documents`` — persistent across worker
restarts (unlike an in-memory guard which would allow burst-
past-limit in a multi-worker deploy).

Response payload cap: mapper truncates ``line_items`` to 25 per
doc for the wire payload.  Full extractor output stays in
``db.import_batches.{batch_id}.extracted_documents_full`` for
Phase H.2 commit retrieval.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from config import db
from services.imports.extraction_schema import ExtractedBatch, MapperReport
from services.imports.pdf_invoice_extractor import extract
from services.imports.pdf_mapper import map_extracted_to_quote_in
from utils import require_admin

# ``get_current_tenant`` mirrors the import shape used by
# ``routers/quotes.py``.
from routers.tenants import get_current_tenant


logger = logging.getLogger("routers.imports")

# H.1 spec constants.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024        # 10 MB
_RATE_LIMIT_MAX_IN_FLIGHT = 3
_RATE_LIMIT_WINDOW = timedelta(minutes=5)

router = APIRouter(prefix="/api/imports", tags=["imports"])


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


async def _rate_limit_check(tenant_id: str) -> None:
    """H.1 spec §Rate-limit guard.  Counts ``status=in_flight``
    rows within the 5-min window; anything older than the window
    is treated as abandoned and does NOT count."""
    now = datetime.now(timezone.utc)
    cutoff = (now - _RATE_LIMIT_WINDOW).isoformat()
    in_flight = await db.import_batches.count_documents({
        "tenant_id": tenant_id,
        "status": "in_flight",
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


@router.post("/pdf-invoice")
async def import_pdf_invoice(
    file: UploadFile = File(...),
    hint_doc_kind: Optional[str] = Form(default=None),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Task H · Phase H.1 — extract + preview.  See module doc."""
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
    # UploadFile.read() buffers to memory; we cap by streaming
    # up to _MAX_UPLOAD_BYTES+1 and rejecting on overflow. The
    # ``+1`` sentinel lets us distinguish "at the limit" (OK)
    # from "past the limit" (reject).
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

    # ── Reserve an in_flight batch row ─────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    start_ms = time.perf_counter()

    # We stamp the batch id AFTER the extractor runs because the
    # extractor generates its own UUID + we want the batch_id
    # persisted here to match.  Insert a placeholder now with an
    # ephemeral id; upgrade to the real id below.
    reservation_id = f"reservation-{tenant_id}-{now_iso}"
    await db.import_batches.insert_one({
        "id": reservation_id,
        "tenant_id": tenant_id,
        "status": "in_flight",
        "source_filename": file.filename or "upload.pdf",
        "created_at": now_iso,
        "created_by": user.get("id"),
    })

    try:
        # ── Extract ────────────────────────────────────────
        batch: ExtractedBatch = await extract(
            pdf_bytes=pdf_bytes,
            tenant_id=tenant_id,
            source_filename=file.filename or "upload.pdf",
            hint_doc_kind=hint_doc_kind,
            db=db,
        )

        # ── Map every document ─────────────────────────────
        mapper_previews: List[MapperReport] = []
        for idx, doc in enumerate(batch.documents):
            report = await map_extracted_to_quote_in(
                doc, db=db, tenant_id=tenant_id,
                batch_id=batch.batch_id,
                operator_user=user, source_doc_index=idx,
            )
            mapper_previews.append(report)

        duration_ms = int((time.perf_counter() - start_ms) * 1000)

        # ── Persist the batch record (H.2 will read this) ──
        # Replace the reservation row with the real batch id +
        # store full extractor output so H.2 can retrieve
        # truncated line-item lists.
        await db.import_batches.delete_one({"id": reservation_id})
        await db.import_batches.insert_one({
            "id": batch.batch_id,
            "tenant_id": tenant_id,
            "status": "preview_complete",
            "source_filename": batch.source_filename,
            "source_sha256": batch.source_sha256,
            "source_byte_count": batch.source_byte_count,
            "page_count": batch.page_count,
            "model_used": batch.model_used,
            "duration_ms": duration_ms,
            "created_at": now_iso,
            "created_by": user.get("id"),
            "extraction_started_at": batch.extraction_started_at.isoformat(),
            "extraction_finished_at": batch.extraction_finished_at.isoformat(),
            "warnings": batch.warnings,
            # Full extractor output — Phase H.2 commit path reads
            # this to reconstruct the un-truncated line-item lists.
            "extracted_documents_full": [
                d.model_dump(mode="json") for d in batch.documents
            ],
            "mapper_previews": [
                m.model_dump(mode="json") for m in mapper_previews
            ],
        })

        logger.info(
            f"[pdf-import] tenant={tenant_id} batch={batch.batch_id} "
            f"file={batch.source_filename!r} pages={batch.page_count} "
            f"docs={len(batch.documents)} model={batch.model_used} "
            f"duration_ms={duration_ms}"
        )

        return {
            "batch": batch.model_dump(mode="json"),
            "mapper_previews": [m.model_dump(mode="json") for m in mapper_previews],
            "duration_ms": duration_ms,
        }

    except HTTPException:
        # Best-effort cleanup — cancel the reservation row.
        await db.import_batches.update_one(
            {"id": reservation_id},
            {"$set": {"status": "failed"}},
        )
        raise
    except Exception as exc:                                       # noqa: BLE001
        logger.exception(f"[pdf-import] tenant={tenant_id} error={exc}")
        await db.import_batches.update_one(
            {"id": reservation_id},
            {"$set": {"status": "failed", "error": str(exc)[:400]}},
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "extraction_failed",
                     "message": "Extraction pipeline failed; see server logs."},
        )
