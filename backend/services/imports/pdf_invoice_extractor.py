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
    '    {{"item_name": str|null, "sku": str|null, "description": str|null, '
    '"cost_rate": float|null, "qty": float|null, "tax_pct": float|null, '
    '"tax_line": float|null, "line_total": float|null, '
    '"confidence": 0.0-1.0}}\n'
    "  ],\n"
    '  "subtotal": float | null,\n'
    '  "tax_total": float | null,\n'
    '  "tax_rate": float | null,\n'
    '  "grand_total": float | null,\n'
    '  "amount_paid": float | null,\n'
    '  "total_due": float | null,\n'
    '  "is_paid": true | false | null,\n'
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
    "- ``item_name`` is the SHORT SKU / product-catalog label "
    "(e.g. 'CL-4LB', 'FLT-CART') suitable for a one-line "
    "inventory column; ``description`` is the LONG, human-"
    "readable narrative the invoice actually prints (e.g. "
    "'Chlorine 4-lb tablets delivered on 3/12 during weekly "
    "service').  These are DIFFERENT fields — extract each "
    "separately as it appears on the PDF.\n"
    "- ``sku`` is a distinct SKU / part-number column when the "
    "PDF prints one alongside item_name (rare — most vendors "
    "conflate the two).  Leave null when the PDF has only one "
    "identifier column; use ``item_name`` for the primary "
    "label in that case.\n"
    "- If the invoice line has only ONE text label (no separate "
    "SKU + description), put it in ``item_name`` and leave "
    "``description`` null.  Do NOT duplicate the string.\n"
    "- PRESERVE MULTI-LINE DESCRIPTIONS VERBATIM.  If a line "
    "item's description wraps across multiple visual lines on "
    "the PDF, join them with ``\\n`` (newline) — do NOT "
    "concatenate with spaces and do NOT truncate.  Every "
    "character the PDF shows in the description column must "
    "round-trip into the ``description`` field.\n"
    "- ``line_total`` MUST be extracted verbatim from the PDF's "
    "line-item column.  Do NOT compute it as qty × price — a "
    "PDF's printed line_total may reflect discounts or rounding "
    "the extractor cannot see.  Leave null only when the PDF "
    "literally does not print a per-line total.\n"
    "- ``tax_line`` is the per-line tax AMOUNT in dollars when "
    "the PDF prints a per-line tax column.  Distinct from "
    "``tax_pct`` (per-line tax rate).  Leave null when the PDF "
    "shows only a single roll-up ``tax_total`` at the bottom.\n"
    "- ``subtotal`` is the pre-tax total; ``tax_total`` is the "
    "tax value in DOLLARS; ``tax_rate`` is the tax value as a "
    "PERCENTAGE (e.g. 6.25 for 6.25%).  ``grand_total`` is the "
    "final amount owed — capture it from ANY of the following "
    "printed labels: 'Total', 'Total Due', 'Amount Due', "
    "'Balance Due', 'Grand Total', 'Invoice Total', or the "
    "final bold row of the totals block.  If the PDF prints "
    "ONLY a subtotal + tax_total with no explicit grand-total "
    "line, still capture ``grand_total`` as the sum. "
    "When all three (subtotal / tax_total / grand_total) are "
    "visible, verify that ``subtotal + tax_total ≈ grand_total`` "
    "(small rounding differences <$0.01 are fine).\n"
    "- PDFI-PAID-A · Feb-2026 — ``is_paid`` is a DERIVED boolean. "
    "Return true ONLY when the invoice is clearly marked paid: "
    "a visible ``PAID`` watermark / stamp, OR ``Total Due`` prints as "
    "$0.00, OR ``Amount Paid`` equals ``Total`` / ``Grand Total``. "
    "Return false when a positive balance remains (``Total Due`` > 0 "
    "or ``Amount Paid`` < ``Grand Total``).  Return null when the PDF "
    "shows no paid-status indicators at all.  ``amount_paid`` and "
    "``total_due`` are the raw-value inputs the backend uses to re-"
    "derive ``is_paid`` under a strict ruling when you return null; "
    "always extract them verbatim when visible.\n"
    "- ``paid_at`` MUST be an ISO date (``YYYY-MM-DD``) when a payment "
    "date is explicitly printed (``Paid on``, ``Payment Date``, "
    "``Received``, a dated ``PAID`` stamp).  Return null when the PDF "
    "shows ``is_paid=true`` indicators but no explicit date — the "
    "operator fills it in at the preview-confirm step.\n"
)

# PDF-FIX-C · Feb-2026 — prompt-version stamp for A/B measurement
# across extraction runs. Bumped whenever the extractor prompt
# semantic contract changes (new required fields, altered rules).
# Emitted on the ``[pdf_extract.start]`` log line at every
# ``extract()`` invocation so downstream analytics can bucket
# extraction quality by prompt revision.
EXTRACTOR_PROMPT_VERSION = "v3_pdf_mirror"


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


def _coerce_date(
    raw: Any,
    *,
    dayfirst: bool = False,
    log_ambiguous: bool = True,
) -> Optional[date]:
    """Accept every date shape the PDFs in the field print:
    ``YYYY-MM-DD``, ``MM/DD/YYYY``, ``DD/MM/YYYY``, ``Month DD, YYYY``,
    ``DD Month YYYY``, ``MMM DD YYYY``. Returns ``None`` on
    unparseable input — ``None`` bubbles up as a warning through
    the ``_ensure_document`` normalizer, never a hard error.

    PDF-MIRROR · Feb-2026 additions:

    * ``dayfirst`` — passed through to ``dateutil.parser.parse``
      so tenants configured with a non-US locale
      (``settings.locale != "en_US"``) parse ambiguous slash-
      separated dates as DD/MM/YYYY. Default False (US).
    * ``log_ambiguous`` — when True (default) an ambiguous
      ``NN/NN/YYYY`` where the first two digits could be either
      month or day (both ≤ 12) is logged at WARN so ops can
      cross-check the imported date against the source PDF.
      No parse behaviour change — the WARN is diagnostic only;
      the value returned still respects ``dayfirst``.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    try:
        parsed = _du_parser.parse(raw_str, dayfirst=dayfirst).date()
    except (ValueError, TypeError, OverflowError):
        logger.warning(
            "[pdf_extract.date] unparseable date %r — returning None",
            raw_str,
        )
        return None

    if log_ambiguous:
        # Detect ``NN/NN/YYYY`` (or ``NN-NN-YYYY``) where BOTH
        # NNs are ≤ 12 — genuinely ambiguous without locale.
        m = re.match(r"^\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\s*$",
                     raw_str)
        if m:
            a, b, _ = int(m.group(1)), int(m.group(2)), m.group(3)
            if 1 <= a <= 12 and 1 <= b <= 12 and a != b:
                logger.warning(
                    "[pdf_extract.date] ambiguous %r — parsed as "
                    "%s (dayfirst=%s). Verify tenant locale.",
                    raw_str, parsed.isoformat(), dayfirst,
                )
    return parsed


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
                       doc_position_hint: int,
                       structured_warnings: Optional[
                           List[Dict[str, Any]]
                       ] = None) -> ExtractedDocument:
    """Coerce a loose model dict into an ``ExtractedDocument``,
    normalising payment_method + dates, and appending warnings
    for every mapper-blocking optional that landed null.

    Feb-2026 · PDF Importer Sub-phase B — the caller may pass a
    ``structured_warnings`` list; when the ``doc_date`` gate fires
    the extractor ALSO appends a machine-readable entry
    ``{code, message, doc_position}`` to that list so downstream
    UI (Sub-phase E) can render per-row yellow-border banners
    per R8 · C.  Kept optional so unit tests that only care about
    the ``warnings: List[str]`` legacy behavior don't need to
    plumb the extra list.
    """
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
            ExtractedLineItem(
                **{**li, "description": li.get("description") or ""}
            )
            for li in (raw.get("line_items") or [])
            # PDF-FIX-C · Feb-2026 — accept items with EITHER
            # ``item_name`` OR non-empty ``description``.  The
            # new prompt allows ``description=null`` when only a
            # SKU is on the invoice line, so filtering strictly
            # on ``description`` would drop legitimate SKU-only
            # rows.  Empty-both items still drop (matches the
            # PDF-FIX-B FE fallback which also skips them).
            if isinstance(li, dict)
            and (li.get("item_name") or (li.get("description") or "").strip())
        ],
        subtotal=raw.get("subtotal"),
        tax_total=raw.get("tax_total"),
        tax_rate=raw.get("tax_rate"),
        grand_total=raw.get("grand_total"),
        amount_paid=raw.get("amount_paid"),
        total_due=raw.get("total_due"),
        # PDFI-PAID-A · Feb-2026 — honor model-supplied ``is_paid`` when
        # the vision prompt returns an explicit bool; otherwise re-derive
        # under the STRICT ruling using the raw inputs the model
        # extracted.  Keeps vision + fast-path aligned on the same rule.
        is_paid=(
            raw["is_paid"]
            if isinstance(raw.get("is_paid"), bool)
            else _derive_is_paid(raw.get("amount_paid"), raw.get("total_due"))
        ),
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
        # Feb-2026 · Sub-phase B — sharpen the doc_date warning with a
        # structured code so Sub-phase E's per-row banner treatment
        # can identify + link to the offending row without regex
        # parsing the legacy string list.  R8 · C ruling.
        msg = (
            f"document {doc_position_hint}: doc_date missing / unparseable"
        )
        warnings.append(msg)
        if structured_warnings is not None:
            structured_warnings.append({
                "code": "doc_date_missing",
                "message": msg,
                "doc_position": doc_position_hint,
            })
    if doc.doc_kind in ("invoice", "estimate") and not doc.line_items:
        warnings.append(f"document {doc_position_hint}: line_items empty")

    # PDF-FIX-C · Feb-2026 — soft totals-consistency check.
    # When ``subtotal``, ``tax_total``, and ``grand_total`` are
    # all extracted, verify that ``subtotal + tax_total ≈
    # grand_total`` within $0.01. Mismatches are logged as
    # warnings (rulings §3) but never reject the document —
    # scanned invoices legitimately show rounding drift and we
    # can't distinguish that from an extractor error at write
    # time.  Downstream admin surfaces read the log for spot-
    # checks.
    _check_totals_consistency(doc, doc_position_hint)

    return doc


def _check_totals_consistency(
    doc: ExtractedDocument, doc_position_hint: int,
) -> None:
    """Log a warning when ``subtotal + tax_total`` diverges
    from ``grand_total`` by more than $0.01. No-op when any of
    the three fields is null (nothing to reconcile). Never
    raises — the extractor's write path stays fault-tolerant.
    """
    subtotal = doc.subtotal
    tax = doc.tax_total
    grand = doc.grand_total
    if subtotal is None or tax is None or grand is None:
        return
    computed = subtotal + tax
    delta = computed - grand
    # Round to pennies before the threshold check so IEEE-754
    # noise (e.g. ``100.00 - 100.01 = -0.01000...5``) doesn't
    # trigger a false-positive warning on legitimate
    # penny-level totals.  Semantic intent per rulings §3:
    # "$0.01 delta is exactly a penny and should NOT warn."
    if round(abs(delta), 2) > 0.01:
        logger.warning(
            f"[pdf_extract.consistency] subtotal_tax_mismatch "
            f"doc={doc_position_hint} subtotal={subtotal:.2f} "
            f"tax={tax:.2f} grand={grand:.2f} "
            f"computed={computed:.2f} delta={delta:+.2f}"
        )


# ── Public entrypoint ──────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════
# PDFI-III · Feb-2026 — PyMuPDF native-text fast path.
# ═══════════════════════════════════════════════════════════════════
# For native-text PDFs (text layer present, small enough to parse
# with regex rules), skip the two-pass gpt-4o pipeline entirely and
# synthesise an ``ExtractedDocument`` from ``page.get_text()`` output.
# Any required-field miss, oversize document, or empty text layer
# falls back to the vision path verbatim — operator sees zero
# behavioural difference, only faster + cheaper previews on the
# happy path. Every path decision is logged with structured context
# so hit-rate can be measured post-ship without a schema change.
#
# Required-field contract (ALL four must parse to accept):
#   * customer_name   — "Bill To:" or "Customer:" labelled line
#   * doc_date        — any format ``_coerce_date`` accepts
#   * grand_total     — labelled total line, positive float
#   * line_items      — ≥ 1 row with ``item_name`` + ``cost_rate``
# Everything else (address, doc_number, tax_rate, etc.) is
# best-effort — missing optionals do NOT trigger fallback.

_FAST_PATH_PAGE_LIMIT = 10
_FAST_PATH_MIN_TEXT_LEN = 50
_FAST_PATH_CONFIDENCE = 0.95

_FAST_DATE_RE = re.compile(
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
    r'\s+\d{1,2},?\s+\d{4}\b'
    r'|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b'
    r'|\b\d{4}-\d{2}-\d{2}\b',
    re.IGNORECASE,
)
_FAST_CUSTOMER_RE = re.compile(
    r'(?:Bill\s*To|Customer|Sold\s*To)\s*[:#]?\s*\n+\s*([^\n]+)',
    re.IGNORECASE,
)
_FAST_INV_NUM_RE = re.compile(
    r'(?:Invoice\s*#?|Invoice\s*No\.?)\s*[:#]?\s*(\d{3,})',
    re.IGNORECASE,
)
_FAST_INV_NUM_FALLBACK_RE = re.compile(r'(?<![A-Za-z0-9])#\s*(\d{3,})\b')
_FAST_TOTAL_RE = re.compile(
    r'(?:Grand\s*Total|Amount\s*Due|Total\s*Due|This\s*Invoice|Total)'
    r'\s*[:#]?\s*\$?\s*([\d]{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)',
    re.IGNORECASE,
)
_FAST_AMOUNT_PAID_RE = re.compile(
    r'(?:Amount\s*Paid|Paid)\s*[:#]?\s*\$?\s*([\d,]+(?:\.\d{1,2})?)',
    re.IGNORECASE,
)
_FAST_TOTAL_DUE_RE = re.compile(
    r'(?:Balance\s*Due|Total\s*Due)\s*[:#]?\s*\$?\s*([\d,]+(?:\.\d{1,2})?)',
    re.IGNORECASE,
)
# PDFI-PAID-A · Feb-2026 — payment-date keyword prefix followed by any
# of the shapes ``_FAST_DATE_RE`` already accepts (long-month, slash-
# separated, ISO).  Keyword list intentionally narrow — "Paid on" /
# "Payment Date" / "Date Paid" / "Received on".  Bare "Paid" (which
# would also match ``Amount Paid`` labels) is excluded so we don't
# false-positive on a dollar amount.
_FAST_PAID_AT_RE = re.compile(
    r'(?:Paid\s+on|Payment\s+Date|Date\s+Paid|Received\s+on)'
    r'\s*[:#]?\s*'
    r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'
    r'\s+\d{1,2},?\s+\d{4}'
    r'|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
    r'|\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)
# Line-item row pattern — leading non-numeric label, optional qty,
# two currency amounts (unit_price then line_total). Dollar signs
# optional, commas allowed, cents optional.
_FAST_LINE_ITEM_RE = re.compile(
    r'^\s*(?P<label>[A-Za-z][A-Za-z0-9 \-/&().,\'"]+?)'  # label
    r'(?:\s+(?P<qty>\d+(?:\.\d+)?))?'                      # optional qty
    r'\s+\$?\s*(?P<price>[\d,]+(?:\.\d{1,2})?)'            # unit price
    r'\s+\$?\s*(?P<total>[\d,]+(?:\.\d{1,2})?)\s*$'        # line total
)
_FAST_LINE_LABEL_BLACKLIST = {
    "total", "subtotal", "grand total", "amount due", "amount paid",
    "balance due", "total due", "tax", "sales tax", "this invoice",
    "paid", "payment",
}


def _parse_fast_total_value(raw: str) -> Optional[float]:
    """Strip commas / whitespace, coerce to float, reject on parse fail."""
    try:
        return float(str(raw).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


# PDFI-PAID-A · Feb-2026 — derived paid-status rule.
# STRICT ruling: both inputs must be present AND satisfy the predicate.
# ``amount_paid > 0`` AND ``total_due <= 0.01`` (tolerance for a nominal
# zero after float arithmetic).  Any missing input returns False — the
# caller surfaces this as "not clearly paid" and operator confirms at
# preview.  Never raises.
_PAID_ZERO_TOLERANCE = 0.01


def _derive_is_paid(
    amount_paid: Optional[float],
    total_due: Optional[float],
) -> bool:
    """Return True IFF the invoice is strictly marked paid.

    Required: both ``amount_paid`` and ``total_due`` are present (not
    None) AND ``amount_paid > 0`` AND ``total_due <= 0.01``.  Any
    missing input OR partial-payment state (``total_due > 0.01``)
    returns False.  Kept side-effect-free so both fast-path and
    vision-path callers can invoke it without threading context.
    """
    if amount_paid is None or total_due is None:
        return False
    try:
        if float(amount_paid) <= 0:
            return False
        if float(total_due) > _PAID_ZERO_TOLERANCE:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _parse_native_text_fields(text: str) -> Dict[str, Any]:
    """Rule-based extraction of invoice fields from a native-text
    layer. Returns a dict with whichever fields parsed cleanly —
    the caller enforces the required-field contract.
    """
    result: Dict[str, Any] = {}
    if not text or not text.strip():
        return result

    # ── Date — earliest occurrence ───────────────────────────
    m_date = _FAST_DATE_RE.search(text)
    if m_date:
        parsed_date = _coerce_date(m_date.group(0), log_ambiguous=False)
        if parsed_date is not None:
            result["doc_date"] = parsed_date

    # ── Customer name ────────────────────────────────────────
    m_cust = _FAST_CUSTOMER_RE.search(text)
    if m_cust:
        name = m_cust.group(1).strip()
        # Guard against the next heading accidentally sticking.
        if name and len(name) < 120:
            result["customer_name"] = name
            # Follow-on address block: up to 3 non-blank lines
            # after the name, until a line that looks like the
            # next section header (contains ':' or starts with
            # a known block keyword).
            idx = m_cust.end()
            tail_lines = [
                ln.strip() for ln in text[idx:].split("\n") if ln.strip()
            ]
            addr_lines: List[str] = []
            for ln in tail_lines[:4]:
                low = ln.lower()
                if ":" in ln:
                    break
                if any(low.startswith(h) for h in (
                    "invoice", "date", "due", "total", "amount",
                    "bill to", "subtotal",
                )):
                    break
                addr_lines.append(ln)
                if len(addr_lines) >= 3:
                    break
            if addr_lines:
                result["customer_address"] = ", ".join(addr_lines)

    # ── Invoice number ──────────────────────────────────────
    m_num = _FAST_INV_NUM_RE.search(text) or _FAST_INV_NUM_FALLBACK_RE.search(text)
    if m_num:
        result["doc_number"] = m_num.group(1)

    # ── Grand total — labelled form, pick the LAST labelled
    # hit so e.g. the "Total:" row at the bottom of the invoice
    # wins over a stray "Total:" header earlier on the page.
    # Fallback: largest currency figure anywhere in the text.
    labelled = list(_FAST_TOTAL_RE.finditer(text))
    if labelled:
        gt = _parse_fast_total_value(labelled[-1].group(1))
        if gt is not None and gt > 0:
            result["grand_total"] = gt
    if "grand_total" not in result:
        all_amounts = re.findall(
            r'\$\s*([\d,]+(?:\.\d{1,2})?)',
            text,
        )
        vals = [v for v in (_parse_fast_total_value(a) for a in all_amounts)
                if v is not None]
        if vals:
            result["grand_total"] = max(vals)

    # ── Amount paid + total due (nullable optionals) ────────
    m_paid = _FAST_AMOUNT_PAID_RE.search(text)
    if m_paid:
        v = _parse_fast_total_value(m_paid.group(1))
        if v is not None:
            result["amount_paid"] = v
    m_due = _FAST_TOTAL_DUE_RE.search(text)
    if m_due:
        v = _parse_fast_total_value(m_due.group(1))
        if v is not None:
            result["total_due"] = v

    # PDFI-PAID-A · Feb-2026 — payment date (nullable optional).
    # Vision path has carried ``paid_at`` since H.1; fast-path finally
    # extracts it here so a native-text invoice marked paid also
    # surfaces its payment date without a vision round-trip.
    m_paid_at = _FAST_PAID_AT_RE.search(text)
    if m_paid_at:
        parsed_paid_at = _coerce_date(m_paid_at.group(1), log_ambiguous=False)
        if parsed_paid_at is not None:
            result["paid_at"] = parsed_paid_at

    # Derived paid-status flag (STRICT ruling).  Written whenever
    # BOTH inputs parsed cleanly, otherwise defaults to False so
    # downstream readers get a definite bool rather than tri-state
    # None semantics.
    result["is_paid"] = _derive_is_paid(
        result.get("amount_paid"),
        result.get("total_due"),
    )

    # ── Line items — scan each line for the row pattern ────
    line_items: List[Dict[str, Any]] = []
    for raw_line in text.split("\n"):
        ln = raw_line.rstrip()
        if not ln.strip():
            continue
        m_li = _FAST_LINE_ITEM_RE.match(ln)
        if not m_li:
            continue
        label = m_li.group("label").strip()
        if label.lower() in _FAST_LINE_LABEL_BLACKLIST:
            continue
        price = _parse_fast_total_value(m_li.group("price"))
        line_total = _parse_fast_total_value(m_li.group("total"))
        if price is None or line_total is None:
            continue
        qty_raw = m_li.group("qty")
        try:
            qty = float(qty_raw) if qty_raw else 1.0
        except ValueError:
            qty = 1.0
        line_items.append({
            "description": label,
            "item_name": label,
            "qty": qty,
            "cost_rate": price,
            "line_total": line_total,
        })
    if line_items:
        result["line_items"] = line_items

    return result


def _try_text_fast_path(
    pdf_bytes: bytes,
    *,
    batch_id: str,
    doc_idx: int,
) -> Optional[ExtractedDocument]:
    """PDFI-III · Feb-2026 — synthesise an ``ExtractedDocument`` from
    a native-text PDF's PyMuPDF ``get_text()`` output. Returns
    ``None`` on any rejection condition so the caller falls through
    to the vision pipeline verbatim.
    """
    try:
        pdoc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:                              # noqa: BLE001
        logger.info(
            "pdfi_fast_path_decision",
            extra={
                "batch_id": batch_id,
                "doc_idx": doc_idx,
                "pages": 0,
                "text_len": 0,
                "decision": "rejected",
                "missing_fields": [f"pymupdf_open_error:{type(exc).__name__}"],
            },
        )
        return None
    try:
        page_count = pdoc.page_count
        if page_count > _FAST_PATH_PAGE_LIMIT:
            logger.info(
                "pdfi_fast_path_decision",
                extra={
                    "batch_id": batch_id,
                    "doc_idx": doc_idx,
                    "pages": page_count,
                    "text_len": 0,
                    "decision": "rejected",
                    "missing_fields": ["pages_over_limit"],
                },
            )
            return None
        page_texts = [pdoc[i].get_text() or "" for i in range(page_count)]
        if any(pt.strip() == "" for pt in page_texts):
            logger.info(
                "pdfi_fast_path_decision",
                extra={
                    "batch_id": batch_id,
                    "doc_idx": doc_idx,
                    "pages": page_count,
                    "text_len": sum(len(pt) for pt in page_texts),
                    "decision": "rejected",
                    "missing_fields": ["blank_page_text_layer"],
                },
            )
            return None
        full_text = "\n".join(page_texts)
        text_len = len(full_text)
        if text_len < _FAST_PATH_MIN_TEXT_LEN:
            logger.info(
                "pdfi_fast_path_decision",
                extra={
                    "batch_id": batch_id,
                    "doc_idx": doc_idx,
                    "pages": page_count,
                    "text_len": text_len,
                    "decision": "rejected",
                    "missing_fields": ["text_layer_too_short"],
                },
            )
            return None

        parsed = _parse_native_text_fields(full_text)
        missing: List[str] = []
        if not parsed.get("customer_name"):
            missing.append("customer_name")
        if parsed.get("doc_date") is None:
            missing.append("doc_date")
        gt = parsed.get("grand_total")
        if gt is None or gt <= 0:
            missing.append("grand_total")
        lis = parsed.get("line_items") or []
        if not lis or not all(
            (li.get("item_name") and li.get("cost_rate") is not None)
            for li in lis
        ):
            missing.append("line_items")

        if missing:
            logger.info(
                "pdfi_fast_path_decision",
                extra={
                    "batch_id": batch_id,
                    "doc_idx": doc_idx,
                    "pages": page_count,
                    "text_len": text_len,
                    "decision": "rejected",
                    "missing_fields": missing,
                },
            )
            return None

        logger.info(
            "pdfi_fast_path_decision",
            extra={
                "batch_id": batch_id,
                "doc_idx": doc_idx,
                "pages": page_count,
                "text_len": text_len,
                "decision": "accepted",
                "missing_fields": [],
                # PDFI-PAID-A · Feb-2026 — paid-status telemetry so
                # post-ship analytics can measure how often native-
                # text invoices land already-paid vs. open.
                "is_paid": bool(parsed.get("is_paid")),
                "amount_paid": parsed.get("amount_paid"),
                "paid_at_found": parsed.get("paid_at") is not None,
            },
        )
        return ExtractedDocument(
            doc_kind="invoice",
            source_page_range=[1, page_count],
            customer_name=parsed["customer_name"],
            customer_address=parsed.get("customer_address"),
            doc_number=parsed.get("doc_number"),
            doc_date=parsed["doc_date"],
            line_items=[ExtractedLineItem(**li) for li in parsed["line_items"]],
            grand_total=parsed["grand_total"],
            amount_paid=parsed.get("amount_paid"),
            total_due=parsed.get("total_due"),
            # PDFI-PAID-A · Feb-2026 — carry paid_at + derived is_paid
            # through the fast-path write.  Both nullable: paid_at is
            # None when the invoice is marked paid but no date is
            # printed (test (e) locks this); is_paid is False when the
            # STRICT ruling isn't satisfied.
            paid_at=parsed.get("paid_at"),
            is_paid=bool(parsed.get("is_paid")),
            extraction_confidence=_FAST_PATH_CONFIDENCE,
        )
    finally:
        pdoc.close()


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
    # PDF-FIX-C · Feb-2026 — prompt-version stamp on every run.
    # Downstream analytics can bucket extraction quality by
    # ``prompt_version`` across time.
    logger.info(
        f"[pdf_extract.start] prompt_version={EXTRACTOR_PROMPT_VERSION} "
        f"batch_id={batch_id} sha={sha[:8]} filename={source_filename!r}"
    )

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    warnings: List[str] = []
    # PDFI-III · Feb-2026 — attempt the native-text fast path
    # BEFORE any vision call. On a hit we return a single-
    # document ExtractedBatch with ``model_used`` tagged so
    # downstream metrics can bucket fast vs. vision runs. On
    # a miss we fall through to the two-pass vision pipeline
    # verbatim (ZERO change below this block).
    fast_doc = _try_text_fast_path(
        pdf_bytes, batch_id=batch_id, doc_idx=0,
    )
    if fast_doc is not None:
        logger.info(
            "pdfi_fast_path_hit",
            extra={
                "batch_id": batch_id,
                "pages": page_count,
                "sha": sha[:8],
            },
        )
        doc.close()
        finished = datetime.now(timezone.utc)
        return ExtractedBatch(
            batch_id=batch_id,
            source_filename=source_filename,
            source_sha256=sha,
            source_byte_count=len(pdf_bytes),
            page_count=page_count,
            tenant_id=tenant_id,
            documents=[fast_doc],
            warnings=[],
            structured_warnings=[],
            model_used="pymupdf-fast-path",
            extraction_started_at=started,
            extraction_finished_at=finished,
        )
    # Vision fallback path — PDFI-III fast-path above either
    # declined or found a required-field miss. Everything
    # below is the pre-PDFI-III two-pass vision pipeline,
    # unmodified.
    # Feb-2026 · PDF Importer Sub-phase B — additive structured
    # warnings list threaded through ``_ensure_document`` so
    # ``doc_date_missing`` entries carry a ``code`` + ``doc_position``
    # per R8 · C for Sub-phase E's per-row banner treatment.
    structured_warnings: List[Dict[str, Any]] = []

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
        documents.append(_ensure_document(
            raw, warnings, idx + 1,
            structured_warnings=structured_warnings,
        ))

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
        structured_warnings=structured_warnings,
        model_used=_MODEL_NAME,
        extraction_started_at=started,
        extraction_finished_at=finished,
    )
