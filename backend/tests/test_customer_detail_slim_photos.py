"""Feb-2026 · GET /api/customers/{cid} slim-photos ship (backend regression).

Locks the shape of the embedded ``jobs`` array on the customer-detail
endpoint:

  1. ``GET /api/customers/{cid}`` drops each embedded job's full
     ``photos`` array and emits ``photo_count`` (int) + ``photo_ids``
     (list[str]) — mirrors the ``/api/jobs`` list slim-photos ship
     verbatim (see ``test_jobs_list_slim_photos.py``).
  2. Every embedded job carries BOTH keys (never ``None``), even
     legacy rows with no ``photos`` field.
  3. Response payload is materially smaller than the pre-slim shape
     (bench recorded in
     ``/app/memory/PERF_SLIM_PHOTOS_WORKSTREAM_AND_CUSTOMER.md``).

Uses live HTTP against the running FastAPI instance for parity with
the earlier slim-photos test file.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]], client


async def _tid(db):
    t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    return t["id"]


@pytest.fixture(scope="module")
def photo_customer():
    """Seed a customer + one job with 10 embedded photos.

    ~4 KB base64 blob per photo → ~40 KB overhead if the customer
    detail endpoint were to ship the full array. Assertion below
    proves it doesn't.
    """
    async def _setup():
        db, client = await _db()
        try:
            tid = await _tid(db)
            cid = "TEST_SLIM_CUST_" + uuid.uuid4().hex[:8]
            jid = "TEST_SLIM_JOB_" + uuid.uuid4().hex[:8]
            photos = [
                {"id": f"ph_{i:02d}",
                 "label": f"photo {i}",
                 "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB" * 128}
                for i in range(10)
            ]
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"Slim Photo Customer {cid}",
                "is_active": True,
            })
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": cid,
                "title": f"TEST_slim_photos_customer_{jid}",
                "status": "completed",
                "scheduled_date": "2026-01-15T09:00:00+00:00",
                "photos": photos,
            })
            return {"cid": cid, "jid": jid, "tid": tid,
                    "photo_ids": [p["id"] for p in photos],
                    "photo_count": 10}
        finally:
            client.close()

    seeded = _run(_setup())
    yield seeded

    async def _teardown():
        db, client = await _db()
        try:
            await db.customers.delete_one({"id": seeded["cid"]})
            await db.jobs.delete_one({"id": seeded["jid"]})
        finally:
            client.close()
    _run(_teardown())


# ═════════════════════════════════════════════════════════════════
# 1 · Default shape — full ``photos`` dropped, count/ids emitted.
# ═════════════════════════════════════════════════════════════════

def test_customer_detail_drops_photos_emits_count_and_ids(
    photo_customer, admin_headers,
):
    cid = photo_customer["cid"]
    jid = photo_customer["jid"]
    r = requests.get(f"{API}/customers/{cid}",
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    embedded = body.get("jobs") or []
    assert embedded, "expected embedded jobs list on customer detail"
    row = next((j for j in embedded if j.get("id") == jid), None)
    assert row is not None, f"seeded job {jid} missing from embedded list"
    # Slim contract — full photos array absent.
    assert "photos" not in row, (
        "slim-photos regression on /customers/{cid}: full photos "
        "array leaked into embedded jobs list"
    )
    # Count + ids emitted.
    assert row.get("photo_count") == 10, (
        f"photo_count mismatch: got {row.get('photo_count')} expected 10"
    )
    ids = row.get("photo_ids")
    assert isinstance(ids, list) and len(ids) == 10, (
        f"photo_ids missing / wrong length: {ids!r}"
    )
    assert set(ids) == set(photo_customer["photo_ids"]), (
        "photo_ids do not match seeded ids"
    )


# ═════════════════════════════════════════════════════════════════
# 2 · Every embedded job carries both slim keys (uniform shape).
# ═════════════════════════════════════════════════════════════════

def test_customer_detail_every_embedded_job_has_slim_keys(
    photo_customer, admin_headers,
):
    """Even if a legacy job has no ``photos`` field, the response
    must normalize it to ``photo_count=0`` + ``photo_ids=[]`` so
    the frontend contract is uniform."""
    cid = photo_customer["cid"]
    # Seed a second job on the SAME customer with NO photos field.
    async def _seed_bare():
        db, client = await _db()
        try:
            bare_jid = "TEST_SLIM_BARE_" + uuid.uuid4().hex[:8]
            await db.jobs.insert_one({
                "id": bare_jid, "tenant_id": photo_customer["tid"],
                "customer_id": cid,
                "title": "TEST_bare_no_photos",
                "status": "scheduled",
                "scheduled_date": "2026-02-01T09:00:00+00:00",
            })
            return bare_jid
        finally:
            client.close()

    bare_jid = _run(_seed_bare())
    try:
        r = requests.get(f"{API}/customers/{cid}",
                           headers=admin_headers, timeout=30)
        assert r.status_code == 200
        embedded = r.json().get("jobs") or []
        for row in embedded:
            assert "photo_count" in row, (
                f"job {row.get('id')} missing photo_count"
            )
            assert "photo_ids" in row, (
                f"job {row.get('id')} missing photo_ids"
            )
            assert isinstance(row["photo_count"], int)
            assert isinstance(row["photo_ids"], list)
        # Verify our bare row specifically.
        bare = next((j for j in embedded if j.get("id") == bare_jid), None)
        assert bare is not None
        assert bare["photo_count"] == 0
        assert bare["photo_ids"] == []
    finally:
        async def _teardown():
            db, client = await _db()
            try:
                await db.jobs.delete_one({"id": bare_jid})
            finally:
                client.close()
        _run(_teardown())


# ═════════════════════════════════════════════════════════════════
# 3 · Bench — slim response is materially smaller than pre-slim.
# ═════════════════════════════════════════════════════════════════

def test_customer_detail_response_size_smaller_than_full_photos(
    photo_customer, admin_headers,
):
    """Compare the live slim response size against the size the
    same payload WOULD have with ``photos`` restored. Materiality
    threshold: slim ≥ 5× smaller for a 10-photo × ~4 KB seed."""
    cid = photo_customer["cid"]
    r = requests.get(f"{API}/customers/{cid}",
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200
    slim_size = len(r.content)

    # Rehydrate what the response WOULD be if we restored ``photos``.
    async def _read_full_photos():
        db, client = await _db()
        try:
            job = await db.jobs.find_one({"id": photo_customer["jid"]},
                                              {"_id": 0, "photos": 1})
            return job.get("photos") or []
        finally:
            client.close()

    photos = _run(_read_full_photos())
    # Approximate: bytes added if the response had shipped full photos.
    import json as _json
    photos_bytes = len(_json.dumps(photos).encode("utf-8"))
    hypothetical_full_size = slim_size + photos_bytes
    ratio = hypothetical_full_size / max(1, slim_size)
    assert ratio >= 5.0, (
        f"slim-photos win too small: slim={slim_size} "
        f"full={hypothetical_full_size} ratio={ratio:.2f}× "
        f"(expected ≥ 5×)"
    )
