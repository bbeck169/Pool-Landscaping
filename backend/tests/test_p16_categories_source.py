"""Phase P16 · Feb-2026 — Category source-of-truth contract.

Path A (chosen): the ``service_categories`` collection exists (its
router is already registered in ``server.py`` and it seeds a
per-tenant default set on first access). The master-service
``category`` field carries the category NAME (case-insensitive
match against ``service_categories.name``) so an unknown name is
rejected at write time.

Locked-in behaviour:
  1. POST with a KNOWN category name → 200; the stored ``category``
     is normalised to the canonical case from ``service_categories``.
  2. POST with an UNKNOWN category → 400 ``category_invalid``.
  3. POST with an empty / whitespace-only category → 400
     ``category_required``.
  4. PATCH swapping to an unknown category → 400 ``category_invalid``.
  5. GET /master-services/categories returns the tenant's active
     service categories name-only, sorted stable + no cross-tenant
     leak.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def admin_tid(dbc) -> str:
    u = dbc.users.find_one({"email": "admin@aquaterra.com"},
                            {"_id": 0, "tenant_id": 1})
    assert u and u.get("tenant_id"), "seed admin missing tenant_id"
    return u["tenant_id"]


@pytest.fixture(scope="module")
def known_category(dbc, admin_tid) -> str:
    row = dbc.service_categories.find_one(
        {"tenant_id": admin_tid, "is_archived": False},
        {"_id": 0, "name": 1},
    )
    assert row and row.get("name"), "seed tenant missing service categories"
    return row["name"]


@pytest.fixture(autouse=True)
def _scrub(dbc, admin_tid):
    """Purge any TEST-P16CS rows before + after each test so
    counts / dedup assertions stay deterministic."""
    dbc.pricebook.delete_many({"tenant_id": admin_tid,
                                 "name": {"$regex": "^TEST-P16CS "}})
    yield
    dbc.pricebook.delete_many({"tenant_id": admin_tid,
                                 "name": {"$regex": "^TEST-P16CS "}})


def _name(hint: str = "") -> str:
    return f"TEST-P16CS {hint or uuid.uuid4().hex[:8]}"


def _create(admin_h: dict, name: str, category: str) -> requests.Response:
    return requests.post(
        f"{API}/master-services", headers=admin_h,
        json={"name": name, "default_price": 100.0, "category": category},
        timeout=15,
    )


# ═════════════════════════════════════════════════════════════════════
# Acceptance 1 · Known category — 200, name normalised to canonical
# case.
# ═════════════════════════════════════════════════════════════════════
def test_create_with_known_category_returns_200_and_normalises_case(
    admin_h, known_category,
):
    # Type the same category with intentionally mixed-case so the
    # canonical case-normalisation assertion has teeth.
    typed = known_category.swapcase()
    r = _create(admin_h, _name("known-case"), typed)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == known_category


# ═════════════════════════════════════════════════════════════════════
# Acceptance 2 · Unknown category → 400 category_invalid
# ═════════════════════════════════════════════════════════════════════
def test_create_with_unknown_category_returns_400(admin_h):
    r = _create(admin_h, _name("unknown"),
                 f"P16-BOGUS-{uuid.uuid4().hex[:8]}")
    assert r.status_code == 400, r.text
    assert "category_invalid" in r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 3 · Empty / whitespace category → 400 validation
# ═════════════════════════════════════════════════════════════════════
def test_create_with_empty_category_returns_400(admin_h):
    # Empty string trips Pydantic min_length=1 → 422; whitespace-only
    # goes through Pydantic (non-empty) but our own validator
    # surfaces a ``category_required`` code.  Both are >= 400 with
    # a stable error signature the FE can key on.
    r1 = _create(admin_h, _name("empty"), "")
    assert r1.status_code in (400, 422), r1.text
    r2 = _create(admin_h, _name("blank"), "   ")
    assert r2.status_code == 400, r2.text
    assert "category_required" in r2.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 4 · PATCH swapping to unknown category → 400
# ═════════════════════════════════════════════════════════════════════
def test_patch_to_unknown_category_returns_400(admin_h, known_category):
    body = _create(admin_h, _name("patch-swap"), known_category).json()
    r = requests.patch(
        f"{API}/master-services/{body['id']}",
        headers=admin_h,
        json={"category": f"P16-BOGUS-{uuid.uuid4().hex[:8]}"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "category_invalid" in r.text


# ═════════════════════════════════════════════════════════════════════
# Acceptance 5 · GET /master-services/categories returns tenant's
# active categories (no cross-tenant leak).
# ═════════════════════════════════════════════════════════════════════
def test_categories_endpoint_returns_tenant_scoped_names(
    admin_h, admin_tid, dbc,
):
    # Seed a foreign-tenant service category so we can verify the
    # endpoint doesn't leak it.
    other_tid = f"TEST-p16-other-{uuid.uuid4().hex[:8]}"
    leak_name = f"P16-LEAK-{uuid.uuid4().hex[:8]}"
    dbc.tenants.insert_one({"id": other_tid, "name": "P16 Other",
                              "slug": f"p16-other-{other_tid}",
                              "active": True})
    dbc.service_categories.insert_one({
        "id": f"TEST-p16-cat-{uuid.uuid4().hex[:8]}",
        "tenant_id": other_tid,
        "name": leak_name,
        "is_archived": False,
        "sort_order": 0,
    })
    try:
        r = requests.get(f"{API}/master-services/categories",
                           headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        names = {row["name"] for row in r.json()["items"]}
        # Cross-tenant category NEVER surfaces.
        assert leak_name not in names
        # Tenant's own categories DO surface.
        own = list(dbc.service_categories.find(
            {"tenant_id": admin_tid, "is_archived": False},
            {"_id": 0, "name": 1},
        ))
        assert own, "seed tenant should have at least one active category"
        for c in own:
            assert c["name"] in names
    finally:
        dbc.service_categories.delete_many({"tenant_id": other_tid})
        dbc.tenants.delete_one({"id": other_tid})


# ═════════════════════════════════════════════════════════════════════
# Acceptance 6 · Archived categories DO NOT satisfy validation.
# ═════════════════════════════════════════════════════════════════════
def test_archived_category_is_rejected_at_write_time(
    admin_h, admin_tid, dbc,
):
    archived_name = f"P16-ARCHIVED-{uuid.uuid4().hex[:8]}"
    cat_id = f"TEST-p16-arch-{uuid.uuid4().hex[:8]}"
    dbc.service_categories.insert_one({
        "id": cat_id, "tenant_id": admin_tid,
        "name": archived_name, "is_archived": True,
        "sort_order": 0,
    })
    try:
        r = _create(admin_h, _name("archived"), archived_name)
        assert r.status_code == 400, r.text
        assert "category_invalid" in r.text
    finally:
        dbc.service_categories.delete_one({"id": cat_id})
