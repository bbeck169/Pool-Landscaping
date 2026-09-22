"""Phase P15 · Feb-2026 — Dashboard "today" tenant-tz lock.

Locks in the ``dashboard_action_cards`` endpoint's tenant-timezone
anchoring:

  1. At 01:30 UTC (== 18:30 Phoenix the previous UTC day) a job
     scheduled for ``20:00 Phoenix current-Phoenix-day`` is counted
     under ``today_routes``.
  2. Same freeze, a job scheduled for ``23:00 Phoenix
     previous-Phoenix-day`` is NOT counted.
  3. A tenant with no ``timezone`` field defaults to Phoenix (matches
     the P13 default) and produces the same count as an
     explicit-Phoenix tenant.

Written as an in-process call to the endpoint's inner async function
so we can freeze ``datetime.now()`` reliably.  ``freezegun`` is
listed in ``backend/requirements.txt``.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from dotenv import dotenv_values
from freezegun import freeze_time
from pymongo import MongoClient

from routers.dashboard_action_cards import get_action_cards

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

PHOENIX = ZoneInfo("America/Phoenix")


@pytest.fixture(scope="module")
def sync_db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def _tenant(sync_db):
    """Provision an isolated tenant with ``timezone = America/Phoenix``
    for the duration of this test.  Teardown deletes every seeded row
    so the test is idempotent across runs."""
    tid = f"TEST-p15-tenant-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid,
        "name": "P15 · Phoenix Test Tenant",
        "slug": f"p15-{tid}",
        "timezone": "America/Phoenix",
        "active": True,
    }
    sync_db.tenants.insert_one(doc)
    yield doc
    sync_db.tenants.delete_one({"id": tid})
    sync_db.jobs.delete_many({"tenant_id": tid})
    sync_db.leads.delete_many({"tenant_id": tid})
    sync_db.intelligence_alerts.delete_many({"tenant_id": tid})


@pytest.fixture
def _tenant_no_tz(sync_db):
    """Same as above but WITHOUT a ``timezone`` field — exercises the
    Phoenix fallback contract."""
    tid = f"TEST-p15-tenant-notz-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": tid,
        "name": "P15 · No-TZ Test Tenant",
        "slug": f"p15-notz-{tid}",
        "active": True,
    }
    sync_db.tenants.insert_one(doc)
    yield doc
    sync_db.tenants.delete_one({"id": tid})
    sync_db.jobs.delete_many({"tenant_id": tid})
    sync_db.leads.delete_many({"tenant_id": tid})
    sync_db.intelligence_alerts.delete_many({"tenant_id": tid})


def _seed_job(sync_db, tenant_id: str, scheduled_date_iso: str,
              scheduled_start_utc: datetime) -> str:
    jid = f"TEST-p15-job-{uuid.uuid4().hex[:8]}"
    sync_db.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant_id,
        "technician_id": "TEST-p15-tech",
        "scheduled_date": scheduled_date_iso,
        "scheduled_start": scheduled_start_utc.isoformat(),
        "status": "scheduled",
        "created_at": scheduled_start_utc.isoformat(),
    })
    return jid


def _call_action_cards(tenant: dict) -> dict:
    """Invoke the endpoint's async function directly with a mock
    admin user and the fixture tenant.  Bypasses HTTP so ``freezegun``
    can pin ``datetime.now()`` for the duration of the call."""
    admin_user = {
        "id": f"TEST-p15-user-{uuid.uuid4().hex[:8]}",
        "role": "admin",
        "tenant_id": tenant["id"],
    }
    coro = get_action_cards(user=admin_user, tenant=tenant)
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════
# Item A · 20:00 Phoenix on current Phoenix day IS counted at 01:30 UTC.
# ═════════════════════════════════════════════════════════════════════
def test_today_routes_includes_20h_phoenix_job_at_0130_utc(
    sync_db, _tenant,
):
    # Freeze to 2026-02-16 01:30 UTC.  Phoenix (UTC-7, no DST) reads
    # this as 2026-02-15 18:30 Phoenix — so the "current Phoenix
    # day" is 2026-02-15.  A job at 20:00 Phoenix 2026-02-15 IS
    # today's job.
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    phoenix_today = "2026-02-15"
    job_start_local = datetime(2026, 2, 15, 20, 0, tzinfo=PHOENIX)
    job_start_utc = job_start_local.astimezone(timezone.utc)

    _seed_job(sync_db, _tenant["id"], phoenix_today, job_start_utc)

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["today_routes"] == 1, result


# ═════════════════════════════════════════════════════════════════════
# Item B · 23:00 Phoenix on PREVIOUS Phoenix day is NOT counted.
# ═════════════════════════════════════════════════════════════════════
def test_today_routes_excludes_23h_previous_phoenix_day_at_0130_utc(
    sync_db, _tenant,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    phoenix_yesterday = "2026-02-14"
    job_start_local = datetime(2026, 2, 14, 23, 0, tzinfo=PHOENIX)
    job_start_utc = job_start_local.astimezone(timezone.utc)

    _seed_job(sync_db, _tenant["id"], phoenix_yesterday, job_start_utc)

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["today_routes"] == 0, result


# ═════════════════════════════════════════════════════════════════════
# Item C · leads/created_at anchored to tenant-tz day start (UTC).
# ═════════════════════════════════════════════════════════════════════
def test_new_leads_today_counts_lead_created_after_tenant_day_start(
    sync_db, _tenant,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    # Tenant-local Phoenix day start for 2026-02-15 == 2026-02-15
    # 07:00 UTC.  A lead created at 2026-02-15 08:00 UTC (== 01:00
    # Phoenix on 2026-02-15) IS after the tenant-day start and
    # should count as today's lead.
    lead_created = datetime(2026, 2, 15, 8, 0, tzinfo=timezone.utc)
    sync_db.leads.insert_one({
        "id":         f"TEST-p15-lead-{uuid.uuid4().hex[:8]}",
        "tenant_id":  _tenant["id"],
        "created_at": lead_created.isoformat(),
        "status":     "new",
    })

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["new_leads_today"] == 1, result


def test_new_leads_today_excludes_lead_before_tenant_day_start(
    sync_db, _tenant,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    # Lead created at 2026-02-15 06:00 UTC == 2026-02-14 23:00
    # Phoenix — yesterday's Phoenix day. Should NOT count.
    lead_created = datetime(2026, 2, 15, 6, 0, tzinfo=timezone.utc)
    sync_db.leads.insert_one({
        "id":         f"TEST-p15-lead-{uuid.uuid4().hex[:8]}",
        "tenant_id":  _tenant["id"],
        "created_at": lead_created.isoformat(),
        "status":     "new",
    })

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["new_leads_today"] == 0, result


# ═════════════════════════════════════════════════════════════════════
# Item D · missing timezone → defaults to Phoenix.
# ═════════════════════════════════════════════════════════════════════
def test_no_tenant_timezone_defaults_to_phoenix(
    sync_db, _tenant_no_tz,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    phoenix_today = "2026-02-15"
    job_start_local = datetime(2026, 2, 15, 20, 0, tzinfo=PHOENIX)
    job_start_utc = job_start_local.astimezone(timezone.utc)
    _seed_job(sync_db, _tenant_no_tz["id"], phoenix_today, job_start_utc)

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant_no_tz)

    assert result["today_routes"] == 1, result


# ═════════════════════════════════════════════════════════════════════
# Item E · missed_services_today anchored to tenant-tz day start.
# ═════════════════════════════════════════════════════════════════════
def test_missed_services_today_counts_alert_after_tenant_day_start(
    sync_db, _tenant,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    # 2026-02-15 12:00 UTC == 2026-02-15 05:00 Phoenix (after
    # Phoenix midnight).
    alert_created = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    sync_db.intelligence_alerts.insert_one({
        "id":           f"TEST-p15-alert-{uuid.uuid4().hex[:8]}",
        "tenant_id":    _tenant["id"],
        "category":     "missed_service",
        "dismissed_at": None,
        "created_at":   alert_created,
    })

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["missed_services_today"] == 1, result


def test_missed_services_today_excludes_alert_before_tenant_day_start(
    sync_db, _tenant,
):
    freeze_at = datetime(2026, 2, 16, 1, 30, tzinfo=timezone.utc)
    # 2026-02-15 06:00 UTC == 2026-02-14 23:00 Phoenix — yesterday.
    alert_created = datetime(2026, 2, 15, 6, 0, tzinfo=timezone.utc)
    sync_db.intelligence_alerts.insert_one({
        "id":           f"TEST-p15-alert-{uuid.uuid4().hex[:8]}",
        "tenant_id":    _tenant["id"],
        "category":     "missed_service",
        "dismissed_at": None,
        "created_at":   alert_created,
    })

    with freeze_time(freeze_at):
        result = _call_action_cards(_tenant)

    assert result["missed_services_today"] == 0, result
