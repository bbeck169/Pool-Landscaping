"""KB IH-A · Feb-2026 — cosine query contract (unit).

Split-out from ``test_kb_indexer.py`` to match the file
layout the user brief specified.  Shares the same fake
hash-based embedder + PDF synth helpers used in the indexer
suite — no OpenAI calls.

Coverage:
- top_k slicing.
- ``min_score`` cutoff removes low-similarity chunks.
- Tenant isolation — 2 tenants with identical text → 0
  cross-tenant hits.
- ``doc_ids`` filter narrows to the intended KB doc.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
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


@pytest.fixture()
def adb():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def kb_tenant_q_a(dbc):
    tid = f"tenant-kbq-a-{uuid.uuid4().hex[:12]}"
    dbc.tenants.insert_one({"id": tid, "slug": tid, "name": "KB-Q A"})
    yield tid
    dbc.tenants.delete_one({"id": tid})
    dbc.ai_knowledge_base.delete_many({"tenant_id": tid})
    dbc.kb_document_chunks.delete_many({"tenant_id": tid})


@pytest.fixture()
def kb_tenant_q_b(dbc):
    tid = f"tenant-kbq-b-{uuid.uuid4().hex[:12]}"
    dbc.tenants.insert_one({"id": tid, "slug": tid, "name": "KB-Q B"})
    yield tid
    dbc.tenants.delete_one({"id": tid})
    dbc.ai_knowledge_base.delete_many({"tenant_id": tid})
    dbc.kb_document_chunks.delete_many({"tenant_id": tid})


def _fake_embed_factory(dim: int = 1536):
    async def _fake_embed(texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for text in texts:
            h = hashlib.sha256((text or "").encode("utf-8")).digest()
            vec = []
            for i in range(dim):
                b = h[i % len(h)]
                vec.append(((b / 255.0) - 0.5) * ((i % 7) + 1) * 0.1)
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out
    return _fake_embed


def _make_pdf(pages):
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


def _seed_kb_doc(dbc, tenant_id: str, title: str = "Q Test") -> str:
    kb_id = f"kb-q-{uuid.uuid4().hex[:12]}"
    dbc.ai_knowledge_base.insert_one({
        "id": kb_id, "tenant_id": tenant_id,
        "kind": "custom", "title": title,
        "content_md": "seed", "tags": [], "is_active": True,
        "source_type": "pdf",
        "index_status": "pending", "chunks_count": 0, "pages_count": 0,
        "last_indexed_at": None, "index_error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return kb_id


# ══════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════
@pytest.mark.anyio
async def test_top_k_respected(adb, dbc, kb_tenant_q_a):
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_id = _seed_kb_doc(dbc, kb_tenant_q_a)
    # PDF with 3 pages of distinct text → several chunks.
    pdf = _make_pdf([
        "Alpha content " * 40,
        "Beta content "  * 40,
        "Gamma content " * 40,
    ])
    fake = _fake_embed_factory()
    await index_document(
        kb_id, tenant_id=kb_tenant_q_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    result = await search_chunks(
        query="alpha", tenant_id=kb_tenant_q_a, db=adb,
        top_k=2, min_score=0.0, embedder=fake,
    )
    assert len(result["hits"]) <= 2


@pytest.mark.anyio
async def test_min_score_cutoff_removes_low_similarity(
    adb, dbc, kb_tenant_q_a,
):
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_id = _seed_kb_doc(dbc, kb_tenant_q_a)
    pdf = _make_pdf(["Filter content " * 40])
    fake = _fake_embed_factory()
    await index_document(
        kb_id, tenant_id=kb_tenant_q_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    # An unrelated query on a hash-based embedder will yield
    # low cosine — 0.99 min_score cuts everything.
    result = await search_chunks(
        query="wildly unrelated cosmic ray telescope",
        tenant_id=kb_tenant_q_a, db=adb, top_k=6,
        min_score=0.99, embedder=fake,
    )
    assert result["hits"] == []


@pytest.mark.anyio
async def test_tenant_isolation_zero_cross_bleed(
    adb, dbc, kb_tenant_q_a, kb_tenant_q_b,
):
    """Both tenants index the SAME corpus; a query on
    tenant-A NEVER returns tenant-B rows."""
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_a = _seed_kb_doc(dbc, kb_tenant_q_a, title="Tenant A")
    kb_b = _seed_kb_doc(dbc, kb_tenant_q_b, title="Tenant B")
    pdf = _make_pdf(["Identical text " * 40])
    fake = _fake_embed_factory()
    await index_document(
        kb_a, tenant_id=kb_tenant_q_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    await index_document(
        kb_b, tenant_id=kb_tenant_q_b, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    result_a = await search_chunks(
        query="Identical text", tenant_id=kb_tenant_q_a, db=adb,
        top_k=50, min_score=-1.0, embedder=fake,
    )
    assert result_a["hits"], "expected at least one hit"
    for hit in result_a["hits"]:
        assert hit["doc_id"] == kb_a, (
            f"cross-tenant leak: tenant-A query returned "
            f"doc_id={hit['doc_id']} which belongs to tenant-B "
            f"(kb_b={kb_b})"
        )


@pytest.mark.anyio
async def test_doc_ids_filter_narrows_to_one_doc(adb, dbc, kb_tenant_q_a):
    from services.kb.kb_indexer import index_document
    from services.kb.kb_query import search_chunks
    kb_x = _seed_kb_doc(dbc, kb_tenant_q_a, title="X")
    kb_y = _seed_kb_doc(dbc, kb_tenant_q_a, title="Y")
    pdf = _make_pdf(["Shared string " * 40])
    fake = _fake_embed_factory()
    await index_document(
        kb_x, tenant_id=kb_tenant_q_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    await index_document(
        kb_y, tenant_id=kb_tenant_q_a, db=adb,
        file_bytes=pdf, embedder=fake,
    )
    result = await search_chunks(
        query="Shared string", tenant_id=kb_tenant_q_a, db=adb,
        top_k=50, min_score=-1.0, doc_ids=[kb_x], embedder=fake,
    )
    assert result["hits"]
    for hit in result["hits"]:
        assert hit["doc_id"] == kb_x
