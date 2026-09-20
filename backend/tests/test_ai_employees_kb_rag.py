"""Phase Feb-2026 · AI Employees chat — ai_knowledge_base RAG tests.

Covers the pure retrieval helper (Path B / text search) and the end-
to-end wire-in via the AI Employees ``send_message`` endpoint.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from services.ai_kb_retrieval import (
    _score,
    _tokenize,
    format_kb_context,
    retrieve_kb_sources,
)


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    """Force a single ``asyncio`` backend so motor's session-scoped
    client can reuse the same event loop across every async test in
    this module.  Without this each ``@pytest.mark.anyio`` test
    spins up a fresh loop and motor's cached loop reference goes
    stale between calls → ``RuntimeError: Event loop is closed``."""
    return "asyncio"


@pytest.fixture(scope="module")
async def motor_db():
    """Fresh motor client bound to the test module's event loop.
    Passed into ``retrieve_kb_sources`` via ``db_handle=`` so we
    never touch the app's process-wide motor client (which is
    bound to the uvicorn worker's loop, not pytest's)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    cli = AsyncIOMotorClient(_MONGO_URL)
    yield cli[_DB_NAME]
    cli.close()


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _admin_headers():
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tenant_id() -> str:
    return _sync.tenants.find_one(
        {"slug": "aquaterra"}, {"_id": 0, "id": 1},
    )["id"]


# ═══════════════════════ pure builder ═══════════════════════════════
class TestTokenizer:
    def test_lowercases_and_dedupes(self):
        assert _tokenize("Pool pool POOL cleaner") == ["pool", "cleaner"]

    def test_strips_stopwords(self):
        # "how", "do", "i", "for", "a" all filtered → only content words
        toks = _tokenize("How do I set up chemicals for a saltwater pool?")
        assert "how" not in toks
        assert "chemicals" in toks
        assert "saltwater" in toks
        assert "pool" in toks

    def test_empty_input(self):
        assert _tokenize("") == []
        assert _tokenize(None) == []


class TestScoring:
    def test_title_weighs_more_than_body(self):
        row = {"title": "Chemical dosing", "content_md": "Some body",
               "tags": []}
        title_score = _score(row, ["chemical"])
        body_score = _score(
            {"title": "Other", "content_md": "chemical body", "tags": []},
            ["chemical"],
        )
        assert title_score > body_score

    def test_tags_contribute(self):
        row = {"title": "x", "content_md": "y", "tags": ["saltwater"]}
        assert _score(row, ["saltwater"]) > 0

    def test_no_tokens_no_score(self):
        row = {"title": "x", "content_md": "y", "tags": []}
        assert _score(row, []) == 0.0


# ═══════════════════════ live retrieval helper ══════════════════════
@pytest.fixture
def seeded_kb_docs():
    """Insert a few TEST_ KB docs across two tenants + verify tenant
    isolation. Cleaned up automatically."""
    tid = _tenant_id()
    other_tid = f"TEST_kb_other_{uuid.uuid4().hex[:6]}"
    docs = [
        {
            "id": f"kb-a-{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "kind": "policy",
            "title": "TEST_ Saltwater chemical dosing policy",
            "content_md": "Weekly rounds must maintain 3.5g/L salinity "
                          "in every saltwater pool. Check the chlorinator "
                          "current after each visit.",
            "tags": ["saltwater", "chemicals"],
            "is_active": True, "is_deleted": False,
            "updated_at": "2026-02-14T10:00:00Z",
        },
        {
            "id": f"kb-b-{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "kind": "faq",
            "title": "TEST_ Employee benefits FAQ",
            "content_md": "PTO accrues at 1.25 days/month. Health kicks "
                          "in after 60 days.",
            "tags": ["hr"], "is_active": True, "is_deleted": False,
            "updated_at": "2026-02-01T10:00:00Z",
        },
        {
            "id": f"kb-c-{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "kind": "custom",
            "title": "TEST_ Inactive draft chemical policy",
            "content_md": "Draft saltwater chemical policy — not final.",
            "tags": ["saltwater"], "is_active": False, "is_deleted": False,
            "updated_at": "2026-02-10T10:00:00Z",
        },
        {
            "id": f"kb-d-{uuid.uuid4().hex[:6]}",
            "tenant_id": tid, "kind": "faq",
            "title": "TEST_ Deleted chem faq",
            "content_md": "should never appear",
            "tags": ["chemicals"], "is_active": True, "is_deleted": True,
            "updated_at": "2026-02-10T10:00:00Z",
        },
        # Cross-tenant leak candidate
        {
            "id": f"kb-x-{uuid.uuid4().hex[:6]}",
            "tenant_id": other_tid, "kind": "policy",
            "title": "TEST_ Cross-tenant saltwater doc — MUST NOT LEAK",
            "content_md": "This must not appear for the aquaterra tenant.",
            "tags": ["saltwater"], "is_active": True, "is_deleted": False,
            "updated_at": "2026-02-14T10:00:00Z",
        },
    ]
    _sync.ai_knowledge_base.insert_many(docs)
    yield {"tenant_id": tid, "docs": docs}
    _sync.ai_knowledge_base.delete_many(
        {"id": {"$in": [d["id"] for d in docs]}},
    )


class TestRetrievalHelper:
    @pytest.mark.anyio
    async def test_returns_active_match_only(self, seeded_kb_docs, motor_db):
        tid = seeded_kb_docs["tenant_id"]
        sources = await retrieve_kb_sources(
            tid, "saltwater chemicals dosing", db_handle=motor_db,
        )
        titles = [s["title"] for s in sources]
        assert any("Saltwater chemical dosing policy" in t for t in titles)
        assert not any("Inactive draft" in t for t in titles)
        assert not any("Deleted chem" in t for t in titles)

    @pytest.mark.anyio
    async def test_tenant_isolation(self, seeded_kb_docs, motor_db):
        tid = seeded_kb_docs["tenant_id"]
        sources = await retrieve_kb_sources(
            tid, "saltwater chemicals", db_handle=motor_db,
        )
        titles = [s["title"] for s in sources]
        assert not any("Cross-tenant" in t for t in titles)

    @pytest.mark.anyio
    async def test_empty_query_returns_empty(self, seeded_kb_docs, motor_db):
        out = await retrieve_kb_sources(
            seeded_kb_docs["tenant_id"], "", db_handle=motor_db,
        )
        assert out == []

    @pytest.mark.anyio
    async def test_no_match_returns_empty(self, seeded_kb_docs, motor_db):
        out = await retrieve_kb_sources(
            seeded_kb_docs["tenant_id"], "unrelated_gibberish_zzzz",
            db_handle=motor_db,
        )
        assert out == []

    @pytest.mark.anyio
    async def test_top_k_cap(self, seeded_kb_docs, motor_db):
        out = await retrieve_kb_sources(
            seeded_kb_docs["tenant_id"],
            "policy chemicals faq saltwater", top_k=1,
            db_handle=motor_db,
        )
        assert len(out) == 1

    @pytest.mark.anyio
    async def test_result_shape(self, seeded_kb_docs, motor_db):
        out = await retrieve_kb_sources(
            seeded_kb_docs["tenant_id"], "saltwater chemicals",
            db_handle=motor_db,
        )
        assert out
        first = out[0]
        assert set(first.keys()) >= {"doc_id", "title", "snippet", "kind", "score"}


class TestFormatContext:
    def test_empty_returns_empty(self):
        assert format_kb_context([]) == ""

    def test_includes_title_and_snippet(self):
        blob = format_kb_context([
            {"doc_id": "1", "title": "Chem", "kind": "policy",
             "snippet": "Do this thing."},
        ])
        assert "Chem" in blob
        assert "Do this thing." in blob
        assert "knowledge base" in blob.lower()


# ═══════════════════════ endpoint smoke ═════════════════════════════
def _get_admin_employee_id(headers):
    r = requests.get(f"{API}/ai-employees", headers=headers, timeout=15)
    r.raise_for_status()
    rows = r.json()
    for row in rows:
        if (row.get("audience") or "admin") == "admin":
            return row["id"]
    return rows[0]["id"]


class TestSendMessageAttachesSources:
    def test_sources_returned_when_kb_matches(self, seeded_kb_docs):
        h = _admin_headers()
        eid = _get_admin_employee_id(h)
        r = requests.post(
            f"{API}/ai-employees/{eid}/conversations",
            headers=h, json={"title": "TEST_ kb rag"}, timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        cid = r.json()["id"]

        r2 = requests.post(
            f"{API}/ai-employees/{eid}/conversations/{cid}/messages",
            headers=h,
            json={"text": "How do we handle saltwater chemical dosing?"},
            timeout=45,
        )
        assert r2.status_code in (200, 201), r2.text
        body = r2.json()
        # Envelope-level ``sources``
        assert "sources" in body
        assert isinstance(body["sources"], list)
        titles = [s.get("title", "") for s in body["sources"]]
        assert any("Saltwater chemical dosing" in t for t in titles)
        # Mirrored on the assistant message
        assistant = body["assistant_message"]
        assert isinstance(assistant.get("sources"), list)
        assert titles == [s["title"] for s in assistant["sources"]]

    def test_sources_empty_on_unrelated_query(self):
        h = _admin_headers()
        eid = _get_admin_employee_id(h)
        r = requests.post(
            f"{API}/ai-employees/{eid}/conversations",
            headers=h, json={"title": "TEST_ kb rag empty"}, timeout=15,
        )
        cid = r.json()["id"]
        r2 = requests.post(
            f"{API}/ai-employees/{eid}/conversations/{cid}/messages",
            headers=h,
            json={"text": "purple monkey dishwasher blorf blorf"},
            timeout=45,
        )
        assert r2.status_code in (200, 201)
        body = r2.json()
        assert isinstance(body.get("sources"), list)
        # No KB doc mentions "purple monkey dishwasher" so no matches.
        # (Aquaterra's seeded company_profile might still hit "we" / "our"
        # if that leaked past the stopword filter — the filter already
        # strips those so this must be exactly zero.)
        assert body["sources"] == []
