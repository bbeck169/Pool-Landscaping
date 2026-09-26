"""QV-service · Feb-2026 — Admin quote-views endpoint tests.

Coverage matrix (per QV-service dispatch):

  1  Admin ``GET /api/quotes/{qid}/views`` → 200 with the summary
     shape (``first_viewed_at`` / ``last_viewed_at`` /
     ``view_count`` / ``events``).
  2  Technician → 403.
  3  Customer   → 403.
  4  Cross-tenant read → tenant-scoped payload (view_count=0,
     empty events) because the summary is filtered by tenant_id in
     ``fetch_quote_views_summary``.
  5  Empty history (never-viewed quote) → 200 with ``view_count: 0``
     + empty events array + null aggregates.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

_db = _shared_db()


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def aqua_tid():
    t = _db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    assert t is not None, "aquaterra tenant not seeded"
    return t["id"]


def _seed_quote(tid: str, status: str = "sent") -> str:
    qid = "TEST_qv_ep_" + uuid.uuid4().hex[:10]
    _db.quotes.insert_one({
        "id": qid, "tenant_id": tid, "doc_type": "quote",
        "status": status,
        "title": "QV endpoint test",
    })
    return qid


def _seed_view_events(tid: str, qid: str, n: int) -> None:
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    for i in range(n):
        _db.quote_views.insert_one({
            "quote_id": qid, "tenant_id": tid,
            "source": "portal", "viewed_at": now_iso,
            "user_agent": "curl/8.4.0", "ua_class": "Other",
            "ip": "203.0.113.42",
        })
    _db.quotes.update_one(
        {"id": qid, "tenant_id": tid, "doc_type": "quote"},
        {"$set": {"first_viewed_at": now_iso,
                    "last_viewed_at": now_iso,
                    "view_count": n}},
    )


def _cleanup(tid: str, qid: str) -> None:
    _db.quotes.delete_one({"id": qid, "tenant_id": tid})
    _db.quote_views.delete_many({"quote_id": qid, "tenant_id": tid})


# ─── 1 · Admin GET → 200 with expected shape ──────────────────
def test_admin_get_quote_views_200_with_summary(admin_headers, aqua_tid):
    qid = _seed_quote(aqua_tid, status="sent")
    _seed_view_events(aqua_tid, qid, n=3)
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/views",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quote_id"] == qid
        assert body["view_count"] == 3
        assert body["first_viewed_at"] is not None
        assert body["last_viewed_at"] is not None
        assert isinstance(body["events"], list)
        assert len(body["events"]) == 3
        # Every event carries the QV-service-specific ua_class.
        for e in body["events"]:
            assert "ua_class" in e
            assert e["source"] == "portal"
            assert e["quote_id"] == qid
    finally:
        _cleanup(aqua_tid, qid)


# ─── 2 · Technician → 403 ─────────────────────────────────────
def test_technician_gets_403(tech_headers, aqua_tid):
    qid = _seed_quote(aqua_tid, status="sent")
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/views",
            headers=tech_headers, timeout=15,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(aqua_tid, qid)


# ─── 3 · Customer → 403 ───────────────────────────────────────
def test_customer_gets_403(customer_headers, aqua_tid):
    qid = _seed_quote(aqua_tid, status="sent")
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/views",
            headers=customer_headers, timeout=15,
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(aqua_tid, qid)


# ─── 4 · Cross-tenant read is filtered ────────────────────────
def test_cross_tenant_returns_empty_summary(admin_headers, aqua_tid):
    """Seed a quote + events under a FOREIGN tenant. The
    aquaterra admin's ``GET`` for that qid MUST return the
    empty-summary shape (view_count=0, events=[], nulls) — the
    handler filters strictly by the caller's tenant_id."""
    foreign_tid = "TEST_qv_foreign_" + uuid.uuid4().hex[:10]
    _db.tenants.insert_one({
        "id": foreign_tid, "slug": f"foreign-{uuid.uuid4().hex[:6]}",
        "name": "Foreign QV tenant", "active": True,
    })
    qid = _seed_quote(foreign_tid, status="sent")
    _seed_view_events(foreign_tid, qid, n=2)
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/views",
            headers=admin_headers, timeout=15,
        )
        # aquaterra admin can call — endpoint doesn't 404 on
        # unknown quote (mirrors invoice sibling shape). But the
        # summary is tenant-scoped to the caller's tenant so both
        # count + events are empty.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quote_id"] == qid
        assert body["view_count"] == 0
        assert body["first_viewed_at"] is None
        assert body["last_viewed_at"] is None
        assert body["events"] == []
    finally:
        _cleanup(foreign_tid, qid)
        _db.tenants.delete_one({"id": foreign_tid})


# ─── 5 · Empty history → 200 with nulls + zero count ──────────
def test_never_viewed_quote_returns_zero_summary(admin_headers, aqua_tid):
    qid = _seed_quote(aqua_tid, status="sent")
    # NO ``_seed_view_events`` — the quote has never been viewed.
    try:
        r = requests.get(
            f"{API}/quotes/{qid}/views",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quote_id"] == qid
        assert body["view_count"] == 0
        assert body["first_viewed_at"] is None
        assert body["last_viewed_at"] is None
        assert body["events"] == []
    finally:
        _cleanup(aqua_tid, qid)
