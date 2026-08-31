"""Feb-2026 · Notification bundle — edge-case probes (behaviour
characterisation, filed by the QA sweep).

These exercise reschedule-notification behaviour on job states that
arguably should NOT notify the customer:
  * status = completed / cancelled
  * new scheduled_date in the past (back-dating / data cleanup)
Currently the hook has no status or past-date gate, so a notification
fires. Marked xfail-style with explicit assertions so the developer
agent can decide the intended product behaviour.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_notif_pipeline_live_api import (  # noqa: E402
    DATE_B, TENANT_ID, _audit_rows, _login, _patch, _sync,
)


@pytest.fixture(scope="module")
def admin():
    return _login("admin@aquaterra.com")


def _mk(status, scheduled_date="2026-11-02"):
    m = uuid.uuid4().hex[:8]
    cid = f"TEST_NOTIF_cust_{m}"
    jid = f"TEST_NOTIF_job_{m}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": TENANT_ID,
        "name": f"TEST_NOTIF_Customer {m}",
        "email": f"test_notif_{m}@example.com",
        "phone": "+15558675309", "is_active": True,
    })
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_ID, "customer_id": cid,
        "title": f"TEST_NOTIF_Job {m}",
        "scheduled_date": scheduled_date,
        "service_type": "Weekly pool cleaning",
        "status": status,
    })
    return cid, jid


def _clean(cid, jid):
    _sync.customers.delete_many({"id": cid})
    _sync.jobs.delete_many({"id": jid})
    _sync.notifications_sent_log.delete_many({"job_id": jid})


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_reschedule_on_terminal_status_job(admin, status):
    headers, _ = admin
    cid, jid = _mk(status)
    try:
        r = _patch(headers, jid, {"scheduled_date": DATE_B})
        assert r.status_code == 200, r.text[:300]
        rows = _audit_rows(jid)
        print(f"[edge] status={status} audit_rows={len(rows)} "
              f"sent={rows[0]['channels_sent'] if rows else None}")
        assert rows, (
            f"documenting current behaviour: notification DOES fire for "
            f"status={status}")
    finally:
        _clean(cid, jid)


def test_reschedule_to_past_date(admin):
    headers, _ = admin
    cid, jid = _mk("scheduled", scheduled_date="2020-01-01")
    try:
        r = _patch(headers, jid, {"scheduled_date": "2020-02-01"})
        assert r.status_code == 200, r.text[:300]
        rows = _audit_rows(jid)
        print(f"[edge] past-date audit_rows={len(rows)} "
              f"sent={rows[0]['channels_sent'] if rows else None}")
        # Past-date move also stamps service_reminder_sent_at because
        # hours_until < 24 — verify that side effect.
        job = _sync.jobs.find_one({"id": jid}, {"_id": 0})
        print(f"[edge] service_reminder_sent_at="
              f"{job.get('service_reminder_sent_at')}")
        assert rows, "documenting current behaviour: past-date move notifies"
    finally:
        _clean(cid, jid)


def test_technician_reschedule_actor_recorded(admin):
    """A technician assigned to the job can PATCH scheduled_date; the
    audit actor must record the technician, not the admin."""
    headers, _ = admin
    tech = _sync.users.find_one({"email": "mike@aquaterra.com"}, {"_id": 0})
    cid, jid = _mk("scheduled")
    _sync.jobs.update_one({"id": jid}, {"$set": {
        "technician_id": tech["id"], "tech_user_id": tech["id"],
    }})
    tech_headers, tech_id = _login("mike@aquaterra.com")
    try:
        r = _patch(tech_headers, jid, {"scheduled_date": DATE_B})
        assert r.status_code == 200, r.text[:300]
        rows = _audit_rows(jid)
        assert len(rows) == 1, rows
        assert rows[0]["actor"] == f"user:{tech_id}", rows[0]["actor"]
    finally:
        _clean(cid, jid)
