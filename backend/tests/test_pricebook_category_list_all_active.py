"""Pricebook Category UX fixes · Feb-2026 — Task B.

Backend verification that ``GET /service-categories`` returns the
FULL active-category list for a tenant with no implicit server
limit (the previous 12-row client-side truncation lived in
``CategoryComboCell``; this test guards the server contract that
powers the new native-<select> inline cell).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    for _ in range(3):
        try:
            r = requests.post(
                f"{API}/auth/login",
                json={"email": email, "password": "password123"},
                timeout=30,
            )
            if r.status_code == 200:
                _CACHE[key] = r.json()["access_token"]
                return _CACHE[key]
        except requests.exceptions.RequestException:
            continue
    raise RuntimeError(f"login failed for {email}")


def _seed_tenant():
    tid = f"TEST-cat-list-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({"id": tid,
                             "slug": f"test-cat-list-{uuid.uuid4().hex[:6]}",
                             "name": "TEST_cat_list", "active": True})
    return tid


def _seed_admin(tid):
    from utils import hash_password
    uid = f"TEST-cat-u-{uuid.uuid4().hex[:6]}"
    email = f"cat-list-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_cat_list_admin", "role": "admin",
        "password_hash": hash_password("password123"),
    })
    return uid, email, _login(email)


def _cleanup(tid, uid, email):
    _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.service_categories.delete_many({"tenant_id": tid})
    _CACHE.pop(f"tok:{email}", None)


def test_service_categories_returns_all_active_with_no_implicit_limit():
    """Seed >30 active service categories for a tenant and assert
    that ``GET /service-categories`` returns every single one in a
    single call. If a later refactor reintroduces a client-side
    picker limit (e.g. ``limit=25``) or a server-side pagination
    default < 30, this test fails loudly.
    """
    tid = _seed_tenant()
    uid, email, tok = _seed_admin(tid)
    seeded_ids: list[str] = []
    try:
        # Seed 35 active service categories alongside the defaults
        # that ``ensure_defaults_for_tenant`` injects on first list.
        for i in range(35):
            cid = f"TEST-cat-{uuid.uuid4().hex[:6]}"
            seeded_ids.append(cid)
            _db.service_categories.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"TEST_Cat_{i:02d}",
                "is_archived": False,
                "sort_order": 100 + i,
                "color": "#000000",
            })
        # Also seed 3 archived categories to prove the default
        # (``include_archived=False``) filter excludes them.
        for i in range(3):
            cid = f"TEST-cat-arc-{uuid.uuid4().hex[:6]}"
            _db.service_categories.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"TEST_Arc_{i:02d}",
                "is_archived": True,
                "sort_order": 200 + i, "color": "#000000",
            })

        r = requests.get(
            f"{API}/service-categories",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") or []

        test_prefixed = [c for c in items if c["id"].startswith("TEST-cat-")]
        # Every seeded active row made it through.
        for cid in seeded_ids:
            assert any(c["id"] == cid for c in test_prefixed), (
                f"seeded active category {cid} missing from response"
            )
        # Archived rows are excluded by default (no ``include_archived``).
        assert not any(
            c["id"].startswith("TEST-cat-arc-") for c in items
        ), "archived rows must be excluded when include_archived is omitted"

        # No implicit truncation — the response count covers all 35
        # seeded + however many default rows the backend auto-seeds
        # for a new tenant.
        assert len(items) >= 35, (
            f"expected ≥ 35 categories (35 seeded + defaults); "
            f"got {len(items)} — possible truncation bug"
        )
    finally:
        _cleanup(tid, uid, email)
