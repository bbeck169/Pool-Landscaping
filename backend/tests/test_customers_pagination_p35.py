"""Feb-2026 · P35 — customers list pagination.

The ``GET /api/customers`` endpoint gained an opt-in paginated envelope
when either ``page`` or ``page_size`` is supplied. Bare-array response
is preserved verbatim when neither is present (Strategy B — see the
router docstring). This suite pins the new contract and the guardrails.
"""
from __future__ import annotations

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


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_TAG = "TEST_p35_"


# ── auth ────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


# ── seeding ─────────────────────────────────────────────────────────
def _seed_customers(tid: str, n: int, *, is_active: bool = True) -> list[str]:
    """Insert ``n`` customers with deterministic, sortable names.

    Names are ``TEST_p35_active_0001 …`` so the endpoint's ``sort("name", 1)``
    yields a predictable order for slice assertions.
    """
    prefix = f"{_TAG}{'active' if is_active else 'inactive'}"
    ids = []
    docs = []
    for i in range(1, n + 1):
        cid = f"{prefix}_{uuid.uuid4().hex[:6]}_{i:04d}"
        ids.append(cid)
        docs.append({
            "id": cid, "tenant_id": tid,
            "name": f"{prefix}_{i:04d}",
            "is_active": is_active,
            "phone": "+15555550100", "email": f"{cid}@example.com",
            "address": "1 Test Way",
            "created_at": "2026-06-01T09:00:00+00:00",
        })
    _sync.customers.insert_many(docs)
    return ids


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
    _reset()
    yield
    _reset()


# ── contract pins ───────────────────────────────────────────────────
# Phase 15 · Feb-2026 — the Feb-2026 ``sort`` param now defaults to
# ``created_desc`` (newest first). Our seed inserts 250 rows in a
# tight loop so ``created_at`` ties are highly likely, which makes
# the row order non-deterministic. Pin ``sort=name_asc`` on every
# contract call so the ``_0001`` / ``_0250`` ordering guards still
# hold.
_SORT = "name_asc"


def test_page1_returns_first_100_and_envelope(admin_h, aquaterra_tid):
    _seed_customers(aquaterra_tid, 250, is_active=True)
    # Narrow the query to only the seeded rows so we're insulated from
    # other tenants' data on the shared aquaterra tenant.
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=1&page_size=100"
        f"&sort={_SORT}",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict), \
        "Paginated response must be an object, not a bare array"
    assert set(body.keys()) >= {
        "items", "total", "page", "page_size", "total_pages"}
    assert body["total"] == 250
    assert body["page"] == 1
    assert body["page_size"] == 100
    assert body["total_pages"] == 3
    assert len(body["items"]) == 100
    # First 100 sorted by name asc → names ending _0001 .. _0100.
    first_name = body["items"][0]["name"]
    assert first_name.endswith("_0001"), first_name
    last_name = body["items"][-1]["name"]
    assert last_name.endswith("_0100"), last_name


def test_page3_returns_last_50_rows(admin_h, aquaterra_tid):
    _seed_customers(aquaterra_tid, 250, is_active=True)
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=3&page_size=100"
        f"&sort={_SORT}",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 250
    assert body["page"] == 3
    assert body["total_pages"] == 3
    assert len(body["items"]) == 50
    assert body["items"][0]["name"].endswith("_0201")
    assert body["items"][-1]["name"].endswith("_0250")


def test_out_of_range_page_returns_empty_items_not_404(admin_h, aquaterra_tid):
    _seed_customers(aquaterra_tid, 250, is_active=True)
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=4&page_size=100",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 250
    assert body["page"] == 4
    assert body["total_pages"] == 3


def test_page_zero_returns_400(admin_h, aquaterra_tid):
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=0&page_size=100",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["detail"] == "invalid_page"


def test_page_size_over_cap_returns_400(admin_h, aquaterra_tid):
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=1&page_size=1000",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["detail"]["detail"] == "invalid_page_size"


def test_filter_and_pagination_compose(admin_h, aquaterra_tid):
    _seed_customers(aquaterra_tid, 30, is_active=True)
    _seed_customers(aquaterra_tid, 150, is_active=False)
    r = requests.get(
        (f"{API}/customers?search={_TAG}inactive"
          "&is_active=false&page=2&page_size=100"),
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 150
    assert body["page"] == 2
    assert body["total_pages"] == 2
    assert len(body["items"]) == 50
    # Every item must be inactive — filter honored under pagination.
    assert all(row.get("is_active") is False for row in body["items"])


def test_pagination_is_deterministic(admin_h, aquaterra_tid):
    _seed_customers(aquaterra_tid, 250, is_active=True)
    url = f"{API}/customers?search={_TAG}active&page=1&page_size=100"
    a = requests.get(url, headers=admin_h, timeout=20).json()
    b = requests.get(url, headers=admin_h, timeout=20).json()
    a_ids = [row["id"] for row in a["items"]]
    b_ids = [row["id"] for row in b["items"]]
    assert a_ids == b_ids, "Same page must return identical rows across requests"
    assert a["total"] == b["total"] == 250


def test_no_pagination_query_returns_legacy_bare_array(admin_h, aquaterra_tid):
    """Strategy B guardrail — bare-array callers untouched."""
    _seed_customers(aquaterra_tid, 5, is_active=True)
    r = requests.get(
        f"{API}/customers?search={_TAG}active",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list), (
        "Requests without page/page_size must keep returning a bare array. "
        f"Got {type(body).__name__}: {body!r:.200}")
    assert len(body) == 5


def test_count_only_still_uses_compact_shape(admin_h, aquaterra_tid):
    """P35 must not disturb the pre-existing ``count_only`` contract."""
    _seed_customers(aquaterra_tid, 8, is_active=True)
    r = requests.get(
        (f"{API}/customers?search={_TAG}active"
          "&is_active=true&count_only=true"),
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"count": 8}


def test_page_size_zero_returns_400(admin_h, aquaterra_tid):
    r = requests.get(
        f"{API}/customers?search={_TAG}active&page=1&page_size=0",
        headers=admin_h, timeout=20,
    )
    assert r.status_code == 400
    assert r.json()["detail"]["detail"] == "invalid_page_size"


def test_openapi_documents_pagination_params(admin_h):
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    spec = r.json()
    op = spec["paths"]["/api/customers"]["get"]
    names = {p["name"] for p in op.get("parameters", [])}
    assert {"page", "page_size"}.issubset(names)
