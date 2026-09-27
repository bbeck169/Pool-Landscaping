"""KB IH-A · Feb-2026 — page-scoped PDF chunker.

Takes raw PDF bytes, extracts per-page text, and cuts each page
into ~800-char windows with 120-char overlap.  Page boundaries
are NEVER crossed — page fidelity is the whole point (so MARCO
can cite "see page 12").

The extraction primitive is ``pypdf.PdfReader`` — same tool the
existing KB upload path uses at ``ai_brain.py:_extract_pdf_text``.
The brief pointed at ``services/imports/`` but that module's
``pdf_invoice_extractor`` is a vision-model invoice extractor,
not a page-text utility.  Using ``pypdf`` directly here is the
right primitive.

Output shape per chunk::

    {
      "doc_id": str,
      "page_num": int,        # 1-indexed
      "chunk_index": int,     # 0-indexed within the document
      "chunk_text": str,
      "char_start": int,      # char offset within the page text
      "char_end": int,
      "figure_refs": [
        {"page_num": int, "figure_label": str, "bbox": None}
      ],
    }

``figure_refs`` are populated by regex on the chunk text.
``bbox`` is left None for MVP — PDF-FIX-B levels of
coordinate extraction are out of scope for IH-A.
"""
from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# Tunables
# ═════════════════════════════════════════════════════════════
CHUNK_TARGET_CHARS = 800
CHUNK_OVERLAP_CHARS = 120

# Figure / diagram references — captures "Figure 12",
# "Fig. 3", "Diagram 5", including trailing period-or-colon.
_FIGURE_RE = re.compile(
    r"\b(?P<label>(?:Figure|Fig\.?|Diagram)\s+\d+[a-z]?)\b",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════
# Text-only fallback path — used when the caller passes plain
# text (docx, txt, md) instead of PDF bytes.  Single logical
# "page 1" so downstream consumers still see a page_num.
# ═════════════════════════════════════════════════════════════
def chunk_text(
    text: str, doc_id: str, page_num: int = 1, base_index: int = 0,
) -> List[Dict[str, Any]]:
    """Slice ``text`` into 800-char windows with 120-char
    overlap.  All chunks tagged with the same ``page_num``.
    Used by both the PDF per-page loop and the non-PDF
    plain-text fallback in ``chunk_pdf`` when the extractor
    yields no ``pypdf`` pages.
    """
    text = (text or "").strip()
    if not text:
        return []

    chunks: List[Dict[str, Any]] = []
    step = max(1, CHUNK_TARGET_CHARS - CHUNK_OVERLAP_CHARS)
    cursor = 0
    idx = base_index
    n = len(text)
    while cursor < n:
        end = min(cursor + CHUNK_TARGET_CHARS, n)
        chunk_text_val = text[cursor:end]
        figure_refs = _extract_figure_refs(chunk_text_val, page_num)
        chunks.append({
            "doc_id": doc_id,
            "page_num": page_num,
            "chunk_index": idx,
            "chunk_text": chunk_text_val,
            "char_start": cursor,
            "char_end": end,
            "figure_refs": figure_refs,
        })
        idx += 1
        if end >= n:
            break
        cursor += step
    return chunks


def _extract_figure_refs(
    text: str, page_num: int,
) -> List[Dict[str, Any]]:
    """Regex-scan ``text`` for figure / diagram references.
    Dedupe by normalised label so "Fig. 3" and "Figure 3" on
    the same chunk don't produce two entries.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for m in _FIGURE_RE.finditer(text or ""):
        label = m.group("label").strip()
        # Normalise "Fig." vs "Figure" for dedupe key so we
        # don't emit both variants; keep the FIRST occurrence's
        # exact label string.
        norm = re.sub(r"^Fig\.?", "Figure", label, flags=re.IGNORECASE)
        norm = re.sub(r"\s+", " ", norm.strip().lower())
        if norm in seen:
            continue
        seen[norm] = {
            "page_num": page_num,
            "figure_label": label,
            "bbox": None,
        }
    return list(seen.values())


# ═════════════════════════════════════════════════════════════
# Public API
# ═════════════════════════════════════════════════════════════
def chunk_pdf(
    file_bytes: bytes, doc_id: str,
    *, fallback_text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Chunk raw PDF bytes into page-scoped windows.

    ``fallback_text`` — when the caller has already extracted
    plain text (docx/txt/md path) they can pass it here and
    the function returns a single-page chunk stream instead
    of trying to parse ``file_bytes`` as a PDF.  Keeps the
    caller-side branch trivial.

    Returns an empty list on unrecoverable parse error — the
    caller sets ``index_status='error'`` with the corresponding
    message.  We never raise; the caller decides how to react.
    """
    # Non-PDF fallback path — plain text upstream.
    if fallback_text is not None:
        return chunk_text(fallback_text, doc_id, page_num=1)

    if not file_bytes:
        return []

    try:
        from pypdf import PdfReader  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        logger.warning("[kb.chunker] pypdf import failed: %s", exc)
        return []

    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[kb.chunker] pdf open failed: %s", exc)
        return []

    all_chunks: List[Dict[str, Any]] = []
    next_index = 0
    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            page_text = ""
        if not page_text:
            continue
        page_chunks = chunk_text(
            page_text, doc_id, page_num=page_idx, base_index=next_index,
        )
        all_chunks.extend(page_chunks)
        next_index += len(page_chunks)

    return all_chunks
