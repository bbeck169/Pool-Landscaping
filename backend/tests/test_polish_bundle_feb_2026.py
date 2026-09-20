"""Phase Feb-2026 · Polish bundle · Item 1 tests.

``GET /api/recurring-jobs/orphans?source=`` — accept ``structural``
/ ``keyword_match`` / ``gap_inference`` / ``default``; unknown 422;
omitted returns unfiltered set.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
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


def _login() -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": "super@aquaterra.com", "password": "password123"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_id_of(tok: str) -> str:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )
    return r.json()["tenant_id"]


def _seed_customer(tid: str) -> str:
    cid = f"TEST_pb1-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"TEST_pb1_{cid[-6:]}",
    })
    return cid


def _seed_keyword_cluster(tid: str, cid: str) -> None:
    """3 jobs w/ title-only keyword hints → keyword_match source."""
    for i in range(3):
        d = (date(2026, 3, 1) + timedelta(days=7 * i)).isoformat()
        _sync.jobs.insert_one({
            "id": f"TEST_pb1-j-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "customer_id": cid,
            "customer_name": f"TEST_pb1_{cid[-6:]}",
            "title": "TEST_pb1 Weekly Pool Service",
            "service_type": "TEST_pb1_KwSvc",
            "scheduled_date": d, "price": 100.0,
        })


def _cleanup(tid: str, cid: str) -> None:
    _sync.jobs.delete_many({"tenant_id": tid, "customer_id": cid})
    _sync.recurring_job_templates.delete_many(
        {"tenant_id": tid, "customer_id": cid})
    _sync.customers.delete_many({"id": cid})


@pytest.fixture(scope="module")
def token() -> str:
    return _login()


@pytest.fixture(scope="module")
def tenant_id(token) -> str:
    return _tenant_id_of(token)


@pytest.fixture()
def kw_cluster(tenant_id):
    cid = _seed_customer(tenant_id)
    _seed_keyword_cluster(tenant_id, cid)
    yield cid
    _cleanup(tenant_id, cid)


class TestOrphansSourceFilter:
    def test_no_filter_returns_all(self, token, kw_cluster):
        r = requests.get(
            f"{API}/recurring-jobs/orphans",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("source_filter") is None
        ours = [x for x in body["orphans"]
                if x.get("customer_id") == kw_cluster]
        assert len(ours) == 1
        assert ours[0]["backfill_source"] == "keyword_match"

    def test_filter_keyword_match(self, token, kw_cluster):
        r = requests.get(
            f"{API}/recurring-jobs/orphans?source=keyword_match",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_filter"] == "keyword_match"
        # every row in the response carries the filter value
        for row in body["orphans"]:
            assert row["backfill_source"] == "keyword_match"
        # our seeded cluster IS in the filtered response
        ours = [x for x in body["orphans"]
                if x.get("customer_id") == kw_cluster]
        assert len(ours) == 1

    def test_filter_default_excludes_keyword_cluster(self, token, kw_cluster):
        r = requests.get(
            f"{API}/recurring-jobs/orphans?source=default",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_filter"] == "default"
        # our keyword cluster must NOT be in a ``default``-filtered result
        ours = [x for x in body["orphans"]
                if x.get("customer_id") == kw_cluster]
        assert ours == []

    def test_filter_structural_excludes_keyword_cluster(self, token,
                                                          kw_cluster):
        r = requests.get(
            f"{API}/recurring-jobs/orphans?source=structural",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source_filter"] == "structural"
        ours = [x for x in body["orphans"]
                if x.get("customer_id") == kw_cluster]
        assert ours == []

    def test_unknown_source_returns_422(self, token):
        r = requests.get(
            f"{API}/recurring-jobs/orphans?source=bogus",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 422, r.text
        body = r.json()
        assert "invalid_source" in str(body.get("detail", ""))

    def test_empty_source_treated_as_omitted_or_422(self, token, kw_cluster):
        """``?source=`` (empty value) — FastAPI parses this as empty
        string, which is neither omitted nor a valid enum member, so
        it must 422. This guards against silently returning
        unfiltered results when the client sends a blank string."""
        r = requests.get(
            f"{API}/recurring-jobs/orphans?source=",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        assert r.status_code == 422, r.text
