"""Feb-2026 · Schedule map — jobs listing exposes customer geocoded
coordinates under the ``location_lat`` / ``location_lng`` alias so
the web + mobile schedule maps can render pins without an N+1
customer lookup. Tenant-scoped: a job's coords are read from the
customer doc scoped to the SAME tenant as the job.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _login(email: str) -> str:
    for _ in range(4):
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": demo_pw(email)},
                              timeout=30)
            assert r.status_code == 200, r.text
            return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout,
                 requests.exceptions.ConnectionError):
            continue
    raise AssertionError("could not login super@aquaterra.com")


def _fresh_db():
    loop = asyncio.get_event_loop()
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    return client[_ENV["DB_NAME"]], client


async def _seed_customer(db, tenant_id, *, lat, lng):
    cid = f"TEST_smap_{uuid.uuid4().hex[:8]}"
    await db.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": f"TEST_smap {cid}",
        "email": f"{cid}@example.com",
        "service_lat": lat,
        "service_lng": lng,
    })
    return cid


async def _seed_job(db, tenant_id, *, customer_id, sched_date):
    jid = f"TEST_smap_job_{uuid.uuid4().hex[:8]}"
    await db.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": f"TEST_smap {jid}",
        "service_type": "Weekly Pool Service",
        "scheduled_date": sched_date,
        "status": "pending",
    })
    return jid


async def _cleanup(db, tenant_id):
    await db.customers.delete_many(
        {"tenant_id": tenant_id, "id": {"$regex": "^TEST_smap_"}})
    await db.jobs.delete_many(
        {"tenant_id": tenant_id, "id": {"$regex": "^TEST_smap_"}})


def _resolve_tenant_id(super_token) -> str:
    """The super_admin's active tenant id is exposed by the
    /auth/me endpoint under ``tenant_id`` — grab it once per test."""
    r = requests.get(f"{API}/auth/me",
                     headers={"Authorization": f"Bearer {super_token}"},
                     timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    tid = body.get("tenant_id") or body.get("user", {}).get("tenant_id")
    assert tid, f"could not resolve tenant_id from /auth/me: {body}"
    return tid


def test_list_jobs_returns_location_lat_lng_when_customer_geocoded():
    """Job payloads include ``location_lat`` / ``location_lng`` copied
    from the linked customer's ``service_lat`` / ``service_lng``. Both
    keys are always present (may be null) so the shape is stable."""
    tok = _login("super@aquaterra.com")
    tid = _resolve_tenant_id(tok)

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            geoc_cid = await _seed_customer(db, tid, lat=33.75, lng=-112.35)
            geoc_jid = await _seed_job(
                db, tid, customer_id=geoc_cid, sched_date="2027-01-15")
            ungeoc_cid = await _seed_customer(db, tid, lat=None, lng=None)
            ungeoc_jid = await _seed_job(
                db, tid, customer_id=ungeoc_cid, sched_date="2027-01-15")
            return geoc_jid, ungeoc_jid
        finally:
            client.close()

    geoc_jid, ungeoc_jid = asyncio.get_event_loop().run_until_complete(_drive())

    try:
        r = requests.get(
            f"{API}/jobs?start=2027-01-15&end=2027-01-15",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body if isinstance(body, list) else body.get("items", [])
        by_id = {row["id"]: row for row in rows}
        assert geoc_jid in by_id, f"geocoded job missing from response: {list(by_id.keys())[:5]}"
        assert ungeoc_jid in by_id
        # Geocoded row → coords populated.
        assert by_id[geoc_jid]["location_lat"] == pytest.approx(33.75)
        assert by_id[geoc_jid]["location_lng"] == pytest.approx(-112.35)
        # Ungeocoded row → both keys present, both null.
        assert by_id[ungeoc_jid]["location_lat"] is None
        assert by_id[ungeoc_jid]["location_lng"] is None
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_list_jobs_location_keys_are_tenant_scoped():
    """A customer's coords must NOT bleed across tenants — the projection
    only reads customer docs matching the caller's active tenant. We
    seed a job whose ``customer_id`` matches a customer in a DIFFERENT
    tenant; the join must miss and both location keys must be null."""
    tok = _login("super@aquaterra.com")
    tid = _resolve_tenant_id(tok)
    other_tid = f"TEST_smap_other_tenant_{uuid.uuid4().hex[:6]}"

    async def _drive():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            # Customer with coords lives in a DIFFERENT tenant.
            leaky_cid = f"TEST_smap_leaky_{uuid.uuid4().hex[:8]}"
            await db.customers.insert_one({
                "id": leaky_cid, "tenant_id": other_tid,
                "name": "TEST_smap other-tenant customer",
                "email": f"{leaky_cid}@example.com",
                "service_lat": 40.0, "service_lng": -80.0,
            })
            # Job in OUR tenant references the leaky customer id.
            jid = await _seed_job(
                db, tid, customer_id=leaky_cid, sched_date="2027-02-15")
            return leaky_cid, jid
        finally:
            client.close()

    leaky_cid, jid = asyncio.get_event_loop().run_until_complete(_drive())

    try:
        r = requests.get(
            f"{API}/jobs?start=2027-02-15&end=2027-02-15",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body if isinstance(body, list) else body.get("items", [])
        by_id = {row["id"]: row for row in rows}
        assert jid in by_id
        # Tenant isolation — the OTHER tenant's coords must NOT leak.
        assert by_id[jid]["location_lat"] is None
        assert by_id[jid]["location_lng"] is None
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
                await db.customers.delete_one({"id": leaky_cid})
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())
