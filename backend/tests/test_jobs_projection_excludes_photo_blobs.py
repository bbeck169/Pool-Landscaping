"""Feb-2026 · PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS sweep.

Locks the wire contracts after the bulk projection sweep:

  1. Every full-doc-fetch ``db.jobs.find*(...)`` in the backend now
     applies ``{"photos.data": 0}`` at the Mongo boundary — the
     base64 blobs never leave Mongo → process wire traffic drops
     proportionally.
  2. Slim-photos wire contract is preserved:
     * ``photo_count`` + ``photo_ids`` still emit correctly (they
       derive from ``len(photos)`` and ``photos[].id`` — both of
       which survive the ``photos.data`` exclusion via Mongo
       dot-notation).
  3. The single-job detail endpoint ``GET /api/jobs/{jid}`` is the
     documented opt-out — still returns full ``photos`` including
     ``data``.
  4. ``GET /api/jobs?include_photos=true`` opt-in still returns
     full ``photos`` including ``data`` — the conditional
     projection branch honors the query param.

Bench: sanity check that a full-doc fetch on a job with 10 embedded
photos returns a payload smaller than the equivalent
``{"_id": 0}``-projection fetch would.
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
    t = await db.tenants.find_one({"slug": "aquaterra"},
                                     {"_id": 0, "id": 1})
    return t["id"]


@pytest.fixture(scope="module")
def photo_job():
    """Seed a customer + job with 10 photos carrying real base64
    blobs. The blobs are large enough (~4 KB each) that the
    excluded-vs-included byte-count delta is unambiguous.
    """
    async def _setup():
        db, client = await _db()
        try:
            tid = await _tid(db)
            cid = "TEST_PROJ_CUST_" + uuid.uuid4().hex[:8]
            jid = "TEST_PROJ_JOB_" + uuid.uuid4().hex[:8]
            blob = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB" * 128
            photos = [
                {"id": f"ph_{i:02d}",
                 "label": f"photo {i}",
                 "data": f"data:image/jpeg;base64,{blob}",
                 "created_at": "2026-02-10T22:00:00+00:00"}
                for i in range(10)
            ]
            await db.customers.insert_one({
                "id": cid, "tenant_id": tid,
                "name": f"Proj Test {cid}",
                "is_active": True,
            })
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": cid,
                "title": f"TEST_projection_sweep_{jid}",
                "status": "completed",
                "scheduled_date": "2026-01-15T09:00:00+00:00",
                "photos": photos,
            })
            return {"cid": cid, "jid": jid, "tid": tid,
                    "photo_ids": [p["id"] for p in photos]}
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


def _list_rows(r):
    """Extract job rows from the /api/jobs response — supports
    both bare-list and ``{items: [...]}`` envelope shapes."""
    body = r.json()
    return body if isinstance(body, list) else (body.get("items") or [])


# ═════════════════════════════════════════════════════════════════
# 1 · List surface — ``photo_count`` + ``photo_ids`` still populate,
#     ``photos`` array is absent, ``photos.data`` never fetched.
# ═════════════════════════════════════════════════════════════════

def test_jobs_list_still_emits_photo_count_and_ids(photo_job, admin_headers):
    r = requests.get(f"{API}/jobs",
                       params={"customer_id": photo_job["cid"]},
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    rows = _list_rows(r)
    row = next((j for j in rows if j.get("id") == photo_job["jid"]), None)
    assert row is not None
    assert "photos" not in row, (
        "slim-photos regression: full photos leaked on list surface"
    )
    assert row["photo_count"] == 10
    assert set(row["photo_ids"]) == set(photo_job["photo_ids"])


# ═════════════════════════════════════════════════════════════════
# 2 · Detail surface — full ``photos`` including ``data`` still
#     ships. Opt-out from the projection sweep verified.
# ═════════════════════════════════════════════════════════════════

def test_jobs_detail_still_returns_full_photos_with_base64_data(
    photo_job, admin_headers,
):
    r = requests.get(f"{API}/jobs/{photo_job['jid']}",
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    doc = r.json()
    photos = doc.get("photos") or []
    assert len(photos) == 10, (
        f"detail dropped photos: only {len(photos)} returned "
        "(sweep should NOT touch the detail endpoint)"
    )
    for p in photos:
        assert p.get("id")
        assert p.get("data"), (
            "detail regression: photo.data missing — the "
            "PERF-MONGO-PROJECT sweep must OPT OUT of GET /jobs/{jid}"
        )
        assert p["data"].startswith("data:image/"), (
            "detail regression: photo.data no longer carries base64 prefix"
        )


# ═════════════════════════════════════════════════════════════════
# 3 · List opt-in — ``?include_photos=true`` still ships full
#     photos including ``data``.
# ═════════════════════════════════════════════════════════════════

def test_jobs_list_include_photos_true_still_ships_full_data(
    photo_job, admin_headers,
):
    r = requests.get(f"{API}/jobs",
                       params={"customer_id": photo_job["cid"],
                               "include_photos": "true"},
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    rows = _list_rows(r)
    row = next((j for j in rows if j.get("id") == photo_job["jid"]), None)
    assert row is not None
    photos = row.get("photos") or []
    assert len(photos) == 10, (
        f"opt-in regression: only {len(photos)} photos returned"
    )
    for p in photos:
        assert p.get("data"), (
            "opt-in regression: photo.data missing when "
            "?include_photos=true — conditional projection must "
            "restore the full doc"
        )
    # ``photo_count`` and ``photo_ids`` remain a strict superset
    # (present alongside the full photos array).
    assert row["photo_count"] == 10
    assert set(row["photo_ids"]) == set(photo_job["photo_ids"])


# ═════════════════════════════════════════════════════════════════
# 4 · Wire-size bench — list-surface payload is materially smaller
#     than the include_photos=true payload for the SAME rows.
# ═════════════════════════════════════════════════════════════════

def test_list_wire_size_smaller_than_include_photos_variant(
    photo_job, admin_headers,
):
    r_slim = requests.get(f"{API}/jobs",
                           params={"customer_id": photo_job["cid"]},
                           headers=admin_headers, timeout=30)
    r_full = requests.get(f"{API}/jobs",
                           params={"customer_id": photo_job["cid"],
                                   "include_photos": "true"},
                           headers=admin_headers, timeout=30)
    assert r_slim.status_code == 200
    assert r_full.status_code == 200
    slim = len(r_slim.content)
    full = len(r_full.content)
    ratio = full / max(1, slim)
    assert ratio >= 5.0, (
        f"wire-size bench too small: slim={slim} full={full} "
        f"ratio={ratio:.2f}× (expected ≥ 5×)"
    )


# ═════════════════════════════════════════════════════════════════
# 5 · Helper constant contract — the shared projection module
#     emits the exact keys downstream call sites depend on.
# ═════════════════════════════════════════════════════════════════

def test_shared_helper_exposes_projection_constants():
    """Guards the helper's public API — any rename requires
    a coordinated update across ~60 call sites."""
    from services.jobs_slim_photos import (
        JOBS_LIST_PROJECTION,
        JOBS_LIST_PROJECT_STAGE,
        JOBS_PHOTOS_ONLY_EXCLUDE,
        jobs_projection,
    )
    assert JOBS_LIST_PROJECTION == {"_id": 0, "photos.data": 0}
    assert JOBS_LIST_PROJECT_STAGE == {"_id": 0, "photos.data": 0}
    assert JOBS_PHOTOS_ONLY_EXCLUDE == {"photos.data": 0}
    # include_photos=False → slim projection.
    assert jobs_projection(include_photos=False) == \
        {"_id": 0, "photos.data": 0}
    # include_photos=True → full doc.
    assert jobs_projection(include_photos=True) == {"_id": 0}
    # Returned dict is a copy — mutating the caller's copy must
    # NOT mutate the module constant.
    p = jobs_projection(include_photos=False)
    p["extra"] = 1
    assert "extra" not in JOBS_LIST_PROJECTION
