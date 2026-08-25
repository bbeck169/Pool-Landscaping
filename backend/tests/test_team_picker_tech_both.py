"""Feb-2026 · Team picker — cross-trained technician (``"tech_both"``).

Locks in the ``("technician", "both")`` combo added to
``backend/routers/team.py``:

  * ``_ROLE_DEPT_COMBOS`` — ("technician", "both") → "Tech (Both)".
  * ``_VALID_DEPTS_BY_ROLE["technician"]`` — now includes "both".

Coverage:
  1. GET /api/team/role-options exposes the new combo to the picker.
  2. PATCH /api/users/{uid} with {role:"technician", department:"both"}
     succeeds (200) and persists the pair.
  3. PATCH /api/users/{uid} with the classic invalid pair
     {role:"admin", department:"pool"} still returns 400.
  4. Re-PATCHing an existing "tech + both" row to a plain "pool" tech
     also succeeds (regression: whitelist change must not lock rows in).
  5. non-admin caller → 403 (require_admin unchanged).

Ships in the same PR as the frontend ``ROLE_OPTIONS`` addition and the
``timeclock_landscaping.py`` docstring refresh.

Mirrors the harness used by ``test_phase26_bulk_apply_departments.py``:
sync PyMongo for setup/teardown, requests against the live pod
backend (``localhost:8001``), signed JWTs from ``backend/.env``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

JWT_SECRET = (
    _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET")
    or "dev-secret-change-me"
)
JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _tok(user_id: str, email: str, role: str,
          tenant_id: str | None = None) -> str:
    payload = {
        "sub": user_id, "email": email, "role": role,
        "tenant_id": tenant_id or "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


# ══════════════════════════════════════════════════════════════════
# Fixtures — one tenant per test, cleaned on teardown.
# ══════════════════════════════════════════════════════════════════
@pytest.fixture()
def tenant_id():
    tid = f"ptb-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"PTB {tid}", "slug": f"ptb-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "audit_log"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *, department=None,
                extra: dict | None = None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@ptb.test"
    doc = {
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"PTB {role}", "email": email,
        "department": department,
    }
    if extra:
        doc.update(extra)
    _sync.users.insert_one(doc)
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


@pytest.fixture()
def admin(tenant_id):
    return _seed_user(tenant_id, "admin")


@pytest.fixture()
def technician(tenant_id):
    return _seed_user(tenant_id, "technician", department="pool")


@pytest.fixture()
def super_admin(tenant_id):
    return _seed_user(tenant_id, "super_admin")


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


# ══════════════════════════════════════════════════════════════════
# 1 · GET /api/team/role-options exposes ("technician","both")
# ══════════════════════════════════════════════════════════════════
def test_role_options_lists_tech_both(admin):
    r = requests.get(f"{API}/team/role-options",
                     headers=_auth(admin["token"], admin["tenant_id"]))
    assert r.status_code == 200, r.text
    body = r.json()
    combos = {(o["role"], o.get("department")): o["label"]
              for o in body["options"]}
    # New combo present with the canonical label.
    assert ("technician", "both") in combos
    assert combos[("technician", "both")] == "Tech (Both)"
    # Existing four combos still present + unchanged labels.
    assert combos[("technician", "pool")]        == "Pool Tech"
    assert combos[("technician", "landscaping")] == "Landscape Tech"
    assert combos[("admin", None)]               == "Admin"
    assert combos[("admin", "both")]             == "All (Admin + Pool + Landscape)"


# ══════════════════════════════════════════════════════════════════
# 2 · PATCH /users/{uid} accepts {role:"technician", department:"both"}
# ══════════════════════════════════════════════════════════════════
def test_patch_user_accepts_tech_both(admin, technician):
    r = requests.patch(
        f"{API}/users/{technician['id']}",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"role": "technician", "department": "both"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    changes = body.get("changes") or {}
    # Department flipped from the seed "pool" → "both".
    assert changes.get("department", {}).get("new") == "both"
    # Row round-trips: refetch and confirm persistence.
    row = _sync.users.find_one({"id": technician["id"]},
                               {"_id": 0, "role": 1, "department": 1})
    assert row["role"] == "technician"
    assert row["department"] == "both"


# ══════════════════════════════════════════════════════════════════
# 3 · Legacy invalid pair {role:"admin", department:"pool"} still 400.
# ══════════════════════════════════════════════════════════════════
def test_patch_admin_pool_still_rejected(admin, super_admin):
    # Use super_admin as the actor so we can modify a different admin
    # row (self-demotion protection is separately covered).
    target = _seed_user(admin["tenant_id"], "admin")
    r = requests.patch(
        f"{API}/users/{target['id']}",
        headers=_auth(super_admin["token"], super_admin["tenant_id"]),
        json={"role": "admin", "department": "pool"},
    )
    assert r.status_code == 400, r.text
    # The exact whitelist error message from ``routers/team.py`` should
    # cite the role and the allowed set. We keep the assertion loose so
    # a wording tweak doesn't flake the test.
    assert "department" in r.text.lower()
    assert "admin" in r.text.lower()


# ══════════════════════════════════════════════════════════════════
# 4 · A "tech + both" row can be re-PATCHed to a plain "pool" tech.
#      Regression guard: whitelist change must not trap rows in "both".
# ══════════════════════════════════════════════════════════════════
def test_patch_from_tech_both_back_to_pool(admin, tenant_id):
    target = _seed_user(tenant_id, "technician", department="both")
    r = requests.patch(
        f"{API}/users/{target['id']}",
        headers=_auth(admin["token"], admin["tenant_id"]),
        json={"role": "technician", "department": "pool"},
    )
    assert r.status_code == 200, r.text
    row = _sync.users.find_one({"id": target["id"]},
                               {"_id": 0, "department": 1})
    assert row["department"] == "pool"


# ══════════════════════════════════════════════════════════════════
# 5 · A technician caller cannot PATCH /users/{id} (require_admin).
# ══════════════════════════════════════════════════════════════════
def test_technician_caller_blocked(technician, tenant_id):
    target = _seed_user(tenant_id, "technician", department="pool")
    r = requests.patch(
        f"{API}/users/{target['id']}",
        headers=_auth(technician["token"], technician["tenant_id"]),
        json={"role": "technician", "department": "both"},
    )
    # 401 or 403 both acceptable — require_admin can raise either.
    assert r.status_code in (401, 403), r.text
