"""Feb-2026 · Onboarding-tile clickable ship — ``portal_invited`` filter tests.

Locks the invariants:

  1. ``portal_invited=any``  → rows whose ``has_login`` is truthy.
     Predicate matches the ``/reports/portal-onboarding-health``
     ``invited`` cohort tally exactly (chip-vs-list-vs-tile
     numerical consistency, same drift-fix pattern as Never).
  2. ``portal_invited=none`` → rows where ``has_login`` is missing,
     null, or False.
  3. Bad value → 400 ``invalid_portal_invited``.
  4. ``count_only=true`` variant returns the count of matched rows.
  5. Intersection with ``first_access=never`` isolates the
     chase-stalled-invites audience (invited AND never-signed-in).
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1})
    return tenant["id"], admin


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                        "name": {"$regex": f"^{prefix}"}})


async def _seed_three_customers(db, tid, prefix):
    """
      (A) invited & never signed in — chase audience.
      (B) invited & has signed in.
      (C) never invited.
    """
    cid_a = f"{prefix}A"
    cid_b = f"{prefix}B"
    cid_c = f"{prefix}C"
    await db.customers.insert_many([
        {"id": cid_a, "tenant_id": tid, "name": f"{prefix}A_stalled",
         "is_active": True, "has_login": True,
         # portal_first_login_at intentionally missing
         "email": f"{prefix}a@example.com"},
        {"id": cid_b, "tenant_id": tid, "name": f"{prefix}B_signed_in",
         "is_active": True, "has_login": True,
         "portal_first_login_at": "2026-01-01T00:00:00+00:00",
         "email": f"{prefix}b@example.com"},
        {"id": cid_c, "tenant_id": tid, "name": f"{prefix}C_uninvited",
         "is_active": True,  # has_login absent, portal_first_login_at absent
         "email": f"{prefix}c@example.com"},
    ])
    return cid_a, cid_b, cid_c


def test_portal_invited_any_returns_only_invited_rows():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_PI_ANY_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                portal_invited="any", search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}A_stalled", f"{prefix}B_signed_in"}, (
                f"expected A+B; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_portal_invited_none_returns_only_uninvited_rows():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_PI_NONE_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                portal_invited="none", search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}C_uninvited"}, (
                f"expected only C; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_portal_invited_bad_value_returns_400():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        with pytest.raises(HTTPException) as exc:
            await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=10,
                portal_invited="bogus", tags=[],
            )
        assert exc.value.status_code == 400
        detail = exc.value.detail
        if isinstance(detail, dict):
            assert detail.get("detail") == "invalid_portal_invited"

    run_test(_go)


def test_portal_invited_count_only_returns_count():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_PI_CNT_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=1,
                portal_invited="any", search=prefix, tags=[],
                count_only=True,
            )
            # count_only=True returns ``{"count": N}``.
            total = (res.get("count")
                     if isinstance(res, dict) else int(res))
            assert total == 2, f"expected 2 invited rows; got {total}"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_intersection_isolates_chase_audience():
    """The chase-stalled-invites modal queries with
    ``portal_invited=any&first_access=never`` — assert the
    intersection returns ONLY invited-and-never-signed-in
    customers (row A), NOT the signed-in invited row (B) or the
    uninvited row (C)."""
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_PI_CHASE_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_three_customers(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=100,
                portal_invited="any", first_access="never",
                search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}A_stalled"}, (
                f"expected only A (invited+never); got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
