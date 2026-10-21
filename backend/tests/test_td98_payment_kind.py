"""TD-98-be-sources-payment-kind · pytest coverage for the
``invoice_auto_charged`` → ``kind=payment`` reclassification.

Scope lock per operator approval:
  - Reclassify only ``invoice_auto_charged`` → ``kind="payment"``
    (previously ``"note"``).
  - BE emits ``total`` numeric field (amount in dollars) alongside the
    body string so the FE ``DefaultRow`` ``$X.XX`` money chip surfaces.
  - Portal field-strip preserved (``actor_user_id`` + impersonation
    stamp admin-only) — gate is on ``event_type`` not ``kind``.
  - ``?kind=payment`` filter accepted; ``?kind=note`` no longer surfaces
    former auto-charge rows (regression lock on the kind flip).
  - Zero scope creep into ACH-initiated, manual payments, refunds,
    failed charges, Stripe webhook feed — those are separate candidate
    tickets.

Companion to ``test_td98_be_sources_audit_events.py`` which locks the
pre-reclassification shape; this file locks the post-reclassification
shape + the new ``total`` wire-through + the ``?kind=payment`` filter
semantics + regression on existing kinds.
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

PFX = f"td98pk_{uuid.uuid4().hex[:6]}_"


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


async def _seed_customer(tenant_id=TENANT, cid=CID):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tenant_id, "name": "Payment-Kind Test",
        "email": "pk@ex.com", "phone": "+15550000", "contacts": [],
    })


async def _seed_audit(
    *, tenant_id, event_type, payload,
    timestamp="2026-10-21T10:00:00+00:00",
    actor_email=None, actor_id=None, via_impersonation=False,
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
    await _DB.audit_events.insert_one(doc)
    return rid


async def _wipe():
    rx = {"$regex": f"^{PFX}"}
    for c in ("audit_events", "customers"):
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


# ─── §1 · invoice_auto_charged emits kind=payment (admin + portal) ─
def test_invoice_auto_charged_emits_kind_payment_admin():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv-pk-1",
                 "amount_cents": 12345, "currency": "usd",
                 "payment_intent_id": "pi_abcdef123456"},
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin"))
    assert len(items) == 1
    assert items[0]["kind"] == "payment"
    assert items[0]["trigger_kind"] == "invoice_auto_charged"
    # Related ref still points at the invoice.
    assert items[0]["related_ref"] == {"kind": "invoice", "id": "inv-pk-1"}


def test_invoice_auto_charged_emits_kind_payment_portal():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv-pk-2",
                 "amount_cents": 5000, "currency": "usd"},
        actor_email="admin@ex.com", actor_id="admin-u",
        via_impersonation=True,
    ))
    portal = _run(_call_build(role="customer"))
    assert len(portal) == 1
    assert portal[0]["kind"] == "payment"
    # Portal field-strip preserved (gate on event_type, not kind).
    assert "actor_user_id" not in portal[0]
    assert "(via impersonation)" not in portal[0]["body"]
    assert "admin@ex.com" not in portal[0]["body"]


# ─── §2 · total numeric field (FE money chip wire-through) ────────
def test_payment_item_emits_total_numeric_in_dollars():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv-pk-3",
                 "amount_cents": 12345, "currency": "usd"},
    ))
    items = _run(_call_build(role="admin"))
    assert items[0]["total"] == 123.45


def test_payment_item_emits_total_on_portal_too():
    # Amount is already in the body for both admin + portal; the
    # numeric form carries no additional PII beyond what body carries,
    # so no field-strip needed.
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv-pk-4",
                 "amount_cents": 999, "currency": "usd"},
    ))
    portal = _run(_call_build(role="customer"))
    assert portal[0]["total"] == 9.99


def test_payment_item_total_zero_when_amount_missing():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "invoice_id": "inv-pk-5"},
    ))
    items = _run(_call_build(role="admin"))
    assert items[0]["kind"] == "payment"
    assert items[0]["total"] == 0


# ─── §3 · kind filter — ?kind=payment scopes correctly ────────────
def test_kind_filter_payment_only():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 1000,
                 "currency": "usd"},
        timestamp="2026-10-20T10:00:00+00:00",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "job_id": "j1",
                 "fields_changed": ["notes"]},
        timestamp="2026-10-21T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin", wanted_kinds={"payment"}))
    assert len(items) == 1
    assert items[0]["kind"] == "payment"
    assert items[0]["trigger_kind"] == "invoice_auto_charged"


# ─── §4 · kind filter regression — ?kind=note EXCLUDES former
#         invoice_auto_charged rows (regression lock on reclassification) ─
def test_kind_filter_note_no_longer_returns_invoice_auto_charged():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 100,
                 "currency": "usd"},
        timestamp="2026-10-20T10:00:00+00:00",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "job_id": "j1",
                 "fields_changed": ["notes"]},
        timestamp="2026-10-21T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin", wanted_kinds={"note"}))
    # Only the K6 note row surfaces — the auto-charge is now kind=payment.
    assert len(items) == 1
    assert items[0]["kind"] == "note"
    assert items[0]["trigger_kind"] == "job_edited_after_completion"
    # The auto-charge is NOT in the note slice.
    assert all(i["trigger_kind"] != "invoice_auto_charged" for i in items)


# ─── §5 · CSV filter — ?kind=note,payment composes correctly ──────
def test_kind_filter_note_and_payment_csv_composes():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="invoice_auto_charged",
        payload={"customer_id": CID, "amount_cents": 100,
                 "currency": "usd"},
        timestamp="2026-10-20T10:00:00+00:00",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "job_id": "j1",
                 "fields_changed": ["notes"]},
        timestamp="2026-10-21T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    _run(_seed_audit(
        tenant_id=TENANT, event_type="portal_invite_bulk",
        payload={"customer_ids": [CID], "sent": 1},
        timestamp="2026-10-22T10:00:00+00:00",
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin",
                               wanted_kinds={"note", "payment"}))
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["note", "payment"]
    # Portal invite (kind=email) is NOT in the filtered slice.
    assert all(i["trigger_kind"] != "portal_invite_bulk" for i in items)


# ─── §6 · ``payment`` is a valid _TIMELINE_ALLOWED_KINDS member ───
def test_timeline_allowed_kinds_includes_payment():
    from routers.communication_timeline import (
        _TIMELINE_ALLOWED_KINDS, _parse_kinds,
    )
    assert "payment" in _TIMELINE_ALLOWED_KINDS
    assert _parse_kinds("payment") == {"payment"}
    assert _parse_kinds("note,payment") == {"note", "payment"}


# ─── §7 · _normalise_existing_item src map — payment branch ───────
def test_normalise_existing_item_src_map_payment():
    from routers.communication_timeline import _normalise_existing_item
    item = {"kind": "payment", "subject": "Invoice auto-charged",
            "created_at": "2026-10-21T10:00:00+00:00"}
    out = _normalise_existing_item(item)
    assert out["source_type"] == "payment"


# ─── §8 · Regression: other audit event types classify unchanged ──
def test_regression_portal_invite_bulk_still_email():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="portal_invite_bulk",
        payload={"customer_ids": [CID], "sent": 1,
                 "skipped_already_activated": 0},
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin"))
    assert len(items) == 1
    assert items[0]["kind"] == "email"
    assert items[0]["trigger_kind"] == "portal_invite_bulk"
    # No total emitted on non-payment items.
    assert "total" not in items[0]


def test_regression_job_edited_still_note():
    _run(_seed_customer())
    _run(_seed_audit(
        tenant_id=TENANT, event_type="job_edited_after_completion",
        payload={"customer_id": CID, "job_id": "j1",
                 "fields_changed": ["notes", "total"]},
        actor_email="admin@ex.com", actor_id="admin-u",
    ))
    items = _run(_call_build(role="admin"))
    assert len(items) == 1
    assert items[0]["kind"] == "note"
    assert items[0]["trigger_kind"] == "job_edited_after_completion"
    # No total emitted on non-payment items (even though the K6 body
    # mentions "total" as a field name — the item.total key must not
    # be present since it's a kind=note item).
    assert "total" not in items[0]
