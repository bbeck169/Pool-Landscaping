"""D2-hotfix (2026-02) · Schedule reorder read-path regression.

**User report**: "the schedule reorder is not saving in the order I
changed it to in admin screen or for tech".

**Root cause**: ``GET /api/jobs`` sorted by
``[("scheduled_date", 1), ("route_index", 1), ("created_at", 1)]``.
Because most jobs persist ``scheduled_date`` as a full ISO datetime
(``2026-08-22T11:00:00+00:00``), the string comparison on
``scheduled_date`` was decided by the TIME portion before
``route_index`` ever got a look-in — so the admin's reorder writes to
``route_index`` succeeded in Mongo (POST /jobs/reorder returned
``updated == expected``) but the follow-up refresh via
``/api/jobs?start&end`` re-ordered them back into time order,
appearing to "revert" the reorder in the UI.

**Fix**: switch the read path from ``find().sort()`` to an aggregation
that first extracts the ``YYYY-MM-DD`` day prefix, then sorts by
``(day, route_index, scheduled_date, created_at)``. Multi-day
ordering is preserved by day; ``route_index`` is authoritative
within a day; time+created_at remain the tie-breakers on
un-reordered days.

This regression test seeds two jobs on the same day for the same
tech with distinct ISO-datetime ``scheduled_date`` values (9am, 11am),
POSTs a reversed ``ordered_job_ids``, and asserts the very next
``GET /api/jobs?start&end`` returns them in the persisted
``route_index`` order — NOT the time order.
"""
from __future__ import annotations

import asyncio
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
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": demo_pw(email)},
        timeout=15,
    )
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    doc = _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))
    return doc["tenant_id"]


DATE = "2026-03-15"
TECH_ID = f"tech-readpath-{uuid4().hex[:6]}"


async def _seed_two_jobs_iso_datetime(tenant_id: str) -> tuple[str, str]:
    """Insert two jobs on the same day for the same tech, but with
    DIFFERENT ISO-datetime ``scheduled_date`` values (9am + 11am).
    Returns ``(job_id_9am, job_id_11am)``.

    This mirrors what production writes look like — the mix of
    time-of-day inside ``scheduled_date`` is precisely what made the
    old find().sort() dominate ``route_index`` in the read path.
    """
    j_early = f"TEST_readpath_{uuid4().hex[:10]}"
    j_late  = f"TEST_readpath_{uuid4().hex[:10]}"
    await _DB.jobs.insert_one({
        "id": j_early, "tenant_id": tenant_id,
        "customer_id": f"cust_{uuid4().hex[:8]}",
        "tech_user_id": TECH_ID, "technician_id": TECH_ID,
        "title": "TEST_readpath 9am job",
        "scheduled_date": f"{DATE}T09:00:00+00:00",
        "status": "scheduled",
    })
    await _DB.jobs.insert_one({
        "id": j_late, "tenant_id": tenant_id,
        "customer_id": f"cust_{uuid4().hex[:8]}",
        "tech_user_id": TECH_ID, "technician_id": TECH_ID,
        "title": "TEST_readpath 11am job",
        "scheduled_date": f"{DATE}T11:00:00+00:00",
        "status": "scheduled",
    })
    return j_early, j_late


async def _wipe():
    await _DB.jobs.delete_many({"title": {"$regex": "^TEST_readpath"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


def _fetch_targets(tok: str, targets: set[str]) -> list[dict]:
    """Call ``/api/jobs`` with a wide window that mirrors what the web
    ``CalendarSchedule`` actually sends (``focus - 60d`` to
    ``focus + 90d``), then filter the response down to just our two
    seeded ids while preserving their returned order.

    Note: ``/api/jobs`` uses a string ``$gte/$lte`` range on
    ``scheduled_date``. Because most jobs persist that field as a full
    ISO datetime (``2026-03-15T09:00:00+00:00``), a single-day filter
    ``start=end=DATE`` excludes ISO-datetime rows (``"...T09:00"`` >
    ``"2026-03-15"``). We deliberately use a wide window here to match
    real production usage — the single-day $lte edge case is a
    separate pre-existing bug (not this hotfix's scope).
    """
    r = requests.get(
        f"{API}/jobs?start=2026-01-01&end=2026-12-31",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else (
        r.json().get("items") or r.json().get("jobs") or []
    )
    return [j for j in items if j.get("id") in targets]


def test_reorder_read_path_honors_route_index_over_scheduled_time():
    """The core D2 regression: after a reorder that REVERSES time order,
    ``GET /api/jobs?start&end`` must return jobs in ``route_index``
    order — not in ``scheduled_date`` (time) order.
    """
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    j9, j11 = _run(_seed_two_jobs_iso_datetime(tenant_id))

    # ── Baseline: no route_index set anywhere — the read path must
    # fall back to time order (9am before 11am) so we don't regress
    # the untouched-day behavior.
    baseline = _fetch_targets(admin_tok, {j9, j11})
    assert [j["id"] for j in baseline] == [j9, j11], (
        f"baseline (no route_index) should sort by time; got {baseline}"
    )

    # ── Force route_index to REVERSE the natural time order:
    # 11am job → position 0, 9am job → position 1.
    reordered = [j11, j9]
    r = requests.post(
        f"{API}/jobs/reorder",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"tech_user_id": TECH_ID, "date": DATE, "ordered_job_ids": reordered},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("updated") == 2

    # ── The critical assertion: /api/jobs must now return
    # [11am job, 9am job] — i.e. route_index (0,1) wins, NOT time.
    after = _fetch_targets(admin_tok, {j9, j11})
    assert [j["id"] for j in after] == [j11, j9], (
        f"after reorder /api/jobs must honor route_index; got "
        f"{[(j['id'], j.get('route_index'), j.get('scheduled_date')) for j in after]}"
    )
    # And route_index must be exposed on the response so mobile clients
    # can trust the server-side sort without a second GET.
    assert after[0]["route_index"] == 0
    assert after[1]["route_index"] == 1


def test_reorder_read_path_flip_persists_and_reverses():
    """Second flip should re-reverse — proving the read path always
    reflects the LATEST route_index, not just the first write."""
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    j9, j11 = _run(_seed_two_jobs_iso_datetime(tenant_id))

    def _reorder(order: list[str]) -> None:
        r = requests.post(
            f"{API}/jobs/reorder",
            headers={"Authorization": f"Bearer {admin_tok}"},
            json={"tech_user_id": TECH_ID, "date": DATE, "ordered_job_ids": order},
            timeout=15,
        )
        assert r.status_code == 200, r.text

    _reorder([j11, j9])
    assert [j["id"] for j in _fetch_targets(admin_tok, {j9, j11})] == [j11, j9]

    _reorder([j9, j11])
    assert [j["id"] for j in _fetch_targets(admin_tok, {j9, j11})] == [j9, j11]


def test_reorder_read_path_untouched_days_still_sort_by_time():
    """A day that has never been reordered (all route_index == None)
    must still fall back to time order — proves the fix didn't
    regress the untouched-day behavior for the rest of the calendar.
    """
    admin_tok = _login("admin@aquaterra.com")
    tenant_id = _tenant_of("admin@aquaterra.com")
    j9, j11 = _run(_seed_two_jobs_iso_datetime(tenant_id))
    # No reorder call — both jobs stay at route_index == None.
    items = _fetch_targets(admin_tok, {j9, j11})
    assert [j["id"] for j in items] == [j9, j11], (
        f"untouched day should sort by time; got {items}"
    )
    assert all(j.get("route_index") is None for j in items)
