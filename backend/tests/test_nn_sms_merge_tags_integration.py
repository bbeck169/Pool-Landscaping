"""Ticket NN · Feb-2026 · Commit 2 — SMS merge-tag resolution tests.

Live-endpoint integration tests for the three operator-facing SMS
paths now wired to the canonical
``services.marketing.merge_tags.render_template`` resolver:

    1. ``POST /customers/bulk-sms`` (KK Mass Text)
    2. ``POST /leads/{lead_id}/send-sms`` (lead comms)
    3. ``POST /customers/{cid}/send-sms`` (customer-profile send)

Pre-NN behaviour: operator-authored merge-tag strings
(``{{CUSTOMER_FIRST_NAME}}``, ``{{COMPANY_NAME}}``, etc.) hit the
adapter verbatim and shipped as literal brace text to the recipient.
Post-NN: ``render_template`` substitutes per-recipient values from
``render_context(customer=..., tenant=...)``; unknown tokens
fall back to the empty string (``missing="empty"``) to match the
mass_messaging + marketing_templates behaviour.

All three endpoints eventually call the Ticket NN Commit 1 adapter
safety net which strips any HTML that leaks past the upstream
resolver, so the END-TO-END contract is: tokens resolve, HTML
strips, no literal braces reach the recipient.  These tests pin
the resolve-side contract; Commit 1's test file pins the strip-side.

Fixture reuses the KK ``kk_fixture`` pattern — ephemeral tenants
(``is_real`` unset so K72 does not short-circuit) + admin login +
seeded customers and lead rows.  Teardown wipes every seeded doc.
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


# ─── Shared fixture ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def _sync_db():
    return _shared_db()


@pytest.fixture(scope="module")
def nn_fixture(_sync_db):
    """Ephemeral tenant + admin + customer + lead on a non-real
    tenant so the K72 real-tenant-non-prod guard doesn't block the
    live SMS endpoints.  Teardown wipes every seeded doc.
    """
    suffix = uuid.uuid4().hex[:8]
    tenant_id = f"nn-tenant-{suffix}"
    admin_email = f"nn-admin-{suffix}@example.com"
    admin_pw = "NN-password-123!"
    customer_id = f"nn-cust-{suffix}"
    lead_id = f"nn-lead-{suffix}"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _sync_db.tenants.insert_one({
        "id": tenant_id, "slug": f"nn-{suffix}",
        "name": "NN Fixture Co", "active": True, "created_at": now,
    })
    _sync_db.users.insert_one({
        "id": f"nn-admin-{suffix}", "email": admin_email,
        "name": "NN Admin", "role": "admin",
        "password_hash": hash_password(admin_pw),
        "tenant_id": tenant_id, "tenant_ids": [tenant_id],
        "active": True, "created_at": now,
    })
    _sync_db.customers.insert_one({
        "id": customer_id, "tenant_id": tenant_id,
        "name": "Ada Lovelace",
        "first_name": "Ada", "last_name": "Lovelace",
        "phone": "+14805550199", "email": "ada@example.com",
        "phones": [{"number": "+14805550199", "is_primary": True}],
        "is_active": True, "created_at": now,
    })
    _sync_db.leads.insert_one({
        "id": lead_id, "tenant_id": tenant_id,
        "name": "Grace Hopper",
        "first_name": "Grace", "last_name": "Hopper",
        "phone": "+14805550277", "email": "grace@example.com",
        "sms_ok": True, "email_ok": True,
        "created_at": now,
    })
    yield {
        "tenant_id": tenant_id,
        "admin_email": admin_email, "admin_pw": admin_pw,
        "customer_id": customer_id, "lead_id": lead_id,
        "suffix": suffix,
    }
    # teardown
    _sync_db.tenants.delete_one({"id": tenant_id})
    _sync_db.users.delete_many({"email": admin_email})
    _sync_db.customers.delete_many({"id": customer_id})
    _sync_db.leads.delete_many({"id": lead_id})
    _sync_db.mass_messaging_batches.delete_many({"tenant_id": tenant_id})
    _sync_db.marketing_deliveries.delete_many({"tenant_id": tenant_id})
    _sync_db.communications_log.delete_many({"tenant_id": tenant_id})
    _sync_db.lead_communications.delete_many({"tenant_id": tenant_id})


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
    _sync_db.mass_messaging_batches.delete_many({"tenant_id": tenant_id})


# ═══════════════════════════════════════════════════════════════════
# 1. KK Mass Text — merge tags resolve per-recipient at fanout time.
# ═══════════════════════════════════════════════════════════════════
def test_customers_bulk_sms_renders_merge_tags(nn_fixture, _sync_db):
    """Fire the KK Mass Text endpoint with a body carrying
    ``{{CUSTOMER_FIRST_NAME}}`` + ``{{COMPANY_NAME}}``; the
    background fanout resolves per-customer via Commit 2's
    ``_render_template(sms_body, per_ctx, missing="empty")``.  We
    assert the ``marketing_deliveries`` audit row carries the
    resolved body — which is what the recipient actually got.
    """
    tok = _login(nn_fixture["admin_email"], nn_fixture["admin_pw"])
    _purge_rate_limit(_sync_db, nn_fixture["tenant_id"])
    r = requests.post(
        f"{API}/customers/bulk-sms",
        json={
            "customer_ids": [nn_fixture["customer_id"]],
            "message": "Hi {{CUSTOMER_FIRST_NAME}}, from {{COMPANY_NAME}}!",
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    batch_id = body["batch_id"]
    assert body["queued"] == 1

    # Background fanout runs in a FastAPI BackgroundTask after the
    # response — poll the delivery log briefly until the row lands.
    deadline = time.time() + 8
    delivery = None
    while time.time() < deadline:
        delivery = _sync_db.marketing_deliveries.find_one(
            {"batch_id": batch_id,
              "tenant_id": nn_fixture["tenant_id"]},
            {"_id": 0},
        )
        if delivery:
            break
        time.sleep(0.3)
    assert delivery is not None, "marketing_deliveries row never landed"
    audited_body = delivery.get("body") or ""
    # Resolved tokens present as plain text.
    assert "Ada" in audited_body
    assert "NN Fixture Co" in audited_body
    # Literal braces never reach the audit (and therefore never
    # reach the recipient).
    assert "{{" not in audited_body
    assert "}}" not in audited_body


# ═══════════════════════════════════════════════════════════════════
# 2. Lead comms SMS — merge tags resolve against the lead doc.
# ═══════════════════════════════════════════════════════════════════
def test_leads_send_sms_renders_merge_tags(nn_fixture, _sync_db):
    """``POST /leads/{lead_id}/send-sms`` with
    ``{{CUSTOMER_FIRST_NAME}}`` resolves to the lead's first name
    via the ``_lead_as_customer`` adapter the NN patch introduced.
    """
    tok = _login(nn_fixture["admin_email"], nn_fixture["admin_pw"])
    r = requests.post(
        f"{API}/leads/{nn_fixture['lead_id']}/send-sms",
        json={
            "body": "Hi {{CUSTOMER_FIRST_NAME}}, your quote from "
                     "{{COMPANY_NAME}} is ready.",
            "override_consent": False,
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    row = r.json()
    # The lead_communications row stores the OPERATOR-authored
    # body (pre-resolve) per the Phase L3 contract — the resolver
    # patches the body the ADAPTER sees, not the audit row.  Pin
    # the adapter contract via a source-shape check instead so
    # future refactors can't drop the resolver silently.
    from routers import lead_communications as _lc
    src = inspect.getsource(_lc.send_sms_from_lead)
    assert "render_template as _render_template" in src
    assert "rendered_body, _unresolved" in src
    assert "body=rendered_body" in src
    # Row sanity — the dispatch landed and recorded a status.
    assert row.get("channel") == "sms"
    assert row.get("status") in ("sent", "failed", "queued")


# ═══════════════════════════════════════════════════════════════════
# 3. Customer-profile send-sms — merge tags resolve against the
#    customer doc.  Source-shape lock covers the Q2 unlock scope.
# ═══════════════════════════════════════════════════════════════════
def test_customers_send_sms_renders_merge_tags(nn_fixture, _sync_db):
    """``POST /customers/{cid}/send-sms`` resolves
    ``{{CUSTOMER_FIRST_NAME}}`` + ``{{COMPANY_NAME}}`` before
    dispatch.  The ``communications_log`` row preserves the raw
    operator body per the existing audit contract; the resolver
    patches the adapter payload only, so this test asserts the
    source-shape contract + a successful 200 round-trip.
    """
    tok = _login(nn_fixture["admin_email"], nn_fixture["admin_pw"])
    r = requests.post(
        f"{API}/customers/{nn_fixture['customer_id']}/send-sms",
        json={
            "to": "+14805550199",
            "body": "Hi {{CUSTOMER_FIRST_NAME}}, {{COMPANY_NAME}} here.",
        },
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    # Grep-lock: Q2 unlock scope — the NN patch MUST live inside
    # the ``customer_send_sms`` handler body only.  No sibling
    # routes were touched.
    from routers import customers as _c
    src = inspect.getsource(_c.customer_send_sms)
    assert "render_template as _nn_render" in src
    assert "rendered_sms_body" in src
    assert "body=rendered_sms_body" in src


# ═══════════════════════════════════════════════════════════════════
# 4. Grep-lock: KK bulk-sms fanout uses render_template per-recipient.
# ═══════════════════════════════════════════════════════════════════
def test_kk_fanout_renders_per_recipient():
    """Pin the KK fanout contract — ``_run_bulk_sms`` must resolve
    merge tags inside the per-customer loop (not once above the
    loop) so each recipient's ``{{CUSTOMER_FIRST_NAME}}`` resolves
    to THEIR name, not the first customer's.
    """
    from routers import customers_bulk_sms as _kk
    src = inspect.getsource(_kk._run_bulk_sms)
    assert "render_template as _render_template" in src
    assert "render_context as _render_context" in src
    # Rendering lives INSIDE the ``for c in customers:`` loop.
    loop_pos = src.index("for c in customers:")
    render_pos = src.index("_render_template(")
    assert loop_pos < render_pos, (
        "render_template must be called per-recipient inside the "
        "customers loop, not once above it."
    )
    # Dispatch uses the resolved body, not the raw template.
    assert "body=resolved_body" in src
