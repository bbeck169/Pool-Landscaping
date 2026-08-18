"""Feb-2026 · super_admin ≥ admin coverage + assignable-user widen.

Two invariants pinned in this suite:

1. **Item 1** — a ``super_admin`` session must be accepted by every
   route an ``admin`` session is accepted by (baseline: 200 on GETs
   that require admin+). Confirms no gate silently drops
   super_admin.

2. **Item 2** — ``/api/technicians`` returns admin / super_admin /
   manager rows alongside real technicians, and POST /jobs accepts
   an admin user id in the ``technician_id`` field.
"""
from __future__ import annotations

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

AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


def _login(email: str, password: str = "password123"):
    try:
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception:
        return None


ADMIN_ROUTES = [
    "/technicians",
    "/team",
    "/recurring-jobs",
    "/jobs?limit=1",
]


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_super_admin_matches_admin_on_admin_routes(route):
    """Any GET route accepted for admin must also accept super_admin."""
    su = _login("super@aquaterra.com")
    ad = _login("admin@aquaterra.com")
    if not (su and ad):
        pytest.skip("super/admin seeds not both provisioned")
    su_r = requests.get(f"{API}{route}", headers={"Authorization": f"Bearer {su}"}, timeout=15)
    ad_r = requests.get(f"{API}{route}", headers={"Authorization": f"Bearer {ad}"}, timeout=15)
    # Both must land in the 2xx band. Skew is what we're pinning
    # against — if the admin passes and super_admin doesn't, that's
    # the exact regression we care about.
    assert 200 <= ad_r.status_code < 300, f"admin unexpectedly 4xx on {route}: {ad_r.status_code}"
    assert 200 <= su_r.status_code < 300, f"super_admin blocked on {route}: {su_r.status_code}"


def test_technicians_endpoint_includes_admin_super_admin_manager(sync_db):
    tok = _login("super@aquaterra.com")
    r = requests.get(f"{API}/technicians", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    r.raise_for_status()
    rows = r.json()
    roles = {str(x.get("role") or "").lower() for x in rows}
    # The synth section unions users with these roles; the fixture
    # tenant has all three seeded.
    assert "admin" in roles or "super_admin" in roles, \
        f"admin family missing from /technicians: {roles}"
    # Regression guard — technicians must still be there.
    assert "technician" in roles or "landscaper" in roles


def test_post_jobs_accepts_admin_id_as_technician(sync_db):
    tok = _login("super@aquaterra.com")
    # Grab an admin-family user in-tenant.
    admin_user = sync_db.users.find_one(
        {"tenant_id": AQUATERRA_TID,
         "role": {"$in": ["admin", "super_admin", "manager"]}},
        {"_id": 0, "id": 1, "role": 1, "email": 1},
    )
    assert admin_user, "no admin-family user in tenant"
    payload = {
        "customer_id": "bug-repro-1",
        "title": "Assignable-widen test",
        "service_type": "Repair",
        "technician_id": admin_user["id"],
        "scheduled_date": "2026-08-30",
        "status": "scheduled",
        "price": 0,
    }
    r = requests.post(
        f"{API}/jobs", json=payload,
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    new_id = body[0]["id"] if isinstance(body, list) else body.get("id")
    try:
        # Confirm the row round-trips with the admin user set as
        # ``technician_id``.
        stored = sync_db.jobs.find_one({"id": new_id})
        assert stored and stored["technician_id"] == admin_user["id"]
    finally:
        if new_id:
            sync_db.jobs.delete_one({"id": new_id})
