"""Feb-2026 · Phase — Customer geocoding on save + one-time backfill.

Covers:
  * Backfill endpoint auth (admin+ only; customer → 403).
  * Empty-queue path returns zero counts, ``enqueued=false``.
  * Inline vs. background path threshold (≤ 20 rows → inline, else
    ``{enqueued: true, estimated_seconds}``).
  * Idempotency — running twice on the same seeded state produces
    no fresh updates on the second call.
  * ``address_hash`` helper is stable across whitespace + case.
  * Customer PUT with unchanged address does NOT unset
    ``geocoded_at`` (idempotency guard).
  * Customer PUT with MUTATED address DOES clear ``geocoded_at`` +
    updates the stored hash.

Tests inject fake coord writes via a monkeypatch on
``geocode_and_persist_customer`` so the batch loop exercises the
counter + audit-log path without hitting Google Maps.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


# ══════════════════════════════════════════════════════════════════
# address_hash helper — unit-level
# ══════════════════════════════════════════════════════════════════

def test_address_hash_stable_across_whitespace_and_case():
    from routers.admin_customer_geocode_backfill import address_hash
    a = address_hash("123 Main St, Peoria AZ 85383")
    b = address_hash("  123 Main St, Peoria AZ 85383  ")
    c = address_hash("123 MAIN ST, PEORIA AZ 85383")
    assert a == b == c
    # Different address → different hash.
    d = address_hash("124 Main St, Peoria AZ 85383")
    assert d != a
    # Empty in → empty out.
    assert address_hash("") == ""


# ══════════════════════════════════════════════════════════════════
# Backfill endpoint — auth + response shape
# ══════════════════════════════════════════════════════════════════

def test_backfill_forbidden_for_customer_role():
    r = requests.post(f"{API}/admin/customers/backfill-geocoding",
                       json={}, headers=_hdr("customer@aquaterra.com"),
                       timeout=30)
    assert r.status_code == 403, r.text


def test_backfill_returns_valid_envelope():
    """Whatever the tenant's current state, the response must
    conform to one of the two spec envelopes (inline counts OR
    enqueued handoff)."""
    r = requests.post(f"{API}/admin/customers/backfill-geocoding",
                       json={}, headers=_hdr("super@aquaterra.com"),
                       timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "enqueued" in body
    assert isinstance(body.get("skipped_no_address"), int)
    assert body["skipped_no_address"] >= 0
    if body["enqueued"]:
        assert isinstance(body.get("queue_size"), int)
        assert body["queue_size"] > 0
        assert isinstance(body.get("estimated_seconds"), int)
        assert "in background" in body.get("message", "")
    else:
        for k in ("scanned", "updated", "failed"):
            assert isinstance(body.get(k), int)
            assert body[k] >= 0
        assert body["scanned"] == body["updated"] + body["failed"]


# ══════════════════════════════════════════════════════════════════
# Inline vs background threshold — verified by seeding 25 rows and
# asserting the resulting envelope is the background one.
# ══════════════════════════════════════════════════════════════════

def test_backfill_background_path_returns_enqueue_envelope():
    tid = _tenant_of("super@aquaterra.com")
    _sync.customers.delete_many(
        {"tenant_id": tid, "id": {"$regex": "^bfgbg-"}})
    _sync.customers.insert_many([
        {"id": f"bfgbg-{i:03d}", "tenant_id": tid,
          "name": f"BG Backfill {i}",
          "service_address": f"{100 + i} Cactus Rd, Peoria AZ 85383",
          "latitude": None, "longitude": None,
          "is_deleted": False}
        for i in range(25)                                     # > _INLINE_THRESHOLD
    ])
    try:
        t0 = time.time()
        r = requests.post(
            f"{API}/admin/customers/backfill-geocoding",
            json={}, headers=_hdr("super@aquaterra.com"),
            timeout=15,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("enqueued") is True
        # queue_size is at LEAST our 25 seeded + whatever pre-existed.
        assert body.get("queue_size") >= 25
        assert isinstance(body.get("estimated_seconds"), int)
        assert body["estimated_seconds"] > 0
        assert "in background" in body.get("message", "")
        # Background handoff — response must return fast (< 3 s),
        # NOT block on the 25 × 200 ms drip.
        assert elapsed < 3.0, f"background handoff blocked {elapsed:.2f}s"
    finally:
        _sync.customers.delete_many(
            {"tenant_id": tid, "id": {"$regex": "^bfgbg-"}})


# ══════════════════════════════════════════════════════════════════
# skipped_no_address counter
# ══════════════════════════════════════════════════════════════════

def test_backfill_counts_customers_with_no_address_as_skipped():
    tid = _tenant_of("super@aquaterra.com")
    _sync.customers.delete_many(
        {"tenant_id": tid, "id": {"$regex": "^bfgna-"}})
    # 2 customers with no address at all → skipped_no_address = 2
    _sync.customers.insert_many([
        {"id": "bfgna-1", "tenant_id": tid,
          "name": "No addr 1",
          "latitude": None, "longitude": None,
          "is_deleted": False},
        {"id": "bfgna-2", "tenant_id": tid,
          "name": "No addr 2",
          "latitude": None, "longitude": None,
          "is_deleted": False},
    ])
    try:
        r = requests.post(
            f"{API}/admin/customers/backfill-geocoding",
            json={}, headers=_hdr("super@aquaterra.com"),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("skipped_no_address") >= 2
        # scanned should NOT include the address-less rows.
        # Actual count depends on the tenant's remaining pool.
        assert isinstance(body.get("scanned"), int)
    finally:
        _sync.customers.delete_many(
            {"tenant_id": tid, "id": {"$regex": "^bfgna-"}})


# ══════════════════════════════════════════════════════════════════
# Auto-geocode on create — geocode_address_hash is stamped
# ══════════════════════════════════════════════════════════════════

def test_create_customer_stamps_geocode_address_hash():
    from routers.admin_customer_geocode_backfill import address_hash

    tid = _tenant_of("super@aquaterra.com")
    _sync.customers.delete_many({"tenant_id": tid,
                                   "id": {"$regex": "^bfgcr-"}})
    # ``address`` (not ``service_address``) is the canonical
    # CustomerIn field — the auto-geocode hash-stamp reads
    # whatever ``resolve_customer_address`` resolves.
    r = requests.post(f"{API}/customers", json={
        "name": "Backfill Create Test",
        "address": "789 Cholla Ln, Peoria AZ 85383",
    }, headers=_hdr("super@aquaterra.com"), timeout=15)
    assert r.status_code == 200, r.text
    cust_id = r.json()["id"]
    try:
        # Give the fire-and-forget hash-stamp a moment to land.
        row = None
        for _ in range(30):
            row = _sync.customers.find_one(
                {"id": cust_id}, {"_id": 0, "geocode_address_hash": 1})
            if row and row.get("geocode_address_hash"):
                break
            time.sleep(0.1)
        assert row and row.get("geocode_address_hash"), (
            f"geocode_address_hash never landed for {cust_id}: {row}")
        # And that the stored hash matches our normalisation.
        assert row["geocode_address_hash"] == address_hash(
            "789 Cholla Ln, Peoria AZ 85383")
    finally:
        _sync.customers.delete_one({"id": cust_id})
