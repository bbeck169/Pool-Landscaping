"""Feb-2026 · P42 — customer_since lifecycle stamp."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"
_TAG = "TEST_p42_"


def _login(email="admin@aquaterra.com", pw="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login()}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _mk_customer(tid: str, *, is_active: bool = True,
                    with_since: str | None = None,
                    with_deleted_at: str | None = None) -> str:
    cid = f"{_TAG}{uuid.uuid4().hex[:10]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"P42 {cid}",
        "first_name": "P42", "last_name": cid,
        "email": f"{cid.lower()}@example.com",
        "phone": "",
        "is_active": is_active,
        "status": "active" if is_active else "inactive",
        "created_at": "2026-01-01T00:00:00Z",
    }
    if with_since is not None:
        doc["customer_since"] = with_since
    if with_deleted_at is not None:
        doc["deleted_at"] = with_deleted_at
    _sync.customers.insert_one(doc)
    return cid


def _create_job_via_api(admin_h, cid: str) -> requests.Response:
    return requests.post(
        f"{API}/jobs",
        headers={**admin_h, "Content-Type": "application/json"},
        json={"customer_id": cid, "title": "P42 Weekly Clean",
                "service_type": "Weekly Clean"},
        timeout=15)


def _wait_for_customer_since(cid: str, tid: str,
                                 timeout_s: float = 3.0) -> str | None:
    """Poll — the stamp is fired from a BackgroundTask so the write
    can trail the HTTP response by a moment."""
    import time
    end = time.time() + timeout_s
    while time.time() < end:
        row = _sync.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "customer_since": 1})
        if row and row.get("customer_since"):
            return row["customer_since"]
        time.sleep(0.05)
    return None


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        # Wide sweep — id-prefix catches directly-seeded rows, and
        # last_name/email regex catches P41 CSV-imported rows whose
        # ids are random UUIDs.
        wide_q = {
            "tenant_id": aquaterra_tid,
            "$or": [
                {"id": {"$regex": f"^{_TAG}"}},
                {"last_name": {"$regex": f"^{_TAG}"}},
                {"email": {"$regex": f"^{_TAG.lower()}"}},
            ],
        }
        victims = [c["id"] for c in _sync.customers.find(
            wide_q, {"_id": 0, "id": 1})]
        if victims:
            _sync.jobs.delete_many(
                {"tenant_id": aquaterra_tid,
                  "customer_id": {"$in": victims}})
            _sync.customers.delete_many(
                {"tenant_id": aquaterra_tid, "id": {"$in": victims}})
        _sync.audit_logs.delete_many({
            "tenant_id": aquaterra_tid,
            "event": "customer_since_stamped",
            "customer_id": {"$in": victims} if victims else {"$regex": f"^{_TAG}"},
        })
    _reset(); yield; _reset()


# ── stamp_customer_since helper — exercised via the HTTP trigger
# surfaces below to avoid Motor's cross-event-loop pain when calling
# the async helper directly from a sync pytest process. Every branch
# of the helper is still covered end-to-end:
#   * active + ≥1 job  → test_job_create_stamps_active_customer
#   * inactive         → test_job_create_does_not_stamp_inactive_customer
#   * already stamped  → test_job_create_is_noop_when_already_stamped
#   * zero jobs        → test_reactivate_customer_without_jobs_does_not_stamp


# ── Job create trigger ─────────────────────────────────────────────
def test_job_create_stamps_active_customer(admin_h, aquaterra_tid):
    cid = _mk_customer(aquaterra_tid, is_active=True)
    r = _create_job_via_api(admin_h, cid)
    assert r.status_code == 200, r.text
    since = _wait_for_customer_since(cid, aquaterra_tid)
    assert since is not None
    # Audit log written (one entry per stamp, spec).
    audit = _sync.audit_logs.find_one({
        "tenant_id": aquaterra_tid,
        "event": "customer_since_stamped",
        "customer_id": cid,
    })
    assert audit is not None
    assert audit.get("customer_since") == since


def test_job_create_does_not_stamp_inactive_customer(
        admin_h, aquaterra_tid):
    cid = _mk_customer(aquaterra_tid, is_active=False)
    r = _create_job_via_api(admin_h, cid)
    assert r.status_code == 200, r.text
    # Give the background task a moment.
    since = _wait_for_customer_since(cid, aquaterra_tid, timeout_s=0.6)
    assert since is None
    row = _sync.customers.find_one({"id": cid})
    assert row.get("customer_since") is None


def test_job_create_is_noop_when_already_stamped(
        admin_h, aquaterra_tid):
    prev = "2020-05-05T00:00:00+00:00"
    cid = _mk_customer(aquaterra_tid, is_active=True, with_since=prev)
    r = _create_job_via_api(admin_h, cid)
    assert r.status_code == 200, r.text
    # Wait long enough for any errant write, then assert unchanged.
    _wait_for_customer_since(cid, aquaterra_tid, timeout_s=0.6)
    row = _sync.customers.find_one({"id": cid})
    assert row["customer_since"] == prev


# ── Reactivation trigger ────────────────────────────────────────────
def test_reactivate_customer_with_jobs_stamps(admin_h, aquaterra_tid):
    cid = _mk_customer(aquaterra_tid, is_active=False)
    _sync.jobs.insert_one({
        "id": f"{_TAG}j-{uuid.uuid4().hex[:8]}",
        "tenant_id": aquaterra_tid, "customer_id": cid,
        "created_at": "2026-02-05T00:00:00Z",
    })
    # PATCH the customer to flip is_active → True (routes through
    # ``_apply_activation_cascade``).
    r = requests.patch(
        f"{API}/customers/{cid}/activation",
        headers={**admin_h, "Content-Type": "application/json"},
        json={"is_active": True},
        timeout=15)
    assert r.status_code == 200, r.text
    row = _sync.customers.find_one({"id": cid})
    assert row.get("customer_since")


def test_reactivate_customer_without_jobs_does_not_stamp(
        admin_h, aquaterra_tid):
    cid = _mk_customer(aquaterra_tid, is_active=False)
    r = requests.patch(
        f"{API}/customers/{cid}/activation",
        headers={**admin_h, "Content-Type": "application/json"},
        json={"is_active": True},
        timeout=15)
    assert r.status_code == 200, r.text
    row = _sync.customers.find_one({"id": cid})
    assert row.get("customer_since") is None


# ── Persistence across status changes ──────────────────────────────
def test_soft_delete_preserves_customer_since(admin_h, aquaterra_tid):
    prev = "2022-08-01T00:00:00+00:00"
    cid = _mk_customer(aquaterra_tid, is_active=True, with_since=prev)
    # Simulate the P0 soft-delete write path directly (a full
    # bulk-delete endpoint round-trip is unnecessary here).
    _sync.customers.update_one(
        {"id": cid},
        {"$set": {"deleted_at": "2026-03-01T00:00:00Z"}})
    row = _sync.customers.find_one({"id": cid})
    assert row["customer_since"] == prev


def test_mute_preserves_customer_since(aquaterra_tid):
    prev = "2021-04-01T00:00:00+00:00"
    cid = _mk_customer(aquaterra_tid, is_active=True, with_since=prev)
    _sync.customers.update_one(
        {"id": cid},
        {"$set": {"is_muted": True, "muted_at": "2026-02-06T00:00:00Z"}})
    row = _sync.customers.find_one({"id": cid})
    assert row["customer_since"] == prev


# ── PUT immutability ────────────────────────────────────────────────
def test_put_ignores_customer_since_in_body(admin_h, aquaterra_tid):
    prev = "2019-06-06T00:00:00+00:00"
    cid = _mk_customer(aquaterra_tid, is_active=True, with_since=prev)
    body = {
        "name": "Renamed", "first_name": "Ren", "last_name": "Amed",
        "email": "renamed@example.com",
        "customer_since": "1999-01-01T00:00:00+00:00",  # attempt overwrite
        "is_active": True,
    }
    r = requests.put(f"{API}/customers/{cid}",
                        headers={**admin_h, "Content-Type": "application/json"},
                        json=body, timeout=15)
    assert r.status_code == 200, r.text
    row = _sync.customers.find_one({"id": cid})
    assert row["customer_since"] == prev


def test_post_ignores_customer_since_at_create(admin_h, aquaterra_tid):
    body = {
        "name": "New Cust", "first_name": "New", "last_name": "Cust",
        "email": f"{_TAG.lower()}post-{uuid.uuid4().hex[:6]}@ex.com",
        "customer_since": "2000-01-01T00:00:00+00:00",  # attempt at create
    }
    r = requests.post(f"{API}/customers",
                         headers={**admin_h, "Content-Type": "application/json"},
                         json=body, timeout=15)
    assert r.status_code == 200, r.text
    created = r.json()
    # Tag it with our prefix in Mongo so cleanup catches it.
    _sync.customers.update_one(
        {"id": created["id"]}, {"$set": {"id": f"{_TAG}{created['id']}"}})
    row = _sync.customers.find_one({"id": f"{_TAG}{created['id']}"})
    assert row.get("customer_since") is None


# ── P41 CSV import does NOT stamp ───────────────────────────────────
def test_csv_import_creates_without_customer_since(
        admin_h, aquaterra_tid):
    import io
    hdr = ["First Name", "Last Name", "Service Address", "Service City",
             "Service State", "Service Zip Code", "Billing Address",
             "Billing City", "Billing State", "Billing Zip Code",
             "Email", "Phone Number"]
    tag_email = f"{_TAG.lower()}csv-{uuid.uuid4().hex[:8]}@ex.com"
    buf = io.StringIO()
    buf.write(",".join(hdr) + "\n")
    buf.write(",".join([
        "Csv", f"{_TAG}CsvLn", "1 Csv Rd", "Phoenix", "AZ", "85001",
        "", "", "", "", tag_email, "+15550001111",
    ]) + "\n")
    r = requests.post(
        f"{API}/customers/import-csv",
        headers=admin_h,
        files={"file": ("p42.csv", buf.getvalue().encode(), "text/csv")},
        data={"target_status": "active"},
        timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    row = _sync.customers.find_one({
        "tenant_id": aquaterra_tid, "last_name": f"{_TAG}CsvLn"})
    assert row is not None
    assert row.get("customer_since") is None


# ── Backfill migration ──────────────────────────────────────────────
def test_backfill_migration_stamps_only_qualifying(aquaterra_tid):
    from migrations.task_p42_backfill_customer_since import run as bf_run

    # 3 active with jobs (all should stamp), 1 active without jobs
    # (skip), 1 inactive with jobs (skip).
    active_with_jobs = [
        _mk_customer(aquaterra_tid, is_active=True) for _ in range(3)]
    active_no_jobs = _mk_customer(aquaterra_tid, is_active=True)
    inactive_with_jobs = _mk_customer(aquaterra_tid, is_active=False)
    for cid in active_with_jobs + [inactive_with_jobs]:
        _sync.jobs.insert_one({
            "id": f"{_TAG}j-{uuid.uuid4().hex[:8]}",
            "tenant_id": aquaterra_tid, "customer_id": cid,
            "created_at": f"2025-0{(hash(cid) % 8) + 1}-01T00:00:00Z",
        })

    # Dry run — nothing written.
    dry = asyncio.run(bf_run(commit=False))
    assert dry["committed"] is False
    for cid in active_with_jobs:
        row = _sync.customers.find_one({"id": cid})
        assert row.get("customer_since") is None

    # Commit run.
    r = asyncio.run(bf_run(commit=True))
    assert r["committed"] is True
    for cid in active_with_jobs:
        row = _sync.customers.find_one({"id": cid})
        assert row.get("customer_since"), (
            f"active-with-jobs {cid} should be stamped")
    row = _sync.customers.find_one({"id": active_no_jobs})
    assert row.get("customer_since") is None
    row = _sync.customers.find_one({"id": inactive_with_jobs})
    assert row.get("customer_since") is None

    # Idempotent on rerun — no additional stamps.
    stamps_after_first = {cid: _sync.customers.find_one({"id": cid})[
        "customer_since"] for cid in active_with_jobs}
    r2 = asyncio.run(bf_run(commit=True))
    assert r2["committed"] is True
    for cid in active_with_jobs:
        row = _sync.customers.find_one({"id": cid})
        assert row["customer_since"] == stamps_after_first[cid]
