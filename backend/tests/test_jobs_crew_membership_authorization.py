"""Feb-2026 · Phase F1 · P0-B regression coverage.

Verifies that a technician who is a MEMBER of the crew assigned to
a job (but not the direct ``technician_id`` on the row) can still
open, read, and act on that job. Prior to Phase F1 every gate in
``routers/jobs.py`` returned 403 "Not your job" because the check
was ``job.technician_id != user.technician_id`` — which drops
crew-only jobs.

The helper ``services.authz.is_tech_authorized_on_job`` is the
single source of truth. These tests pin its behaviour directly.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List

from services.authz import is_tech_authorized_on_job


class _FakeCollection:
    """Motor-compatible collection stub used for the crew lookup.
    Supports the exact query shape ``is_tech_authorized_on_job``
    issues: ``{"id": <crew_id>, "tenant_id": <tid>, "tech_ids": <tech_pk>}``.
    """

    def __init__(self, rows: Iterable[Dict[str, Any]]):
        self._rows = list(rows)

    async def find_one(self, query, projection=None):  # noqa: ARG002
        for row in self._rows:
            if self._matches(row, query):
                return dict(row)
        return None

    @staticmethod
    def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
        for k, v in query.items():
            if k == "tech_ids":
                if v not in (row.get("tech_ids") or []):
                    return False
            elif row.get(k) != v:
                return False
        return True


class _FakeDB:
    def __init__(self, crews):
        self.crews = _FakeCollection(crews)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_direct_assignment_by_user_id_authorized():
    """Legacy seed — ``jobs.technician_id`` holds the user row id."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": "user-a", "tenant_id": "t1"}
    db = _FakeDB(crews=[])
    assert _run(is_tech_authorized_on_job(user, job, db)) is True


def test_direct_assignment_by_tech_id_authorized():
    """Newer seed — ``jobs.technician_id`` holds the technicians id."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": "tech-a", "tenant_id": "t1"}
    db = _FakeDB(crews=[])
    assert _run(is_tech_authorized_on_job(user, job, db)) is True


def test_crew_member_on_crew_only_job_authorized():
    """P0-B — crew-only job with no ``technician_id`` opens for a
    crew member. This is the exact bug Brian Beckman hit."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": None, "crew_id": "crew-1", "tenant_id": "t1"}
    db = _FakeDB(crews=[
        {"id": "crew-1", "tenant_id": "t1", "tech_ids": ["tech-a", "tech-b"]},
    ])
    assert _run(is_tech_authorized_on_job(user, job, db)) is True


def test_crew_member_on_crew_job_assigned_to_teammate_authorized():
    """Job stamped with a teammate's ``technician_id`` but also
    bound to a crew — every crew member still opens it."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": "tech-b", "crew_id": "crew-1", "tenant_id": "t1"}
    db = _FakeDB(crews=[
        {"id": "crew-1", "tenant_id": "t1", "tech_ids": ["tech-a", "tech-b"]},
    ])
    assert _run(is_tech_authorized_on_job(user, job, db)) is True


def test_non_member_not_authorized():
    """Stranger tech (not the assignee AND not in the crew) rejected."""
    user = {"id": "stranger", "technician_id": "tech-x", "role": "technician"}
    job = {"technician_id": "tech-a", "crew_id": "crew-1", "tenant_id": "t1"}
    db = _FakeDB(crews=[
        {"id": "crew-1", "tenant_id": "t1", "tech_ids": ["tech-a", "tech-b"]},
    ])
    assert _run(is_tech_authorized_on_job(user, job, db)) is False


def test_no_crew_no_direct_assignment_rejected():
    """Legacy job with only a stranger's id — no crew — rejected."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": "tech-b", "tenant_id": "t1"}
    db = _FakeDB(crews=[])
    assert _run(is_tech_authorized_on_job(user, job, db)) is False


def test_crew_lookup_tenant_isolated():
    """A tech in a crew of tenant B must NOT authorize on tenant A."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": None, "crew_id": "crew-1", "tenant_id": "t1"}
    # The crew with matching id exists in a DIFFERENT tenant.
    db = _FakeDB(crews=[
        {"id": "crew-1", "tenant_id": "t2", "tech_ids": ["tech-a"]},
    ])
    assert _run(is_tech_authorized_on_job(user, job, db)) is False


def test_missing_tenant_hint_falls_back_to_job_tenant():
    """When the caller omits ``tenant_id`` the helper reads it from
    ``job.tenant_id`` — matches how the routers use it."""
    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": None, "crew_id": "crew-1", "tenant_id": "t1"}
    db = _FakeDB(crews=[
        {"id": "crew-1", "tenant_id": "t1", "tech_ids": ["tech-a"]},
    ])
    assert _run(is_tech_authorized_on_job(user, job, db)) is True


def test_db_failure_returns_false_not_raise():
    """The helper must never propagate a DB exception — a failing
    membership lookup is treated as ``not authorized``."""

    class _BoomCollection:
        async def find_one(self, *_a, **_k):  # noqa: ARG002
            raise RuntimeError("motor exploded")

    class _BoomDB:
        crews = _BoomCollection()

    user = {"id": "user-a", "technician_id": "tech-a", "role": "technician"}
    job = {"technician_id": None, "crew_id": "crew-1", "tenant_id": "t1"}
    assert _run(is_tech_authorized_on_job(user, job, _BoomDB())) is False
