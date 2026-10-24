"""TD-crew-edit-no-auto-remove-and-save-full-roster · Feb-2026.

Contract tests for Ticket G.  Locks in the BE behaviour the ticket
depends on even though the FE change (``OpsHub.jsx`` auto-prune
removal) is where the source edit actually lives — a future
"cleanup" refactor on the BE that re-introduces role / lifecycle
filtering on ``_resolve_tenant_members`` would silently regress
the ticket's user-visible fix without this suite catching it.

Scope
    * ``PATCH /api/crews/{cid}`` persists the full ``tech_ids``
      array even when some members are role=admin, role=super_admin,
      ``active=false``, or soft-deleted.  No role gate, no
      lifecycle gate.
    * ``PATCH`` returns 400 with categorised ``errors`` list when
      a ``tech_id`` references a user that doesn't exist anywhere
      (``reason: orphan``) or belongs to a different tenant
      (``reason: foreign_tenant``, with ``tenant_id`` set).
    * Tenant isolation — admin on tenant A cannot inject
      another tenant's user into their own crew.
    * ``PATCH`` is admin-only; non-admin receives 403.

Everything self-seeds (sync pymongo + self-minted JWT, mirrors the
CARAC pattern used in ``test_td_timeclock_tech_clock_out_flow``) so
the suite runs green in every env without depending on a specific
upstream seed.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = (
    _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = _BE_ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE_ENV.get("DB_NAME") or os.environ.get("DB_NAME")
JWT_SECRET = (
    _BE_ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = "HS256"


def _mint(uid: str, email: str, tid: str, role: str) -> str:
    return jwt.encode(
        {"sub": uid, "email": email, "role": role, "tenant_id": tid,
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm=JWT_ALGO,
    )


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def tenants(db):
    """Spin up two tenants (A + B) so the isolation + foreign-tenant
    cases are self-contained."""
    tid_a = f"td-crew-ga-{uuid.uuid4().hex[:8]}"
    tid_b = f"td-crew-gb-{uuid.uuid4().hex[:8]}"
    db.tenants.insert_many([
        {"id": tid_a, "name": "TD-crew G tenant A", "slug": tid_a, "active": True},
        {"id": tid_b, "name": "TD-crew G tenant B", "slug": tid_b, "active": True},
    ])
    yield {"a": tid_a, "b": tid_b}
    db.tenants.delete_many({"id": {"$in": [tid_a, tid_b]}})


@pytest.fixture(scope="module")
def seeded(db, tenants):
    """Seed a cross-section of tenant-A users (one of every lifecycle
    bucket the FE used to drop), a tenant-B tech, and a single
    orphan ``tech_id`` string.

    Yields the id map + the admin header the tests use to call
    ``PATCH /crews/{id}``.
    """
    tid_a, tid_b = tenants["a"], tenants["b"]
    bag = {
        "admin": f"u-adm-{uuid.uuid4().hex[:8]}",
        "field_tech": f"u-fld-{uuid.uuid4().hex[:8]}",
        "super_admin_member": f"u-sa-{uuid.uuid4().hex[:8]}",
        "admin_member": f"u-am-{uuid.uuid4().hex[:8]}",
        "inactive_member": f"u-in-{uuid.uuid4().hex[:8]}",
        "soft_deleted_member": f"u-sd-{uuid.uuid4().hex[:8]}",
        "foreign_tech": f"u-fg-{uuid.uuid4().hex[:8]}",
        "orphan_id": f"u-orphan-{uuid.uuid4().hex[:8]}",
    }
    db.users.insert_many([
        {"id": bag["admin"], "tenant_id": tid_a, "role": "admin",
         "email": f'{bag["admin"]}@td.local', "name": "G Admin",
         "active": True, "password_hash": "x"},
        {"id": bag["field_tech"], "tenant_id": tid_a, "role": "technician",
         "email": f'{bag["field_tech"]}@td.local', "name": "G Field Tech",
         "active": True},
        {"id": bag["super_admin_member"], "tenant_id": tid_a,
         "role": "super_admin",
         "email": f'{bag["super_admin_member"]}@td.local',
         "name": "G Super Admin Member", "active": True},
        {"id": bag["admin_member"], "tenant_id": tid_a, "role": "admin",
         "email": f'{bag["admin_member"]}@td.local',
         "name": "G Admin Member", "active": True},
        {"id": bag["inactive_member"], "tenant_id": tid_a, "role": "technician",
         "email": f'{bag["inactive_member"]}@td.local',
         "name": "G Inactive Member", "active": False},
        {"id": bag["soft_deleted_member"], "tenant_id": tid_a,
         "role": "technician",
         "email": f'{bag["soft_deleted_member"]}@td.local',
         "name": "G Soft-Deleted Member", "active": True,
         "deleted_at": datetime.now(timezone.utc).isoformat()},
        {"id": bag["foreign_tech"], "tenant_id": tid_b, "role": "technician",
         "email": f'{bag["foreign_tech"]}@td.local',
         "name": "G Foreign Tech", "active": True},
    ])
    admin_tok = _mint(bag["admin"], f'{bag["admin"]}@td.local', tid_a, "admin")
    tech_tok = _mint(
        bag["field_tech"], f'{bag["field_tech"]}@td.local', tid_a, "technician")
    yield {
        **bag, "tid_a": tid_a, "tid_b": tid_b,
        "admin_h": {"Authorization": f"Bearer {admin_tok}"},
        "tech_h": {"Authorization": f"Bearer {tech_tok}"},
    }
    # Teardown
    db.users.delete_many({"id": {"$in": [v for k, v in bag.items()
                                          if k != "orphan_id"]}})
    db.crews.delete_many({"tenant_id": {"$in": [tid_a, tid_b]}})


@pytest.fixture
def crew(seeded, db):
    """A fresh empty crew in tenant A for each test — avoids cross-
    test state leaking through the roster field.
    """
    cid = f"td-crewG-{uuid.uuid4().hex[:8]}"
    db.crews.insert_one({
        "id": cid, "tenant_id": seeded["tid_a"], "name": "TD-G Crew",
        "color": "#3B82F6", "tech_ids": [seeded["field_tech"]],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield cid
    db.crews.delete_many({"id": cid})


# ─── Core contract: full roster persists regardless of role/lifecycle ─────
def test_patch_persists_full_roster_with_admin_super_admin_inactive_soft_deleted(
    seeded, crew, db,
):
    """The exact Ticket-G user-visible contract.  Operator saves a
    crew whose members span every lifecycle bucket the FE used to
    silently drop; the BE must persist all of them with no gate.
    """
    full_roster = [
        seeded["field_tech"],
        seeded["admin_member"],
        seeded["super_admin_member"],
        seeded["inactive_member"],
        seeded["soft_deleted_member"],
    ]
    r = requests.patch(
        f"{API}/crews/{crew}",
        headers=seeded["admin_h"],
        json={"tech_ids": full_roster},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["tech_ids"]) == set(full_roster)
    # DB-level receipt — regression lock
    doc = db.crews.find_one({"id": crew}, {"_id": 0, "tech_ids": 1})
    assert set(doc["tech_ids"]) == set(full_roster)
    assert len(doc["tech_ids"]) == 5


# ─── 400 on orphan id (truly structural) ───────────────────────
def test_patch_returns_400_with_orphan_category_for_unknown_id(
    seeded, crew,
):
    r = requests.patch(
        f"{API}/crews/{crew}",
        headers=seeded["admin_h"],
        json={"tech_ids": [seeded["field_tech"], seeded["orphan_id"]]},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    # detail may be the structured payload directly or wrapped.
    payload = detail if isinstance(detail, dict) else detail
    errors = (payload or {}).get("errors") or []
    orphan_hits = [e for e in errors if e.get("tech_id") == seeded["orphan_id"]]
    assert orphan_hits, errors
    assert orphan_hits[0]["reason"] == "orphan"


# ─── 400 on foreign-tenant id ───────────────────────────────────
def test_patch_returns_400_with_foreign_tenant_category(seeded, crew):
    r = requests.patch(
        f"{API}/crews/{crew}",
        headers=seeded["admin_h"],
        json={"tech_ids": [seeded["field_tech"], seeded["foreign_tech"]]},
        timeout=20,
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail")
    payload = detail if isinstance(detail, dict) else detail
    errors = (payload or {}).get("errors") or []
    foreign_hits = [e for e in errors
                     if e.get("tech_id") == seeded["foreign_tech"]]
    assert foreign_hits, errors
    assert foreign_hits[0]["reason"] == "foreign_tenant"
    assert foreign_hits[0]["tenant_id"] == seeded["tid_b"]


# ─── Tenant isolation on the endpoint itself ──────────────────
def test_patch_cannot_cross_tenants(seeded, db):
    # Spawn a crew in tenant B directly — tenant A admin must not
    # be able to mutate it.
    cid_b = f"td-crewG-b-{uuid.uuid4().hex[:8]}"
    db.crews.insert_one({
        "id": cid_b, "tenant_id": seeded["tid_b"], "name": "B Crew",
        "color": "#3B82F6", "tech_ids": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.patch(
            f"{API}/crews/{cid_b}",
            headers=seeded["admin_h"],
            json={"name": "pwned"},
            timeout=20,
        )
        assert r.status_code == 404, r.text
    finally:
        db.crews.delete_many({"id": cid_b})


# ─── Role gating on the endpoint ──────────────────────────────
def test_patch_requires_admin(seeded, crew):
    r = requests.patch(
        f"{API}/crews/{crew}",
        headers=seeded["tech_h"],
        json={"name": "nope"},
        timeout=20,
    )
    assert r.status_code == 403, r.text
