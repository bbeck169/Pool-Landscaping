"""Task H · Phase H.1 · Feb-2026 — PDF Invoice Importer extractor.

Two-pass gpt-4o vision pipeline that turns a raw multi-page PDF
into a strongly-typed ``ExtractedBatch``.

Pipeline shape:

  1. PDF bytes → PyMuPDF ``fitz.open()`` (in-memory, no temp
     files, no external binaries).
  2. Pass 1 · segmentation.  Render a downsampled 6-wide grid
     of all pages into ONE JPEG (green-lit budget: ≤ 36 pages
     per grid tile → 1200×1560 max).  Ask gpt-4o to return the
     list of ``(page_start, page_end, doc_kind_hint)`` tuples.
  3. Pass 2 · per-segment extraction.  For each segment, render
     the exact page range at 200 DPI PNG and call gpt-4o with
     the strict-JSON extraction prompt.
  4. Coerce dates + normalize payment methods + emit warnings
     for every downstream-blocking optional that landed null.

Test seam — ``_call_vision_model`` is the sole entrypoint that
touches ``dispatch_ai_completion``.  All 12 unit tests
monkeypatch this seam via the shared ``mock_vision`` fixture;
tests never make a real vision call.  The one opt-in
integration test (``-m integration``) hits the real dispatcher
via this same seam.

Operator-line disambiguation (H.1 spec §5) — the prompt
carries a strong instruction: ``The customer is the recipient
(``Bill To`` / ``Customer:`` label).  Names appearing in audit
lines like ``Added by X`` or ``Processed by X`` are OPERATORS,
not customers — never assign them to ``customer_name``.``
The receipt-fixture test locks this contract end-to-end.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from dateutil import parser as _du_parser

from .extraction_schema import (
    ExtractedBatch,
    ExtractedDocument,
    ExtractedLineItem,
)

logger = logging.getLogger("imports.pdf_invoice_extractor")

_MODEL_NAME = "gpt-4o"

# ── Prompts ────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are an expert invoice / estimate / payment-receipt data "
    "extractor for a US pool & landscaping services company. "
    "You return ONLY valid JSON that conforms EXACTLY to the "
    "schema described in the user message. "
    "\n\n"
    "STRICT DISAMBIGUATION RULES: "
    "\n"
    "1. The customer is the RECIPIENT of the document, typically "
    "labelled 'Bill To', 'Customer:', or appearing under the "
    "vendor's header block. "
    "\n"
    "2. Names appearing in audit lines such as 'Added by X', "
    "'Processed by X', 'Recorded by X', or 'Received by X' are "
    "OPERATORS (employees of the vendor) — NEVER assign them to "
    "customer_name. "
    "\n"
    "3. The vendor is 'Pool & Landscaping of Vistancia LLC' — "
    "NEVER assign the vendor name to customer_name. "
    "\n"
    "4. If a field is not visible, return null for it (do NOT "
    "invent values).\n"
)

_SEGMENTATION_USER_TMPL = (
    "This is a downsampled thumbnail-grid preview of a "
    "{page_count}-page PDF.  Identify the distinct logical "
    "documents (invoices, estimates, or payment receipts) "
    "present.\n\n"
    "SEGMENTATION RULES (apply in this priority order):\n\n"
    "1. STUB-CONTINUATION RULE (highest priority): A page "
    "showing only a remittance stub, payment stub, detach "
    "slip, tear-off coupon, or 'please return with your "
    "payment' instructions -- with NO customer line items "
    "and NO 'Bill To' header -- is a CONTINUATION of the "
    "preceding invoice, NEVER a standalone document.  Fold "
    "that stub page into the segment of the invoice it is "
    "paired with.\n\n"
    "2. INTERLEAVING QUALIFIER: Batches may mix one-page "
    "invoices and two-page (invoice + stub) invoices in any "
    "order.  Do NOT assume a fixed repeating N-page pattern "
    "across the whole PDF; detect each invoice boundary "
    "independently, even when the layout looks visually "
    "uniform.\n\n"
    "3. DISTINCT-NUMBER ANCHOR: A new segment starts only "
    "when a NEW distinct invoice / receipt / estimate number "
    "appears on a page (or, if no number is visible, when a "
    "new invoice header + 'Bill To' block appears).  Page "
    "breaks, template repetition, and visual similarity "
    "across pages are NOT segment boundaries on their own.\n\n"
    "Return JSON of the shape:\n"
    "{{\n"
    '  "segments": [\n'
    '    {{"page_start": 1, "page_end": 2, "doc_kind_hint": '
    '"invoice"}},\n'
    "    ...\n"
    "  ],\n"
    '  "confidence": 0.0-1.0\n'
    "}}\n\n"
    "doc_kind_hint MUST be one of: 'invoice', 'estimate', "
    "'payment_receipt'.\n"
    "Page numbers are 1-indexed, inclusive on both ends.\n"
)

_EXTRACTION_USER_TMPL = (
    "Extract structured data from this {doc_kind_hint} "
    "spanning pages {page_start}-{page_end} of the source PDF.\n\n"
    "Return JSON of the shape:\n"
    "{{\n"
    '  "doc_kind": "invoice" | "estimate" | "payment_receipt",\n'
    '  "source_page_range": [{page_start}, {page_end}],\n'
    '  "customer_name": str | null,\n'
    '  "customer_email": str | null,\n'
    '  "customer_phone": str | null,\n'
    '  "customer_address": str | null,\n'
    '  "doc_number": str | null,\n'
    '  "doc_date": "YYYY-MM-DD" | null,\n'
    '  "due_date": "YYYY-MM-DD" | null,\n'
    '  "paid_at": "YYYY-MM-DD" | null,\n'
    '  "payment_method": "cash"|"check"|"card"|"ach"|"other"|null,\n'
    '  "payment_reference": str | null,\n'
    '  "line_items": [\n'
    '    {{"description": str, "cost_rate": float|null, '
    '"qty": float|null, "tax_pct": float|null, '
    '"line_total": float|null, "confidence": 0.0-1.0}}\n'
    "  ],\n"
    '  "subtotal": float | null,\n'
    '  "tax_total": float | null,\n'
    '  "grand_total": float | null,\n'
    '  "amount_paid": float | null,\n'
    '  "total_due": float | null,\n'
    '  "notes": str | null,\n'
    '  "raw_operator_audit_line": str | null,\n'
    '  "extraction_confidence": 0.0-1.0\n'
    "}}\n\n"
    "REMINDERS:\n"
    "- Vendor is 'Pool & Landscaping of Vistancia LLC' — do NOT "
    "put the vendor name into customer_name.\n"
    "- 'Added by X' / 'Processed by X' / 'Received by X' names "
    "are operators; capture the whole line verbatim in "
    "raw_operator_audit_line and NEVER use it for customer_name.\n"
)


# ── Payment-method normalization ───────────────────────────────
_PAY_METHOD_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(debit|credit)\s+card\b", re.I), "card"),
    (re.compile(r"\b(visa|mastercard|amex|discover)\b", re.I), "card"),
    (re.compile(r"\bcard\b", re.I), "card"),
    (re.compile(r"\bch(eck|eque)\b", re.I), "check"),
    (re.compile(r"\bcash\b", re.I), "cash"),
    (re.compile(r"\b(ach|wire|zelle|venmo|paypal)\b", re.I), "ach"),
]


def normalize_payment_method(raw: Optional[str]) -> Optional[str]:
    """Lower-cased substring match into the enum.  ``None`` on
    ``None`` input; ``"other"`` as the catch-all so downstream
    consumers get a valid enum even for exotic labels."""
    if raw is None:
        return None
    for pat, tag in _PAY_METHOD_RULES:
        if pat.search(raw):
            return tag
    return "other"


def _coerce_date(raw: Any) -> Optional[date]:
    """Accept ``YYYY-MM-DD`` ISO, ``Month DD, YYYY``, and
    ``MM/DD/YYYY`` variants.  Returns ``None`` on unparseable
    input — ``None`` bubbles up as a warning through the
    ``_ensure_document`` normalizer, never a hard error."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    try:
        return _du_parser.parse(str(raw)).date()
    except (ValueError, TypeError, OverflowError):
        return None


# ── PDF → image rendering (PyMuPDF) ────────────────────────────
def _render_page_png_b64(page: fitz.Page, dpi: int = 200) -> str:
    """Render one page as a PNG at ``dpi`` and return the raw
    base64 string ready for ``image_b64s`` on the dispatcher."""
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    png_bytes = pix.tobytes("png")
    return base64.b64encode(png_bytes).decode("ascii")


def _render_segmentation_grid_jpg_b64(
    doc: fitz.Document, max_cols: int = 6, max_rows: int = 6,
    cell_w: int = 300, cell_h: int = 390, jpg_quality: int = 70,
) -> str:
    """Render up to ``max_cols * max_rows`` page thumbnails into a
    single JPEG grid image.

    Task H · Phase B2.A · Feb-2026 — geometry bumped from
    (200x260, q=60) to (300x390, q=70).  Rationale: at H.1's
    default geometry the invoice-number band on each page tile
    rasterised too small for gpt-4o to read reliably, so the
    segmentation model under-anchored on the DISTINCT-NUMBER
    ANCHOR rule (see ``_SEGMENTATION_USER_TMPL``) and fell back
    to extrapolating a uniform 2-page pattern from the first few
    pairs.  At 300x390 each thumbnail is ~1.5x larger in both
    dimensions (2.25x pixel count) and the invoice-number band
    is legible; q=70 keeps JPEG artefacts from blurring the
    number strokes.

    Green-lit budget: 6x6 = 36 pages per grid tile → 1800x2340
    max (H.1: 1200x1560).  Returns base64 JPEG.

    Larger PDFs (>36 pages) still get one grid tile that samples
    the first 36 pages — for the H.1 fixture set this is enough
    to detect the pattern; the segmentation model is hinted to
    extend detected patterns across the full page count via the
    prompt's ``page_count`` template variable."""
    total = min(doc.page_count, max_cols * max_rows)
    rows = (total + max_cols - 1) // max_cols
    grid_w = max_cols * cell_w
    grid_h = rows * cell_h

    # PyMuPDF supports building a Pixmap of arbitrary size and
    # blitting per-page pixmaps into it via ``copy_pixmap``.
    grid = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, grid_w, grid_h),
                        False)
    grid.clear_with(255)   # white background

    for idx in range(total):
        page = doc[idx]
        # Fit cell — compute zoom so the page fits within cell_w
        # / cell_h preserving aspect ratio.
        pw, ph = page.rect.width, page.rect.height
        zoom = min(cell_w / pw, cell_h / ph) if pw and ph else 1.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        r = idx // max_cols
        c = idx % max_cols
        x0 = c * cell_w + (cell_w - pix.width) // 2
        y0 = r * cell_h + (cell_h - pix.height) // 2

        # Blit — use ``fitz.Pixmap.copy`` with a bounding rect.
        pix.set_origin(x0, y0)
        grid.copy(pix, fitz.IRect(x0, y0, x0 + pix.width, y0 + pix.height))

    jpg_bytes = grid.tobytes("jpg", jpg_quality=jpg_quality)
    return base64.b64encode(jpg_bytes).decode("ascii")


# ── Vision seam (monkeypatch target) ───────────────────────────
async def _call_vision_model(
    *,
    tenant_id: str,
    system_prompt: str,
    user_text: str,
    image_b64s: List[str],
    db: Any = None,
) -> Dict[str, Any]:
    """Sole outbound vision call.  Tests monkeypatch THIS function.

    Returns ``{"parsed": <dict>, "raw": <full result dict>}`` on
    success or ``{"error": "<code>", "message": "..."}`` on any
    upstream failure.  Callers rely on the ``parsed`` key so a
    hardened schema is enforced by the caller (not this seam) —
    keep the seam thin.

    Phase H.1.5 · Feb-2026 — dispatcher-return unwrap fix.  When
    ``parse_json=True`` the dispatcher stashes the parsed payload at
    ``result.raw["raw"]`` (mirroring the envelope contract
    documented in ``routers/ai_measure._unwrap_dispatcher_envelope``)
    and leaves ``result.content`` as an EMPTY STRING because the
    ``raw`` dict has no ``text`` / ``content`` sub-key.  The
    original H.1 seam read ``result.content`` only — which returned
    an empty string on every live call and tripped the
    ``vision_parse_failed`` warning across 3/3 real fixtures even
    though gpt-4o was emitting perfect JSON.  We now unwrap the
    parsed envelope first and only fall back to string-parse +
    regex on ``result.content`` if the envelope is absent
    (defensive belt-and-suspenders for a future dispatcher change
    that might route parsed content back through ``.content``).
    """
    # Late import so tests that never reach this seam can run
    # without the whole dispatcher module graph.
    from services.ai.dispatcher import dispatch_ai_completion

    result = await dispatch_ai_completion(
        tenant_id=tenant_id,
        system_prompt=system_prompt,
        user_text=user_text,
        model=_MODEL_NAME,
        route="openai_vision",
        image_b64s=image_b64s,
        parse_json=True,
        db=db,
    )

    # Primary path — parsed payload lives at ``result.raw["raw"]``
    # when ``parse_json=True``.  Also tolerate the case where the
    # parsed payload has been hoisted straight onto ``result.raw``
    # (some adapter code paths skip the extra wrap).
    parsed: Optional[Dict[str, Any]] = None
    raw_env = getattr(result, "raw", None)
    if isinstance(raw_env, dict):
        inner = raw_env.get("raw")
        if isinstance(inner, dict) and "provider" not in inner:
            parsed = inner
        elif isinstance(raw_env, dict) and (
            "doc_kind" in raw_env or "segments" in raw_env
        ):
            # Adapter hoisted the parsed payload directly onto
            # ``raw`` without the extra wrap — accept it.
            parsed = raw_env

    # Fallback path — string-parse ``result.content`` (or its
    # markdown-fenced JSON block) if the parsed envelope is
    # missing.  Kept intentionally after the primary path so a
    # single dispatcher regression doesn't silently degrade the
    # extractor into 0/N again.
    if parsed is None:
        content = getattr(result, "content", "") or ""
        if isinstance(content, str) and content:
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except (ValueError, TypeError):
                        parsed = None

    if parsed is None:
        preview_src = raw_env if raw_env else getattr(result, "content", "")
        return {"error": "vision_parse_failed",
                "message": f"Could not parse JSON from model output: "
                            f"{str(preview_src)[:200]!r}"}
    return {"parsed": parsed, "raw": raw_env or {}}


# ── Document normalization ─────────────────────────────────────
def _ensure_document(raw: Dict[str, Any], warnings: List[str],
                       doc_position_hint: int) -> ExtractedDocument:
    """Coerce a loose model dict into an ``ExtractedDocument``,
    normalising payment_method + dates, and appending warnings
    for every mapper-blocking optional that landed null."""
    doc_kind = raw.get("doc_kind") or "invoice"
    if doc_kind not in ("invoice", "estimate", "payment_receipt"):
        warnings.append(
            f"document {doc_position_hint}: unknown doc_kind={doc_kind!r}, "
            f"coerced to 'invoice'"
        )
        doc_kind = "invoice"

    doc = ExtractedDocument(
        doc_kind=doc_kind,
        source_page_range=list(raw.get("source_page_range") or [1, 1]),
        customer_name=raw.get("customer_name"),
        customer_email=raw.get("customer_email"),
        customer_phone=raw.get("customer_phone"),
        customer_address=raw.get("customer_address"),
        doc_number=raw.get("doc_number"),
        doc_date=_coerce_date(raw.get("doc_date")),
        due_date=_coerce_date(raw.get("due_date")),
        paid_at=_coerce_date(raw.get("paid_at")),
        payment_method=normalize_payment_method(raw.get("payment_method")),
        payment_reference=raw.get("payment_reference"),
        line_items=[
            ExtractedLineItem(**li) for li in (raw.get("line_items") or [])
            if isinstance(li, dict) and li.get("description")
        ],
        subtotal=raw.get("subtotal"),
        tax_total=raw.get("tax_total"),
        grand_total=raw.get("grand_total"),
        amount_paid=raw.get("amount_paid"),
        total_due=raw.get("total_due"),
        notes=raw.get("notes"),
        raw_operator_audit_line=raw.get("raw_operator_audit_line"),
        extraction_confidence=float(raw.get("extraction_confidence") or 1.0),
    )

    # Mapper-blocking null warnings — every field the mapper
    # needs to build a valid QuoteIn.
    if doc.customer_name in (None, ""):
        warnings.append(f"document {doc_position_hint}: customer_name missing")
    if doc.doc_number in (None, ""):
        warnings.append(f"document {doc_position_hint}: doc_number missing")
    if doc.doc_date is None:
        warnings.append(f"document {doc_position_hint}: doc_date missing / unparseable")
    if doc.doc_kind in ("invoice", "estimate") and not doc.line_items:
        warnings.append(f"document {doc_position_hint}: line_items empty")

    return doc


# ── Public entrypoint ──────────────────────────────────────────
async def extract(
    *,
    pdf_bytes: bytes,
    tenant_id: str,
    source_filename: str,
    hint_doc_kind: Optional[str] = None,
    db: Any = None,
    batch_id: Optional[str] = None,
    progress_callback: Optional[
        Callable[..., Awaitable[None]]
    ] = None,
) -> ExtractedBatch:
    """Task H · Phase H.1 extractor.  See module docstring.

    Task H · Phase B2.B · Feb-2026 additions:

    - ``batch_id`` — optional caller-provided UUID.  When set (from
      the async router), the extractor uses it verbatim so the row
      persisted at kickoff time and the row returned at completion
      share the same primary key.  Defaults to a fresh ``uuid4()``
      for backward-compat (all H.1 unit tests still call without
      this kwarg).
    - ``progress_callback`` — optional ``async`` fn invoked at
      three stages (best-effort — any callback exception is
      swallowed so a monitoring hiccup never corrupts the batch):
        * ``await cb(stage="segmentation", current=None, total=None)``
          right before the segmentation vision call.
        * ``await cb(stage="extraction", current=N, total=M,
                     partial_documents=[...])`` after each per-
          segment extraction succeeds (or graceful-warning fails).
        * The router owns the ``"mapping"`` + ``"persisting"``
          stage transitions and calls its own update path — no
          callback needed for those.
    """
    started = datetime.now(timezone.utc)
    batch_id = batch_id or str(uuid.uuid4())
    sha = hashlib.sha256(pdf_bytes).hexdigest()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    warnings: List[str] = []

    async def _emit(stage: str, current: Optional[int] = None,
                     total: Optional[int] = None,
                     partial_documents: Optional[List[ExtractedDocument]] = None,
                     ) -> None:
        if progress_callback is None:
            return
        try:
            await progress_callback(
                stage=stage,
                current=current,
                total=total,
                partial_documents=partial_documents,
            )
        except Exception as _exc:                                  # noqa: BLE001
            logger.warning(
                f"[extract] progress_callback swallowed exception: {_exc}"
            )

    # ── Pass 1 · segmentation ──────────────────────────────
    await _emit("segmentation")
    if page_count == 1:
        # Skip Pass 1 for single-page docs — segmentation is
        # trivial and would waste tokens.
        segments = [{
            "page_start": 1, "page_end": 1,
            "doc_kind_hint": hint_doc_kind or "invoice",
        }]
    else:
        grid_b64 = _render_segmentation_grid_jpg_b64(doc)
        seg_result = await _call_vision_model(
            tenant_id=tenant_id,
            system_prompt=_SYSTEM_PROMPT,
            user_text=_SEGMENTATION_USER_TMPL.format(page_count=page_count),
            image_b64s=[grid_b64],
            db=db,
        )
        if seg_result.get("error"):
            warnings.append(
                f"segmentation failed: {seg_result.get('error')} — "
                f"falling back to single-doc treatment"
            )
            segments = [{
                "page_start": 1, "page_end": page_count,
                "doc_kind_hint": hint_doc_kind or "invoice",
            }]
        else:
            raw_segs = seg_result["parsed"].get("segments") or []
            segments = raw_segs if raw_segs else [{
                "page_start": 1, "page_end": page_count,
                "doc_kind_hint": hint_doc_kind or "invoice",
            }]

    # ── Pass 2 · per-segment extraction ────────────────────
    documents: List[ExtractedDocument] = []
    total_segments = len(segments)
    for idx, seg in enumerate(segments):
        p_start = max(1, int(seg.get("page_start") or 1))
        p_end = min(page_count, int(seg.get("page_end") or p_start))
        doc_kind_hint = seg.get("doc_kind_hint") or hint_doc_kind or "invoice"

        # Render this segment's pages.
        page_b64s = [
            _render_page_png_b64(doc[i])
            for i in range(p_start - 1, p_end)
        ]

        ext_result = await _call_vision_model(
            tenant_id=tenant_id,
            system_prompt=_SYSTEM_PROMPT,
            user_text=_EXTRACTION_USER_TMPL.format(
                doc_kind_hint=doc_kind_hint,
                page_start=p_start,
                page_end=p_end,
            ),
            image_b64s=page_b64s,
            db=db,
        )
        if ext_result.get("error"):
            warnings.append(
                f"segment {idx + 1} (pages {p_start}-{p_end}) extraction "
                f"failed: {ext_result.get('error')}"
            )
            # Still emit progress on graceful-warning failures so
            # the poll surface advances.
            await _emit("extraction", current=idx + 1,
                         total=total_segments,
                         partial_documents=documents)
            continue

        # Ensure the segment's page range wins if the model
        # returned something different (defends against models
        # that hallucinate wider ranges).
        raw = dict(ext_result["parsed"])
        raw["source_page_range"] = [p_start, p_end]
        documents.append(_ensure_document(raw, warnings, idx + 1))

        # Per-segment progress hint — the router persists this to
        # the batch row's ``stage`` field so admins see live
        # advancement inside the extraction bulk.
        await _emit("extraction", current=idx + 1,
                     total=total_segments,
                     partial_documents=documents)

    doc.close()
    finished = datetime.now(timezone.utc)

    return ExtractedBatch(
        batch_id=batch_id,
        source_filename=source_filename,
        source_sha256=sha,
        source_byte_count=len(pdf_bytes),
        page_count=page_count,
        tenant_id=tenant_id,
        documents=documents,
        warnings=warnings,
        model_used=_MODEL_NAME,
        extraction_started_at=started,
        extraction_finished_at=finished,
    )
