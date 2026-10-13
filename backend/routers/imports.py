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
from typing import Any, Dict, Final, List, Optional

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
from services.imports.pdf_tiled_extractor import extract_with_tiling
from services.imports.pdf_mapper import map_extracted_to_quote_in
from utils import require_admin

# Preview isolation · Feb-2026 P0 — the PDF-invoice extractor
# produces structured rows with real customer PII (``customer_name``,
# ``bill_to_address``, phone/email metadata). Those rows persist to
# ``import_batches.extracted_documents_full`` + ``mapper_previews``
# which later turn into real ``customers`` + ``quotes`` rows on
# commit. We sanitize at the PERSIST site so every downstream
# consumer (commit route, preview polling route) reads pre-sanitized
# content. Production env: the helpers below are strict no-ops
# because ``sanitize_pdf_extracted_rows`` short-circuits on
# ``is_production_env()``.
from services.preview_isolation import (
    sanitize_pdf_extracted_rows as _preview_sanitize_pdf_extracted_rows,
)


def _preview_sanitize_pdf_docs(docs: list) -> list:
    """Sanitize the ``ExtractedDocument.model_dump()`` list before
    persist. No-op on production."""
    return _preview_sanitize_pdf_extracted_rows(docs)


def _preview_sanitize_pdf_previews(previews: list) -> list:
    """Sanitize the ``MapperReport.model_dump()`` list before
    persist. The nested ``quote_in`` + ``extracted_customer_*``
    fields carry PII; the recursive dict walker inside the
    sanitizer handles both top-level + nested keys."""
    return _preview_sanitize_pdf_extracted_rows(previews)


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
        # PDF Importer Sub-phase D · Feb-2026 — routed through the
        # tiled orchestrator. Small PDFs (≤36 pages) fast-path
        # straight to the original ``extract`` call byte-identically;
        # larger PDFs are sliced into overlapping tiles + merged.
        batch: ExtractedBatch = await extract_with_tiling(
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
        # Feb-2026 · PDF Import Hub bug-fixes · see
        # ``services/imports/pdf_preview_post.py`` module header.
        # Three defensive concerns run over every mapper report
        # before the preview envelope is persisted:
        #   • Bug 1 — force ``quote_in.doc_type`` to the operator's
        #     explicit ``hint_doc_kind`` when provided (classifier
        #     output stashed on ``auto_detected_doc_type`` for
        #     forensics).
        #   • Bug 3 — null ``customer_name`` + flag low-confidence
        #     when it looks like the document number.
        #   • Bug 2 defensive — WARN on line_total/subtotal
        #     mismatch > $0.01 and stamp the delta on quote_in so
        #     the FE expand panel surfaces the amber warning.
        try:
            from services.imports.pdf_preview_post import (
                apply_preview_post_processing,
            )
            apply_preview_post_processing(
                mapper_previews,
                hint_doc_kind=hint_doc_kind,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[pdf-import] preview post-processing failed — "
                "proceeding with raw mapper output; tenant=%s "
                "batch=%s", tenant_id, batch_id,
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
                # PDF Importer Sub-phase D · Feb-2026 — persist the
                # tile-summary alongside the batch so Sub-phase E's
                # frontend banner can render "78 pages · 4 tiles · 3
                # merges" without having to re-extract. ``None`` for
                # ≤36-page single-shot batches — the field is
                # additive-only.
                "tile_summary": batch.tile_summary,
                "extracted_documents_full": _preview_sanitize_pdf_docs([
                    d.model_dump(mode="json") for d in batch.documents
                ]),
                "mapper_previews": _preview_sanitize_pdf_previews([
                    m.model_dump(mode="json") for m in mapper_previews
                ]),
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
# PDF-HUB · Feb-2026 — Document Type hint whitelist.
#
# The FE dropdown emits one of ``invoice`` / ``estimate`` /
# ``payment`` (or an empty/omitted value = auto-detect). The
# extractor internally uses ``payment_receipt`` as the doc-kind
# literal — we normalise ``payment → payment_receipt`` at the
# router boundary so the wire vocabulary stays FE-friendly while
# the pipeline still sees its canonical value.
_HINT_DOC_KIND_ALLOWED: Final = frozenset({"invoice", "estimate", "payment", "payment_receipt"})


def _normalise_hint_doc_kind(raw: Optional[str]) -> Optional[str]:
    """Validate + normalise the ``hint_doc_kind`` form field.

    * ``None`` / empty → returns ``None`` (auto-detect).
    * ``invoice`` / ``estimate`` → returned as-is.
    * ``payment`` → normalised to ``payment_receipt`` (the
      extractor's internal literal).
    * ``payment_receipt`` → accepted for callers that already
      know the internal literal (existing tests + integrations).
    * Anything else → raises ``HTTPException(400,
      error_code="invalid_hint_doc_kind")``.
    """
    if raw is None or raw == "":
        return None
    if raw not in _HINT_DOC_KIND_ALLOWED:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_hint_doc_kind",
                "message": (
                    f"hint_doc_kind={raw!r} is not one of "
                    "{'invoice', 'estimate', 'payment'} (or empty for "
                    "auto-detect)."
                ),
            },
        )
    if raw == "payment":
        return "payment_receipt"
    return raw


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

    # PDF-HUB · Feb-2026 — validate the doc-kind hint BEFORE the
    # 415 MIME check so an invalid hint returns 400 rather than
    # being masked by a downstream 415 from a non-PDF payload.
    hint_doc_kind = _normalise_hint_doc_kind(hint_doc_kind)

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
    sanitized = _sanitize_row(row)
    # ─────────────────────────────────────────────────────────
    # Phase 33 Step C.1 · Feb-2026 — PDF-import auto-create preview
    # badge. When the batch is in ``preview_complete`` (operator is
    # about to click Commit) and carries ``PENDING::<uuid>``
    # sentinels, run a dry-run classification against
    # ``pending_import_customers`` so the FE can render a
    # "Will auto-create: N" badge BEFORE commit — no commit-time
    # surprises for the operator.
    #
    # Shape: ``pending_customer_classification: {will_auto_create: [...],
    # will_require_manual_review: [...]}``. Empty for batches without
    # PENDING sentinels (no-op); omitted on terminal statuses
    # (committed / rolled_back) where the batch no longer has
    # pending work to resolve.
    # ─────────────────────────────────────────────────────────
    status = sanitized.get("status") or ""
    mapper_previews = sanitized.get("mapper_previews") or []
    if (
        status == _STATUS_PREVIEW_COMPLETE
        and mapper_previews
    ):
        try:
            sanitized["pending_customer_classification"] = (
                await classify_pending_for_preview(
                    previews=mapper_previews,
                    tenant_id=tenant["id"],
                    db=db,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # Classification is a UI convenience — never let a
            # transient DB blip take down the main poll endpoint.
            logger.warning(
                "[pdf-import] classify_pending_for_preview failed "
                "for batch=%s tenant=%s (non-fatal): %s",
                batch_id, tenant["id"], exc,
            )
    return sanitized



# ═════════════════════════════════════════════════════════════
# Task H · Phase H.2 — Commit + rollback endpoints
# ═════════════════════════════════════════════════════════════
from pydantic import BaseModel  # noqa: E402

from services.imports.pdf_commit import (                          # noqa: E402
    DuplicateBatchError,
    PaidStatusValidationError,
    UnresolvedCustomersError,
    check_duplicates,
    classify_pending_for_preview,
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
    * ``customer_match_overrides`` — Feb-2026 match-ladder
      expansion.  Per-pending-id overrides keyed by the
      ``pending_customer_id`` (uuid portion of the ``PENDING::<uuid>``
      sentinel).  Current action vocabulary:

        * ``"reject_fuzzy"`` — operator rejected the dry-run
          fuzzy match surfaced on ``pending_customer_classification
          .will_match_existing``.  Backend skips the fuzzy tier
          for that pending; exact tiers still run; falls through
          to auto-create if exact tiers also miss.

      Empty dict / omitted = no overrides, ladder runs with
      default fuzzy ceiling.
    """
    on_duplicate: Optional[str] = _DUP_SKIP
    notes: Optional[str] = None
    customer_match_overrides: Optional[Dict[str, str]] = None


class _PreviewPatchIn(BaseModel):
    """PDFI-II · Feb-2026 — body for the preview-edit route.

    * ``doc_idx`` — 0-based index into ``batch.mapper_previews``
      (same ordering as the extractor emits).
    * ``patch`` — partial dict with any subset of top-level
      keys (``customer_name``, ``customer_address``,
      ``doc_number``, ``doc_date``, ``grand_total``) + a
      nested ``line_items`` dict keyed by integer index.
      Per-line value may be ``None`` (remove that line) or a
      partial dict (merge into the existing line). Indices
      beyond ``len(line_items)`` append the new line at the
      end — sparse appends pad with empty dicts, mirroring
      the JSON-array semantics the FE sends.
    """
    doc_idx: int
    patch: Dict[str, Any]


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
        # Feb-2026 · auto-create UX ticket — spec alias so FE
        # consumers can key off ``row_index`` without reaching
        # into ``source_doc_index``.
        "row_index": u.source_doc_index,
        "extracted_customer_name": u.extracted_customer_name,
        "pending_customer_id": u.pending_customer_id,
        "reason": getattr(u, "reason", None),
        # Per-row error_code so the FE can distinguish
        # low-confidence (Bug 3 demoted) rows from generic
        # no-identifying-info pendings when rendering the
        # resolve-customer picker amber warning.
        "error_code": (
            "customer_requires_manual_resolution"
            if getattr(u, "reason", None)
                == "customer_extraction_confidence_low"
            else "customer_requires_manual_resolution"
        ),
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
            customer_match_overrides=opts.customer_match_overrides,
        )
    except UnresolvedCustomersError as exc:
        # Phase 33 Step C.1 · Feb-2026 — residuals here are rows
        # the Step B auto-create helper could not resolve (zero
        # identifying info: no name, no address, no phone). Pre-
        # Phase-33 this bucket caught EVERY PENDING sentinel; now
        # it catches only truly manual-review cases.
        #
        # Reset batch to preview_complete so the operator can
        # resolve pendings via H.3 UI and retry.
        #
        # Feb-2026 · auto-create UX ticket — status flipped from
        # 400 → 422 with the new primary ``error_code``
        # ``"customer_requires_manual_resolution"``. Legacy
        # ``error="manual_review_required"`` + ``unresolved``
        # aliases are preserved for pre-FE-update consumers.
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_PREVIEW_COMPLETE},
              "$unset": {"commit_started_at": ""}},
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": exc.error_code,
                # Legacy top-level ``error`` alias — preserved
                # for pre-FE-update consumers.
                "error": "manual_review_required",
                "message": (
                    f"{len(exc.unresolved)} preview(s) carry "
                    f"customer rows that require manual "
                    f"resolution before commit. Pick an "
                    f"existing customer or type over the "
                    f"extracted name to proceed."
                ),
                "manual_review_needed": _serialise_unresolved(
                    exc.unresolved,
                ),
                # Legacy alias — preserved for pre-Phase-33
                # frontend callers. Will be dropped in a future
                # release after FE adopts manual_review_needed.
                "unresolved": _serialise_unresolved(exc.unresolved),
            },
        )
    except PaidStatusValidationError as exc:
        # PDFI-PAID-B · Feb-2026 — paid-status validation gate
        # fired BEFORE any db writes. Reset batch to
        # preview_complete so the operator can PATCH /preview
        # with the missing paid_at / amount_paid and rerun.
        await db.import_batches.update_one(
            {"id": batch_id, "tenant_id": tenant_id},
            {"$set": {"status": _STATUS_PREVIEW_COMPLETE},
              "$unset": {"commit_started_at": ""}},
        )
        _PAID_ERR_MSG = {
            "paid_without_date": (
                "One or more previews are marked is_paid=True "
                "but have no paid_at. Set paid_at via PATCH "
                "/preview or clear is_paid before commit."
            ),
            "paid_without_amount": (
                "One or more previews are marked is_paid=True "
                "but have amount_paid=0/null. Set amount_paid "
                "via PATCH /preview or clear is_paid before "
                "commit."
            ),
        }
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "pdf_import_row_validation",
                "error": exc.error_code,  # legacy alias — kept for FE back-compat
                "message": (
                    "One or more rows failed commit validation. "
                    + _PAID_ERR_MSG.get(exc.error_code, exc.error_code)
                ),
                "batch_id": batch_id,
                "doc_indices": exc.doc_indices,
                "rows": list(exc.rows or []),
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
        # PDF Importer Sub-phase C · Feb-2026 — per-doc-type
        # breakdown so the operator UI can render "3 invoices,
        # 1 estimate, 2 payments (1 unlinked)" without re-scanning
        # ``mapper_previews``.
        "committed": {
            "invoices": {
                "created": commit_result.invoices_created,
            },
            "estimates": {
                "created": commit_result.estimates_created,
            },
            "payments": {
                "created": commit_result.payments_created,
                "updated": commit_result.payments_updated,
                "unlinked": commit_result.payments_unlinked,
                "ids": commit_result.payment_ids,
                "errors": commit_result.payment_errors,
                # FIN-PARITY-A · Feb-2026 — reconciliation
                # summaries for every payment that carried an
                # ``invoice_id``. Empty array when all payments
                # were unlinked.
                "reconciled_invoices": commit_result.reconciled_invoices,
            },
        },
        "warnings": commit_result.warnings,
        # ═══════════════════════════════════════════════════════
        # Phase 33 Step C.1 · Feb-2026 — unified mixed-outcome
        # commit response. The FE renders inline per-row banners
        # keyed off these buckets instead of the old single-modal
        # error flow. Every bucket is a top-level array/object so
        # a mixed-outcome commit (some invoices created, some
        # customers auto-made, some duplicates skipped, some rows
        # flagged for manual review) can be rendered in one pass.
        #
        # Shape ruling: ADDITIVE — pre-Phase-33 keys above remain
        # unchanged for backwards compatibility. New keys below
        # layer on top so callers can migrate at their own pace.
        # ═══════════════════════════════════════════════════════
        "auto_created_customers": commit_result.auto_created_customers,
        "manual_review_needed": [],
        "skipped": {
            "duplicates": commit_result.quotes_skipped_duplicates,
            "idempotent": commit_result.quotes_skipped_idempotent,
        },
        "validation_errors": {
            "insert_errors": commit_result.insert_errors,
            "payment_errors": commit_result.payment_errors,
        },
        "summary": {
            "committed_count": (
                commit_result.invoices_created
                + commit_result.estimates_created
                + commit_result.payments_created
                + commit_result.payments_updated
            ),
            "auto_created_customers_count": len(
                commit_result.auto_created_customers,
            ),
            "skipped_count": (
                commit_result.quotes_skipped_duplicates
                + commit_result.quotes_skipped_idempotent
            ),
            "manual_review_count": 0,
            "warning_count": len(commit_result.warnings),
            "error_count": (
                len(commit_result.insert_errors)
                + len(commit_result.payment_errors)
            ),
        },
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


@router.patch("/pdf-invoice/{batch_id}/preview")
async def patch_pdf_invoice_preview(
    batch_id: str,
    body: _PreviewPatchIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """PDFI-II · Feb-2026 — edit a single preview before commit.

    Deep-merges ``body.patch`` into
    ``batch.mapper_previews[body.doc_idx].quote_in`` and persists
    to Mongo. Also bumps ``preview_patches_applied`` + appends to
    ``preview_patch_log`` (bounded to the most recent 50 entries)
    for observability.

    Guards:
      * 404 ``batch_not_found`` — row missing OR owned by another
        tenant (same cross-tenant posture the sibling GET uses).
      * 409 ``batch_wrong_status`` — only ``preview_complete`` is
        editable. Transient (``committing`` / ``rolling_back``)
        and terminal states are locked.
      * 422 ``doc_idx_out_of_range``.
      * 400 ``empty_patch`` / ``no_recognised_keys`` / malformed
        ``line_items`` shape.

    Unknown line-item sub-keys are silently dropped (narrow-merge
    semantics) so the FE can send a superset dict without tripping
    validation. Allowed per-line keys mirror the
    ``_line_item_to_quote_shape`` output: ``item_name``,
    ``description``, ``quantity``, ``unit_price``,
    ``line_total``, ``pricebook_item_id``, ``sku``, ``tax_pct``,
    ``tax_line``.
    """
    tenant_id = tenant["id"]
    row = await db.import_batches.find_one(
        {"id": batch_id, "tenant_id": tenant_id},
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
    cur_status = row.get("status")
    _PATCHABLE_STATES = {_STATUS_PREVIEW_COMPLETE}
    if cur_status not in _PATCHABLE_STATES:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "batch_wrong_status",
                "message": (
                    f"Batch {batch_id!r} is in status {cur_status!r}; "
                    f"preview edits allowed only in "
                    f"{sorted(_PATCHABLE_STATES)!r}."
                ),
                "current_status": cur_status,
            },
        )
    previews = row.get("mapper_previews") or []
    if body.doc_idx < 0 or body.doc_idx >= len(previews):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "doc_idx_out_of_range",
                "message": (
                    f"doc_idx={body.doc_idx} is outside "
                    f"[0,{len(previews)})."
                ),
                "doc_count": len(previews),
            },
        )
    patch = body.patch or {}
    if not patch:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "empty_patch",
                "message": "patch body cannot be empty.",
            },
        )

    preview = previews[body.doc_idx]
    quote_in = preview.setdefault("quote_in", {}) or {}
    preview["quote_in"] = quote_in
    patched_keys: List[str] = []

    _TOP_LEVEL_KEYS = {
        "customer_name", "customer_address",
        "doc_number", "doc_date", "grand_total",
        # PDFI-PAID-B · Feb-2026 — paid-status whitelist. The
        # operator fills these at preview-confirm when the
        # extractor couldn't derive them from the PDF (no
        # Payment Date line, operator-marked paid). Required
        # by the commit path's paid-status validation gate.
        "is_paid", "amount_paid", "paid_at",
    }
    for k in _TOP_LEVEL_KEYS:
        if k in patch:
            quote_in[k] = patch[k]
            patched_keys.append(k)

    if "line_items" in patch:
        li_patch = patch["line_items"]
        if not isinstance(li_patch, dict):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "line_items_patch_must_be_dict",
                    "message": (
                        "line_items patch must be a "
                        "{index: patch|null} dict."
                    ),
                },
            )
        _ALLOWED_LINE_KEYS = {
            "item_name", "description", "quantity",
            "unit_price", "line_total",
            "pricebook_item_id", "sku",
            "tax_pct", "tax_line",
        }
        existing_items = list(quote_in.get("line_items") or [])
        indexed: Dict[int, Any] = {}
        for raw_k, v in li_patch.items():
            try:
                i = int(raw_k)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "line_items_key_not_int",
                        "message": (
                            f"line_items patch key must be an "
                            f"integer index, got {raw_k!r}."
                        ),
                    },
                )
            indexed[i] = v
        delete_indices = sorted(
            (i for i, v in indexed.items() if v is None), reverse=True,
        )
        for i in delete_indices:
            if 0 <= i < len(existing_items):
                existing_items.pop(i)
        updates = sorted(
            ((i, v) for i, v in indexed.items() if v is not None),
            key=lambda t: t[0],
        )
        for i, line_patch in updates:
            if not isinstance(line_patch, dict):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "line_patch_must_be_dict",
                        "message": (
                            f"line_items[{i}] patch must be a "
                            f"dict or null."
                        ),
                    },
                )
            filtered = {
                kk: vv for kk, vv in line_patch.items()
                if kk in _ALLOWED_LINE_KEYS
            }
            if i < len(existing_items):
                existing_items[i] = {**existing_items[i], **filtered}
            else:
                while len(existing_items) < i:
                    existing_items.append({})
                existing_items.append(filtered)
        quote_in["line_items"] = existing_items
        patched_keys.append("line_items")

    if not patched_keys:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_recognised_keys",
                "message": (
                    "patch contained no recognised keys. Allowed: "
                    + repr(sorted(_TOP_LEVEL_KEYS | {"line_items"}))
                    + "."
                ),
            },
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "ts": now_iso,
        "user_id": user.get("id") or user.get("sub"),
        "doc_idx": body.doc_idx,
        "patched_keys": patched_keys,
    }
    new_log = list(row.get("preview_patch_log") or [])
    new_log.append(log_entry)
    if len(new_log) > 50:
        new_log = new_log[-50:]
    new_counter = int(row.get("preview_patches_applied") or 0) + 1

    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant_id},
        {"$set": {
            f"mapper_previews.{body.doc_idx}": preview,
            "preview_patches_applied": new_counter,
            "preview_patch_log": new_log,
            "preview_last_patched_at": now_iso,
        }},
    )

    return {
        "batch_id": batch_id,
        "doc_idx": body.doc_idx,
        "patched_keys": patched_keys,
        "preview": preview,
        "preview_patches_applied": new_counter,
    }
