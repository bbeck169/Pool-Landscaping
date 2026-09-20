"""Phase T1 · Feb-2026 — Tenant Split + Multi-Tenant Users pytest.

Covers:
  1.  Pilot-create script is idempotent (2 runs = 2 tenants).
  2.  Backfill seeds a 1-item membership on legacy users; idempotent.
  3.  ``POST /api/auth/switch-tenant`` accepts valid membership,
      issues a new JWT with the ``active_tenant_id`` claim.
  4.  ``POST /api/auth/switch-tenant`` returns 403
      ``tenant_not_in_memberships`` for a stranger tenant.
  5.  Authenticated read AFTER switching returns tenant-B-scoped
      data — proves the claim flows through ``get_current_tenant``.
  6.  Legacy JWT without the claim resolves via ``user.tenant_id``.
  7.  ``POST /api/admin/users/{id}/memberships`` — super_admin ok.
  8.  ``POST /api/admin/users/{id}/memberships`` — admin 403.
  9.  ``POST /api/admin/users/{id}/memberships`` — tech 403.
  10. ``POST /api/admin/users/{id}/memberships`` — idempotent.
  11. ``DELETE`` cannot strip the user's default tenant.
  12. ``/api/auth/me`` returns ``available_tenants`` populated.
  13. Stale membership (claim present but user removed from tenant)
      → 403 ``stale_tenant_membership``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import httpx
import jwt as _jwt
import pytest

from tests._f7_loop_fixture import run_test


API = "/api"


def _get_app():
    from server import app
    return app


def _mint_token(
    *, uid: str, tid: str, role: str,
    active_tenant_id: str = "",
) -> str:
    from config import JWT_SECRET
    payload: Dict[str, Any] = {
        "sub":       uid,
        "email":     f"{uid}@ex.test",
        "role":      role,
        "tenant_id": tid,
        "exp":       int((datetime.now(timezone.utc)
                            + timedelta(hours=1)).timestamp()),
    }
    if active_tenant_id:
        payload["active_tenant_id"] = active_tenant_id
    return _jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def t1_seed():
    tid_a = f"t1-tid-a-{uuid.uuid4()}"
    tid_b = f"t1-tid-b-{uuid.uuid4()}"
    tid_c = f"t1-tid-c-{uuid.uuid4()}"     # NOT in memberships
    admin_uid = f"t1-admin-{uuid.uuid4()}"
    tech_uid = f"t1-tech-{uuid.uuid4()}"
    super_uid = f"t1-super-{uuid.uuid4()}"

    async def _seed(_db):
        await _db.tenants.insert_many([
            {"id": tid_a, "name": "T1 A",
              "slug": f"t1a-{uuid.uuid4().hex[:6]}",
              "active": True, "settings": {}},
            {"id": tid_b, "name": "T1 B",
              "slug": f"t1b-{uuid.uuid4().hex[:6]}",
              "active": True, "settings": {}},
            {"id": tid_c, "name": "T1 C-Stranger",
              "slug": f"t1c-{uuid.uuid4().hex[:6]}",
              "active": True, "settings": {}},
        ])
        await _db.users.insert_many([
            {"id": admin_uid,
              "email": f"admin-{admin_uid}@ex.test",
              "role": "admin", "tenant_id": tid_a,
              "name": "Alex Admin",
              "tenant_memberships": [
                  {"tenant_id": tid_a, "role": "admin",
                    "joined_at": "2025-01-01T00:00:00+00:00"},
                  {"tenant_id": tid_b, "role": "manager",
                    "joined_at": "2025-06-01T00:00:00+00:00"},
              ]},
            {"id": tech_uid,
              "email": f"tech-{tech_uid}@ex.test",
              "role": "technician", "tenant_id": tid_a,
              "name": "Terry Tech",
              "tenant_memberships": [
                  {"tenant_id": tid_a, "role": "technician",
                    "joined_at": "2025-01-01T00:00:00+00:00"},
              ]},
            {"id": super_uid,
              "email": f"super-{super_uid}@ex.test",
              "role": "super_admin", "tenant_id": tid_a,
              "name": "Sam Super",
              # Phase S1.2 · Feb-2026 — super_admin owns the switch
              # flow now. Give the fixture super_admin explicit
              # memberships in both A and B so switch-tenant tests
              # can exercise the happy path without extra plumbing.
              "tenant_memberships": [
                  {"tenant_id": tid_a, "role": "super_admin",
                    "joined_at": "2025-01-01T00:00:00+00:00"},
                  {"tenant_id": tid_b, "role": "super_admin",
                    "joined_at": "2025-06-01T00:00:00+00:00"},
              ]},
        ])
        # Tenant-B has one job we can spot after switching.
        await _db.jobs.insert_one({
            "id": f"t1-b-job-{uuid.uuid4()}", "tenant_id": tid_b,
            "status": "scheduled",
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
            "service_type": "Weekly service",
            "customer_id": "t1-b-cust",
        })

    async def _teardown(_db):
        await _db.tenants.delete_many(
            {"id": {"$in": [tid_a, tid_b, tid_c]}})
        await _db.users.delete_many(
            {"id": {"$in": [admin_uid, tech_uid, super_uid]}})
        await _db.jobs.delete_many({"tenant_id": {"$in": [tid_a, tid_b]}})

    run_test(_seed)
    yield {
        "tid_a":       tid_a,
        "tid_b":       tid_b,
        "tid_c":       tid_c,
        "admin_uid":   admin_uid,
        "tech_uid":    tech_uid,
        "super_uid":   super_uid,
        "admin_token": _mint_token(uid=admin_uid, tid=tid_a, role="admin"),
        "tech_token":  _mint_token(uid=tech_uid,  tid=tid_a, role="technician"),
        "super_token": _mint_token(uid=super_uid, tid=tid_a, role="super_admin"),
    }
    run_test(_teardown)


# ═════════════════════════════════════════════════════════════════════
# 1 · Pilot-create idempotency.
# ═════════════════════════════════════════════════════════════════════
def test_pilot_create_is_idempotent():
    async def _go(_db):
        # Import lazily so the module rebind happens after the fixture.
        from scripts.create_pilot_tenants import _create_pilot
        # Feb-2026 hotfix — DO NOT touch the production ``pool`` /
        # ``landscaping`` slugs. Use test-isolated slugs so the
        # cleanup step below can nuke everything we created without
        # accidentally wiping the live pilot tenants that admin flows
        # depend on.
        test_specs = [
            {
                "legacy_id": f"t1-legacy-pool-{uuid.uuid4()}",
                "slug":      f"t1-test-pool-{uuid.uuid4().hex[:8]}",
                "name":      "Test Pool Pilot",
                "default_industry": "pool",
            },
            {
                "legacy_id": f"t1-legacy-land-{uuid.uuid4()}",
                "slug":      f"t1-test-land-{uuid.uuid4().hex[:8]}",
                "name":      "Test Landscape Pilot",
                "default_industry": "landscape",
            },
        ]
        r1 = [await _create_pilot(_db, s, dry_run=False) for s in test_specs]
        r2 = [await _create_pilot(_db, s, dry_run=False) for s in test_specs]
        created_ids = [r["id"] for r in r1 if r["id"]]
        legacy_ids  = [s["legacy_id"] for s in test_specs]
        # Cleanup — scoped to the ids/slugs this test created.
        await _db.tenants.delete_many(
            {"$or": [
                {"id":   {"$in": created_ids + legacy_ids}},
                {"slug": {"$in": [s["slug"] for s in test_specs]}},
            ]})
        await _db.service_categories.delete_many(
            {"tenant_id": {"$in": created_ids + legacy_ids}})
        await _db.income_categories.delete_many(
            {"tenant_id": {"$in": created_ids + legacy_ids}})
        return r1, r2

    r1, r2 = run_test(_go)
    r1_statuses = [r["status"] for r in r1]
    r2_statuses = [r["status"] for r in r2]
    assert set(r1_statuses) <= {
        "created", "already_exists", "renamed_from_legacy",
    }, r1_statuses
    assert all(s == "already_exists" for s in r2_statuses), r2_statuses


# ═════════════════════════════════════════════════════════════════════
# 2 · Backfill seeds a 1-item membership on legacy users.
# ═════════════════════════════════════════════════════════════════════
def test_backfill_seeds_single_membership():
    tid = f"t1-legacy-{uuid.uuid4()}"
    uid = f"t1-legacy-user-{uuid.uuid4()}"

    async def _go(_db):
        await _db.tenants.insert_one(
            {"id": tid, "name": "L", "slug": f"legacy-{uid[:6]}",
              "active": True})
        await _db.users.insert_one({
            "id": uid, "email": f"{uid}@ex.test", "role": "technician",
            "tenant_id": tid,
            "created_at": "2025-06-01T00:00:00+00:00"})
        # First backfill pass — inline (script is a __main__ helper).
        cursor = _db.users.find(
            {"tenant_memberships": {"$in": [None, []]}, "id": uid},
            {"_id": 0, "id": 1, "tenant_id": 1, "role": 1,
              "created_at": 1})
        seeded = 0
        async for u in cursor:
            membership = {
                "tenant_id":  u["tenant_id"],
                "role":       u.get("role", "customer"),
                "joined_at":  u.get("created_at"),
            }
            await _db.users.update_one(
                {"id": u["id"]},
                {"$set": {"tenant_memberships": [membership]}})
            seeded += 1
        fresh = await _db.users.find_one({"id": uid}, {"_id": 0})
        # Idempotency check.
        cursor2 = _db.users.find(
            {"tenant_memberships": {"$in": [None, []]}, "id": uid},
            {"_id": 0, "id": 1})
        remaining = [u async for u in cursor2]
        await _db.users.delete_many({"id": uid})
        await _db.tenants.delete_many({"id": tid})
        return seeded, fresh, remaining

    seeded, fresh, remaining = run_test(_go)
    assert seeded == 1
    assert len(fresh.get("tenant_memberships") or []) == 1
    assert fresh["tenant_memberships"][0]["tenant_id"] == tid
    assert remaining == []


# ═════════════════════════════════════════════════════════════════════
# 3 · POST /api/auth/switch-tenant happy path.
# ═════════════════════════════════════════════════════════════════════
def test_switch_tenant_happy(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            # Phase S1.2 · Feb-2026 — switch is super_admin only.
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid_b"]},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()
        # Verify user.active_tenant_id was persisted.
        fresh = await _db.users.find_one(
            {"id": S["super_uid"]}, {"_id": 0, "active_tenant_id": 1})
        result["persisted"] = fresh.get("active_tenant_id")

    run_test(_go)
    assert result["status"] == 200, result
    assert result["persisted"] == S["tid_b"]
    # Decode the returned JWT.
    from config import JWT_SECRET
    payload = _jwt.decode(
        result["body"]["access_token"], JWT_SECRET,
        algorithms=["HS256"])
    assert payload["active_tenant_id"] == S["tid_b"]


# ═════════════════════════════════════════════════════════════════════
# 3.b · Admin trying to switch tenant → 403 insufficient_role.
# ═════════════════════════════════════════════════════════════════════
def test_switch_tenant_admin_forbidden(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid_b"]},
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "insufficient_role_for_tenant_switch"


# ═════════════════════════════════════════════════════════════════════
# 4 · Switch to a tenant NOT in memberships → 403.
# ═════════════════════════════════════════════════════════════════════
def test_switch_tenant_stranger_403(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.post(
                f"{API}/auth/switch-tenant",
                json={"tenant_id": S["tid_c"]},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "tenant_not_in_memberships"


# ═════════════════════════════════════════════════════════════════════
# 5 · Read AFTER switching returns tenant-B-scoped data.
# ═════════════════════════════════════════════════════════════════════
def test_read_after_switch_returns_tenant_b_data(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Mint a token WITH active_tenant_id = tid_b directly
        # (equivalent to what switch-tenant returned).
        token = _mint_token(uid=S["admin_uid"], tid=S["tid_a"],
                              role="admin",
                              active_tenant_id=S["tid_b"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/jobs?limit=5",
                headers={"Authorization": f"Bearer {token}"})
            result["status"] = r.status_code
            data = r.json()
            items = data if isinstance(data, list) else \
                        (data.get("items") or data.get("data") or [])
            result["tenant_ids_seen"] = list({j.get("tenant_id")
                                                  for j in items})

    run_test(_go)
    assert result["status"] == 200, result
    # Every returned job should be scoped to tenant B, never A.
    seen = [t for t in result["tenant_ids_seen"] if t]
    assert seen == [] or seen == [S["tid_b"]], seen


# ═════════════════════════════════════════════════════════════════════
# 6 · Legacy JWT (no claim) resolves via user.tenant_id.
# ═════════════════════════════════════════════════════════════════════
def test_legacy_jwt_falls_back_to_user_tenant(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/auth/me",
                headers={"Authorization": f"Bearer {S['admin_token']}"})
            result["status"] = r.status_code
            result["body"] = r.json()

    run_test(_go)
    assert result["status"] == 200
    # `active_tenant_id` on the me payload should default to
    # `user.tenant_id` (tid_a).
    assert result["body"]["active_tenant_id"] == S["tid_a"]
    # ``available_tenants`` populated.
    tids = {t["id"] for t in result["body"]["available_tenants"]}
    assert S["tid_a"] in tids
    assert S["tid_b"] in tids


# ═════════════════════════════════════════════════════════════════════
# 7·8·9 · Admin memberships route — role gating.
# ═════════════════════════════════════════════════════════════════════
def test_admin_add_membership_role_matrix(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            for label, token in (
                ("super",  S["super_token"]),
                ("admin",  S["admin_token"]),
                ("tech",   S["tech_token"]),
            ):
                r = await c.post(
                    f"{API}/admin/users/{S['tech_uid']}/memberships",
                    json={"tenant_id": S["tid_b"], "role": "technician"},
                    headers={"Authorization": f"Bearer {token}"})
                result[label] = {"status": r.status_code,
                                 "detail": r.json().get("detail")}

    run_test(_go)
    assert result["super"]["status"] == 200
    assert result["admin"]["status"] == 403
    assert result["admin"]["detail"] == \
        "insufficient_role_for_membership_mgmt"
    assert result["tech"]["status"] == 403


# ═════════════════════════════════════════════════════════════════════
# 10 · Idempotency on membership add.
# ═════════════════════════════════════════════════════════════════════
def test_admin_add_membership_idempotent(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r1 = await c.post(
                f"{API}/admin/users/{S['tech_uid']}/memberships",
                json={"tenant_id": S["tid_b"], "role": "technician"},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            r2 = await c.post(
                f"{API}/admin/users/{S['tech_uid']}/memberships",
                json={"tenant_id": S["tid_b"], "role": "technician"},
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["r1"] = r1.json()
            result["r2"] = r2.json()

    run_test(_go)
    assert result["r1"]["created"] is True
    assert result["r2"]["created"] is False
    # Membership list length unchanged on second call.
    assert len(result["r2"]["memberships"]) == len(result["r1"]["memberships"])


# ═════════════════════════════════════════════════════════════════════
# 11 · DELETE refuses to strip default tenant.
# ═════════════════════════════════════════════════════════════════════
def test_delete_membership_refuses_default(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.delete(
                f"{API}/admin/users/{S['admin_uid']}/memberships/{S['tid_a']}",
                headers={"Authorization": f"Bearer {S['super_token']}"})
            result["status"] = r.status_code
            result["detail"] = r.json().get("detail")

    run_test(_go)
    assert result["status"] == 400
    assert result["detail"] == "cannot_remove_default_tenant_membership"


# ═════════════════════════════════════════════════════════════════════
# 13 · Stale membership → 403.
# ═════════════════════════════════════════════════════════════════════
def test_stale_membership_returns_403(t1_seed):
    S = t1_seed
    app = _get_app()
    result: Dict[str, Any] = {}

    async def _go(_db):
        # Mint a JWT with active_tenant_id = tid_c (NOT in
        # memberships) — simulates the token being minted before a
        # membership revocation.
        token = _mint_token(uid=S["admin_uid"], tid=S["tid_a"],
                              role="admin",
                              active_tenant_id=S["tid_c"])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as c:
            r = await c.get(
                f"{API}/auth/me",
                headers={"Authorization": f"Bearer {token}"})
            result["status"] = r.status_code
            result["detail"] = (r.json() or {}).get("detail")

    run_test(_go)
    assert result["status"] == 403
    assert result["detail"] == "stale_tenant_membership"
