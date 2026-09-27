"""KB IH-A · Feb-2026 — indexer + query end-to-end tests.

Uses an injected fake embedder that maps text → a
deterministic 1536-dim vector from a hash of the text, so the
tests exercise the full write / read path without ever
hitting OpenAI.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


# ══════════════════════════════════════════════════════════════
# Fixtures — Mongo + tenant + KB doc scaffolding
# ══════════════════════════════════════════════════════════════
@pytest.fixture()
def adb():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def kb_tenant_a(dbc):
    tid = f"tenant-kb-a-{uuid.uuid4().hex[:12]}"
    dbc.tenants.insert_one({"id": tid, "slug": tid, "name": "KB Tenant A"})
    yield tid
    dbc.tenants.delete_one({"id": tid})
    dbc.ai_knowledge_base.delete_many({"tenant_id": tid})
    dbc.kb_document_chunks.delete_many({"tenant_id": tid})


@pytest.fixture()
def kb_tenant_b(dbc):
    tid = f"tenant-kb-b-{uuid.uuid4().hex[:12]}"
    dbc.tenants.insert_one({"id": tid, "slug": tid, "name": "KB Tenant B"})
    yield tid
    dbc.tenants.delete_one({"id": tid})
    dbc.ai_knowledge_base.delete_many({"tenant_id": tid})
    dbc.kb_document_chunks.delete_many({"tenant_id": tid})


def _seed_kb_doc(dbc, tenant_id: str, title: str = "Test Manual") -> str:
    """Insert a bare KB doc row (mimics the state right after
    an upload but BEFORE the background indexer fires)."""
    kb_id = f"kb-{uuid.uuid4().hex[:12]}"
    dbc.ai_knowledge_base.insert_one({
        "id": kb_id,
        "tenant_id": tenant_id,
        "kind": "custom",
        "title": title,
        "content_md": "seed",
        "tags": [],
        "is_active": True,
        "source_type": "pdf",
        "index_status": "pending",
        "chunks_count": 0,
        "pages_count": 0,
        "last_indexed_at": None,
        "index_error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return kb_id


# ══════════════════════════════════════════════════════════════
# Fake embedder — deterministic hash-of-text → 1536-dim vector.
# The vector is L2-normalised so cosine similarity is
# semantically meaningful (identical strings → 1.0).
# ══════════════════════════════════════════════════════════════
def _fake_embed_factory(dim: int = 1536):
    async def _fake_embed(texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for text in texts:
            h = hashlib.sha256((text or "").encode("utf-8")).digest()
            # Fan the 32 hash bytes across 1536 dims by tiling
            # + jittering. Result is deterministic for a given
            # ``text``; different strings yield distinct vecs.
            vec = []
            for i in range(dim):
                b = h[i % len(h)]
                vec.append(((b / 255.0) - 0.5) * ((i % 7) + 1) * 0.1)
            # L2-normalise.
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out
    return _fake_embed


def _make_pdf(pages: list[str]) -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for text in pages:
        y = 750
        for line in (text or "").splitlines() or [""]:
            c.drawString(72, y, line[:1000])
            y -= 14
        c.showPage()
    c.save()
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
# Indexer contract — idempotency, status transitions, errors
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_index_document_happy_path(adb, dbc, kb_tenant_a):
    """PDF bytes + fake embedder → chunks persisted +
    index_status='ready' + counts populated."""
    from services.kb.kb_indexer import index_document
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    pdf = _make_pdf(["Page one text " * 40, "Page two text " * 40])

    report = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    assert report.status == "ready"
    assert report.chunks_indexed > 0
    assert report.pages_indexed == 2

    row = dbc.ai_knowledge_base.find_one({"id": kb_id})
    assert row["index_status"] == "ready"
    assert row["chunks_count"] == report.chunks_indexed
    assert row["pages_count"] == 2
    assert row["last_indexed_at"] is not None
    assert row["index_error"] is None

    persisted = list(dbc.kb_document_chunks.find({
        "tenant_id": kb_tenant_a, "doc_id": kb_id,
    }))
    assert len(persisted) == report.chunks_indexed
    for chunk in persisted:
        assert len(chunk["embedding"]) == 1536
        assert chunk["page_num"] in (1, 2)


@pytest.mark.anyio
async def test_index_document_idempotent_delete_then_insert(
    adb, dbc, kb_tenant_a,
):
    """Re-indexing the same doc yields the SAME chunk count
    (delete_many wipes prior chunks before insert_many)."""
    from services.kb.kb_indexer import index_document
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    pdf = _make_pdf(["Idempotency check " * 50])

    r1 = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    r2 = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    assert r1.chunks_indexed == r2.chunks_indexed
    persisted = dbc.kb_document_chunks.count_documents({
        "tenant_id": kb_tenant_a, "doc_id": kb_id,
    })
    assert persisted == r2.chunks_indexed


@pytest.mark.anyio
async def test_index_document_tenant_isolation_on_delete(
    adb, dbc, kb_tenant_a, kb_tenant_b,
):
    """Wiping tenant-A chunks during a re-index does NOT
    delete tenant-B chunks (the delete_many is
    ``tenant_id`` + ``doc_id`` scoped)."""
    from services.kb.kb_indexer import index_document
    kb_a = _seed_kb_doc(dbc, kb_tenant_a)
    kb_b = _seed_kb_doc(dbc, kb_tenant_b)
    pdf = _make_pdf(["Tenant iso " * 40])

    # Same doc_id COULDN'T happen in practice (each doc has a
    # unique id) but we run separate kb ids for clarity.
    await index_document(
        kb_a, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    await index_document(
        kb_b, tenant_id=kb_tenant_b, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    # Re-index A — B's chunks stay put.
    b_before = dbc.kb_document_chunks.count_documents({
        "tenant_id": kb_tenant_b,
    })
    await index_document(
        kb_a, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    b_after = dbc.kb_document_chunks.count_documents({
        "tenant_id": kb_tenant_b,
    })
    assert b_after == b_before


@pytest.mark.anyio
async def test_index_document_embedding_unavailable_marks_error(
    adb, dbc, kb_tenant_a,
):
    """Embedder that raises ``EmbeddingUnavailable`` → doc
    lands in ``index_status='error'`` with the message
    (NO random-vector fallback per user brief)."""
    from services.kb.embedder import EmbeddingUnavailable
    from services.kb.kb_indexer import index_document
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    pdf = _make_pdf(["Some content " * 30])

    async def _boom(_texts):
        raise EmbeddingUnavailable("simulated_no_key")

    report = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_boom,
    )
    assert report.status == "error"
    assert "simulated_no_key" in (report.error or "")

    row = dbc.ai_knowledge_base.find_one({"id": kb_id})
    assert row["index_status"] == "error"
    assert "simulated_no_key" in row["index_error"]
    assert dbc.kb_document_chunks.count_documents({
        "tenant_id": kb_tenant_a, "doc_id": kb_id,
    }) == 0


@pytest.mark.anyio
async def test_index_document_empty_extract_marks_error(
    adb, dbc, kb_tenant_a,
):
    """Empty / unparseable bytes → 'no_extractable_text'
    error status."""
    from services.kb.kb_indexer import index_document
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    report = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=b"garbage", embedder=_fake_embed_factory(),
    )
    assert report.status == "error"
    row = dbc.ai_knowledge_base.find_one({"id": kb_id})
    assert row["index_status"] == "error"
    assert "no_extractable_text" in row["index_error"]


@pytest.mark.anyio
async def test_index_document_status_transitions_indexing_to_ready(
    adb, dbc, kb_tenant_a,
):
    """The first thing ``index_document`` does is flip
    ``index_status`` to ``'indexing'`` — verify by inspecting
    the doc AFTER the flip but BEFORE embed completes (using
    an embedder that observes the doc state)."""
    from services.kb.kb_indexer import index_document
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    pdf = _make_pdf(["Transition check " * 40])

    seen_status: dict = {}

    async def _observe_then_embed(texts):
        row = dbc.ai_knowledge_base.find_one({"id": kb_id})
        seen_status["value"] = row["index_status"]
        # Delegate to the real fake embedder.
        return await _fake_embed_factory()(texts)

    report = await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_observe_then_embed,
    )
    assert seen_status["value"] == "indexing"
    assert report.status == "ready"


# ══════════════════════════════════════════════════════════════
# Query contract — top_k, min_score, tenant iso, doc_ids filter
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_query_returns_top_k_hits(adb, dbc, kb_tenant_a):
    """Cosine similarity ranks the exact-match chunk on top."""
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_id = _seed_kb_doc(dbc, kb_tenant_a, title="Chlorine Manual")
    pdf = _make_pdf([
        "The chlorine dosage table is on page five. "
        "For weekly service, use 3ppm.",
        "See Figure 12 for the wiring diagram of the pool pump. "
        "Diagram 3 shows the filter assembly.",
    ])
    await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )

    # Since the fake embedder is hash-based, only IDENTICAL
    # strings hit exact cosine=1. Query the first chunk's
    # text back to confirm it top-ranks.
    persisted = list(dbc.kb_document_chunks.find(
        {"tenant_id": kb_tenant_a, "doc_id": kb_id, "page_num": 1},
        {"_id": 0, "chunk_text": 1},
    ).limit(1))
    query_text = persisted[0]["chunk_text"]

    result = await search_chunks(
        query=query_text, tenant_id=kb_tenant_a, db=adb,
        top_k=3, min_score=0.0,
        embedder=_fake_embed_factory(),
    )
    assert len(result["hits"]) <= 3
    assert result["hits"], "expected at least one hit"
    top = result["hits"][0]
    assert top["doc_id"] == kb_id
    assert top["page_num"] == 1
    assert top["doc_title"] == "Chlorine Manual"
    assert top["score"] >= 0.99, (
        f"exact-string round-trip should score ~1.0, got {top['score']}"
    )


@pytest.mark.anyio
async def test_query_min_score_cutoff(adb, dbc, kb_tenant_a):
    """A high ``min_score`` filters out low-similarity chunks.
    ``0.99`` cuts everything except an exact-string round-trip.
    """
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_id = _seed_kb_doc(dbc, kb_tenant_a)
    pdf = _make_pdf(["Content A " * 30, "Content B " * 30])
    await index_document(
        kb_id, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=_fake_embed_factory(),
    )
    result = await search_chunks(
        query="totally unrelated query string",
        tenant_id=kb_tenant_a, db=adb, top_k=6,
        min_score=0.99,
        embedder=_fake_embed_factory(),
    )
    assert result["hits"] == []


@pytest.mark.anyio
async def test_query_tenant_isolation_zero_cross_bleed(
    adb, dbc, kb_tenant_a, kb_tenant_b,
):
    """Two tenants index the SAME chunk text; a query on
    tenant-A NEVER returns tenant-B rows."""
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_a = _seed_kb_doc(dbc, kb_tenant_a, title="A's Doc")
    kb_b = _seed_kb_doc(dbc, kb_tenant_b, title="B's Doc")
    identical_pdf = _make_pdf(["Identical corpus " * 40])

    fake = _fake_embed_factory()
    await index_document(
        kb_a, tenant_id=kb_tenant_a, db=adb,
        file_bytes=identical_pdf, embedder=fake,
    )
    await index_document(
        kb_b, tenant_id=kb_tenant_b, db=adb,
        file_bytes=identical_pdf, embedder=fake,
    )

    result_a = await search_chunks(
        query="Identical corpus", tenant_id=kb_tenant_a, db=adb,
        top_k=10, min_score=0.0, embedder=fake,
    )
    for hit in result_a["hits"]:
        assert hit["doc_id"] == kb_a, (
            f"tenant-A query leaked a tenant-B hit: {hit}"
        )


@pytest.mark.anyio
async def test_query_doc_ids_filter(adb, dbc, kb_tenant_a):
    """``doc_ids=[X]`` narrows results to that single doc."""
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_x = _seed_kb_doc(dbc, kb_tenant_a, title="Doc X")
    kb_y = _seed_kb_doc(dbc, kb_tenant_a, title="Doc Y")
    pdf = _make_pdf(["Common phrase " * 40])
    fake = _fake_embed_factory()
    await index_document(
        kb_x, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    await index_document(
        kb_y, tenant_id=kb_tenant_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    # Query filtered to doc X only.
    result = await search_chunks(
        query="Common phrase", tenant_id=kb_tenant_a, db=adb,
        top_k=10, min_score=0.0, doc_ids=[kb_x],
        embedder=fake,
    )
    assert result["hits"], "expected hits on doc X"
    for hit in result["hits"]:
        assert hit["doc_id"] == kb_x
