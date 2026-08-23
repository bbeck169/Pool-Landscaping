"""Feb-2026 · P47 — quarterly + semi_annual recurrence cadences."""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"
_TAG = "TEST_p47_"


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


@pytest.fixture
def seed_customer(admin_h, aquaterra_tid):
    cid = f"{_TAG}c-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": aquaterra_tid,
        "name": f"P47 {cid}", "last_name": f"{_TAG}ln",
        "is_active": True,
    })
    yield cid
    _sync.customers.delete_one({"id": cid})


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        tpls = list(_sync.recurring_job_templates.find(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}},
            {"_id": 0, "id": 1}))
        for t in tpls:
            _sync.jobs.delete_many({"recurring_template_id": t["id"]})
        _sync.recurring_job_templates.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": f"^{_TAG}"}})
    _reset(); yield; _reset()


def _mk_template(admin_h, seed_customer, **overrides):
    body = {
        "customer_id": seed_customer,
        "service_type": "Weekly Clean",
        "start_date": "2026-01-15",
        "frequency": "quarterly",
        "day_of_month": 15,
        **overrides,
    }
    return requests.post(f"{API}/recurring-jobs",
                            headers={**admin_h,
                                        "Content-Type": "application/json"},
                            json=body, timeout=15)


def _rename_for_cleanup(tpl_id: str) -> str:
    """Tag the freshly-created template with our prefix so ``_cleanup``
    catches it (create endpoint assigns a random uuid)."""
    tagged = f"{_TAG}{tpl_id}"
    _sync.recurring_job_templates.update_one(
        {"id": tpl_id}, {"$set": {"id": tagged}})
    return tagged


def _expand(admin_h, template_id: str, through_iso: str) -> list[str]:
    r = requests.post(
        f"{API}/recurring-jobs/{template_id}/generate"
        f"?through={through_iso}",
        headers=admin_h, timeout=30)
    assert r.status_code == 200, r.text
    return sorted(r.json().get("dates") or [])


# ── Quarterly happy path ────────────────────────────────────────────
def test_quarterly_creates_and_expands_four_dates(admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="quarterly", day_of_month=15,
                        start_date="2026-01-15")
    assert r.status_code == 200, r.text
    tpl_id = _rename_for_cleanup(r.json()["id"])
    dates = _expand(admin_h, tpl_id, "2027-01-31")
    # Jan 15, Apr 15, Jul 15, Oct 15, Jan 15
    assert dates[:5] == ["2026-01-15", "2026-04-15", "2026-07-15",
                             "2026-10-15", "2027-01-15"]


# ── Semi-annual happy path ─────────────────────────────────────────
def test_semi_annual_expands_two_dates_per_year(admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="semi_annual", day_of_month=1,
                        start_date="2026-01-01")
    assert r.status_code == 200, r.text
    tpl_id = _rename_for_cleanup(r.json()["id"])
    dates = _expand(admin_h, tpl_id, "2027-12-31")
    assert dates == ["2026-01-01", "2026-07-01",
                        "2027-01-01", "2027-07-01"]


# ── Month-length clamp: Jan 31 + quarterly ─────────────────────────
def test_month_length_clamp_quarterly_from_jan_31(
        admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="quarterly", day_of_month=31,
                        start_date="2026-01-31")
    tpl_id = _rename_for_cleanup(r.json()["id"])
    dates = _expand(admin_h, tpl_id, "2027-02-28")
    # Jan 31 → Apr 30 (clamped) → Jul 31 → Oct 31 → Jan 31, 2027
    assert dates == ["2026-01-31", "2026-04-30",
                        "2026-07-31", "2026-10-31", "2027-01-31"]


# ── Leap-day clamp: Feb 29 + semi_annual ───────────────────────────
def test_leap_day_clamp_semi_annual(admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="semi_annual", day_of_month=29,
                        start_date="2028-02-29")   # 2028 is a leap year
    tpl_id = _rename_for_cleanup(r.json()["id"])
    dates = _expand(admin_h, tpl_id, "2029-08-31")
    # Feb 29 2028 → Aug 29 2028 (Aug has 31, unchanged)
    #             → Feb 28 2029 (non-leap, clamped)
    #             → Aug 29 2029
    assert dates == ["2028-02-29", "2028-08-29",
                        "2029-02-28", "2029-08-29"]


# ── Missing day_of_month → 422 ──────────────────────────────────────
def test_quarterly_without_day_of_month_returns_422(
        admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="quarterly", day_of_month=None,
                        start_date="2026-01-15")
    assert r.status_code == 422, r.text


# ── nth_weekday not supported for new cadences → 422 ───────────────
def test_quarterly_with_nth_weekday_returns_422(admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="quarterly", day_of_month=15,
                        monthly_pattern="nth_weekday",
                        monthly_nth_week="first",
                        monthly_weekday=0,
                        start_date="2026-01-15")
    assert r.status_code == 422, r.text


# ── Idempotent re-expansion (unique index preserved) ───────────────
def test_expansion_is_idempotent_on_rerun(admin_h, seed_customer):
    r = _mk_template(admin_h, seed_customer,
                        frequency="quarterly", day_of_month=15,
                        start_date="2026-01-15")
    tpl_id = _rename_for_cleanup(r.json()["id"])
    _expand(admin_h, tpl_id, "2027-01-31")
    n1 = _sync.jobs.count_documents({"recurring_template_id": tpl_id})
    # Re-expand across the same horizon.
    _expand(admin_h, tpl_id, "2027-01-31")
    n2 = _sync.jobs.count_documents({"recurring_template_id": tpl_id})
    assert n1 == n2 >= 5


# ── Preview endpoint (create-form hint) ────────────────────────────
def test_preview_endpoint_quarterly(admin_h):
    r = requests.post(f"{API}/jobs/recurrence-preview",
                         headers={**admin_h,
                                     "Content-Type": "application/json"},
                         json={"cadence": "quarterly",
                                  "count": 4,
                                  "start_date": "2026-01-15"},
                         timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["dates"] == ["2026-01-15", "2026-04-15",
                                            "2026-07-15", "2026-10-15"]


def test_preview_endpoint_semi_annual(admin_h):
    r = requests.post(f"{API}/jobs/recurrence-preview",
                         headers={**admin_h,
                                     "Content-Type": "application/json"},
                         json={"cadence": "semi_annual",
                                  "count": 4,
                                  "start_date": "2026-01-01"},
                         timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["dates"] == ["2026-01-01", "2026-07-01",
                                            "2027-01-01", "2027-07-01"]
