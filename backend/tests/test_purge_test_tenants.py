"""Phase A · Feb-2026 — purge_test_tenants.py test suite.

Tests use the shared F7 loop fixture (``_f7_loop_fixture.run_test``)
so every case pins the Motor client to a single event loop.  The
purge script imports ``from config import db`` late, so when the
fixture rebinds ``config.db`` the script sees the same handle.

Scenarios covered
-----------------
  1. ``dry_run_reports_correct_counts`` — seeded 3 test + 1 real
     tenant, dry-run reports the right counts and mutates nothing.
  2. ``apply_deletes_all_matched_tenants_and_children`` — apply
     wipes matched tenants + every downstream row, leaves the
     non-test tenant intact.
  3. ``rerun_apply_is_no_op`` — a second ``--apply`` with the same
     args returns tenants_matched=0 and mutates nothing.
  4. ``audit_events_row_has_expected_shape`` — a row lands in
     ``audit_events`` with the correct ``event_type``, actor and
     payload keys.
  5. ``tenant_id_explicit_targeting`` — ``--tenant-id`` isolates a
     single tenant and only that tenant's rows are removed.
  6. ``safety_limit_gate_refuses`` — when matched > --limit, apply
     is refused via ``SafetyRefused``.
  7. ``prod_gate_refuses_without_ack`` — APP_ENV=production + apply
     without ``--i-know-this-is-prod`` is refused.

F3 pre/post scan is disabled per-test via ``skip_f3=True`` because
it depends on live ``jobs``/``customers``/``crews`` state; the F3
guard behavior itself is tested separately in
``test_f9_data_repair_status.py`` and the integrity_check unit
tests.  We reintroduce a lightweight F3 check in the live-preview
run (see the script empirical proof).
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from tests._f7_loop_fixture import run_test


# Preview / dev boxes carry APP_ENV=production by default (the pod
# manifest matches the prod env for parity). Force APP_ENV=preview
# for the apply-path tests so the prod safety gate doesn't refuse
# them. The dedicated prod-gate test flips this back inside its
# own body via ``monkeypatch``.
@pytest.fixture(autouse=True)
def _pin_app_env_preview(monkeypatch):
    monkeypatch.setenv("APP_ENV", "preview")
    yield


# ═══════════════════════════════════════════════════════════════════
# Fixture helpers
# ═══════════════════════════════════════════════════════════════════

async def _seed_test_dataset(db) -> dict:
    """Seed 3 CI-test tenants matching each default prefix + one
    non-test tenant.  Each tenant gets a small downstream footprint
    across ``customers``, ``jobs``, ``users``, ``leads`` so we can
    prove the cascade works AND that non-test rows are untouched.

    Returns a metadata dict for later assertion.
    """
    real_id = f"real-{uuid.uuid4().hex[:8]}"
    test_ids = [
        "TEST_gs_purge_test_" + uuid.uuid4().hex[:8],
        "csv-purge_test_" + uuid.uuid4().hex[:8],
        "jca-purge_test_" + uuid.uuid4().hex[:8],
    ]

    # Clean any lingering rows from a previous test iteration.
    all_ids = [real_id, *test_ids]
    await asyncio.gather(
        db.tenants.delete_many({"id": {"$in": all_ids}}),
        db.customers.delete_many({"tenant_id": {"$in": all_ids}}),
        db.jobs.delete_many({"tenant_id": {"$in": all_ids}}),
        db.users.delete_many({"tenant_id": {"$in": all_ids}}),
        db.leads.delete_many({"tenant_id": {"$in": all_ids}}),
        db.audit_events.delete_many({
            "event_type": "test_tenant_purge",
            "payload.tenant_ids": {"$in": all_ids},
        }),
    )

    # Insert tenant docs.
    await db.tenants.insert_many([
        {"id": real_id, "slug": "real-tenant-" + real_id[-4:],
         "name": "Real Tenant"},
        {"id": test_ids[0], "slug": "gs-fake",
         "name": "GS Fake Tenant"},
        {"id": test_ids[1], "slug": test_ids[1],
         "name": "CSV Fake Tenant"},
        {"id": test_ids[2], "slug": test_ids[2],
         "name": "JCA Fake Tenant"},
    ])

    # Insert 2 customers + 3 jobs + 2 users + 1 lead per tenant.
    docs_customers = []
    docs_jobs = []
    docs_users = []
    docs_leads = []
    for tid in all_ids:
        for _ in range(2):
            docs_customers.append({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "name": f"Cust of {tid[:12]}",
            })
        for _ in range(3):
            docs_jobs.append({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "status": "scheduled",
            })
        for _ in range(2):
            docs_users.append({
                "id": str(uuid.uuid4()), "tenant_id": tid,
                "email": f"{uuid.uuid4().hex[:6]}@{tid[:8]}.test",
                "role": "admin",
            })
        docs_leads.append({
            "id": str(uuid.uuid4()), "tenant_id": tid,
            "name": "Lead X",
        })

    await asyncio.gather(
        db.customers.insert_many(docs_customers),
        db.jobs.insert_many(docs_jobs),
        db.users.insert_many(docs_users),
        db.leads.insert_many(docs_leads),
    )

    return {
        "real_id": real_id,
        "test_ids": test_ids,
        "expected_per_tenant": {
            "customers": 2, "jobs": 3, "users": 2, "leads": 1,
        },
    }


async def _cleanup_dataset(db, meta: dict) -> None:
    all_ids = [meta["real_id"], *meta["test_ids"]]
    await asyncio.gather(
        db.tenants.delete_many({"id": {"$in": all_ids}}),
        db.customers.delete_many({"tenant_id": {"$in": all_ids}}),
        db.jobs.delete_many({"tenant_id": {"$in": all_ids}}),
        db.users.delete_many({"tenant_id": {"$in": all_ids}}),
        db.leads.delete_many({"tenant_id": {"$in": all_ids}}),
        # Only nuke audit rows whose payload actually references
        # our test-seeded tenant ids — never wholesale-delete every
        # `test_tenant_purge` row (that would clobber real ops runs
        # against the shared preview DB).
        db.audit_events.delete_many({
            "event_type": "test_tenant_purge",
            "payload.tenant_ids": {"$in": all_ids},
        }),
    )


# ═══════════════════════════════════════════════════════════════════
# 1. dry-run reports counts + mutates nothing
# ═══════════════════════════════════════════════════════════════════

def test_dry_run_reports_correct_counts_and_no_writes():
    from scripts.purge_test_tenants import run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            result = await run_purge(
                db,
                prefixes=["TEST_gs_", "csv-", "jca-"],
                tenant_ids=[],
                apply=False,
                skip_f3=True,
            )
            # Exactly the 3 seeded test tenants (may pick up other
            # preview rows on the shared DB — assert >= 3).
            assert result["tenants_matched"] >= 3
            assert result["tenants_deleted"] == 0
            assert result["child_rows_deleted"] == 0
            assert result["mode"] == "dry_run"
            assert set(meta["test_ids"]).issubset(set(result["target_ids"]))

            # Non-test tenant still present with all rows.
            assert await db.tenants.count_documents(
                {"id": meta["real_id"]}) == 1
            assert await db.customers.count_documents(
                {"tenant_id": meta["real_id"]}) == 2
            assert await db.jobs.count_documents(
                {"tenant_id": meta["real_id"]}) == 3

            # Test tenants + their rows are still there (dry-run).
            for tid in meta["test_ids"]:
                assert await db.tenants.count_documents(
                    {"id": tid}) == 1
                assert await db.customers.count_documents(
                    {"tenant_id": tid}) == 2
                assert await db.jobs.count_documents(
                    {"tenant_id": tid}) == 3
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. apply deletes matched tenants + children, leaves real untouched
# ═══════════════════════════════════════════════════════════════════

def test_apply_deletes_matched_tenants_and_cascade_children():
    from scripts.purge_test_tenants import run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            # Use ONLY --tenant-id targeting so we don't cascade
            # across other preview CI cruft during a shared-DB run.
            result = await run_purge(
                db,
                prefixes=[],
                tenant_ids=meta["test_ids"],
                apply=True,
                skip_f3=True,
            )
            assert result["mode"] == "apply"
            assert result["tenants_deleted"] == 3
            # 3 tenants × (2 customers + 3 jobs + 2 users + 1 lead) = 24
            assert result["child_rows_deleted"] == 24

            # Test tenants + all their rows: gone.
            for tid in meta["test_ids"]:
                assert await db.tenants.count_documents(
                    {"id": tid}) == 0
                assert await db.customers.count_documents(
                    {"tenant_id": tid}) == 0
                assert await db.jobs.count_documents(
                    {"tenant_id": tid}) == 0
                assert await db.users.count_documents(
                    {"tenant_id": tid}) == 0
                assert await db.leads.count_documents(
                    {"tenant_id": tid}) == 0

            # Non-test tenant fully preserved.
            assert await db.tenants.count_documents(
                {"id": meta["real_id"]}) == 1
            assert await db.customers.count_documents(
                {"tenant_id": meta["real_id"]}) == 2
            assert await db.jobs.count_documents(
                {"tenant_id": meta["real_id"]}) == 3
            assert await db.users.count_documents(
                {"tenant_id": meta["real_id"]}) == 2
            assert await db.leads.count_documents(
                {"tenant_id": meta["real_id"]}) == 1
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Re-run apply is a no-op
# ═══════════════════════════════════════════════════════════════════

def test_second_apply_run_is_no_op():
    from scripts.purge_test_tenants import run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            await run_purge(
                db, prefixes=[], tenant_ids=meta["test_ids"],
                apply=True, skip_f3=True,
            )
            # Second call — nothing to find, nothing to delete.
            result2 = await run_purge(
                db, prefixes=[], tenant_ids=meta["test_ids"],
                apply=True, skip_f3=True,
            )
            assert result2["tenants_matched"] == 0
            assert result2["tenants_deleted"] == 0
            assert result2["child_rows_deleted"] == 0
            assert result2["mode"] == "apply"
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. audit_events row shape
# ═══════════════════════════════════════════════════════════════════

def test_audit_events_row_written_with_expected_shape():
    from scripts.purge_test_tenants import (
        AUDIT_EVENT_TYPE, run_purge,
    )

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            result = await run_purge(
                db, prefixes=[], tenant_ids=meta["test_ids"],
                apply=True, skip_f3=True,
            )
            aid = result["audit_event_id"]
            assert aid, "audit_event_id must be present"

            row = await db.audit_events.find_one(
                {"id": aid}, {"_id": 0},
            )
            assert row is not None
            assert row["event_type"] == AUDIT_EVENT_TYPE
            assert row["actor_user_id"].startswith("cli:")
            assert row["timestamp"]
            # Payload has all required keys the runbook promises.
            payload = row["payload"]
            for key in ("prefixes", "tenant_ids", "tenants_deleted",
                        "per_collection_counts", "dry_run",
                        "elapsed_s"):
                assert key in payload, f"payload missing key: {key}"
            assert payload["dry_run"] is False
            assert payload["tenants_deleted"] == 3
            assert set(meta["test_ids"]).issubset(
                set(payload["tenant_ids"]),
            )
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5. --tenant-id targets exactly one tenant
# ═══════════════════════════════════════════════════════════════════

def test_tenant_id_flag_purges_only_the_named_tenant():
    from scripts.purge_test_tenants import run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        target = meta["test_ids"][1]
        siblings = [meta["test_ids"][0], meta["test_ids"][2]]
        try:
            result = await run_purge(
                db, prefixes=[], tenant_ids=[target],
                apply=True, skip_f3=True,
            )
            assert result["tenants_matched"] == 1
            assert result["tenants_deleted"] == 1
            # Only target row-set removed.
            assert await db.tenants.count_documents(
                {"id": target}) == 0
            assert await db.jobs.count_documents(
                {"tenant_id": target}) == 0
            # Sibling test tenants untouched.
            for sib in siblings:
                assert await db.tenants.count_documents(
                    {"id": sib}) == 1
                assert await db.jobs.count_documents(
                    {"tenant_id": sib}) == 3
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 6. --limit safety cap refuses when exceeded
# ═══════════════════════════════════════════════════════════════════

def test_safety_limit_refuses_apply_when_matched_exceeds_cap():
    from scripts.purge_test_tenants import SafetyRefused, run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            with pytest.raises(SafetyRefused):
                await run_purge(
                    db, prefixes=[],
                    tenant_ids=meta["test_ids"],
                    apply=True, limit=2, skip_f3=True,
                )
            # No deletions happened (guard runs before delete).
            for tid in meta["test_ids"]:
                assert await db.tenants.count_documents(
                    {"id": tid}) == 1
        finally:
            await _cleanup_dataset(db, meta)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7. Prod gate refuses without --i-know-this-is-prod
# ═══════════════════════════════════════════════════════════════════

def test_prod_env_refuses_apply_without_ack_flag(monkeypatch):
    from scripts.purge_test_tenants import SafetyRefused, run_purge

    async def _go(db):
        meta = await _seed_test_dataset(db)
        try:
            monkeypatch.setenv("APP_ENV", "production")
            with pytest.raises(SafetyRefused) as ei:
                await run_purge(
                    db, prefixes=[],
                    tenant_ids=meta["test_ids"],
                    apply=True, i_know_this_is_prod=False,
                    skip_f3=True,
                )
            assert "prod" in str(ei.value).lower()
            # No deletions occurred.
            for tid in meta["test_ids"]:
                assert await db.tenants.count_documents(
                    {"id": tid}) == 1
        finally:
            monkeypatch.delenv("APP_ENV", raising=False)
            await _cleanup_dataset(db, meta)

    run_test(_go)
