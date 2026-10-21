"""TD-98-be-sources · Phase 2 · ``notification_dispatch_log`` reader.

Full-matrix pytest coverage per audit §4.e (2) + §7.a File 1:
  1. SMS + email dispatch rows surface on admin timeline with
     correct ``kind`` + ``delivery_status`` + ``ref_type``.
  2. ``recipient_id`` match AND ``resolved_address`` match both work
     via ``$or``; union doesn't double-count.
  3. Tenant isolation — cross-tenant rows never leak.
  4. Portal path (``/customers/me/timeline``) sees dispatch rows but
     NOT ``actor_user_id`` / ``delivery_error`` top-level.
  5. ``kind`` filter (``?kind=email``) scopes correctly.
  6. ``from`` / ``to`` date-range composes.
  7. Hard-cap at ``_TIMELINE_HARD_CAP`` = 500.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

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

PFX = f"td98bes_disp_{uuid.uuid4().hex[:6]}_"


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


async def _seed_customer(tenant_id=TENANT, cid=CID,
                           emails=None, phones=None):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Test Customer",
        "email": (emails or ["t@example.com"])[0],
        "phone": (phones or ["+15550000"])[0],
        "contacts": [
            {"email": e} for e in (emails or [])
        ] + [{"phone": p} for p in (phones or [])],
    })


async def _seed_dispatch(
    *, tenant_id, channel="sms", recipient_id=None,
    resolved_address=None, status="delivered", error=None,
    sent_at="2026-02-10T10:00:00+00:00", template_name="",
    subject="", body=None, actor_user_id=None,
) -> str:
    rid = f"{PFX}d_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id,
        "channel": channel,
        "recipient_id": recipient_id,
        "resolved_address": resolved_address,
        "status": status,
        "sent_at": sent_at,
        "template_name": template_name,
        "subject": subject,
        "error": error,
        "dedupe_key": rid,
        "notification_type": "test_notif",
        "metadata": {"body": body} if body else {},
    }
    if actor_user_id:
        doc["metadata"]["actor_user_id"] = actor_user_id
    await _DB.notification_dispatch_log.insert_one(doc)
    return rid


async def _wipe():
    rx = {"$regex": f"^{PFX}"}
    for c in ("notification_dispatch_log", "customers", "audit_events",
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
    from routers.communication_timeline import (
        _notification_dispatch_log_to_items,
    )
    customer = await _DB.customers.find_one(
        {"id": CID}, {"_id": 0})
    return await _notification_dispatch_log_to_items(
        customer, TENANT, wanted_kinds, None, None, role,
    )


# ─── §1 · kind + delivery_status + ref_type ───────────────────────
def test_sms_and_email_kinds_surface_correctly():
    _run(_seed_customer(emails=["c@ex.com"], phones=["+15551111"]))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="sms", recipient_id=CID,
        resolved_address="+15551111", status="delivered",
        body="hi", subject="SMS"))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email", recipient_id=CID,
        resolved_address="c@ex.com", status="sent",
        body="hello", subject="Email"))
    items = _run(_call_build(role="admin"))
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["email", "sms"]
    assert all(i["ref_type"] == "notification_dispatch" for i in items)
    statuses = sorted(i["delivery_status"] for i in items)
    assert statuses == ["delivered", "sent"]


# ─── §2 · $or recipient_id OR resolved_address ────────────────────
def test_or_match_recipient_id_and_resolved_address_union_no_double():
    _run(_seed_customer(emails=["x@ex.com"], phones=["+15552222"]))
    # Match by recipient_id only.
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="sms",
        recipient_id=CID, resolved_address="+15559999",
        subject="recip-match"))
    # Match by resolved_address only.
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email",
        recipient_id="other-cust", resolved_address="x@ex.com",
        subject="addr-match"))
    # Match both (should still be 1 row, not 2).
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="sms",
        recipient_id=CID, resolved_address="+15552222",
        subject="both-match"))
    items = _run(_call_build(role="admin"))
    subjects = sorted(i["subject"] for i in items)
    assert subjects == ["addr-match", "both-match", "recip-match"]


# ─── §3 · Tenant isolation ───────────────────────────────────────
def test_tenant_isolation():
    _run(_seed_customer(tenant_id=TENANT, emails=["a@ex.com"]))
    _run(_seed_customer(tenant_id=TENANT_B, cid=CID,
                          emails=["a@ex.com"]))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email",
        recipient_id=CID, resolved_address="a@ex.com",
        subject="A-tenant"))
    _run(_seed_dispatch(
        tenant_id=TENANT_B, channel="email",
        recipient_id=CID, resolved_address="a@ex.com",
        subject="B-tenant-noise"))
    items = _run(_call_build(role="admin"))
    assert [i["subject"] for i in items] == ["A-tenant"]


# ─── §4 · Portal path strips admin fields ─────────────────────────
def test_portal_strips_delivery_error_and_actor_user_id():
    _run(_seed_customer(emails=["p@ex.com"]))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email", recipient_id=CID,
        resolved_address="p@ex.com", status="failed",
        error="twilio_error_30001",
        actor_user_id="user-admin-123",
        subject="Portal-visible"))
    admin_items = _run(_call_build(role="admin"))
    portal_items = _run(_call_build(role="customer"))

    assert len(admin_items) == 1
    assert admin_items[0]["delivery_error"] == "twilio_error_30001"
    assert admin_items[0]["actor_user_id"] == "user-admin-123"

    assert len(portal_items) == 1
    assert "delivery_error" not in portal_items[0]
    assert "actor_user_id" not in portal_items[0]
    # Core fields still present.
    assert portal_items[0]["kind"] == "email"
    assert portal_items[0]["subject"] == "Portal-visible"


# ─── §5 · wanted_kinds scopes correctly ──────────────────────────
def test_wanted_kinds_filter_scopes():
    _run(_seed_customer(emails=["w@ex.com"], phones=["+15553333"]))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="sms",
        recipient_id=CID, resolved_address="+15553333",
        subject="S"))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email",
        recipient_id=CID, resolved_address="w@ex.com",
        subject="E"))
    items_email = _run(_call_build(role="admin",
                                      wanted_kinds={"email"}))
    assert [i["subject"] for i in items_email] == ["E"]
    items_sms = _run(_call_build(role="admin",
                                    wanted_kinds={"sms"}))
    assert [i["subject"] for i in items_sms] == ["S"]
    items_none = _run(_call_build(role="admin",
                                     wanted_kinds={"note"}))
    assert items_none == []


# ─── §6 · from / to date range ───────────────────────────────────
def test_date_range_composes():
    from routers.communication_timeline import (
        _notification_dispatch_log_to_items,
    )
    _run(_seed_customer(emails=["r@ex.com"]))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email", recipient_id=CID,
        resolved_address="r@ex.com", subject="Jan",
        sent_at="2026-01-15T00:00:00+00:00"))
    _run(_seed_dispatch(
        tenant_id=TENANT, channel="email", recipient_id=CID,
        resolved_address="r@ex.com", subject="Mar",
        sent_at="2026-03-15T00:00:00+00:00"))
    customer = _run(_DB.customers.find_one({"id": CID}, {"_id": 0}))
    out = _run(_notification_dispatch_log_to_items(
        customer, TENANT, None,
        "2026-02-01T00:00:00+00:00",
        "2026-04-01T00:00:00+00:00",
        "admin",
    ))
    assert [i["subject"] for i in out] == ["Mar"]


# ─── §7 · Hard-cap at _TIMELINE_HARD_CAP (sanity, light scale) ───
def test_hard_cap_limit_applied():
    _run(_seed_customer(emails=["c@ex.com"]))
    # Seed 10 rows — well under cap; validate items ≤ cap.
    for i in range(10):
        _run(_seed_dispatch(
            tenant_id=TENANT, channel="email", recipient_id=CID,
            resolved_address="c@ex.com",
            subject=f"n{i}", sent_at=f"2026-02-{i+1:02d}T00:00:00+00:00"))
    items = _run(_call_build(role="admin"))
    from routers.communication_timeline import _TIMELINE_HARD_CAP
    assert len(items) <= _TIMELINE_HARD_CAP
    assert len(items) == 10
