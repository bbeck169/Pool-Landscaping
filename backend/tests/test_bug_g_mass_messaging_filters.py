"""Feb-2026 · BUG G — Mass messaging regression: filter-signature mismatch.

Root cause: ``MassMessagingComposeDialog::handleSend`` was omitting
``category_ids`` / ``service_days`` / ``assigned_tech_user_ids`` from
its send payload while the preview included them. The backend's
``_consume_confirm_token`` guard requires filter-signature parity
between preview and send, so any admin who applied ANY filter got
back **400 CONFIRM_TOKEN_FILTERS_MISMATCH** and the batch never ran.

These tests pin the backend guard behavior + prove a filtered
preview → filtered send round-trip now works.
"""
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


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _purge_rate_limit(tenant_id: str) -> None:
    """The mass-messaging send is rate-limited to 1 broadcast per
    5 min per tenant. Tests must clear the batches collection between
    cases so back-to-back sends don't 429."""
    _sync_db.mass_messaging_batches.delete_many({"tenant_id": tenant_id})


@pytest.fixture
def seeded_pair():
    """Two customers with email + phone on the aquaterra tenant. The
    fixture also stamps them into a shared category so filtered
    audience tests don't need to reason about pre-existing data."""
    tenant = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    tid = tenant["id"]
    cat_id = f"bug-g-cat-{uuid.uuid4().hex[:6]}"
    ids = [f"bug-g-a-{uuid.uuid4().hex[:6]}", f"bug-g-b-{uuid.uuid4().hex[:6]}"]
    _sync_db.customers.insert_many([
        {"id": ids[0], "tenant_id": tid, "name": "Bug G Alice",
         "email": "alice-bug-g@example.local", "phone": "+15551234901",
         "is_active": True, "category_ids": [cat_id]},
        {"id": ids[1], "tenant_id": tid, "name": "Bug G Ben",
         "email": "ben-bug-g@example.local", "phone": "+15551234902",
         "is_active": True, "category_ids": [cat_id]},
    ])
    # Purge batches so back-to-back tests don't 429 on the 5-min limit.
    _purge_rate_limit(tid)
    yield {"customer_ids": ids, "category_id": cat_id, "tenant_id": tid}
    _sync_db.customers.delete_many({"id": {"$in": ids}})
    _purge_rate_limit(tid)


def _preview(token: str, payload: dict):
    return requests.post(f"{API}/mass-messaging/preview", json=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=15)


def _send(token: str, payload: dict):
    return requests.post(f"{API}/mass-messaging/send", json=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=15)


# ── ROOT CAUSE — filter parity guard ────────────────────────────
def test_confirm_token_rejects_filter_signature_drift(seeded_pair):
    """This is the exact regression BUG G triggered from the UI —
    preview with a filter → send without → server must 400 with
    CONFIRM_TOKEN_FILTERS_MISMATCH."""
    admin = _login("admin@aquaterra.com")
    preview_payload = {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "regression",
        "body": "regression",
    }
    prev = _preview(admin, preview_payload)
    assert prev.status_code == 200, prev.text
    tok = prev.json()["confirm_token"]
    # Send with the SAME filters — should succeed.
    good_send = {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "regression",
        "body": "regression",
        "confirm_token": tok,
    }
    # Deliberately DROP the filters — the BUG-G reproduction.
    bad_send = {k: v for k, v in good_send.items()
                 if k not in ("category_ids", "service_days", "assigned_tech_user_ids")}
    r = _send(admin, bad_send)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "CONFIRM_TOKEN_FILTERS_MISMATCH"


def test_preview_and_send_with_filter_roundtrip(seeded_pair):
    """The exact UI flow the fix enables — preview with a filter,
    send with the SAME filter, batch runs against the filtered
    audience and completes normally."""
    admin = _login("admin@aquaterra.com")
    prev = _preview(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "roundtrip",
        "body": "roundtrip",
    })
    assert prev.status_code == 200, prev.text
    # Exactly the 2 seeded customers match the filter.
    est = prev.json()["estimated_recipients"]
    assert est["email"] == 2, prev.json()
    tok = prev.json()["confirm_token"]

    r = _send(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "roundtrip",
        "body": "roundtrip",
        "confirm_token": tok,
    })
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    assert r.json()["queued_email"] == 2


def test_send_no_filters_still_works(seeded_pair):
    """Regression guard — the pre-existing no-filter happy path stays
    green through the fix."""
    admin = _login("admin@aquaterra.com")
    prev = _preview(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "subject": "no-filter",
        "body": "no-filter",
    })
    assert prev.status_code == 200
    tok = prev.json()["confirm_token"]
    est_email = prev.json()["estimated_recipients"]["email"]
    assert est_email >= 2  # our seeded pair + any pre-existing customers

    r = _send(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "subject": "no-filter",
        "body": "no-filter",
        "confirm_token": tok,
    })
    assert r.status_code == 200
    assert r.json()["queued_email"] == est_email


def test_background_fanout_writes_marketing_deliveries(seeded_pair):
    """Prove the fanout writes rows the batches page can render.
    This is the "not sending" acceptance test — 400s from the
    signature guard used to prevent the batch from ever running."""
    import time as _time
    # Purge any recent batches to avoid the rate-limit window.
    _sync_db.mass_messaging_batches.delete_many({"tenant_id": seeded_pair["tenant_id"]})

    admin = _login("admin@aquaterra.com")
    prev = _preview(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "fanout",
        "body": "fanout body",
    })
    tok = prev.json()["confirm_token"]

    r = _send(admin, {
        "channels": ["email"],
        "audience": "all_active_customers",
        "audience_status": "active",
        "category_ids": [seeded_pair["category_id"]],
        "service_days": [],
        "assigned_tech_user_ids": [],
        "subject": "fanout",
        "body": "fanout body",
        "confirm_token": tok,
    })
    assert r.status_code == 200
    batch_id = r.json()["batch_id"]

    # Wait for background fanout to complete (bounded).
    for _ in range(20):
        _time.sleep(0.3)
        b = _sync_db.mass_messaging_batches.find_one({"id": batch_id}, {"_id": 0, "status": 1, "stats": 1})
        if b and b.get("status") == "completed":
            break
    assert b is not None and b.get("status") == "completed", b
    dels = list(_sync_db.marketing_deliveries.find(
        {"batch_id": batch_id}, {"_id": 0},
    ))
    assert len(dels) == 2
    for d in dels:
        assert d["channel"] == "email"
        assert d["delivery_status"] in ("sent", "queued", "mocked", "suppressed")
