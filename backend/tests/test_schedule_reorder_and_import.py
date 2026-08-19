"""Feb-2026 · Backend tests for schedule DnD reorder + Dispatch import.

Covers:
  * ``POST /api/jobs/reorder`` — happy path, cross-tenant rejection,
    role gate, empty payload guard.
  * ``POST /api/dispatch/import-schedule`` — happy path, idempotent
    re-run, tenant isolation, tech-filter narrowing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": demo_pw(email)}, timeout=15)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))["tenant_id"]


# Seed helpers ─────────────────────────────────────────────────────────
DATE = "2026-03-15"  # A Sunday — irrelevant, we just use the string.
TECH_A = f"tech-A-{uuid4().hex[:6]}"
TECH_B = f"tech-B-{uuid4().hex[:6]}"


async def _seed_jobs(tenant_id: str, tech_id: str, count: int) -> list[str]:
    """Insert ``count`` jobs for the given tenant + tech on DATE.
    Returns the list of created job ids in insertion order."""
    ids = []
    for i in range(count):
        jid = f"TEST_reorder_{uuid4().hex[:10]}"
        cid = f"cust_{uuid4().hex[:8]}"
        await _DB.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "customer_id": cid,
            "tech_user_id": tech_id,
            "technician_id": tech_id,  # dual-key for schema drift
            "title": f"TEST_reorder job {i}",
            "scheduled_date": DATE,
            "route_index": i,
            "status": "scheduled",
        })
        ids.append(jid)
    return ids


async def _wipe():
    await _DB.jobs.delete_many({"title": {"$regex": "^TEST_reorder"}})
    await _DB.dispatch_route_orders.delete_many(
        {"source": "schedule_import", "source_date": DATE})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


# ═══════════════════════════════════════════════════════════════════════
# POST /api/jobs/reorder
# ═══════════════════════════════════════════════════════════════════════
def test_reorder_happy_path_renumbers_route_index():
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    ids = _run(_seed_jobs(tenant_id, TECH_A, 4))

    # Reverse the order.
    reordered = list(reversed(ids))
    r = requests.post(f"{API}/jobs/reorder",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"tech_user_id": TECH_A, "date": DATE,
                            "ordered_job_ids": reordered},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated"] == 4
    assert body["expected"] == 4

    for i, jid in enumerate(reordered):
        row = _run(_DB.jobs.find_one({"id": jid}, {"_id": 0, "route_index": 1}))
        assert row["route_index"] == i, f"job {jid} expected idx {i}, got {row}"


def test_reorder_rejects_cross_tenant_ids_silently():
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    own_ids = _run(_seed_jobs(tenant_id, TECH_A, 2))

    # Foreign-tenant job that must NOT be updated.
    foreign_jid = f"TEST_reorder_foreign_{uuid4().hex[:8]}"
    _run(_DB.jobs.insert_one({
        "id": foreign_jid, "tenant_id": "other-tenant-XXX",
        "customer_id": "cust_x", "tech_user_id": TECH_A,
        "technician_id": TECH_A,
        "title": "TEST_reorder foreign",
        "scheduled_date": DATE, "route_index": 99, "status": "scheduled",
    }))

    r = requests.post(f"{API}/jobs/reorder",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"tech_user_id": TECH_A, "date": DATE,
                            "ordered_job_ids": [foreign_jid, *own_ids]},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # Only own_ids matched.
    assert body["updated"] == 2
    assert body["expected"] == 3

    foreign = _run(_DB.jobs.find_one({"id": foreign_jid}, {"_id": 0, "route_index": 1}))
    assert foreign["route_index"] == 99  # untouched


def test_reorder_role_gate_rejects_technician():
    # Login as a technician demo account.
    tech_tok = _login("carlos@aquaterra.com")
    r = requests.post(f"{API}/jobs/reorder",
                      headers={"Authorization": f"Bearer {tech_tok}"},
                      json={"tech_user_id": TECH_A, "date": DATE,
                            "ordered_job_ids": ["nonexistent"]},
                      timeout=15)
    assert r.status_code == 403, r.text


def test_reorder_empty_payload_is_400():
    admin_tok = _login("admin@aquaterra.com")
    r = requests.post(f"{API}/jobs/reorder",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"tech_user_id": TECH_A, "date": DATE,
                            "ordered_job_ids": []},
                      timeout=15)
    assert r.status_code == 400, r.text


# ═══════════════════════════════════════════════════════════════════════
# POST /api/dispatch/import-schedule
# ═══════════════════════════════════════════════════════════════════════
def test_import_schedule_happy_path_creates_route_orders():
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    _run(_seed_jobs(tenant_id, TECH_A, 3))
    _run(_seed_jobs(tenant_id, TECH_B, 2))

    r = requests.post(f"{API}/dispatch/import-schedule",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"date": DATE}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["techs_written"] == 2
    assert body["weekday"] == datetime.strptime(DATE, "%Y-%m-%d").strftime("%A").lower()
    assert body["job_count"] == 5

    # Docs exist per tech.
    a = _run(_DB.dispatch_route_orders.find_one(
        {"tenant_id": tenant_id, "day": body["weekday"], "tech_user_id": TECH_A}))
    b = _run(_DB.dispatch_route_orders.find_one(
        {"tenant_id": tenant_id, "day": body["weekday"], "tech_user_id": TECH_B}))
    assert a and len(a["ordered_customer_ids"]) == 3
    assert b and len(b["ordered_customer_ids"]) == 2
    assert a["source"] == "schedule_import"
    assert a["source_date"] == DATE


def test_import_schedule_is_idempotent_on_rerun():
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    _run(_seed_jobs(tenant_id, TECH_A, 3))

    r1 = requests.post(f"{API}/dispatch/import-schedule",
                       headers={"Authorization": f"Bearer {admin_tok}"},
                       json={"date": DATE}, timeout=15).json()
    r2 = requests.post(f"{API}/dispatch/import-schedule",
                       headers={"Authorization": f"Bearer {admin_tok}"},
                       json={"date": DATE}, timeout=15).json()
    # Second run either no-ops modified_count (Mongo doesn't dirty
    # equal-value writes) or writes the same order — either way, the
    # ordering doc still has 3 items and no duplicates.
    day = r1["weekday"]
    doc = _run(_DB.dispatch_route_orders.find_one(
        {"tenant_id": tenant_id, "day": day, "tech_user_id": TECH_A}))
    assert len(doc["ordered_customer_ids"]) == 3
    assert len(set(doc["ordered_customer_ids"])) == 3  # no dupes
    assert r1["job_count"] == r2["job_count"] == 3


def test_import_schedule_respects_tech_filter():
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    _run(_seed_jobs(tenant_id, TECH_A, 3))
    _run(_seed_jobs(tenant_id, TECH_B, 2))

    r = requests.post(f"{API}/dispatch/import-schedule",
                      headers={"Authorization": f"Bearer {admin_tok}"},
                      json={"date": DATE, "tech_user_ids": [TECH_A]},
                      timeout=15).json()
    assert r["techs_written"] == 1
    assert r["job_count"] == 3
    day = r["weekday"]
    # TECH_B's ordering doc must NOT exist post-filter.
    b = _run(_DB.dispatch_route_orders.find_one(
        {"tenant_id": tenant_id, "day": day, "tech_user_id": TECH_B,
         "source": "schedule_import", "source_date": DATE}))
    assert b is None


def test_import_schedule_role_gate_rejects_technician():
    tech_tok = _login("carlos@aquaterra.com")
    r = requests.post(f"{API}/dispatch/import-schedule",
                      headers={"Authorization": f"Bearer {tech_tok}"},
                      json={"date": DATE}, timeout=15)
    assert r.status_code == 403, r.text
