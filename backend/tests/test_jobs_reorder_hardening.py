"""Feb-2026 · numbered-order schedule reorder — hardening tests.

Companion to ``test_schedule_reorder_and_import.py``.  The pre-existing
suite covers the happy path + role gate + weekday derivation.  These
tests lock in the new defense-in-depth rules the schedule UI relies
on:

  1. Duplicate ids in the payload → 422.
  2. Payload missing one of the day's non-terminal jobs → 422.
  3. Payload includes a job from a different day → 422.
  4. Terminal-status jobs on the day are excluded from the required
     "complete set" so an admin can still reorder around a completed
     job without accidentally re-opening its terminal state.
  5. Successful reorder upserts ``dispatch_route_orders`` — the
     Dispatch Board's data contract stays in sync with the schedule.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_env = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
API = _env.get("BACKEND_INTERNAL_URL", "http://localhost:8001") + "/api"
MONGO_URL = _env["MONGO_URL"]
DB_NAME = _env["DB_NAME"]

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_client = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _client[DB_NAME]

# Aligns with the pre-existing suite's seed fixture.
TECH_A = "tech_a_valid_reorder_test"
DATE = "2026-03-15"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=10)
    r.raise_for_status()
    body = r.json()
    return body.get("token") or body.get("access_token")


def _tenant_of(email: str) -> str:
    doc = _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))
    return doc["tenant_id"]


async def _seed_jobs(tenant_id: str, tech_id: str, count: int,
                       date: str = DATE, status: str = "scheduled") -> list[str]:
    ids: list[str] = []
    for i in range(count):
        jid = f"TEST_reorder_hardening_{uuid4().hex[:8]}_{i}"
        await _DB.jobs.insert_one({
            "id": jid, "tenant_id": tenant_id,
            "customer_id": f"cust_{jid}",
            "tech_user_id": tech_id, "technician_id": tech_id,
            "title": f"TEST_reorder_hardening {i}",
            "scheduled_date": date, "route_index": i,
            "status": status,
        })
        ids.append(jid)
    return ids


def _cleanup_by_prefix(prefix: str = "TEST_reorder_hardening_") -> None:
    _run(_DB.jobs.delete_many({"id": {"$regex": f"^{prefix}"}}))


# ─────────────────────────────────────────────────────────────────

def test_reorder_rejects_duplicate_ids_in_payload():
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    ids = _run(_seed_jobs(tenant_id, TECH_A, 3))
    try:
        # Include ids[0] twice → 422 duplicate guard.
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": [ids[0], ids[0], ids[1]]},
                          timeout=15)
        assert r.status_code == 422, r.text
        assert "duplicate" in r.text.lower()
    finally:
        _cleanup_by_prefix()


def test_reorder_rejects_incomplete_set_missing_a_day_job():
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    ids = _run(_seed_jobs(tenant_id, TECH_A, 3))
    try:
        # Send only 2 of the 3 non-terminal jobs → 422 completeness.
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": ids[:2]},
                          timeout=15)
        assert r.status_code == 422, r.text
        assert "missing" in r.text.lower() or "set" in r.text.lower()
    finally:
        _cleanup_by_prefix()


def test_reorder_rejects_id_from_different_day():
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    todays = _run(_seed_jobs(tenant_id, TECH_A, 2, date=DATE))
    othersday = _run(_seed_jobs(tenant_id, TECH_A, 1, date="2026-04-01"))
    try:
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": [*todays, othersday[0]]},
                          timeout=15)
        assert r.status_code == 422, r.text
        assert "not on this tech" in r.text.lower() or "set" in r.text.lower()
    finally:
        _cleanup_by_prefix()


def test_reorder_ignores_terminal_status_jobs_when_computing_day_set():
    """A completed job on the day is NOT part of the required set —
    admins can still renumber the remaining live jobs without having
    to include a closed row in the payload."""
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    open_ids = _run(_seed_jobs(tenant_id, TECH_A, 2, status="scheduled"))
    closed_ids = _run(_seed_jobs(tenant_id, TECH_A, 1, status="completed"))
    try:
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": list(reversed(open_ids))},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 2

        # The completed row's route_index must not have been touched
        # (it wasn't in the payload).
        closed = _run(_DB.jobs.find_one(
            {"id": closed_ids[0]}, {"_id": 0, "route_index": 1}))
        assert closed["route_index"] == 0  # seeded value preserved
    finally:
        _cleanup_by_prefix()


def test_reorder_upserts_dispatch_route_orders():
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    ids = _run(_seed_jobs(tenant_id, TECH_A, 3))
    try:
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": list(reversed(ids))},
                          timeout=15)
        assert r.status_code == 200, r.text

        row = _run(_DB.dispatch_route_orders.find_one({
            "tenant_id": tenant_id,
            "tech_user_id": TECH_A,
            "day": "sunday",  # 2026-03-15 is a Sunday
        }, {"_id": 0}))
        assert row is not None
        # ordered_customer_ids reflects reversed job order.
        assert row["ordered_customer_ids"] == [f"cust_{jid}" for jid in reversed(ids)]
        assert row["source"] == "schedule_reorder"
    finally:
        _cleanup_by_prefix()


def test_reorder_read_path_returns_jobs_in_saved_order():
    """Empirical round-trip: after ``POST /jobs/reorder``, the
    subsequent ``GET /jobs`` must return the same tech-day's jobs in
    the exact order we saved.  This is the guard that pinned the
    Feb-2026 read-path bug — the sort was ``scheduled_date`` only,
    so same-day jobs came back in natural collection (insertion)
    order regardless of ``route_index``.  With the triple-key sort
    ``(scheduled_date, route_index, created_at)`` this must pass.
    """
    _cleanup_by_prefix()
    tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    ids = _run(_seed_jobs(tenant_id, TECH_A, 3))
    try:
        # Reverse the natural order so mistakenly sorting by
        # insertion / created_at would produce a wrong result.
        target = list(reversed(ids))
        r = requests.post(f"{API}/jobs/reorder",
                          headers={"Authorization": f"Bearer {tok}"},
                          json={"tech_user_id": TECH_A, "date": DATE,
                                "ordered_job_ids": target},
                          timeout=15)
        assert r.status_code == 200, r.text

        # Refetch — filter to just the seeded tech-day rows.
        list_r = requests.get(
            f"{API}/jobs?limit=500",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert list_r.status_code == 200, list_r.text
        rows = list_r.json()
        rows = rows if isinstance(rows, list) else (
            rows.get("jobs") or rows.get("items") or []
        )
        seen = [j["id"] for j in rows if j["id"] in set(target)]
        assert seen == target, (
            f"read-path returned wrong order\n"
            f"  expected: {target}\n"
            f"  got:      {seen}\n"
            f"  full row route_indices: "
            f"{[(j['id'][-4:], j.get('route_index')) for j in rows if j['id'] in set(target)]}"
        )
    finally:
        _cleanup_by_prefix()
