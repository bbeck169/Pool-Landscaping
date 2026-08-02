"""Phase 26 · Super-admin bulk-apply department suggestions — pytest.

Covers the four scenarios from the Phase 26 brief:

    1. Happy path — 3 applications land as 3 db.users updates + 3 audit
       rows in db.department_change_audit.
    2. Partial failure — 1 unknown user_id yields ``applied: 2`` and
       ``failed: [{user_id, reason: 'user_not_found'}]``.
    3. Auth — non-super-admin (admin, technician, customer) all 403.
    4. Empty payload — ``applied: 0, failed: []`` with zero writes to
       either users or audit collection.

The suite follows the shared harness used by the Phase-20 test:
sync PyMongo for setup/teardown, requests against the live pod
backend (``localhost:8001``), signed JWTs built from the backend .env.
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

JWT_SECRET = _ENV.get("JWT_SECRET") or os.environ.get("JWT_SECRET") \
    or "dev-secret-change-me"
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
# Fixtures — tenant + users of each role we need.
# ══════════════════════════════════════════════════════════════════
@pytest.fixture()
def tenant_id():
    tid = f"p26-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": f"P26 {tid}", "slug": f"p26-{tid}",
        "active": True, "widget_allowed_domains": [],
    })
    yield tid
    for col in ("tenants", "users", "department_change_audit"):
        _sync[col].delete_many({"tenant_id": tid})


def _seed_user(tenant_id: str, role: str, *, department=None) -> dict:
    uid = f"{role}-{uuid.uuid4().hex[:8]}"
    email = f"{uid}@p26.test"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"P26 {role}", "email": email,
        "department": department,
    })
    return {"id": uid, "email": email, "role": role,
            "tenant_id": tenant_id,
            "token": _tok(uid, email, role, tenant_id)}


@pytest.fixture()
def super_admin(tenant_id):
    return _seed_user(tenant_id, "super_admin")


@pytest.fixture()
def admin(tenant_id):
    return _seed_user(tenant_id, "admin")


@pytest.fixture()
def technician(tenant_id):
    return _seed_user(tenant_id, "technician")


def _post(url, token, tenant_id, payload):
    return requests.post(
        f"{API}{url}",
        headers={"Authorization": f"Bearer {token}",
                 "X-Tenant-Id": tenant_id},
        json=payload,
    )


# ══════════════════════════════════════════════════════════════════
# 1) Happy path — 3 applications → 3 updates + 3 audit rows.
# ══════════════════════════════════════════════════════════════════
def test_happy_path_three_applications_persist_and_audit(
    tenant_id, super_admin,
):
    techs = [_seed_user(tenant_id, "technician") for _ in range(3)]
    payload = {"applications": [
        {"user_id": techs[0]["id"], "department": "pool_tech"},
        {"user_id": techs[1]["id"], "department": "landscape_tech"},
        {"user_id": techs[2]["id"], "department": "both"},
    ]}
    r = _post("/admin/apply-department-suggestions",
              super_admin["token"], tenant_id, payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 3
    assert body["failed"] == []

    # db.users mutated for all three.
    for t, want in zip(techs, ["pool_tech", "landscape_tech", "both"]):
        row = _sync.users.find_one({"id": t["id"]})
        assert row["department"] == want
        assert row["department_updated_by"] == super_admin["id"]

    # 3 audit rows landed in db.department_change_audit for this tenant
    # + this actor, one per target.
    audits = list(_sync.department_change_audit.find(
        {"tenant_id": tenant_id,
         "actor_user_id": super_admin["id"]},
        {"_id": 0},
    ))
    assert len(audits) == 3
    for a in audits:
        assert a["source"] == "admin_bulk_apply"
        assert a["from_department"] is None
        assert a["to_department"] in ("pool_tech", "landscape_tech", "both")
        assert a["target_user_id"] in {t["id"] for t in techs}


# ══════════════════════════════════════════════════════════════════
# 2) Partial failure — unknown user_id yields entry in ``failed``.
# ══════════════════════════════════════════════════════════════════
def test_partial_failure_unknown_user_reports_and_partial_apply(
    tenant_id, super_admin,
):
    a = _seed_user(tenant_id, "technician")
    b = _seed_user(tenant_id, "technician")
    ghost_id = f"ghost-{uuid.uuid4().hex[:8]}"

    payload = {"applications": [
        {"user_id": a["id"], "department": "pool_tech"},
        {"user_id": ghost_id, "department": "pool_tech"},
        {"user_id": b["id"], "department": "landscape_tech"},
    ]}
    r = _post("/admin/apply-department-suggestions",
              super_admin["token"], tenant_id, payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 2
    assert len(body["failed"]) == 1
    assert body["failed"][0]["user_id"] == ghost_id
    assert body["failed"][0]["reason"] == "user_not_found"

    # Real users mutated.
    assert _sync.users.find_one({"id": a["id"]})["department"] == "pool_tech"
    assert _sync.users.find_one({"id": b["id"]})["department"] == "landscape_tech"
    # Audit rows only for the two that landed.
    audits = list(_sync.department_change_audit.find(
        {"tenant_id": tenant_id, "actor_user_id": super_admin["id"]},
        {"_id": 0},
    ))
    assert len(audits) == 2
    audit_targets = {row["target_user_id"] for row in audits}
    assert audit_targets == {a["id"], b["id"]}
    assert ghost_id not in audit_targets


# ══════════════════════════════════════════════════════════════════
# 3) Auth — non-super-admin roles are 403.
# ══════════════════════════════════════════════════════════════════
def test_admin_role_is_forbidden(tenant_id, admin):
    victim = _seed_user(tenant_id, "technician")
    payload = {"applications":
        [{"user_id": victim["id"], "department": "pool_tech"}]}
    r = _post("/admin/apply-department-suggestions",
              admin["token"], tenant_id, payload)
    assert r.status_code == 403, r.text
    # No mutation.
    assert _sync.users.find_one({"id": victim["id"]})["department"] is None
    assert _sync.department_change_audit.count_documents(
        {"tenant_id": tenant_id}) == 0


def test_technician_role_is_forbidden(tenant_id, technician):
    victim = _seed_user(tenant_id, "technician")
    payload = {"applications":
        [{"user_id": victim["id"], "department": "pool_tech"}]}
    r = _post("/admin/apply-department-suggestions",
              technician["token"], tenant_id, payload)
    assert r.status_code == 403, r.text


# ══════════════════════════════════════════════════════════════════
# 4) Empty payload — {applied:0, failed:[]} with zero writes.
# ══════════════════════════════════════════════════════════════════
def test_empty_payload_is_a_noop(tenant_id, super_admin):
    baseline_users = _sync.users.count_documents({"tenant_id": tenant_id})
    baseline_audit = _sync.department_change_audit.count_documents(
        {"tenant_id": tenant_id})

    r = _post("/admin/apply-department-suggestions",
              super_admin["token"], tenant_id, {"applications": []})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 0
    assert body["failed"] == []

    assert _sync.users.count_documents({"tenant_id": tenant_id}) \
        == baseline_users
    assert _sync.department_change_audit.count_documents(
        {"tenant_id": tenant_id}) == baseline_audit
