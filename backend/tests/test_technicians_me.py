"""Feb-2026 · ``GET /api/technicians/me`` — auth-scoped tech resolver.

Covers:
  1. Primary match via ``user_id``.
  2. Email fallback + INFO log line ``tech_resolved_via_fallback
     method=email``.
  3. Name fallback + INFO log line ``tech_resolved_via_fallback
     method=name``.
  4. No match → ``404 technician_not_found``.
  5. Cross-tenant isolation — user from tenant A cannot resolve
     tenant B's technician.
  6. Unauthenticated → 401 (shared ``get_current_user`` gate).
  7. Response shape parity with ``GET /api/technicians/{tid}``.
  8. NO auto-provisioning — miss stays a miss.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def seeded(dbc):
    """Seed:

      * Tenant A with:
        - user U_primary  → tech T_primary (linked by user_id)
        - user U_email    → tech T_email    (linked by email only)
        - user U_name     → tech T_name     (linked by name only)
        - user U_miss     → no matching tech
      * Tenant B with:
        - user U_other    → tech T_other
        The tenant-A user U_email's email matches Tenant B's
        T_other.email — but tenant isolation must prevent the
        fallback from cross-tenant resolving.
    """
    tid = f"tenant_res_{uuid.uuid4().hex[:6]}"
    tid_b = f"tenant_res_b_{uuid.uuid4().hex[:6]}"

    U_primary = f"u_primary_{uuid.uuid4().hex[:6]}"
    U_email   = f"u_email_{uuid.uuid4().hex[:6]}"
    U_name    = f"u_name_{uuid.uuid4().hex[:6]}"
    U_miss    = f"u_miss_{uuid.uuid4().hex[:6]}"
    U_other   = f"u_other_{uuid.uuid4().hex[:6]}"

    T_primary = f"t_primary_{uuid.uuid4().hex[:6]}"
    T_email   = f"t_email_{uuid.uuid4().hex[:6]}"
    T_name    = f"t_name_{uuid.uuid4().hex[:6]}"
    T_other   = f"t_other_{uuid.uuid4().hex[:6]}"

    shared_email = f"TEST_shared_{uuid.uuid4().hex[:6]}@example.com"

    dbc.tenants.insert_many([
        {"id": tid, "slug": f"res-{tid[:6]}", "name": "Resolver Test"},
        {"id": tid_b, "slug": f"res-b-{tid_b[:6]}", "name": "Resolver Other"},
    ])
    dbc.users.insert_many([
        {"id": U_primary, "tenant_id": tid, "role": "technician",
         "email": f"TEST_primary_{U_primary[:6]}@example.com",
         "name": "Primary Tech",
         "first_name": "Primary", "last_name": "Tech"},
        {"id": U_email, "tenant_id": tid, "role": "technician",
         "email": shared_email,
         "name": "Email Match",
         "first_name": "Email", "last_name": "Match"},
        {"id": U_name, "tenant_id": tid, "role": "technician",
         "email": f"TEST_namematch_{U_name[:6]}@example.com",
         "name": "Name Match Alpha",
         "first_name": "Name", "last_name": "Match Alpha"},
        {"id": U_miss, "tenant_id": tid, "role": "technician",
         "email": f"TEST_miss_{U_miss[:6]}@example.com",
         "name": "Miss User",
         "first_name": "Miss", "last_name": "User"},
        {"id": U_other, "tenant_id": tid_b, "role": "technician",
         "email": shared_email,   # same as U_email — cross-tenant
         "name": "Email Match",
         "first_name": "Email", "last_name": "Match"},
    ])
    dbc.technicians.insert_many([
        # (1) Primary — linked by user_id.
        {"id": T_primary, "tenant_id": tid, "user_id": U_primary,
         "name": "Primary Tech",
         "email": f"TEST_primary_{U_primary[:6]}@example.com",
         "active": True},
        # (2) Email-only — DELIBERATELY has NO user_id.
        {"id": T_email, "tenant_id": tid,
         "email": shared_email.upper(),   # case-insensitive test
         "name": "Some Other Name",
         "active": True},
        # (3) Name-only — no user_id AND email doesn't match.
        {"id": T_name, "tenant_id": tid,
         "email": f"TEST_wrong_{T_name[:6]}@example.com",
         "name": "name match alpha",   # case-insensitive test
         "active": True},
        # (4) Cross-tenant — must NOT be resolved by tenant A callers.
        {"id": T_other, "tenant_id": tid_b, "user_id": U_other,
         "name": "Email Match", "email": shared_email,
         "active": True},
    ])

    yield {
        "tid": tid, "tid_b": tid_b,
        "U_primary": U_primary, "U_email": U_email, "U_name": U_name,
        "U_miss": U_miss, "U_other": U_other,
        "T_primary": T_primary, "T_email": T_email, "T_name": T_name,
        "T_other": T_other,
        "shared_email": shared_email,
    }

    dbc.tenants.delete_many(
        {"id": {"$in": [tid, tid_b]}},
    )
    dbc.users.delete_many(
        {"id": {"$in": [U_primary, U_email, U_name, U_miss, U_other]}},
    )
    dbc.technicians.delete_many(
        {"id": {"$in": [T_primary, T_email, T_name, T_other]}},
    )


def _call_me(user_doc: Dict[str, Any] | None,
              tenant_id: str | None):
    """Fire ``GET /api/technicians/me`` with a
    ``get_current_user`` + ``get_current_tenant`` override.

    When ``user_doc`` is None, the endpoint runs WITHOUT the override
    which triggers the real ``get_current_user`` — expected to 401
    against an anonymous httpx client.
    """
    async def _drive(_db):
        from utils import get_current_user as _dep_user
        from routers.tenants import get_current_tenant as _dep_tenant
        app = _get_app()
        if user_doc is not None:
            app.dependency_overrides[_dep_user] = lambda: user_doc
        if tenant_id is not None:
            app.dependency_overrides[_dep_tenant] = lambda: {
                "id": tenant_id, "slug": "test", "name": "Test",
            }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                resp = await ac.get("/api/technicians/me")
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                return resp.status_code, data
        finally:
            app.dependency_overrides.pop(_dep_user, None)
            app.dependency_overrides.pop(_dep_tenant, None)
    return run_test(_drive)


# ═════════════════════════════════════════════════════════════════════
# Primary + fallbacks
# ═════════════════════════════════════════════════════════════════════
def test_primary_match_via_user_id(seeded):
    user = {"id": seeded["U_primary"], "role": "technician",
             "email": f"TEST_primary_{seeded['U_primary'][:6]}@example.com",
             "first_name": "Primary", "last_name": "Tech",
             "tenant_id": seeded["tid"]}
    code, body = _call_me(user, seeded["tid"])
    assert code == 200, body
    assert body["id"] == seeded["T_primary"]
    assert body["_resolved_via"] == "user_id"
    assert "jobs" in body   # shape parity with /technicians/{tid}
    assert isinstance(body["jobs"], list)


def test_email_fallback_case_insensitive(seeded, caplog):
    user = {"id": seeded["U_email"], "role": "technician",
             "email": seeded["shared_email"],
             "first_name": "Email", "last_name": "Match",
             "tenant_id": seeded["tid"]}
    with caplog.at_level(logging.INFO):
        code, body = _call_me(user, seeded["tid"])
    assert code == 200, body
    assert body["id"] == seeded["T_email"]
    assert body["_resolved_via"] == "email"
    # Info log line captured.
    fallback_logs = [r.message for r in caplog.records
                      if "tech_resolved_via_fallback" in r.message]
    assert any("method=email" in m for m in fallback_logs), (
        f"expected an INFO log with method=email, got: {fallback_logs}"
    )


def test_name_fallback_case_insensitive(seeded, caplog):
    user = {"id": seeded["U_name"], "role": "technician",
             "email": f"TEST_namematch_{seeded['U_name'][:6]}@example.com",
             "first_name": "Name", "last_name": "Match Alpha",
             "tenant_id": seeded["tid"]}
    with caplog.at_level(logging.INFO):
        code, body = _call_me(user, seeded["tid"])
    assert code == 200, body
    assert body["id"] == seeded["T_name"]
    assert body["_resolved_via"] == "name"
    fallback_logs = [r.message for r in caplog.records
                      if "tech_resolved_via_fallback" in r.message]
    assert any("method=name" in m for m in fallback_logs)


def test_no_match_returns_404_and_does_not_auto_provision(seeded, dbc):
    pre_count = dbc.technicians.count_documents({"tenant_id": seeded["tid"]})
    user = {"id": seeded["U_miss"], "role": "technician",
             "email": f"TEST_miss_{seeded['U_miss'][:6]}@example.com",
             "first_name": "Miss", "last_name": "User",
             "tenant_id": seeded["tid"]}
    code, body = _call_me(user, seeded["tid"])
    assert code == 404, body
    assert body.get("detail") == "technician_not_found"
    # No auto-provisioned row.
    post_count = dbc.technicians.count_documents({"tenant_id": seeded["tid"]})
    assert post_count == pre_count


def test_cross_tenant_user_cannot_resolve_other_tenants_tech(seeded):
    # U_email (tenant A) shares an email with U_other's tenant B tech.
    # The tenant-A caller MUST NOT see the tenant-B tech.
    user_a = {"id": seeded["U_email"], "role": "technician",
                "email": seeded["shared_email"],
                "first_name": "Email", "last_name": "Match",
                "tenant_id": seeded["tid"]}
    code, body = _call_me(user_a, seeded["tid"])
    assert code == 200, body
    # Must resolve to tenant A's row, NOT tenant B's.
    assert body["id"] == seeded["T_email"]
    assert body["id"] != seeded["T_other"]
    assert body["tenant_id"] == seeded["tid"]


def test_unauthenticated_returns_401(seeded):
    # No dependency override on ``get_current_user`` → the real gate
    # runs against the anonymous httpx client which has no
    # ``Authorization`` header → 401.
    code, _body = _call_me(user_doc=None, tenant_id=seeded["tid"])
    assert code == 401


# ═════════════════════════════════════════════════════════════════════
# Response-shape parity with GET /api/technicians/{tid}
# ═════════════════════════════════════════════════════════════════════
def test_shape_parity_with_technician_detail(seeded, dbc):
    """Both endpoints must return the same field set so the mobile
    normaliser can be shared."""
    user = {"id": seeded["U_primary"], "role": "admin",
             "email": f"TEST_primary_{seeded['U_primary'][:6]}@example.com",
             "first_name": "Primary", "last_name": "Tech",
             "tenant_id": seeded["tid"]}
    code_me, body_me = _call_me(user, seeded["tid"])
    assert code_me == 200, body_me

    async def _drive(_db):
        from utils import get_current_user as _dep_user
        from routers.tenants import get_current_tenant as _dep_tenant
        app = _get_app()
        app.dependency_overrides[_dep_user] = lambda: user
        app.dependency_overrides[_dep_tenant] = lambda: {
            "id": seeded["tid"], "slug": "test", "name": "Test",
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                resp = await ac.get(
                    f"/api/technicians/{seeded['T_primary']}",
                )
                return resp.status_code, resp.json()
        finally:
            app.dependency_overrides.pop(_dep_user, None)
            app.dependency_overrides.pop(_dep_tenant, None)
    code_det, body_det = run_test(_drive)
    assert code_det == 200, body_det
    # Every field the detail endpoint emits (except ``_resolved_via``,
    # which is /me-only metadata) must be present in the /me response
    # with the SAME VALUE.
    for k, v in body_det.items():
        assert k in body_me, f"/me missing field ``{k}`` from detail"
        assert body_me[k] == v, (
            f"field {k!r} differs — /me={body_me[k]!r} vs /detail={v!r}"
        )
    # /me adds ``_resolved_via`` — detail must not carry it.
    assert body_me["_resolved_via"] == "user_id"
    assert "_resolved_via" not in body_det
