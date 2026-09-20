"""Feb-2026 · P46 — multi-tag + city server-side filters, and the
manager-role-gate regression pin."""
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
_TAG = "TEST_p46_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _mk(tid: str, tags: list[str], *,
           service_city: str | None = None,
           billing_city: str | None = None,
           address: str | None = None) -> str:
    cid = f"{_TAG}c-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"P46 {cid}", "last_name": f"{_TAG}ln",
        "email": f"{cid.lower()}@ex.com", "phone": "",
        "tags": tags, "is_active": True,
    }
    if service_city is not None: doc["service_city"] = service_city
    if billing_city is not None: doc["billing_city"] = billing_city
    if address is not None: doc["address"] = address
    _sync.customers.insert_one(doc)
    return cid


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many({
            "tenant_id": aquaterra_tid,
            "id": {"$regex": f"^{_TAG}"},
        })
    _reset(); yield; _reset()


def _fetch(admin_h, q: str) -> dict:
    r = requests.get(f"{API}/customers?is_active=true&{q}",
                        headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mine(items):
    return [c for c in items
              if (c.get("last_name") or "").startswith(_TAG)]


# ── Multi-tag AND ───────────────────────────────────────────────────
def test_multi_tag_and_intersects(admin_h, aquaterra_tid):
    both = _mk(aquaterra_tid, ["Pool", "Landscaping"])
    only_pool = _mk(aquaterra_tid, ["Pool"])
    only_land = _mk(aquaterra_tid, ["Landscaping"])
    neither = _mk(aquaterra_tid, ["Other"])
    body = _fetch(admin_h,
                     "tags=Pool&tags=Landscaping&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert both in ids
    assert only_pool not in ids
    assert only_land not in ids
    assert neither not in ids


def test_single_tag_backwards_compat(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, ["Pool"])
    b = _mk(aquaterra_tid, ["Landscaping"])
    body = _fetch(admin_h, "tag=Pool&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids and b not in ids


def test_plural_wins_when_both_provided(admin_h, aquaterra_tid):
    # ``tag=Pool`` alone would match; plural ``tags=Landscaping``
    # takes precedence and forces the row to have Landscaping.
    a = _mk(aquaterra_tid, ["Pool"])                # only Pool
    b = _mk(aquaterra_tid, ["Pool", "Landscaping"]) # both
    body = _fetch(admin_h,
                     "tag=Pool&tags=Landscaping&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert b in ids
    assert a not in ids


def test_empty_tag_values_are_stripped(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, ["Pool"])
    # Simulate a URL like ``?tags=&tags=Pool`` — the empty entry
    # must not accidentally $all-match ``""`` (which would return
    # zero rows).
    body = _fetch(admin_h, "tags=&tags=Pool&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids


# ── City filter — regex across 3 fields ─────────────────────────────
def test_city_matches_service_city(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, [], service_city="Phoenix")
    b = _mk(aquaterra_tid, [], service_city="Tempe")
    body = _fetch(admin_h, "city=Phoenix&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids and b not in ids


def test_city_matches_billing_city(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, [], billing_city="Scottsdale")
    body = _fetch(admin_h, "city=Scottsdale&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids


def test_city_matches_legacy_address_field(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, [], address="42 Elm, Mesa, AZ 85201")
    body = _fetch(admin_h, "city=Mesa&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids


def test_city_case_insensitive(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, [], service_city="Phoenix")
    body = _fetch(admin_h, "city=phoenix&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids


def test_city_regex_metacharacters_are_escaped(admin_h, aquaterra_tid):
    # A city containing "." should not be interpreted as regex "any-
    # char". Seed a Foo.Bar row and a FooXBar row; ``city=Foo.Bar``
    # must match only the literal.
    good = _mk(aquaterra_tid, [], service_city="Foo.Bar")
    trap = _mk(aquaterra_tid, [], service_city="FooXBar")
    body = _fetch(admin_h, "city=Foo.Bar&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert good in ids
    assert trap not in ids


# ── Compose city + tags ────────────────────────────────────────────
def test_city_and_tags_compose(admin_h, aquaterra_tid):
    a = _mk(aquaterra_tid, ["Pool"], service_city="Phoenix")
    b = _mk(aquaterra_tid, ["Pool"], service_city="Tempe")
    c = _mk(aquaterra_tid, ["Other"], service_city="Phoenix")
    body = _fetch(admin_h,
                     "tags=Pool&city=Phoenix&page=1&page_size=500")
    ids = {c["id"] for c in _mine(body["items"])}
    assert a in ids
    assert b not in ids
    assert c not in ids


# ── count_only honors both (P40 unified-predicate contract) ────────
def test_count_only_matches_paginated_total_for_multi_tag(
        admin_h, aquaterra_tid):
    _mk(aquaterra_tid, ["Pool", "Landscaping"])
    _mk(aquaterra_tid, ["Pool", "Landscaping"])
    _mk(aquaterra_tid, ["Pool"])
    _mk(aquaterra_tid, ["Landscaping"])
    body = _fetch(admin_h,
                     "tags=Pool&tags=Landscaping&page=1&page_size=500")
    my_list_ct = len(_mine(body["items"]))
    ct = _fetch(admin_h,
                    "tags=Pool&tags=Landscaping&count_only=true")
    # The count_only branch spans all rows on this tenant, so the
    # global count is >= our tenant-scoped seeded count.
    assert ct["count"] >= my_list_ct == 2


def test_count_only_matches_paginated_total_for_city(
        admin_h, aquaterra_tid):
    _mk(aquaterra_tid, [], service_city="Chandler")
    body = _fetch(admin_h, "city=Chandler&page=1&page_size=500")
    ct = _fetch(admin_h, "city=Chandler&count_only=true")
    assert ct["count"] >= len(_mine(body["items"])) >= 1


# ── Pagination compatibility on page 2 ─────────────────────────────
def test_pagination_page_2_still_filters(admin_h, aquaterra_tid):
    # Use a P46-unique tag so paging is scoped to exactly our seeds.
    unique_tag = f"{_TAG}pool_only_{uuid.uuid4().hex[:6]}"
    for _ in range(6):
        _mk(aquaterra_tid, [unique_tag])
    p1 = _fetch(admin_h, f"tags={unique_tag}&page=1&page_size=3")
    p2 = _fetch(admin_h, f"tags={unique_tag}&page=2&page_size=3")
    all_ids = {c["id"] for c in p1["items"] + p2["items"]}
    assert len(all_ids) == 6, (
        "6 seeded rows should be reachable across page 1+2")
    # And every returned row carries the tag.
    for c in p1["items"] + p2["items"]:
        assert unique_tag in (c.get("tags") or [])
    assert p1["total"] == 6 and p2["total"] == 6


# ── Tenant scoping ─────────────────────────────────────────────────
def test_tenant_scoping_blocks_cross_tenant_leak(
        admin_h, aquaterra_tid):
    other = _sync.users.find_one(
        {"tenant_id": {"$ne": aquaterra_tid}}, {"_id": 0, "tenant_id": 1})
    other_tid = (other or {}).get("tenant_id") or "TENANT_p46_other"
    other_id = _mk(other_tid, ["Pool"], service_city="Phoenix")
    try:
        body = _fetch(admin_h,
                         "tags=Pool&city=Phoenix&page=1&page_size=500")
        ids = {c["id"] for c in body["items"]}
        assert other_id not in ids
    finally:
        _sync.customers.delete_one({"id": other_id})


# ── Manager role gate (regression pin) ─────────────────────────────
def test_manager_role_gets_200_from_list(admin_h, aquaterra_tid):
    # Create/find a manager user on the tenant. If one already exists
    # in test seed data we prefer to reuse them; otherwise seed one.
    from utils import hash_password as _hp
    mgr_email = f"{_TAG.lower()}mgr@ex.com"
    _sync.users.delete_many({"email": mgr_email})
    _sync.users.insert_one({
        "id": f"{_TAG}mgr-user", "tenant_id": aquaterra_tid,
        "email": mgr_email, "role": "manager",
        "password_hash": _hp("mgrpw123"),
        "is_active": True,
    })
    try:
        r = requests.post(f"{API}/auth/login",
                             json={"email": mgr_email,
                                      "password": "mgrpw123"}, timeout=15)
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
        # Pre-fix behavior: 403. Post-fix: 200 with an envelope.
        body = requests.get(
            f"{API}/customers?is_active=true&page=1&page_size=10",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert body.status_code == 200, body.text
        assert "items" in body.json()
    finally:
        _sync.users.delete_many({"email": mgr_email})
