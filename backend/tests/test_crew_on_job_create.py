"""Feb-2026 · Crew assignment on New Job create.

Covers ``POST /api/jobs`` handling of ``crew_id`` (see
``routers/jobs.py::create_job``):

* Valid same-tenant crew → 200; job persists ``crew_id``,
  denormalized ``crew_name`` + ``crew_color``. ``technician_id``
  is preserved (overlay, never replacement).
* Crew from a different tenant → 400 with clear detail.
* Non-existent crew id → 400.
* Omitting ``crew_id`` → job created without crew fields (back-
  compat with legacy callers).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from utils import create_token, hash_password


TID_A = "test-tenant-crew-create-a"
TID_B = "test-tenant-crew-create-b"


async def _seed() -> dict:
    for coll in ("users", "customers", "properties", "jobs",
                  "tenants", "crews"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
    await db.tenants.delete_many({"id": {"$in": [TID_A, TID_B]}})
    for tid, slug in ((TID_A, "cc-a"), (TID_B, "cc-b")):
        await db.tenants.insert_one({
            "id": tid, "name": f"Crew Create {tid}",
            "slug": slug, "active": True, "settings": {},
        })
    admin = {
        "id": "u-cc-admin", "tenant_id": TID_A,
        "email": "cc-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "CC Admin", "deleted_at": None,
    }
    await db.users.insert_one(admin)
    await db.customers.insert_one({
        "id": "c-cc", "tenant_id": TID_A, "name": "Crew Customer",
        "is_active": True,
    })
    await db.crews.insert_many([
        {"id": "crew-a", "tenant_id": TID_A, "name": "Blue Crew",
          "color": "#0284C7", "tech_ids": []},
        {"id": "crew-b", "tenant_id": TID_B, "name": "Other-Tenant Crew",
          "color": "#DC2626", "tech_ids": []},
    ])
    return {"admin_token": create_token(admin)}


async def _teardown():
    for coll in ("users", "customers", "properties", "jobs",
                  "tenants", "crews"):
        await db[coll].delete_many({"tenant_id": {"$in": [TID_A, TID_B]}})
    await db.tenants.delete_many({"id": {"$in": [TID_A, TID_B]}})


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


class TestCreateJobWithCrew:
    def test_create_with_valid_crew_persists_denorms(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Weekly with crew",
                    "customer_id": "c-cc",
                    "crew_id": "crew-a",
                }, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["crew_id"] == "crew-a"
                assert body["crew_name"] == "Blue Crew"
                assert body["crew_color"] == "#0284C7"
                # Verify persisted state.
                doc = await db.jobs.find_one({"id": body["id"]})
                assert doc["crew_id"] == "crew-a"
                assert doc["crew_name"] == "Blue Crew"
        _run(go())

    def test_create_with_crew_and_tech_are_both_stored(self, seeded, client):
        """Crew is an OVERLAY — technician_id must not be cleared."""
        async def go():
            async with client as c:
                # Seed a technician in the same tenant.
                await db.technicians.delete_many({"tenant_id": TID_A})
                await db.technicians.insert_one({
                    "id": "tech-cc", "tenant_id": TID_A, "name": "Tech CC",
                })
                r = await c.post("/api/jobs", json={
                    "title": "Both tech + crew",
                    "customer_id": "c-cc",
                    "technician_id": "tech-cc",
                    "crew_id": "crew-a",
                }, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["technician_id"] == "tech-cc"
                assert body["crew_id"] == "crew-a"
                await db.technicians.delete_many({"tenant_id": TID_A})
        _run(go())

    def test_create_with_cross_tenant_crew_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Cross-tenant crew",
                    "customer_id": "c-cc",
                    "crew_id": "crew-b",  # tenant B
                }, headers=_hdr(seeded))
                assert r.status_code == 400
                assert "crew" in r.json()["detail"].lower()
        _run(go())

    def test_create_with_nonexistent_crew_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Ghost crew",
                    "customer_id": "c-cc",
                    "crew_id": "crew-does-not-exist",
                }, headers=_hdr(seeded))
                assert r.status_code == 400
                assert "crew" in r.json()["detail"].lower()
        _run(go())

    def test_create_without_crew_backcompat(self, seeded, client):
        """Legacy caller omitting ``crew_id`` still creates a job."""
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "No crew",
                    "customer_id": "c-cc",
                }, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                body = r.json()
                assert body.get("crew_id") is None
                assert "crew_name" not in body or body.get("crew_name") is None
        _run(go())
