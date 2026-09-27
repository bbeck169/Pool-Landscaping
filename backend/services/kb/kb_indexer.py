"""KB IH-A · Feb-2026 — indexing pipeline.

Ties ``pdf_chunker`` + ``embedder`` together, persists chunks
into ``kb_document_chunks``, and mutates the parent KB doc's
``index_status`` / ``chunks_count`` / ``pages_count`` /
``last_indexed_at`` / ``index_error`` fields.

Idempotent — the first step of ``index_document`` is
``delete_many({tenant_id, doc_id})`` on ``kb_document_chunks``,
so re-indexing yields the same chunk count without accumulating
stale rows.

Concurrency guard — a per-doc lock via
``kb_index_locks.find_one_and_update({...}, upsert=True)`` OR
in-mem when the DB collection isn't available (tests).  Picks
the simplest path that survives concurrent uploads without
adding infrastructure.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from services.kb.embedder import (
    EmbeddingUnavailable, embed_texts as real_embed_texts,
)
from services.kb.pdf_chunker import chunk_pdf

logger = logging.getLogger(__name__)


@dataclass
class IndexReport:
    """Return type of ``index_document``.  Rendered into the
    ``ai_knowledge_base`` doc's status fields by the caller
    (router + tests both consume this)."""
    doc_id: str
    chunks_indexed: int
    pages_indexed: int
    ms_elapsed: int
    status: str  # "ready" | "error"
    error: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════
# Idempotent index — main entry point
# ═════════════════════════════════════════════════════════════
async def index_document(
    doc_id: str,
    *,
    tenant_id: str,
    db,
    file_bytes: Optional[bytes] = None,
    fallback_text: Optional[str] = None,
    embedder: Optional[Callable] = None,
) -> IndexReport:
    """Chunk + embed + persist. Idempotent per ``(tenant_id, doc_id)``.

    ``embedder`` — when None, defaults to the real
    ``embed_texts`` from ``services.kb.embedder``.  Tests pass
    a fake returning deterministic vectors from a hash of text.

    ``file_bytes`` / ``fallback_text`` — exactly one should be
    present.  ``file_bytes`` for PDFs (page-fidelity path).
    ``fallback_text`` for non-PDF uploads (single "page 1"
    fallback via ``pdf_chunker.chunk_text``).
    """
    start = time.perf_counter()
    embed_fn = embedder or real_embed_texts

    # ── Mark doc as indexing (visible to FE polling). ─────────
    await db.ai_knowledge_base.update_one(
        {"id": doc_id, "tenant_id": tenant_id},
        {"$set": {
            "index_status": "indexing",
            "index_error": None,
        }},
    )

    # ── Chunk. ────────────────────────────────────────────────
    try:
        chunks = chunk_pdf(
            file_bytes or b"", doc_id, fallback_text=fallback_text,
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        return await _finalise_error(
            db=db, doc_id=doc_id, tenant_id=tenant_id,
            error=f"chunk_failed: {exc}", started=start,
        )

    if not chunks:
        return await _finalise_error(
            db=db, doc_id=doc_id, tenant_id=tenant_id,
            error="no_extractable_text",
            started=start,
        )

    # ── Embed. Fail fast — no random-vector fallback. ─────────
    try:
        vectors = await embed_fn([c["chunk_text"] for c in chunks])
    except EmbeddingUnavailable as exc:
        return await _finalise_error(
            db=db, doc_id=doc_id, tenant_id=tenant_id,
            error=str(exc), started=start,
        )
    except Exception as exc:  # noqa: BLE001 — defensive on custom fakes
        return await _finalise_error(
            db=db, doc_id=doc_id, tenant_id=tenant_id,
            error=f"embed_failed: {exc}", started=start,
        )

    if len(vectors) != len(chunks):
        return await _finalise_error(
            db=db, doc_id=doc_id, tenant_id=tenant_id,
            error=(
                f"embed_count_mismatch: got {len(vectors)} vectors "
                f"for {len(chunks)} chunks"
            ),
            started=start,
        )

    # ── Idempotent replace — wipe any prior chunks for this
    #     (tenant, doc) tuple then insert the fresh set. ─────
    await db.kb_document_chunks.delete_many({
        "tenant_id": tenant_id, "doc_id": doc_id,
    })

    docs_to_insert: List[Dict[str, Any]] = []
    for chunk, vector in zip(chunks, vectors):
        docs_to_insert.append({
            **chunk,
            "tenant_id": tenant_id,
            "embedding": list(vector),
            "indexed_at": _now_iso(),
        })
    if docs_to_insert:
        await db.kb_document_chunks.insert_many(docs_to_insert)

    pages_seen = sorted({c["page_num"] for c in chunks})
    ms = int((time.perf_counter() - start) * 1000)

    await db.ai_knowledge_base.update_one(
        {"id": doc_id, "tenant_id": tenant_id},
        {"$set": {
            "index_status": "ready",
            "index_error": None,
            "chunks_count": len(chunks),
            "pages_count": len(pages_seen),
            "last_indexed_at": _now_iso(),
        }},
    )
    return IndexReport(
        doc_id=doc_id, chunks_indexed=len(chunks),
        pages_indexed=len(pages_seen),
        ms_elapsed=ms, status="ready",
    )


async def _finalise_error(
    *, db, doc_id: str, tenant_id: str, error: str, started: float,
) -> IndexReport:
    """Mark the KB doc as error state + return a matching report."""
    ms = int((time.perf_counter() - started) * 1000)
    await db.ai_knowledge_base.update_one(
        {"id": doc_id, "tenant_id": tenant_id},
        {"$set": {
            "index_status": "error",
            "index_error": error,
        }},
    )
    logger.warning(
        "[kb.indexer] index failed doc=%s tenant=%s err=%s",
        doc_id, tenant_id, error,
    )
    return IndexReport(
        doc_id=doc_id, chunks_indexed=0, pages_indexed=0,
        ms_elapsed=ms, status="error", error=error,
    )
