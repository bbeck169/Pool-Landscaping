"""Feb-2026 · mobile-gap coverage — auto_clockin_enabled + orphan customer repair."""
import os
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if _MONGO_URL and _DB_NAME else None


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


# ── /auth/me exposes new fields ──────────────────────────────────
def test_auth_me_tech_has_auto_clockin_true():
    tok = _login("landscaper@aquaterra.com")
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    body = r.json()
    assert body.get("role") == "technician"
    assert body.get("auto_clockin_enabled") is True


def test_auth_me_admin_defaults_auto_clockin_false():
    tok = _login("admin@aquaterra.com")
    body = requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    assert body.get("auto_clockin_enabled") is False


def test_auth_me_customer_flags_orphan_when_no_linked_record():
    tok = _login("customer@aquaterra.com")
    body = requests.get(f"{API}/auth/me",
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    # The seeded customer user has a customer_id that points at a doc
    # not present in db.customers → orphan. Flag is present.
    assert "customer_record_missing" in body
    assert isinstance(body["customer_record_missing"], bool)


# ── PATCH /users/me self-update ─────────────────────────────────
# Phase 29 · Feb-2026 — techs can no longer disable Auto Clock-In.
# The endpoint now returns 403 when a tech-role caller submits
# ``auto_clockin_enabled: false``. Non-tech roles + the tech-flips-
# it-back-to-True path both stay 200.
def test_self_patch_auto_clockin_flip():
    tok = _login("landscaper@aquaterra.com")
    # Phase 29 · disabling as a tech must be rejected with 403.
    r = requests.patch(f"{API}/users/me",
                        json={"auto_clockin_enabled": False},
                        headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 403, r.text
    assert "enforced" in r.text.lower() or "cannot be disabled" in r.text.lower()
    # Setting it back to True (idempotent) still works.
    r2 = requests.patch(f"{API}/users/me",
                         json={"auto_clockin_enabled": True},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["user"]["auto_clockin_enabled"] is True
    # DB row remains True (belt-and-suspenders — the 403 above must
    # have written nothing).
    fresh = _sync_db.users.find_one({"email": "landscaper@aquaterra.com"},
                                     {"_id": 0, "auto_clockin_enabled": 1})
    assert fresh["auto_clockin_enabled"] is True


# ── PATCH /users/{id} admin update ──────────────────────────────
def test_admin_patch_auto_clockin_on_tech():
    admin = _login("admin@aquaterra.com")
    u = _sync_db.users.find_one({"email": "landscaper@aquaterra.com"},
                                  {"_id": 0, "id": 1})
    r = requests.patch(f"{API}/users/{u['id']}",
                        json={"auto_clockin_enabled": False},
                        headers={"Authorization": f"Bearer {admin}"}, timeout=15)
    assert r.status_code == 200
    fresh = _sync_db.users.find_one({"id": u["id"]},
                                      {"_id": 0, "auto_clockin_enabled": 1})
    assert fresh["auto_clockin_enabled"] is False
    _sync_db.users.update_one({"id": u["id"]},
                                {"$set": {"auto_clockin_enabled": True}})


def test_admin_patch_auto_clockin_type_validation():
    admin = _login("admin@aquaterra.com")
    u = _sync_db.users.find_one({"email": "landscaper@aquaterra.com"},
                                  {"_id": 0, "id": 1})
    r = requests.patch(f"{API}/users/{u['id']}",
                        json={"auto_clockin_enabled": "not-a-bool"},
                        headers={"Authorization": f"Bearer {admin}"}, timeout=15)
    assert r.status_code == 400


# ── boot backfill idempotency ───────────────────────────────────
def test_auto_clockin_backfill_is_idempotent():
    import asyncio
    from routers.auto_clockin import run_auto_clockin_backfill
    from tests._shared_loop import LOOP, run as _run

    first = _run(run_auto_clockin_backfill())
    second = _run(run_auto_clockin_backfill())
    # Second run should stamp nothing because the field is now
    # present on every user.
    assert second["tech_true"] == 0
    assert second["non_tech_false"] == 0


# ── orphan customer repair endpoint ─────────────────────────────
def test_orphan_repair_creates_linked_customer():
    sup = _login("super@aquaterra.com")

    # Create a throwaway customer auth user with no linked record.
    orphan_id = f"orphan-{uuid.uuid4().hex[:8]}"
    orphan_email = f"orphan-{orphan_id}@example.local"
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    _sync_db.users.insert_one({
        "id": orphan_id,
        "tenant_id": tenant["id"],
        "email": orphan_email,
        "role": "customer",
        "name": "Orphan Test",
        "password_hash": "unused",
    })

    r = requests.post(
        f"{API}/admin/users/{orphan_id}/create-customer-record",
        headers={"Authorization": f"Bearer {sup}"}, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["was_already_linked"] is False
    new_cid = body["customer_id"]
    # Customer record persisted.
    assert _sync_db.customers.find_one({"id": new_cid}) is not None
    # User doc got the link.
    fresh_u = _sync_db.users.find_one({"id": orphan_id}, {"_id": 0, "customer_id": 1})
    assert fresh_u["customer_id"] == new_cid

    # Idempotent — second call returns was_already_linked.
    r2 = requests.post(
        f"{API}/admin/users/{orphan_id}/create-customer-record",
        headers={"Authorization": f"Bearer {sup}"}, timeout=15,
    )
    assert r2.status_code == 200
    assert r2.json()["was_already_linked"] is True

    # Teardown.
    _sync_db.users.delete_one({"id": orphan_id})
    _sync_db.customers.delete_one({"id": new_cid})


def test_orphan_repair_admin_forbidden():
    adm = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/admin/users/does-not-matter/create-customer-record",
        headers={"Authorization": f"Bearer {adm}"}, timeout=15,
    )
    assert r.status_code == 403


# ── NEW · Feb-2026 · GET /admin/orphan-customer-users ─────────────
def test_orphan_list_super_admin_returns_orphans():
    """Super-admin lists orphan customer auth users."""
    sup = _login("super@aquaterra.com")
    # Seed a throwaway orphan.
    orphan_id = f"orphlist-{uuid.uuid4().hex[:8]}"
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    _sync_db.users.insert_one({
        "id": orphan_id,
        "tenant_id": tenant["id"],
        "email": f"{orphan_id}@example.local",
        "role": "customer",
        "name": "Orphan List Test",
        "password_hash": "unused",
    })
    try:
        r = requests.get(
            f"{API}/admin/orphan-customer-users",
            headers={"Authorization": f"Bearer {sup}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("users"), list)
        found = [u for u in body["users"] if u["id"] == orphan_id]
        assert len(found) == 1
        assert found[0]["reason"] == "missing_customer_id"
        assert found[0]["email"] == f"{orphan_id}@example.local"
    finally:
        _sync_db.users.delete_one({"id": orphan_id})


def test_orphan_list_admin_forbidden():
    adm = _login("admin@aquaterra.com")
    r = requests.get(
        f"{API}/admin/orphan-customer-users",
        headers={"Authorization": f"Bearer {adm}"}, timeout=15,
    )
    assert r.status_code == 403


# ── NEW · Feb-2026 · POST /portal/complete-profile ────────────────
def test_complete_profile_customer_only():
    """Non-customers cannot hit the endpoint (403)."""
    adm = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/portal/complete-profile",
        json={"first_name": "X", "last_name": "Y", "phone": "5551234",
              "service_address": "1 Test St", "preferred_contact": "email"},
        headers={"Authorization": f"Bearer {adm}"}, timeout=15,
    )
    assert r.status_code == 403


def test_complete_profile_creates_customer_and_clears_flag():
    """First submission creates customer + clears the orphan flag.
    Second submission is idempotent (was_already_linked=True)."""
    # Seed an orphan customer auth user with a login we control.
    orphan_id = f"cp-{uuid.uuid4().hex[:8]}"
    orphan_email = f"{orphan_id}@example.com"
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})

    # Real bcrypt hash for the password 'password123' via the app's own
    # helper so we can log in via the API.
    from utils import hash_password
    _sync_db.users.insert_one({
        "id": orphan_id,
        "tenant_id": tenant["id"],
        "email": orphan_email,
        "role": "customer",
        "name": "",
        "password_hash": hash_password("password123"),
    })
    new_cid = None
    try:
        tok = _login(orphan_email)

        # /auth/me should report orphan.
        me = requests.get(f"{API}/auth/me",
                           headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
        assert me.get("customer_record_missing") is True

        r = requests.post(
            f"{API}/portal/complete-profile",
            json={
                "first_name": "Jane",
                "last_name": "Doe",
                "phone": "5555550100",
                "service_address": "42 Vistancia Blvd",
                "preferred_contact": "sms",
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["was_already_linked"] is False
        assert body["customer_record_missing"] is False
        new_cid = body["customer_id"]

        # DB reflects: customer doc exists + auth-user relinked.
        cust = _sync_db.customers.find_one({"id": new_cid}, {"_id": 0})
        assert cust is not None
        assert cust["email"] == orphan_email
        assert cust["preferred_contact"] == "sms"
        assert cust["address"] == "42 Vistancia Blvd"
        assert cust["created_via"] == "customer_self_serve"
        u2 = _sync_db.users.find_one({"id": orphan_id},
                                       {"_id": 0, "customer_id": 1})
        assert u2["customer_id"] == new_cid

        # /auth/me now reports NOT orphan.
        me2 = requests.get(f"{API}/auth/me",
                            headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
        assert me2.get("customer_record_missing") is False

        # Idempotent — second call returns was_already_linked.
        r2 = requests.post(
            f"{API}/portal/complete-profile",
            json={
                "first_name": "Jane",
                "last_name": "Doe",
                "phone": "5555550100",
                "service_address": "42 Vistancia Blvd",
                "preferred_contact": "sms",
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json()["was_already_linked"] is True
    finally:
        _sync_db.users.delete_one({"id": orphan_id})
        if new_cid:
            _sync_db.customers.delete_one({"id": new_cid})


def test_complete_profile_skip_audits_and_leaves_orphan():
    """?skip=1 writes an audit event and leaves the flag intact."""
    orphan_id = f"cpskip-{uuid.uuid4().hex[:8]}"
    orphan_email = f"{orphan_id}@example.com"
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})

    from utils import hash_password
    _sync_db.users.insert_one({
        "id": orphan_id,
        "tenant_id": tenant["id"],
        "email": orphan_email,
        "role": "customer",
        "name": "",
        "password_hash": hash_password("password123"),
    })
    try:
        tok = _login(orphan_email)
        r = requests.post(
            f"{API}/portal/complete-profile?skip=1",
            json={},
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["skipped"] is True
        assert body["customer_record_missing"] is True
        # Still orphan on the auth side.
        u = _sync_db.users.find_one({"id": orphan_id},
                                      {"_id": 0, "customer_id": 1})
        assert not u.get("customer_id")
        # Audit note written.
        note = _sync_db.audit_events.find_one({
            "kind": "profile_incomplete_reminder",
            "user_id": orphan_id,
        }, {"_id": 0})
        assert note is not None
    finally:
        _sync_db.users.delete_one({"id": orphan_id})
        _sync_db.audit_events.delete_many({"user_id": orphan_id})
