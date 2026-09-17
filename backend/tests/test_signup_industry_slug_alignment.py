"""Feb-2026 · Business Signup SP3 — industry slug canonical alignment.

Enforces the SP3 non-negotiable: the SP1 ``POST /api/signup`` +
SP2 ``PATCH /api/signup-onboarding/step/4`` industry validators
share ONE source of truth (``routers/industry_checklists.INDUSTRY_SLUGS``)
and alias-normalize the legacy plural ``"pools"`` to the canonical
singular ``"pool"`` before storage.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _drop(email: str) -> None:
    u = _sync.users.find_one({"email": email.lower()})
    if u:
        _sync.tenants.delete_many({"id": u.get("tenant_id")})
        _sync.users.delete_many({"id": u["id"]})


def _payload(industry: str) -> Dict[str, Any]:
    return {
        "business_name":            "Slug Alignment LLC",
        "admin_name":               "Slug Tester",
        "admin_email":              f"slug-{uuid.uuid4().hex[:8]}@t.example",
        "admin_password":           "correcthorse42battery",
        "admin_phone":              "+15551234567",
        "primary_industry":         industry,
        "timezone":                 "America/Phoenix",
        "country":                  "US",
        "stripe_payment_method_id": "pm_test",
    }


# ── Alias-normalize: "pools" → "pool" ─────────────────────────────

def test_signup_accepts_pool_singular_and_stores_singular():
    body = _payload("pool")
    _drop(body["admin_email"])
    r = requests.post(f"{API}/signup", json=body, timeout=15)
    assert r.status_code == 201, r.text
    tenant_id = r.json()["tenant_id"]
    doc = _sync.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    assert doc.get("primary_industry") == "pool", doc
    assert "pool" in (doc.get("industries") or []), doc
    _drop(body["admin_email"])


def test_signup_accepts_pools_plural_alias_and_normalises_to_singular():
    body = _payload("pools")
    _drop(body["admin_email"])
    r = requests.post(f"{API}/signup", json=body, timeout=15)
    assert r.status_code == 201, r.text
    tenant_id = r.json()["tenant_id"]
    doc = _sync.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    assert doc.get("primary_industry") == "pool", (
        "SP3 alias-normalize: plural 'pools' MUST store as canonical "
        "'pool' — got %r" % doc.get("primary_industry")
    )
    assert "pool" in (doc.get("industries") or []), doc
    _drop(body["admin_email"])


# ── All 23 canonical slugs accepted ────────────────────────────────

def test_signup_accepts_every_canonical_slug():
    from routers.industry_checklists import INDUSTRY_SLUGS
    canonical = list(INDUSTRY_SLUGS)
    assert len(canonical) == 23, canonical
    for slug in canonical:
        body = _payload(slug)
        _drop(body["admin_email"])
        r = requests.post(f"{API}/signup", json=body, timeout=15)
        assert r.status_code == 201, (
            f"canonical slug {slug!r} rejected: {r.status_code} {r.text}"
        )
        tenant_id = r.json()["tenant_id"]
        doc = _sync.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
        assert doc.get("primary_industry") == slug, doc
        _drop(body["admin_email"])


# ── Non-canonical slugs rejected ───────────────────────────────────

@pytest.mark.parametrize("bad_slug", [
    "pool_service",
    "POOL",  # uppercase — validator lowercases + then checks membership
    "not_a_real_industry",
    "carpentry",   # was in the drifted SP1 set but NOT canonical
    "flooring",    # same
    "moving",      # same
    "junk_removal",
    "general_services",
])
def test_signup_rejects_non_canonical_slugs(bad_slug: str):
    body = _payload(bad_slug)
    _drop(body["admin_email"])
    r = requests.post(f"{API}/signup", json=body, timeout=15)
    # ``POOL`` lowercases to ``pool`` so IS accepted — assert that
    # explicitly so the test's intent is documented.
    if bad_slug == "POOL":
        assert r.status_code == 201, r.text
        _drop(body["admin_email"])
        return
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("code") == "invalid_industry", detail


# ── Backfill migration idempotency ─────────────────────────────────

def test_backfill_pools_to_pool_is_idempotent():
    """Runs the backfill twice against a seeded tenant. First run
    normalises ``pools`` → ``pool`` in both the scalar field and
    the array field; second run finds nothing to change."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.migrations.backfill_industry_slug_pools_to_pool import (
        run_backfill_industry_slug_pools_to_pool,
    )

    # Seed via the pymongo sync client (same loop-safe pattern used
    # elsewhere in this file). Then run the async migration against
    # a fresh MotorClient bound to a brand-new event loop.
    tid = "sp3-backfill-test-%s" % uuid.uuid4().hex[:8]
    _sync.tenants.insert_one({
        "id": tid,
        "name": "SP3 Backfill Test",
        "primary_industry": "pools",
        "industries": ["pools", "landscaping"],
    })
    try:
        loop = asyncio.new_event_loop()
        try:
            motor_client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
            adb = motor_client[_ENV["DB_NAME"]]
            first = loop.run_until_complete(
                run_backfill_industry_slug_pools_to_pool(adb),
            )
            assert first["modified_primary"] >= 1, first
            assert first["modified_array"] >= 1, first

            row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
            assert row["primary_industry"] == "pool", row
            assert row["industries"] == ["pool", "landscaping"], row

            # Second run must be a no-op (idempotent).
            second = loop.run_until_complete(
                run_backfill_industry_slug_pools_to_pool(adb),
            )
            assert second["matched_primary"] == 0, second
            assert second["modified_primary"] == 0, second
            assert second["modified_array"] == 0, second
        finally:
            motor_client.close()
            loop.close()
    finally:
        _sync.tenants.delete_one({"id": tid})
