"""Phase H4 · Feb-2026 — /api/customers ?waitlisted filter tests.

Waitlist cohort data model (audit confirmed):
    * ``db.customers.waitlisted``: bool field toggled by the
      ``add_waitlist`` / ``remove_waitlist`` bulk actions in
      ``routers/customers.py`` (line 742). No schema change in H4 —
      the tab layers on top of the existing predicate.

Contract locked here:
    * ``?waitlisted=true``   → only rows with ``waitlisted == True``
    * ``?waitlisted=false``  → only rows with ``waitlisted == False``
    * omitted / ``None``     → no filter (rows with the field absent
                                 stay visible)
    * ``?count_only=true``   → compact ``{count: N}`` still honors it
    * Composes as intersection with ``is_active`` / ``is_muted`` /
      ``portal_status`` / search / tenant scope so the fifth cohort
      tab stacks cleanly with the G4a portal filter.
"""
from __future__ import annotations

import uuid

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


async def _seed_four(db, tid, prefix):
    """(W) waitlisted + active
       (N) not waitlisted (explicit false) + active
       (M) waitlisted + muted (waitlist is orthogonal to muted)
       (A) neither field for waitlisted — absent → must NOT match
           ``waitlisted=true`` and MUST NOT be treated as false
           implicitly for the true predicate."""
    docs = [
        {"id": f"{prefix}W", "tenant_id": tid, "name": f"{prefix}W_waitlisted",
         "is_active": True, "waitlisted": True},
        {"id": f"{prefix}N", "tenant_id": tid, "name": f"{prefix}N_not_wl",
         "is_active": True, "waitlisted": False},
        {"id": f"{prefix}M", "tenant_id": tid, "name": f"{prefix}M_wl_muted",
         "is_active": False, "is_muted": True, "waitlisted": True},
        {"id": f"{prefix}A", "tenant_id": tid, "name": f"{prefix}A_absent",
         "is_active": True},  # waitlisted field absent
    ]
    await db.customers.insert_many(docs)


def test_h4_waitlisted_true_returns_only_waitlisted_rows():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_H4_T_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_four(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                waitlisted=True, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            # W + M both carry ``waitlisted=True``; N (explicit False)
            # and A (absent) must be excluded.
            assert names == {
                f"{prefix}W_waitlisted",
                f"{prefix}M_wl_muted",
            }, f"expected W+M; got {sorted(names)}"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h4_waitlisted_omitted_returns_every_row():
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_H4_O_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_four(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                waitlisted=None, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert len(names) == 4, (
                f"waitlisted=None must not filter; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h4_count_only_true_returns_compact_envelope():
    """The Waitlist tab badge fetches counts via
    ``count_only=true``. Contract: shape stays a bare ``{count: N}``
    dict — the paginated envelope is only returned when the caller
    supplies ``page``/``page_size`` AND does not supply ``count_only``.
    """
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_H4_C_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _seed_four(db, tid, prefix)
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                waitlisted=True, count_only=True,
                search=prefix, tags=[],
            )
            # Compact envelope, N == 2 (W + M).
            assert isinstance(res, dict), type(res)
            assert res.get("count") == 2, res
            assert "items" not in res, (
                "count_only responses must not carry ``items``"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h4_waitlist_stacks_with_portal_status_as_intersection():
    """H4 × G4a intersection contract: Waitlist ∩ Not-Activated must
    return only rows that are BOTH waitlisted AND lacking a portal
    login. This is the actual product driver — ops teams triage
    waitlisted leads that haven't gotten portal access yet."""
    from routers.customers import list_customers

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "TEST_H4_X_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # W1: waitlisted + not activated  → should appear
        # W2: waitlisted + activated      → excluded (portal filter)
        # N : not waitlisted + not activated → excluded (waitlist filter)
        await db.customers.insert_many([
            {"id": f"{prefix}W1", "tenant_id": tid, "name": f"{prefix}W1",
             "is_active": True, "waitlisted": True},
            {"id": f"{prefix}W2", "tenant_id": tid, "name": f"{prefix}W2",
             "is_active": True, "waitlisted": True, "has_login": True},
            {"id": f"{prefix}N", "tenant_id": tid, "name": f"{prefix}N",
             "is_active": True, "waitlisted": False},
        ])
        try:
            res = await list_customers(
                user=admin, tenant={"id": tid},
                page=1, page_size=500,
                waitlisted=True, portal_status="not_activated",
                search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}W1"}, (
                f"H4×G4a intersection failed; got {sorted(names)}"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


def test_h4_tenant_scoping_prevents_leak():
    from routers.customers import list_customers

    async def _go(db):
        tid_a, admin_a = await _seed(db)
        tid_b = f"h4-alt-tenant-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({
            "id": tid_b, "slug": tid_b, "name": "H4 Alt Tenant",
        })
        prefix = "TEST_H4_ISO_" + uuid.uuid4().hex[:6] + "_"
        try:
            await db.customers.insert_many([
                {"id": f"{prefix}Aw", "tenant_id": tid_a,
                 "name": f"{prefix}Aw_waitlisted_tid_a",
                 "is_active": True, "waitlisted": True},
                {"id": f"{prefix}Bw", "tenant_id": tid_b,
                 "name": f"{prefix}Bw_waitlisted_tid_b",
                 "is_active": True, "waitlisted": True},
            ])
            res = await list_customers(
                user=admin_a, tenant={"id": tid_a},
                page=1, page_size=500,
                waitlisted=True, search=prefix, tags=[],
            )
            names = {c["name"] for c in res["items"]}
            assert names == {f"{prefix}Aw_waitlisted_tid_a"}, (
                f"tenant leak detected; got {sorted(names)}"
            )
        finally:
            await db.customers.delete_many({
                "name": {"$regex": f"^{prefix}"},
            })
            await db.tenants.delete_one({"id": tid_b})

    run_test(_go)
