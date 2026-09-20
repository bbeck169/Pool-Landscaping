"""Phase K31 · Feb-2026 — regression coverage for the three K31
fixes shipped together:

  1. Fix 1 — ``marketing_sequences::process_due_enrolments`` hydrates
     ``job`` + ``service_report`` into the render context when the
     enrolment carries them in ``trigger_meta``.  Fixes the
     ``"for ."`` empty-merge-tag rendering on
     ``{{SERVICE_NAME}}`` / ``{{job.*}}``.
  2. Fix 2 — ``services.comms.consent_gate.has_sms_consent`` — opt-in
     per tenant, grandfather-if-prior-successful-send.
  3. Fix 3 — ``routers.customers::_k31_audit_phone_collision`` post-
     write hook fires an ``audit_events`` row when two customers in
     the same tenant share a phone.

All three tests are in-process (no HTTP hops) so they run in the
existing sync pytest harness without requiring an event loop
reshape.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_sync = _shared_db()
API = "http://localhost:8001/api"
_TAG = "TEST_k31"

# K31 · fresh event loop + Motor client for the async-driven tests.
# Rebind the module handles inside a fixture so other test files
# aren't left holding a K31-loop-bound client.
_LOOP = asyncio.new_event_loop()
_K31_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_K31_DB = _K31_MOTOR[os.environ["DB_NAME"]]


@pytest.fixture
def rebind_db_to_k31_loop(monkeypatch):
    """Rebind ``config.db`` + module-local motor handles to a client
    bound to our K31 event loop, and auto-revert on teardown.  Only
    the tests that call ``_run(...)`` need this."""
    import config as _config_mod
    from services.comms import consent_gate as _consent_gate_mod
    from routers import marketing_sequences as _ms_mod
    monkeypatch.setattr(_config_mod, "db", _K31_DB)
    monkeypatch.setattr(_consent_gate_mod, "db", _K31_DB)
    monkeypatch.setattr(_ms_mod, "db", _K31_DB)
    yield


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _login(email: str = "admin@aquaterra.com") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_tenant() -> str:
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


# ══════════════════════════════════════════════════════════════════════
# Fix 1 — job/service_report render-context hydration
# ══════════════════════════════════════════════════════════════════════
def test_k31_fix1_render_context_hydrates_job_and_service_report(rebind_db_to_k31_loop):
    """When ``enrolment.trigger_meta`` carries ``service_report_id``
    and ``job_id``, ``process_due_enrolments`` MUST look up both docs
    and pass them into ``render_context`` so a template referencing
    ``{{SERVICE_NAME}}`` renders the real service name (not '')."""
    tid = _admin_tenant()
    cid = f"{_TAG}_cust_{uuid.uuid4().hex[:6]}"
    jid = f"{_TAG}_job_{uuid.uuid4().hex[:6]}"
    sr_id = f"{_TAG}_sr_{uuid.uuid4().hex[:6]}"
    tpl_id = f"{_TAG}_tpl_{uuid.uuid4().hex[:6]}"
    seq_id = f"{_TAG}_seq_{uuid.uuid4().hex[:6]}"
    en_id = f"{_TAG}_en_{uuid.uuid4().hex[:6]}"
    try:
        _sync.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "TEST_k31 Fix1", "phone": "+15550000001",
            "first_name": "K31",
        })
        _sync.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "service_name": "TEST_k31 pool cleaning",
            "service_type": "pool",
            "status": "completed",
        })
        _sync.service_reports.insert_one({
            "id": sr_id, "tenant_id": tid, "job_id": jid,
        })
        _sync.marketing_templates.insert_one({
            "id": tpl_id, "tenant_id": tid,
            "category": "service_completed", "channel": "sms",
            "subject": "", "body": "Hi, we finished your visit for {{SERVICE_NAME}}.",
        })
        _sync.marketing_sequences.insert_one({
            "id": seq_id, "tenant_id": tid, "name": "TEST_k31 seq",
            "trigger_type": "service_completed", "active": True,
            "steps": [
                {"id": "s1", "channel": "sms",
                 "template_id": tpl_id, "delay_hours": 0},
            ],
        })
        _sync.marketing_drip_enrolments.insert_one({
            "id": en_id, "tenant_id": tid, "sequence_id": seq_id,
            "customer_id": cid, "current_step": 0, "status": "active",
            "trigger_source": "service_completed",
            "trigger_meta": {"service_report_id": sr_id, "job_id": jid},
            "next_send_at": "2020-01-01T00:00:00+00:00",
            "history": [],
        })

        from routers import marketing_sequences as ms

        # The tick fires the SMS through the RC adapter which is
        # mocked in preview.  Rather than monkeypatch the adapter,
        # we assert on the rendered body persisted into
        # ``marketing_deliveries`` — that row captures the exact
        # rendered ``body_rendered`` right after the K31 hydration.
        _run(ms.process_due_enrolments(tenant_id=tid))

        delivery = _sync.marketing_deliveries.find_one(
            {"enrolment_id": en_id},
            {"_id": 0, "body_rendered": 1, "step_index": 1},
        )
        assert delivery is not None, (
            "sequence tick didn't produce a marketing_deliveries row"
        )
        body = delivery.get("body_rendered") or ""
        assert "TEST_k31 pool cleaning" in body, (
            f"Fix 1 regression: SERVICE_NAME wasn't hydrated. "
            f"Rendered body: {body!r}"
        )
        # The '.' rendering symptom must be gone.
        assert "for ." not in body, (
            f"Fix 1 regression: template still renders 'for .' — "
            f"got {body!r}"
        )
    finally:
        _sync.customers.delete_one({"id": cid})
        _sync.jobs.delete_one({"id": jid})
        _sync.service_reports.delete_one({"id": sr_id})
        _sync.marketing_templates.delete_one({"id": tpl_id})
        _sync.marketing_sequences.delete_one({"id": seq_id})
        _sync.marketing_drip_enrolments.delete_one({"id": en_id})
        _sync.marketing_deliveries.delete_many({"enrolment_id": en_id})


# ══════════════════════════════════════════════════════════════════════
# Fix 2 — affirmative consent gate
# ══════════════════════════════════════════════════════════════════════
def test_k31_fix2_consent_gate_defaults_open_when_tenant_toggle_off(rebind_db_to_k31_loop):
    """With ``tenants.sms_consent_gate_enabled`` absent / False the
    gate MUST return True (no behaviour change for tenants that
    haven't opted in)."""
    from services.comms.consent_gate import has_sms_consent
    tid = _admin_tenant()
    # The seeded admin tenant has no sms_consent_gate_enabled — should
    # return True regardless of the customer's consent state.
    assert _run(has_sms_consent(tid, "any-cid", category="transactional")) is True


def test_k31_fix2_consent_gate_blocks_no_record_when_toggle_on(rebind_db_to_k31_loop):
    """With the tenant toggle ON, a customer with neither
    ``sms_consent_captured_at`` nor a prior successful SMS MUST be
    blocked."""
    from services.comms.consent_gate import has_sms_consent
    tid = _admin_tenant()
    cid = f"{_TAG}_cust_gate_{uuid.uuid4().hex[:6]}"
    try:
        _sync.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "TEST_k31 gate-blocked", "phone": "+15550000002",
        })
        _sync.tenants.update_one(
            {"id": tid}, {"$set": {"sms_consent_gate_enabled": True}},
        )
        assert _run(has_sms_consent(tid, cid, category="transactional")) is False
    finally:
        _sync.tenants.update_one(
            {"id": tid}, {"$unset": {"sms_consent_gate_enabled": ""}},
        )
        _sync.customers.delete_one({"id": cid})


def test_k31_fix2_consent_gate_allows_explicit_consent(rebind_db_to_k31_loop):
    """Toggle ON + ``sms_consent_captured_at`` set → True."""
    from services.comms.consent_gate import has_sms_consent
    tid = _admin_tenant()
    cid = f"{_TAG}_cust_ok_{uuid.uuid4().hex[:6]}"
    try:
        _sync.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "TEST_k31 gate-ok", "phone": "+15550000003",
            "sms_consent_captured_at":
                datetime.now(timezone.utc).isoformat(),
        })
        _sync.tenants.update_one(
            {"id": tid}, {"$set": {"sms_consent_gate_enabled": True}},
        )
        assert _run(has_sms_consent(tid, cid, category="transactional")) is True
    finally:
        _sync.tenants.update_one(
            {"id": tid}, {"$unset": {"sms_consent_gate_enabled": ""}},
        )
        _sync.customers.delete_one({"id": cid})


def test_k31_fix2_consent_gate_grandfathers_prior_successful_send(rebind_db_to_k31_loop):
    """Toggle ON + prior successful SMS in ``notification_dispatch_log``
    → True (grandfather rule)."""
    from services.comms.consent_gate import has_sms_consent
    tid = _admin_tenant()
    cid = f"{_TAG}_cust_grand_{uuid.uuid4().hex[:6]}"
    ndl_id = f"{_TAG}_ndl_{uuid.uuid4().hex[:6]}"
    try:
        _sync.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "TEST_k31 grandfathered", "phone": "+15550000004",
        })
        _sync.notification_dispatch_log.insert_one({
            "id": ndl_id, "tenant_id": tid, "recipient_id": cid,
            "channel": "sms", "provider_status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
        _sync.tenants.update_one(
            {"id": tid}, {"$set": {"sms_consent_gate_enabled": True}},
        )
        assert _run(has_sms_consent(tid, cid, category="transactional")) is True
    finally:
        _sync.tenants.update_one(
            {"id": tid}, {"$unset": {"sms_consent_gate_enabled": ""}},
        )
        _sync.customers.delete_one({"id": cid})
        _sync.notification_dispatch_log.delete_one({"id": ndl_id})


# ══════════════════════════════════════════════════════════════════════
# Fix 3 — phone-collision audit hook
# ══════════════════════════════════════════════════════════════════════
def test_k31_fix3_phone_collision_writes_audit_event():
    """Two customers created with the same phone in the same tenant
    MUST cause an ``audit_events`` row with
    ``event_type="customer_phone_collision"`` on the second create."""
    tok = _login()
    tid = _admin_tenant()
    phone = f"+1555{uuid.uuid4().hex[:7]}"
    inserted_ids: list[str] = []
    try:
        # First insert — no collision. Use the API so
        # ``_apply_multi_contact`` fires exactly as in production.
        r1 = requests.post(
            f"{API}/customers", json={
                "name": f"TEST_k31 First {uuid.uuid4().hex[:6]}",
                "phone": phone,
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r1.status_code == 200, r1.text
        c1 = r1.json()["id"]
        inserted_ids.append(c1)

        # No collision audit yet.
        pre = _sync.audit_events.count_documents({
            "tenant_id": tid, "event_type": "customer_phone_collision",
            "payload.phones": phone,
        })
        assert pre == 0

        # Second insert — same phone → must fire the audit.
        r2 = requests.post(
            f"{API}/customers", json={
                "name": f"TEST_k31 Collision {uuid.uuid4().hex[:6]}",
                "phone": phone,
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r2.status_code == 200, r2.text
        c2 = r2.json()["id"]
        inserted_ids.append(c2)

        # Audit row is written non-blockingly; it's still synchronous
        # inside the same request, so it's present by the time the
        # HTTP call returns.
        rows = list(_sync.audit_events.find({
            "tenant_id": tid, "event_type": "customer_phone_collision",
            "payload.customer_id": c2,
        }))
        assert len(rows) == 1, (
            f"expected exactly one phone-collision audit, got {len(rows)}"
        )
        payload = rows[0]["payload"]
        assert phone in payload["phones"]
        assert c1 in payload["colliding_customer_ids"]
    finally:
        for cid in inserted_ids:
            _sync.customers.delete_one({"id": cid})
        _sync.audit_events.delete_many({
            "tenant_id": tid, "event_type": "customer_phone_collision",
            "payload.phones": phone,
        })


def test_k31_fix3_no_audit_when_phone_is_unique():
    """A customer create with a phone no other customer holds MUST
    NOT fire the audit event."""
    tok = _login()
    tid = _admin_tenant()
    phone = f"+1555{uuid.uuid4().hex[:7]}"
    try:
        r = requests.post(
            f"{API}/customers", json={
                "name": f"TEST_k31 Unique {uuid.uuid4().hex[:6]}",
                "phone": phone,
            },
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        try:
            hits = _sync.audit_events.count_documents({
                "tenant_id": tid, "event_type": "customer_phone_collision",
                "payload.customer_id": cid,
            })
            assert hits == 0
        finally:
            _sync.customers.delete_one({"id": cid})
    finally:
        pass
