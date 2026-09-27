"""PDF Importer Sub-phase D · Feb-2026 — tiled segmentation tests.

Locks the nine acceptance cases from the PDF-D dispatch:

    (a) 36-page PDF → single-shot path, no tiling.
    (b) 37-page PDF → tile path, 2 tiles used (tail absorbed).
    (c) 78-page PDF → 5 tiles with correct overlap boundaries.
    (d) Cross-tile duplicate document → deduped in final output.
    (e) Cross-tile continuation: header in tile 1, extra line
        items in tile 2 → merged single doc with concatenated
        line items.
    (f) Single-tile LLM failure → other tiles complete, warning
        surfaced in tile_summary.
    (g) tile_summary block present for >36-page batch.
    (h) Line-item cap enforcement: >500 merged line items →
        truncated + warning emitted.
    (i) Tenant isolation: extract_with_tiling preserves the
        tenant_id through every tile's extract() call and every
        resulting document carries the caller's tenant_id.

Test seam: we patch :func:`pdf_tiled_extractor._single_shot_extract`
directly (one call per tile), which lets us return pre-baked
:class:`ExtractedBatch` objects deterministically per tile index
regardless of concurrent execution order. Patching
``_call_vision_model`` would work too but its counter interleaves
segmentation + extraction + concurrency in ways that make
per-tile assertions fragile.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import fitz  # PyMuPDF
import pytest

from services.imports.extraction_schema import (
    ExtractedBatch, ExtractedDocument, ExtractedLineItem,
)
from services.imports.pdf_tiled_extractor import (
    extract_with_tiling,
    _plan_tile_ranges,
    TILE_PAGE_THRESHOLD,
    TILE_PAGE_SIZE,
    TILE_PAGE_OVERLAP,
    MAX_LINE_ITEMS_PER_MERGED_DOC,
)


# ═════════════════════════════════════════════════════════════════════
# Fixture: build a synthetic multi-page PDF in memory.
# ═════════════════════════════════════════════════════════════════════
def _make_pdf(page_count: int, *, marker: str = "PDFD") -> bytes:
    """Return a byte-string PDF with the requested page count."""
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            (72, 72),
            f"{marker} page {i + 1} of {page_count}",
            fontsize=16,
        )
    return doc.tobytes()


# ═════════════════════════════════════════════════════════════════════
# Document builder — returns a real ExtractedDocument instance so
# the tile extractor's field-access path (model_fields, model_copy)
# behaves identically to the production path.
# ═════════════════════════════════════════════════════════════════════
def _mk_doc(
    *, doc_number: Optional[str] = "INV-1000",
    doc_date: Optional[str] = "2026-02-15",
    customer_name: Optional[str] = "Acme Corp",
    line_items: Optional[List[Dict[str, Any]]] = None,
    total_due: float = 100.0,
    source_page_range: Optional[List[int]] = None,
) -> ExtractedDocument:
    lis = [ExtractedLineItem(**li) for li in (line_items or [
        {"item_name": "Filter clean", "description": "Filter clean",
         "qty": 1, "cost_rate": total_due, "line_total": total_due},
    ])]
    parsed = {
        "doc_kind": "invoice",
        "doc_number": doc_number,
        "doc_date": doc_date,
        "customer_name": customer_name,
        "line_items": [li.model_dump() for li in lis],
        "total_due": total_due,
        "source_page_range": source_page_range or [1, 1],
    }
    return ExtractedDocument.model_validate(parsed)


def _mk_batch(
    documents: List[ExtractedDocument], *,
    page_count: int = 20, tenant_id: str = "test_tenant",
    filename: str = "tile.pdf",
) -> ExtractedBatch:
    now = datetime.now(timezone.utc)
    return ExtractedBatch(
        batch_id="stub",
        source_filename=filename,
        source_sha256="stub",
        source_byte_count=1,
        page_count=page_count,
        tenant_id=tenant_id,
        documents=documents,
        warnings=[],
        structured_warnings=[],
        model_used="stub-model",
        extraction_started_at=now,
        extraction_finished_at=now,
    )


# ═════════════════════════════════════════════════════════════════════
# Stub for _single_shot_extract — one call per tile.
# ═════════════════════════════════════════════════════════════════════
class _TileStub:
    """Callable replacing :func:`_single_shot_extract`. One call
    per tile. Returns pre-baked ``ExtractedBatch`` per tile index.
    Concurrency-safe: uses a lock + shared counter that tracks
    the tile ORDER the coroutines actually completed in, but the
    docs returned map to the tile ORDER the caller planned (from
    the ``source_filename`` suffix ``#tile-N``).

    Args:
        per_tile_batches: list where [i] is the ExtractedBatch to
            return for tile i (0-indexed), OR None to raise a
            RuntimeError from that tile.
        fail_first_attempts: set of tile indices that should fail
            on their FIRST attempt but succeed on retry (per PDF-D
            ruling #4 — one retry per tile).
    """
    def __init__(
        self,
        per_tile_batches: List[Optional[ExtractedBatch]],
        fail_first_attempts: Optional[set] = None,
    ):
        self.per_tile_batches = per_tile_batches
        self.fail_first_attempts = fail_first_attempts or set()
        self.attempts_per_tile: Dict[int, int] = {}
        self.tenant_ids_seen: List[str] = []

    def _extract_tile_idx(self, source_filename: str) -> int:
        # source_filename shape: "<orig>#tile-<N>" where N is 1-indexed.
        if "#tile-" in source_filename:
            return int(source_filename.rsplit("#tile-", 1)[1]) - 1
        return 0

    async def __call__(self, *, pdf_bytes: bytes, tenant_id: str,
                          source_filename: str, hint_doc_kind=None,
                          db=None, batch_id=None,
                          progress_callback=None) -> ExtractedBatch:
        self.tenant_ids_seen.append(tenant_id)
        tidx = self._extract_tile_idx(source_filename)
        attempts = self.attempts_per_tile.get(tidx, 0)
        self.attempts_per_tile[tidx] = attempts + 1
        # First-attempt retry gate.
        if attempts == 0 and tidx in self.fail_first_attempts:
            raise RuntimeError(
                f"stub: tile {tidx} first-attempt injected failure"
            )
        payload = self.per_tile_batches[tidx] if tidx < len(
            self.per_tile_batches,
        ) else None
        if payload is None:
            # Permanent failure — raises on every call.
            raise RuntimeError(f"stub: tile {tidx} permanent failure")
        return payload


# ═════════════════════════════════════════════════════════════════════
# (a) 36-page PDF → single-shot path.
# ═════════════════════════════════════════════════════════════════════
def test_a_36_pages_uses_single_shot_path():
    """A PDF at the threshold delegates straight to
    ``pdf_invoice_extractor.extract`` — no tile plan, no
    tile_summary, no cross-tile merge."""
    pdf = _make_pdf(TILE_PAGE_THRESHOLD)   # exactly 36
    fake_batch = _mk_batch(
        [_mk_doc()], page_count=TILE_PAGE_THRESHOLD,
        tenant_id="t-a",
    )
    stub = _TileStub([fake_batch])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-a",
                source_filename="tiled_a.pdf",
            )

    batch = asyncio.run(_run())
    assert batch.page_count == TILE_PAGE_THRESHOLD
    assert batch.tile_summary is None, (
        "≤36-page PDFs must take the single-shot fast path"
    )
    # Fast-path calls the extract WITHOUT a #tile- suffix.
    assert stub.attempts_per_tile == {0: 1}


# ═════════════════════════════════════════════════════════════════════
# (b) 37-page PDF → tile path, 2 tiles.
# ═════════════════════════════════════════════════════════════════════
def test_b_37_pages_triggers_2_tile_path():
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)   # 37
    stub = _TileStub([
        _mk_batch([_mk_doc(doc_number="INV-A")]),
        _mk_batch([_mk_doc(doc_number="INV-B")]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-b",
                source_filename="tiled_b.pdf",
            )

    batch = asyncio.run(_run())
    assert batch.tile_summary is not None
    assert batch.tile_summary["tiles_used"] == 2
    assert batch.tile_summary["total_pages"] == 37
    assert len(batch.documents) == 2
    doc_numbers = {d.doc_number for d in batch.documents}
    assert doc_numbers == {"INV-A", "INV-B"}


# ═════════════════════════════════════════════════════════════════════
# (c) Tile planning math — 78 pages.
# ═════════════════════════════════════════════════════════════════════
def test_c_78_pages_plan_correct_overlap():
    """Pure-function test on ``_plan_tile_ranges``. TILE_PAGE_SIZE=20,
    TILE_PAGE_OVERLAP=4 → step=16."""
    plan = _plan_tile_ranges(
        page_count=78,
        tile_size=TILE_PAGE_SIZE,
        tile_overlap=TILE_PAGE_OVERLAP,
    )
    assert plan == [
        (1, 20), (17, 36), (33, 52), (49, 68), (65, 78),
    ]
    covered = set()
    for start, end in plan:
        covered.update(range(start, end + 1))
    assert covered == set(range(1, 79))


# ═════════════════════════════════════════════════════════════════════
# (d) Cross-tile duplicate → deduped.
# ═════════════════════════════════════════════════════════════════════
def test_d_cross_tile_duplicate_is_deduped():
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)
    stub = _TileStub([
        _mk_batch([_mk_doc(doc_number="INV-DUP",
                              customer_name="Same Corp")]),
        _mk_batch([_mk_doc(doc_number="INV-DUP",
                              customer_name="Same Corp")]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-d",
                source_filename="tiled_d.pdf",
            )

    batch = asyncio.run(_run())
    assert batch.tile_summary["docs_pre_merge"] == 2
    assert batch.tile_summary["docs_post_merge"] == 1
    assert batch.tile_summary["cross_tile_merges"] == 1
    assert len(batch.documents) == 1
    assert batch.documents[0].doc_number == "INV-DUP"


# ═════════════════════════════════════════════════════════════════════
# (e) Cross-tile continuation → concatenated line items.
# ═════════════════════════════════════════════════════════════════════
def test_e_cross_tile_continuation_concatenates_line_items():
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)
    stub = _TileStub([
        _mk_batch([_mk_doc(
            doc_number="INV-CONT",
            line_items=[
                {"item_name": "Chlorine", "description": "Chlorine",
                 "qty": 1, "cost_rate": 50.0, "line_total": 50.0},
            ],
        )]),
        _mk_batch([_mk_doc(
            doc_number="INV-CONT",
            line_items=[
                {"item_name": "pH plus", "description": "pH plus",
                 "qty": 2, "cost_rate": 25.0, "line_total": 50.0},
                {"item_name": "Salt", "description": "Salt",
                 "qty": 1, "cost_rate": 40.0, "line_total": 40.0},
            ],
        )]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-e",
                source_filename="tiled_e.pdf",
            )

    batch = asyncio.run(_run())
    assert len(batch.documents) == 1
    merged = batch.documents[0]
    assert merged.doc_number == "INV-CONT"
    item_names = {li.item_name for li in merged.line_items}
    assert item_names == {"Chlorine", "pH plus", "Salt"}


# ═════════════════════════════════════════════════════════════════════
# (f) Single-tile permanent failure → others complete + warning.
# ═════════════════════════════════════════════════════════════════════
def test_f_single_tile_failure_isolates_gracefully():
    """Tile 0's extract raises on BOTH attempts (initial + retry).
    Tile 1 succeeds. Warning must surface in tile_summary and
    tile 1's document lands in the final batch."""
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)   # 2 tiles
    stub = _TileStub([
        None,   # tile 0 — permanent failure
        _mk_batch([_mk_doc(doc_number="INV-OK")]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-f",
                source_filename="tiled_f.pdf",
            )

    batch = asyncio.run(_run())
    assert len(batch.documents) == 1
    assert batch.documents[0].doc_number == "INV-OK"
    warning_codes = {
        w.get("code") for w in batch.tile_summary["warnings"]
    }
    assert "tile_extraction_failed" in warning_codes
    # And tile 0 was actually tried the full 2 attempts (initial + 1 retry).
    assert stub.attempts_per_tile.get(0, 0) == 2


def test_f2_single_tile_first_attempt_retry_succeeds():
    """Complementary: tile 0 fails on first attempt but succeeds on
    retry (per PDF-D ruling #4 — one retry per tile). Both tiles
    should ultimately land docs; no warning."""
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)
    stub = _TileStub(
        [
            _mk_batch([_mk_doc(doc_number="INV-RETRY")]),
            _mk_batch([_mk_doc(doc_number="INV-CLEAN")]),
        ],
        fail_first_attempts={0},
    )

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-f2",
                source_filename="tiled_f2.pdf",
            )

    batch = asyncio.run(_run())
    assert len(batch.documents) == 2
    assert stub.attempts_per_tile.get(0, 0) == 2   # 1 fail + 1 retry
    assert stub.attempts_per_tile.get(1, 0) == 1
    # No warnings because the retry succeeded.
    assert batch.tile_summary["warnings"] == []


# ═════════════════════════════════════════════════════════════════════
# (g) tile_summary present + shape correct.
# ═════════════════════════════════════════════════════════════════════
def test_g_tile_summary_present_and_shape_correct():
    pdf = _make_pdf(60)   # → 4 tiles
    stub = _TileStub([
        _mk_batch([_mk_doc(doc_number=f"INV-{i}")]) for i in range(4)
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-g",
                source_filename="tiled_g.pdf",
            )

    batch = asyncio.run(_run())
    ts = batch.tile_summary
    assert ts is not None
    for key in (
        "total_pages", "tiles_used", "docs_pre_merge",
        "docs_post_merge", "cross_tile_merges", "warnings",
    ):
        assert key in ts, f"tile_summary missing key {key}"
    assert ts["total_pages"] == 60
    assert ts["tiles_used"] == 4
    assert ts["cross_tile_merges"] == 0


# ═════════════════════════════════════════════════════════════════════
# (h) Line-item cap enforcement.
# ═════════════════════════════════════════════════════════════════════
def test_h_line_item_cap_enforced_with_warning():
    """Cross-tile merge producing >500 unique line items MUST be
    truncated at the cap with a warning entry in ``ExtractedBatch.
    warnings``."""
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)
    items_a = [
        {"item_name": f"A-{i}", "description": f"desc A {i}",
         "qty": 1.0, "cost_rate": float(i + 1),
         "line_total": float(i + 1)}
        for i in range(300)
    ]
    items_b = [
        {"item_name": f"B-{i}", "description": f"desc B {i}",
         "qty": 1.0, "cost_rate": float(i + 1000),
         "line_total": float(i + 1000)}
        for i in range(300)
    ]
    stub = _TileStub([
        _mk_batch([_mk_doc(doc_number="INV-HUGE", line_items=items_a)]),
        _mk_batch([_mk_doc(doc_number="INV-HUGE", line_items=items_b)]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="t-h",
                source_filename="tiled_h.pdf",
            )

    batch = asyncio.run(_run())
    assert len(batch.documents) == 1
    merged = batch.documents[0]
    assert len(merged.line_items) == MAX_LINE_ITEMS_PER_MERGED_DOC
    joined = " ".join(batch.warnings)
    assert "truncated" in joined.lower()
    assert str(MAX_LINE_ITEMS_PER_MERGED_DOC) in joined


# ═════════════════════════════════════════════════════════════════════
# (i) Tenant isolation — every tile's extract gets caller's tenant.
# ═════════════════════════════════════════════════════════════════════
def test_i_tenant_id_propagates_through_every_tile():
    pdf = _make_pdf(TILE_PAGE_THRESHOLD + 1)
    stub = _TileStub([
        _mk_batch([_mk_doc(doc_number="INV-P")]),
        _mk_batch([_mk_doc(doc_number="INV-Q")]),
    ])

    async def _run():
        with patch(
            "services.imports.pdf_tiled_extractor._single_shot_extract",
            new=stub,
        ):
            return await extract_with_tiling(
                pdf_bytes=pdf, tenant_id="tenant_A_only",
                source_filename="tiled_i.pdf",
            )

    batch = asyncio.run(_run())
    # Every tile received the caller's tenant_id verbatim — no
    # substitution, no leak.
    assert set(stub.tenant_ids_seen) == {"tenant_A_only"}
    assert len(stub.tenant_ids_seen) == 2  # 2 tiles, no retries
    # And the returned batch envelope carries the caller's tenant.
    assert batch.tenant_id == "tenant_A_only"
