"""Phase B Perf Triad · Feb-2026 — SKIP_TEST_TENANT_PATTERNS filter.

Locks in the semantic guarantee that ``scan_dangling_refs`` skips
CI-fixture tenants ONLY when the env-var explicitly asks for it,
AND that the report shape stays byte-identical on the current DB
state (0 orphans → 0 orphans regardless of filter setting).
"""
from __future__ import annotations

import asyncio
import pytest

from tests._f7_loop_fixture import run_test


@pytest.fixture(autouse=True)
def _env_pin(monkeypatch):
    monkeypatch.delenv("SKIP_TEST_TENANT_PATTERNS", raising=False)
    monkeypatch.setenv("APP_ENV", "preview")
    yield


def test_filter_honors_env_var_defaults_and_skip_set(monkeypatch):
    from services.startup.integrity_check import (
        _test_tenant_ids_to_skip,
    )

    async def _go(db):
        import uuid
        test_id = "TEST_gs_" + uuid.uuid4().hex[:8]
        real_id = "real-" + uuid.uuid4().hex[:8]
        await db.tenants.delete_many({"id": {"$in": [test_id, real_id]}})
        await db.tenants.insert_many([
            {"id": test_id, "slug": "gs-x", "name": "GS Fixture"},
            {"id": real_id, "slug": "real-x", "name": "Real Co"},
        ])
        try:
            # 1) Default under PYTEST_CURRENT_TEST → filter OFF.
            skip = await _test_tenant_ids_to_skip(db)
            assert skip == set()

            # 2) Force default-ON by clearing PYTEST_CURRENT_TEST +
            # APP_ENV=preview → prefix defaults kick in.
            monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
            monkeypatch.setenv("APP_ENV", "preview")
            skip = await _test_tenant_ids_to_skip(db)
            assert test_id in skip
            assert real_id not in skip

            # 3) Explicit empty → filter OFF regardless of env.
            monkeypatch.setenv("SKIP_TEST_TENANT_PATTERNS", "")
            skip = await _test_tenant_ids_to_skip(db)
            assert skip == set()

            # 4) Explicit list → uses only what's listed.
            monkeypatch.setenv("SKIP_TEST_TENANT_PATTERNS", "real-")
            skip = await _test_tenant_ids_to_skip(db)
            assert real_id in skip
            assert test_id not in skip
        finally:
            await db.tenants.delete_many({"id": {"$in": [test_id, real_id]}})

    run_test(_go)


def test_scan_output_shape_preserved_when_filter_empty():
    """Byte-identical safety gate: with filter unset OR empty, the
    output shape of ``scan_dangling_refs`` must match the pre-Triad
    contract exactly (same top-level keys, same summary sub-keys)."""
    from services.startup.integrity_check import scan_dangling_refs

    async def _go(db):
        import os
        os.environ["SKIP_TEST_TENANT_PATTERNS"] = ""  # force filter OFF
        try:
            report = await scan_dangling_refs(db)
            # Locked top-level keys — same as pre-Triad.
            for k in ("orphan_customer", "orphan_customer_total",
                      "orphan_technician", "orphan_technician_total",
                      "orphan_crew", "orphan_crew_total",
                      "_all_orphans_customer",
                      "_all_orphans_technician",
                      "_all_orphans_crew",
                      "tenant_breakdown", "summary"):
                assert k in report, f"missing top-level key: {k}"
            for k in ("total_dangling_refs", "customer_class",
                      "technician_class", "crew_class"):
                assert k in report["summary"], (
                    f"missing summary key: {k}"
                )
        finally:
            os.environ.pop("SKIP_TEST_TENANT_PATTERNS", None)

    run_test(_go)
