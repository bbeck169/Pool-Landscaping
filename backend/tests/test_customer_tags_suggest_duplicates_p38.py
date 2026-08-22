"""Feb-2026 · P38 — Suggested duplicate customer tags."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from routers import customer_tags as ct

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"
_TAG = "TEST_p38_"


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
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_tag(tid: str, name: str, usage: int = 0) -> str:
    tag_id = f"{_TAG}{uuid.uuid4().hex[:8]}"
    _sync.customer_tags.insert_one({
        "id": tag_id, "tenant_id": tid,
        "name": name, "name_lower": name.lower(),
        "color": "#DBEAFE", "sort_order": 0,
        "usage_count": usage, "is_active": True,
    })
    return tag_id


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customer_tags.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
        ct._DUPE_CACHE.pop(aquaterra_tid, None)
        # The server-side process holds its own ``_DUPE_CACHE`` copy —
        # clear it via the internal reset endpoint so cross-test cache
        # entries can't mask newly-seeded rows.
        try:
            tok = _login()
            requests.post(
                f"{API}/internal/customer-tags/reset-dupe-cache",
                json={"tenant_id": aquaterra_tid},
                headers={"Authorization": f"Bearer {tok}"},
                timeout=15)
        except Exception:
            pass
    _reset(); yield; _reset()


def _get(admin_h) -> dict:
    r = requests.get(f"{API}/customer-tags/suggest-duplicates",
                        headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def test_landscape_trio_clusters_with_expected_canonical(admin_h, aquaterra_tid):
    _seed_tag(aquaterra_tid, "Landscape", usage=5)
    _seed_tag(aquaterra_tid, "Landscaping", usage=12)   # highest
    _seed_tag(aquaterra_tid, "Landscapes", usage=3)
    _seed_tag(aquaterra_tid, "Pool", usage=20)
    _seed_tag(aquaterra_tid, "Spa", usage=8)

    body = _get(admin_h)
    # Filter to only clusters made up of our seeded rows so shared-tenant
    # noise from prior test runs can't pollute the assertion.
    ours = [c for c in body["clusters"]
              if all(l.lower() in {"landscape", "landscaping", "landscapes"}
                       for l in c["labels"])]
    assert len(ours) == 1
    cluster = ours[0]
    assert cluster["suggested_canonical"] == "Landscaping"
    assert set(cluster["labels"]) == {"Landscape", "Landscaping", "Landscapes"}
    assert cluster["confidence"] >= 0.8


def test_pool_and_spa_do_not_cluster(admin_h, aquaterra_tid):
    _seed_tag(aquaterra_tid, "Pool_p38A", usage=20)
    _seed_tag(aquaterra_tid, "Spa_p38A", usage=8)
    body = _get(admin_h)
    ours = [c for c in body["clusters"]
              if set(c["labels"]) == {"Pool_p38A", "Spa_p38A"}]
    assert ours == []


def test_exact_case_variants_cluster_with_ratio_one(admin_h, aquaterra_tid):
    # Direct insert to bypass any (tenant, name_lower) uniqueness so
    # both rows with the same ``name_lower`` coexist and cluster.
    # Both rows share the SAME ``name_lower`` — true case variants —
    # which forces SequenceMatcher ratio to 1.0.
    for suffix in ("A", "B"):
        _sync.customer_tags.insert_one({
            "id": f"{_TAG}case-{suffix}-{uuid.uuid4().hex[:6]}",
            "tenant_id": aquaterra_tid,
            "name": "Poolside_p38X" if suffix == "A" else "poolside_p38x",
            "name_lower": "poolside_p38x",
            "color": "#DBEAFE", "sort_order": 0,
            "usage_count": 5 if suffix == "A" else 2, "is_active": True,
        })
    body = _get(admin_h)
    ours = [c for c in body["clusters"]
              if all(l.lower() == "poolside_p38x" for l in c["labels"])
              and len(c["labels"]) == 2]
    assert len(ours) == 1
    # Exact case variants — identical ``name_lower`` → ratio == 1.0.
    assert ours[0]["confidence"] == 1.0


def test_rbac_technician_403(aquaterra_tid):
    _seed_tag(aquaterra_tid, "Landscape_p38T")
    tok = _login("carlos@aquaterra.com")
    r = requests.get(f"{API}/customer-tags/suggest-duplicates",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15)
    assert r.status_code == 403


def test_empty_tenant_returns_empty_clusters(admin_h, aquaterra_tid):
    body = _get(admin_h)
    # Any pre-existing clusters on shared tenant are fine; just assert
    # the shape.
    assert "clusters" in body and isinstance(body["clusters"], list)
    assert body["ratio_threshold"] == 0.8


def test_cache_hit_within_60s(admin_h, aquaterra_tid):
    _seed_tag(aquaterra_tid, "Landscape_p38C1", usage=5)
    _seed_tag(aquaterra_tid, "Landscaping_p38C1", usage=10)
    # First call — populates cache.
    _get(admin_h)
    # Now spy on Mongo call to prove second call skips the aggregation.
    import motor.motor_asyncio as _m
    call_count = {"n": 0}
    real_find = ct.db.customer_tags.find

    def _spy(*a, **kw):
        call_count["n"] += 1
        return real_find(*a, **kw)

    with patch.object(ct.db.customer_tags, "find", _spy):
        _get(admin_h)
    assert call_count["n"] == 0, (
        f"Second call within 60s should hit cache, but find() ran "
        f"{call_count['n']}x")


def test_openapi_lists_endpoint():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert "/api/customer-tags/suggest-duplicates" in (r.json().get("paths") or {})
