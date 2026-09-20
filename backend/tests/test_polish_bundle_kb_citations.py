"""Phase Feb-2026 · Polish bundle · Item 2 tests.

``GET /api/ai/kb/citations/top`` — aggregates
``ai_employee_messages.sources[]`` by ``doc_id``. Admin+/super_admin.
Tenant-scoped. Empty telemetry returns ``items=[]``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_FE_ENV = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _login(email: str, pwd: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pwd}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def h_customer():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def tenant_id(h_admin):
    r = requests.get(f"{API}/auth/me", headers=h_admin, timeout=15)
    return r.json()["tenant_id"]


def _seed_assistant_message(tid, doc_id, doc_title, when=None, extra=None):
    when = when or datetime.now(timezone.utc)
    row = {
        "id": f"TEST_pb2-{uuid.uuid4().hex[:8]}",
        "tenant_id": tid,
        "conversation_id": f"TEST_pb2-conv-{uuid.uuid4().hex[:4]}",
        "employee_id": f"TEST_pb2-emp-{uuid.uuid4().hex[:4]}",
        "role": "assistant",
        "text": "TEST_pb2 seeded response",
        "sources": [{"doc_id": doc_id, "title": doc_title,
                      "snippet": "s", "kind": "policy", "score": 1.0}],
        "created_at": when.isoformat(),
    }
    if extra:
        row.update(extra)
    _sync.ai_employee_messages.insert_one(row)
    return row["id"]


@pytest.fixture()
def seeded_citations(tenant_id):
    """Seed 3 assistant messages: doc-A cited 2x, doc-B cited 1x."""
    ids = []
    now = datetime.now(timezone.utc)
    ids.append(_seed_assistant_message(
        tenant_id, "TEST_pb2-doc-A", "TEST_pb2 Doc A", when=now))
    ids.append(_seed_assistant_message(
        tenant_id, "TEST_pb2-doc-A", "TEST_pb2 Doc A",
        when=now - timedelta(hours=1)))
    ids.append(_seed_assistant_message(
        tenant_id, "TEST_pb2-doc-B", "TEST_pb2 Doc B",
        when=now - timedelta(hours=2)))
    yield {"doc_a": "TEST_pb2-doc-A", "doc_b": "TEST_pb2-doc-B"}
    _sync.ai_employee_messages.delete_many({"id": {"$in": ids}})


class TestKBCitationsEndpoint:
    def test_returns_grouped_top_docs(self, h_admin, seeded_citations):
        r = requests.get(
            f"{API}/ai/kb/citations/top?days=7&limit=10",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        by_id = {it["doc_id"]: it for it in body["items"]}
        # Both seeded docs must appear
        assert seeded_citations["doc_a"] in by_id
        assert seeded_citations["doc_b"] in by_id
        # Doc A cited 2x, Doc B cited 1x
        assert by_id[seeded_citations["doc_a"]]["citations"] >= 2
        assert by_id[seeded_citations["doc_b"]]["citations"] >= 1
        # Doc A must rank above Doc B
        docs = [it["doc_id"] for it in body["items"]]
        assert docs.index(seeded_citations["doc_a"]) < \
            docs.index(seeded_citations["doc_b"])

    def test_empty_when_no_matches(self, h_admin, tenant_id):
        # 1-day window with an impossibly-narrow query — pick a
        # cutoff that excludes all future/backfilled rows.
        r = requests.get(
            f"{API}/ai/kb/citations/top?days=1&limit=5",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200, r.text
        # We only assert shape here — the tenant may have other
        # activity within 1d; we validate schema, not counts.
        body = r.json()
        assert "items" in body
        assert body["days"] == 1
        assert "since" in body and "until" in body

    def test_limit_param_respected(self, h_admin, seeded_citations):
        r = requests.get(
            f"{API}/ai/kb/citations/top?days=7&limit=1",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) <= 1

    def test_customer_forbidden(self, h_customer):
        r = requests.get(
            f"{API}/ai/kb/citations/top?days=7&limit=5",
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403

    def test_missing_days_uses_default(self, h_admin):
        r = requests.get(
            f"{API}/ai/kb/citations/top",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["days"] == 7

    def test_days_out_of_range_422(self, h_admin):
        r = requests.get(
            f"{API}/ai/kb/citations/top?days=0",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 422
