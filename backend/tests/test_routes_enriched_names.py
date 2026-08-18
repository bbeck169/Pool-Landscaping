"""Feb-2026 · Routes enrichment · ``/api/routes/{tech_id}/stops``.

The endpoint denormalises ``customer_name`` from the job doc and now
also emits ``tech_name`` + ``tech_color_hex`` at the top level (single
user lookup, no N+1) and a per-stop ``customer_display_name`` fallback
for jobs whose customer was later deleted.

Sync ``pymongo`` + live ``requests`` pattern — matches the crews /
duplicate-key regression style so no Motor loop-binding flakes.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from pymongo import MongoClient


BASE_URL = ""
for ln in Path("/app/frontend/.env").read_text().splitlines():
    if ln.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _read_env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_read_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_read_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


@pytest.fixture(scope="module")
def tok() -> str:
    r = requests.post(f"{API}/auth/login", json=SUPER, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def seeded_route(sync_db):
    """Seed a technician user (with a color) + two jobs, then tear
    them down. Jobs live on a synthetic future date so they can't
    collide with real seed data."""
    date = "2029-11-15"
    day_start = f"{date}T09:00:00+00:00"
    day_end = f"{date}T10:00:00+00:00"
    tech_id = f"tech-routes-{uuid4().hex[:8]}"
    sync_db.users.insert_one({
        "id": tech_id,
        "tenant_id": AQUATERRA_TID,
        "role": "technician",
        "name": "Route Test Tech",
        "email": f"{tech_id}@t.local",
        "display_color_hex": "#DB2777",
    })
    j1 = {
        "id": f"job-r1-{uuid4().hex[:8]}",
        "tenant_id": AQUATERRA_TID,
        "technician_id": tech_id,
        "customer_id": "cust-alive",
        "customer_name": "Alive Alice",
        "title": "Weekly clean",
        "service_type": "Pool Cleaning",
        "scheduled_start": day_start,
        "scheduled_end": day_end,
        "scheduled_date": date,
        "status": "scheduled",
        "address": "123 Real St",
        "route_order": 1,
    }
    j2 = {
        "id": f"job-r2-{uuid4().hex[:8]}",
        "tenant_id": AQUATERRA_TID,
        "technician_id": tech_id,
        # Customer deleted after import — no ``customer_name`` on the
        # job doc; fallback to address must fire.
        "customer_id": "cust-deleted",
        "customer_name": "",
        "title": "Filter swap",
        "service_type": "Filter",
        "scheduled_start": day_start,
        "scheduled_end": day_end,
        "scheduled_date": date,
        "status": "scheduled",
        "address": "456 Ghost Ave",
        "route_order": 2,
    }
    sync_db.jobs.insert_many([j1, j2])
    yield {"tech_id": tech_id, "date": date, "jobs": [j1["id"], j2["id"]]}
    sync_db.users.delete_one({"id": tech_id})
    sync_db.jobs.delete_many({"id": {"$in": [j1["id"], j2["id"]]}})


def test_response_carries_tech_name_and_color(tok, seeded_route):
    r = requests.get(
        f"{API}/routes/{seeded_route['tech_id']}/stops?date={seeded_route['date']}",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tech_id"] == seeded_route["tech_id"]
    assert body["tech_name"] == "Route Test Tech"
    assert body["tech_color_hex"] == "#DB2777"
    assert body["count"] == 2


def test_customer_name_round_trips_and_deleted_falls_back(tok, seeded_route):
    r = requests.get(
        f"{API}/routes/{seeded_route['tech_id']}/stops?date={seeded_route['date']}",
        headers={"Authorization": f"Bearer {tok}"}, timeout=30,
    )
    stops = r.json()["stops"]
    by_id = {s["job_id"]: s for s in stops}
    alive = by_id[seeded_route["jobs"][0]]
    deleted = by_id[seeded_route["jobs"][1]]
    # Alive customer — name flows through.
    assert alive["customer_name"] == "Alive Alice"
    assert alive["customer_display_name"] == "Alive Alice"
    # Deleted customer — address takes over.
    assert deleted["customer_name"] == ""
    assert deleted["customer_display_name"] == "456 Ghost Ave"


def test_endpoint_is_tenant_scoped(tok, sync_db):
    """A tech id from a foreign tenant returns 0 stops even if that
    id happens to match a job in another tenant."""
    foreign_tech = f"foreign-tech-{uuid4().hex[:8]}"
    foreign_tenant = f"foreign-tenant-{uuid4().hex[:8]}"
    sync_db.users.insert_one({
        "id": foreign_tech, "tenant_id": foreign_tenant,
        "role": "technician", "name": "Foreign",
    })
    sync_db.jobs.insert_one({
        "id": f"job-foreign-{uuid4().hex[:8]}",
        "tenant_id": foreign_tenant,
        "technician_id": foreign_tech,
        "customer_name": "Foreign Cust",
        "scheduled_start": "2029-12-01T09:00:00+00:00",
        "scheduled_date": "2029-12-01",
        "status": "scheduled",
    })
    try:
        r = requests.get(
            f"{API}/routes/{foreign_tech}/stops?date=2029-12-01",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        # Super admin authed against aquaterra can't see the foreign
        # tenant's user row → ``tech_user`` empty → 0 stops returned.
        assert r.status_code == 200
        assert r.json()["count"] == 0
    finally:
        sync_db.users.delete_one({"id": foreign_tech})
        sync_db.jobs.delete_many({"tenant_id": foreign_tenant})
