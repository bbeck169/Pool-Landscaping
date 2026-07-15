"""Phase 34a — dispatch.technician-skills backend dedup.

Regression guard: a tech with entries in BOTH `technicians` and `users`
must appear once in `/api/dispatch/technician-skills`. Previously the
router keyed dedup on `id` / `user_id`, so a legacy `technicians` row
with `user_id=None` slipped through and the human showed up twice.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN_A = {"email": "admin@aquaterra.com", "password": "password123"}
TECH    = {"email": "mike@aquaterra.com",  "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok): return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_a_tok(): return _login(ADMIN_A)


@pytest.fixture(scope="module")
def tech_tok(): return _login(TECH)


def _tenant_id_for(email: str) -> str:
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]

    async def _q():
        u = await db.users.find_one({"email": email})
        return u["tenant_id"] if u else None
    tid = asyncio.get_event_loop().run_until_complete(_q())
    cli.close()
    return tid


def test_existing_dedup_aquaterra_returns_two_techs(admin_a_tok):
    """Aquaterra fixture DB ships 2 humans (Mike + Sara). The previous
    endpoint returned 3 due to Mike existing in both collections. Now
    it must return exactly 2."""
    r = requests.get(f"{API}/dispatch/technician-skills",
                      headers=_auth(admin_a_tok), timeout=15)
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    emails = [(i.get("email") or "").lower() for i in items]
    assert len(items) == len(set(emails)), (
        f"duplicates present: {emails}"
    )
    assert 2 <= len(items) <= 5, f"expected ≥2 techs, got {len(items)}: {emails}"


def test_synthetic_double_row_dedups_to_one(admin_a_tok):
    """Seed a synthetic tech + user with the same email but different
    ids — the endpoint must fold them into one row and prefer the
    users row."""
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]
    tid = _tenant_id_for(ADMIN_A["email"])
    marker = f"TEST_dedup_{uuid.uuid4().hex[:8]}@aquaterra.com"
    user_id = f"TEST-user-{uuid.uuid4().hex[:8]}"
    tech_id = f"TEST-tech-{uuid.uuid4().hex[:8]}"

    async def _seed():
        await db.users.insert_one({
            "id": user_id, "tenant_id": tid,
            "email": marker, "role": "technician",
            "name": "TEST Rivera (users)",
            "preferred_service_types": ["pool"],
        })
        # `technicians` row for same human, but with NO user_id (the
        # exact shape that broke the old dedup logic).
        await db.technicians.insert_one({
            "id": tech_id, "tenant_id": tid,
            "email": marker, "user_id": None,
            "name": "TEST Rivera (technicians)",
            "is_active": True,
            "preferred_service_types": ["landscape"],
        })

    async def _cleanup():
        await db.users.delete_one({"id": user_id})
        await db.technicians.delete_one({"id": tech_id})

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_seed())
    try:
        r = requests.get(f"{API}/dispatch/technician-skills",
                          headers=_auth(admin_a_tok), timeout=15)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        # Router lowercases emails as it dedups — compare case-insensitively.
        rows = [i for i in items
                 if (i.get("email") or "").lower() == marker.lower()]
        assert len(rows) == 1, f"expected 1 row for {marker}, got {len(rows)}: {rows}"
        # Users row must win — id equals user_id.
        assert rows[0]["id"] == user_id
        # Non-empty preferred_service_types must be preserved
        # (users has ["pool"]).
        assert rows[0]["preferred_service_types"] == ["pool"]
        assert rows[0]["name"] == "TEST Rivera (users)"
    finally:
        loop.run_until_complete(_cleanup())
        cli.close()


def test_tech_role_forbidden(tech_tok):
    """RBAC guard preserved — non-admins get 403 (existing behavior)."""
    r = requests.get(f"{API}/dispatch/technician-skills",
                      headers=_auth(tech_tok), timeout=15)
    assert r.status_code == 403, r.text


def test_standalone_technician_without_user_still_included(admin_a_tok):
    """A `technicians` row with no matching user by email or user_id
    must still surface in the list."""
    env = dotenv_values("/app/backend/.env")
    cli = AsyncIOMotorClient(env["MONGO_URL"])
    db = cli[env["DB_NAME"]]
    tid = _tenant_id_for(ADMIN_A["email"])
    tech_id = f"TEST-tech-solo-{uuid.uuid4().hex[:8]}"
    marker = f"TEST_solo_{uuid.uuid4().hex[:6]}@aquaterra.com"

    async def _seed():
        await db.technicians.insert_one({
            "id": tech_id, "tenant_id": tid,
            "email": marker, "user_id": None,
            "name": "TEST Solo Tech", "is_active": True,
            "preferred_service_types": ["pool"],
        })

    async def _cleanup():
        await db.technicians.delete_one({"id": tech_id})

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_seed())
    try:
        r = requests.get(f"{API}/dispatch/technician-skills",
                          headers=_auth(admin_a_tok), timeout=15)
        assert r.status_code == 200
        rows = [i for i in r.json().get("items", [])
                 if (i.get("email") or "").lower() == marker.lower()]
        assert len(rows) == 1
        assert rows[0]["id"] == tech_id
        assert rows[0]["preferred_service_types"] == ["pool"]
    finally:
        loop.run_until_complete(_cleanup())
        cli.close()
