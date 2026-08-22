"""Feb-2026 · P33h — Lazy self-heal top-up on GET /api/customer-tags.

Bug from prod: catalog empty because P33 seed migration was never
run; distinct tags on ``customers.tags`` never landed in the picker.
Contract: on every GET, aggregate distinct customer tag strings and
insert any that are missing from the catalog (case-insensitive dedup,
respects archived rows, whitespace skipped, rate-limited per tenant).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _hdrs(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def admin_h(): return _hdrs("admin@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_cust_with_tags(tid: str, tags: list) -> str:
    cid = f"TEST_p33h_c_{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid,
        "name": f"P33H {uuid.uuid4().hex[:6]}",
        "email": f"{cid}@example.com", "phone": "6235550100",
        "address": "1 Test St", "tags": list(tags),
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    return cid


def _reset_rate_limit(tid: str) -> None:
    """Hit an internal reset endpoint so the backend process clears
    its per-tenant self-heal window. Tests share the running server."""
    try:
        requests.post(
            f"{API}/internal/customer-tags/reset-self-heal",
            headers=_hdrs("admin@aquaterra.com"),
            json={"tenant_id": tid}, timeout=5,
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": "^TEST_p33h_"}})
        _sync.customer_tags.delete_many(
            {"tenant_id": aquaterra_tid,
              "name_lower": {"$regex": "^selfheal|^p33h|^whitespace"}})
        _reset_rate_limit(aquaterra_tid)
    _reset()
    yield
    _reset()


def test_self_heal_inserts_missing_tags(admin_h, aquaterra_tid):
    _seed_cust_with_tags(aquaterra_tid,
                              ["SelfHeal Test A", "SelfHeal Test B"])
    _seed_cust_with_tags(aquaterra_tid, ["SelfHeal Test C"])
    r = requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert r.status_code == 200
    names = {t["name"] for t in r.json()["items"]}
    for want in ("SelfHeal Test A", "SelfHeal Test B", "SelfHeal Test C"):
        assert want in names
    # Every inserted row is auto_created + is_active.
    for want in ("SelfHeal Test A", "SelfHeal Test B", "SelfHeal Test C"):
        row = _sync.customer_tags.find_one(
            {"tenant_id": aquaterra_tid, "name_lower": want.lower()})
        assert row is not None
        assert row["auto_created"] is True
        assert row["is_active"] is True


def test_self_heal_is_idempotent_case_insensitive(admin_h, aquaterra_tid):
    _seed_cust_with_tags(aquaterra_tid, ["SelfHeal Test A"])
    _seed_cust_with_tags(aquaterra_tid, ["selfheal test a"])  # case variant
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    n = _sync.customer_tags.count_documents(
        {"tenant_id": aquaterra_tid, "name_lower": "selfheal test a"})
    assert n == 1, "case-variant tag must produce exactly one catalog row"


def test_self_heal_does_not_reactivate_archived(admin_h, aquaterra_tid):
    _seed_cust_with_tags(aquaterra_tid, ["SelfHeal Archived"])
    # Pre-seed an archived catalog row matching the customer tag.
    _sync.customer_tags.insert_one({
        "id": f"TEST_p33h_t_{uuid.uuid4().hex[:8]}",
        "tenant_id": aquaterra_tid,
        "name": "SelfHeal Archived", "name_lower": "selfheal archived",
        "color": "#0EA5E9", "is_system": False,
        "created_at": "2026-01-01T00:00:00Z", "created_by": "seed",
        "is_active": False, "auto_created": False, "sort_order": 5,
        "archived_at": "2026-02-01T00:00:00Z", "archived_by": "admin",
    })
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    rows = list(_sync.customer_tags.find(
        {"tenant_id": aquaterra_tid, "name_lower": "selfheal archived"}))
    assert len(rows) == 1
    assert rows[0]["is_active"] is False, \
        "self-heal must NOT reactivate an archived tag (P36 refinement #1)"


def test_self_heal_skips_whitespace(admin_h, aquaterra_tid):
    _seed_cust_with_tags(aquaterra_tid, ["   ", "\t\n", ""])
    baseline = _sync.customer_tags.count_documents({"tenant_id": aquaterra_tid})
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    after = _sync.customer_tags.count_documents({"tenant_id": aquaterra_tid})
    assert after == baseline, "whitespace-only tags must NOT create catalog rows"


def test_self_heal_rate_limit_per_tenant(admin_h, aquaterra_tid):
    """Rate limit is DB-observable: a within-window second GET must
    NOT re-insert a row that the test deleted between the two calls."""
    _seed_cust_with_tags(aquaterra_tid, ["SelfHeal Rate A"])
    # First call heals — the row lands.
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert _sync.customer_tags.count_documents(
        {"tenant_id": aquaterra_tid,
          "name_lower": "selfheal rate a"}) == 1

    # Delete the row so we can prove the second GET does NOT re-insert.
    _sync.customer_tags.delete_many(
        {"tenant_id": aquaterra_tid, "name_lower": "selfheal rate a"})

    # Second call within the 5-min window — rate limit must skip the
    # aggregate, so the deleted row stays deleted.
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert _sync.customer_tags.count_documents(
        {"tenant_id": aquaterra_tid,
          "name_lower": "selfheal rate a"}) == 0, \
        "self-heal must not re-run within the per-tenant window"

    # After a reset, the aggregate runs again and re-inserts.
    _reset_rate_limit(aquaterra_tid)
    requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert _sync.customer_tags.count_documents(
        {"tenant_id": aquaterra_tid,
          "name_lower": "selfheal rate a"}) == 1


def test_self_heal_does_not_500_when_aggregate_fails(admin_h, aquaterra_tid,
                                                              monkeypatch):
    """Injects a failure into the helper and asserts the GET still 200s."""
    from routers import customer_tags as _c
    _reset_rate_limit(aquaterra_tid)
    async def _boom(tid: str):
        raise RuntimeError("simulated aggregate failure")
    monkeypatch.setattr(_c, "_self_heal_catalog", _boom)
    r = requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
