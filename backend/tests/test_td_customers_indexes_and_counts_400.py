"""TD-customers-indexes-and-counts-400 · Feb-2026 — regression lock.

Covers both halves of the ticket:

  Part 1 · ``perf_customers_v3`` migration
      1. Idempotency — second run is sentinel-skipped with zero
         creates. Expected indexes present on ``customers`` /
         ``properties`` after a fresh run.
      2. ``jobs`` + ``invoices`` reported as ``verified`` (covered
         by ``perf_customers_v1``) without duplicate index creation.
      3. Sentinel row lives in ``db.migration_status`` (NOT
         ``db._migrations``).

  Part 2 · ``GET /api/customers/counts`` 400 regression
      4. Empty-filter call returns 200 + full envelope (the exact
         pre-fix repro: FastAPI's ``Query(None, deprecated=True)``
         sentinel on ``size`` was being inherited by the direct-
         call bypass from ``customer_counts`` → ``list_customers``).
      5. With admin filters composed via query string → 200 with
         sensible counts.
      6. Cross-tenant isolation — another tenant's customers never
         land in the caller's counts.
      7. Contract preservation — ``GET /api/customers?size=100``
         (HTTP, real int) still 400s with the same ``unknown_param``
         payload.
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = "perf_customers_v3"

EXPECTED_V3_INDEXES = [
    # (collection, index_name, keys)
    ("customers",
     "perf_customers_v3_tenant_service_category",
     [("tenant_id", 1), ("service_category", 1)]),
    ("customers",
     "perf_customers_v3_tenant_created_desc_id",
     [("tenant_id", 1), ("created_at", -1), ("_id", -1)]),
    ("properties",
     "perf_customers_v3_properties_tenant_customer_active",
     [("tenant_id", 1), ("customer_id", 1), ("active", 1)]),
]

VERIFY_ONLY_COLLECTIONS = ("jobs", "invoices")


# ═════════════════════════════════════════════════════════════════════
# Part 1 — migration tests
# ═════════════════════════════════════════════════════════════════════


def test_perf_customers_v3_run_is_idempotent_and_creates_expected_indexes():
    """First run creates (or reuses) the three v3 indexes and stamps
    the sentinel. Second run is sentinel-skipped with zero creates.
    ``list_indexes()`` returns each expected name on both runs
    (indexes survive between calls)."""
    async def _go(db):
        from services.migrations.perf_customers_indexes_v3 import run

        # Clean slate so run() actually executes.
        await db.migration_status.delete_one({"key": MIGRATION_KEY})

        res1 = await run(db)
        assert res1["ok"] is True
        assert res1["skipped"] is False, (
            f"First run reported skipped=True — sentinel leaked: {res1}"
        )

        # Each expected index now appears on its collection.
        for coll_name, idx_name, _keys in EXPECTED_V3_INDEXES:
            names = set()
            async for idx in db[coll_name].list_indexes():
                names.add(idx.get("name") or "")
            assert idx_name in names, (
                f"{coll_name}: expected index {idx_name!r} missing — "
                f"actual indexes: {sorted(names)}"
            )

        # Second run — sentinel short-circuits.
        res2 = await run(db)
        assert res2["ok"] is True
        assert res2["skipped"] is True, (
            f"Second run should be sentinel-skipped but was: {res2}"
        )
        assert res2["created"] == 0
        assert res2["reason"] == "already_ran"

    run_test(_go)


def test_perf_customers_v3_reports_jobs_invoices_as_verified():
    """``perf_customers_v1`` already ships
    ``(tenant_id, customer_id, created_at)`` on ``jobs`` and
    ``invoices`` — v3 MUST report them as ``verified`` without
    creating a duplicate index.
    """
    async def _go(db):
        from services.migrations.perf_customers_indexes_v3 import run

        await db.migration_status.delete_one({"key": MIGRATION_KEY})

        # Snapshot index counts on jobs/invoices BEFORE the run.
        before_counts = {}
        for coll in VERIFY_ONLY_COLLECTIONS:
            cnt = 0
            async for _ in db[coll].list_indexes():
                cnt += 1
            before_counts[coll] = cnt

        res = await run(db)
        assert res["ok"] is True
        verified = res.get("verified") or []
        for coll in VERIFY_ONLY_COLLECTIONS:
            assert coll in verified, (
                f"Expected {coll!r} in result.verified but got: "
                f"{verified!r} (full result: {res})"
            )

        # Index counts on jobs/invoices unchanged — no duplicate
        # indexes created by v3.
        for coll in VERIFY_ONLY_COLLECTIONS:
            cnt = 0
            async for _ in db[coll].list_indexes():
                cnt += 1
            assert cnt == before_counts[coll], (
                f"{coll}: index count changed from "
                f"{before_counts[coll]} to {cnt} — v3 wrote a "
                f"duplicate index on a verify-only collection"
            )

    run_test(_go)


def test_perf_customers_v3_writes_sentinel_to_migration_status():
    """Sentinel row lives in ``db.migration_status`` keyed by
    ``perf_customers_v3`` with a truthy ``completed_at``. The
    diagnostic ``db.migrations`` collection MUST NOT receive a row
    with the same key."""
    async def _go(db):
        from services.migrations.perf_customers_indexes_v3 import run

        await db.migration_status.delete_one({"key": MIGRATION_KEY})
        await db.migrations.delete_many({"id": MIGRATION_KEY})

        await run(db)

        row = await db.migration_status.find_one(
            {"key": MIGRATION_KEY}, {"_id": 0},
        )
        assert row is not None, (
            "migration_status row missing — v3 sentinel was not "
            "written."
        )
        assert row.get("key") == MIGRATION_KEY
        assert row.get("completed_at"), (
            f"v3 sentinel missing completed_at: {row}"
        )

        wrong = await db.migrations.find_one({"id": MIGRATION_KEY})
        assert wrong is None, (
            "v3 wrote to db.migrations — should be "
            "db.migration_status only."
        )

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# Part 2 — /customers/counts 400 regression
# ═════════════════════════════════════════════════════════════════════


async def _seed_customer(db, *, tenant_id, **fields):
    doc = {
        "id": f"c-{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "name": fields.pop("name", "Counts Test Customer"),
        "email": fields.pop("email", "test@example.com"),
        "phone": fields.pop("phone", "+15555550199"),
        "is_active": fields.pop("is_active", True),
    }
    doc.update(fields)
    await db.customers.insert_one(doc)
    return doc["id"]


def test_customer_counts_with_empty_query_returns_200_envelope():
    """Pre-fix repro: calling ``customer_counts`` directly (same
    code path the FE hits with no filters) 400'd because the
    direct-call bypass inherited the ``Query(None, deprecated=True)``
    sentinel for the ``size`` parameter and the gate used
    ``is not None`` instead of ``isinstance(..., int)``.

    Fixed in TD-customers-indexes-and-counts-400 by tightening the
    gate to ``isinstance(size, int)``. HTTP callers still 400 on a
    real ``?size=100``, direct callers composing without ``size``
    now flow through.
    """
    from routers.customers import customer_counts

    async def _go(db):
        tid = f"t-k400-{uuid.uuid4().hex[:6]}"
        cids = []
        for _ in range(2):
            cids.append(await _seed_customer(
                db, tenant_id=tid, is_active=True,
            ))
        cids.append(await _seed_customer(
            db, tenant_id=tid, is_active=False,
        ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "K400 Tenant"}
            # Direct call — the exact bypass that was 400'ing.
            res = await customer_counts(user=user, tenant=tenant)
            payload = res.model_dump()
            # Full envelope — all nine keys MUST be present.
            for key in (
                "active", "inactive", "muted", "waitlist", "all",
                "missing_address", "portal_activated",
                "portal_not_activated", "no_payment_method",
                "never_logged_in",
            ):
                assert key in payload, (
                    f"customer_counts missing key: {key} "
                    f"(payload: {payload})"
                )
            # Sanity on the counts we seeded.
            assert payload["active"] >= 2
            assert payload["inactive"] >= 1
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


def test_customer_counts_with_filters_returns_200():
    """Chip composition still works — passing admin filters doesn't
    regress the size-sentinel fix."""
    from routers.customers import customer_counts

    async def _go(db):
        tid = f"t-k400f-{uuid.uuid4().hex[:6]}"
        cids = []
        # 2 active, no payment method; 1 active, with payment method.
        for _ in range(2):
            cids.append(await _seed_customer(
                db, tenant_id=tid, is_active=True,
                saved_payment_methods_count=0,
            ))
        cids.append(await _seed_customer(
            db, tenant_id=tid, is_active=True,
            saved_payment_methods_count=2,
        ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "K400 Filter Tenant"}
            res = await customer_counts(
                user=user, tenant=tenant,
                has_payment_method=False,
            )
            payload = res.model_dump()
            # 2 of 3 seeded customers have no_payment_method →
            # ``active`` (tab, chip-composed) counts those 2.
            assert payload["active"] == 2, (
                f"Expected active=2 with has_payment_method=False, "
                f"got {payload['active']} (payload: {payload})"
            )
            # Standalone badge (stability contract — NOT chip-
            # composed) counts ALL no-payment-method customers in
            # the tenant: 2.
            assert payload["no_payment_method"] >= 2
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


def test_customer_counts_tenant_isolation():
    """A customer in tenant B MUST NOT land in tenant A's counts."""
    from routers.customers import customer_counts

    async def _go(db):
        tid_a = f"t-k400a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-k400b-{uuid.uuid4().hex[:6]}"
        cids = []
        # Tenant A: 1 active.
        cids.append(await _seed_customer(
            db, tenant_id=tid_a, is_active=True,
        ))
        # Tenant B: 5 active — should never leak into A.
        for _ in range(5):
            cids.append(await _seed_customer(
                db, tenant_id=tid_b, is_active=True,
            ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant_a = {"id": tid_a, "name": "Tenant A"}
            res = await customer_counts(user=user, tenant=tenant_a)
            payload = res.model_dump()
            assert payload["active"] == 1, (
                f"Tenant isolation leak — tenant A ``active`` should "
                f"be 1 but got {payload['active']} (tenant B seeded "
                f"5 extras)"
            )
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


def test_customers_list_size_param_still_rejected_via_http_shape():
    """Contract preservation — a real integer ``size`` param (what
    FastAPI's query parser hands to ``list_customers`` on a real
    HTTP call) still 400s with the same ``unknown_param`` payload
    shape. The direct-call bypass fix did NOT loosen the HTTP
    contract."""
    from fastapi import HTTPException

    from routers.customers import list_customers

    async def _go(db):
        tid = f"t-k400s-{uuid.uuid4().hex[:6]}"
        user = {"id": "u-adm", "role": "admin"}
        tenant = {"id": tid, "name": "Size Reject Tenant"}

        raised = None
        try:
            await list_customers(
                user=user, tenant=tenant,
                search=None, tag=None, tags=None, city=None,
                waitlisted=None, unscheduled=None,
                is_active=None, missing_card=None,
                missing_email=False, missing_phone=False,
                missing_address=False,
                portal_activated=None, portal_invited=None,
                first_access=None, portal_status=None,
                is_muted=None, has_payment_method=None,
                count_only=False,
                include_deleted=False, include_merged=False,
                ids_in=None,
                page=None, page_size=None,
                size=100,  # real int, HTTP-shaped
                sort="created_desc",
                slim=False,
            )
        except HTTPException as e:
            raised = e

        assert raised is not None, (
            "HTTP-shape ``size=100`` should 400 but did not raise"
        )
        assert raised.status_code == 400
        detail = raised.detail
        assert isinstance(detail, dict), (
            f"Expected dict detail, got: {type(detail).__name__}"
        )
        assert detail.get("error_code") == "unknown_param"
        assert detail.get("detail") == "unsupported_query_param"
        assert detail.get("param") == "size"

    run_test(_go)
