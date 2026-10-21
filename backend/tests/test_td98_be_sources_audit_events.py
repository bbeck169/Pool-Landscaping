"""TD-98-be-sources · Phase 2 · ``audit_events`` reader.

Full-matrix pytest coverage per audit §4.e (2) + §7.a File 2:
  1. All 3 event types surface on admin timeline with correct
     derived ``kind`` (per §4.b α mapping).
  2. ``payload.customer_id`` + ``payload.customer_ids`` both match
     via ``$or``; union doesn't double-count.
  3. Tenant isolation.
  4. Portal path per §4.d operator pick:
       - ``portal_invite_bulk``          → admin-only.
       - ``job_edited_after_completion`` → admin-only.
       - ``invoice_auto_charged``        → portal YES (field-strip).
  5. Field-strip on portal-visible ``invoice_auto_charged``:
     admin sees ``actor_user_id`` + impersonation stamp; portal
     doesn't.
  6. K6 ``job_edited_after_completion`` never leaks before/after
     field values — body contains only field NAMES.
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

PFX = f"td98bes_aud_{uuid.uuid4().hex[:6]}_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db():
    import config
    config.db = _DB
    import routers.communication_timeline as mod
    mod.db = _DB


TENANT = f"{PFX}tenA"
TENANT_B = f"{PFX}tenB"
CID = f"{PFX}cust"


async def _seed_customer(tenant_id=TENANT, cid=CID):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tenant_id, "name": "Test",
        "email": "t@ex.com", "phone": "+15550000", "contacts": [],
    })


async def _seed_audit(
    *, tenant_id, event_type, payload,
    timestamp="2026-02-10T10:00:00+00:00",
    actor_email=None, actor_id=None, via_impersonation=False,
    reason=None,
) -> str:
    rid = f"{PFX}a_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id,
        "event_type": event_type,
        "payload": payload, "timestamp": timestamp,
        "actor_email": actor_email,
        "actor_id": actor_id,
        "via_impersonation": via_impersonation,
    }
    if reason:
        doc["reason"] = reason
    await _DB.audit_events.insert_one(doc)
    return rid


async def _wipe():
    rx = {"$regex": f"^{PFX}"}
    for c in ("audit_events", "customers", "notification_dispatch_log",
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


async def _call_build(role="admin", wanted_kinds=None):
    from routers.communication_timeline import _audit_events_to_items
    customer = await _DB.customers.find_one({"id": CID}, {"_id": 0})
    return await _audit_events_to_items(
        customer, TENANT, wanted_kinds, None, None, role,
    )


# ─── §1 · All 3 event types surface on admin with correct kind ───
def test_all_event_types_surface_admin_with_mapped_kind():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="portal_invite_bulk",
        payload={"customer_ids": [CID], "sent": 1, "skipped_already_activated": 0},
        timestamp="2026-02-10T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "job_id": "j1",
                 "fields_changed": ["notes", "total"]},
        timestamp="2026-02-11T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv1",
                 "amount_cents": 12300, "currency": "usd",
                 "payment_intent_id": "pi_1234567890"},
        timestamp="2026-02-12T10:00:00+00:00",
        actor_id="system",
    ))
    items = _run(_call_build(role="admin"))
    # DESC by timestamp.
    assert [i["trigger_kind"] for i in items] == [
        "invoice_auto_charged",
        "job_edited_after_completion",
        "portal_invite_bulk",
    ]
    # §4.b β (post-TD-98-be-sources-payment-kind): portal_invite_bulk=email;
    # job_edited=note; invoice_auto_charged=payment (reclassified from note).
    assert [i["kind"] for i in items] == ["payment", "note", "email"]
    assert all(i["ref_type"] == "audit_event" for i in items)


# ─── §2 · $or payload.customer_id OR payload.customer_ids ────────
def test_or_match_customer_id_singleton_vs_list():
    _run(_seed_customer())
    # Singleton payload.
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv1",
                 "amount_cents": 10000, "currency": "usd"},
        timestamp="2026-02-10T10:00:00+00:00",
    ))
    # Bulk payload (customer_ids).
    _run(_seed_audit(
        tenant_id=TENANT, event_type="portal_invite_bulk",
        payload={"customer_ids": [CID, "other"], "sent": 2},
        timestamp="2026-02-11T10:00:00+00:00",
    ))
    items = _run(_call_build(role="admin"))
    assert len(items) == 2


# ─── §3 · Tenant isolation ───────────────────────────────────────
def test_tenant_isolation():
    _run(_seed_customer(tenant_id=TENANT))
    _run(_seed_customer(tenant_id=TENANT_B, cid=CID))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 100,
                 "currency": "usd"},
    ))
    _run(_seed_audit(
        tenant_id=TENANT_B, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 999,
                 "currency": "usd"},
    ))
    items = _run(_call_build(role="admin"))
    assert len(items) == 1
    assert "$1.00" in items[0]["body"]
    assert "$9.99" not in items[0]["body"]


# ─── §4 · Portal visibility matrix per §4.d ──────────────────────
def test_portal_visibility_split_only_invoice_auto_charged():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="portal_invite_bulk",
        payload={"customer_ids": [CID], "sent": 1}))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "fields_changed": ["notes"]}))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 1234,
                 "currency": "usd"}))
    admin_items = _run(_call_build(role="admin"))
    portal_items = _run(_call_build(role="customer"))

    admin_types = sorted(i["trigger_kind"] for i in admin_items)
    assert admin_types == [
        "invoice_auto_charged",
        "job_edited_after_completion",
        "portal_invite_bulk",
    ]
    portal_types = sorted(i["trigger_kind"] for i in portal_items)
    assert portal_types == ["invoice_auto_charged"]


# ─── §5 · Field-strip on portal-visible invoice_auto_charged ─────
def test_invoice_auto_charged_portal_strips_actor_and_impersonation():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 1234,
                 "currency": "usd",
                 "payment_intent_id": "pi_9999999999"},
        actor_email="admin@ex.com", actor_id="admin-u",
        via_impersonation=True,
    ))
    admin_items = _run(_call_build(role="admin"))
    portal_items = _run(_call_build(role="customer"))

    assert len(admin_items) == 1
    assert admin_items[0]["actor_user_id"] == "admin-u"
    assert "(via impersonation)" in admin_items[0]["body"]
    assert "admin@ex.com" in admin_items[0]["body"]

    assert len(portal_items) == 1
    assert "actor_user_id" not in portal_items[0]
    assert "delivery_error" not in portal_items[0]
    assert "(via impersonation)" not in portal_items[0]["body"]
    assert "admin@ex.com" not in portal_items[0]["body"]
    # Core fields intact.
    assert "$12.34" in portal_items[0]["body"]


# ─── §6 · K6 never leaks before/after values ─────────────────────
def test_k6_never_leaks_before_after_values():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={
            "customer_id": CID,
            "job_id": "j1",
            "fields_changed": ["notes", "total"],
            # These keys MUST NOT appear in the item body.
            "notes_before": "SECRET-OLD-VALUE",
            "notes_after": "SECRET-NEW-VALUE",
            "total_before": 999999,
            "total_after": 111111,
        },
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    admin_items = _run(_call_build(role="admin"))
    assert len(admin_items) == 1
    body = admin_items[0]["body"]
    # Field names present.
    assert "notes" in body
    assert "total" in body
    # Values absent.
    assert "SECRET-OLD-VALUE" not in body
    assert "SECRET-NEW-VALUE" not in body
    assert "999999" not in body
    assert "111111" not in body
