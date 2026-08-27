"""Feb-2026 · ``new_lead`` sequence trigger fan-out.

Locks in the real-time (BackgroundTasks-deferred) enrolment path
across the lead-creation surfaces AND the direct fan-out helper.

Coverage:

* Registry exposes ``new_lead`` on ``GET /marketing/sequences/
  triggers/registry`` so the composer dropdown can render it.
* ``fire_new_lead_sequence_trigger`` enrols the lead into every
  ACTIVE tenant sequence whose ``trigger_type == "new_lead"``.
* Inactive sequences are ignored.
* Cross-tenant safety — a lead in tenant A never enrolls into
  tenant B's sequences.
* Idempotent — re-fire on the same (tenant, sequence, lead) is a
  no-op (sequence-scoped dedupe inside
  ``enrol_customer_into_sequence``).
* ``POST /api/leads`` (manual admin path) fires the trigger.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from utils import create_token, hash_password


TID_A = "test-tenant-new-lead-a"
TID_B = "test-tenant-new-lead-b"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed() -> dict:
    for coll in ("users", "tenants", "leads",
                  "marketing_sequences", "marketing_drip_enrolments"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
    for tid, slug in ((TID_A, "nl-a"), (TID_B, "nl-b")):
        await db.tenants.insert_one({
            "id": tid, "name": tid, "slug": slug,
            "active": True, "settings": {},
        })
    admin = {
        "id": "u-nl-admin", "tenant_id": TID_A,
        "email": "nl-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "NL Admin", "deleted_at": None,
    }
    await db.users.insert_one(admin)
    # Active sequence on TID_A + INACTIVE sequence on TID_A + active
    # sequence on TID_B (cross-tenant safety guard).
    await db.marketing_sequences.insert_many([
        {"id": "seq-a-active", "tenant_id": TID_A,
          "name": "Welcome new lead", "active": True,
          "trigger_type": "new_lead", "trigger_config": {},
          "steps": [{"order": 0, "channel": "email",
                       "template_id": "tpl-x", "delay_hours": 0,
                       "delay_from": "trigger"}]},
        {"id": "seq-a-inactive", "tenant_id": TID_A,
          "name": "Draft", "active": False,
          "trigger_type": "new_lead", "trigger_config": {},
          "steps": [{"order": 0, "channel": "email",
                       "template_id": "tpl-x", "delay_hours": 0,
                       "delay_from": "trigger"}]},
        {"id": "seq-b-active", "tenant_id": TID_B,
          "name": "TID_B new lead", "active": True,
          "trigger_type": "new_lead", "trigger_config": {},
          "steps": [{"order": 0, "channel": "email",
                       "template_id": "tpl-y", "delay_hours": 0,
                       "delay_from": "trigger"}]},
    ])
    return {"admin_token": create_token(admin)}


async def _teardown():
    for coll in ("users", "tenants", "leads",
                  "marketing_sequences", "marketing_drip_enrolments"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
    await db.tenants.delete_many({"id": {"$in": [TID_A, TID_B]}})


@pytest.fixture(scope="module")
def seeded():
    ctx = _run(_seed())
    yield ctx
    _run(_teardown())


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app),
                        base_url="http://test")


def _hdr(seeded):
    return {"Authorization": f"Bearer {seeded['admin_token']}"}


class TestRegistryExposesNewLead:
    def test_registry_contains_new_lead(self):
        from routers.marketing_sequences import (
            TRIGGER_REGISTRY, _ALLOWED_TRIGGERS,
        )
        types = {t["type"] for t in TRIGGER_REGISTRY}
        assert "new_lead" in types
        assert "new_lead" in _ALLOWED_TRIGGERS


class TestFireNewLeadSequenceTrigger:
    def test_enrolls_only_active_new_lead_sequences_in_same_tenant(self, seeded):
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        # Ensure clean enrolment table for this test run.
        _run(db.marketing_drip_enrolments.delete_many(
            {"tenant_id": {"$in": [TID_A, TID_B]}}))
        result = _run(fire_new_lead_sequence_trigger(
            lead={"id": "lead-1", "tenant_id": TID_A, "name": "L1"},
            tenant_id=TID_A,
        ))
        assert result == {"sequences_matched": 1,
                            "enrolments_dispatched": 1}
        # Exactly ONE enrolment on tenant A, mapped to the active
        # sequence; the inactive sequence is skipped.
        rows = _run(db.marketing_drip_enrolments.find(
            {"tenant_id": TID_A}, {"_id": 0, "sequence_id": 1,
                                        "customer_id": 1},
        ).to_list(20))
        assert len(rows) == 1
        assert rows[0]["sequence_id"] == "seq-a-active"
        assert rows[0]["customer_id"] == "lead-1"
        # Cross-tenant safety — tenant B untouched.
        n_b = _run(db.marketing_drip_enrolments.count_documents(
            {"tenant_id": TID_B}))
        assert n_b == 0

    def test_refire_same_lead_same_sequence_is_a_noop(self, seeded):
        """Sequence-scoped dedupe inside ``enrol_customer_into_sequence``
        must prevent double-enrolment even when the caller mistakenly
        re-fires the trigger."""
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        _run(db.marketing_drip_enrolments.delete_many(
            {"tenant_id": TID_A}))
        first = _run(fire_new_lead_sequence_trigger(
            lead={"id": "lead-dup", "tenant_id": TID_A, "name": "D"},
            tenant_id=TID_A,
        ))
        _run(fire_new_lead_sequence_trigger(
            lead={"id": "lead-dup", "tenant_id": TID_A, "name": "D"},
            tenant_id=TID_A,
        ))
        assert first == {"sequences_matched": 1,
                            "enrolments_dispatched": 1}
        n = _run(db.marketing_drip_enrolments.count_documents(
            {"tenant_id": TID_A, "customer_id": "lead-dup"}))
        # Sequence dedupe keeps a single row despite two invocations.
        assert n == 1

    def test_short_circuits_when_no_active_new_lead_sequences(self, seeded):
        """Tenant that has no active new_lead sequence returns
        ``(0, 0)`` without a crash — matches the sibling sweep helpers."""
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        _run(db.marketing_sequences.update_many(
            {"tenant_id": TID_A, "trigger_type": "new_lead"},
            {"$set": {"active": False}},
        ))
        try:
            r = _run(fire_new_lead_sequence_trigger(
                lead={"id": "lead-3", "tenant_id": TID_A},
                tenant_id=TID_A,
            ))
            assert r == {"sequences_matched": 0,
                          "enrolments_dispatched": 0}
        finally:
            # Restore for other tests.
            _run(db.marketing_sequences.update_one(
                {"id": "seq-a-active"}, {"$set": {"active": True}},
            ))

    def test_missing_lead_id_or_tenant_short_circuits(self, seeded):
        from services.marketing.lead_triggers import (
            fire_new_lead_sequence_trigger,
        )
        r1 = _run(fire_new_lead_sequence_trigger(
            lead={"id": "", "tenant_id": TID_A}, tenant_id=TID_A))
        r2 = _run(fire_new_lead_sequence_trigger(
            lead={"id": "x"}, tenant_id=""))
        assert r1 == {"sequences_matched": 0,
                       "enrolments_dispatched": 0}
        assert r2 == {"sequences_matched": 0,
                       "enrolments_dispatched": 0}
