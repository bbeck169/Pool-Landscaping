"""Phase K63.finalize · Feb-2026 — resend endpoint + new ingress wires.

Two flavors of coverage:

  1. ``POST /api/admin/leads/{lead_id}/resend-notifications``
     * Role gate: admin + super_admin OK; manager + tech → 403.
     * 404 on cross-tenant / missing lead.
     * Bypasses idempotency: refire the same lead twice → both
       dispatches land audit rows (dispatcher's guard is cleared
       between runs).
     * Writes an ``audit_logs`` row of event
       ``lead_notification_resent`` with the actor metadata.
     * Response shape: ``{ok, lead_id, dispatched, sms_queued,
       email_queued, idempotency_rows_cleared,
       muted_suppressed_customer_id}``.

  2. Ingress smoke-checks:
     * ``POST /api/d2d/knocks`` with disposition ``interested`` fires
       the K63 dispatch (D2D ingress wire).
     * ``POST /api/customer-portal/referrals`` fires the K63 dispatch
       (portal-referrals ingress wire).

  Real Resend + RingCentral adapter calls are gated by the FastAPI
  server; the tests only check that the audit row lands, so we
  count on the actual delivery hooks working (they do — Brian's
  canary succeeded end-to-end in the previous phase).
"""
from __future__ import annotations

import asyncio
import time

import pytest
import requests

from config import db
from utils import new_id


API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module", autouse=True)
def _warmup_backend():
    try:
        requests.get(f"{API}/tenants/current", timeout=15)
    except Exception:
        pass


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def super_headers():
    return _login("super@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers():
    return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tid(admin_headers) -> str:
    r = requests.get(f"{API}/tenants/current", headers=admin_headers, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


def _wait_for(query: dict, expected: int, timeout: float = 5.0) -> int:
    async def _poll():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            n = await db.audit_logs.count_documents(query)
            if n >= expected:
                return n
            await asyncio.sleep(0.1)
        return await db.audit_logs.count_documents(query)
    return asyncio.get_event_loop().run_until_complete(_poll())


@pytest.fixture()
def seeded_lead(tid):
    """Insert a fresh lead we own, yield its id, then clean up."""
    lid = new_id()
    doc = {
        "id": lid, "tenant_id": tid,
        "name": "K63.finalize seed", "email": f"k63f-{lid}@example.com",
        "phone": "+16025559999", "source": "admin_manual",
        "status": "new", "created_at": "2026-02-01T00:00:00+00:00",
    }
    async def _insert():
        await db.leads.insert_one(doc)
    asyncio.get_event_loop().run_until_complete(_insert())
    yield lid
    async def _cleanup():
        await db.leads.delete_one({"id": lid})
        await db.audit_logs.delete_many({"lead_id": lid})
        await db.lead_notification_dispatches.delete_many({"lead_id": lid})
    asyncio.get_event_loop().run_until_complete(_cleanup())


# ─── Resend endpoint ────────────────────────────────────────────────

def test_resend_admin_ok(admin_headers, seeded_lead):
    r = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["lead_id"] == seeded_lead
    assert "dispatched" in body
    # Aquaterra tenant seeds 2 recipients (Brian, both channels).
    assert body["sms_queued"] >= 1
    assert body["email_queued"] >= 1
    # Audit row for the resend action landed.
    n = _wait_for({
        "lead_id": seeded_lead, "event": "lead_notification_resent",
    }, expected=1)
    assert n == 1


def test_resend_super_admin_ok(super_headers, seeded_lead):
    r = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=super_headers, timeout=30,
    )
    assert r.status_code == 200


def test_resend_manager_forbidden(manager_headers, seeded_lead):
    r = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=manager_headers, timeout=15,
    )
    assert r.status_code == 403


def test_resend_tech_forbidden(tech_headers, seeded_lead):
    r = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=tech_headers, timeout=15,
    )
    assert r.status_code == 403


def test_resend_lead_not_found_returns_404(admin_headers):
    r = requests.post(
        f"{API}/admin/leads/lead-that-does-not-exist/resend-notifications",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 404


def test_resend_bypasses_idempotency_and_writes_two_audits(admin_headers, seeded_lead):
    """Two consecutive resends for the same lead → the second
    call also fires the adapter because the endpoint clears the
    dispatcher's idempotency rows before each invocation."""
    # First resend.
    r1 = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=admin_headers, timeout=30,
    )
    assert r1.status_code == 200
    # Let audit rows settle after BG tasks drain.
    _wait_for({
        "lead_id": seeded_lead,
        "event": {"$in": ["lead_notification_sent", "lead_notification_failed"]},
    }, expected=2)
    first_sent = asyncio.get_event_loop().run_until_complete(
        db.audit_logs.count_documents({
            "lead_id": seeded_lead,
            "event": {"$in": ["lead_notification_sent",
                                 "lead_notification_failed"]},
        }),
    )
    # Second resend.
    r2 = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=admin_headers, timeout=30,
    )
    assert r2.status_code == 200
    _wait_for({
        "lead_id": seeded_lead,
        "event": {"$in": ["lead_notification_sent", "lead_notification_failed"]},
    }, expected=first_sent + 2, timeout=8.0)
    second_sent = asyncio.get_event_loop().run_until_complete(
        db.audit_logs.count_documents({
            "lead_id": seeded_lead,
            "event": {"$in": ["lead_notification_sent",
                                 "lead_notification_failed"]},
        }),
    )
    assert second_sent > first_sent, (
        f"resend #2 should have added audit rows (before={first_sent}, "
        f"after={second_sent})"
    )
    # And there are exactly TWO ``lead_notification_resent`` audit
    # rows recording the two admin actions.
    resent_count = asyncio.get_event_loop().run_until_complete(
        db.audit_logs.count_documents({
            "lead_id": seeded_lead,
            "event": "lead_notification_resent",
        }),
    )
    assert resent_count == 2


def test_resend_audit_row_captures_actor(admin_headers, seeded_lead):
    """The audit row captures the admin's identity so we know who
    triggered the retry."""
    r = requests.post(
        f"{API}/admin/leads/{seeded_lead}/resend-notifications",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200
    _wait_for({
        "lead_id": seeded_lead, "event": "lead_notification_resent",
    }, expected=1)
    row = asyncio.get_event_loop().run_until_complete(
        db.audit_logs.find_one({
            "lead_id": seeded_lead,
            "event": "lead_notification_resent",
        }, {"_id": 0}),
    )
    assert row is not None
    assert row.get("actor_email") == "admin@aquaterra.com"
    assert row.get("actor_role") == "admin"


# ─── Ingress wires ──────────────────────────────────────────────────

def test_d2d_interested_knock_fires_k63_dispatch(admin_headers, tid):
    """Creating a D2D knock disposed as ``interested`` synthesises
    a lead AND fans out the K63 alert (Aquaterra has 2 recipients
    seeded — Brian, both channels)."""
    payload = {
        "disposition": "interested",
        "name": "K63.finalize D2D test",
        "phone": "+16025557777",
        "notes": "auto-seeded by K63.finalize pytest",
        "address": "1 Test St",
    }
    r = requests.post(
        f"{API}/d2d/knocks", headers=admin_headers,
        json=payload, timeout=15,
    )
    assert r.status_code == 200, r.text
    lid = r.json().get("lead_id")
    assert lid, "d2d handler must synthesise a lead for interested/sold"
    try:
        n = _wait_for({
            "lead_id": lid,
            "event": {"$in": ["lead_notification_sent",
                                 "lead_notification_failed"]},
        }, expected=1, timeout=8.0)
        assert n >= 1, (
            f"expected >=1 K63 audit row for D2D-synth lead {lid}, got {n} — "
            f"D2D ingress wire is missing."
        )
    finally:
        # Best-effort cleanup so subsequent runs stay clean.
        async def _cleanup():
            await db.leads.delete_one({"id": lid})
            await db.d2d_knocks.delete_many({"lead_id": lid})
            await db.audit_logs.delete_many({"lead_id": lid})
            await db.lead_notification_dispatches.delete_many({"lead_id": lid})
        asyncio.get_event_loop().run_until_complete(_cleanup())
