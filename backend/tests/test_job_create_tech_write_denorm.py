"""Feb-2026 · P0 hotfix — Write-side tech-assignment identity mismatch.

The New Job form on prod was creating every job as "Unassigned"
even though the tech was clearly selected in the picker. Cause:

  * ``GET /api/technicians`` returns a UNION of real ``db.technicians``
    docs (id shape = ``technicians._id``) AND synthesized rows from
    ``db.users`` (id shape = ``user.technician_id || user.id``). Real
    team members added through the roster UI live in the second bucket.
  * The frontend picker binds ``<option value={t.id}>`` — so the
    posted ``technician_id`` is whichever shape the tech came in as.
  * The old write handlers did a single-collection lookup
    (``db.technicians.find_one({id: technician_id})``) and stamped
    ``technician_name = None`` when the id was a synth-from-users
    shape — the id every real team member has.
  * The GET /jobs/{jid} read path returned the raw doc verbatim, so
    a job stamped with ``technician_name = null`` at write-time
    rendered "Unassigned" forever.

This suite locks the fix in place:

  1. Create a job with ``technician_id = user.id`` (synth shape) →
     ``technician_name`` populated in the response.
  2. Create a job with ``technician_id = technicians.id`` (real shape)
     → same.
  3. PATCH an existing job's ``technician_id`` to a synth shape →
     ``technician_name`` denorm is refreshed on the stored doc.
  4. GET /jobs/{jid} on a doc stamped ``technician_name = null``
     (simulates historical prod data) with a valid ``technician_id``
     → response emits the resolved name via the cascade fallback.

Cleanup: TEST_ prefixed titles + ``TEST-tid-write-`` prefixed ids so
the session teardown hook in conftest.py sweeps automatically. The
module-scoped autouse fixture also self-cleans on setup + teardown.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

_JOB_TITLE_PREFIX = "TEST_TidWrite_"
_ID_PREFIX = "TEST-tid-write-"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


async def _get_tenant_id(slug: str = "aquaterra") -> str:
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _pick_customer_id(tenant_id: str) -> str:
    c = await _db().customers.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    assert c, "expected at least one customer in aquaterra"
    return c["id"]


async def _get_mike_identity(tenant_id: str) -> dict:
    """Return Mike's three id shapes so we can exercise both cascade
    rungs the write helper depends on."""
    mike = await _db().users.find_one(
        {"email": "mike@aquaterra.com", "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "technician_id": 1,
         "name": 1, "first_name": 1, "last_name": 1},
    )
    assert mike, "mike@aquaterra.com is a required seed"
    uid = mike["id"]
    tdoc = await _db().technicians.find_one(
        {"tenant_id": tenant_id, "user_id": uid},
        {"_id": 0, "id": 1, "name": 1},
    ) or {}
    display = (
        mike.get("name")
        or f"{mike.get('first_name', '')} {mike.get('last_name', '')}".strip()
        or tdoc.get("name")
    )
    return {
        "user_id": uid,
        "tech_doc_id": tdoc.get("id"),
        "expected_name": display,
    }


async def _cleanup() -> None:
    seeded_ids = [j["id"] async for j in _db().jobs.find(
        {"$or": [
            {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}},
            {"id": {"$regex": f"^{_ID_PREFIX}"}},
        ]},
        {"_id": 0, "id": 1},
    )]
    await _db().jobs.delete_many(
        {"id": {"$in": seeded_ids}} if seeded_ids
        else {"id": {"$regex": f"^{_ID_PREFIX}"}})


@pytest.fixture(scope="module", autouse=True)
def seed_ctx():
    tenant_id = _run(_get_tenant_id())
    customer_id = _run(_pick_customer_id(tenant_id))
    mike = _run(_get_mike_identity(tenant_id))
    _run(_cleanup())
    yield {"tenant_id": tenant_id, "customer_id": customer_id, "mike": mike}
    _run(_cleanup())


def _job_payload(customer_id: str, tech_id: str, label: str) -> dict:
    return {
        "customer_id": customer_id,
        "title": f"{_JOB_TITLE_PREFIX}{label}",
        "service_type": "Weekly Pool Cleaning",
        "job_type": "pool",
        "scheduled_date": "2099-10-15",
        "technician_id": tech_id,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════
def test_create_with_users_id_shape_populates_technician_name(
    admin_headers, seed_ctx,
):
    """The exact bug the user reported — creating a job with a synth-
    from-users technician_id must land ``technician_name`` populated,
    not null."""
    uid = seed_ctx["mike"]["user_id"]
    expected = seed_ctx["mike"]["expected_name"]
    r = requests.post(
        f"{API}/jobs",
        headers=admin_headers,
        json=_job_payload(seed_ctx["customer_id"], uid, "synth_shape"),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("technician_id") == uid
    assert body.get("technician_name") == expected, (
        f"synth-shape create: expected technician_name={expected!r}, "
        f"got {body.get('technician_name')!r}"
    )


def test_create_with_technicians_id_shape_populates_technician_name(
    admin_headers, seed_ctx,
):
    """Regression guard on the real-tech-doc path — same rung 1 lookup
    that used to work must keep working under the new cascade helper."""
    tdoc_id = seed_ctx["mike"]["tech_doc_id"]
    if not tdoc_id:
        pytest.skip("no real technicians.id shape available for Mike")
    expected = seed_ctx["mike"]["expected_name"]
    r = requests.post(
        f"{API}/jobs",
        headers=admin_headers,
        json=_job_payload(seed_ctx["customer_id"], tdoc_id, "real_shape"),
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("technician_id") == tdoc_id
    assert body.get("technician_name") == expected


def test_patch_technician_id_refreshes_denorm(admin_headers, seed_ctx):
    """PATCH /jobs/{jid} with a new technician_id must refresh the
    denormalized ``technician_name`` — same cascade helper."""
    uid = seed_ctx["mike"]["user_id"]
    expected = seed_ctx["mike"]["expected_name"]
    # Create with NO tech first.
    r_create = requests.post(
        f"{API}/jobs",
        headers=admin_headers,
        json={
            "customer_id": seed_ctx["customer_id"],
            "title": f"{_JOB_TITLE_PREFIX}patch_source",
            "service_type": "Weekly Pool Cleaning",
            "job_type": "pool",
            "scheduled_date": "2099-10-16",
        },
        timeout=30,
    )
    assert r_create.status_code == 200, r_create.text
    jid = r_create.json()["id"]
    assert not r_create.json().get("technician_name")

    # PATCH tech in via user.id-shape.
    r_patch = requests.put(
        f"{API}/jobs/{jid}",
        headers=admin_headers,
        json={"technician_id": uid},
        timeout=30,
    )
    assert r_patch.status_code == 200, r_patch.text

    # Fetch — assert refreshed denorm on the stored doc.
    async def _fetch():
        return await _db().jobs.find_one({"id": jid}, {"_id": 0})
    stored = _run(_fetch())
    assert stored["technician_id"] == uid
    assert stored["technician_name"] == expected, (
        f"PATCH denorm refresh: expected {expected!r}, "
        f"got {stored.get('technician_name')!r}"
    )


def test_get_job_falls_back_to_cascade_for_historical_null(
    admin_headers, seed_ctx,
):
    """Historical jobs on prod were stamped ``technician_name = null``
    (write path pre-fix). GET /jobs/{jid} must resolve on-the-fly via
    the cascade so those rows render correctly without a backfill."""
    from utils import now_iso, new_id
    uid = seed_ctx["mike"]["user_id"]
    expected = seed_ctx["mike"]["expected_name"]

    # Seed a historical-shape job directly in Mongo — tech_id set,
    # denorm null (matches Ethan Smith's prod job shape).
    jid = f"{_ID_PREFIX}historical-{uuid.uuid4().hex[:6]}"

    async def _seed():
        await _db().jobs.insert_one({
            "id": jid,
            "tenant_id": seed_ctx["tenant_id"],
            "customer_id": seed_ctx["customer_id"],
            "title": f"{_JOB_TITLE_PREFIX}historical_null",
            "service_type": "Weekly Pool Cleaning",
            "job_type": "pool",
            "scheduled_date": "2099-10-17",
            "technician_id": uid,
            "technician_name": None,   # ← historical broken shape
            "technician_avatar": "",
            "status": "scheduled",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    _run(_seed())

    # GET must enrich on the fly.
    r = requests.get(
        f"{API}/jobs/{jid}", headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("technician_id") == uid
    assert body.get("technician_name") == expected, (
        f"historical-null GET: expected {expected!r} via cascade, "
        f"got {body.get('technician_name')!r}"
    )

    # Confirm the enrichment did NOT mutate the stored doc — the
    # spec says response-only enrichment.
    async def _fetch():
        return await _db().jobs.find_one({"id": jid}, {"_id": 0})
    stored = _run(_fetch())
    assert stored.get("technician_name") is None, (
        "get_job enrichment must not mutate the stored doc — "
        "call a dedicated backfill script if persistence is needed"
    )
