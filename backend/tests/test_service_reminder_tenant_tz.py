"""Feb-2026 · Service reminder cron · tenant-TZ dispatch semantics.

The cron ticks hourly (UTC). Each tick, per-tenant, we check the
tenant's CURRENT LOCAL HOUR — only tenants whose local hour equals
the trigger hour (default 08 or per env override) get scanned.

Two tenants in different TZs on the same UTC tick can therefore
have DIFFERENT dispatch behaviour — that's the entire point.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.notifications_pipeline import service_notifications as sn
from tests._notif_pipeline_fakes import _DB, _EmailCapture, _SMSCapture


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_only_tenants_at_local_trigger_hour_dispatch(monkeypatch):
    """Set the trigger hour to `H`. Only tenants whose LOCAL hour
    is `H` at UTC-now get scanned; the other tenant is skipped."""
    utc_now = datetime.utcnow()

    # Pick two IANA zones that reliably differ by several hours
    # from each other AND from UTC on the current wall clock.
    tz_a_name = "America/Phoenix"      # UTC-7 year-round (no DST)
    tz_b_name = "Asia/Tokyo"            # UTC+9

    now_a = datetime.now(ZoneInfo(tz_a_name))
    now_b = datetime.now(ZoneInfo(tz_b_name))
    # Trigger hour = the LOCAL hour in tenant A. Tenant B will
    # not match unless the two zones happen to share an hour,
    # which never happens for PHX vs TOK (16-hour gap).
    trigger = now_a.hour
    assert now_b.hour != trigger, (
        "test fixture assumption failed — PHX and TOK share hour"
    )
    monkeypatch.setenv("SERVICE_REMINDER_LOCAL_HOUR", str(trigger))

    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    async def _lease(**_k):
        return {"acquired": True, "lease_id": "test"}
    monkeypatch.setattr(
        "services.comms_hardening.scheduler_lease.try_acquire_lease",
        _lease,
    )

    fake_db = _DB(
        tenants=[
            {"id": "tA", "name": "TenantA", "timezone": tz_a_name},
            {"id": "tB", "name": "TenantB", "timezone": tz_b_name},
        ],
        # Both tenants have a job 25 hours out.
        jobs=[
            {"id": "jA", "tenant_id": "tA", "status": "scheduled",
             "customer_id": "cA",
             "scheduled_date": (now_a + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S")},
            {"id": "jB", "tenant_id": "tB", "status": "scheduled",
             "customer_id": "cB",
             "scheduled_date": (now_b + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S")},
        ],
        customers=[
            {"id": "cA", "tenant_id": "tA", "email": "a@a",
             "phone": "+1"},
            {"id": "cB", "tenant_id": "tB", "email": "b@b",
             "phone": "+2"},
        ],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.service_reminder_cron_tick())

    # Exactly ONE tenant scanned (the one whose local hour is
    # ``trigger``) → tenant A. Tenant B was skipped entirely.
    assert result["scanned_tenants"] == 1
    scanned_ids = [row["tenant_id"] for row in result["per_tenant"]]
    assert scanned_ids == ["tA"]
    # Tenant B's job MUST NOT have been stamped (untouched).
    tB_job = next(j for j in fake_db.jobs.rows if j["id"] == "jB")
    assert "service_reminder_sent_at" not in tB_job
    # Tenant A's job WAS stamped.
    tA_job = next(j for j in fake_db.jobs.rows if j["id"] == "jA")
    assert tA_job.get("service_reminder_sent_at")


def test_default_tz_fallback_when_tenant_missing_timezone(monkeypatch):
    """Tenant with no ``timezone`` field falls back to
    ``America/Phoenix`` — matches equipment_trackers_cron."""
    default_tz = "America/Phoenix"
    now_local = datetime.now(ZoneInfo(default_tz))
    monkeypatch.setenv("SERVICE_REMINDER_LOCAL_HOUR",
                        str(now_local.hour))

    email = _EmailCapture(); sms = _SMSCapture()
    monkeypatch.setattr("services.comms_email_adapter.send_email", email)
    monkeypatch.setattr("services.comms_sms_adapter.send_sms", sms)

    async def _lease(**_k):
        return {"acquired": True, "lease_id": "test"}
    monkeypatch.setattr(
        "services.comms_hardening.scheduler_lease.try_acquire_lease",
        _lease,
    )

    fake_db = _DB(
        tenants=[{"id": "t1", "name": "NoTZ"}],  # no timezone
        jobs=[{"id": "j1", "tenant_id": "t1", "status": "scheduled",
                "customer_id": "c1",
                "scheduled_date": (now_local + timedelta(hours=25))
                                    .strftime("%Y-%m-%dT%H:%M:%S")}],
        customers=[{"id": "c1", "tenant_id": "t1",
                     "email": "a@x", "phone": "+15551"}],
    )
    monkeypatch.setattr(sn, "db", fake_db)

    result = _run(sn.service_reminder_cron_tick())
    # Fallback TZ still identifies this tenant as being at the
    # trigger hour → 1 scan.
    assert result["scanned_tenants"] == 1
