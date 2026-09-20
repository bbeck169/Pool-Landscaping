"""Feb-2026 · P44 — ``only_used`` filter on the customer-tags list."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

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
_TAG = "TEST_p44_"


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


def _mk_tag(tid: str, name: str, *, is_active: bool = True) -> str:
    tag_id = f"{_TAG}tag-{uuid.uuid4().hex[:8]}"
    _sync.customer_tags.insert_one({
        "id": tag_id, "tenant_id": tid,
        "name": name, "name_lower": name.lower(),
        "color": "#DBEAFE", "sort_order": 0,
        "usage_count": 0, "is_active": is_active,
    })
    return tag_id


def _mk_customer(tid: str, tags: list[str], *,
                    is_deleted: bool = False) -> str:
    cid = f"{_TAG}cust-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"P44 {cid}", "last_name": f"{_TAG}ln",
        "email": f"{cid.lower()}@ex.com", "phone": "",
        "tags": tags, "is_active": True,
    }
    if is_deleted:
        doc["deleted_at"] = "2026-02-06T00:00:00Z"
    _sync.customers.insert_one(doc)
    return cid


def _reset_cache(admin_h, tid: str):
    requests.post(
        f"{API}/internal/customer-tags/reset-usage-cache",
        json={"tenant_id": tid},
        headers=admin_h, timeout=10)


@pytest.fixture(autouse=True)
def _cleanup(admin_h, aquaterra_tid):
    def _reset():
        _sync.customer_tags.delete_many({
            "tenant_id": aquaterra_tid,
            "id": {"$regex": f"^{_TAG}"},
        })
        _sync.customers.delete_many({
            "tenant_id": aquaterra_tid,
            "id": {"$regex": f"^{_TAG}"},
        })
        _reset_cache(admin_h, aquaterra_tid)
    _reset(); yield; _reset()


def _fetch(admin_h, params: str = "") -> list[dict]:
    r = requests.get(f"{API}/customer-tags?{params}",
                        headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _my_names(rows: list[dict]) -> set[str]:
    return {r["name"] for r in rows if r["name"].startswith("p44_")}


# ── Core filter behavior ────────────────────────────────────────────
def test_only_used_returns_only_tags_in_use(admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_in_use_A")
    _mk_tag(aquaterra_tid, "p44_in_use_B")
    _mk_tag(aquaterra_tid, "p44_unused_C")
    _mk_tag(aquaterra_tid, "p44_unused_D")
    _mk_tag(aquaterra_tid, "p44_archived_E", is_active=False)
    _mk_customer(aquaterra_tid, ["p44_in_use_A"])
    _mk_customer(aquaterra_tid, ["p44_in_use_B"])
    _mk_customer(aquaterra_tid, ["p44_in_use_A", "p44_in_use_B"])

    rows = _fetch(admin_h, "only_used=true")
    got = _my_names(rows)
    assert got == {"p44_in_use_A", "p44_in_use_B"}


def test_default_off_returns_all_active_tags(admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_in_use_A")
    _mk_tag(aquaterra_tid, "p44_unused_C")
    _mk_tag(aquaterra_tid, "p44_unused_D")
    _mk_tag(aquaterra_tid, "p44_archived_E", is_active=False)
    _mk_customer(aquaterra_tid, ["p44_in_use_A"])

    rows = _fetch(admin_h)
    got = _my_names(rows)
    # All active regardless of usage; archived still excluded.
    assert got == {"p44_in_use_A", "p44_unused_C", "p44_unused_D"}


def test_include_inactive_composes_with_only_used(
        admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_in_use_A")
    _mk_tag(aquaterra_tid, "p44_archived_used_F", is_active=False)
    _mk_tag(aquaterra_tid, "p44_archived_unused_G", is_active=False)
    _mk_customer(aquaterra_tid, ["p44_in_use_A"])
    _mk_customer(aquaterra_tid, ["p44_archived_used_F"])
    _reset_cache(admin_h, aquaterra_tid)

    rows = _fetch(admin_h, "only_used=true&include_inactive=true")
    got = _my_names(rows)
    # Both active + archived rows appear IFF they're currently in use.
    assert got == {"p44_in_use_A", "p44_archived_used_F"}


# ── Case-insensitive match ─────────────────────────────────────────
def test_case_insensitive_usage_match(admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_in_use_A")   # catalog stores "A"
    _mk_customer(aquaterra_tid, ["p44_in_use_a"])  # customer stores "a"
    _reset_cache(admin_h, aquaterra_tid)

    rows = _fetch(admin_h, "only_used=true")
    got = _my_names(rows)
    assert "p44_in_use_A" in got


# ── Soft-deleted customer's tags don't count ────────────────────────
def test_soft_deleted_customer_tags_ignored(admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_phantom")
    _mk_customer(aquaterra_tid, ["p44_phantom"], is_deleted=True)
    _reset_cache(admin_h, aquaterra_tid)

    rows = _fetch(admin_h, "only_used=true")
    got = _my_names(rows)
    assert "p44_phantom" not in got


# ── Whitespace-only tag strings ignored ─────────────────────────────
def test_whitespace_only_tag_strings_do_not_count(
        admin_h, aquaterra_tid):
    _mk_tag(aquaterra_tid, "p44_in_use_A")
    _mk_customer(aquaterra_tid, ["   ", "\t\n", "p44_in_use_A"])
    _reset_cache(admin_h, aquaterra_tid)

    rows = _fetch(admin_h, "only_used=true")
    got = _my_names(rows)
    assert got == {"p44_in_use_A"}


# ── Cache hit / TTL ─────────────────────────────────────────────────
def test_cache_hit_within_60s(admin_h, aquaterra_tid):
    """Two rapid calls should distinct-query customers only once.
    Spy on the in-process motor collection via ``patch.object`` — the
    live server holds the cache, so we exercise the cache path by
    priming, mutating the collection out-of-band, and asserting the
    2nd read still sees the stale set."""
    _mk_tag(aquaterra_tid, "p44_in_use_A")
    _mk_customer(aquaterra_tid, ["p44_in_use_A"])
    _reset_cache(admin_h, aquaterra_tid)

    # Prime.
    first = _fetch(admin_h, "only_used=true")
    assert "p44_in_use_A" in _my_names(first)

    # Add a new usage out-of-band; the cache should hide it until reset.
    _mk_tag(aquaterra_tid, "p44_in_use_B")
    _mk_customer(aquaterra_tid, ["p44_in_use_B"])
    stale = _fetch(admin_h, "only_used=true")
    assert "p44_in_use_B" not in _my_names(stale), (
        "cache should have hidden the new usage until reset")

    # Explicit reset → the new usage is now visible.
    _reset_cache(admin_h, aquaterra_tid)
    fresh = _fetch(admin_h, "only_used=true")
    assert "p44_in_use_B" in _my_names(fresh)


# ── RBAC on reset endpoint ─────────────────────────────────────────
def test_reset_endpoint_rbac_technician_403():
    tok = _login("carlos@aquaterra.com")
    r = requests.post(
        f"{API}/internal/customer-tags/reset-usage-cache",
        json={},
        headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 403
