"""Feb-2026 · Landscape Time Clock — cross-trained ("both") tech gate.

The web `/team` "Tech (Both)" PR loosened `_VALID_DEPTS_BY_ROLE` in
``backend/routers/team.py`` so an admin can save a technician with
``department = "both"``. This test locks in that a cross-trained
technician can then actually PUNCH the landscape time clock.

The gate in ``routers/timeclock_landscaping.py::_require_landscaping``
already accepts ``dept in ("landscaping", "both")`` (added in Phase 56.3.B),
so the code path is not new — but there was no coverage explicitly
asserting the "both" branch. This file fills that gap so a future
tightening of the gate would fail loudly.

Coverage:
  1. A ``role="technician", department="both"`` user can POST
     ``/timeclock/punch`` with ``punch_type="in"`` (200).
  2. Same user can then punch out (200 + closes the shift).
  3. A ``role="technician", department="pool"`` user is REJECTED
     (403, code = "not_landscaping").  Guardrail: guarantees the
     "both" branch didn't accidentally open the gate to pool techs.
  4. Admin passthrough still works (regression).

Harness matches ``test_phase26_bulk_apply_departments.py``:
sync PyMongo for setup, HTTP against the live pod, signed JWTs.
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


@pytest.fixture()
def tenant_id():
    tid = f"ltcb-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"LTCB {tid}", "slug": f"ltcb-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    # Also nuke any punches these tests created.
    _sync.timeclock_punches.delete_many({"tenant_id": tid})
    for col in ("tenants", "users"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *, department=None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@ltcb.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"LTCB {role}", "email": email,
        "department": department,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


def _auth(token: str, tenant_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": tenant_id,
    }


def _punch(user: dict, punch_type: str) -> requests.Response:
    return requests.post(
        f"{API}/timeclock/punch",
        headers=_auth(user["token"], user["tenant_id"]),
        json={
            "punch_type": punch_type,
            # No GPS — we just want the auth+department gate exercise.
            "lat": None, "lng": None, "accuracy_m": None,
            "source": "web", "geo_denied": True,
        },
    )


# ══════════════════════════════════════════════════════════════════
# 1 · Cross-trained ("both") tech can punch IN.
# ══════════════════════════════════════════════════════════════════
def test_dept_both_tech_can_punch_in(tenant_id):
    tech = _seed_user(tenant_id, "technician", department="both")
    r = _punch(tech, "in")
    assert r.status_code == 200, r.text
    # Persistence check — one open shift for this user, no `out` yet.
    open_shifts = list(_sync.timeclock_punches.find(
        {"user_id": tech["id"], "tenant_id": tenant_id},
    ))
    assert len(open_shifts) == 1
    assert open_shifts[0]["punch_type"] == "in"


# ══════════════════════════════════════════════════════════════════
# 2 · Same user can then punch OUT (full IN → OUT cycle).
# ══════════════════════════════════════════════════════════════════
def test_dept_both_tech_can_punch_in_then_out(tenant_id):
    tech = _seed_user(tenant_id, "technician", department="both")
    assert _punch(tech, "in").status_code == 200
    r = _punch(tech, "out")
    assert r.status_code == 200, r.text
    punches = list(_sync.timeclock_punches.find(
        {"user_id": tech["id"], "tenant_id": tenant_id},
    ).sort("timestamp", 1))
    types = [p["punch_type"] for p in punches]
    assert types == ["in", "out"]


# ══════════════════════════════════════════════════════════════════
# 3 · A pool-only tech still gets 403 (guardrail — "both" branch must
#      not have leaked into a "pool" acceptance).
# ══════════════════════════════════════════════════════════════════
def test_pool_only_tech_still_rejected(tenant_id):
    tech = _seed_user(tenant_id, "technician", department="pool")
    r = _punch(tech, "in")
    assert r.status_code == 403, r.text
    body = r.json()
    detail = body.get("detail") or {}
    # The 403 body contains a `code=not_landscaping` marker per the
    # `_require_landscaping` handler.
    if isinstance(detail, dict):
        assert detail.get("code") == "not_landscaping"


# ══════════════════════════════════════════════════════════════════
# 4 · Admin passthrough — still allowed regardless of department.
# ══════════════════════════════════════════════════════════════════
def test_admin_can_punch_regardless_of_department(tenant_id):
    # Admin with no department set — the gate uses role-based bypass.
    admin = _seed_user(tenant_id, "admin", department=None)
    r = _punch(admin, "in")
    assert r.status_code == 200, r.text
