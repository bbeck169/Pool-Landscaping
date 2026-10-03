"""
Admin · Unlinked Technicians · Remove endpoint — Feb-2026
=========================================================
Covers ``POST /api/admin/technicians/{tech_id}/remove`` shipped in
``backend/routers/admin_unlinked_techs.py``.

Test matrix:

  Unit — ``require_admin_or_manager`` dep (shared with Convert /
  Decline / Reopen):
    * 4 allow × admin, super_admin, owner, manager
    * 3 deny  × technician, customer, dispatcher

  Integration — live HTTP against the preview backend, Mongo
  direct-seed for setup / assertions:
    * happy path (admin role)
      - 200 + ``deleted_at`` + ``deleted_by_user_id`` stamped
      - audit row written to ``db.audit_log``
      - subsequent GET /admin/technicians/unlinked HIDES the row
    * 404 — tech not found
    * 404 — cross-tenant (same code; never leak tenant membership)
    * 400 — already-linked tech (``user_id`` set) returns
      ``{code:"not_unlinked_technician"}``
    * 400 — already-removed tech returns
      ``{code:"already_removed", deleted_at:<iso>}``

Pat Kail lock: this file NEVER seeds against customer_id
``014ce6bb-1dbc-4067-998d-e05c16e7e342``. All seeds are UUID4-scoped.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values, load_dotenv
from fastapi import HTTPException

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 30

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}

PAT_KAIL_LOCKED = "014ce6bb-1dbc-4067-998d-e05c16e7e342"


# ─── Admin / manager / etc. role fixtures (shared with Phase 3) ───
_ADMIN      = {"id": "u-admin-1",      "role": "admin",      "tenant_id": "t-x"}
_SUPERADMIN = {"id": "u-super-1",      "role": "super_admin","tenant_id": "t-x"}
_OWNER      = {"id": "u-owner-1",      "role": "owner",      "tenant_id": "t-x"}
_MANAGER    = {"id": "u-manager-1",    "role": "manager",    "tenant_id": "t-x"}
_TECH       = {"id": "u-tech-1",       "role": "technician", "tenant_id": "t-x"}
_CUSTOMER   = {"id": "u-cust-1",       "role": "customer",   "tenant_id": "t-x"}
_DISPATCHER = {"id": "u-disp-1",       "role": "dispatcher", "tenant_id": "t-x"}


# ═══════════════════════════════════════════════════════════════════
# Unit — require_admin_or_manager (dep used by the new endpoint)
# Lives at ``backend/utils.py:196`` and is shared with
# Convert-to-Invoice (Phase 1) + Decline / Reopen (Phase 3 B1 / B2).
# These parametrize cases lock the gate for the Remove endpoint.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("actor", [_ADMIN, _SUPERADMIN, _OWNER, _MANAGER])
def test_remove_rbac_allowed_roles(actor):
    """admin / super_admin / owner / manager pass the gate."""
    from utils import require_admin_or_manager
    assert require_admin_or_manager(user=actor) == actor


@pytest.mark.parametrize("actor", [_TECH, _CUSTOMER, _DISPATCHER])
def test_remove_rbac_denied_roles(actor):
    """technician / customer / dispatcher get 403 at the dep layer."""
    from utils import require_admin_or_manager
    with pytest.raises(HTTPException) as e:
        require_admin_or_manager(user=actor)
    assert e.value.status_code == 403


# ═══════════════════════════════════════════════════════════════════
# Integration helpers — Mongo direct seed + live HTTP admin session
# ═══════════════════════════════════════════════════════════════════
def _db():
    from pymongo import MongoClient
    mc = MongoClient(_ENV["MONGO_URL"])
    return mc[_ENV["DB_NAME"]]


def _admin_token() -> str:
    """Log in as the standard admin test account (same credentials
    used by the K79 toggle + decline/reopen suites)."""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@aquaterra.com", "password": "password123"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def _admin_tenant_id(token: str) -> str:
    """Resolve the admin's tenant_id via /api/auth/me — we need it
    to seed techs inside the same tenant so the endpoint can find
    them."""
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200
    return r.json()["tenant_id"]


@pytest.fixture
def seed():
    """Seed + teardown. Yields a dict with ``db``, ``token``,
    ``tenant_id``, ``cleanup_ids`` (list of tech_ids to delete on
    teardown). Pat Kail lock: no seeds against the locked
    customer_id."""
    db = _db()
    token = _admin_token()
    tenant_id = _admin_tenant_id(token)
    cleanup_ids: list[str] = []
    cleanup_audit_actions = ["unlinked_technician_removed"]
    cleanup_audit_tech_ids: list[str] = []

    assert tenant_id != PAT_KAIL_LOCKED

    def _seed_tech(**overrides) -> dict:
        tech_id = f"tech-remove-test-{uuid4()}"
        assert tech_id != PAT_KAIL_LOCKED
        doc = {
            "id":          tech_id,
            "tenant_id":   tenant_id,
            "name":        "Test Tech · remove-regression",
            "email":       f"testtech-{uuid4()}@example.test",
            "phone":       "+1-555-0100",
            "user_id":     None,
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        doc.update(overrides)
        db.technicians.insert_one(doc)
        cleanup_ids.append(tech_id)
        cleanup_audit_tech_ids.append(tech_id)
        return doc

    yield {
        "db":          db,
        "token":       token,
        "tenant_id":   tenant_id,
        "seed_tech":   _seed_tech,
        "cleanup_ids": cleanup_ids,
    }

    # Teardown — always runs.
    for tid in cleanup_ids:
        db.technicians.delete_many({"id": tid})
    for tid in cleanup_audit_tech_ids:
        db.audit_log.delete_many({
            "action": {"$in": cleanup_audit_actions},
            "target_tech_id": tid,
        })


def _remove(tech_id: str, token: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/api/admin/technicians/{tech_id}/remove",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQ_TIMEOUT,
    )


# ═══════════════════════════════════════════════════════════════════
# Integration — happy path (admin)
# ═══════════════════════════════════════════════════════════════════
def test_remove_happy_path_stamps_deleted_at_and_audit_row(seed):
    tech = seed["seed_tech"]()
    r = _remove(tech["id"], seed["token"])
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:400]}"

    body = r.json()
    assert body["ok"] is True
    assert body["tech_id"] == tech["id"]
    assert isinstance(body["deleted_at"], str) and body["deleted_at"]
    assert isinstance(body["deleted_by_user_id"], str) and body["deleted_by_user_id"]

    # Verify Mongo state.
    row = seed["db"].technicians.find_one({"id": tech["id"]}, {"_id": 0})
    assert row is not None
    assert row["deleted_at"] == body["deleted_at"]
    assert row["deleted_by_user_id"] == body["deleted_by_user_id"]
    assert row["updated_at"] == body["deleted_at"]

    # Verify audit row written to db.audit_log (singular — matches
    # the file-local convention used by the sibling create-user
    # audit writer).
    audit = seed["db"].audit_log.find_one({
        "action": "unlinked_technician_removed",
        "target_tech_id": tech["id"],
    })
    assert audit is not None, (
        "Audit row missing for action=unlinked_technician_removed "
        f"target_tech_id={tech['id']}"
    )
    assert audit["tenant_id"] == seed["tenant_id"]
    assert audit["actor_user_id"] == body["deleted_by_user_id"]
    assert audit["at"] == body["deleted_at"]


# ═══════════════════════════════════════════════════════════════════
# Integration — 404 tech not found
# ═══════════════════════════════════════════════════════════════════
def test_remove_tech_not_found_returns_404(seed):
    r = _remove(f"nonexistent-tech-{uuid4()}", seed["token"])
    assert r.status_code == 404, f"HTTP {r.status_code}: {r.text[:200]}"


# ═══════════════════════════════════════════════════════════════════
# Integration — 404 cross-tenant (never leak membership)
# ═══════════════════════════════════════════════════════════════════
def test_remove_cross_tenant_returns_404(seed):
    tech_id = f"tech-xtenant-{uuid4()}"
    xtenant = f"tenant-foreign-{uuid4()}"
    assert xtenant != PAT_KAIL_LOCKED
    assert xtenant != seed["tenant_id"]

    seed["db"].technicians.insert_one({
        "id":         tech_id,
        "tenant_id":  xtenant,
        "name":       "Foreign tech",
        "user_id":    None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    seed["cleanup_ids"].append(tech_id)

    r = _remove(tech_id, seed["token"])
    assert r.status_code == 404, f"HTTP {r.status_code}: {r.text[:200]}"


# ═══════════════════════════════════════════════════════════════════
# Integration — 400 ``not_unlinked_technician`` for linked tech
# ═══════════════════════════════════════════════════════════════════
def test_remove_already_linked_returns_400_not_unlinked(seed):
    tech = seed["seed_tech"](user_id=f"u-linked-{uuid4()}")
    r = _remove(tech["id"], seed["token"])
    assert r.status_code == 400, f"HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body["detail"]["code"] == "not_unlinked_technician"


# ═══════════════════════════════════════════════════════════════════
# Integration — 400 ``already_removed`` for double-remove
# ═══════════════════════════════════════════════════════════════════
def test_remove_double_remove_returns_400_already_removed(seed):
    tech = seed["seed_tech"]()
    r1 = _remove(tech["id"], seed["token"])
    assert r1.status_code == 200
    first_deleted_at = r1.json()["deleted_at"]

    r2 = _remove(tech["id"], seed["token"])
    assert r2.status_code == 400, f"HTTP {r2.status_code}: {r2.text[:200]}"
    body = r2.json()
    assert body["detail"]["code"] == "already_removed"
    assert body["detail"]["deleted_at"] == first_deleted_at


# ═══════════════════════════════════════════════════════════════════
# Integration regression — GET list hides soft-deleted techs
# ═══════════════════════════════════════════════════════════════════
def test_list_endpoint_hides_soft_deleted_techs(seed):
    tech_a = seed["seed_tech"]()  # will stay unlinked + active
    tech_b = seed["seed_tech"]()  # will be removed

    # Remove B.
    r = _remove(tech_b["id"], seed["token"])
    assert r.status_code == 200

    # List should include A but NOT B.
    r_list = requests.get(
        f"{BASE_URL}/api/admin/technicians/unlinked",
        headers={"Authorization": f"Bearer {seed['token']}"},
        timeout=REQ_TIMEOUT,
    )
    assert r_list.status_code == 200
    ids = {t["tech_id"] for t in r_list.json()["technicians"]}
    assert tech_a["id"] in ids, (
        f"Active unlinked tech {tech_a['id']} missing from list"
    )
    assert tech_b["id"] not in ids, (
        f"Soft-deleted tech {tech_b['id']} should be hidden but was listed"
    )
