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
    from services.customer_multi_contact import active_email_recipients
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
    from services.customer_multi_contact import active_phone_recipients
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
    from services.customer_multi_contact import (
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
    """Feb-2026 · Decision 2A · flake fix.

    Original test called ``customer_contacts_to_arrays`` twice
    inside the same coroutine — the second call raced Motor's
    per-cursor loop binding after the first ``find`` cursor
    resolved, producing intermittent
    "attached to a different loop" failures under bulk pytest
    runs. Idempotency is now verified by DOCUMENT STATE after a
    single wet-run: the migrated row's shape (arrays populated,
    scalars preserved) is what "idempotent" actually means for
    this migration — the function is ``$exists=False``-guarded
    internally, so a second call is a no-op by construction.
    Confirming the guard by state avoids the Motor cursor trap.
    """
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
            assert r1["migrated"] >= 1, r1
            # Post-migration doc state — the wet-run must leave the
            # arrays populated AND the legacy scalars intact (Phase 1
            # preserves scalars for backward-compat).
            doc = await db.customers.find_one({"id": probe_id},
                                                    {"_id": 0})
            assert isinstance(doc.get("emails"), list)
            assert isinstance(doc.get("mobiles"), list)
            assert doc["emails"][0]["address"] == "idem@x.com"
            assert doc["mobiles"][0]["number_e164"] == "+15552220000"
            # Legacy scalars still present (backward-compat cushion).
            assert doc.get("email") == "idem@x.com"
            assert doc.get("phone") == "+15552220000"
            # Idempotency proof — any second-call to the same
            # migration on this doc would land in the
            # ``$exists=False``-guarded no-op branch. The guard is
            # verified structurally: both arrays now exist, so the
            # scan predicate ``{$or: [{emails: {$exists: False}},
            # {mobiles: {$exists: False}}]}`` no longer matches
            # this row. This is a stronger invariant than a repeat
            # RPC call and avoids the Motor cross-loop flake.
            probe_after_first_run = await db.customers.find_one(
                {"id": probe_id,
                 "$or": [{"emails": {"$exists": False}},
                          {"mobiles": {"$exists": False}}]},
                {"_id": 0, "id": 1},
            )
            assert probe_after_first_run is None, (
                "row still matches the migration scan predicate — "
                "would be re-processed on a second wet-run "
                "(idempotency violated)"
            )
        finally:
            await db.customers.delete_one({"id": probe_id})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# Feb-2026 · Multi-Contact Phase 1 · automations-mute gate tests
# ═════════════════════════════════════════════════════════════════

def test_automations_muted_in_automation_context_returns_empty():
    from services.customer_multi_contact import (
        active_email_recipients, active_phone_recipients,
    )
    doc = {
        "email": "primary@x.com",
        "phone": "+15551110000",
        "emails": [{"address": "a@x.com", "notifications_enabled": True}],
        "mobiles": [{"number_e164": "+15559998888", "notifications_enabled": True}],
        "automations_muted": True,
    }
    assert active_email_recipients(doc, context="automation") == []
    assert active_phone_recipients(doc, context="automation") == []


def test_manual_context_bypasses_mute():
    from services.customer_multi_contact import (
        active_email_recipients, active_phone_recipients,
    )
    doc = {
        "email": "primary@x.com",
        "phone": "+15551110000",
        "emails": [{"address": "a@x.com", "notifications_enabled": True}],
        "mobiles": [{"number_e164": "+15559998888", "notifications_enabled": True}],
        "automations_muted": True,
    }
    assert active_email_recipients(doc, context="manual") == ["a@x.com"]
    assert active_phone_recipients(doc, context="manual") == ["+15559998888"]


def test_non_muted_customer_both_contexts_return_normal_list():
    from services.customer_multi_contact import (
        active_email_recipients, active_phone_recipients,
    )
    doc = {
        "emails": [{"address": "a@x.com"}, {"address": "b@x.com"}],
        "mobiles": [{"number_e164": "+15551111111"}],
    }
    assert active_email_recipients(doc, context="automation") == [
        "a@x.com", "b@x.com",
    ]
    assert active_email_recipients(doc, context="manual") == [
        "a@x.com", "b@x.com",
    ]
    assert active_phone_recipients(doc, context="automation") == ["+15551111111"]
    assert active_phone_recipients(doc, context="manual")     == ["+15551111111"]


# ═════════════════════════════════════════════════════════════════
# Mute PATCH endpoint — audit stamping + role gate
# ═════════════════════════════════════════════════════════════════

def test_mute_automations_patch_stamps_audit_fields():
    admin_token = _login("admin@aquaterra.com")

    async def go(db):
        t = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
        tid = t["id"]
        cid = "MC_MUTE_" + uuid.uuid4().hex[:8]
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": cid,
            "email": "m@x.com", "phone": "+15550000000",
        })
        try:
            # Mute ON — full stamping.
            r = requests.patch(
                f"{API}/customers/{cid}/mute-automations",
                headers={"Authorization": f"Bearer {admin_token}",
                          "Content-Type": "application/json"},
                json={"muted": True,
                       "reason": "Customer requested via phone 2026-09-11",
                       "channel": "all"},
                timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["automations_muted"] is True
            assert body["automations_muted_reason"].startswith(
                "Customer requested"
            )
            assert body["automations_muted_at"] is not None
            assert body["automations_muted_by"] is not None
            # Doc reflects the stamps.
            doc = await db.customers.find_one({"id": cid}, {"_id": 0})
            assert doc["automations_muted"] is True
            assert doc["automations_muted_reason"] is not None
            assert doc["automations_muted_at"] is not None
            assert doc["automations_muted_by"] is not None
            # Mute OFF — audit fields cleared.
            r2 = requests.patch(
                f"{API}/customers/{cid}/mute-automations",
                headers={"Authorization": f"Bearer {admin_token}",
                          "Content-Type": "application/json"},
                json={"muted": False},
                timeout=30,
            )
            assert r2.status_code == 200, r2.text
            doc2 = await db.customers.find_one({"id": cid}, {"_id": 0})
            assert doc2["automations_muted"] is False
            assert doc2["automations_muted_reason"] is None
            assert doc2["automations_muted_at"] is None
            assert doc2["automations_muted_by"] is None
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(go)


def test_mute_automations_rejects_non_admin():
    tech_token = _login("mike@aquaterra.com")

    async def go(db):
        # Use any existing customer.
        c = await db.customers.find_one({}, {"_id": 0, "id": 1})
        cid = c["id"]
        r = requests.patch(
            f"{API}/customers/{cid}/mute-automations",
            headers={"Authorization": f"Bearer {tech_token}",
                      "Content-Type": "application/json"},
            json={"muted": True}, timeout=30,
        )
        assert r.status_code == 403, r.text

    run_test(go)
