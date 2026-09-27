"""PDF Importer Sub-phase D · Feb-2026 — tiled segmentation orchestrator.

Wraps :func:`services.imports.pdf_invoice_extractor.extract` with a
tile-based pre-processing pass for PDFs whose page count exceeds
:data:`TILE_PAGE_THRESHOLD`. The upstream extractor's segmentation
grid is limited to ``6 x 6 = 36`` pages (see
``pdf_invoice_extractor._render_segmentation_grid_jpg_b64``), so
anything beyond that never reaches the segmentation model. This
module slices the PDF into overlapping tiles, extracts each tile
independently (using the *same* :func:`extract` entry point, so
every downstream invariant — vision-model prompt, structured
warnings, doc_kind classifier — stays intact), and merges the
resulting documents on the natural key
``(doc_kind, doc_number, doc_date, customer_name)``.

Constants
─────────
    TILE_PAGE_THRESHOLD         36    ≤ this → single-shot path
    TILE_PAGE_SIZE              20    pages per tile
    TILE_PAGE_OVERLAP            4    trailing pages of tile N = leading of N+1
    TILE_CONCURRENCY             3    max in-flight extract() calls
    MAX_LINE_ITEMS_PER_MERGED_DOC 500  post-merge cap; warning at trigger

Public API
──────────
    extract_with_tiling(**kwargs) -> ExtractedBatch

Same kwargs as :func:`pdf_invoice_extractor.extract`. Returns the
same :class:`ExtractedBatch` shape with ``page_count`` reflecting
the FULL PDF and ``tile_summary`` populated iff the tile path was
taken.

Router wiring
─────────────
:mod:`routers.imports` imports :func:`extract_with_tiling` instead
of :func:`extract`. Small PDFs still exercise the single-shot code
path byte-identically — this wrapper is a no-op for them.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import fitz

from services.imports.extraction_schema import (
    ExtractedBatch, ExtractedDocument,
)
from services.imports.pdf_invoice_extractor import (
    extract as _single_shot_extract,
)


logger = logging.getLogger("pdf_tiled_extractor")


TILE_PAGE_THRESHOLD = 36
TILE_PAGE_SIZE = 20
TILE_PAGE_OVERLAP = 4
TILE_CONCURRENCY = 3
MAX_LINE_ITEMS_PER_MERGED_DOC = 500
_MAX_TILE_RETRIES = 1  # one retry per tile, then log-and-continue


# ═════════════════════════════════════════════════════════════════════
# Public entry point.
# ═════════════════════════════════════════════════════════════════════
async def extract_with_tiling(
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
    """Extract documents from ``pdf_bytes`` with tile orchestration.

    Delegates directly to :func:`pdf_invoice_extractor.extract` when
    ``page_count <= TILE_PAGE_THRESHOLD``. Otherwise slices the PDF
    into overlapping tiles, extracts each concurrently (capped at
    :data:`TILE_CONCURRENCY`), and merges cross-tile duplicates.
    """
    # Fast-path — count pages without a full render so small PDFs
    # avoid the tile-plan cost.
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page_count = doc.page_count

    if page_count <= TILE_PAGE_THRESHOLD:
        # Zero-risk delegation. Everything downstream (segmentation
        # grid, per-page extraction, structured warnings, cross-
        # tenant safety) is byte-identical to the pre-D behaviour.
        return await _single_shot_extract(
            pdf_bytes=pdf_bytes,
            tenant_id=tenant_id,
            source_filename=source_filename,
            hint_doc_kind=hint_doc_kind,
            db=db,
            batch_id=batch_id,
            progress_callback=progress_callback,
        )

    started = datetime.now(timezone.utc)
    batch_id = batch_id or str(uuid.uuid4())
    sha = hashlib.sha256(pdf_bytes).hexdigest()

    # ── Plan the tile page ranges ────────────────────────────
    tile_ranges = _plan_tile_ranges(
        page_count=page_count,
        tile_size=TILE_PAGE_SIZE,
        tile_overlap=TILE_PAGE_OVERLAP,
    )
    logger.info(
        "[tiled_extract] tenant=%s pages=%s tiles=%s ranges=%s",
        tenant_id, page_count, len(tile_ranges), tile_ranges,
    )

    # ── Extract every tile concurrently (bounded) ────────────
    sem = asyncio.Semaphore(TILE_CONCURRENCY)
    tile_warnings: List[Dict[str, Any]] = []

    async def _run_tile(tile_idx: int, span: Tuple[int, int]):
        async with sem:
            return await _extract_one_tile(
                tile_idx=tile_idx, span=span,
                pdf_bytes=pdf_bytes,
                tenant_id=tenant_id,
                source_filename=source_filename,
                hint_doc_kind=hint_doc_kind, db=db,
                warnings=tile_warnings,
            )

    tile_results: List[Optional[ExtractedBatch]] = await asyncio.gather(
        *[_run_tile(i, span) for i, span in enumerate(tile_ranges)],
        return_exceptions=False,
    )

    # ── Collect pre-merge documents (with their originating tile) ─
    pre_merge: List[Tuple[int, ExtractedDocument]] = []
    aggregate_warnings: List[str] = []
    aggregate_structured: List[Dict[str, Any]] = []
    model_used = "gpt-4o"  # will be overwritten by any successful tile
    for idx, res in enumerate(tile_results):
        if res is None:
            continue  # tile failed even on retry — already warned
        for d in res.documents:
            pre_merge.append((idx, d))
        for w in res.warnings:
            aggregate_warnings.append(f"[tile {idx + 1}] {w}")
        for sw in res.structured_warnings:
            sw_copy = dict(sw)
            sw_copy["tile_index"] = idx + 1
            aggregate_structured.append(sw_copy)
        model_used = res.model_used

    # ── Merge cross-tile duplicates + continuations ──────────
    merged, cross_tile_merges, merge_warnings = _merge_cross_tile_documents(
        pre_merge,
    )
    aggregate_warnings.extend(merge_warnings)

    finished = datetime.now(timezone.utc)

    tile_summary = {
        "total_pages": page_count,
        "tiles_used": len(tile_ranges),
        "docs_pre_merge": len(pre_merge),
        "docs_post_merge": len(merged),
        "cross_tile_merges": cross_tile_merges,
        "warnings": tile_warnings,
    }

    # Progress callback — surface the tile summary as a synthetic
    # "extraction complete" event so the router-side status watcher
    # can update the batch row's ``stage`` without needing tile-
    # awareness in its own code.
    if progress_callback is not None:
        try:
            await progress_callback(
                stage="extraction", current=len(tile_ranges),
                total=len(tile_ranges),
                partial_documents=merged,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[tiled_extract] progress_callback swallowed: %s", exc,
            )

    return ExtractedBatch(
        batch_id=batch_id,
        source_filename=source_filename,
        source_sha256=sha,
        source_byte_count=len(pdf_bytes),
        page_count=page_count,
        tenant_id=tenant_id,
        documents=merged,
        warnings=aggregate_warnings,
        structured_warnings=aggregate_structured,
        tile_summary=tile_summary,
        model_used=model_used,
        extraction_started_at=started,
        extraction_finished_at=finished,
    )


# ═════════════════════════════════════════════════════════════════════
# Tile planning.
# ═════════════════════════════════════════════════════════════════════
def _plan_tile_ranges(
    *, page_count: int, tile_size: int, tile_overlap: int,
) -> List[Tuple[int, int]]:
    """Return a list of 1-indexed inclusive ``(page_start, page_end)``
    tuples covering the full ``page_count`` with overlap.

    Example (tile_size=20, tile_overlap=4)::

        page_count=37  →  [(1, 20), (17, 37)]
        page_count=78  →  [(1, 20), (17, 36), (33, 52), (49, 68), (65, 78)]

    Guarantees: (1) every page appears in at least one tile,
    (2) every consecutive pair of tiles overlaps by exactly
    ``tile_overlap`` pages when possible, (3) the last tile is
    clipped to ``page_count``.

    Tail-tile absorption: if the naive stride would produce a
    trailing tile that adds ``<= tile_overlap`` new pages beyond
    the previous tile (i.e. the tail is almost entirely inside
    the overlap band), the previous tile is EXTENDED to cover
    ``page_count`` instead of appending a tiny redundant tile.
    This keeps the plan minimal on borderline page counts (e.g.,
    37 pages → 2 tiles, not 3).
    """
    if page_count <= tile_size:
        return [(1, page_count)]
    step = max(1, tile_size - tile_overlap)
    ranges: List[Tuple[int, int]] = []
    start = 1
    while start <= page_count:
        end = min(page_count, start + tile_size - 1)
        ranges.append((start, end))
        if end == page_count:
            break
        start += step
    # Tail absorption — see docstring. Only applies when there
    # are at least 2 tiles and the last tile's overhang beyond
    # the previous tile is within the overlap budget.
    if len(ranges) >= 2:
        prev_start, prev_end = ranges[-2]
        last_start, last_end = ranges[-1]
        if last_end - prev_end <= tile_overlap:
            ranges[-2] = (prev_start, last_end)
            ranges.pop()
    return ranges


# ═════════════════════════════════════════════════════════════════════
# Per-tile extraction with retry.
# ═════════════════════════════════════════════════════════════════════
async def _extract_one_tile(
    *,
    tile_idx: int,
    span: Tuple[int, int],
    pdf_bytes: bytes,
    tenant_id: str,
    source_filename: str,
    hint_doc_kind: Optional[str],
    db: Any,
    warnings: List[Dict[str, Any]],
) -> Optional[ExtractedBatch]:
    """Slice ``pdf_bytes`` to the tile page range, then call
    :func:`_single_shot_extract` up to ``1 + _MAX_TILE_RETRIES``
    times. Never re-raises — a persistently-failing tile logs a
    warning entry and returns ``None`` so the caller can continue
    with the remaining tiles (per PDF-D ruling #4)."""
    p_start, p_end = span
    try:
        tile_bytes = _slice_pdf_bytes(pdf_bytes, p_start, p_end)
    except Exception as exc:  # noqa: BLE001
        warnings.append({
            "code": "tile_slice_failed",
            "tile_index": tile_idx + 1,
            "message": (
                f"failed to slice pages {p_start}-{p_end}: {exc}"
            ),
        })
        return None

    last_exc: Optional[BaseException] = None
    for attempt in range(_MAX_TILE_RETRIES + 1):
        try:
            batch = await _single_shot_extract(
                pdf_bytes=tile_bytes,
                tenant_id=tenant_id,
                source_filename=(
                    f"{source_filename}#tile-{tile_idx + 1}"
                ),
                hint_doc_kind=hint_doc_kind,
                db=db,
                batch_id=None,   # per-tile batches don't share the outer id
                progress_callback=None,
            )
            # Stamp the tile's absolute page range onto every doc
            # so downstream merge logic can reason about cross-tile
            # boundaries. The extractor internally uses 1-indexed
            # page numbers relative to the tile — rebase to the
            # source PDF here.
            for doc in batch.documents:
                if doc.source_page_range:
                    a, b = doc.source_page_range
                    doc.source_page_range = [
                        p_start + a - 1, p_start + b - 1,
                    ]
                else:
                    doc.source_page_range = [p_start, p_end]
            return batch
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _MAX_TILE_RETRIES:
                logger.warning(
                    "[tiled_extract] tile %s failed (attempt %s), "
                    "retrying: %s",
                    tile_idx + 1, attempt + 1, exc,
                )
                continue
            break
    # All attempts exhausted.
    warnings.append({
        "code": "tile_extraction_failed",
        "tile_index": tile_idx + 1,
        "message": (
            f"tile {tile_idx + 1} (pages {p_start}-{p_end}) "
            f"extraction failed after {_MAX_TILE_RETRIES + 1} "
            f"attempts: {last_exc}"
        ),
    })
    return None


def _slice_pdf_bytes(
    pdf_bytes: bytes, page_start_1: int, page_end_1: int,
) -> bytes:
    """Return a fresh PDF byte-string containing pages
    ``page_start_1..page_end_1`` (inclusive, 1-indexed) sliced
    from ``pdf_bytes``.

    Uses PyMuPDF's ``insert_pdf`` which is efficient (streams
    page dicts, doesn't re-render). The intermediate handles are
    context-managed so a 100-page PDF doesn't hold all tile
    slices in memory simultaneously (per PDF-D ruling #7)."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as src:
        with fitz.open() as sub:
            sub.insert_pdf(
                src, from_page=page_start_1 - 1, to_page=page_end_1 - 1,
            )
            return sub.tobytes()


# ═════════════════════════════════════════════════════════════════════
# Cross-tile merge.
# ═════════════════════════════════════════════════════════════════════
def _merge_cross_tile_documents(
    pre_merge: List[Tuple[int, ExtractedDocument]],
) -> Tuple[List[ExtractedDocument], int, List[str]]:
    """Group documents by natural key, then merge each group.

    Merge key: ``(doc_kind, doc_number, doc_date_iso, normalised_customer_name)``.
    Docs with a null ``doc_number`` OR a null ``doc_date`` are treated
    as unique (no merge candidate) so we don't accidentally collapse
    two unrelated invoice-like items into one.

    Returns: ``(merged_docs, cross_tile_merge_count, warnings)``.
    """
    groups: Dict[Tuple[Any, ...], List[Tuple[int, ExtractedDocument]]] = {}
    orphans: List[ExtractedDocument] = []
    for tile_idx, doc in pre_merge:
        key = _merge_key(doc)
        if key is None:
            orphans.append(doc)
            continue
        groups.setdefault(key, []).append((tile_idx, doc))

    merged: List[ExtractedDocument] = []
    warnings: List[str] = []
    cross_tile_merges = 0

    for key, members in groups.items():
        if len(members) == 1:
            merged.append(members[0][1])
            continue
        # Cross-tile duplicate/continuation — merge.
        cross_tile_merges += 1
        merged_doc, merge_warnings = _merge_group(members)
        merged.append(merged_doc)
        warnings.extend(merge_warnings)

    merged.extend(orphans)
    # Deterministic ordering — sort by source_page_range start so
    # the caller sees documents in the natural PDF order rather
    # than in whatever order the concurrent tile extractions
    # completed.
    merged.sort(key=lambda d: (
        (d.source_page_range or [999999])[0],
    ))
    return merged, cross_tile_merges, warnings


def _merge_key(doc: ExtractedDocument) -> Optional[Tuple[Any, ...]]:
    if not doc.doc_number or not doc.doc_date:
        return None
    return (
        doc.doc_kind,
        (doc.doc_number or "").strip().upper(),
        doc.doc_date.isoformat(),
        (doc.customer_name or "").strip().lower(),
    )


def _merge_group(
    members: List[Tuple[int, ExtractedDocument]],
) -> Tuple[ExtractedDocument, List[str]]:
    """Merge two-or-more documents that share the same
    ``_merge_key``. Fields prefer the doc with the most non-None
    values; line-items are concatenated + deduplicated + capped.
    """
    warnings: List[str] = []
    # Sort by tile index so the earliest tile wins on any tie.
    members = sorted(members, key=lambda t: t[0])
    # Field-picking: iterate all members, take the first non-None
    # value seen per field. This preserves the "keep the doc with
    # more fields populated" semantics without a per-field
    # completeness score.
    base = members[0][1].model_copy(deep=True)
    for _tile_idx, doc in members[1:]:
        for fname in type(base).model_fields:
            if fname in ("line_items", "source_page_range"):
                continue
            current = getattr(base, fname, None)
            other = getattr(doc, fname, None)
            if (current is None or current == "") and other not in (None, ""):
                setattr(base, fname, other)
    # source_page_range: expand to the union.
    ranges = [
        d.source_page_range for _, d in members if d.source_page_range
    ]
    if ranges:
        base.source_page_range = [
            min(r[0] for r in ranges),
            max(r[1] for r in ranges),
        ]

    # Line-items: concat then dedupe on (item_name, description,
    # qty, cost_rate). Preserve first-seen order.
    seen: set = set()
    merged_items = []
    for _tile_idx, doc in members:
        for li in (doc.line_items or []):
            sig = (
                (li.item_name or "").strip().lower(),
                (li.description or "").strip().lower(),
                li.qty,
                li.cost_rate,
            )
            if sig in seen:
                continue
            seen.add(sig)
            merged_items.append(li)
    if len(merged_items) > MAX_LINE_ITEMS_PER_MERGED_DOC:
        warnings.append(
            f"cross-tile merge for doc {base.doc_number!r} produced "
            f"{len(merged_items)} line items — truncated to "
            f"{MAX_LINE_ITEMS_PER_MERGED_DOC} (hallucination guard)"
        )
        merged_items = merged_items[:MAX_LINE_ITEMS_PER_MERGED_DOC]
    base.line_items = merged_items
    return base, warnings


__all__ = [
    "extract_with_tiling",
    "TILE_PAGE_THRESHOLD",
    "TILE_PAGE_SIZE",
    "TILE_PAGE_OVERLAP",
    "TILE_CONCURRENCY",
    "MAX_LINE_ITEMS_PER_MERGED_DOC",
]
