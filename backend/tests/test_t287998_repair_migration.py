"""Ticket 287998 — one-shot cross-customer property repair migration.

End-to-end against a THROWAWAY database (never the app DB): seeds the exact
shapes seen in production, then checks dry-run, execute, idempotency, backups,
the merged-duplicate exclusion and the marker.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrations import t287998_repair_cross_customer_property_links as mig  # noqa: E402

T = "t1"


def _addr(line1, city="Peoria", postal="85383"):
    return {"line1": line1, "line2": None, "city": city, "state": "AZ", "postal_code": postal}


CUSTOMERS = [
    {"id": "carl", "tenant_id": T, "address": "27059 North 130th Drive, Peoria, AZ, 85383"},
    {"id": "jolene", "tenant_id": T, "address": "22442 N 80th Lane, Peoria, AZ, 85383"},
    {"id": "lynn", "tenant_id": T, "address": "11975 W Skinner Dr, Peoria, AZ 85383"},  # no property
    {"id": "toni_new", "tenant_id": T, "address": "5634 E Yolantha St"},
    {"id": "toni_old", "tenant_id": T, "merged_into": "toni_new"},
]
PROPERTIES = [
    {"id": "p_jolene", "tenant_id": T, "customer_id": "jolene", "active": True, "sort_order": 0,
     "address": _addr("22442 N 80th Lane")},
    {"id": "p_carl", "tenant_id": T, "customer_id": "carl", "active": True, "sort_order": 0,
     "address": _addr("27059 North 130th Drive")},
    {"id": "p_toni_old", "tenant_id": T, "customer_id": "toni_old", "active": True, "sort_order": 0,
     "address": _addr("5634 East Yolantha Street", "Scottsdale", "85266")},
    {"id": "p_ghost", "tenant_id": T, "customer_id": "ghost_customer_gone", "active": True,
     "sort_order": 0, "address": _addr("1 Ghost Way")},
]
SNAPSHOT = "22442 N 80th Lane, Peoria, AZ, 85383"  # copied from jolene's property
JOBS = [
    {"id": "j1", "customer_id": "carl", "property_id": "p_jolene", "address": SNAPSHOT},
    {"id": "j2", "customer_id": "carl", "property_id": "p_jolene", "address": "Side gate, 27059 N 130th Dr"},
    {"id": "j3", "customer_id": "lynn", "property_id": "p_jolene", "address": SNAPSHOT},
    {"id": "j4", "customer_id": "toni_new", "property_id": "p_toni_old",
     "address": "5634 East Yolantha Street, Scottsdale, AZ 85266"},
    {"id": "j5", "customer_id": "jolene", "property_id": "p_jolene", "address": SNAPSHOT},
    {"id": "j6", "customer_id": "carl", "property_id": "p_ghost", "address": "1 Ghost Way, Peoria, AZ 85383"},
    {"id": "j7", "customer_id": "carl", "property_id": "p_jolene", "address": SNAPSHOT,
     "deleted_at": "2026-09-01T00:00:00+00:00"},
]
TEMPLATES = [{"id": "t1", "customer_id": "carl", "property_id": "p_jolene", "active": True}]


async def _scenario():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    name = f"test_t287998_{uuid.uuid4().hex[:10]}"
    tdb = client[name]
    real_db = mig.db
    mig.db = tdb
    try:
        await tdb.customers.insert_many([dict(c) for c in CUSTOMERS])
        await tdb.properties.insert_many([dict(p) for p in PROPERTIES])
        await tdb.jobs.insert_many([dict(dict(j, tenant_id=T), deleted_at=j.get("deleted_at")) for j in JOBS])
        await tdb.recurring_job_templates.insert_many([dict(t, tenant_id=T) for t in TEMPLATES])

        async def job(i):
            return await tdb.jobs.find_one({"id": i}, {"_id": 0})

        before = {j["id"]: await job(j["id"]) for j in JOBS}

        # --- dry run: reports, writes nothing ------------------------------
        dry = await mig.run(execute=False)
        assert dry["dry_run"] is True and dry["mismatched"] == 5  # template t1 + jobs j1 j2 j3 j6
        assert {j["id"]: await job(j["id"]) for j in JOBS} == before
        assert await tdb[mig.BACKUP_COLLECTION].count_documents({}) == 0
        assert await tdb[mig.MARKER_COLLECTION].count_documents({}) == 0

        # --- execute --------------------------------------------------------
        res = await mig.run(execute=True)
        assert res["errors"] == 0 and res["remaining_after"] == 0 and res.get("marker_stamped") is True
        assert res["skipped_merged"] >= 1

        j1 = await job("j1")
        assert j1["property_id"] == "p_carl" and j1["address"] == "27059 North 130th Drive, Peoria, AZ 85383"
        j2 = await job("j2")  # repointed, but custom address text preserved
        assert j2["property_id"] == "p_carl" and j2["address"] == "Side gate, 27059 N 130th Dr"
        j3 = await job("j3")  # lynn has no property: cleared, text -> her own address
        assert "property_id" not in j3 and j3["address"] == "11975 W Skinner Dr, Peoria, AZ 85383"
        assert await job("j4") == before["j4"]  # merged duplicate: untouched
        assert await job("j5") == before["j5"]  # healthy: untouched
        j6 = await job("j6")  # orphaned owner: still repaired
        assert j6["property_id"] == "p_carl"
        assert await job("j7") == before["j7"]  # soft-deleted: untouched
        t1 = await tdb.recurring_job_templates.find_one({"id": "t1"}, {"_id": 0})
        assert t1["property_id"] == "p_carl" and "address" not in t1
        for fixed in ("j1", "j2", "j3", "j6"):
            assert (await job(fixed))["updated_at"]  # delta-sync marker bumped

        # --- backups hold the ORIGINAL docs ---------------------------------
        assert await tdb[mig.BACKUP_COLLECTION].count_documents({}) == 5  # 4 jobs + 1 template
        b1 = await tdb[mig.BACKUP_COLLECTION].find_one({"collection": "jobs", "doc_id": "j1"})
        assert b1["doc"]["property_id"] == "p_jolene" and b1["doc"]["address"] == SNAPSHOT

        # --- idempotent: rerun (forced past the marker) changes nothing ------
        snap = {j["id"]: await job(j["id"]) for j in JOBS}
        again = await mig.run(execute=True, force=True)
        assert again["mismatched"] == 0 and again["repointed"] == 0 and again["cleared"] == 0
        assert {j["id"]: await job(j["id"]) for j in JOBS} == snap
        assert await tdb[mig.BACKUP_COLLECTION].count_documents({}) == 5
        b1b = await tdb[mig.BACKUP_COLLECTION].find_one({"collection": "jobs", "doc_id": "j1"})
        assert b1b["doc"]["address"] == SNAPSHOT  # first backup never overwritten

        # --- marker short-circuits normal boots; kill switch works ----------
        assert (await mig.run(execute=True))["skipped_by_marker"] is True
        os.environ["T287998_DISABLE"] = "1"
        try:
            assert (await mig.run(execute=True, force=True))["disabled"] is True
        finally:
            os.environ.pop("T287998_DISABLE", None)
    finally:
        mig.db = real_db
        await client.drop_database(name)
        client.close()


def test_migration_end_to_end_on_throwaway_db():
    asyncio.run(_scenario())


def test_plan_fix_is_pure_and_merge_aware():
    custs = {"a": {"id": "a", "address": "A addr"}, "b": {"id": "b", "merged_into": "a"}}
    prop = {"id": "pb", "customer_id": "b", "address": _addr("9 B St")}
    doc = {"customer_id": "a", "property_id": "pb", "address": "9 B St, Peoria, AZ 85383"}
    assert mig.plan_fix("jobs", doc, prop, custs, None)["action"] == "skipped_merged"
    assert mig.plan_fix("jobs", doc, prop, {"a": custs["a"]}, None)["action"] == "clear"
    assert mig.plan_fix("jobs", doc, prop, {}, None)["action"] == "skipped_no_customer"
    assert mig.same_customer("b", "a", custs) and not mig.same_customer("x", "a", custs)
