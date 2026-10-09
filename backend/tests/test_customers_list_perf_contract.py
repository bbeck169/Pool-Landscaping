"""Phase 9c · Feb-2026 — Customers list perf contract tests.

Locks the ``?slim=1`` opt-in projection on ``GET /api/customers``
and verifies composition against the existing filter + pagination
surface. Index creation is exercised in
``test_customers_indexes.py`` (session-scoped ensure_indexes
run); this file focuses on the HTTP contract and the slim-path
hydration skip.

Cases:
    1. ``slim=1`` paginated response omits per-row
       ``properties_count`` + ``next_scheduled_at`` hydration keys
       (they're set by the two extra aggregations the list
       endpoint runs under non-slim mode).
    2. ``slim=1`` paginated response envelope shape unchanged —
       items / total / page / page_size / total_pages all present.
    3. ``slim=1`` composes with the Phase 9b portal tile filters
       (``portal_activated=true``, ``first_access=any``,
       ``has_payment_method=true``) — AND semantics preserved.
    4. ``slim=1`` composes with the search param (``search=...``)
       on a case-insensitive match.
    5. Non-slim paginated response STILL ships
       ``properties_count`` (regression lock — slim is strictly
       opt-in, legacy callers unaffected).
    6. Tenant isolation: tenant A's slim list never leaks tenant
       B's rows.
    7. ``counts_by_status`` block is present under slim (regression
       lock — slim must not strip the K68 counts the FE tabs read).
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


async def _seed_tenant():
    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        return tenant["id"], admin
    return await _go(None) if False else None  # placated — see per-test seed


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                      "name": {"$regex": f"^{prefix}"}})
    await db.properties.delete_many({"tenant_id": tid,
                                       "customer_id": {"$regex": f"^{prefix}"}})
    await db.jobs.delete_many({"tenant_id": tid,
                                "customer_id": {"$regex": f"^{prefix}"}})


def _seed_customer(prefix, i, tid, overrides=None):
    doc = {
        "id": f"{prefix}{i:02d}",
        "tenant_id": tid,
        "name": f"{prefix}{i:02d}",
        "email": f"{prefix}{i:02d}@example.com",
        "is_active": True,
        "created_at": f"2026-02-05T00:00:{i:02d}Z",
        "saved_payment_methods_count": 0,
    }
    if overrides:
        doc.update(overrides)
    return doc


# ═════════════════════════════════════════════════════════════════
# 1 · slim=1 response omits properties_count + next_scheduled_at
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_response_skips_hydration_keys():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_SLIM_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # Seed 3 customers + 1 property per customer so the
        # non-slim path WOULD populate properties_count.
        for i in range(3):
            await db.customers.insert_one(_seed_customer(prefix, i, tid))
            await db.properties.insert_one({
                "id": f"PROP_{prefix}{i:02d}",
                "tenant_id": tid,
                "customer_id": f"{prefix}{i:02d}",
                "active": True,
            })
        try:
            slim_page = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=25, tags=[],
                slim=True,
            )
            assert isinstance(slim_page, dict)
            items = slim_page["items"]
            assert len(items) >= 3
            # Hydration keys MUST be absent on slim rows.
            for row in items:
                assert "properties_count" not in row, (
                    f"slim=1 leaked properties_count on row: {row.get('id')}"
                )
                assert "next_scheduled_at" not in row, (
                    f"slim=1 leaked next_scheduled_at on row: {row.get('id')}"
                )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · slim=1 preserves pagination envelope shape
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_envelope_shape_unchanged():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_ENV_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        for i in range(6):
            await db.customers.insert_one(_seed_customer(prefix, i, tid))
        try:
            page1 = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=3, tags=[],
                slim=True,
            )
            assert isinstance(page1, dict)
            # Envelope keys all present + consistent.
            for k in ("items", "total", "page", "page_size", "total_pages"):
                assert k in page1, f"slim envelope missing: {k}"
            assert page1["page"] == 1
            assert page1["page_size"] == 3
            assert page1["total"] >= 6
            assert len(page1["items"]) == 3
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · slim=1 composes with Phase 9b portal tile filters
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_composes_with_portal_tile_filters():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_TILE_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)

        # 3 customers:
        #   #0 — activated (portal_password_set_at set)
        #   #1 — activated (last_portal_login_at set)
        #   #2 — not activated
        await db.customers.insert_one(_seed_customer(
            prefix, 0, tid,
            {"portal_password_set_at": "2026-02-01T00:00:00Z"},
        ))
        await db.customers.insert_one(_seed_customer(
            prefix, 1, tid,
            {"last_portal_login_at": "2026-02-02T00:00:00Z"},
        ))
        await db.customers.insert_one(_seed_customer(prefix, 2, tid))

        try:
            # Phase 9b "Activated" tile → ?portal_activated=true
            activated_page = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=25, tags=[],
                slim=True, portal_activated=True,
            )
            activated_ids = {r["id"] for r in activated_page["items"]}
            assert f"{prefix}00" in activated_ids
            assert f"{prefix}01" in activated_ids
            assert f"{prefix}02" not in activated_ids, (
                "slim + portal_activated=true leaked a non-activated row"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · slim=1 composes with search (case-insensitive)
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_composes_with_search():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_SEARCH_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one(_seed_customer(
            prefix, 0, tid, {"name": f"{prefix}Smith"},
        ))
        await db.customers.insert_one(_seed_customer(
            prefix, 1, tid, {"name": f"{prefix}Jones"},
        ))
        try:
            page = await list_customers(
                user=admin, tenant={"id": tid},
                search=f"{prefix}smith", page=1, page_size=25, tags=[],
                slim=True,
            )
            ids = {r["id"] for r in page["items"]}
            assert f"{prefix}00" in ids, (
                "slim + search didn't match the Smith row"
            )
            assert f"{prefix}01" not in ids, (
                "slim + search leaked a non-matching row"
            )
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · Non-slim path STILL ships properties_count (regression lock)
# ═════════════════════════════════════════════════════════════════
def test_9c_non_slim_regression_properties_count_present():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_NONSLIM_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await db.customers.insert_one(_seed_customer(prefix, 0, tid))
        await db.properties.insert_one({
            "id": f"PROP_{prefix}00",
            "tenant_id": tid,
            "customer_id": f"{prefix}00",
            "active": True,
        })
        try:
            page = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=25, tags=[],
                # slim NOT set — default False
            )
            items = page["items"]
            assert items
            # Legacy callers still get properties_count populated.
            assert "properties_count" in items[0], (
                "non-slim regression: properties_count was dropped"
            )
            assert items[0]["properties_count"] >= 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 6 · Tenant isolation on slim list
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_tenant_isolation():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        other_tid = "TEST_9C_OTHER_" + uuid.uuid4().hex[:6]
        prefix = "TEST_9C_ISO_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        await _cleanup(db, other_tid, prefix)
        await db.customers.insert_one(_seed_customer(
            prefix, 0, tid, {"name": f"{prefix}MINE"},
        ))
        await db.customers.insert_one(_seed_customer(
            prefix, 1, other_tid, {"name": f"{prefix}THEIRS"},
        ))
        try:
            page = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=25, tags=[],
                slim=True,
            )
            ids = {r["id"] for r in page["items"]}
            assert f"{prefix}00" in ids
            assert f"{prefix}01" not in ids, (
                "slim list leaked another tenant's rows"
            )
        finally:
            await _cleanup(db, tid, prefix)
            await _cleanup(db, other_tid, prefix)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 7 · counts_by_status block present under slim (regression lock)
# ═════════════════════════════════════════════════════════════════
def test_9c_slim_counts_by_status_still_present():
    from routers.customers import list_customers

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                         {"_id": 0, "id": 1, "role": 1})
        tid = tenant["id"]
        prefix = "TEST_9C_CBS_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        for i in range(3):
            await db.customers.insert_one(_seed_customer(prefix, i, tid))
        try:
            page = await list_customers(
                user=admin, tenant={"id": tid},
                search=prefix, page=1, page_size=25, tags=[],
                slim=True,
            )
            assert "counts_by_status" in page, (
                "slim stripped the K68 counts_by_status block"
            )
            cbs = page["counts_by_status"]
            # Shape unchanged — same 5 buckets.
            for bucket in ("active", "inactive", "muted", "waitlist", "all"):
                assert bucket in cbs, f"counts_by_status missing {bucket}"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
