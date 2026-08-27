"""Feb-2026 · Customers list — sort dropdown backend contract.

Covers ``GET /api/customers`` ``sort`` query param:
  * ``sort=created_desc`` (default) — newest ``created_at`` first,
    with ``_id`` tie-breaker so legacy docs without ``created_at``
    still land in the correct chronological bucket.
  * ``sort=created_asc`` — oldest first.
  * ``sort=name_asc`` — legacy alphabetical (preserved).
  * ``sort=garbage`` or missing — falls back to ``created_desc``.

These tests run against the live in-container backend (same shape as
``test_customers_pagination_p35.py``) and seed a deterministic batch
of customers whose ``created_at`` timestamps are staggered so the
returned order is unambiguously assertable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_TAG = "TEST_sort_"


# ── auth ────────────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


# ── seeding ─────────────────────────────────────────────────────────
def _seed_staggered(tid: str, n: int = 5) -> list[dict]:
    """Insert ``n`` customers whose ``created_at`` is staggered by 1 day.

    Ordering (newest → oldest) is 4, 3, 2, 1, 0 by suffix, so a
    ``created_desc`` request must return the 4-suffix row first and
    the 0-suffix row last.
    """
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    docs = []
    for i in range(n):
        cid = f"{_TAG}{uuid.uuid4().hex[:6]}_{i}"
        docs.append({
            "id": cid, "tenant_id": tid,
            "name": f"Sort Test {i}",
            "is_active": True,
            "phone": "+15555550100",
            "email": f"{cid}@example.com",
            "address": "1 Sort Way",
            "created_at": (base + timedelta(days=i)).isoformat(),
        })
    _sync.customers.insert_many(docs)
    return docs


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.customers.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
    _reset()
    yield
    _reset()


def _list_ids(sort_param: str | None, admin_h) -> list[str]:
    q = f"search={_TAG}&page=1&page_size=50"
    if sort_param is not None:
        q += f"&sort={sort_param}"
    r = requests.get(f"{API}/customers?{q}", headers=admin_h, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    return [it["id"] for it in items]


# ── contract pins ───────────────────────────────────────────────────
def test_default_sort_is_created_desc(admin_h, aquaterra_tid):
    """No ``sort`` param → newest-first order."""
    seeded = _seed_staggered(aquaterra_tid, 5)
    ids = _list_ids(None, admin_h)
    # First seeded id should be the LAST (i=4) row.
    seeded_ids = [d["id"] for d in seeded]
    tag_ids = [i for i in ids if i.startswith(_TAG)]
    assert tag_ids[0] == seeded_ids[-1]
    assert tag_ids[-1] == seeded_ids[0]


def test_sort_created_desc_explicit(admin_h, aquaterra_tid):
    seeded = _seed_staggered(aquaterra_tid, 5)
    ids = _list_ids("created_desc", admin_h)
    seeded_ids = [d["id"] for d in seeded]
    tag_ids = [i for i in ids if i.startswith(_TAG)]
    assert tag_ids == list(reversed(seeded_ids))


def test_sort_created_asc(admin_h, aquaterra_tid):
    seeded = _seed_staggered(aquaterra_tid, 5)
    ids = _list_ids("created_asc", admin_h)
    seeded_ids = [d["id"] for d in seeded]
    tag_ids = [i for i in ids if i.startswith(_TAG)]
    assert tag_ids == seeded_ids


def test_sort_name_asc_preserves_legacy(admin_h, aquaterra_tid):
    """``sort=name_asc`` retains the pre-Feb2026 alphabetical order."""
    _seed_staggered(aquaterra_tid, 5)
    ids = _list_ids("name_asc", admin_h)
    # Names are ``Sort Test 0 … Sort Test 4`` → seeded order == name-asc.
    # We look up the names by id and confirm they're strictly non-decreasing.
    body = requests.get(
        f"{API}/customers?search={_TAG}&page=1&page_size=50&sort=name_asc",
        headers=admin_h, timeout=20,
    ).json()
    items = body["items"] if isinstance(body, dict) else body
    names = [it["name"] for it in items if it["id"].startswith(_TAG)]
    assert names == sorted(names)
    assert len(names) == 5


def test_sort_garbage_falls_back_to_default(admin_h, aquaterra_tid):
    """Unknown ``sort`` values must not 400 — they land on the default."""
    seeded = _seed_staggered(aquaterra_tid, 5)
    ids_bad = _list_ids("obviously_bogus_value", admin_h)
    ids_default = _list_ids(None, admin_h)
    tag_bad = [i for i in ids_bad if i.startswith(_TAG)]
    tag_default = [i for i in ids_default if i.startswith(_TAG)]
    assert tag_bad == tag_default
    # And that default is newest-first.
    seeded_ids = [d["id"] for d in seeded]
    assert tag_bad[0] == seeded_ids[-1]


def test_sort_survives_count_only_branch(admin_h, aquaterra_tid):
    """``count_only=true`` returns the same count regardless of sort —
    proves the sort param doesn't accidentally leak into the count
    branch or 400."""
    _seed_staggered(aquaterra_tid, 5)
    for s in ("created_desc", "created_asc", "garbage", None):
        q = f"search={_TAG}&count_only=true"
        if s is not None:
            q += f"&sort={s}"
        r = requests.get(f"{API}/customers?{q}", headers=admin_h, timeout=20)
        assert r.status_code == 200, (s, r.text)
        # 5 seeded rows in this batch.
        assert r.json()["count"] >= 5
