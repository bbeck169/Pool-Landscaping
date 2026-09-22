"""Phase P23 · Feb-2026 — Restore Ethan / Steven technicians migration tests.

Locks the four migration contracts:

  1. Fresh DB (rows missing) → migration inserts both with the exact
     fields specified by the user (name / department / email /
     tenant_id / active + created_at + updated_at).
  2. Second run → no changes (idempotent). Neither row is re-inserted;
     ``already_present`` list contains both ids.
  3. Existing row with an admin-modified name → migration does NOT
     clobber (``$setOnInsert`` semantics). The modified name survives.
  4. Jobs pre-existing with matching ``technician_id`` → after
     migration, the diagnostic count returns the pre-existing job
     count (relink via FK, no data mutation of ``db.jobs``).
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


ETHAN_ID = "b728523e-533d-40b4-b33a-dbd3592c0e39"
STEVEN_ID = "ed4a4b04-d153-490c-bb17-3c402c72c8cb"
PLOFV_TENANT_ID = "67752881-7a80-4a2c-a03e-5d1aff4861a4"


async def _clean(db):
    await db.technicians.delete_many({"id": {"$in": [ETHAN_ID, STEVEN_ID]}})
    await db.jobs.delete_many({"id": {"$regex": "^TEST_P23_MIG_"}})


# ─── 1) Fresh DB — both rows inserted with the exact fields ───────
def test_p23_migration_inserts_both_technicians_on_fresh_db():
    async def _go(db):
        await _clean(db)
        try:
            from migrations.p23_restore_ethan_steven_technicians import run
            report = await run()
            assert set(report["inserted"]) == {ETHAN_ID, STEVEN_ID}, (
                f"expected both ids inserted, got {report['inserted']}"
            )
            assert report["already_present"] == []

            ethan = await db.technicians.find_one({"id": ETHAN_ID})
            steven = await db.technicians.find_one({"id": STEVEN_ID})
            assert ethan is not None
            assert steven is not None
            # Exact field spec.
            assert ethan["name"] == "Ethan Smith"
            assert ethan["department"] == "pool_tech"
            assert ethan["email"] == "ej3015@hotmail.com"
            assert ethan["tenant_id"] == PLOFV_TENANT_ID
            assert ethan["active"] is True
            assert ethan.get("created_at")
            assert ethan.get("updated_at")

            assert steven["name"] == "Steven Martinez"
            assert steven["department"] == "landscape_tech"
            assert steven["email"] == "landscape7@plofv.com"
            assert steven["tenant_id"] == PLOFV_TENANT_ID
            assert steven["active"] is True
            assert steven.get("created_at")
            assert steven.get("updated_at")
        finally:
            await _clean(db)
    run_test(_go)


# ─── 2) Second run is a no-op (idempotent) ─────────────────────────
def test_p23_migration_is_idempotent_on_second_run():
    async def _go(db):
        await _clean(db)
        try:
            from migrations.p23_restore_ethan_steven_technicians import run
            _ = await run()   # first pass — inserts
            report2 = await run()  # second pass — MUST no-op
            assert report2["inserted"] == []
            assert set(report2["already_present"]) == {ETHAN_ID, STEVEN_ID}
        finally:
            await _clean(db)
    run_test(_go)


# ─── 3) Admin-modified name must NOT be clobbered ──────────────────
def test_p23_migration_preserves_admin_modifications():
    async def _go(db):
        await _clean(db)
        try:
            # Pre-seed Ethan with a different name — simulates an admin
            # who renamed the row between the delete + this migration.
            await db.technicians.insert_one({
                "id": ETHAN_ID, "tenant_id": PLOFV_TENANT_ID,
                "name": "Ethan RENAMED",
                "department": "pool_tech",
                "email": "ej3015@hotmail.com",
                "active": True,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
            })

            from migrations.p23_restore_ethan_steven_technicians import run
            report = await run()

            # Ethan is already_present, Steven still needs an insert.
            assert ETHAN_ID in report["already_present"]
            assert STEVEN_ID in report["inserted"]

            ethan_after = await db.technicians.find_one({"id": ETHAN_ID})
            assert ethan_after["name"] == "Ethan RENAMED", (
                "$setOnInsert clobbered a pre-existing name — regression!"
            )
        finally:
            await _clean(db)
    run_test(_go)


# ─── 4) FK relink — pre-existing jobs count returns after migration ─
def test_p23_migration_relinks_existing_jobs_by_fk_without_mutation():
    async def _go(db):
        await _clean(db)
        try:
            # Seed 5 jobs on Ethan + 3 on Steven — all with the ORIGINAL
            # technician_id FK. The migration MUST NOT touch these; the
            # count returned in ``active_job_count`` should be exactly 8.
            docs = []
            for i in range(5):
                docs.append({
                    "id": f"TEST_P23_MIG_ETH_{i}_{uuid.uuid4().hex[:4]}",
                    "tenant_id": PLOFV_TENANT_ID,
                    "technician_id": ETHAN_ID,
                    "status": "scheduled",
                    "customer_id": "p23-fake",
                    "scheduled_date": "2026-05-01",
                })
            for i in range(3):
                docs.append({
                    "id": f"TEST_P23_MIG_STV_{i}_{uuid.uuid4().hex[:4]}",
                    "tenant_id": PLOFV_TENANT_ID,
                    "technician_id": STEVEN_ID,
                    "status": "scheduled",
                    "customer_id": "p23-fake",
                    "scheduled_date": "2026-05-01",
                })
            await db.jobs.insert_many(docs)

            from migrations.p23_restore_ethan_steven_technicians import run
            report = await run()

            assert report["active_job_count"] >= 8, (
                f"P23 FK-relink diagnostic returned {report['active_job_count']} "
                f"(expected ≥ 8 from the pre-existing seed)"
            )
            # Sanity check: jobs.technician_id values are untouched.
            for d in docs:
                row = await db.jobs.find_one({"id": d["id"]}, {"_id": 0})
                assert row["technician_id"] == d["technician_id"]
        finally:
            await _clean(db)
    run_test(_go)
