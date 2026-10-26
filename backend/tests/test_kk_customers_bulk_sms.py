"""Ticket KK · Feb-2026 — ``POST /customers/bulk-sms`` endpoint tests.

Covers the KK contract (operator picks N rows on the Customers list,
hits "Mass Text", server resolves the ids tenant-scoped, pre-counts
opt-out / no-phone / cross-tenant skips, and schedules a background
fanout). All happy-path assertions run against an **ephemeral test
tenant with ``is_real`` unset** so the K72 real-tenant-non-prod guard
doesn't short-circuit the send — mirrors how KK's underlying
mass_messaging primitives already handle environment-level safety.

Coverage:
    1. Happy path — admin fires at [c_phone_in, c_opt_out, c_no_phone,
       b1_cross_tenant] and the response envelope breakdown is
       correct (resolved=3, skipped_cross_tenant=1, skipped_no_phone=1,
       skipped_opt_out=1, queued=1).
    2. Template_id resolves tenant-scoped (admin on tenant A loads
       tenant A's SMS template → 200).
    3. Cross-tenant template_id rejected (admin on tenant A uses
       tenant B's SMS template → 404 from ``_load_template``).
    4. Non-admin → 403.
    5. Rate-limit — second send inside the 5-min window → 429 with
       the ``RATE_LIMITED`` code (shares the ``mass_messaging_batches``
       window with ``/mass-messaging/send``).
    6. ``message`` and ``template_id`` both missing → 400.
    7. K72 guards — grep-locked check that both the CI_BLOCK env +
       the real-tenant-non-prod guard appear verbatim in the handler
       source (future refactor can't quietly drop either).
"""
from __future__ import annotations

import inspect
import os
import time
import uuid

import pytest
import requests

from tests._shared_mongo import shared_db as _shared_db
from utils import hash_password


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


# ─── Fixtures ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def _sync_db():
    return _shared_db()


@pytest.fixture(scope="module")
def kk_fixture(_sync_db):
    """Seed two ephemeral tenants + an admin / tech user on tenant A +
    four customers (c_phone_in, c_opt_out, c_no_phone, b1_foreign) +
    one SMS marketing template on each tenant.

    Teardown wipes every ``KK_`` / ``kk-`` stamped doc so repeated
    runs stay idempotent.
    """
    suffix = uuid.uuid4().hex[:8]
    tenant_a_id = f"kk-tenant-a-{suffix}"
    tenant_b_id = f"kk-tenant-b-{suffix}"
    admin_email = f"kk-admin-{suffix}@example.com"
    tech_email = f"kk-tech-{suffix}@example.com"
    admin_pw = "KK-password-123!"
    tech_pw = "KK-password-123!"

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _sync_db.tenants.insert_many([
        {"id": tenant_a_id, "slug": f"kk-a-{suffix}",
          "name": "KK Fixture A", "active": True, "created_at": now},
        {"id": tenant_b_id, "slug": f"kk-b-{suffix}",
          "name": "KK Fixture B", "active": True, "created_at": now},
    ])
    _sync_db.users.insert_many([
        {
            "id": f"kk-admin-{suffix}", "email": admin_email,
            "name": "KK Admin", "role": "admin",
            "password_hash": hash_password(admin_pw),
            "tenant_id": tenant_a_id, "tenant_ids": [tenant_a_id],
            "active": True, "created_at": now,
        },
        {
            "id": f"kk-tech-{suffix}", "email": tech_email,
            "name": "KK Tech", "role": "technician",
            "password_hash": hash_password(tech_pw),
            "tenant_id": tenant_a_id, "tenant_ids": [tenant_a_id],
            "active": True, "created_at": now,
        },
    ])

    c_phone_in = f"kk-cust-phone-in-{suffix}"
    c_opt_out = f"kk-cust-opt-out-{suffix}"
    c_no_phone = f"kk-cust-no-phone-{suffix}"
    b1_foreign = f"kk-cust-foreign-{suffix}"
    _sync_db.customers.insert_many([
        {"id": c_phone_in, "tenant_id": tenant_a_id,
          "name": "KK Phone-In", "phone": "+14805550101",
          "email": "", "is_active": True, "created_at": now},
        {"id": c_opt_out, "tenant_id": tenant_a_id,
          "name": "KK Opt-Out", "phone": "+14805550102",
          "email": "", "is_active": True, "created_at": now},
        {"id": c_no_phone, "tenant_id": tenant_a_id,
          "name": "KK No-Phone", "phone": "",
          "email": "", "is_active": True, "created_at": now},
        {"id": b1_foreign, "tenant_id": tenant_b_id,
          "name": "KK Foreign", "phone": "+14805550103",
          "email": "", "is_active": True, "created_at": now},
    ])
    # Opt-out signal: ``routers.marketing_preferences.is_suppressed``
    # looks up by (tenant_id, channel, address) with ``deleted_at:
    # None``. Seed a marketing_suppressions row keyed on the opt-out
    # customer's phone number so the pre-count path flags them as
    # ``skipped_opt_out``.
    _sync_db.marketing_suppressions.insert_one({
        "id": f"kk-sup-{suffix}",
        "tenant_id": tenant_a_id,
        "channel": "sms",
        "address": "+14805550102",
        "category": "marketing",
        "deleted_at": None,
        "created_at": now,
    })

    tpl_a_id = f"kk-tpl-a-{suffix}"
    tpl_b_id = f"kk-tpl-b-{suffix}"
    _sync_db.marketing_templates.insert_many([
        {"id": tpl_a_id, "tenant_id": tenant_a_id,
          "channel": "sms", "name": "KK Reminder A",
          "body": "KK template-A body", "created_at": now},
        {"id": tpl_b_id, "tenant_id": tenant_b_id,
          "channel": "sms", "name": "KK Reminder B",
          "body": "KK template-B body", "created_at": now},
    ])

    yield {
        "tenant_a_id": tenant_a_id, "tenant_b_id": tenant_b_id,
        "admin_email": admin_email, "admin_pw": admin_pw,
        "tech_email": tech_email, "tech_pw": tech_pw,
        "c_phone_in": c_phone_in, "c_opt_out": c_opt_out,
        "c_no_phone": c_no_phone, "b1_foreign": b1_foreign,
        "tpl_a_id": tpl_a_id, "tpl_b_id": tpl_b_id,
        "suffix": suffix,
    }

    # ── teardown ────────────────────────────────────────────────
    _sync_db.tenants.delete_many({"id": {"$in": [tenant_a_id, tenant_b_id]}})
    _sync_db.users.delete_many(
        {"email": {"$in": [admin_email, tech_email]}}
    )
    _sync_db.customers.delete_many(
        {"id": {"$in": [c_phone_in, c_opt_out, c_no_phone, b1_foreign]}}
    )
    _sync_db.marketing_suppressions.delete_many(
        {"tenant_id": {"$in": [tenant_a_id, tenant_b_id]}}
    )
    _sync_db.marketing_templates.delete_many(
        {"id": {"$in": [tpl_a_id, tpl_b_id]}}
    )
    _sync_db.mass_messaging_batches.delete_many(
        {"tenant_id": {"$in": [tenant_a_id, tenant_b_id]}}
    )


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


def _purge_rate_limit(_sync_db, tenant_id: str) -> None:
    """Clear ``mass_messaging_batches`` so back-to-back KK tests
    don't 429 each other on the shared 5-min window."""
    _sync_db.mass_messaging_batches.delete_many({"tenant_id": tenant_id})


# ─── 1. Happy path · counts resolve correctly ────────────────────
def test_happy_path_counts_resolve_correctly(kk_fixture, _sync_db):
    tok = _login(kk_fixture["admin_email"], kk_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={
            "customer_ids": [
                kk_fixture["c_phone_in"],
                kk_fixture["c_opt_out"],
                kk_fixture["c_no_phone"],
                kk_fixture["b1_foreign"],
            ],
            "message": "KK happy-path message",
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["selected_count"] == 4
    # Foreign id dropped silently (cross-tenant safety).
    assert body["resolved_count"] == 3
    assert body["skipped_cross_tenant"] == 1
    # c_no_phone has empty phone → skipped before adapter call.
    assert body["skipped_no_phone"] == 1
    # c_opt_out matches the marketing_suppressions row seeded in the
    # fixture → counted as opt-out, not queued.
    assert body["skipped_opt_out"] == 1
    assert body["queued"] == 1
    assert body["status"] == "running"
    assert body["batch_id"]
    # Audit row landed in the shared mass_messaging_batches collection
    # with the KK ``audience`` sentinel.
    batch = _sync_db.mass_messaging_batches.find_one(
        {"id": body["batch_id"]}, {"_id": 0}
    )
    assert batch is not None
    assert batch["tenant_id"] == kk_fixture["tenant_a_id"]
    assert batch["audience"] == "customers_bulk_sms"
    assert batch["channels"] == ["sms"]
    assert batch["queued_sms"] == 1


# ─── 2. Template_id resolves tenant-scoped ───────────────────────
def test_template_id_resolves_tenant_scoped(kk_fixture, _sync_db):
    tok = _login(kk_fixture["admin_email"], kk_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={
            "customer_ids": [kk_fixture["c_phone_in"]],
            "template_id": kk_fixture["tpl_a_id"],
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolved_count"] == 1
    assert body["queued"] == 1


# ─── 3. Cross-tenant template_id rejected ────────────────────────
def test_template_id_cross_tenant_rejected(kk_fixture, _sync_db):
    tok = _login(kk_fixture["admin_email"], kk_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={
            "customer_ids": [kk_fixture["c_phone_in"]],
            "template_id": kk_fixture["tpl_b_id"],  # belongs to tenant B
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 404, r.text


# ─── 4. Non-admin → 403 ──────────────────────────────────────────
def test_non_admin_rejected(kk_fixture, _sync_db):
    tok = _login(kk_fixture["tech_email"], kk_fixture["tech_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={
            "customer_ids": [kk_fixture["c_phone_in"]],
            "message": "should 403",
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 403, r.text


# ─── 5. Rate-limit — second send inside the window → 429 ─────────
def test_rate_limit_within_window(kk_fixture, _sync_db):
    tok = _login(kk_fixture["admin_email"], kk_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r1 = requests.post(
        f"{API}/customers/bulk-sms",
        json={"customer_ids": [kk_fixture["c_phone_in"]],
              "message": "KK rate-limit first"},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r1.status_code == 200, r1.text
    r2 = requests.post(
        f"{API}/customers/bulk-sms",
        json={"customer_ids": [kk_fixture["c_phone_in"]],
              "message": "KK rate-limit second"},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r2.status_code == 429, r2.text
    assert r2.json()["detail"]["code"] == "RATE_LIMITED"


# ─── 6. Payload must have `message` or `template_id` ─────────────
def test_requires_message_or_template(kk_fixture, _sync_db):
    tok = _login(kk_fixture["admin_email"], kk_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, kk_fixture["tenant_a_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={"customer_ids": [kk_fixture["c_phone_in"]]},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BULK_SMS_EMPTY_PAYLOAD"


# ─── 7. K72 guards grep-locked ───────────────────────────────────
def test_k72_guards_grep_locked():
    """The KK handler must carry both K72 belts verbatim so a future
    refactor can't quietly drop the real-tenant-non-prod or CI block.
    """
    from routers import customers_bulk_sms as _kk
    src = inspect.getsource(_kk)
    assert "CI_BLOCK_MASS_MESSAGING" in src
    assert "K72_CI_MASS_MESSAGING_BLOCKED" in src
    assert "K72_REAL_TENANT_NON_PROD_BLOCKED" in src
