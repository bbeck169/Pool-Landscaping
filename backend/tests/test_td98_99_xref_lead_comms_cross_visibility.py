"""TD-98/99-xref · Feb-2026 — Cross-visibility aggregator pytest smoke.

Covers the 7 scenarios defined in the TD-98/99-xref Phase-1 audit §6:

  1. Happy path — converted lead's SMS + email + inbound SMS surface
     on ``GET /customers/{cid}/timeline`` interleaved with
     customer-era marketing deliveries, sorted desc by created_at.
  2. Multi-lead-to-one-customer (merge branch) — two leads converted
     to the same customer, one comm each → both appear.
  3. Tenant isolation — tenant B lead with the same converted_customer_id
     string by coincidence does NOT leak into tenant A's response.
  4. Non-converted customer regression — zero lead-era items, zero
     DB roundtrip past the empty ``$in``.
  5. Portal field-safety — ``GET /customers/me/timeline`` returns
     lead-era items with no admin-only field leakage.
  6. Kind filter composition — ``?kind=sms`` returns only SMS rows
     (both lead-era + customer-era), no email.
  7. Date-range filter — lead-era items outside ``[from, to]`` are
     excluded, items inside are retained.

Pattern parity: mirrors the ASGITransport harness established by
``test_td96_lead_recipient_exclusion.py`` and
``test_td93_list_quotes_date_range.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTtd98xref_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _iso(y, m, d, h=12):
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc).isoformat()


async def _seed_customer(*, cid, tenant_id, name="Converted Customer"):
    await _DB.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name, "email": "cust@example.com",
        "phone": "+14805550100", "emails": ["cust@example.com"],
        "phones": ["+14805550100"],
    })


async def _seed_converted_lead(*, lid, cid, tenant_id):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tenant_id,
        "name": "Converted Lead",
        "status": "Closed Won",
        "converted_customer_id": cid,
        "archived_at": _iso(2026, 2, 15),
    })


async def _seed_lead_comm(*, lid, tenant_id, channel="sms",
                            body="Hello world", status="sent",
                            created_at=None, subject=None):
    row_id = f"{PFX}lc_{uuid.uuid4().hex[:8]}"
    await _DB.lead_communications.insert_one({
        "id": row_id, "tenant_id": tenant_id, "lead_id": lid,
        "direction": "outbound", "channel": channel,
        "from_identity": "+14805559999",
        "to_identity":   "+14805550100",
        "subject": subject, "body": body, "status": status,
        "created_at": created_at or _iso(2026, 2, 10),
        "sent_by_user_id": f"{PFX}u_admin",
    })
    return row_id


async def _seed_lead_inbound(*, lid, tenant_id,
                               body="Thanks, call me back",
                               received_at=None):
    row_id = f"{PFX}in_{uuid.uuid4().hex[:8]}"
    await _DB.sms_inbound.insert_one({
        "id": row_id, "tenant_id": tenant_id,
        "matched_lead_id": lid,
        "from_identity": "+14805550100",
        "message_text":  body,
        "received_at":   received_at or _iso(2026, 2, 11),
    })
    return row_id


async def _seed_customer_marketing(*, cid, tenant_id,
                                       channel="email",
                                       created_at=None):
    row_id = f"{PFX}md_{uuid.uuid4().hex[:8]}"
    await _DB.marketing_deliveries.insert_one({
        "id": row_id, "tenant_id": tenant_id,
        "customer_id": cid, "channel": channel,
        "recipient_address": "cust@example.com",
        "subject": "Welcome aboard",
        "template_code": "welcome_v1",
        "delivery_status": "delivered",
        "created_at": created_at or _iso(2026, 2, 20),
    })
    return row_id


async def _wipe():
    rx = {"$regex": f"^{PFX}"}
    for coll in ("customers", "leads", "lead_communications",
                  "sms_inbound", "marketing_deliveries"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}, {"lead_id": rx},
                     {"customer_id": rx}, {"matched_lead_id": rx},
                     {"converted_customer_id": rx}]},
        )


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"


def _build_admin_app(tid):
    from routers import communication_timeline as mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": f"{PFX}u_admin", "role": "admin",
             "tenant_id": tid}
    tenant = {"id": tid}
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    mod.db = _DB
    return app


def _build_portal_app(tid, cid):
    from routers import communication_timeline as mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": f"{PFX}u_cust", "role": "customer",
             "customer_id": cid, "tenant_id": tid}
    tenant = {"id": tid}
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    mod.db = _DB
    return app


async def _get_admin(tid, cid, **params):
    app = _build_admin_app(tid)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport,
                             base_url="http://test") as c:
        r = await c.get(f"/api/customers/{cid}/timeline", params=params)
    return r.status_code, r.json()


async def _get_portal(tid, cid, **params):
    app = _build_portal_app(tid, cid)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport,
                             base_url="http://test") as c:
        r = await c.get("/api/customers/me/timeline", params=params)
    return r.status_code, r.json()


# ═══════════════════════════════════════════════════════════════════
# §1 · Happy path — interleaved lead-era + customer-era
# ═══════════════════════════════════════════════════════════════════
def test_converted_customer_timeline_interleaves_lead_and_customer_items():
    cid = f"{PFX}cust_1"
    lid = f"{PFX}lead_1"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT,
                          channel="sms", body="Lead-era SMS",
                          created_at=_iso(2026, 2, 10)))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT,
                          channel="email", subject="Lead-era email subject",
                          body="Lead-era email body",
                          created_at=_iso(2026, 2, 12)))
    _run(_seed_lead_inbound(lid=lid, tenant_id=TENANT,
                              body="Lead-era inbound reply",
                              received_at=_iso(2026, 2, 11)))
    _run(_seed_customer_marketing(cid=cid, tenant_id=TENANT,
                                      channel="email",
                                      created_at=_iso(2026, 2, 20)))

    status, body = _run(_get_admin(TENANT, cid, page=1, page_size=50))
    assert status == 200
    items = body["items"]
    assert len(items) == 4
    # Sorted DESC by occurred_at.
    occurred = [i.get("occurred_at") or i.get("created_at") for i in items]
    assert occurred == sorted(occurred, reverse=True)
    # Three lead-era items + 1 customer-era item.
    ref_types = {i["ref_type"] for i in items}
    assert "lead_communication" in ref_types
    assert "lead_sms_inbound" in ref_types
    assert "marketing_delivery" in ref_types


# ═══════════════════════════════════════════════════════════════════
# §2 · Multi-lead-to-one-customer merge branch
# ═══════════════════════════════════════════════════════════════════
def test_multi_lead_merge_into_one_customer():
    cid = f"{PFX}cust_merge"
    lid1 = f"{PFX}lead_m1"
    lid2 = f"{PFX}lead_m2"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid1, cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid2, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid1, tenant_id=TENANT, channel="sms",
                          body="From first lead",
                          created_at=_iso(2026, 1, 10)))
    _run(_seed_lead_comm(lid=lid2, tenant_id=TENANT, channel="sms",
                          body="From second lead",
                          created_at=_iso(2026, 2, 10)))

    status, body = _run(_get_admin(TENANT, cid, page=1, page_size=50))
    assert status == 200
    items = body["items"]
    assert len(items) == 2
    related_lead_ids = {(i.get("related_ref") or {}).get("id")
                           for i in items}
    assert related_lead_ids == {lid1, lid2}


# ═══════════════════════════════════════════════════════════════════
# §3 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_tenant_isolation_cross_tenant_lead_does_not_leak():
    TENANT_B = f"{PFX}tenant_B"
    cid = f"{PFX}cust_shared_id"
    lid_a = f"{PFX}lead_in_A"
    lid_b = f"{PFX}lead_in_B"
    # Tenant A: customer + converted lead + 1 comm.
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid_a, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid_a, tenant_id=TENANT, channel="sms",
                          body="Tenant A comm",
                          created_at=_iso(2026, 2, 10)))
    # Tenant B: coincidentally same converted_customer_id value.
    _run(_seed_converted_lead(lid=lid_b, cid=cid, tenant_id=TENANT_B))
    _run(_seed_lead_comm(lid=lid_b, tenant_id=TENANT_B, channel="sms",
                          body="Tenant B comm — must NOT leak",
                          created_at=_iso(2026, 2, 10)))

    status, body = _run(_get_admin(TENANT, cid, page=1, page_size=50))
    assert status == 200
    items = body["items"]
    assert len(items) == 1
    assert items[0].get("related_ref", {}).get("id") == lid_a


# ═══════════════════════════════════════════════════════════════════
# §4 · Non-converted customer regression
# ═══════════════════════════════════════════════════════════════════
def test_non_converted_customer_timeline_unchanged():
    cid = f"{PFX}cust_virgin"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_customer_marketing(cid=cid, tenant_id=TENANT,
                                      channel="email",
                                      created_at=_iso(2026, 2, 20)))

    status, body = _run(_get_admin(TENANT, cid, page=1, page_size=50))
    assert status == 200
    items = body["items"]
    assert len(items) == 1
    assert items[0]["ref_type"] == "marketing_delivery"


# ═══════════════════════════════════════════════════════════════════
# §5 · Portal field-safety
# ═══════════════════════════════════════════════════════════════════
def test_portal_timeline_surfaces_lead_era_without_admin_leakage():
    cid = f"{PFX}cust_portal"
    lid = f"{PFX}lead_portal"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="sms",
                          body="Portal-visible lead-era SMS",
                          created_at=_iso(2026, 2, 10)))

    status, body = _run(_get_portal(TENANT, cid, page=1, page_size=50))
    assert status == 200
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert item["ref_type"] == "lead_communication"
    # Admin-only top-level fields must NOT be present.
    assert "actor_user_id" not in item
    assert "delivery_error" not in item


# ═══════════════════════════════════════════════════════════════════
# §6 · Kind filter composition
# ═══════════════════════════════════════════════════════════════════
def test_kind_filter_scoped_to_sms_excludes_lead_era_email():
    cid = f"{PFX}cust_filter"
    lid = f"{PFX}lead_filter"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="sms",
                          body="SMS", created_at=_iso(2026, 2, 10)))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="email",
                          subject="Email", body="E body",
                          created_at=_iso(2026, 2, 11)))

    status, body = _run(_get_admin(TENANT, cid, page=1, page_size=50,
                                      kind="sms"))
    assert status == 200
    items = body["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "sms"


# ═══════════════════════════════════════════════════════════════════
# §7 · Date-range filter
# ═══════════════════════════════════════════════════════════════════
def test_date_range_excludes_lead_era_items_outside_range():
    cid = f"{PFX}cust_daterange"
    lid = f"{PFX}lead_daterange"
    _run(_seed_customer(cid=cid, tenant_id=TENANT))
    _run(_seed_converted_lead(lid=lid, cid=cid, tenant_id=TENANT))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="sms",
                          body="Before range",
                          created_at=_iso(2026, 1, 15)))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="sms",
                          body="Inside range",
                          created_at=_iso(2026, 2, 15)))
    _run(_seed_lead_comm(lid=lid, tenant_id=TENANT, channel="sms",
                          body="After range",
                          created_at=_iso(2026, 3, 15)))

    status, body = _run(_get_admin(
        TENANT, cid, page=1, page_size=50,
        **{"from": _iso(2026, 2, 1), "to": _iso(2026, 2, 28)}
    ))
    assert status == 200
    items = body["items"]
    assert len(items) == 1
    assert "Inside range" in (items[0].get("body")
                                or items[0].get("detail", {}).get("note_body")
                                or "")
