"""Phase P23.1 · Feb-2026 — Super-admin cross-tenant technicians diagnostic.

Locks the following contracts of the new
``GET /api/admin/technicians/all-tenants`` endpoint:

  1. **Super-admin** → 200 with technicians across ALL tenants and a
     ``tenant_id`` field on each row.
  2. **Regular admin** → 403 "Super admin access required".
  3. **Technician** → 403 "Super admin access required".
  4. **Response shape** — top level is
     ``{"count": <int>, "technicians": [<row>, ...]}``; each row has
     ``id``, ``name``, ``tenant_id`` at minimum.
  5. **Ordering** — rows are sorted by ``(tenant_id, name)`` so the
     tester sees techs grouped by tenant.
  6. **Isolation guardrail** — the endpoint does NOT change the
     behavior of ``GET /api/technicians`` (tenant-scoped list stays
     tenant-scoped). Verified by direct comparison: a technician
     row visible to super-admin under tenant X does NOT appear in a
     tenant Y admin's list.

Direct-call harness (mirrors ``test_p23_technician_soft_delete.py``).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


TAG = "TEST_P23_1_XT_"


async def _cleanup(db):
    await db.technicians.delete_many({"id": {"$regex": f"^{TAG}"}})
    await db.tenants.delete_many({"id": {"$regex": f"^{TAG}"}})


async def _seed_tenant(db, tid):
    await db.tenants.insert_one({
        "id": tid,
        "name": f"P23.1 XT Tenant {tid[-4:]}",
        "slug": f"p23-1-xt-{tid[-4:]}".lower(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def _seed_tech(db, tid, tech_id, name):
    await db.technicians.insert_one({
        "id": tech_id, "tenant_id": tid, "name": name,
        "department": "pool_tech",
        "email": f"{tech_id[-4:]}@p23-1-xt.test",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def _super_admin():
    return {"id": "p23-1-super", "role": "super_admin",
            "email": "super@p23-1-xt.test"}


def _admin():
    return {"id": "p23-1-admin", "role": "admin",
            "email": "admin@p23-1-xt.test"}


def _technician():
    return {"id": "p23-1-tech", "role": "technician",
            "email": "tech@p23-1-xt.test"}


# ── 1) Super admin → 200, cross-tenant rows, tenant_id present ────


def test_p23_1_super_admin_lists_technicians_across_all_tenants():
    async def _go(db):
        await _cleanup(db)
        tenant_x = f"{TAG}TENANT_X_{uuid.uuid4().hex[:6]}"
        tenant_y = f"{TAG}TENANT_Y_{uuid.uuid4().hex[:6]}"
        await _seed_tenant(db, tenant_x)
        await _seed_tenant(db, tenant_y)
        tech_x1 = f"{TAG}TECH_X1_{uuid.uuid4().hex[:6]}"
        tech_y1 = f"{TAG}TECH_Y1_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tenant_x, tech_x1, "Alpha X")
        await _seed_tech(db, tenant_y, tech_y1, "Bravo Y")

        try:
            from routers.technicians import list_technicians_all_tenants
            res = await list_technicians_all_tenants(user=_super_admin())

            assert isinstance(res, dict)
            assert "count" in res and "technicians" in res
            assert res["count"] >= 2

            # Both seeded rows must be present with tenant_id.
            ids = {t["id"] for t in res["technicians"]}
            assert tech_x1 in ids
            assert tech_y1 in ids
            for t in res["technicians"]:
                if t["id"] in (tech_x1, tech_y1):
                    assert t.get("tenant_id") in (tenant_x, tenant_y)
                    assert t.get("name")

        finally:
            await _cleanup(db)

    run_test(_go)


# ── 2) Regular admin → 403 ────────────────────────────────────────


def test_p23_1_regular_admin_gets_403():
    """A regular admin's user dict MUST be rejected by
    ``require_super_admin`` — the dependency is what protects the
    endpoint; ``list_technicians_all_tenants`` accepts its return
    value as the ``user`` param."""
    async def _go(db):
        # We don't call the endpoint directly — we call the guard.
        from utils import require_super_admin
        try:
            require_super_admin(user=_admin())
            assert False, "expected 403 from admin role"
        except HTTPException as e:
            assert e.status_code == 403
            assert "super admin" in (e.detail or "").lower()

    run_test(_go)


# ── 3) Technician → 403 ───────────────────────────────────────────


def test_p23_1_technician_gets_403():
    async def _go(db):
        from utils import require_super_admin
        try:
            require_super_admin(user=_technician())
            assert False, "expected 403 from technician role"
        except HTTPException as e:
            assert e.status_code == 403

    run_test(_go)


# ── 4) Response ordering — sorted by (tenant_id, name) ────────────


def test_p23_1_all_tenants_response_sorted_by_tenant_then_name():
    async def _go(db):
        await _cleanup(db)
        # Two tenants, out-of-order names to prove the sort.
        t1 = f"{TAG}TENANT_1_{uuid.uuid4().hex[:6]}"
        t2 = f"{TAG}TENANT_2_{uuid.uuid4().hex[:6]}"
        await _seed_tenant(db, t1)
        await _seed_tenant(db, t2)
        # Sort at insertion is scrambled so the endpoint's sort has
        # something to actually do.
        await _seed_tech(db, t2, f"{TAG}Z1", "Zulu")
        await _seed_tech(db, t1, f"{TAG}A1", "Alpha")
        await _seed_tech(db, t1, f"{TAG}B1", "Bravo")
        await _seed_tech(db, t2, f"{TAG}Y1", "Yankee")

        try:
            from routers.technicians import list_technicians_all_tenants
            res = await list_technicians_all_tenants(user=_super_admin())
            rows = [t for t in res["technicians"]
                    if t.get("id", "").startswith(TAG)]
            # Group by tenant, first tenant's rows all before second's.
            tenant_ids_in_order = [t["tenant_id"] for t in rows]
            # Contiguous grouping: no interleave.
            seen = []
            for tid in tenant_ids_in_order:
                if not seen or seen[-1] != tid:
                    seen.append(tid)
            assert len(seen) == len(set(seen)), (
                f"Tenant ids not contiguously grouped: {tenant_ids_in_order}"
            )
            # Within each tenant, names are alphabetical.
            by_tenant: dict = {}
            for r in rows:
                by_tenant.setdefault(r["tenant_id"], []).append(r["name"])
            for tid, names in by_tenant.items():
                assert names == sorted(names), (
                    f"Names not alpha-sorted within tenant {tid}: {names}"
                )
        finally:
            await _cleanup(db)

    run_test(_go)


# ── 5) Isolation guardrail — tenant-scoped endpoint unchanged ─────


def test_p23_1_all_tenants_does_not_leak_into_tenant_scoped_list():
    """A tenant-A admin's ``GET /api/technicians`` MUST NOT include
    rows from tenant B, EVEN though the all-tenants endpoint now
    exists. Locks that P23.1 did not accidentally loosen tenant
    isolation on the pre-existing endpoint."""
    async def _go(db):
        await _cleanup(db)
        tenant_a = f"{TAG}TENANT_A_{uuid.uuid4().hex[:6]}"
        tenant_b = f"{TAG}TENANT_B_{uuid.uuid4().hex[:6]}"
        await _seed_tenant(db, tenant_a)
        await _seed_tenant(db, tenant_b)
        tech_a = f"{TAG}TECH_A1_{uuid.uuid4().hex[:6]}"
        tech_b = f"{TAG}TECH_B1_{uuid.uuid4().hex[:6]}"
        await _seed_tech(db, tenant_a, tech_a, "AAlpha")
        await _seed_tech(db, tenant_b, tech_b, "BBravo")

        try:
            from routers.technicians import list_technicians
            # Tenant-A admin — user dict + tenant dict shape follows
            # the existing endpoint's Depends signature.
            user = {"id": "u-a", "role": "admin", "tenant_id": tenant_a,
                    "email": "adminA@p23-1-xt.test"}
            tenant = {"id": tenant_a}
            rows = await list_technicians(user=user, tenant=tenant)
            ids = {r.get("id") for r in rows}
            assert tech_a in ids or any(
                r.get("id") == tech_a for r in rows
            ), f"Tenant-A tech should surface for tenant-A admin"
            assert tech_b not in ids, (
                f"Tenant-B tech leaked into tenant-A list: {ids}"
            )
        finally:
            await _cleanup(db)

    run_test(_go)


# ── 6) Endpoint is registered under /api ──────────────────────────


def test_p23_1_all_tenants_endpoint_registered_under_api_prefix():
    """FastAPI route registration guard — the new endpoint MUST
    appear under ``/api/admin/technicians/all-tenants`` on the
    running app instance. Guards against a router-loop regression
    where the technicians module isn't wired into ``api_router``."""
    from server import app
    paths = {r.path for r in app.routes}
    assert "/api/admin/technicians/all-tenants" in paths, (
        f"P23.1 endpoint not registered — {sorted([p for p in paths if 'admin' in p and 'tech' in p])}"
    )
