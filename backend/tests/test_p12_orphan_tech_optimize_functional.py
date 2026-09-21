"""Phase P12 · Feb-2026 — Orphan-loop functional test (closes tester HUMAN_REQUIRED gap).

Complements ``test_p12_route_optimize_orphan_soft.py`` with a
direct-Mongo seed that stresses BOTH soft-guard exits at once so
they're proven to coexist in a single request:

  Job A — Mike as ``technician_id``, clean (goes to
          ``ordered_job_ids``).
  Job B — Mike as ``assigned_technician_id``, ``technician_id``
          points at an obviously-fake ORPHAN id (goes to
          ``ordered_job_ids`` + ``orphaned_tech_ids``).
  Job C — Mike as ``assigned_technician_id``, no ``technician_id``,
          no ``assigned_to`` (goes to ``skipped_unassigned``).

The pre-P12 clobbered query silently degraded the tech-lane to
"any tenant job today", which meant this scenario couldn't even
be constructed reliably. Post-P12 the lane filter is honest AND
the orphan/unassigned soft-guard surfaces both classes at once —
that's what this test locks in.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def _cleanup(dbc):
    bag: list[str] = []
    yield bag
    for jid in bag:
        dbc.jobs.delete_one({"id": jid})


def test_p12_orphan_loop_functional_both_soft_guards_fire(dbc, _cleanup):
    """Three-shape seed exercises both ``orphaned_tech_ids`` and
    ``skipped_unassigned`` in one call."""
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    assert mike, "mike@aquaterra.com missing from seed"
    tenant_id = mike["tenant_id"]

    # Use a distant future day so the query cache doesn't collide
    # with anything real. All three jobs share the same day.
    day = "2027-04-04"
    orphan_ref = "ORPHAN-XYZ-{}".format(uuid.uuid4().hex[:6])

    job_a = str(uuid.uuid4())     # Clean — Mike's technician_id.
    job_b = str(uuid.uuid4())     # Orphaned technician_id, assigned to Mike.
    job_c = str(uuid.uuid4())     # No technician_id at all, assigned to Mike.

    # A: clean.
    dbc.jobs.insert_one({
        "id": job_a, "tenant_id": tenant_id,
        "technician_id": mike["id"],
        "title": "p12-orphan-loop · clean",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.800, "site_lng": -112.100,
        "address": "clean site",
    })
    _cleanup.append(job_a)

    # B: technician_id points at an orphan; matches Mike's lane
    #    via ``assigned_technician_id``.
    dbc.jobs.insert_one({
        "id": job_b, "tenant_id": tenant_id,
        "technician_id": orphan_ref,
        "assigned_technician_id": mike["id"],
        "title": "p12-orphan-loop · orphan-ref",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.810, "site_lng": -112.110,
        "address": "orphan site",
    })
    _cleanup.append(job_b)

    # C: no technician_id AT ALL; matches Mike's lane via
    #    ``assigned_technician_id``. Must land in skipped_unassigned.
    dbc.jobs.insert_one({
        "id": job_c, "tenant_id": tenant_id,
        "assigned_technician_id": mike["id"],
        "title": "p12-orphan-loop · unassigned",
        "status": "scheduled",
        "scheduled_date": day,
        "site_lat": 33.820, "site_lng": -112.120,
        "address": "unassigned site",
    })
    _cleanup.append(job_c)

    admin_tok = _login("admin@aquaterra.com")["access_token"]
    r = requests.post(
        f"{API}/schedule/optimize-route",
        headers={"Authorization": f"Bearer {admin_tok}"},
        json={"technician_id": mike["id"], "date": day},
        timeout=30,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()

    ordered = body.get("ordered_job_ids") or []
    orphaned = body.get("orphaned_tech_ids") or []
    skipped = body.get("skipped_unassigned") or []
    warnings = body.get("warnings") or []

    # 1) Clean job made it through.
    assert job_a in ordered, (
        f"clean job A missing from ordered_job_ids: {ordered}"
    )
    # 2) Orphan job made it through AND surfaces its ref in
    #    ``orphaned_tech_ids``.
    assert job_b in ordered, (
        f"orphan job B missing from ordered_job_ids: {ordered}"
    )
    assert orphan_ref in orphaned, (
        f"orphan ref {orphan_ref!r} missing from orphaned_tech_ids: "
        f"{orphaned}"
    )
    # 3) Unassigned job C was skipped from the optimizer input AND
    #    surfaces its id in ``skipped_unassigned``.
    assert job_c not in ordered, (
        f"unassigned job C leaked into ordered_job_ids: {ordered}"
    )
    assert job_c in skipped, (
        f"unassigned job C missing from skipped_unassigned: {skipped}"
    )
    # 4) The ``warnings`` list carries at least one human-readable
    #    line for each soft-guard class.
    joined = " ".join(warnings).lower()
    assert "orphan" in joined, (
        f"missing 'orphaned technician' warning line: {warnings}"
    )
    assert "no technician_id" in joined or "skipped" in joined, (
        f"missing 'skipped / no technician_id' warning line: {warnings}"
    )
