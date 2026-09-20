"""Feb-2026 · Notification bundle — LIVE preview-API verification.

Covers the review-request matrix for the service-notifications
pipeline against the running backend (preview URL) + real Mongo:

  1. PUT /api/jobs/{jid} scheduled_date A→B  → notifications_sent_log
     row (template_key=reschedule_service, transition_key='A→B',
     actor='user:<admin id>').
  2. No-change PATCH + repeat transition → transition-key idempotency
     (no second audit row).
  3. sms_opt_in=False customer → channels_skipped has
     'sms:hard_opt_out'.
  4. customer with no phone → channels_skipped has 'sms:no_address'.
  5. PATCH title/notes only → no audit row.
  6. register_service_reminder_cron(mock scheduler) → one add_job with
     id='service_reminder_cron', minute=0.
  7. Reminder cron pickup window + idempotency stamp (exercised via
     _due_reminder_jobs_for_tenant + fire_reminder_for_job so we never
     touch production jobs the way a full cron_tick() sweep would).
  8. Identity guard — job pointing at a missing customer → PATCH still
     200, no audit row.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BACKEND_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_FRONT_ENV = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or _FRONT_ENV.get("REACT_APP_BACKEND_URL"))
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = BASE_URL.rstrip("/") + "/api"

_sync = _shared_db()
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
TENANT_ID = _TENANT["id"]
TENANT_TZ = (_TENANT.get("timezone") or "America/Phoenix")

DATE_A = "2026-11-02"
DATE_B = "2026-11-09"
DATE_C = "2026-11-16"


def _loop():
    return asyncio.get_event_loop()


def _run(coro):
    return _loop().run_until_complete(coro)


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=90)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    body = r.json()
    return ({"Authorization": f"Bearer {body['access_token']}"},
            body["user"]["id"])


@pytest.fixture(scope="module")
def admin():
    return _login("admin@aquaterra.com")


def _audit_rows(job_id):
    return list(_sync.notifications_sent_log.find(
        {"job_id": job_id}, {"_id": 0}).sort("sent_at", 1))


def _mk_fixture(*, phone="+15558675309", email=None, sms_opt_in=None,
                customer_id=None, scheduled_date=DATE_A,
                notification_preferences=None):
    """Insert a TEST_NOTIF_ customer + job pair. Returns (cid, jid)."""
    m = uuid.uuid4().hex[:8]
    cid = customer_id or f"TEST_NOTIF_cust_{m}"
    jid = f"TEST_NOTIF_job_{m}"
    cust = {
        "id": cid, "tenant_id": TENANT_ID,
        "name": f"TEST_NOTIF_Customer {m}",
        "first_name": "TESTNOTIF",
        "email": email if email is not None else f"test_notif_{m}@example.com",
        "phone": phone, "is_active": True,
        "service_address": "1 Notification Way",
    }
    if sms_opt_in is not None:
        cust["sms_opt_in"] = sms_opt_in
    if notification_preferences is not None:
        cust["notification_preferences"] = notification_preferences
    _sync.customers.insert_one(cust)
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_ID, "customer_id": cid,
        "title": f"TEST_NOTIF_Job {m}",
        "scheduled_date": scheduled_date,
        "service_type": "Weekly pool cleaning",
        "status": "scheduled",
    })
    return cid, jid


def _cleanup(cid, jid):
    _sync.customers.delete_many({"id": cid})
    _sync.jobs.delete_many({"id": jid})
    _sync.notifications_sent_log.delete_many({"job_id": jid})


def _patch(headers, jid, payload):
    return requests.put(f"{API}/jobs/{jid}", headers=headers,
                        json=payload, timeout=60)


# ═════════════════════════════════════════════════════════════════
# 1 · Reschedule hook writes the audit row
# ═════════════════════════════════════════════════════════════════
def test_reschedule_writes_audit_row(admin):
    headers, admin_id = admin
    cid, jid = _mk_fixture()
    try:
        r = _patch(headers, jid, {"scheduled_date": DATE_B})
        assert r.status_code == 200, r.text[:400]
        rows = _audit_rows(jid)
        assert len(rows) == 1, f"expected 1 audit row, got {len(rows)}: {rows}"
        row = rows[0]
        assert row["template_key"] == "reschedule_service"
        assert row["transition_key"] == f"{DATE_A}→{DATE_B}"
        assert row["actor"] == f"user:{admin_id}", row["actor"]
        assert row["tenant_id"] == TENANT_ID
        assert row["customer_id"] == cid
        assert "_id" not in row
        assert row.get("old_scheduled_at") and row.get("new_scheduled_at")
        # SMS is mocked in dev → counted as sent.
        assert "sms" in row["channels_sent"], (
            f"sms not sent: sent={row['channels_sent']} "
            f"skipped={row['channels_skipped']}")
        # Email: env-dependent (comms whitelist gate / Resend key).
        print(f"[audit] channels_sent={row['channels_sent']} "
              f"channels_skipped={row['channels_skipped']}")
        email_ok = ("email" in row["channels_sent"]
                    or any(s.startswith("email:")
                           for s in row["channels_skipped"]))
        assert email_ok, "email channel neither sent nor accounted for"
    finally:
        _cleanup(cid, jid)


def test_reschedule_email_channel_actually_sends(admin):
    """Resend rejects ``example.com`` recipients, so use Resend's own
    sandbox address to prove the email branch reaches ``status='sent'``
    and lands in ``channels_sent``. Also measures the PATCH latency the
    inline provider call adds."""
    headers, _ = admin
    cid, jid = _mk_fixture(email="delivered@resend.dev")
    try:
        t0 = datetime.now()
        r = _patch(headers, jid, {"scheduled_date": DATE_B})
        elapsed = (datetime.now() - t0).total_seconds()
        assert r.status_code == 200, r.text[:300]
        rows = _audit_rows(jid)
        assert len(rows) == 1
        print(f"[email-live] sent={rows[0]['channels_sent']} "
              f"skipped={rows[0]['channels_skipped']} "
              f"patch_latency={elapsed:.2f}s")
        assert "email" in rows[0]["channels_sent"], rows[0]
        assert "sms" in rows[0]["channels_sent"], rows[0]
    finally:
        _cleanup(cid, jid)


def test_patch_latency_without_reschedule(admin):
    """Baseline: a non-scheduled_date PATCH must not pay the provider
    round-trip cost."""
    headers, _ = admin
    cid, jid = _mk_fixture()
    try:
        t0 = datetime.now()
        r = _patch(headers, jid, {"notes": "TEST_NOTIF baseline"})
        elapsed = (datetime.now() - t0).total_seconds()
        assert r.status_code == 200
        print(f"[latency] no-reschedule PATCH = {elapsed:.2f}s")
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 2 · Idempotency — no-change short-circuit + transition key
# ═════════════════════════════════════════════════════════════════
def test_reschedule_idempotency(admin):
    headers, _ = admin
    cid, jid = _mk_fixture()
    try:
        assert _patch(headers, jid, {"scheduled_date": DATE_B}).status_code == 200
        assert len(_audit_rows(jid)) == 1

        # (a) same value again → no-change short-circuit
        assert _patch(headers, jid, {"scheduled_date": DATE_B}).status_code == 200
        assert len(_audit_rows(jid)) == 1, "no-change PATCH inserted a row"

        # (b) move away then back → A→B transition key already logged
        assert _patch(headers, jid, {"scheduled_date": DATE_A}).status_code == 200
        rows = _audit_rows(jid)
        assert len(rows) == 2, f"B→A should log a row, got {len(rows)}"
        assert rows[1]["transition_key"] == f"{DATE_B}→{DATE_A}"

        assert _patch(headers, jid, {"scheduled_date": DATE_B}).status_code == 200
        rows = _audit_rows(jid)
        assert len(rows) == 2, (
            "repeat A→B transition must be deduplicated, "
            f"got {len(rows)} rows")
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 3 · sms_opt_in = False
# ═════════════════════════════════════════════════════════════════
def test_reschedule_hard_sms_opt_out(admin):
    headers, _ = admin
    cid, jid = _mk_fixture(sms_opt_in=False)
    try:
        assert _patch(headers, jid, {"scheduled_date": DATE_B}).status_code == 200
        rows = _audit_rows(jid)
        assert len(rows) == 1
        row = rows[0]
        assert "sms" not in row["channels_sent"]
        assert "sms:hard_opt_out" in row["channels_skipped"], row
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 4 · no phone on the customer
# ═════════════════════════════════════════════════════════════════
def test_reschedule_no_phone(admin):
    headers, _ = admin
    cid, jid = _mk_fixture(phone="")
    try:
        assert _patch(headers, jid, {"scheduled_date": DATE_B}).status_code == 200
        rows = _audit_rows(jid)
        assert len(rows) == 1
        assert "sms" not in rows[0]["channels_sent"]
        assert "sms:no_address" in rows[0]["channels_skipped"], rows[0]
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 5 · unrelated field PATCH → no notification
# ═════════════════════════════════════════════════════════════════
def test_patch_other_fields_does_not_notify(admin):
    headers, _ = admin
    cid, jid = _mk_fixture()
    try:
        before = len(_audit_rows(jid))
        r = _patch(headers, jid, {"title": "TEST_NOTIF_Job renamed",
                                  "notes": "TEST_NOTIF note"})
        assert r.status_code == 200, r.text[:300]
        assert len(_audit_rows(jid)) == before == 0
        job = _sync.jobs.find_one({"id": jid}, {"_id": 0})
        assert job["title"] == "TEST_NOTIF_Job renamed"
        assert job["scheduled_date"] == DATE_A
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 6 · cron registration path
# ═════════════════════════════════════════════════════════════════
def test_register_service_reminder_cron_mock_scheduler():
    from services.notifications_pipeline.service_notifications import (
        register_service_reminder_cron, service_reminder_cron_tick,
    )

    calls = []

    class _MockScheduler:
        def add_job(self, func, trigger=None, **kwargs):
            calls.append({"func": func, "trigger": trigger, **kwargs})

    register_service_reminder_cron(_MockScheduler())
    assert len(calls) == 1, calls
    c = calls[0]
    assert c["id"] == "service_reminder_cron"
    assert c["minute"] == 0
    assert c["trigger"] == "cron"
    assert c["func"] is service_reminder_cron_tick
    assert c.get("replace_existing") is True
    assert c.get("max_instances") == 1


@pytest.mark.xfail(
    reason="boot_flags.should_enable_scheduler() ANDs `not is_production()`, "
           "so scripts/run_scheduler.py forcing ENABLE_SCHEDULER=true still "
           "registers ZERO cron jobs when APP_ENV=production — the 24-hr "
           "service_reminder_cron never fires in this pod / production.",
    strict=False,
)
def test_prod_scheduler_worker_can_enable_cron():
    """The documented production scheduler worker
    (``ENABLE_SCHEDULER=true python -m scripts.run_scheduler``) must be
    able to turn the scheduler on so ``service_reminder_cron`` gets
    registered. Currently it cannot when APP_ENV=production."""
    import importlib

    import boot_flags
    old_app_env = os.environ.get("APP_ENV")
    old_flag = os.environ.get("ENABLE_SCHEDULER")
    try:
        os.environ["APP_ENV"] = "production"
        os.environ["ENABLE_SCHEDULER"] = "true"   # run_scheduler.py forces this
        importlib.reload(boot_flags)
        assert boot_flags.should_enable_scheduler() is True, (
            "prod scheduler worker cannot enable the scheduler: "
            f"snapshot={boot_flags.snapshot()}")
    finally:
        if old_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = old_app_env
        if old_flag is None:
            os.environ.pop("ENABLE_SCHEDULER", None)
        else:
            os.environ["ENABLE_SCHEDULER"] = old_flag
        importlib.reload(boot_flags)


# ═════════════════════════════════════════════════════════════════
# 7 · reminder pickup window + idempotency stamp
# ═════════════════════════════════════════════════════════════════
def test_reminder_pickup_and_idempotency():
    from services.notifications_pipeline import service_notifications as sn

    target = (datetime.now(ZoneInfo(TENANT_TZ)) + timedelta(hours=25))
    sd = target.strftime("%Y-%m-%dT%H:%M:%S")
    cid, jid = _mk_fixture(scheduled_date=sd)
    try:
        due = _run(sn._due_reminder_jobs_for_tenant(_TENANT))
        assert jid in [j["id"] for j in due], (
            f"25h-out job not picked up. window jobs={len(due)}")

        job = _sync.jobs.find_one({"id": jid}, {"_id": 0})
        res = _run(sn.fire_reminder_for_job(job))
        assert res["ok"] is True, res
        rows = _audit_rows(jid)
        assert len(rows) == 1, rows
        assert rows[0]["template_key"] == "service_reminder"
        assert rows[0]["actor"] == "system_cron"
        assert "sms" in rows[0]["channels_sent"], rows[0]

        stamped = _sync.jobs.find_one({"id": jid}, {"_id": 0})
        assert stamped.get("service_reminder_sent_at"), "job not stamped"

        # Idempotency — the stamped job must fall out of the window scan.
        due2 = _run(sn._due_reminder_jobs_for_tenant(_TENANT))
        assert jid not in [j["id"] for j in due2], (
            "stamped job re-picked by the window scan")
        assert len(_audit_rows(jid)) == 1
    finally:
        _cleanup(cid, jid)


def test_reminder_window_excludes_out_of_range_job():
    from services.notifications_pipeline import service_notifications as sn

    far = (datetime.now(ZoneInfo(TENANT_TZ)) + timedelta(hours=60))
    cid, jid = _mk_fixture(scheduled_date=far.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        due = _run(sn._due_reminder_jobs_for_tenant(_TENANT))
        assert jid not in [j["id"] for j in due]
    finally:
        _cleanup(cid, jid)


# ═════════════════════════════════════════════════════════════════
# 8 · identity guard — unresolvable customer must not 500
# ═════════════════════════════════════════════════════════════════
def test_reschedule_unresolved_identity_does_not_break_patch(admin):
    headers, _ = admin
    m = uuid.uuid4().hex[:8]
    jid = f"TEST_NOTIF_job_{m}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": TENANT_ID,
        "customer_id": f"TEST_NOTIF_ghost_{m}",
        "title": f"TEST_NOTIF_Job {m}",
        "scheduled_date": DATE_A,
        "service_type": "Weekly pool cleaning",
        "status": "scheduled",
    })
    try:
        r = _patch(headers, jid, {"scheduled_date": DATE_C})
        assert r.status_code == 200, r.text[:300]
        assert _audit_rows(jid) == [], "audit row written for unresolved identity"
        job = _sync.jobs.find_one({"id": jid}, {"_id": 0})
        assert job["scheduled_date"] == DATE_C, "PATCH did not persist"
    finally:
        _sync.jobs.delete_many({"id": jid})
        _sync.notifications_sent_log.delete_many({"job_id": jid})
