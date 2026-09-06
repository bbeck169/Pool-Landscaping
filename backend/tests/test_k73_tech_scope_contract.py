"""Phase K73 · Feb-2026 — permanent contract tests locking in
the tech-scope behavior of the read endpoints that expose job /
schedule PII.

These tests are the shipped guardrail for the K73 audit. They
must remain green forever — if a future refactor lets a
technician token see another tech's job through any of the
audited endpoints, this suite MUST hard-fail.

Endpoint coverage (aligned with the R1.c/K73 audit report):

* ``GET /api/jobs``                            — list scope
* ``GET /api/jobs?technician_id=<other>``      — override attempt
* ``GET /api/jobs/<other-tech-job>``           — direct read
* ``GET /api/schedule/today``                  — today lens
* ``GET /api/schedule/day?date=<today>``       — arbitrary day
* ``GET /api/schedule/unassigned-pending-stale`` — admin gate
* ``GET /api/dispatch``                        — admin gate
* ``GET /api/dispatch/board``                  — admin gate

The tech uses ``mike@aquaterra.com``. Any leaked job that is
NOT assigned to mike (or mike's crew — currently mike has no
crew, so crew_id must be ``None`` on every returned row) is a
K73 regression.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"
TODAY = datetime.now(timezone.utc).date().isoformat()


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def mike_profile(tech_h):
    r = requests.get(f"{API}/auth/me", headers=tech_h, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def mike_crew_ids(tech_h) -> list[str]:
    """Fetch the technician_ids mike shares a crew with. In the
    aquaterra fixture mike is a solo tech and this returns
    ``[]``; the test still asserts membership works when
    populated."""
    r = requests.get(f"{API}/crews", headers=tech_h, timeout=15)
    r.raise_for_status()
    body = r.json()
    crews = body if isinstance(body, list) else (body.get("items") or [])
    me = requests.get(f"{API}/auth/me", headers=tech_h, timeout=15).json()
    tid = me.get("technician_id")
    for c in crews:
        if tid in (c.get("tech_ids") or []):
            return list(c.get("tech_ids") or [])
    return [tid] if tid else []


def _tid_of(job: dict) -> str | None:
    return (job.get("technician_id")
            or job.get("assigned_tech_id")
            or job.get("tech_id"))


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("jobs", "items", "routes", "stops", "data", "rows"):
            v = body.get(k)
            if isinstance(v, list):
                return v
    return []


class TestJobsListScope:
    def test_tech_only_sees_own_or_crew_jobs(self, tech_h, mike_crew_ids):
        r = requests.get(f"{API}/jobs?limit=500", headers=tech_h, timeout=30)
        assert r.status_code == 200, r.text
        rows = _rows(r.json())
        for j in rows:
            tid = _tid_of(j)
            # Unassigned rows are allowed — the tech list-view
            # legitimately surfaces jobs that no-one owns yet
            # so a manager can hand them out.
            if tid is None:
                continue
            assert tid in mike_crew_ids, (
                f"[K73 regression] job {j.get('id')} leaked to mike"
                f" (technician_id={tid!r}, mike's crew={mike_crew_ids!r})"
            )

    def test_tech_cannot_override_technician_id_filter(self, tech_h,
                                                       super_h, mike_crew_ids):
        # Grab any job that belongs to a DIFFERENT tech via the
        # super-admin view, then attempt to fetch it as mike via
        # the same ``?technician_id=`` query.
        r = requests.get(f"{API}/jobs?limit=500", headers=super_h, timeout=30)
        assert r.status_code == 200
        other = None
        for j in _rows(r.json()):
            tid = _tid_of(j)
            if tid and tid not in mike_crew_ids:
                other = tid
                break
        if not other:
            pytest.skip("no cross-tech job in fixture")
        r2 = requests.get(f"{API}/jobs?technician_id={other}&limit=500",
                          headers=tech_h, timeout=30)
        assert r2.status_code == 200
        for j in _rows(r2.json()):
            tid = _tid_of(j)
            if tid is None:
                continue
            assert tid in mike_crew_ids, (
                f"[K73 regression] technician_id-override let mike see {tid!r}"
            )


class TestJobsDirectRead:
    def test_tech_gets_403_on_other_techs_job(self, tech_h, super_h, mike_crew_ids):
        # Find another tech's job via super-admin.
        r = requests.get(f"{API}/jobs?limit=500", headers=super_h, timeout=30)
        target = None
        for j in _rows(r.json()):
            tid = _tid_of(j)
            if tid and tid not in mike_crew_ids:
                target = j.get("id")
                break
        if not target:
            pytest.skip("no cross-tech job in fixture")
        r2 = requests.get(f"{API}/jobs/{target}", headers=tech_h, timeout=15)
        assert r2.status_code in (403, 404), \
            f"[K73 regression] mike could read job {target}: {r2.status_code}"


class TestScheduleDayScope:
    def test_today_route_scoped(self, tech_h, mike_crew_ids):
        r = requests.get(f"{API}/schedule/today", headers=tech_h, timeout=30)
        assert r.status_code == 200, r.text
        rows = _rows(r.json())
        for j in rows:
            tid = _tid_of(j)
            if tid is None:
                continue
            assert tid in mike_crew_ids, (
                f"[K73 regression] schedule/today leaked {tid!r} to mike"
            )

    def test_day_route_scoped(self, tech_h, mike_crew_ids):
        r = requests.get(f"{API}/schedule/day?date={TODAY}",
                         headers=tech_h, timeout=30)
        assert r.status_code == 200, r.text
        rows = _rows(r.json())
        for j in rows:
            tid = _tid_of(j)
            if tid is None:
                continue
            assert tid in mike_crew_ids, (
                f"[K73 regression] schedule/day leaked {tid!r} to mike"
            )


class TestAdminOnlyEndpointsGate:
    """The audit found these endpoints already 403 for tech. Lock
    that in so a future permissions-refactor can't accidentally
    open them up."""

    @pytest.mark.parametrize("path", [
        "/schedule/unassigned-pending-stale",
        "/dispatch",
        f"/dispatch/board?date={TODAY}",
        f"/dispatch/route/unscheduled-jobs?date={TODAY}",
        "/dispatch/route/savings/weekly",
    ])
    def test_tech_forbidden(self, tech_h, path):
        r = requests.get(f"{API}{path}", headers=tech_h, timeout=15)
        assert r.status_code in (401, 403), \
            f"[K73 regression] tech got {r.status_code} on {path}"


class TestCustomersDirectReadScoped:
    """Direct customer reads should not leak PII to techs who
    have no job at that customer. The customer list is a coworker
    directory (allowed) but a targeted read is not."""

    def test_tech_gets_404_on_unrelated_customer(self, tech_h, super_h):
        r = requests.get(f"{API}/jobs?limit=500", headers=super_h, timeout=30)
        me = requests.get(f"{API}/auth/me", headers=tech_h, timeout=15).json()
        my_tid = me.get("technician_id")
        target_cid = None
        for j in _rows(r.json()):
            if _tid_of(j) and _tid_of(j) != my_tid and j.get("customer_id"):
                target_cid = j["customer_id"]
                break
        if not target_cid:
            pytest.skip("no cross-tech customer in fixture")
        r2 = requests.get(f"{API}/customers/{target_cid}",
                          headers=tech_h, timeout=15)
        assert r2.status_code in (403, 404), (
            f"[K73 regression] mike could read customer {target_cid}: "
            f"status={r2.status_code}"
        )
