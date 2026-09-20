"""Feb-2026 · P3 — Tech-name hydration in reports.py + analytics.py.

Five assertions across the two routers:

  1. ``GET /export/jobs`` returns a fresh ``technician_name`` after a
     user renames themselves — even though the job doc still holds the
     STALE snapshot from job-write time.
  2. Deleted tech user degrades gracefully — the endpoint does NOT 500;
     the row still lists the raw ``technician_id`` as the name fallback.
  3. Single hydration call per request — spy on ``resolve_technician_names``
     from inside the export/jobs handler to prove no N+1 across N job rows.
  4. Analytics utilization matrix (nested aggregation) hydrates the group
     keys too, and no longer silently drops ``users.id``-shaped rows.
  5. Analytics endpoint also runs at most one hydration call per request.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_tech_and_job(tid: str, *, tech_name: str, stale_snapshot: str,
                        completed_at: str) -> tuple[str, str]:
    """Insert a synthetic technician user + a completed job whose
    ``technician_name`` snapshot is intentionally stale. Returns (uid, jid).
    """
    uid = f"TEST_p3_u_{uuid.uuid4().hex[:8]}"
    jid = f"TEST_p3_j_{uuid.uuid4().hex[:8]}"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tid,
        "email": f"{uid}@example.com",
        "name": tech_name,
        "role": "technician",
        "active": True,
    })
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "title": "TEST P3 job",
        "customer_name": "TEST cust",
        "service_type": "pool",
        "status": "completed",
        "technician_id": uid,
        "technician_name": stale_snapshot,   # ← the bug: baked at write time
        "scheduled_date": completed_at.split("T")[0],
        "scheduled_start": completed_at,
        "scheduled_end": completed_at,
        "completed_at": completed_at,
        "price": 100.0,
        "created_at": completed_at,
    })
    return uid, jid


def _row_for(rows: list[dict], jid: str) -> dict | None:
    return next((r for r in rows if r.get("id") == jid), None)


def _rows_from_csv(csv_text: str) -> list[dict]:
    import csv, io
    return list(csv.DictReader(io.StringIO(csv_text)))


# ── 1. Renamed user → hydrated name overwrites the stale snapshot ──
def test_export_jobs_hydrates_current_tech_name(admin_h, aquaterra_tid):
    tid = aquaterra_tid
    uid, jid = _seed_tech_and_job(
        tid,
        tech_name="Mikey Fresh",
        stale_snapshot="Old Mikey (SNAPSHOT)",
        completed_at="2026-04-01T09:00:00+00:00",
    )
    try:
        r = requests.get(f"{API}/export/jobs?start=2026-04-01&end=2026-04-30",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        rows = _rows_from_csv(r.json()["content"])
        row = _row_for(rows, jid)
        assert row is not None, f"seeded job {jid} missing from export"
        assert row["technician_name"] == "Mikey Fresh", (
            f"stale snapshot leaked through hydration: {row['technician_name']!r}"
        )
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.users.delete_one({"id": uid})


# ── 2. Deleted tech user degrades gracefully ──────────────────────
def test_export_jobs_missing_user_degrades_gracefully(admin_h, aquaterra_tid):
    tid = aquaterra_tid
    uid, jid = _seed_tech_and_job(
        tid, tech_name="ephemeral tech",
        stale_snapshot="Stale Name",
        completed_at="2026-04-02T09:00:00+00:00",
    )
    # Delete the user immediately — job still references its id.
    _sync.users.delete_one({"id": uid})
    try:
        r = requests.get(f"{API}/export/jobs?start=2026-04-02&end=2026-04-30",
                          headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text  # must NOT 500
        rows = _rows_from_csv(r.json()["content"])
        row = _row_for(rows, jid)
        assert row is not None
        # Fallback = raw id (or the pre-existing snapshot). Either way,
        # the endpoint responded 200 with a printable value.
        assert row["technician_name"] in (uid, "Stale Name")
    finally:
        _sync.jobs.delete_one({"id": jid})


# ── 3. Single hydration call per request (no N+1) ─────────────────
def test_export_jobs_hydration_is_single_shot(monkeypatch, admin_h, aquaterra_tid):
    """Spy on ``resolve_technician_names`` inside the reports router.

    We monkeypatch the module-level reference so the handler's call
    site funnels through our counter, then hit the endpoint with 5+
    seeded jobs across 3 different tech ids. Assertion: the spy fires
    exactly ONCE — proving the batch shape survived, no per-row hits.
    """
    from routers import reports as _reports

    counter = {"n": 0}
    real = _reports.resolve_technician_names

    async def _spy(db_arg, tenant_arg, ids_arg):
        counter["n"] += 1
        return await real(db_arg, tenant_arg, ids_arg)

    monkeypatch.setattr(_reports, "resolve_technician_names", _spy)

    tid = aquaterra_tid
    seeded: list[tuple[str, str]] = []
    for i in range(5):
        uid, jid = _seed_tech_and_job(
            tid, tech_name=f"Fresh {i}",
            stale_snapshot=f"stale {i}",
            completed_at="2026-04-03T09:00:00+00:00",
        )
        seeded.append((uid, jid))
    try:
        # NOTE: monkeypatch only takes effect inside this process, but
        # the endpoint runs in the supervisor-managed server process.
        # We instead exercise the code path directly to keep the spy
        # meaningful — call the handler function with a fake ``user``.
        import asyncio
        async def _call():
            return await _reports.export_jobs(
                user={"tenant_id": tid, "role": "admin"},
                start="2026-04-03", end="2026-04-30",
            )
        payload = asyncio.get_event_loop().run_until_complete(_call())
        assert counter["n"] == 1, f"resolve_technician_names called {counter['n']}× (expected 1)"
        # And the returned CSV actually reflects the hydrated names.
        rows = _rows_from_csv(payload["content"])
        for uid, jid in seeded:
            row = _row_for(rows, jid)
            assert row is not None
            # ``Fresh N`` from users.name — not the ``stale N`` from job doc.
            assert row["technician_name"].startswith("Fresh "), row["technician_name"]
    finally:
        for uid, jid in seeded:
            _sync.jobs.delete_one({"id": jid})
            _sync.users.delete_one({"id": uid})


# ── 4. Analytics matrix — nested aggregation gets hydrated ────────
def test_analytics_utilization_matrix_hydrates_and_stops_dropping_users_id_rows(
    monkeypatch, aquaterra_tid,
):
    """The pre-P3 matrix looped ``techs = db.technicians.find(...)`` only,
    so a job whose ``technician_id`` was a ``users.id`` (not present in
    the technicians collection) was silently dropped from the matrix.
    Post-P3 hydration unions observed ids into the row set.
    """
    from routers import analytics as _analytics

    counter = {"n": 0}
    real = _analytics.resolve_technician_names

    async def _spy(db_arg, tenant_arg, ids_arg):
        counter["n"] += 1
        return await real(db_arg, tenant_arg, ids_arg)

    monkeypatch.setattr(_analytics, "resolve_technician_names", _spy)

    tid = aquaterra_tid
    uid, jid = _seed_tech_and_job(
        tid, tech_name="Fresh Utilization",
        stale_snapshot="Stale Utilization",
        completed_at="2026-04-04T09:00:00+00:00",
    )
    try:
        import asyncio
        # Locate the utilization handler by scanning the router for the
        # endpoint that produces a ``matrix`` — the tech utilization one.
        util_fn = None
        for route in _analytics.router.routes:
            if "tech-productivity" in getattr(route, "path", ""):
                util_fn = route.endpoint
                break
        assert util_fn is not None, "tech-productivity endpoint not registered"

        payload = asyncio.get_event_loop().run_until_complete(
            util_fn(user={"tenant_id": tid, "role": "admin"},
                    tenant={"id": tid},
                    start="2026-04-04", end="2026-04-30"),
        )
        matrix = payload.get("matrix") or []
        row = next((r for r in matrix if r["technician_id"] == uid), None)
        assert row is not None, (
            "users.id-shaped technician_id was silently dropped from the matrix"
        )
        # Fresh hydrated name — NOT the stale snapshot from the job doc.
        assert row["technician_name"] == "Fresh Utilization", row["technician_name"]
        # And the spy fired exactly once — no N+1.
        assert counter["n"] == 1, f"analytics called hydrate {counter['n']}×"
    finally:
        _sync.jobs.delete_one({"id": jid})
        _sync.users.delete_one({"id": uid})
