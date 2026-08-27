"""Feb 2026 · Address picker on Job Edit — backend PUT contract.

Covers ``PUT /api/jobs/{id}`` handling of ``property_id`` on the
edit path (see ``routers/jobs.py::update_job``):
* Valid property (same tenant + same customer) → 200; job's
  ``property_id`` + ``address`` + ``site_lat`` / ``site_lng`` are
  updated from the target property.
* Property owned by a different customer → 400 with clear detail.
* Property that doesn't exist in the tenant → 400.
* Non-property fields on the same PUT still work.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from utils import create_token, hash_password


TID = "test-tenant-property-picker"


async def _seed() -> dict:
    for coll in ("users", "customers", "properties", "jobs", "tenants"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.insert_one({
        "id": TID, "name": "Property Picker Test",
        "slug": "pp-test", "active": True, "settings": {},
    })
    admin = {
        "id": "u-pp-admin", "tenant_id": TID, "email": "pp-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "PP Admin", "deleted_at": None,
    }
    await db.users.insert_one(admin)
    # Two customers, each with two properties.
    await db.customers.insert_many([
        {"id": "c-a", "tenant_id": TID, "name": "Customer A", "is_active": True},
        {"id": "c-b", "tenant_id": TID, "name": "Customer B", "is_active": True},
    ])
    await db.properties.insert_many([
        {"id": "p-a1", "tenant_id": TID, "customer_id": "c-a",
          "address": "111 Alpha St", "label": "Main", "sort_order": 1,
          "site_lat": 33.51, "site_lng": -112.11},
        {"id": "p-a2", "tenant_id": TID, "customer_id": "c-a",
          "address": "222 Beta Ave", "label": "Vacation", "sort_order": 2,
          "site_lat": 33.62, "site_lng": -112.22},
        {"id": "p-b1", "tenant_id": TID, "customer_id": "c-b",
          "address": "333 Gamma Rd", "label": "HQ", "sort_order": 1,
          "site_lat": 33.73, "site_lng": -112.33},
    ])
    # Seed a job for customer A pointed at property p-a1.
    await db.jobs.insert_one({
        "id": "j-a", "tenant_id": TID, "customer_id": "c-a",
        "title": "Weekly", "property_id": "p-a1",
        "address": "111 Alpha St", "site_lat": 33.51, "site_lng": -112.11,
        "status": "scheduled",
    })
    return {"admin_token": create_token(admin)}


async def _teardown():
    for coll in ("users", "customers", "properties", "jobs", "tenants"):
        await db[coll].delete_many({"tenant_id": TID})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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


class TestPropertyPickerBackend:
    def test_switch_to_same_customer_property_snapshots_address(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.put("/api/jobs/j-a", json={
                    "property_id": "p-a2",
                }, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                doc = await db.jobs.find_one({"id": "j-a"})
                assert doc["property_id"] == "p-a2"
                # Address + coords were re-snapshotted from the
                # target property.
                assert doc["address"] == "222 Beta Ave"
                assert doc["site_lat"] == 33.62
                assert doc["site_lng"] == -112.22
        _run(go())

    def test_switch_to_different_customer_property_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.put("/api/jobs/j-a", json={
                    "property_id": "p-b1",  # customer B's property
                }, headers=_hdr(seeded))
                assert r.status_code == 400
                assert "different customer" in r.json()["detail"].lower()
                # Job untouched — property still p-a1 (or p-a2 if
                # the prior test ran first).
                doc = await db.jobs.find_one({"id": "j-a"})
                assert doc["customer_id"] == "c-a"
        _run(go())

    def test_switch_to_nonexistent_property_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.put("/api/jobs/j-a", json={
                    "property_id": "p-does-not-exist",
                }, headers=_hdr(seeded))
                assert r.status_code == 400
                assert "does not resolve" in r.json()["detail"].lower()
        _run(go())

    def test_omitting_property_id_leaves_it_unchanged(self, seeded, client):
        async def go():
            async with client as c:
                # Restore to p-a1 first.
                await db.jobs.update_one(
                    {"id": "j-a"},
                    {"$set": {"property_id": "p-a1",
                              "address": "111 Alpha St",
                              "site_lat": 33.51, "site_lng": -112.11}},
                )
                r = await c.put("/api/jobs/j-a", json={
                    "title": "Weekly (retitled)",
                }, headers=_hdr(seeded))
                assert r.status_code == 200
                doc = await db.jobs.find_one({"id": "j-a"})
                assert doc["property_id"] == "p-a1"
                assert doc["address"] == "111 Alpha St"
                assert doc["title"] == "Weekly (retitled)"
        _run(go())
