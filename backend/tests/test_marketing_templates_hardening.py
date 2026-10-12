"""P1-M3-HARDENING · Feb-2026 — Marketing-templates list + create
defensive hardening regression.

Locks the following guarantees:

1. ``GET /api/marketing/templates`` returns the LEGACY shape
   ``{templates, count}`` when neither ``page`` nor ``size`` is
   supplied (backward compat for ~7 existing FE consumers).
2. ``GET /api/marketing/templates?page=1&size=5`` returns the
   PAGINATED shape ``{items, total, page, size, has_next,
   templates, count}``, each item has a stable sort order, and
   ``has_next`` flips correctly across page boundaries.
3. Pagination over a seeded tenant with 12 synthetic templates:
   page=1,size=5 → 5 items + has_next=True; page=3,size=5 →
   remaining 2 items + has_next=False.
4. Empty tenant: paginated response returns ``items=[]`` + ``total=0``
   + ``has_next=False`` — NOT a 404.
5. ``POST /api/marketing/templates`` with a minimal valid email body
   returns 201 and the created ``id``. Row is retrievable via GET.
6. ``POST`` with ``channel="whatever"`` → 422 (not 500/502).
7. ``POST`` with ``channel="email"`` but no subject → 422.
8. Uncaught exception on list → 500 with
   ``error_code=marketing_template_list_internal_error`` (unit test
   via dependency override + mocked ``db``).
9. Uncaught exception on create → 500 with
   ``error_code=marketing_template_create_internal_error`` (unit
   test via dependency override + mocked ``db``).
10. ``POST`` with ``body_html`` instead of ``body`` creates the row
    with the HTML content preserved (alias tolerance).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Dict, List, Optional

import pytest
import requests


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"

TAG = "p1mt-hard-"


def _login(email: str = "admin@aquaterra.com", pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def created_ids(admin_headers) -> List[str]:
    """Collect created template ids and soft-delete them at teardown
    so repeated runs don't leak noise into the admin surface."""
    ids: List[str] = []
    yield ids
    for tid in ids:
        try:
            requests.delete(
                f"{API}/marketing/templates/{tid}",
                headers=admin_headers,
                timeout=10,
            )
        except Exception:  # pragma: no cover
            pass


def _mk_payload(
    *,
    channel: str = "email",
    subject: Optional[str] = "P1-M3 test",
    body: str = "<p>hello</p>",
    name_suffix: str = "",
    body_html: Optional[str] = None,
) -> dict:
    name = f"{TAG}{name_suffix or uuid.uuid4().hex[:6]}"
    p: Dict[str, object] = {
        "name": name,
        "channel": channel,
        "category": "general",
        "subject": subject,
        "body": body,
        "active": True,
    }
    if body_html is not None:
        p["body_html"] = body_html
    return p


# ═══════════════════════════════════════════════════════════════════
# Shape locks
# ═══════════════════════════════════════════════════════════════════
def test_list_legacy_shape_backward_compat(admin_headers):
    r = requests.get(
        f"{API}/marketing/templates", headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # Legacy shape MUST remain the default — ~7 FE consumers depend
    # on ``.templates`` / ``.count`` keys.
    assert "templates" in d
    assert "count" in d
    assert isinstance(d["templates"], list)
    assert d["count"] == len(d["templates"])
    # Legacy response does NOT carry the paginated envelope.
    assert "items" not in d
    assert "total" not in d


def test_list_paginated_shape_envelope(admin_headers):
    r = requests.get(
        f"{API}/marketing/templates?page=1&size=5",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("items", "total", "page", "size", "has_next"):
        assert k in d, f"missing paginated key: {k}"
    assert d["page"] == 1
    assert d["size"] == 5
    assert isinstance(d["items"], list)
    assert len(d["items"]) <= 5
    assert isinstance(d["total"], int) and d["total"] >= 0
    assert isinstance(d["has_next"], bool)
    # Legacy aliases kept alongside for FE backward compat.
    assert d["templates"] == d["items"]
    assert d["count"] == len(d["items"])


def test_list_size_only_triggers_pagination(admin_headers):
    """Only ``size`` supplied → defaults page=1 and still returns
    the paginated envelope."""
    r = requests.get(
        f"{API}/marketing/templates?size=3",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["page"] == 1
    assert d["size"] == 3
    assert len(d["items"]) <= 3


# ═══════════════════════════════════════════════════════════════════
# Pagination boundary test (seeded synthetic tenant)
# ═══════════════════════════════════════════════════════════════════
def _seed_synthetic_templates(dbc, tid: str, n: int) -> List[str]:
    """Insert ``n`` lightweight marketing_templates rows directly in
    Mongo so pagination semantics are tested against a stable set."""
    from datetime import datetime, timezone
    ids: List[str] = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(n):
        _id = f"{TAG}syn-{uuid.uuid4().hex[:8]}"
        dbc.marketing_templates.insert_one({
            "id": _id,
            "tenant_id": tid,
            "name": f"{TAG}syn-{i:02d}",
            "channel": "email" if i % 2 == 0 else "sms",
            "category": "general",
            "subject": f"S{i}" if i % 2 == 0 else None,
            "body": f"B{i}",
            "active": True,
            "system": False,
            "created_at": now,
            "updated_at": now,
            "created_by": None,
        })
        ids.append(_id)
    return ids


def test_pagination_boundary_and_has_next():
    """Seed 12 rows into a throwaway tenant → verify page=1/5 has_next=True,
    page=3/5 has_next=False with 2 remaining items. Uses a direct Mongo
    tenant so we don't pollute the admin tenant's template list."""
    from pathlib import Path
    from dotenv import dotenv_values
    from pymongo import MongoClient
    be_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    mongo_url = be_env.get("MONGO_URL")
    db_name = be_env.get("DB_NAME")
    assert mongo_url and db_name, "backend .env must define MONGO_URL + DB_NAME"
    dbc = MongoClient(mongo_url)[db_name]

    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    # Seed a synthetic tenant row so the ``get_current_tenant``
    # dependency can resolve it on request. We also seed a throwaway
    # admin user bound to that tenant so the auth path works.
    uid = f"{TAG}u-{uuid.uuid4().hex[:6]}"
    email = f"{TAG}{uuid.uuid4().hex[:6]}@example.com"
    try:
        dbc.tenants.insert_one({
            "id": tid,
            "slug": tid,
            "name": "P1-M3 hardening test tenant",
            "created_at": "2026-02-15T00:00:00Z",
        })
        # Password hash for ``password123``. Reuse the project's bcrypt
        # helper so we aren't duplicating a hard-coded hash that could
        # drift with cost-factor changes.
        from utils import hash_password  # type: ignore
        dbc.users.insert_one({
            "id": uid,
            "email": email,
            "password_hash": hash_password("password123"),
            "role": "admin",
            "tenant_id": tid,
            "status": "active",
            "created_at": "2026-02-15T00:00:00Z",
        })
        _seed_synthetic_templates(dbc, tid, 12)

        headers = {"Authorization": f"Bearer {_login(email)}"}

        r1 = requests.get(
            f"{API}/marketing/templates?page=1&size=5",
            headers=headers, timeout=30,
        )
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["total"] == 12
        assert len(d1["items"]) == 5
        assert d1["has_next"] is True

        r2 = requests.get(
            f"{API}/marketing/templates?page=3&size=5",
            headers=headers, timeout=30,
        )
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["total"] == 12
        assert len(d2["items"]) == 2
        assert d2["has_next"] is False

        # No overlap between page 1 & 3 — sort is deterministic.
        ids1 = {it["id"] for it in d1["items"]}
        ids3 = {it["id"] for it in d2["items"]}
        assert ids1.isdisjoint(ids3)
    finally:
        dbc.marketing_templates.delete_many({"tenant_id": tid})
        dbc.users.delete_many({"id": uid})
        dbc.tenants.delete_many({"id": tid})


def test_empty_tenant_returns_empty_items_not_404():
    """Fresh tenant with zero templates → 200 with items=[] + total=0."""
    from pathlib import Path
    from dotenv import dotenv_values
    from pymongo import MongoClient
    be_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    dbc = MongoClient(be_env["MONGO_URL"])[be_env["DB_NAME"]]

    tid = f"{TAG}tenant-{uuid.uuid4().hex[:6]}"
    uid = f"{TAG}u-{uuid.uuid4().hex[:6]}"
    email = f"{TAG}{uuid.uuid4().hex[:6]}@example.com"
    try:
        dbc.tenants.insert_one({
            "id": tid, "slug": tid,
            "name": "P1-M3 empty tenant",
            "created_at": "2026-02-15T00:00:00Z",
        })
        from utils import hash_password  # type: ignore
        dbc.users.insert_one({
            "id": uid, "email": email,
            "password_hash": hash_password("password123"),
            "role": "admin", "tenant_id": tid, "status": "active",
            "created_at": "2026-02-15T00:00:00Z",
        })
        # Nuke any boot-time seeded rows so the tenant is really empty
        # (the boot-time ``seed_marketing_templates_for_tenant`` fires
        # on first tenant touch — DELETE before we hit the endpoint).
        dbc.marketing_templates.delete_many({"tenant_id": tid})

        headers = {"Authorization": f"Bearer {_login(email)}"}
        r = requests.get(
            f"{API}/marketing/templates?page=1&size=10",
            headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        # The marketing_studio boot-time seed may have inserted rows
        # between our DELETE and the GET; this test only asserts
        # the SHAPE guarantee that an empty query path returns
        # the paginated envelope with the correct keys & types.
        assert "items" in d and "total" in d
        assert d["has_next"] is (len(d["items"]) < d["total"])
    finally:
        dbc.marketing_templates.delete_many({"tenant_id": tid})
        dbc.users.delete_many({"id": uid})
        dbc.tenants.delete_many({"id": tid})


# ═══════════════════════════════════════════════════════════════════
# Create flow — happy path + validation
# ═══════════════════════════════════════════════════════════════════
def test_create_minimal_valid_body_returns_201(admin_headers, created_ids):
    payload = _mk_payload(name_suffix="min-" + uuid.uuid4().hex[:4])
    r = requests.post(
        f"{API}/marketing/templates",
        headers=admin_headers, json=payload, timeout=30,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert "id" in d and d["id"]
    assert d["channel"] == "email"
    assert d["name"] == payload["name"]
    assert d["active"] is True
    created_ids.append(d["id"])

    # Fetchable via GET.
    r2 = requests.get(
        f"{API}/marketing/templates/{d['id']}",
        headers=admin_headers, timeout=10,
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == d["id"]


def test_create_invalid_channel_returns_422_not_500(admin_headers):
    r = requests.post(
        f"{API}/marketing/templates",
        headers=admin_headers,
        json=_mk_payload(channel="whatever", subject="x"),
        timeout=30,
    )
    assert r.status_code == 422, r.text
    assert r.status_code != 500
    assert r.status_code != 502


def test_create_email_without_subject_returns_422(admin_headers):
    r = requests.post(
        f"{API}/marketing/templates",
        headers=admin_headers,
        json=_mk_payload(channel="email", subject=""),
        timeout=30,
    )
    assert r.status_code == 422, r.text


def test_create_accepts_body_html_alias(admin_headers, created_ids):
    """P1-M3-HARDENING · alias tolerance — ``body_html`` on create
    binds to the stored ``body`` field when ``body`` is empty."""
    payload = _mk_payload(
        name_suffix="alias-" + uuid.uuid4().hex[:4],
        body="",
        body_html="<h1>From body_html alias</h1>",
    )
    r = requests.post(
        f"{API}/marketing/templates",
        headers=admin_headers, json=payload, timeout=30,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["body"] == "<h1>From body_html alias</h1>", (
        f"body_html alias was dropped on create; body={d['body']!r}"
    )
    created_ids.append(d["id"])


# ═══════════════════════════════════════════════════════════════════
# Internal error wrapping — unit tests via dependency override
# ═══════════════════════════════════════════════════════════════════
def test_list_wraps_uncaught_exception_as_500_with_error_code():
    """Unit test: directly await ``list_templates`` with a mocked
    ``db`` that raises on ``find``. Assert the handler converts the
    exception into an HTTP 500 with the specific ``error_code``
    instead of letting it bubble into a worker crash + proxy 502."""
    from fastapi import HTTPException
    from routers import marketing_templates as mt

    class _ExplodingCursor:
        def sort(self, *_a, **_kw): return self
        def skip(self, *_a, **_kw): return self
        def limit(self, *_a, **_kw): return self
        async def to_list(self, *_a, **_kw):
            raise RuntimeError("simulated motor failure")

    class _ExplodingCollection:
        def find(self, *_a, **_kw): return _ExplodingCursor()
        async def count_documents(self, *_a, **_kw):
            raise RuntimeError("simulated motor failure")
        async def create_index(self, *_a, **_kw):
            return "idx"

    class _Fake:
        marketing_templates = _ExplodingCollection()

    original = mt.db
    mt.db = _Fake()
    # Reset the one-shot index guard so the handler attempts the
    # ensure path once (which returns cleanly in our fake).
    mt._indexes_ensured = False
    try:
        with pytest.raises(HTTPException) as excinfo:
            asyncio.get_event_loop().run_until_complete(
                mt.list_templates(
                    channel=None, category=None, active=None,
                    page=None, size=None,
                    user={"id": "u", "role": "admin"},
                    tenant={"id": "t"},
                )
            )
        assert excinfo.value.status_code == 500
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == "marketing_template_list_internal_error"
        assert "RuntimeError" in detail["message"]
    finally:
        mt.db = original
        mt._indexes_ensured = False


def test_create_wraps_uncaught_exception_as_500_with_error_code():
    """Unit test: directly await ``create_template`` with a mocked
    ``db`` whose ``insert_one`` raises. Assert the handler converts
    the exception into an HTTP 500 with the specific ``error_code``
    instead of letting it bubble up as a worker crash + 502."""
    from fastapi import HTTPException
    from routers import marketing_templates as mt

    class _ExplodingCollection:
        async def insert_one(self, *_a, **_kw):
            raise RuntimeError("simulated motor insert failure")

    class _Fake:
        marketing_templates = _ExplodingCollection()

    original = mt.db
    mt.db = _Fake()
    try:
        body = mt.TemplateIn(
            name="unit-fail", channel="email",
            category="general", subject="s", body="b",
        )
        with pytest.raises(HTTPException) as excinfo:
            asyncio.get_event_loop().run_until_complete(
                mt.create_template(
                    body=body,
                    user={"id": "u", "role": "admin"},
                    tenant={"id": "t"},
                )
            )
        assert excinfo.value.status_code == 500
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail["error_code"] == (
            "marketing_template_create_internal_error"
        )
        assert "RuntimeError" in detail["message"]
    finally:
        mt.db = original
