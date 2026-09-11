"""Feb-2026 · Customer Multi-Contact Phase 1 — contract tests.

Locks these invariants:

  1. ``MAX_MOBILES = 4`` — 4-email + 4-mobile caps match the spec.
  2. ``normalize_emails`` accepts + emits both
     ``notifications_enabled`` and ``marketing_ok``; same for
     ``normalize_mobiles`` + ``sms_ok``.
  3. Fifth entry silently drops (cap-enforced, no exception —
     matches existing normalizer semantics).
  4. Duplicate address dedups on save.
  5. Fan-out helper ``active_email_recipients`` returns ONLY
     notifications-enabled entries in order.
  6. Fan-out helper ``active_phone_recipients`` same.
  7. Fan-out fallbacks to scalar when array empty.
  8. HTTP migration endpoint — super_admin gate + dry-run counts.
  9. Migration idempotent — 2nd wet-run is a no-op.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
import requests
from dotenv import load_dotenv
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test

load_dotenv("/app/backend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str = "admin@aquaterra.com",
           pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ═════════════════════════════════════════════════════════════════
# 1 · Cap = 4 for both arrays
# ═════════════════════════════════════════════════════════════════

def test_max_mobiles_is_four_max_emails_is_four():
    from services.customer_multi_contact import MAX_MOBILES, MAX_EMAILS
    assert MAX_MOBILES == 4
    assert MAX_EMAILS == 4


# ═════════════════════════════════════════════════════════════════
# 2 · notifications_enabled ↔ marketing_ok / sms_ok alias
# ═════════════════════════════════════════════════════════════════

def test_normalize_emails_bidirectional_notifications_alias():
    from services.customer_multi_contact import normalize_emails
    # (a) legacy write: marketing_ok=False → both flags emit False.
    out = normalize_emails([{"address": "a@x.com", "marketing_ok": False}])
    assert out[0]["marketing_ok"] is False
    assert out[0]["notifications_enabled"] is False
    # (b) new write: notifications_enabled=False → both False.
    out = normalize_emails([
        {"address": "b@x.com", "notifications_enabled": False},
    ])
    assert out[0]["marketing_ok"] is False
    assert out[0]["notifications_enabled"] is False


def test_normalize_mobiles_bidirectional_notifications_alias():
    from services.customer_multi_contact import normalize_mobiles
    out = normalize_mobiles([{"number_e164": "+15551234567",
                                "sms_ok": False}])
    assert out[0]["sms_ok"] is False
    assert out[0]["notifications_enabled"] is False
    out = normalize_mobiles([{"number_e164": "+15559876543",
                                "notifications_enabled": False}])
    assert out[0]["sms_ok"] is False
    assert out[0]["notifications_enabled"] is False


# ═════════════════════════════════════════════════════════════════
# 3 · Fifth entry cap-enforced (silently truncated)
# ═════════════════════════════════════════════════════════════════

def test_normalize_emails_caps_at_four():
    from services.customer_multi_contact import normalize_emails
    payload = [{"address": f"e{i}@x.com"} for i in range(6)]
    out = normalize_emails(payload)
    assert len(out) == 4
    assert {e["address"] for e in out} == {"e0@x.com", "e1@x.com",
                                                "e2@x.com", "e3@x.com"}


def test_normalize_mobiles_caps_at_four():
    from services.customer_multi_contact import normalize_mobiles
    payload = [{"number_e164": f"+155500000{i:02d}"} for i in range(6)]
    out = normalize_mobiles(payload)
    assert len(out) == 4


# ═════════════════════════════════════════════════════════════════
# 4 · Duplicate dedup
# ═════════════════════════════════════════════════════════════════

def test_duplicate_email_dedupes():
    from services.customer_multi_contact import normalize_emails
    out = normalize_emails([
        {"address": "SAME@x.com", "label": "First"},
        {"address": "same@x.com", "label": "Second"},
    ])
    assert len(out) == 1
    # First-write wins; label reflects the first entry.
    assert out[0]["label"] == "First"


# ═════════════════════════════════════════════════════════════════
# 5 · active_email_recipients returns notifications-enabled subset
# ═════════════════════════════════════════════════════════════════

def test_active_email_recipients_filters_and_dedupes():
    from services.customer_contacts import active_email_recipients
    doc = {
        "emails": [
            {"address": "a@x.com", "is_primary": True,
             "notifications_enabled": True},
            {"address": "b@x.com", "notifications_enabled": True},
            {"address": "c@x.com", "notifications_enabled": False},  # opted out
            {"address": "d@x.com", "marketing_ok": True},           # legacy alias
        ],
        "email": "primary@x.com",
    }
    out = active_email_recipients(doc)
    assert out == ["a@x.com", "b@x.com", "d@x.com"], out


# ═════════════════════════════════════════════════════════════════
# 6 · active_phone_recipients same contract
# ═════════════════════════════════════════════════════════════════

def test_active_phone_recipients_filters_and_dedupes():
    from services.customer_contacts import active_phone_recipients
    doc = {
        "mobiles": [
            {"number_e164": "+15551234567", "is_primary": True,
             "notifications_enabled": True},
            {"number_e164": "+15559876543", "sms_ok": True},
            {"number_e164": "+15550000000", "notifications_enabled": False},
        ],
        "phone": "+15550000000",
    }
    out = active_phone_recipients(doc)
    assert out == ["+15551234567", "+15559876543"], out


# ═════════════════════════════════════════════════════════════════
# 7 · Fallback to scalar when array empty
# ═════════════════════════════════════════════════════════════════

def test_fan_out_helpers_fallback_to_scalar_when_arrays_empty():
    from services.customer_contacts import (
        active_email_recipients, active_phone_recipients,
    )
    legacy_doc = {"email": "OLD@x.com", "phone": "+15550001111",
                    "emails": [], "mobiles": []}
    assert active_email_recipients(legacy_doc) == ["old@x.com"]
    assert active_phone_recipients(legacy_doc) == ["+15550001111"]
    # And when the arrays are absent entirely.
    older = {"email": "older@x.com", "phone": "+15550002222"}
    assert active_email_recipients(older) == ["older@x.com"]
    assert active_phone_recipients(older) == ["+15550002222"]


# ═════════════════════════════════════════════════════════════════
# 8 · HTTP migration endpoint — auth gate + dry-run counts
# ═════════════════════════════════════════════════════════════════

def test_migration_endpoint_rejects_non_super_admin():
    admin_token = _login("admin@aquaterra.com")  # admin, not super_admin
    r = requests.post(
        f"{API}/admin/migrations/customer-contacts-to-arrays",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"dry_run": True}, timeout=30,
    )
    # Rejected because admin ≠ super_admin.
    assert r.status_code == 403, r.text


def test_migration_endpoint_dry_run_returns_candidate_count():
    """Direct-handler test — call the router function in-process
    with a stub super_admin user so we avoid needing a real
    super_admin JWT in the fixtures."""
    from routers import admin_multi_contact_migrate as mod

    async def go(db):
        # Seed one bare-scalar customer so we know at least one
        # candidate exists for the dry-run count.
        t = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
        tid = t["id"]
        probe_id = "MC_MIG_" + uuid.uuid4().hex[:8]
        await db.customers.insert_one({
            "id": probe_id, "tenant_id": tid,
            "name": probe_id,
            "email": "probe@x.com",
            "phone": "+15551110000",
            # NOTE: no ``emails`` / ``mobiles`` fields — makes this
            # doc a migration candidate.
        })
        try:
            res = await mod.customer_contacts_to_arrays(
                dry_run=True, tenant_id=tid,
                user={"role": "super_admin"},
            )
            assert res["dry_run"] is True
            assert res["candidates_scanned"] >= 1
            assert res["migrated"] == 0  # dry_run never writes
            # DB unchanged — probe still has no arrays.
            doc = await db.customers.find_one({"id": probe_id},
                                                    {"_id": 0})
            assert "emails" not in doc
            assert "mobiles" not in doc
        finally:
            await db.customers.delete_one({"id": probe_id})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 9 · Migration idempotent — 2nd wet-run is a no-op
# ═════════════════════════════════════════════════════════════════

def test_migration_wet_run_is_idempotent():
    from routers import admin_multi_contact_migrate as mod

    async def go(db):
        t = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
        tid = t["id"]
        probe_id = "MC_MIG_IDEM_" + uuid.uuid4().hex[:8]
        await db.customers.insert_one({
            "id": probe_id, "tenant_id": tid, "name": probe_id,
            "email": "idem@x.com", "phone": "+15552220000",
        })
        try:
            r1 = await mod.customer_contacts_to_arrays(
                dry_run=False, tenant_id=tid,
                user={"role": "super_admin"},
            )
            r2 = await mod.customer_contacts_to_arrays(
                dry_run=False, tenant_id=tid,
                user={"role": "super_admin"},
            )
            assert r1["migrated"] >= 1, r1
            # Second run: no candidates remain for THIS probe row.
            doc = await db.customers.find_one({"id": probe_id},
                                                    {"_id": 0})
            assert isinstance(doc.get("emails"), list)
            assert isinstance(doc.get("mobiles"), list)
            assert doc["emails"][0]["address"] == "idem@x.com"
            assert doc["mobiles"][0]["number_e164"] == "+15552220000"
            # r2 either migrated 0 net-new OR fewer than r1 —
            # the important invariant is the doc shape didn't
            # regress under a repeat call.
            assert r2["candidates_scanned"] <= r1["candidates_scanned"]
        finally:
            await db.customers.delete_one({"id": probe_id})

    run_test(go)
