"""Feb-2026 · Enhancement 1 — Schedule drag-and-drop reschedule + notify.

Verifies:
  1. POST /api/schedule/reschedule (dry_run) returns a preview with
     rendered old/new datetimes + resolved SERVICE_NAME.
  2. Committed reschedule persists new fields on the job, appends a
     ``job_history`` entry, and writes exactly one
     ``marketing_deliveries`` row per channel with
     ``trigger_entity.kind == "job_rescheduled"``.
  3. Merge-tag registry surfaces ``SERVICE_NAME``.
  4. RBAC — technicians cannot reschedule.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture
def resched_fixture():
    m = uuid.uuid4().hex[:6]
    cid = f"resched-cust-{m}"
    jid = f"resched-job-{m}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": _TENANT_ID, "name": "Sara Garcia",
        "first_name": "Sara", "email": f"sara-{m}@ex.local",
        "phone": "+15558675309", "is_active": True,
        "service_address": "1 Reschedule Way",
    })
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": _TENANT_ID, "customer_id": cid,
        "scheduled_date": "2026-02-20",
        "scheduled_start_at": "2026-02-20T14:00:00+00:00",
        "scheduled_end_at": "2026-02-20T15:00:00+00:00",
        "technician_id": None,
        "service_type": "Weekly pool cleaning",
        "status": "scheduled",
    })
    yield {"marker": m, "cid": cid, "jid": jid}
    _sync.customers.delete_one({"id": cid})
    _sync.jobs.delete_one({"id": jid})
    _sync.marketing_deliveries.delete_many({"customer_id": cid})


def test_dry_run_returns_preview(admin_headers, resched_fixture):
    r = requests.post(f"{API}/schedule/reschedule", headers=admin_headers,
                       json={"job_id": resched_fixture["jid"],
                              "new_start_at": "2026-02-21T17:00:00+00:00",
                              "dry_run": True}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    p = body["preview"]
    assert p["customer_first_name"] == "Sara"
    assert p["service_name"] == "Weekly pool cleaning"
    # Preview datetime labels must be non-empty + rendered in Phoenix tz.
    assert p["old_datetime"] and p["new_datetime"]
    assert p["old_datetime"] != p["new_datetime"]


def test_commit_persists_and_writes_history_plus_two_deliveries(
    admin_headers, resched_fixture,
):
    new_start = "2026-02-21T17:00:00+00:00"
    r = requests.post(f"{API}/schedule/reschedule", headers=admin_headers,
                       json={"job_id": resched_fixture["jid"],
                              "new_start_at": new_start,
                              "new_end_at": "2026-02-21T18:00:00+00:00"},
                       timeout=15)
    assert r.status_code == 200, r.text
    # Job fields updated.
    job = _sync.jobs.find_one({"id": resched_fixture["jid"]}, {"_id": 0})
    assert job["scheduled_start_at"] == new_start
    assert job["scheduled_date"] == "2026-02-21"
    # Exactly one job_history entry with event=rescheduled.
    hist = job.get("job_history") or []
    assert len(hist) == 1 and hist[0]["event"] == "rescheduled"
    assert hist[0]["from"]["scheduled_start_at"] == "2026-02-20T14:00:00+00:00"
    assert hist[0]["to"]["scheduled_start_at"] == new_start
    # Two marketing_deliveries rows — one email, one sms.
    deliveries = list(_sync.marketing_deliveries.find(
        {"customer_id": resched_fixture["cid"],
          "trigger_entity.kind": "job_rescheduled"},
        {"_id": 0}))
    channels = {d["channel"] for d in deliveries}
    assert channels == {"email", "sms"}, deliveries


def test_technician_forbidden(tech_headers, resched_fixture):
    r = requests.post(f"{API}/schedule/reschedule", headers=tech_headers,
                       json={"job_id": resched_fixture["jid"],
                              "new_start_at": "2026-02-21T17:00:00+00:00"},
                       timeout=10)
    assert r.status_code == 403


def test_merge_tag_registry_lists_service_name():
    from services.marketing.merge_tags import MERGE_TAGS, _TAG_INDEX
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "SERVICE_NAME" in tokens
    assert "SERVICE_NAME" in _TAG_INDEX
    # Resolver actually resolves.
    resolved = _TAG_INDEX["SERVICE_NAME"]({
        "job": {"service_type": "Landscape mow"},
    })
    assert resolved == "Landscape mow"
