"""PERF-AUDIT-A · Feb-2026 — Gap-fill indexes migration tests.

Validates the ``migrations.perf_audit_a_indexes.run`` migration:

  1. Fresh-DB-like run creates every index in the catalog.
  2. Second run (same DB) reports every index as ``already_present``
     — idempotent + fast.
  3. Sentinel row is written to ``db.migrations`` after each run
     with the summary payload.

The migration runs against the live preview DB (same pattern as
``k44_perf_indexes``'s companion tests); indexes are additive so
leaving them in place after the test is harmless.  The test does
NOT drop the created indexes — doing so would churn the planner
cache for other concurrent test files.
"""
from __future__ import annotations

from tests._f7_loop_fixture import run_test


_EXPECTED_INDEX_NAMES = {
    "credits": {"perf_audit_a_credits_tenant_customer"},
    "invoices": {
        "perf_audit_a_invoices_tenant_customer_status",
        "perf_audit_a_invoices_tenant_customer_duedate",
    },
    "quotes": {"perf_audit_a_quotes_tenant_customer_status"},
    "payments": {"perf_audit_a_payments_tenant_invoice"},
    "customers": {
        "perf_audit_a_customers_tenant_tags",
        "perf_audit_a_customers_tenant_deleted_active_created_desc",
    },
}


def test_perf_audit_a_run_creates_every_catalogued_index():
    """First + second run of the migration leaves every expected
    index name present on the target collections, reports a non-
    error summary, and stamps the sentinel row."""
    async def _go(db):
        import migrations.perf_audit_a_indexes as _mod
        _mod.db = db

        # First call — creates whatever's missing.
        res1 = await _mod.run()
        assert res1["status"] == "ok"
        s1 = res1["summary"]
        assert s1["errors"] == [], (
            f"Index creation errors: {s1['errors']}"
        )

        # Second call — every index must now report
        # ``already_present``.  The sum of created+already_present
        # must equal the catalog size.
        res2 = await _mod.run()
        s2 = res2["summary"]
        assert s2["errors"] == []
        assert s2["created"] == 0, (
            f"Second run should be a no-op; created={s2['created']} "
            f"targets={s2['targets']}"
        )
        assert s2["already_present"] == len(_mod._INDEXES), (
            "Every index must report already_present on the 2nd run; "
            f"got already_present={s2['already_present']} "
            f"catalog_size={len(_mod._INDEXES)}"
        )

        # Verify each expected index is actually on the collection.
        for coll_name, want_names in _EXPECTED_INDEX_NAMES.items():
            have = set()
            async for idx in db[coll_name].list_indexes():
                have.add(idx.get("name") or "")
            missing = want_names - have
            assert not missing, (
                f"{coll_name!r} missing expected indexes: {missing} "
                f"(have={sorted(have)})"
            )

        # Sentinel row stamped.
        sen = await db.migrations.find_one(
            {"id": "perf_audit_a_indexes_v1"}, {"_id": 0},
        )
        assert sen is not None
        assert sen.get("last_run_at")
        assert sen.get("summary") is not None

    run_test(_go)
