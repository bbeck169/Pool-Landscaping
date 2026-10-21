"""TD-98-be-sources · Phase 2 · Integration — mixed-source super-timeline.

Per audit §7.a Integration:
  1. Mixed-source fixture interleaves dispatch + audit + lead_comm
     correctly by ``occurred_at DESC``.
  2. Dedupe doesn't drop legitimate dispatch rows — new ``ref_type``
     values (``notification_dispatch`` + ``audit_event``) do NOT
     collide with existing marketing/invoice/estimate ref_types.
  3. Admin vs. portal field-strip holds across the full merge.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = f"td98bes_int_{uuid.uuid4().hex[:6]}_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db():
    import config
    config.db = _DB
    import routers.communication_timeline as mod
    mod.db = _DB


TENANT = f"{PFX}tenA"
CID = f"{PFX}cust"


async def _seed_customer():
    await _DB.customers.insert_one({
        "id": CID, "tenant_id": TENANT, "name": "Test",
        "email": "c@ex.com", "phone": "+15551111", "contacts": [],
    })


async def _wipe():
    rx = {"$regex": f"^{PFX}"}
    for c in ("notification_dispatch_log", "audit_events", "customers",
                "leads", "quotes", "marketing_deliveries", "call_logs",
                "customer_notes", "jobs", "lead_communications",
                "sms_inbound"):
        await _DB[c].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )


@pytest.fixture(autouse=True)
def _clean():
    _patch_db()
    _run(_wipe())
    yield
    _run(_wipe())


async def _build(role):
    from routers.communication_timeline import _build_full_timeline
    customer = await _DB.customers.find_one({"id": CID}, {"_id": 0})
    return await _build_full_timeline(
        customer, TENANT, None, None, None, role,
    )


# ─── §1 · Interleaving by occurred_at DESC ───────────────────────
def test_mixed_sources_interleave_desc_by_occurred_at():
    _run(_seed_customer())
    # Dispatch at Feb-05.
    _run(_DB.notification_dispatch_log.insert_one({
        "id": f"{PFX}d1", "tenant_id": TENANT,
        "channel": "email", "recipient_id": CID,
        "resolved_address": "c@ex.com", "status": "sent",
        "sent_at": "2026-02-05T10:00:00+00:00",
        "dedupe_key": f"{PFX}d1-dk",
        "notification_type": "test_notif",
        "subject": "Dispatch Feb-05", "metadata": {"body": "hi"},
    }))
    # Audit (invoice_auto_charged) at Feb-10.
    _run(_DB.audit_events.insert_one({
        "id": f"{PFX}a1", "tenant_id": TENANT,
        "event_type": "invoice_auto_charged",
        "payload": {"customer_id": CID, "amount_cents": 500,
                        "currency": "usd"},
        "timestamp": "2026-02-10T10:00:00+00:00",
    }))
    # Dispatch at Feb-15.
    _run(_DB.notification_dispatch_log.insert_one({
        "id": f"{PFX}d2", "tenant_id": TENANT,
        "channel": "sms", "recipient_id": CID,
        "resolved_address": "+15551111", "status": "delivered",
        "sent_at": "2026-02-15T10:00:00+00:00",
        "dedupe_key": f"{PFX}d2-dk",
        "notification_type": "test_notif",
        "subject": "Dispatch Feb-15",
    }))
    merged = _run(_build(role="admin"))
    ours = [m for m in merged if m.get("ref_id", "").startswith(PFX)]
    assert len(ours) == 3
    times = [m["occurred_at"] for m in ours]
    # DESC — Feb-15 first.
    assert times[0].startswith("2026-02-15")
    assert times[1].startswith("2026-02-10")
    assert times[2].startswith("2026-02-05")


# ─── §2 · New ref_types don't collide with dedupe heuristic ──────
def test_new_ref_types_no_collision_with_dedupe():
    _run(_seed_customer())
    # Seed one dispatch + one audit with the SAME ref_id value (as a
    # string). Dedupe should keep both because ``ref_type`` differs.
    shared_id = f"{PFX}shared-ref-value"
    _run(_DB.notification_dispatch_log.insert_one({
        "id": shared_id, "tenant_id": TENANT,
        "channel": "email", "recipient_id": CID,
        "resolved_address": "c@ex.com", "status": "sent",
        "sent_at": "2026-02-05T10:00:00+00:00",
        "dedupe_key": shared_id,
        "notification_type": "test_notif",
        "subject": "Dispatch", "metadata": {"body": "hi"},
    }))
    _run(_DB.audit_events.insert_one({
        "id": shared_id, "tenant_id": TENANT,
        "event_type": "invoice_auto_charged",
        "payload": {"customer_id": CID, "amount_cents": 500,
                        "currency": "usd"},
        "timestamp": "2026-02-05T11:00:00+00:00",
    }))
    merged = _run(_build(role="admin"))
    ours = [m for m in merged if m.get("ref_id") == shared_id]
    assert len(ours) == 2
    assert sorted(m["ref_type"] for m in ours) == [
        "audit_event", "notification_dispatch"]


# ─── §3 · Admin vs. portal strip holds across the full merge ─────
def test_admin_vs_portal_strip_holds_across_full_merge():
    _run(_seed_customer())
    # Dispatch with delivery_error + actor_user_id.
    _run(_DB.notification_dispatch_log.insert_one({
        "id": f"{PFX}d1", "tenant_id": TENANT,
        "channel": "email", "recipient_id": CID,
        "resolved_address": "c@ex.com", "status": "failed",
        "sent_at": "2026-02-05T10:00:00+00:00",
        "error": "internal-code-X9",
        "dedupe_key": f"{PFX}d1-dk",
        "notification_type": "test_notif",
        "metadata": {"body": "hi", "actor_user_id": "admin-u"},
        "subject": "Failed send",
    }))
    # Audit admin-only (job_edited) — portal MUST not see it at all.
    _run(_DB.audit_events.insert_one({
        "id": f"{PFX}a1", "tenant_id": TENANT,
        "event_type": "job_edited_after_completion",
        "payload": {"customer_id": CID, "fields_changed": ["notes"]},
        "timestamp": "2026-02-10T10:00:00+00:00",
        "actor_email": "admin@ex.com", "actor_id": "admin-u",
    }))
    admin_merged = _run(_build(role="admin"))
    portal_merged = _run(_build(role="customer"))

    admin_ours = [m for m in admin_merged
                      if m.get("ref_id", "").startswith(PFX)]
    portal_ours = [m for m in portal_merged
                       if m.get("ref_id", "").startswith(PFX)]

    # Admin sees both.
    assert len(admin_ours) == 2
    disp_admin = next(m for m in admin_ours
                          if m["ref_type"] == "notification_dispatch")
    assert disp_admin["delivery_error"] == "internal-code-X9"
    assert disp_admin["actor_user_id"] == "admin-u"

    # Portal sees ONLY the dispatch (job_edited is admin-only).
    assert len(portal_ours) == 1
    assert portal_ours[0]["ref_type"] == "notification_dispatch"
    assert "delivery_error" not in portal_ours[0]
    assert "actor_user_id" not in portal_ours[0]
