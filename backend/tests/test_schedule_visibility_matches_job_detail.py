"""Feb-2026 · Phase F1 · P0-B parity coverage — schedule ↔ job detail.

Contract: any job that the schedule list (``scope_jobs_query``)
surfaces for a technician MUST also open under the job-detail
gate (``is_tech_authorized_on_job``). The reverse holds too — a
tech who cannot see a job in their schedule must be rejected by
the detail endpoint.

The bug this test guards against (P0-B, Feb 2026): schedule
included crew-only jobs but the JobDetail endpoint's inline
``technician_id != user.technician_id`` gate 403'd every one of
them, breaking the tap-through UX for crew techs.

We exercise both ``scope_jobs_query`` (schedule scoping) and
``is_tech_authorized_on_job`` (detail gate) against the same
job/user fixtures and assert their decisions align.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from services.authz import is_tech_authorized_on_job


# ───────────────────────────────────────────────────────────────────
# Test fakes: Motor-compatible in-memory Mongo stubs.
# ───────────────────────────────────────────────────────────────────
class _Coll:
    def __init__(self, rows):
        self.rows: List[Dict[str, Any]] = list(rows)

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self.rows:
            if _matches(row, query):
                return dict(row)
        return None

    def find(self, query=None, projection=None):  # noqa: ARG002
        outer = self
        q = query or {}

        class _Cursor:
            def __init__(self):
                self._rows = [
                    dict(r) for r in outer.rows if _matches(r, q)
                ]

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration

            async def to_list(self, _n):
                return list(self._rows)

        return _Cursor()


class _DB:
    def __init__(self, jobs, crews):
        self.jobs = _Coll(jobs)
        self.crews = _Coll(crews)


def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_matches(row, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict) and "$in" in v:
            if row.get(k) not in v["$in"]:
                return False
            continue
        if isinstance(v, dict):
            # Unsupported operator — treat as no-match to be safe.
            return False
        if k == "tech_ids":
            if v not in (row.get("tech_ids") or []):
                return False
            continue
        if row.get(k) != v:
            return False
    return True


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _scoped_ids(user, tenant, db_fake):
    """Call ``scope_jobs_query`` with the router's ``db`` symbol
    patched to our fake, then evaluate the returned query against
    the fake jobs collection to get the visible job ids."""
    import routers.jobs as jobs_mod

    original = jobs_mod.db
    jobs_mod.db = db_fake  # type: ignore[assignment]
    try:
        q = await jobs_mod.scope_jobs_query(user, tenant, None, None)
    finally:
        jobs_mod.db = original  # type: ignore[assignment]

    return [j["id"] for j in db_fake.jobs.rows if _matches(j, q)]


# ───────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────
def test_direct_assigned_job_visible_in_both_surfaces():
    """Baseline: a job stamped with the tech's ``technician_id``
    appears on the schedule AND opens under the detail gate."""
    user = {"id": "u1", "role": "technician", "technician_id": "tech-a"}
    tenant = {"id": "t1"}
    job = {"id": "job-1", "tenant_id": "t1", "technician_id": "tech-a"}
    db_fake = _DB(jobs=[job], crews=[])

    visible = _run(_scoped_ids(user, tenant, db_fake))
    assert "job-1" in visible

    assert _run(is_tech_authorized_on_job(user, job, db_fake, "t1")) is True


def test_crew_only_job_visible_in_both_surfaces():
    """P0-B: a crew-only job (no direct ``technician_id``) that
    the tech's crew owns must appear in schedule AND open under
    the detail gate — the whole point of Phase F1."""
    user = {"id": "u1", "role": "technician", "technician_id": "tech-a"}
    tenant = {"id": "t1"}
    crew = {"id": "crew-1", "tenant_id": "t1",
            "tech_ids": ["tech-a", "tech-b"]}
    job = {"id": "job-crew", "tenant_id": "t1",
           "technician_id": None, "crew_id": "crew-1"}
    db_fake = _DB(jobs=[job], crews=[crew])

    visible = _run(_scoped_ids(user, tenant, db_fake))
    assert "job-crew" in visible, (
        "schedule dropped a crew-only job — scope_jobs_query regression"
    )

    assert _run(is_tech_authorized_on_job(user, job, db_fake, "t1")) is True, (
        "detail gate rejected a crew-only job — P0-B regression"
    )


def test_teammate_assigned_crew_job_visible_in_both_surfaces():
    """A job stamped with teammate ``tech-b`` but bound to a crew
    the caller (``tech-a``) belongs to — both surfaces must accept."""
    user = {"id": "u1", "role": "technician", "technician_id": "tech-a"}
    tenant = {"id": "t1"}
    crew = {"id": "crew-1", "tenant_id": "t1",
            "tech_ids": ["tech-a", "tech-b"]}
    job = {"id": "job-mate", "tenant_id": "t1",
           "technician_id": "tech-b", "crew_id": "crew-1"}
    db_fake = _DB(jobs=[job], crews=[crew])

    visible = _run(_scoped_ids(user, tenant, db_fake))
    assert "job-mate" in visible

    assert _run(is_tech_authorized_on_job(user, job, db_fake, "t1")) is True


def test_stranger_job_hidden_in_both_surfaces():
    """A job stamped with a stranger's id and no crew — hidden
    from schedule AND rejected by the detail gate. Symmetric."""
    user = {"id": "u1", "role": "technician", "technician_id": "tech-a"}
    tenant = {"id": "t1"}
    job = {"id": "job-stranger", "tenant_id": "t1",
           "technician_id": "tech-z"}
    db_fake = _DB(jobs=[job], crews=[])

    visible = _run(_scoped_ids(user, tenant, db_fake))
    assert "job-stranger" not in visible

    assert _run(is_tech_authorized_on_job(user, job, db_fake, "t1")) is False


def test_other_crew_only_job_hidden_in_both_surfaces():
    """A crew-only job that belongs to a DIFFERENT crew is hidden
    from schedule and rejected by the detail gate."""
    user = {"id": "u1", "role": "technician", "technician_id": "tech-a"}
    tenant = {"id": "t1"}
    # tech-a is in crew-1, but the job belongs to crew-2.
    crews = [
        {"id": "crew-1", "tenant_id": "t1", "tech_ids": ["tech-a"]},
        {"id": "crew-2", "tenant_id": "t1", "tech_ids": ["tech-z"]},
    ]
    job = {"id": "job-other-crew", "tenant_id": "t1",
           "technician_id": None, "crew_id": "crew-2"}
    db_fake = _DB(jobs=[job], crews=crews)

    visible = _run(_scoped_ids(user, tenant, db_fake))
    assert "job-other-crew" not in visible

    assert _run(is_tech_authorized_on_job(user, job, db_fake, "t1")) is False
