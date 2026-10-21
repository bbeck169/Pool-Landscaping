"""TD-search-technicians-bucket · Feb-2026.

Covers the new ``technicians`` bucket on ``GET /api/search``:
  * hit by name / email / phone (digit-normalized).
  * RBAC gate holds — admin passes, field tech 403s.
  * Inactive / soft-deleted / @t.local artifact exclusion.
  * Tenant isolation.
  * All 6 ASSIGNABLE_ROLES surface; privileged roles don't.
  * ``entities=technicians`` narrows the response.
  * ``limit`` cap honored.
  * Empty query → empty bucket.
  * Hit shape: ``{id, primary=name, secondary=role · phone}``.
"""
from __future__ import annotations

import os
import uuid
from typing import Dict, List

import httpx
import pytest
from dotenv import dotenv_values
from tests._shared_mongo import shared_db as _shared_db


BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None


def _mk_tenant(prefix: str = "TEST_gstech") -> str:
    tid = f"{prefix}_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid,
        "slug": f"gstech-{uuid.uuid4().hex[:8]}",
        "name": "GSTech Tenant", "active": True,
    })
    return tid


def _mk_user(tid: str, role: str = "admin", *, email: str | None = None,
             first_name: str = "", last_name: str = "",
             phone: str | None = None,
             active: bool | None = None) -> dict:
    from utils import hash_password
    _email = email or f"gstech-{role}-{uuid.uuid4().hex[:8]}@example.com"
    doc: dict = {
        "id": f"TEST_gstech_user_{uuid.uuid4().hex}",
        "email": _email, "role": role,
        "password_hash": hash_password("password123"),
        "tenant_id": tid,
        "first_name": first_name, "last_name": last_name,
        "phone": phone, "failed_login_attempts": 0,
    }
    if active is not None:
        doc["active"] = active
    _sync.users.insert_one(doc)
    return doc


def _mk_tech_row(tid: str, *, name: str, email: str | None = None,
                  phone: str | None = None, user_id: str | None = None,
                  deleted_at: str | None = None) -> dict:
    doc: dict = {
        "id": f"TEST_gstech_tech_{uuid.uuid4().hex}",
        "tenant_id": tid, "name": name,
        "email": email, "phone": phone, "user_id": user_id,
        "active": True,
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    _sync.technicians.insert_one(doc)
    return doc


def _login(email: str) -> str:
    with httpx.Client(base_url=BASE, timeout=30) as c:
        r = c.post("/api/auth/login",
                   json={"email": email, "password": "password123"})
        r.raise_for_status()
        return r.json()["access_token"]


@pytest.fixture
def admin_ctx():
    tid = _mk_tenant()
    admin = _mk_user(tid, role="admin")
    yield {"tid": tid, "token": _login(admin["email"])}


@pytest.fixture
def tech_ctx():
    tid = _mk_tenant("TEST_gstech_fieldtech")
    u = _mk_user(tid, role="technician",
                  first_name="Field", last_name="Caller")
    yield {"tid": tid, "token": _login(u["email"])}


def _search(token: str, **params) -> Dict[str, List[dict]]:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.get("/api/search", params=params,
                   headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()


# ──────────────────────────────────────────────────────────────────
# Match semantics
# ──────────────────────────────────────────────────────────────────
def test_name_substring_hit(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician", first_name="Miguel", last_name="Rivera")
    out = _search(admin_ctx["token"], q="Rivera",
                   entities="technicians", limit=5)
    bucket = out.get("technicians", [])
    assert len(bucket) == 1
    assert bucket[0]["primary"] == "Miguel Rivera"
    # Hit shape invariant.
    assert set(bucket[0].keys()) == {"id", "primary", "secondary"}


def test_name_case_insensitive(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="landscape_tech",
              first_name="Lana", last_name="Vega")
    out = _search(admin_ctx["token"], q="VEGA",
                   entities="technicians", limit=5)
    assert len(out["technicians"]) == 1


def test_email_substring_hit(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              email=f"findme-{uuid.uuid4().hex[:6]}@example.com",
              first_name="Em", last_name="Found")
    out = _search(admin_ctx["token"], q="findme",
                   entities="technicians", limit=5)
    assert len(out["technicians"]) == 1
    assert out["technicians"][0]["primary"] == "Em Found"


def test_phone_digit_normalized_hit(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              first_name="Phone", last_name="Normal",
              phone="(555) 123-4567")
    out = _search(admin_ctx["token"], q="5551234",
                   entities="technicians", limit=5)
    assert len(out["technicians"]) == 1
    # Secondary = "technician · (555) 123-4567"
    assert "(555) 123-4567" in out["technicians"][0]["secondary"]


def test_phone_minimum_three_digits(admin_ctx):
    """A 2-digit needle must NOT phone-match (prevents broad-brush regex)."""
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              first_name="Short", last_name="Query",
              phone="(555) 123-4567")
    out = _search(admin_ctx["token"], q="55",
                   entities="technicians", limit=5)
    # The digit "55" is only 2 chars so the phone-digit path is a
    # no-op; name/email also don't contain "55". Zero hits expected.
    assert out["technicians"] == []


# ──────────────────────────────────────────────────────────────────
# RBAC
# ──────────────────────────────────────────────────────────────────
def test_field_tech_gets_403(tech_ctx):
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.get("/api/search",
                   params={"q": "anyone", "entities": "technicians"},
                   headers={"Authorization": f"Bearer {tech_ctx['token']}"})
    assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────
# Exclusions
# ──────────────────────────────────────────────────────────────────
def test_soft_deleted_tech_row_excluded(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_tech_row(tid, name="Gone Away",
                  deleted_at="2026-02-01T00:00:00+00:00")
    out = _search(admin_ctx["token"], q="Gone",
                   entities="technicians", limit=5)
    assert out["technicians"] == []


def test_inactive_user_excluded(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              first_name="Inactive", last_name="User", active=False)
    out = _search(admin_ctx["token"], q="Inactive",
                   entities="technicians", limit=5)
    assert out["technicians"] == []


def test_t_local_migration_artifacts_excluded(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              email=f"lastowner-{uuid.uuid4().hex[:6]}@t.local",
              first_name="Owner", last_name="Placeholder")
    out = _search(admin_ctx["token"], q="Owner",
                   entities="technicians", limit=5)
    assert out["technicians"] == []


def test_admin_role_excluded(admin_ctx):
    """Admin users must NOT appear in the technicians bucket."""
    tid = admin_ctx["tid"]
    _mk_user(tid, role="admin",
              first_name="Admin", last_name="Rodriguez")
    out = _search(admin_ctx["token"], q="Rodriguez",
                   entities="technicians", limit=5)
    assert out["technicians"] == []


# ──────────────────────────────────────────────────────────────────
# Tenant isolation
# ──────────────────────────────────────────────────────────────────
def test_tenant_isolation(admin_ctx):
    other_tid = _mk_tenant("TEST_gstech_other")
    _mk_user(other_tid, role="technician",
              first_name="Other", last_name="TenantTech")
    out = _search(admin_ctx["token"], q="TenantTech",
                   entities="technicians", limit=5)
    assert out["technicians"] == []


# ──────────────────────────────────────────────────────────────────
# Role coverage
# ──────────────────────────────────────────────────────────────────
def test_all_six_assignable_roles_surface(admin_ctx):
    """All 6 ASSIGNABLE_ROLES hit the bucket."""
    tid = admin_ctx["tid"]
    needle = f"RoleCov{uuid.uuid4().hex[:4]}"
    for role in ("technician", "tech", "landscaper",
                  "landscape_tech", "pool_tech", "tech_both"):
        _mk_user(tid, role=role,
                  first_name=needle, last_name=role)
    out = _search(admin_ctx["token"], q=needle,
                   entities="technicians", limit=25)
    assert len(out["technicians"]) == 6


# ──────────────────────────────────────────────────────────────────
# Response shape + control flow
# ──────────────────────────────────────────────────────────────────
def test_entities_filter_narrows_response(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              first_name="Narrow", last_name="Scope")
    out = _search(admin_ctx["token"], q="Narrow",
                   entities="technicians", limit=5)
    assert list(out.keys()) == ["technicians"]


def test_limit_caps_bucket(admin_ctx):
    tid = admin_ctx["tid"]
    marker = f"CapM{uuid.uuid4().hex[:4]}"
    for i in range(7):
        _mk_user(tid, role="technician",
                  first_name=marker, last_name=f"Z{i}")
    out = _search(admin_ctx["token"], q=marker,
                   entities="technicians", limit=3)
    assert len(out["technicians"]) == 3


def test_empty_query_short_circuits(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="technician",
              first_name="Should", last_name="Hide")
    out = _search(admin_ctx["token"], q="",
                   entities="technicians", limit=5)
    assert out == {"technicians": []}


def test_secondary_role_and_phone_composed(admin_ctx):
    tid = admin_ctx["tid"]
    _mk_user(tid, role="pool_tech",
              first_name="Sec", last_name="Shape",
              phone="(602) 555-0100")
    out = _search(admin_ctx["token"], q="Sec Shape",
                   entities="technicians", limit=5)
    assert len(out["technicians"]) == 1
    assert out["technicians"][0]["secondary"] == "pool_tech · (602) 555-0100"
