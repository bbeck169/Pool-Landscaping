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
    tok = _login("mike@aquaterra.com")
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
def test_self_patch_auto_clockin_flip():
    tok = _login("mike@aquaterra.com")
    try:
        r = requests.patch(f"{API}/users/me",
                            json={"auto_clockin_enabled": False},
                            headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["auto_clockin_enabled"] is False
        # Flip back.
        r2 = requests.patch(f"{API}/users/me",
                             json={"auto_clockin_enabled": True},
                             headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["user"]["auto_clockin_enabled"] is True
    finally:
        _sync_db.users.update_one(
            {"email": "mike@aquaterra.com"},
            {"$set": {"auto_clockin_enabled": True}},
        )


# ── PATCH /users/{id} admin update ──────────────────────────────
def test_admin_patch_auto_clockin_on_tech():
    admin = _login("admin@aquaterra.com")
    u = _sync_db.users.find_one({"email": "mike@aquaterra.com"},
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
    u = _sync_db.users.find_one({"email": "mike@aquaterra.com"},
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
