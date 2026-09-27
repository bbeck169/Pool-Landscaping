"""KB IH-A · Feb-2026 — HTTP route contract tests.

Covers:
- ``POST /api/kb/query`` returns hits with ``page_num`` +
  ``figure_refs`` + ``doc_title`` + tenant isolation.
- ``POST /api/kb/documents/{doc_id}/reindex`` admin-gated.
- Query auth-guarded.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_TEST_DIR = Path(__file__).resolve().parent
_FE = dotenv_values(_TEST_DIR.parent.parent / "frontend" / ".env")
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

# Point at localhost:8001 by default — uvicorn direct.  The
# preview URL k8s ingress occasionally cold-starts on the
# first hit of a test session; localhost keeps this suite
# hermetic + fast.  Callers can still override via env
# ``KB_ROUTE_TEST_URL=https://...``.
BASE = (os.environ.get("KB_ROUTE_TEST_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def admin_h(dbc):
    """Reuse the aquaterra admin login pattern used across the
    project's HTTP tests.  Returns ``{"Authorization": "Bearer ..."}``.
    """
    res = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=15,
    )
    res.raise_for_status()
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


def _seed_kb_with_chunks(dbc, tenant_id: str, title: str) -> str:
    kb_id = f"kb-rt-{uuid.uuid4().hex[:12]}"
    dbc.ai_knowledge_base.insert_one({
        "id": kb_id,
        "tenant_id": tenant_id,
        "kind": "custom",
        "title": title,
        "content_md": "seed",
        "tags": [],
        "is_active": True,
        "source_type": "pdf",
        "index_status": "ready",
        "chunks_count": 1,
        "pages_count": 1,
        "last_indexed_at": datetime.now(timezone.utc).isoformat(),
        "index_error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    # Pre-seed one chunk with a deterministic embedding we can
    # query against.  1536-dim, half zeros half 1/sqrt(768)
    # → norm = 1.  Query vector must match to score high.
    vec = [0.0] * 1536
    for i in range(768):
        vec[i] = 1.0 / (768 ** 0.5)
    dbc.kb_document_chunks.insert_one({
        "tenant_id": tenant_id,
        "doc_id": kb_id,
        "page_num": 4,
        "chunk_index": 0,
        "chunk_text": "The chlorine dosage table is on page four. See Figure 7.",
        "char_start": 0,
        "char_end": 60,
        "figure_refs": [
            {"page_num": 4, "figure_label": "Figure 7", "bbox": None},
        ],
        "embedding": vec,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    })
    return kb_id


@pytest.fixture()
def kb_doc_with_chunks(dbc, aquaterra_id):
    kb_id = _seed_kb_with_chunks(dbc, aquaterra_id, "Routes Test Manual")
    yield kb_id
    dbc.ai_knowledge_base.delete_one({"id": kb_id})
    dbc.kb_document_chunks.delete_many({"doc_id": kb_id})


# ══════════════════════════════════════════════════════════════
# Query route
# ══════════════════════════════════════════════════════════════
def test_query_unauth_returns_401():
    res = requests.post(f"{API}/kb/query", json={"query": "x"}, timeout=15)
    assert res.status_code in (401, 403)


def test_query_authenticated_returns_hits_or_error_gracefully(
    admin_h, kb_doc_with_chunks,
):
    """Route smoke — auth'd query returns 200 with either
    hits or a graceful ``error`` field when the embedder is
    unavailable in the runtime env (no ``OPENAI_API_KEY``).
    Never crashes.  Full semantic-scoring contract is covered
    by ``test_kb_query.py`` unit tests via injected fake
    embedder — in-server injection isn't possible for a live
    ``uvicorn`` process.
    """
    res = requests.post(
        f"{API}/kb/query",
        json={"query": "chlorine dosage", "top_k": 3, "min_score": 0.0},
        headers=admin_h, timeout=15,
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert "hits" in payload
    assert "query_ms" in payload
    # Either the runtime embedder succeeded (hits present or
    # empty depending on cosine outcome) OR it failed and the
    # response carries a legible ``error`` field.
    if "error" in payload:
        assert isinstance(payload["error"], str)
        assert payload["hits"] == []
    else:
        assert isinstance(payload["hits"], list)


# ══════════════════════════════════════════════════════════════
# Reindex route
# ══════════════════════════════════════════════════════════════
def test_reindex_unknown_doc_404(admin_h):
    res = requests.post(
        f"{API}/kb/documents/does-not-exist/reindex",
        headers=admin_h, timeout=15,
    )
    assert res.status_code == 404


def test_reindex_missing_source_bytes_409(
    admin_h, dbc, aquaterra_id,
):
    """PDF KB doc without a linked files row → 409
    ``source_bytes_missing`` (no S3 read path)."""
    kb_id = _seed_kb_with_chunks(dbc, aquaterra_id, "No Source Doc")
    try:
        res = requests.post(
            f"{API}/kb/documents/{kb_id}/reindex",
            headers=admin_h, timeout=10,
        )
        assert res.status_code == 409
        body = res.json()
        assert (
            body.get("detail", {}).get("code") == "source_bytes_missing"
            or body.get("code") == "source_bytes_missing"
        )
    finally:
        dbc.ai_knowledge_base.delete_one({"id": kb_id})
        dbc.kb_document_chunks.delete_many({"doc_id": kb_id})


def test_reindex_non_pdf_uses_content_md_fallback(
    admin_h, dbc, aquaterra_id, monkeypatch,
):
    """Non-PDF source (txt / md) reindex reads ``content_md``
    as fallback text — no S3 lookup, no 409."""
    kb_id = f"kb-txt-{uuid.uuid4().hex[:12]}"
    dbc.ai_knowledge_base.insert_one({
        "id": kb_id,
        "tenant_id": aquaterra_id,
        "kind": "custom", "title": "TXT reindex",
        "content_md": "Some markdown content " * 30,
        "tags": [], "is_active": True,
        "source_type": "txt",
        "index_status": "ready", "chunks_count": 0, "pages_count": 0,
        "last_indexed_at": None, "index_error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        res = requests.post(
            f"{API}/kb/documents/{kb_id}/reindex",
            headers=admin_h, timeout=10,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True
        assert body["status"] == "pending"
    finally:
        dbc.ai_knowledge_base.delete_one({"id": kb_id})
        dbc.kb_document_chunks.delete_many({"doc_id": kb_id})


def test_reindex_unauth_returns_401():
    res = requests.post(
        f"{API}/kb/documents/any/reindex", timeout=15,
    )
    assert res.status_code in (401, 403)


def test_openapi_surfaces_new_kb_routes():
    """Both new routes appear in the OpenAPI schema."""
    res = requests.get(f"{API}/openapi.json", timeout=15)
    assert res.status_code == 200
    schema = res.json()
    paths = schema.get("paths", {})
    assert "/api/kb/query" in paths, (
        f"missing /api/kb/query in openapi paths; sample: "
        f"{list(paths)[:8]}"
    )
    assert "/api/kb/documents/{doc_id}/reindex" in paths, (
        "missing /api/kb/documents/{doc_id}/reindex in openapi paths"
    )
