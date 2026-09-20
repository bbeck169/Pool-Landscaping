"""Phase 15b · Feb-2026 — customer tag registry test suite.

Invariants exercised:

* Create a tag as admin → 200 + persisted row.
* Duplicate name (case-insensitive, trimmed) → returns existing row,
  no new insert.
* Invalid names (too long, whitespace-only, leading whitespace,
  trailing whitespace) → 400.
* PATCH customer tags with a name absent from the registry →
  auto-creates via the same idempotent path.
* Role gate — tech + customer → 403 on create + list + patch.
* Manager can list + create + patch (admin/manager allowed).
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


_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():   return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers(): return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def customer_headers(): return _login("customer@aquaterra.com")


@pytest.fixture(autouse=True)
def _isolate():
    """Clear scratch tag rows between tests so uniqueness checks don't
    contaminate. Custom names use the `phase15b-` prefix so we never
    disturb real production data (there shouldn't be any post-wipe)."""
    _sync.customer_tags.delete_many({
        "tenant_id": _TENANT_ID,
        "name_lower": {"$regex": "^phase15b-"},
    })
    yield
    _sync.customer_tags.delete_many({
        "tenant_id": _TENANT_ID,
        "name_lower": {"$regex": "^phase15b-"},
    })


@pytest.fixture
def scratch_customer():
    marker = uuid.uuid4().hex[:8]
    doc = {
        "id": f"phase15b-cust-{marker}",
        "tenant_id": _TENANT_ID,
        "name": f"Phase15b Customer {marker}",
        "email": "", "phone": "",
        "is_active": True,
        "tags": [],
    }
    _sync.customers.insert_one(doc)
    try:
        yield doc["id"]
    finally:
        _sync.customers.delete_one({"id": doc["id"]})


# ═════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════
def test_list_open_to_technician_but_customer_still_forbidden(
    tech_headers, customer_headers,
):
    """Feb-2026 · P33 — GET was widened from admin/manager to ANY
    authenticated staff (needed by row-form pickers + the list-page
    "All tags" filter). Technician now 200s. Customer role still
    hits the tenant-scoping wall and 4xx's."""
    r_tech = requests.get(f"{API}/customer-tags",
                              headers=tech_headers, timeout=10)
    assert r_tech.status_code == 200, r_tech.text

    r_cust = requests.get(f"{API}/customer-tags",
                              headers=customer_headers, timeout=10)
    assert r_cust.status_code in (401, 403), r_cust.text


def test_create_forbidden_for_non_admin_non_manager(tech_headers, customer_headers):
    for hdrs in (tech_headers, customer_headers):
        r = requests.post(f"{API}/customer-tags",
                          json={"name": "phase15b-nope"},
                          headers=hdrs, timeout=10)
        assert r.status_code == 403


def test_patch_customer_tags_forbidden_for_non_admin_non_manager(
        tech_headers, customer_headers, scratch_customer):
    for hdrs in (tech_headers, customer_headers):
        r = requests.patch(f"{API}/customers/{scratch_customer}/tags",
                            json={"tags": ["phase15b-nope"]},
                            headers=hdrs, timeout=10)
        assert r.status_code == 403


def test_manager_can_create_and_list(manager_headers):
    r = requests.post(f"{API}/customer-tags",
                       json={"name": "phase15b-manager"},
                       headers=manager_headers, timeout=10)
    assert r.status_code == 200, r.text
    lst = requests.get(f"{API}/customer-tags",
                        headers=manager_headers, timeout=10).json()
    assert any(t["name"] == "phase15b-manager" for t in lst["items"])


# ═════════════════════════════════════════════════════════════════
# Idempotent create
# ═════════════════════════════════════════════════════════════════
def test_admin_can_create_tag(admin_headers):
    r = requests.post(f"{API}/customer-tags",
                       json={"name": "phase15b-VIP", "color": "#FFEECC"},
                       headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "phase15b-VIP"
    assert body["color"] == "#FFEECC"
    assert body["usage_count"] == 0
    row = _sync.customer_tags.find_one({"id": body["id"]})
    assert row is not None


def test_duplicate_name_is_case_insensitive_and_returns_existing(admin_headers):
    r1 = requests.post(f"{API}/customer-tags",
                        json={"name": "phase15b-Repeat"},
                        headers=admin_headers, timeout=10).json()
    # Re-create with alternate casing → must return the SAME row.
    r2 = requests.post(f"{API}/customer-tags",
                        json={"name": "phase15b-REPEAT"},
                        headers=admin_headers, timeout=10).json()
    assert r1["id"] == r2["id"], "same tag id must be returned"
    n = _sync.customer_tags.count_documents({
        "tenant_id": _TENANT_ID, "name_lower": "phase15b-repeat",
    })
    assert n == 1, "must not insert a duplicate row"


# ═════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad_name", [
    "   ",                          # whitespace-only
    " phase15b-leading",            # leading whitespace
    "phase15b-trailing ",           # trailing whitespace
    "phase15b-" + "x" * 40,         # 47 chars — over the 40-char cap
])
def test_invalid_name_rejected(admin_headers, bad_name):
    r = requests.post(f"{API}/customer-tags",
                       json={"name": bad_name},
                       headers=admin_headers, timeout=10)
    assert r.status_code == 400, f"expected 400 for {bad_name!r}, got {r.status_code}"


# ═════════════════════════════════════════════════════════════════
# PATCH auto-creates missing registry entries
# ═════════════════════════════════════════════════════════════════
def test_patch_customer_tags_auto_creates_unknown_names(
        admin_headers, scratch_customer):
    novel = f"phase15b-auto-{uuid.uuid4().hex[:6]}"
    # Ensure the tag doesn't already exist.
    assert _sync.customer_tags.count_documents(
        {"tenant_id": _TENANT_ID, "name_lower": novel.lower()}
    ) == 0

    r = requests.patch(f"{API}/customers/{scratch_customer}/tags",
                        json={"tags": [novel, "phase15b-VIP"]},
                        headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["tags"] == [novel, "phase15b-VIP"]

    # Registry entry now exists.
    row = _sync.customer_tags.find_one({
        "tenant_id": _TENANT_ID, "name_lower": novel.lower(),
    })
    assert row is not None, "PATCH must auto-create the registry entry"

    # Customer doc actually carries the tags.
    cust = _sync.customers.find_one({"id": scratch_customer})
    assert cust["tags"] == [novel, "phase15b-VIP"]


def test_patch_customer_tags_deduplicates_case_insensitively(
        admin_headers, scratch_customer):
    """Two tags differing only by case must collapse to one entry
    (first-writer wins ordering)."""
    r = requests.patch(f"{API}/customers/{scratch_customer}/tags",
                        json={"tags": ["phase15b-Dup", "phase15b-DUP",
                                        "phase15b-Other"]},
                        headers=admin_headers, timeout=10)
    assert r.status_code == 200, r.text
    tags = r.json()["tags"]
    # Case-insensitive de-dupe preserves the first form written.
    lows = [t.lower() for t in tags]
    assert lows == ["phase15b-dup", "phase15b-other"]


def test_patch_customer_tags_recomputes_usage_count(
        admin_headers, scratch_customer):
    # Baseline — usage_count for a brand-new tag is 0.
    r0 = requests.post(f"{API}/customer-tags",
                        json={"name": "phase15b-Usage"},
                        headers=admin_headers, timeout=10).json()
    assert r0["usage_count"] == 0

    requests.patch(f"{API}/customers/{scratch_customer}/tags",
                    json={"tags": ["phase15b-Usage"]},
                    headers=admin_headers, timeout=10)

    row = _sync.customer_tags.find_one({"id": r0["id"]})
    assert row["usage_count"] == 1
