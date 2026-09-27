"""KB IH-A · Feb-2026 — page-fidelity chunker tests.

Locks the chunker's contract independent of the embedder / DB
layer:

  1. Page boundaries are never crossed.
  2. Within a page, overlap is exactly ``CHUNK_OVERLAP_CHARS``
     (~120 chars).
  3. Figure references land as structured ``figure_refs`` per
     chunk with page_num carried through.
  4. Non-PDF ``fallback_text`` path emits a single-page stream.
  5. Empty / malformed bytes → empty list (never raises).
  6. Idempotent: same input twice → identical output.
"""
from __future__ import annotations

import io

import pytest


def _make_pdf(pages: list[str]) -> bytes:
    """Build a minimal multi-page PDF via reportlab. Used by
    the test_task_h1 suite too — matches the project convention
    of synth-PDFs for unit tests.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for text in pages:
        # One line per newline in the source; keep it simple.
        y = 750
        for line in (text or "").splitlines() or [""]:
            c.drawString(72, y, line[:1000])
            y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


def test_page_boundaries_never_crossed():
    """Every chunk carries the correct 1-indexed page_num;
    ``char_start`` / ``char_end`` live within the page's text
    (they DON'T reflect global document position).
    """
    from services.kb.pdf_chunker import chunk_pdf
    pages = [
        "PAGE ONE " * 200,   # ~1800 chars → 3 chunks
        "PAGE TWO " * 60,    # ~540 chars → 1 chunk
        "PAGE THREE " * 200,  # ~2200 chars → 3-4 chunks
    ]
    pdf = _make_pdf(pages)
    chunks = chunk_pdf(pdf, doc_id="doc-A")
    assert chunks, "expected non-empty chunk list from multi-page PDF"

    # Every chunk_text belongs to exactly one page — verified
    # by checking the page marker is in the chunk.
    for c in chunks:
        pnum = c["page_num"]
        marker = ["ONE", "TWO", "THREE"][pnum - 1]
        assert marker in c["chunk_text"], (
            f"chunk on page {pnum} does not contain marker "
            f"{marker!r}: {c['chunk_text'][:80]!r}"
        )


def test_overlap_within_a_page_is_120_chars():
    """Consecutive chunks on the SAME page share their last /
    first ~120 chars.  Overlap is 120, target is 800, so step
    is 680.
    """
    from services.kb.pdf_chunker import (
        chunk_text, CHUNK_OVERLAP_CHARS, CHUNK_TARGET_CHARS,
    )
    # 2400 chars — expect at least 4 chunks with 800/120 config
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 100  # 2600 chars
    chunks = chunk_text(text, "doc-B", page_num=1)
    assert len(chunks) >= 3
    for i in range(len(chunks) - 1):
        # tail of chunk N == head of chunk N+1 for 120 chars.
        tail = chunks[i]["chunk_text"][-CHUNK_OVERLAP_CHARS:]
        head = chunks[i + 1]["chunk_text"][:CHUNK_OVERLAP_CHARS]
        assert tail == head, (
            f"overlap broken between chunk {i} and {i+1}: "
            f"tail={tail[:40]!r} head={head[:40]!r}"
        )


def test_chunk_target_char_size_bounded():
    """No chunk exceeds ``CHUNK_TARGET_CHARS``."""
    from services.kb.pdf_chunker import chunk_text, CHUNK_TARGET_CHARS
    chunks = chunk_text("x" * 5000, "doc-C")
    for c in chunks:
        assert len(c["chunk_text"]) <= CHUNK_TARGET_CHARS


def test_figure_refs_extracted_with_page_num():
    """Figure regex matches ``Figure 12``, ``Fig. 3``,
    ``Diagram 5``; dedupes across variants on the same chunk
    (Fig. 3 + Figure 3 counted once).
    """
    from services.kb.pdf_chunker import chunk_text
    text = (
        "See Figure 12 for the wiring layout. "
        "Also refer to Fig. 3 and Diagram 5. "
        "Figure 3 shows the same schematic. "
    )
    chunks = chunk_text(text, "doc-D", page_num=7)
    assert len(chunks) == 1
    refs = chunks[0]["figure_refs"]
    labels = {r["figure_label"] for r in refs}
    # Fig. 3 + Figure 3 dedupe → one entry (whichever appeared
    # first stays).
    assert "Figure 12" in labels
    assert "Diagram 5" in labels
    assert ("Fig. 3" in labels) or ("Figure 3" in labels)
    for r in refs:
        assert r["page_num"] == 7
        assert r["bbox"] is None  # MVP — bbox deferred.


def test_fallback_text_path_single_page():
    """Non-PDF callers (docx / txt / md) pass ``fallback_text``
    and get a single-page chunk stream — no PDF parsing.
    """
    from services.kb.pdf_chunker import chunk_pdf
    chunks = chunk_pdf(
        b"", "doc-E", fallback_text="Hello world " * 300,
    )
    assert chunks, "fallback_text path must yield chunks"
    assert all(c["page_num"] == 1 for c in chunks)


def test_empty_bytes_returns_empty_list_no_raise():
    """Malformed / empty bytes → empty list (indexer sets
    ``index_status='error'`` with 'no_extractable_text')."""
    from services.kb.pdf_chunker import chunk_pdf
    assert chunk_pdf(b"", "doc-F") == []
    assert chunk_pdf(b"\x00garbage\xff", "doc-G") == []


def test_idempotent_same_input_same_output():
    """Feeding the same bytes twice yields byte-identical
    chunk_text values (idempotency prerequisite for
    ``index_document``'s delete-then-insert refresh)."""
    from services.kb.pdf_chunker import chunk_pdf
    pdf = _make_pdf(["First page.\n" * 50, "Second page.\n" * 80])
    a = chunk_pdf(pdf, "doc-H")
    b = chunk_pdf(pdf, "doc-H")
    assert len(a) == len(b)
    for ca, cb in zip(a, b):
        assert ca["chunk_text"] == cb["chunk_text"]
        assert ca["page_num"] == cb["page_num"]
        assert ca["chunk_index"] == cb["chunk_index"]
