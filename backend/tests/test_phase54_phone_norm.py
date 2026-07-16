"""Phase 54 closeout · Phone normalization + customer matching.

Verifies that a webhook envelope carrying an E.164 phone number
(`+14805550102`) correctly attaches to a customer seeded with the
dashed US format (`480-555-0102`), and that the `_normalize_phone_e164`
helper handles all documented input shapes.
"""
from __future__ import annotations

import asyncio
import pytest

from routers.ringcentral import (
    _normalize_phone_e164,
    _handle_telephony_event,
    _match_customer_by_phone,
)
from config import db
from utils import new_id


def test_normalize_phone_e164_shapes():
    """Every US format shape maps to canonical +1XXXXXXXXXX."""
    assert _normalize_phone_e164("4805550102") == "+14805550102"
    assert _normalize_phone_e164("480-555-0102") == "+14805550102"
    assert _normalize_phone_e164("(480) 555-0102") == "+14805550102"
    assert _normalize_phone_e164("+14805550102") == "+14805550102"
    assert _normalize_phone_e164("1-480-555-0102") == "+14805550102"
    # Invalid inputs.
    assert _normalize_phone_e164(None) is None
    assert _normalize_phone_e164("") is None
    assert _normalize_phone_e164("123") is None
    # Foreign E.164 preserved (not clobbered with +1).
    assert _normalize_phone_e164("+442071838750") == "+442071838750"


@pytest.mark.skip(reason="internal — invoked via the sync wrapper below")
async def test_dashed_phone_matches_e164_webhook_async():
    """Seed a customer with dashed US phone, then simulate a telephony
    webhook envelope with E.164 → assert call_logs row is attached."""
    tenant_id = "phase54-norm-tenant"
    cid = new_id()
    dashed = "555-321-9987"
    e164 = "+15553219987"
    # Clean prior test rows.
    await db.customers.delete_many({"id": cid})
    await db.call_logs.delete_many({"from_number": e164, "customer_id": cid})
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Robert Blake (phase54)",
        "phones": [dashed],
    })
    # Direct helper check first.
    match = await _match_customer_by_phone(None, e164)
    assert match is not None, "matcher should resolve dashed phone from E.164 webhook"
    assert match["id"] == cid
    # Full event handler path.
    fake = {
        "event": "/restapi/v1.0/account/~/telephony/sessions",
        "eventType": "telephony.session",
        "uuid": new_id(),
        "call": {"from": e164, "to": "+16028870000",
                 "duration": 15, "direction": "inbound"},
    }
    await _handle_telephony_event(fake)
    log = await db.call_logs.find_one(
        {"from_number": e164, "customer_id": cid}, {"_id": 0}
    )
    assert log is not None, "call_log should be attached to the dashed-phone customer"
    assert log.get("customer_id") == cid
    # Cleanup.
    await db.customers.delete_many({"id": cid})
    await db.call_logs.delete_many({"from_number": e164, "customer_id": cid})


def test_dashed_phone_matches_e164_webhook():
    """Sync wrapper — no pytest-asyncio dependency."""
    asyncio.run(test_dashed_phone_matches_e164_webhook_async())
