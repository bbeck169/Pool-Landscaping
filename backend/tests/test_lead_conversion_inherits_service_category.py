"""P2 #6 · Feb-2026 — Lead service_interest → customer service_category inheritance pytest.

Locks four invariants on ``_run_close_won_pipeline``:
  1. On first conversion, lead.service_interest "Pool" (title case)
     → customer.service_category "pool" (lowercase) on the created
     customer doc.
  2. "Landscape" (lead's noun form) → "landscaping" (customer's
     gerund form).  "Both" passes through verbatim lowercase.
  3. Case + whitespace tolerant: "  POOL  " still lands as "pool".
  4. Merge branch — when the lead matches an EXISTING customer who
     already has service_category set, the lead inheritance is
     silent (first-write-wins, no overwrite).
  5. Lead with no / unknown service_interest leaves the customer's
     service_category at null (silent fallback).
  6. The pipeline return envelope includes the
     ``inherited_service_category`` tag.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
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
    for mod in ("routers.leads",
                "services.lead_conversion_notifications"):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"p26c-{uuid4().hex[:8]}"
TENANT = f"{PREFIX}-tenant"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_tenant():
    await _DB.tenants.insert_one({"id": TENANT, "name": "T",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_lead(lid, *, name="L", interest=None, email=None):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": TENANT, "name": name,
        "email": email or f"{lid}@example.com", "phone": "480-555-9999",
        "service_address": "100 Palo Verde Way", "address": "100 Palo Verde Way",
        "service_interest": interest,
        "status": "new", "source": "admin_manual",
        "timeline": [], "notes": "",
    })


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("leads", "customers", "audit_logs", "marketing_deliveries",
                 "marketing_drip_enrollments", "sales_sequences",
                 "outbound_emails"):
        await _DB[coll].delete_many({"$or": [
            {"id": rx}, {"tenant_id": rx}, {"email": rx}, {"lead_id": rx},
            {"customer_id": rx},
        ]})
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())

    # Hermetic patch for the welcome bundle (resend / RC adapters).
    import services.lead_conversion_notifications as _m
    import sys as _sys

    async def _fake(**kw):
        return {"email_id": None, "sms_id": None,
                 "drip_enrollment_id": None}
    _m.fire_welcome_bundle = _fake
    _sys.modules["services.lead_conversion_notifications"].fire_welcome_bundle = _fake

    yield
    _run(_cleanup())


async def _close_won(lid):
    from routers.leads import _run_close_won_pipeline
    lead = await _DB.leads.find_one({"id": lid}, {"_id": 0})
    return await _run_close_won_pipeline(
        lead, TENANT, actor_user_id=ADMIN["id"],
    )


@pytest.mark.parametrize("interest,expected", [
    ("Pool", "pool"),
    ("Landscape", "landscaping"),
    ("Landscaping", "landscaping"),
    ("Both", "both"),
    ("  POOL  ", "pool"),
])
def test_inheritance_maps_lead_interest_to_customer_category(interest, expected):
    _run(_seed_tenant())
    lid = f"{PREFIX}-lead-{uuid4().hex[:6]}"
    _run(_seed_lead(lid, interest=interest))
    result = _run(_close_won(lid))
    cid = result["customer_id"]
    assert result.get("inherited_service_category") == expected
    cust = _run(_DB.customers.find_one({"id": cid}, {"_id": 0}))
    assert cust is not None
    assert cust.get("service_category") == expected


def test_null_or_unknown_interest_leaves_category_unset():
    _run(_seed_tenant())
    for i, interest in enumerate([None, "", "Spa", "random text"]):
        lid = f"{PREFIX}-lead-null-{i}"
        _run(_seed_lead(lid, interest=interest))
        result = _run(_close_won(lid))
        cust = _run(_DB.customers.find_one({"id": result["customer_id"]},
                                                {"_id": 0}))
        assert cust.get("service_category") is None, (
            f"interest={interest!r} should NOT stamp a category "
            f"(got {cust.get('service_category')!r})"
        )
        assert result.get("inherited_service_category") is None


def test_merge_branch_does_not_overwrite_existing_category():
    _run(_seed_tenant())
    # Pre-seed a customer with a set category who matches by email.
    cust_id = f"{PREFIX}-cust-pre"
    _run(_DB.customers.insert_one({
        "id": cust_id, "tenant_id": TENANT, "name": "Pre",
        "email": "pre@example.com", "phone": "",
        "service_category": "landscaping",
    }))
    lid = f"{PREFIX}-lead-merge"
    _run(_seed_lead(lid, interest="Pool", email="pre@example.com"))
    result = _run(_close_won(lid))
    assert result["customer_id"] == cust_id
    assert result["was_merged"] is True
    cust = _run(_DB.customers.find_one({"id": cust_id}, {"_id": 0}))
    # First-write-wins: existing "landscaping" is preserved.
    assert cust.get("service_category") == "landscaping"


def test_merge_branch_stamps_when_existing_category_is_null():
    _run(_seed_tenant())
    cust_id = f"{PREFIX}-cust-null"
    _run(_DB.customers.insert_one({
        "id": cust_id, "tenant_id": TENANT, "name": "Null",
        "email": "null@example.com", "phone": "",
        # service_category not set — null branch
    }))
    lid = f"{PREFIX}-lead-stamp"
    _run(_seed_lead(lid, interest="Both", email="null@example.com"))
    result = _run(_close_won(lid))
    assert result["customer_id"] == cust_id
    cust = _run(_DB.customers.find_one({"id": cust_id}, {"_id": 0}))
    assert cust.get("service_category") == "both"
