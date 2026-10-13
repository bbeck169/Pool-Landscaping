"""P2 #5 · Feb-2026 — /api/communications-detail/{id} resolver pytest.

Locks six invariants on the admin communication detail endpoint:
  1. Resolves a ``marketing_deliveries`` row by id → returns full
     body + HTML format.
  2. Resolves a ``lead_communications`` SMS row → full body + text
     format + direction/subject/from/to preserved.
  3. Resolves a ``notification_dispatch_log`` row → ``body_available``
     is False and the metadata (subject, provider_response_id,
     delivery_status) still lands on the envelope.
  4. 404 on unknown id (none of the five collections match).
  5. 404 on cross-tenant id (prevents the endpoint from being used
     as a cross-tenant data probe).
  6. 403 for ``role=customer`` and ``role=technician`` — mirrors the
     ``require_admin_or_manager`` dep contract.

Loop-isolation + ``_patch_db_everywhere`` mirrors the sibling P2 #4
pytests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.communications_detail",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p25-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}
MANAGER = {"id": f"{PREFIX}-u-manager", "role": "manager"}
TECH = {"id": f"{PREFIX}-u-tech", "role": "technician"}
CUSTOMER = {"id": f"{PREFIX}-u-cust", "role": "customer"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("marketing_deliveries", "lead_communications",
                 "notification_dispatch_log", "communications_log",
                 "sms_inbound"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


# ------------------------------------------------------------------
# Case 1 — marketing_deliveries resolve + HTML body
# ------------------------------------------------------------------
def test_resolves_marketing_delivery_with_html_body():
    rid = f"{PREFIX}-md-01"
    _run(_seed_tenant(TENANT_A))
    _run(_DB.marketing_deliveries.insert_one({
        "id": rid, "tenant_id": TENANT_A,
        "channel": "email",
        "recipient_email": "carla@example.com",
        "subject_rendered": "Welcome aboard",
        "body_rendered": "<p>Hi <b>Carla</b></p>",
        "provider": "resend",
        "provider_response_id": "re-abc-123",
        "provider_status": "sent",
        "delivery_status": "delivered",
        "delivered_at": "2026-02-15T12:01:00+00:00",
        "sent_at": "2026-02-15T12:00:00+00:00",
    }))
    from routers.communications_detail import get_communication_detail
    out = _run(get_communication_detail(
        rid, user=ADMIN, tenant={"id": TENANT_A}))
    assert out["source"] == "marketing_deliveries"
    assert out["channel"] == "email"
    assert out["direction"] == "outbound"
    assert out["subject"] == "Welcome aboard"
    assert out["to"] == "carla@example.com"
    assert out["body_available"] is True
    assert "Carla" in out["body"]
    assert out["body_format"] == "html"
    assert out["provider"] == "resend"
    assert out["provider_response_id"] == "re-abc-123"
    assert out["delivery_status"] == "delivered"
    assert out["delivered_at"] == "2026-02-15T12:01:00+00:00"


# ------------------------------------------------------------------
# Case 2 — lead_communications resolve + text format for SMS
# ------------------------------------------------------------------
def test_resolves_lead_communication_sms_as_text():
    rid = f"{PREFIX}-lc-02"
    _run(_seed_tenant(TENANT_A))
    _run(_DB.lead_communications.insert_one({
        "id": rid, "tenant_id": TENANT_A,
        "lead_id": f"{PREFIX}-lead-xyz",
        "direction": "outbound",
        "channel": "sms",
        "from_identity": "+16028874400",
        "to_identity": "+14805550001",
        "subject": None,
        "body": "Thanks for the quote request!",
        "status": "sent",
        "provider_message_id": "sm-xyz-999",
        "provider_status_raw": "queued",
        "created_at": "2026-02-15T13:00:00+00:00",
    }))
    from routers.communications_detail import get_communication_detail
    out = _run(get_communication_detail(
        rid, user=MANAGER, tenant={"id": TENANT_A}))
    assert out["source"] == "lead_communications"
    assert out["channel"] == "sms"
    assert out["direction"] == "outbound"
    assert out["from"] == "+16028874400"
    assert out["to"] == "+14805550001"
    assert out["body"] == "Thanks for the quote request!"
    assert out["body_format"] == "text"
    assert out["body_available"] is True
    assert out["provider_response_id"] == "sm-xyz-999"
    assert out["delivery_status"] == "sent"


# ------------------------------------------------------------------
# Case 3 — notification_dispatch_log resolve + body_available=False
# ------------------------------------------------------------------
def test_resolves_notification_dispatch_log_with_body_unavailable():
    rid = f"{PREFIX}-ndl-03"
    _run(_seed_tenant(TENANT_A))
    _run(_DB.notification_dispatch_log.insert_one({
        "id": rid, "tenant_id": TENANT_A,
        "notification_type": "quote_sent",
        "recipient_id": f"{PREFIX}-cust-abc",
        "dedupe_key": "quote_sent-abc-2026-02-15",
        "channel": "email",
        "resolved_address": "customer@example.com",
        "subject": "Your quote is ready",
        "status": "sent",
        "provider_id": "re-mdl-777",
        "sent_at": "2026-02-15T14:00:00+00:00",
    }))
    from routers.communications_detail import get_communication_detail
    out = _run(get_communication_detail(
        rid, user=ADMIN, tenant={"id": TENANT_A}))
    assert out["source"] == "notification_dispatch_log"
    assert out["body_available"] is False
    assert out["body"] == ""
    assert out["subject"] == "Your quote is ready"
    assert out["to"] == "customer@example.com"
    assert out["provider_response_id"] == "re-mdl-777"
    assert out["delivery_status"] == "sent"
    assert out["channel"] == "email"
    assert out["body_format"] == "html"


# ------------------------------------------------------------------
# Case 4 — 404 on unknown id across all collections
# ------------------------------------------------------------------
def test_404_on_unknown_id():
    _run(_seed_tenant(TENANT_A))
    from routers.communications_detail import get_communication_detail
    with pytest.raises(HTTPException) as exc:
        _run(get_communication_detail(
            f"{PREFIX}-does-not-exist",
            user=ADMIN, tenant={"id": TENANT_A}))
    assert exc.value.status_code == 404


# ------------------------------------------------------------------
# Case 5 — 404 on cross-tenant id (data-probe prevention)
# ------------------------------------------------------------------
def test_404_on_cross_tenant_id():
    rid = f"{PREFIX}-md-xten"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_DB.marketing_deliveries.insert_one({
        "id": rid, "tenant_id": TENANT_B,
        "channel": "email",
        "body_rendered": "<p>cross tenant body</p>",
    }))
    from routers.communications_detail import get_communication_detail
    with pytest.raises(HTTPException) as exc:
        _run(get_communication_detail(
            rid, user=ADMIN, tenant={"id": TENANT_A}))
    assert exc.value.status_code == 404


# ------------------------------------------------------------------
# Case 6 — 403 for role=customer and role=technician
# ------------------------------------------------------------------
@pytest.mark.parametrize("bad_user", [CUSTOMER, TECH])
def test_403_for_non_admin_manager_roles(bad_user):
    from utils import require_admin_or_manager
    with pytest.raises(HTTPException) as exc:
        require_admin_or_manager(user=bad_user)
    assert exc.value.status_code == 403
