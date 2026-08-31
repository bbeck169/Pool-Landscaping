"""Phase F2 — direct DB assertions on the repair side-effects."""
import os

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or _env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _env.get("DB_NAME")


@pytest.fixture(scope="module")
def dbc():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def test_repair_rows_shape(dbc):
    rows = list(dbc.data_integrity_repairs.find({}, {"_id": 0}))
    assert rows, "no rows in data_integrity_repairs — apply never persisted"
    for r in rows:
        assert r["class"] in {"orphaned_customer_ref", "orphaned_technician_ref"}
        assert r["action"] in {"soft_delete", "null_technician_id"}
        assert r["target_collection"] == "jobs"
        assert r.get("run_id") and r.get("target_id") and r.get("id")
        assert "before" in r and "after" in r
    print("repair rows:", len(rows),
          "runs:", len({r["run_id"] for r in rows}))


def test_unique_index_present(dbc):
    idx = dbc.data_integrity_repairs.index_information()
    uniq = [n for n, v in idx.items()
            if v.get("unique") and sorted(k for k, _ in v["key"]) == ["run_id", "target_id"]]
    assert uniq, f"missing unique (run_id,target_id) index: {list(idx)}"


def test_soft_deleted_jobs_carry_repair_reason(dbc):
    targets = [r["target_id"] for r in dbc.data_integrity_repairs.find(
        {"class": "orphaned_customer_ref"}, {"_id": 0, "target_id": 1})]
    assert targets
    jobs = list(dbc.jobs.find({"id": {"$in": targets}}, {"_id": 0}))
    assert len(jobs) == len(set(targets))
    for j in jobs:
        assert j.get("status") == "deleted", (j["id"], j.get("status"))
        assert j.get("deleted_at")
        assert j.get("deleted_reason") == "data_repair_orphaned_customer"
        assert j.get("deleted_by_user_id")


def test_scan_records_have_expiry(dbc):
    scans = list(dbc.data_integrity_scans.find({}, {"_id": 0}).limit(5))
    assert scans, "no scan records persisted"
    for s in scans:
        assert s.get("confirm_token") and s.get("scan_timestamp")
        assert s.get("expires_at") and s.get("created_at")
        assert (s["expires_at"] - s["created_at"]).total_seconds() == 900
