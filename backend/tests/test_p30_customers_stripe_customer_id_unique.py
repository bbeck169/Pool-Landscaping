"""Phase P30 addendum · Feb-2026 — partial unique index migration on
``customers.stripe_customer_id``.

Covers:

1. Fresh DB (no duplicates) → migration installs the partial unique
   index. ``list_indexes`` reports ``unique=True`` and the correct
   ``partialFilterExpression``.
2. Duplicates present → migration LOGS WARN per duplicate cluster,
   DOES NOT create the index, and returns ``{ok: False,
   duplicates: [...]}``. Boot never crashes.
3. Idempotent — a second run against a dup-free DB is a no-op (no
   error, index still present).
4. Partial filter — a customer with ``stripe_customer_id=""`` OR
   ``None`` OR absent field can coexist with another customer with
   the same empty/missing value. Only NON-EMPTY duplicates are
   rejected.

Uses the F7 loop-bound Mongo so the migration exercises the same
collection Mongo API as production boot.
"""
from __future__ import annotations

import logging
import uuid

from tests._f7_loop_fixture import run_test


INDEX_NAME = "p30_customers_stripe_customer_id_unique"


async def _drop_p30_index(db):
    """Best-effort cleanup — safe to call even when the index doesn't
    exist (returns silently). Keeps tests isolated when they run in
    any order."""
    try:
        await db.customers.drop_index(INDEX_NAME)
    except Exception:  # noqa: BLE001
        pass


async def _index_by_name(db, name):
    async for spec in db.customers.list_indexes():
        if spec.get("name") == name:
            return spec
    return None


# ═════════════════════════════════════════════════════════════════════
# 1. Fresh DB — migration installs the index.
# ═════════════════════════════════════════════════════════════════════
def test_p30_idx_fresh_db_installs_partial_unique_index():
    from migrations.p30_customers_stripe_customer_id_unique import run

    async def _go(db):
        await _drop_p30_index(db)
        try:
            res = await run()
            assert res["ok"] is True
            assert res["index_created"] is True
            assert res["duplicates"] == []
            # Introspect Mongo to confirm the index shape.
            spec = await _index_by_name(db, INDEX_NAME)
            assert spec is not None
            assert spec.get("unique") is True
            pfe = spec.get("partialFilterExpression")
            assert pfe is not None
            # The filter must gate on ``stripe_customer_id`` presence
            # + non-empty string so absent / null / "" rows are
            # excluded from the uniqueness constraint.
            assert "stripe_customer_id" in pfe
        finally:
            await _drop_p30_index(db)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Duplicates present → migration logs WARN + refuses to install.
# ═════════════════════════════════════════════════════════════════════
def test_p30_idx_duplicates_skip_index_and_log_warn(caplog):
    from migrations.p30_customers_stripe_customer_id_unique import run

    async def _go(db):
        await _drop_p30_index(db)
        dup_val = f"cus_dup_{uuid.uuid4().hex[:8]}"
        cid_a = f"dupA-{uuid.uuid4().hex[:6]}"
        cid_b = f"dupB-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({
            "id": cid_a, "tenant_id": "t-dup-a", "name": "Dup A",
            "stripe_customer_id": dup_val,
        })
        await db.customers.insert_one({
            "id": cid_b, "tenant_id": "t-dup-b", "name": "Dup B",
            "stripe_customer_id": dup_val,
        })
        try:
            with caplog.at_level(logging.WARNING):
                res = await run()
            assert res["ok"] is False
            assert res["index_created"] is False
            assert len(res["duplicates"]) == 1
            cluster = res["duplicates"][0]
            assert cluster["stripe_customer_id"] == dup_val
            assert cluster["count"] == 2
            assert set(cluster["customer_ids"]) == {cid_a, cid_b}
            # Index NOT installed.
            assert await _index_by_name(db, INDEX_NAME) is None
            # WARN log fired mentioning the dup value.
            assert any(
                dup_val in rec.message
                for rec in caplog.records
                if rec.levelno == logging.WARNING
            )
        finally:
            await db.customers.delete_many(
                {"stripe_customer_id": dup_val},
            )
            await _drop_p30_index(db)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Idempotent — second run against dup-free DB.
# ═════════════════════════════════════════════════════════════════════
def test_p30_idx_second_run_is_idempotent():
    from migrations.p30_customers_stripe_customer_id_unique import run

    async def _go(db):
        await _drop_p30_index(db)
        try:
            res1 = await run()
            res2 = await run()
            assert res1["index_created"] is True
            assert res2["ok"] is True
            # Index still there.
            assert await _index_by_name(db, INDEX_NAME) is not None
        finally:
            await _drop_p30_index(db)

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4. Partial filter — empty / null / absent stripe_customer_id
#    coexists happily; only non-empty duplicates are rejected.
# ═════════════════════════════════════════════════════════════════════
def test_p30_idx_partial_filter_allows_empty_null_absent():
    """After installing the index, two customers can BOTH have
    ``stripe_customer_id=""`` (or ``None``, or the field absent
    entirely) without violating the unique constraint. Regression
    guard against a plain ``create_index("stripe_customer_id",
    unique=True)`` that would collide on the ubiquitous "not yet
    minted" state."""
    from migrations.p30_customers_stripe_customer_id_unique import run

    async def _go(db):
        await _drop_p30_index(db)
        cid_empty1 = f"empty1-{uuid.uuid4().hex[:6]}"
        cid_empty2 = f"empty2-{uuid.uuid4().hex[:6]}"
        cid_absent = f"absent-{uuid.uuid4().hex[:6]}"
        cid_null = f"null-{uuid.uuid4().hex[:6]}"
        try:
            res = await run()
            assert res["ok"] is True
            # Two empty-string rows — SHOULD both insert.
            await db.customers.insert_one({
                "id": cid_empty1, "tenant_id": "t1", "name": "E1",
                "stripe_customer_id": "",
            })
            await db.customers.insert_one({
                "id": cid_empty2, "tenant_id": "t2", "name": "E2",
                "stripe_customer_id": "",
            })
            # Absent field.
            await db.customers.insert_one({
                "id": cid_absent, "tenant_id": "t3", "name": "A1",
            })
            # Null value.
            await db.customers.insert_one({
                "id": cid_null, "tenant_id": "t4", "name": "N1",
                "stripe_customer_id": None,
            })
            # All four rows present → partial filter is working.
            count = await db.customers.count_documents(
                {"id": {"$in": [
                    cid_empty1, cid_empty2, cid_absent, cid_null,
                ]}},
            )
            assert count == 4
        finally:
            await db.customers.delete_many({"id": {"$in": [
                cid_empty1, cid_empty2, cid_absent, cid_null,
            ]}})
            await _drop_p30_index(db)

    run_test(_go)
