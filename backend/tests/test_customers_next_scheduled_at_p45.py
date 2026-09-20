"""Feb-2026 · P45 — customers list hydrates ``next_scheduled_at``."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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
_TAG = "TEST_p45_"


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


def _seed_customer(tid: str, *, is_active: bool = True,
                       is_deleted: bool = False) -> str:
    cid = f"{_TAG}c-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"P45 {cid}", "last_name": f"{_TAG}ln",
        "email": f"{cid.lower()}@ex.com", "phone": "",
        "is_active": is_active,
        "status": "active" if is_active else "inactive",
    }
    if is_deleted:
        doc["deleted_at"] = "2026-03-01T00:00:00Z"
    _sync.customers.insert_one(doc)
    return cid


def _seed_job(tid: str, cid: str, *, scheduled_date: str | None,
                  status: str = "scheduled",
                  is_deleted: bool = False) -> str:
    jid = f"{_TAG}j-{uuid.uuid4().hex[:10]}"
    doc = {
        "id": jid, "tenant_id": tid, "customer_id": cid,
        "status": status, "scheduled_date": scheduled_date,
        "service_type": "P45 Test",
    }
    if is_deleted:
        doc["deleted_at"] = "2026-03-01T00:00:00Z"
    _sync.jobs.insert_one(doc)
    return jid


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _shift_iso(days: int) -> str:
    return (datetime.now(timezone.utc)
              + timedelta(days=days)).strftime("%Y-%m-%dT09:00:00+00:00")


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        cids = [c["id"] for c in _sync.customers.find(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}},
            {"_id": 0, "id": 1})]
        if cids:
            _sync.jobs.delete_many({"tenant_id": aquaterra_tid,
                                          "customer_id": {"$in": cids}})
            _sync.customers.delete_many(
                {"tenant_id": aquaterra_tid, "id": {"$in": cids}})
        _sync.jobs.delete_many({"id": {"$regex": f"^{_TAG}"}})
    _reset(); yield; _reset()


def _fetch_customer(admin_h, cid: str) -> dict | None:
    r = requests.get(
        f"{API}/customers?is_active=true&page=1&page_size=500",
        headers=admin_h, timeout=15).json()
    for c in r.get("items", []):
        if c["id"] == cid:
            return c
    return None


# ── Positive: aggregate populates the field ─────────────────────────
def test_upcoming_scheduled_job_populates_field(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(3),
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    assert row is not None
    assert row["next_scheduled_at"] == _shift_iso(3)


def test_pending_status_also_populates(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(5),
                 status="pending")
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] == _shift_iso(5)


def test_earliest_of_multiple_upcoming_jobs(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(10),
                 status="scheduled")
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(2),
                 status="pending")   # earliest — should win
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(7),
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] == _shift_iso(2)


# ── Negative: terminal statuses ignored ─────────────────────────────
@pytest.mark.parametrize("terminal", [
    "completed", "could_not_service", "cancelled", "canceled",
    "no_show", "missed", "skipped",
])
def test_terminal_status_never_populates(
        admin_h, aquaterra_tid, terminal):
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(3),
                 status=terminal)
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] is None


# ── Date filter: past-dated ignored, today's INCLUDED ──────────────
def test_past_dated_job_never_populates(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    yesterday = (datetime.now(timezone.utc)
                    - timedelta(days=1)).strftime("%Y-%m-%dT09:00:00+00:00")
    _seed_job(aquaterra_tid, cid, scheduled_date=yesterday,
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] is None


def test_todays_job_is_included(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    today_iso = _today_iso() + "T09:00:00+00:00"
    _seed_job(aquaterra_tid, cid, scheduled_date=today_iso,
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] == today_iso


# ── Soft-deleted jobs ignored ──────────────────────────────────────
def test_soft_deleted_job_never_populates(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(4),
                 status="scheduled", is_deleted=True)
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] is None


# ── Tenant scoping ─────────────────────────────────────────────────
def test_cross_tenant_leak_is_impossible(admin_h, aquaterra_tid):
    # Pick a different tenant's id if one exists; otherwise fabricate.
    other = _sync.users.find_one(
        {"tenant_id": {"$ne": aquaterra_tid}}, {"_id": 0, "tenant_id": 1})
    other_tid = (other or {}).get("tenant_id") or "TENANT_p45_other"

    cid = _seed_customer(aquaterra_tid)
    # Seed a job in the OTHER tenant that targets our aquaterra
    # customer id. Even though customer_id would match, tenant_id
    # scoping in the $match must exclude it.
    _seed_job(other_tid, cid, scheduled_date=_shift_iso(1),
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    assert row["next_scheduled_at"] is None


# ── Heterogeneous scheduled_date shapes ────────────────────────────
def test_full_iso_and_date_only_both_recognized(
        admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    # date-only (2 days out) — should still win because it sorts
    # LEXICOGRAPHICALLY before the full-ISO for 3 days out.
    date_only = (datetime.now(timezone.utc)
                     + timedelta(days=2)).strftime("%Y-%m-%d")
    _seed_job(aquaterra_tid, cid, scheduled_date=date_only,
                 status="scheduled")
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(3),
                 status="scheduled")
    row = _fetch_customer(admin_h, cid)
    # $first after ascending sort → the 2-day date-only value wins.
    assert row["next_scheduled_at"] == date_only


# ── Empty case ─────────────────────────────────────────────────────
def test_no_upcoming_jobs_returns_null_field(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    row = _fetch_customer(admin_h, cid)
    assert row is not None
    assert row.get("next_scheduled_at") is None


# ── Pagination compatibility (page 2 rows also hydrated) ───────────
def test_pagination_page2_rows_get_hydrated(admin_h, aquaterra_tid):
    """Seed 6 customers with an upcoming job each and page through
    with a page_size of 3 so at least one seeded row lands on page 2.
    Assert hydration works regardless of page."""
    cids = []
    for _ in range(6):
        cid = _seed_customer(aquaterra_tid)
        _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(4),
                     status="scheduled")
        cids.append(cid)

    def _grab_all_pages():
        found: dict[str, str | None] = {}
        page = 1
        while True:
            r = requests.get(
                f"{API}/customers?is_active=true"
                f"&page={page}&page_size=3",
                headers=admin_h, timeout=15).json()
            items = r.get("items", [])
            for c in items:
                if c["id"] in cids:
                    found[c["id"]] = c.get("next_scheduled_at")
            if page >= r.get("total_pages", 1):
                break
            page += 1
        return found

    got = _grab_all_pages()
    # All 6 seeded rows must be hydrated identically regardless of
    # which page they landed on.
    assert len(got) == 6
    for cid, val in got.items():
        assert val == _shift_iso(4), (
            f"customer {cid} missing next_scheduled_at hydration on "
            f"paged response")


# ── count_only branch is NOT hydrated ──────────────────────────────
def test_count_only_branch_returns_no_hydration(
        admin_h, aquaterra_tid):
    """count_only returns ``{count}`` — no items, no per-row hydration."""
    cid = _seed_customer(aquaterra_tid)
    _seed_job(aquaterra_tid, cid, scheduled_date=_shift_iso(2),
                 status="scheduled")
    r = requests.get(
        f"{API}/customers?is_active=true&count_only=true",
        headers=admin_h, timeout=15).json()
    assert "count" in r
    assert "items" not in r
