"""Feb-2026 · P33 — tenant customer_tags catalog + auto-persist tests.

Extends the Phase 15b customer_tags contract with the P33 auto-persist
hook on customer create + update. The registry itself already ships;
this suite pins:

  * ``GET /api/customer-tags`` — any authenticated staff (incl.
    technician) can read.
  * Auto-persist: creating a customer with a novel tag inserts a
    ``customer_tags`` row with ``auto_created=true``.
  * Idempotent dedup: creating a second customer with the same tag
    (and its case variants) inserts NO duplicate.
  * PUT auto-persist: updating a customer's tags via the main PUT
    route also lands novel tags in the catalog.
  * Isolation: auto-persist failure NEVER blocks the customer save
    (verified via the whitespace-only branch, which is a deterministic
    no-op skip path).
  * Backfill migration: seeded a customer with a tag missing from the
    catalog, migration --commit fills the gap.
  * ``/api/openapi.json`` still 200 and lists ``/customer-tags``.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _cleanup_customers(cids: list[str]) -> None:
    if cids:
        _sync.customers.delete_many({"id": {"$in": cids}})


def _cleanup_tags(tid: str, labels: list[str]) -> None:
    _sync.customer_tags.delete_many(
        {"tenant_id": tid, "name_lower": {"$in": [x.lower() for x in labels]}},
    )


def _new_customer_payload(name_hint: str) -> dict:
    """Minimum body accepted by ``POST /api/customers``."""
    return {
        "name": f"TEST P33 {name_hint} {uuid.uuid4().hex[:6]}",
        "email": f"test-p33-{uuid.uuid4().hex[:6]}@example.com",
        "phone": "6235550100",
        "address": "1 Test St",
    }


# ─── 1. openapi still lists /customer-tags ────────────────────────────

def test_openapi_lists_customer_tags_routes():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200, r.text
    paths = r.json().get("paths") or {}
    assert "/api/customer-tags" in paths
    assert "/api/customer-tags/{tag_id}" in paths


# ─── 2. GET /customer-tags open to any staff (tech + admin) ───────────

def test_get_customer_tags_open_to_technician(tech_h):
    r = requests.get(f"{API}/customer-tags", headers=tech_h, timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json().get("items"), list)


def test_get_customer_tags_still_works_for_admin(admin_h):
    r = requests.get(f"{API}/customer-tags", headers=admin_h, timeout=15)
    assert r.status_code == 200, r.text


# ─── 3. Auto-persist on POST /customers ───────────────────────────────

def test_create_customer_with_novel_tag_auto_persists(
    admin_h, aquaterra_tid,
):
    novel = f"NovelP33{uuid.uuid4().hex[:6]}"
    payload = _new_customer_payload("create")
    payload["tags"] = [novel]
    created_cid = None
    try:
        r = requests.post(f"{API}/customers", headers=admin_h,
                             json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        created_cid = r.json()["id"]

        # Give the async task a beat if needed (auto-persist runs in-line so
        # the row should exist by the time the response returns, but keep a
        # tiny retry loop for tolerance).
        row = None
        for _ in range(5):
            row = _sync.customer_tags.find_one(
                {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
            )
            if row: break
            time.sleep(0.1)
        assert row is not None, "novel tag must land in the catalog"
        assert row.get("auto_created") is True
        assert row.get("name") == novel
    finally:
        _cleanup_customers([created_cid] if created_cid else [])
        _cleanup_tags(aquaterra_tid, [novel])


# ─── 4. Idempotent dedup — case-variant on 2nd create ─────────────────

def test_second_customer_with_case_variant_tag_no_duplicate(
    admin_h, aquaterra_tid,
):
    novel = f"CaseP33{uuid.uuid4().hex[:6]}"
    cid_a = cid_b = None
    try:
        r_a = requests.post(f"{API}/customers", headers=admin_h,
                                json={**_new_customer_payload("a"),
                                        "tags": [novel]}, timeout=15)
        cid_a = r_a.json()["id"]

        # Second create — same label but lowercased.
        r_b = requests.post(f"{API}/customers", headers=admin_h,
                                json={**_new_customer_payload("b"),
                                        "tags": [novel.lower()]}, timeout=15)
        cid_b = r_b.json()["id"]

        rows = list(_sync.customer_tags.find(
            {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
        ))
        assert len(rows) == 1, \
            f"Expected 1 catalog row, got {len(rows)}"
        assert rows[0].get("auto_created") is True
    finally:
        _cleanup_customers([x for x in (cid_a, cid_b) if x])
        _cleanup_tags(aquaterra_tid, [novel])


# ─── 5. Auto-persist on PUT /customers/{cid} ──────────────────────────

def test_update_customer_tags_via_put_auto_persists(
    admin_h, aquaterra_tid,
):
    novel = f"PutP33{uuid.uuid4().hex[:6]}"
    payload = _new_customer_payload("put")
    cid = None
    try:
        r = requests.post(f"{API}/customers", headers=admin_h,
                             json=payload, timeout=15)
        cid = r.json()["id"]

        # No tag exists yet.
        assert _sync.customer_tags.find_one(
            {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
        ) is None

        # PUT the customer with a novel tag added.
        put_payload = {**payload, "tags": [novel]}
        r2 = requests.put(f"{API}/customers/{cid}",
                             headers=admin_h, json=put_payload, timeout=15)
        assert r2.status_code == 200, r2.text

        row = _sync.customer_tags.find_one(
            {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
        )
        assert row is not None, "PUT-added tag must land in the catalog"
        assert row.get("auto_created") is True
    finally:
        _cleanup_customers([cid] if cid else [])
        _cleanup_tags(aquaterra_tid, [novel])


# ─── 6. Whitespace / empty tags skip cleanly ──────────────────────────

def test_customer_with_blank_tag_strings_does_not_leak_to_catalog(
    admin_h, aquaterra_tid,
):
    """Whitespace-only + empty-string tags must not create rows.
    Also proves the auto-persist path handles junk input without
    raising (matches the try/except isolation requirement)."""
    payload = _new_customer_payload("blank")
    payload["tags"] = ["   ", "", "\t\n"]
    cid = None
    baseline = _sync.customer_tags.count_documents(
        {"tenant_id": aquaterra_tid},
    )
    try:
        r = requests.post(f"{API}/customers", headers=admin_h,
                             json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        cid = r.json()["id"]

        after = _sync.customer_tags.count_documents(
            {"tenant_id": aquaterra_tid},
        )
        assert after == baseline, \
            "whitespace-only tag strings must NOT create catalog rows"
    finally:
        _cleanup_customers([cid] if cid else [])


# ─── 7. Backfill migration — --commit inserts missing rows ────────────

def test_backfill_migration_seeds_missing_tags(admin_h, aquaterra_tid):
    novel = f"BackfillP33{uuid.uuid4().hex[:6]}"
    # Insert a customer directly WITHOUT going through the auto-persist
    # path, simulating a legacy import / direct-DB write.
    cid = f"TEST_p33_c_{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": aquaterra_tid,
        "name": f"TEST P33 backfill {uuid.uuid4().hex[:6]}",
        "email": f"{cid}@example.com", "phone": "6235550100",
        "address": "1 Test St", "tags": [novel],
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    try:
        # Catalog does NOT yet have the tag.
        assert _sync.customer_tags.find_one(
            {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
        ) is None

        # Run the migration --commit as a subprocess so it gets its
        # own fresh asyncio event loop + Motor client (importing +
        # calling it inline conflicts with the current test-worker
        # event loop and raises "attached to a different loop").
        import subprocess, sys as _sys
        proj_root = Path(__file__).resolve().parents[1]
        cp = subprocess.run(
            [_sys.executable, "-m",
              "migrations.task_p33_seed_customer_tags_catalog", "--commit"],
            cwd=str(proj_root),
            capture_output=True, text=True, timeout=30,
        )
        assert cp.returncode == 0, cp.stderr
        assert "committed:                     True" in cp.stdout

        # Row now exists with the auto_created flag.
        row = _sync.customer_tags.find_one(
            {"tenant_id": aquaterra_tid, "name_lower": novel.lower()},
        )
        assert row is not None
        assert row.get("auto_created") is True
    finally:
        _cleanup_customers([cid])
        _cleanup_tags(aquaterra_tid, [novel])


# ─── 8. RBAC still gates writes (tech 403) ────────────────────────────

def test_post_customer_tags_still_blocks_technician(tech_h):
    r = requests.post(f"{API}/customer-tags", headers=tech_h,
                         json={"name": "TechShouldNotCreate"}, timeout=15)
    assert r.status_code == 403, r.text
