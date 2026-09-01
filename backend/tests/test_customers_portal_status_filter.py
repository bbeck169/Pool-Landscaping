"""Phase G4a · Feb-2026 — /api/customers ?portal_status filter tests.

Portal-activation data model (audit confirmed):
    * ``db.users``: rows with ``role="customer"``, ``customer_id``,
      ``password_hash``, ``active`` — created by
      ``POST /customers/{cid}/portal-invite`` via
      ``routers.portal_admin._upsert_customer_user``.
    * ``db.customers.has_login``: bool denorm set to ``True`` on
      invite, ``False`` on ``portal-revoke``.  The filter uses THIS
      denorm for O(index) perf.

Contract:
    * ``?portal_status=activated``     → has_login == True
    * ``?portal_status=not_activated`` → has_login missing / null / False
    * ``?portal_status=all`` or omit   → no filter
    * unknown value                    → 400 invalid_portal_status
    * combines with ``is_active`` and search / tenant scope
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                        "name": {"$regex": f"^{prefix}"}})
    await db.users.delete_many({"tenant_id": tid, "role": "customer",
                                    "email": {"$regex": f"^{prefix}"}})


async def _seed_three_customers(db, tid, prefix):
    """(A) has portal user with password + has_login=True
       (B) has portal user with EMPTY password_hash + has_login=False
       (C) no portal user at all + no has_login field."""
    cid_a = f"{prefix}A"
    cid_b = f"{prefix}B"
    cid_c = f"{prefix}C"
    await db.customers.insert_many([
        {"id": cid_a, "tenant_id": tid, "name": f"{prefix}A_activated",
         "is_active": True, "has_login": True,
         "email": f"{prefix}a@example.com"},
        {"id": cid_b, "tenant_id": tid, "name": f"{prefix}B_invited_no_pw",
         "is_active": True, "has_login": False,
         "email": f"{prefix}b@example.com"},
        {"id": cid_c, "tenant_id": tid, "name": f"{prefix}C_never_invited",
         "is_active": True,  # note: has_login intentionally missing.
         "email": f"{prefix}c@example.com"},
    ])
    # Users table mirroring — A has a real password, B has none.
    await db.users.insert_many([
        {"id": f"{prefix}Auser", "tenant_id": tid, "role": "customer",
         "customer_id": cid_a, "email": f"{prefix}a@example.com",
         "password_hash": "$2b$12$abcdefghijklmnopqrstuv",
         "active": True},
        {"id": f"{prefix}Buser", "tenant_id": tid, "role": "customer",
         "customer_id": cid_b, "email": f"{prefix}b@example.com",
         "password_hash": "", "active": False},
    ])
    return cid_a, cid_b, cid_c


def test_g4a_activated_returns_only_customers_with_portal_login():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_G4A_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                portal_status="activated", search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}A_activated"}, (
                f"expected only the A row; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_g4a_not_activated_returns_the_other_two():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_G4A_N_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                portal_status="not_activated", search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {
                f"{prefix}B_invited_no_pw",
                f"{prefix}C_never_invited",
            }, f"expected B+C only; got {sorted(names)}"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_g4a_all_or_omit_returns_every_row():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_G4A_ALL_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            for ps in ("all", None):
                res = await list_customers(
                    user=admin, tenant={"id": tid},
                    page=1, page_size=500,
                    portal_status=ps, search=prefix, tags=[],
                )
                names = {c["name"] for c in res["items"]}
                assert len(names) == 3, (
                    f"portal_status={ps!r} — expected all 3 rows, "
                    f"got {sorted(names)}"
                )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_g4a_composes_with_is_active_intersection():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_G4A_X_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # A (activated + active), B (not_activated + INACTIVE),
        # C (activated + INACTIVE), D (not_activated + active)
        await db.customers.insert_many([
            {"id": f"{prefix}A", "tenant_id": tid, "name": f"{prefix}A",
             "is_active": True, "has_login": True},
            {"id": f"{prefix}B", "tenant_id": tid, "name": f"{prefix}B",
             "is_active": False, "has_login": False},
            {"id": f"{prefix}C", "tenant_id": tid, "name": f"{prefix}C",
             "is_active": False, "has_login": True},
            {"id": f"{prefix}D", "tenant_id": tid, "name": f"{prefix}D",
             "is_active": True},  # has_login absent
        ])
        try:
            # is_active=True AND portal_status=activated → A only
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                is_active=True, portal_status="activated",
                search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}A"}, (
                f"intersection failed; got {sorted(names)}"
            )

            # is_active=False AND portal_status=not_activated → B only
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                is_active=False, portal_status="not_activated",
                search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}B"}, (
                f"intersection failed; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_g4a_tenant_scoping_prevents_leak():
    from routers.customers import list_customers

    async def _go(db):
        tid_a, admin_a = await _seed(db)
        # Seed a second real tenant if not present (safe idempotent).
        tid_b = f"g4a-alt-tenant-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({
            "id": tid_b, "slug": tid_b, "name": "G4A Alt Tenant",
        })
        admin_b = {"id": f"{tid_b}-admin", "role": "admin",
                     "tenant_id": tid_b}

        prefix = "TEST_G4A_ISO_" + uuid.uuid4().hex[:6] + "_"
        try:
            await db.customers.insert_many([
                {"id": f"{prefix}A_activated_tid_a",
                 "tenant_id": tid_a, "name": f"{prefix}A_activated_tid_a",
                 "is_active": True, "has_login": True},
                {"id": f"{prefix}B_activated_tid_b",
                 "tenant_id": tid_b, "name": f"{prefix}B_activated_tid_b",
                 "is_active": True, "has_login": True},
            ])
            # Tenant A's list must not surface tenant B's activated row.
            res = await list_customers(
                user=admin_a, tenant={"id": tid_a},
                page=1, page_size=500,
                portal_status="activated", search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}A_activated_tid_a"}, (
                f"tenant leak detected; got {sorted(names)}"
            )
        finally:
            await db.customers.delete_many({
                "name": {"$regex": f"^{prefix}"},
            })
            await db.tenants.delete_one({"id": tid_b})

    run_test(_go)


def test_g4a_rejects_bogus_portal_status_value():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        with pytest.raises(HTTPException) as ei:
            await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                portal_status="maybe", search="TEST_G4A_400", tags=[],
            )
        assert ei.value.status_code == 400
        det = ei.value.detail
        assert isinstance(det, dict)
        assert det.get("detail") == "invalid_portal_status"
        assert det.get("portal_status") == "maybe"

    run_test(_go)


def test_g4a_rbac_customer_role_blocked_from_list_endpoint():
    """Defense-in-depth: the customer-role user should be rejected by
    the existing endpoint gate BEFORE the portal_status filter is
    inspected. This mirrors the F3.5 test pattern — locks the
    invariant that customers can never enumerate customers, with or
    without our new kwarg."""
    from routers.customers import list_customers

    async def _go(db):
        tid, _ = await _seed(db)
        cust_role = {"id": "test-g4a-customer", "role": "customer",
                        "tenant_id": tid, "customer_id": "some-cid"}
        with pytest.raises(HTTPException) as ei:
            await list_customers(
                user=cust_role, tenant={"id": tid},
                page=1, page_size=500,
                portal_status="activated", tags=[],
            )
        assert ei.value.status_code == 403

    run_test(_go)
