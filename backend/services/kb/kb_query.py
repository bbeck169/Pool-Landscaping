"""KB IH-A · Feb-2026 — cosine-similarity retrieval.

Prefetches chunks for a tenant (with optional ``doc_ids``
filter), embeds the query, computes cosine similarity in
Python, sorts desc, returns top-K.  Zero infrastructure — no
Atlas Search / vector index required.

When ``len(chunks) × EMBEDDING_DIM`` gets big enough to make
this slow (>500ms), the query logs a warning telling us it's
time to graduate to a proper vector index.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Dict, List, Optional

from services.kb.embedder import (
    EmbeddingUnavailable, embed_texts as real_embed_texts,
)

logger = logging.getLogger(__name__)


LATENCY_WARN_MS = 500


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two float vectors of equal
    length.  Zero-safe — returns 0.0 when either vector has
    zero norm (embeddings that come out all-zero would still
    be well-defined, just uninformative)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


async def search_chunks(
    *,
    query: str,
    tenant_id: str,
    db,
    top_k: int = 6,
    doc_ids: Optional[List[str]] = None,
    min_score: float = 0.25,
    embedder: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Return top-K matching chunks + a rendering-friendly
    ``doc_title`` on each hit + latency stats.

    Tenant isolation is enforced hard by the Mongo filter —
    cross-tenant bleed is impossible.
    """
    start = time.perf_counter()
    embed_fn = embedder or real_embed_texts

    if not (query or "").strip():
        return {"hits": [], "query_ms": 0}

    # ── Embed the query. ───────────────────────────────────
    try:
        query_vecs = await embed_fn([query])
    except EmbeddingUnavailable as exc:
        logger.warning(
            "[kb.query] embed failed tenant=%s err=%s",
            tenant_id, exc,
        )
        return {"hits": [], "query_ms": 0, "error": str(exc)}
    if not query_vecs:
        return {"hits": [], "query_ms": 0}
    q_vec = query_vecs[0]

    # ── Prefetch tenant's chunks. ──────────────────────────
    mongo_filter: Dict[str, Any] = {"tenant_id": tenant_id}
    if doc_ids:
        mongo_filter["doc_id"] = {"$in": list(doc_ids)}
    cursor = db.kb_document_chunks.find(mongo_filter, {"_id": 0})
    chunks: List[Dict[str, Any]] = await cursor.to_list(length=None)

    if not chunks:
        ms = int((time.perf_counter() - start) * 1000)
        return {"hits": [], "query_ms": ms}

    # ── Score every chunk. ────────────────────────────────
    scored: List[Dict[str, Any]] = []
    for chunk in chunks:
        emb = chunk.get("embedding") or []
        score = _cosine(q_vec, emb)
        if score < min_score:
            continue
        scored.append({
            "doc_id": chunk.get("doc_id"),
            "page_num": chunk.get("page_num"),
            "chunk_text": chunk.get("chunk_text"),
            "figure_refs": chunk.get("figure_refs") or [],
            "score": round(score, 4),
        })
    scored.sort(key=lambda h: h["score"], reverse=True)
    top = scored[:max(1, int(top_k))]

    # ── Enrich with doc_title (single batched query). ─────
    doc_ids_in_hits = sorted({h["doc_id"] for h in top if h.get("doc_id")})
    title_by_id: Dict[str, str] = {}
    if doc_ids_in_hits:
        rows = await db.ai_knowledge_base.find(
            {"tenant_id": tenant_id, "id": {"$in": doc_ids_in_hits}},
            {"_id": 0, "id": 1, "title": 1},
        ).to_list(len(doc_ids_in_hits))
        title_by_id = {r["id"]: r.get("title") or "" for r in rows}
    for h in top:
        h["doc_title"] = title_by_id.get(h["doc_id"], "")

    ms = int((time.perf_counter() - start) * 1000)
    if ms > LATENCY_WARN_MS:
        logger.warning(
            "[kb.query] slow tenant=%s chunks=%d hits=%d ms=%d — "
            "consider graduating to a vector index",
            tenant_id, len(chunks), len(top), ms,
        )
    return {"hits": top, "query_ms": ms}
