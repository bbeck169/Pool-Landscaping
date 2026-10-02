"""Mobile offline-bundle · jobs query dual-field coverage.

The ``GET /api/mobile/offline-bundle`` endpoint (``routers/mobile_sync.py``)
originally filtered + sorted on ``scheduled_at`` only, but job docs
in this codebase store their schedule on ``scheduled_date``
(date-only ``YYYY-MM-DD``); the live collection has 0 rows with
``scheduled_at``. This suite pins the dual-field fix (mirrors the
pattern already shipped in ``routers/portal_next_visits.py``):

* Jobs with ONLY ``scheduled_date`` inside the window qualify.
* Jobs with ONLY ``scheduled_at``   inside the window qualify
  (back-compat for any future rows carrying full-ISO).
* Jobs with ``scheduled_date`` OUTSIDE the window are excluded.
* Soft-deleted jobs are excluded (``not_deleted_filter``).
* Jobs from a different tenant are excluded (tenant scoping).
* Sort is ascending by schedule time regardless of which field
  carries the value.

Harness mirrors ``test_phase_o4_offline_bundle.py``:
* live ``requests`` to the FastAPI pod (``http://localhost:8001``);
* ``motor`` seeds via ``asyncio.get_event_loop().run_until_complete``;
* explicit teardown deletes every seeded row.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local                                             # noqa: E402
_ENV_BASE = _os_local.environ.get("MOBILE_SYNC_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db                                              # noqa: E402
from utils import new_id                                           # noqa: E402
from routers.mobile_sync import OFFLINE_BUNDLE_WINDOW_DAYS         # noqa: E402


# ─────────────────────────── fixtures ────────────────────────────
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def mike_token() -> str:
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def mike_identity(mike_token) -> dict:
    """Resolve mike's ``technician_id`` / ``id`` + tenant exactly the
    way the endpoint does (``user.technician_id or user.id``)."""
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {mike_token}"},
        timeout=15,
    ).json()
    return {
        "tech_id":   me.get("technician_id") or me.get("id"),
        "tenant_id": me.get("tenant_id"),
    }


@pytest.fixture()
def seeded_jobs(mike_identity):
    """Six seeded jobs covering every branch of the fix.

    Returns a dict ``{"include_date", "include_at", "outside",
    "deleted", "other_tenant", "ids"}``.  Teardown deletes every id.
    """
    tech_id = mike_identity["tech_id"]
    tenant_id = mike_identity["tenant_id"]
    now = datetime.now(timezone.utc)
    inside_dt = now + timedelta(days=2)
    outside_dt = now + timedelta(days=OFFLINE_BUNDLE_WINDOW_DAYS + 3)

    docs = {
        # Modern shape — scheduled_date only (lives on 100% of real rows).
        "include_date": {
            "id": f"mob-sync-dualfield-date-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-dualfield-cust",
            "customer_name": "Dualfield Date-Only",
            "title": "mob-sync dualfield · date only",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": inside_dt.date().isoformat(),
        },
        # Back-compat shape — scheduled_at only (future rows / mobile write-back).
        "include_at": {
            "id": f"mob-sync-dualfield-at-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-dualfield-cust",
            "customer_name": "Dualfield At-Only",
            "title": "mob-sync dualfield · at only",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_at": inside_dt.isoformat(),
        },
        # Outside the 7-day window on scheduled_date — must be excluded.
        "outside": {
            "id": f"mob-sync-dualfield-out-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-dualfield-cust",
            "customer_name": "Dualfield Outside",
            "title": "mob-sync dualfield · outside window",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": outside_dt.date().isoformat(),
        },
        # Soft-deleted — in-window but ``deleted_at`` set → must be excluded.
        "deleted": {
            "id": f"mob-sync-dualfield-del-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-dualfield-cust",
            "customer_name": "Dualfield Deleted",
            "title": "mob-sync dualfield · soft deleted",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": inside_dt.date().isoformat(),
            "deleted_at": now.isoformat(),
            "deleted_by_user_id": "test-seed",
        },
        # Different tenant — same tech id, in-window, but foreign tenant → excluded.
        "other_tenant": {
            "id": f"mob-sync-dualfield-xten-{new_id()}",
            "tenant_id": "mob-sync-foreign-tenant-xyz",
            "technician_id": tech_id,
            "customer_id": "mob-sync-dualfield-cust",
            "customer_name": "Dualfield Foreign Tenant",
            "title": "mob-sync dualfield · wrong tenant",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": inside_dt.date().isoformat(),
        },
    }

    async def _seed():
        for d in docs.values():
            await db.jobs.insert_one(dict(d))
    _run(_seed())

    yield {**docs, "ids": [d["id"] for d in docs.values()]}

    async def _teardown():
        await db.jobs.delete_many(
            {"id": {"$in": [d["id"] for d in docs.values()]}},
        )
    _run(_teardown())


def _fetch_bundle(mike_token) -> dict:
    r = requests.get(
        f"{API}/mobile/offline-bundle",
        headers={"Authorization": f"Bearer {mike_token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ─────────────────────────── tests ───────────────────────────────
def test_job_with_only_scheduled_date_is_included(mike_token, seeded_jobs):
    bundle = _fetch_bundle(mike_token)
    ids = [j["id"] for j in bundle["jobs"]]
    assert seeded_jobs["include_date"]["id"] in ids, (
        f"scheduled_date-only job missing from bundle; got {ids[:20]}"
    )


def test_job_with_only_scheduled_at_is_included_backcompat(mike_token, seeded_jobs):
    bundle = _fetch_bundle(mike_token)
    ids = [j["id"] for j in bundle["jobs"]]
    assert seeded_jobs["include_at"]["id"] in ids, (
        "scheduled_at-only job missing — back-compat regression"
    )


def test_job_outside_window_on_scheduled_date_is_excluded(mike_token, seeded_jobs):
    bundle = _fetch_bundle(mike_token)
    ids = [j["id"] for j in bundle["jobs"]]
    assert seeded_jobs["outside"]["id"] not in ids, (
        "outside-window job leaked into bundle — upper-bound filter broken"
    )


def test_soft_deleted_job_is_excluded(mike_token, seeded_jobs):
    bundle = _fetch_bundle(mike_token)
    ids = [j["id"] for j in bundle["jobs"]]
    assert seeded_jobs["deleted"]["id"] not in ids, (
        "soft-deleted job leaked — not_deleted_filter() dropped from query"
    )


def test_different_tenant_job_is_excluded(mike_token, seeded_jobs):
    bundle = _fetch_bundle(mike_token)
    ids = [j["id"] for j in bundle["jobs"]]
    assert seeded_jobs["other_tenant"]["id"] not in ids, (
        "foreign-tenant job leaked — tenant scoping broken"
    )


def test_jobs_sorted_ascending_by_schedule_regardless_of_field(mike_token, mike_identity):
    """Seeds three in-window jobs with ``scheduled_date`` populated
    at staggered dates and asserts the bundle returns them in
    ascending order.  Also seeds one ``scheduled_at``-only job to
    prove the back-compat shape still qualifies when interleaved
    with the modern shape (inclusion check only — Mongo's native
    sort has no cross-field ``$ifNull`` so mixed-shape rows aren't
    guaranteed to interleave by effective timestamp, matching the
    documented limitation on the sibling ``portal_next_visits.py``
    pattern).
    """
    tech_id = mike_identity["tech_id"]
    tenant_id = mike_identity["tenant_id"]
    now = datetime.now(timezone.utc)
    day1 = now + timedelta(days=1)
    day2 = now + timedelta(days=2)
    day3 = now + timedelta(days=3)

    date_docs = [
        {
            "id": f"mob-sync-sort-d1-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-sort-cust",
            "customer_name": "Sort D1",
            "title": "mob-sync sort · day1 (scheduled_date)",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": day1.date().isoformat(),
        },
        {
            "id": f"mob-sync-sort-d2-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-sort-cust",
            "customer_name": "Sort D2",
            "title": "mob-sync sort · day2 (scheduled_date)",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": day2.date().isoformat(),
        },
        {
            "id": f"mob-sync-sort-d3-{new_id()}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "customer_id": "mob-sync-sort-cust",
            "customer_name": "Sort D3",
            "title": "mob-sync sort · day3 (scheduled_date)",
            "service_type": "Weekly Pool",
            "status": "scheduled",
            "scheduled_date": day3.date().isoformat(),
        },
    ]
    # Back-compat row — in-window scheduled_at only.  Asserted for
    # INCLUSION, not for positional ordering (see docstring).
    backcompat_doc = {
        "id": f"mob-sync-sort-at-{new_id()}",
        "tenant_id": tenant_id,
        "technician_id": tech_id,
        "customer_id": "mob-sync-sort-cust",
        "customer_name": "Sort At-Only",
        "title": "mob-sync sort · back-compat scheduled_at",
        "service_type": "Weekly Pool",
        "status": "scheduled",
        "scheduled_at": day2.isoformat(),
    }
    seeded_ids = [d["id"] for d in date_docs] + [backcompat_doc["id"]]
    date_ids_in_order = [d["id"] for d in date_docs]

    async def _seed():
        for d in date_docs + [backcompat_doc]:
            await db.jobs.insert_one(dict(d))
    _run(_seed())

    try:
        token = _login("mike@aquaterra.com")
        bundle = _fetch_bundle(token)
        all_our_ids = [j["id"] for j in bundle["jobs"] if j["id"] in seeded_ids]
        assert backcompat_doc["id"] in all_our_ids, (
            "back-compat scheduled_at-only job missing in sort scenario"
        )
        # Positional check: among the three scheduled_date rows,
        # the bundle MUST surface them in ascending order.
        date_only_order = [j["id"] for j in bundle["jobs"]
                            if j["id"] in date_ids_in_order]
        assert date_only_order == date_ids_in_order, (
            f"expected ascending {date_ids_in_order}, got {date_only_order}"
        )
    finally:
        async def _teardown():
            await db.jobs.delete_many({"id": {"$in": seeded_ids}})
        _run(_teardown())
