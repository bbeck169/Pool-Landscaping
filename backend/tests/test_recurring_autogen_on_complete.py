"""Feb-2026 · Auto-extend recurring series on last-job completion.

Direct-service tests — invoke ``maybe_extend_recurring_series`` on a
seeded template + jobs, then verify the resulting store shape. Uses a
fresh Motor client per test so the running app's loop-bound ``config.db``
never enters the picture (matches the ``test_pricebook_backfill`` style
that shipped last session).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


def _env(k: str) -> str:
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{k}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


@pytest.fixture(scope="module")
def sync_db():
    cli = MongoClient(_env("MONGO_URL"), serverSelectionTimeoutMS=5000)
    try:
        yield cli[_env("DB_NAME") or "aquaterra"]
    finally:
        cli.close()


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@pytest.fixture()
def tenant_with_template(sync_db):
    tid = f"test-autogen-{uuid.uuid4().hex[:10]}"
    tpl_id = f"tpl-{uuid.uuid4().hex[:10]}"
    sync_db.tenants.insert_one({"id": tid, "name": "test-autogen"})
    start = (date.today() - timedelta(days=30)).isoformat()
    sync_db.recurring_job_templates.insert_one({
        "id": tpl_id, "tenant_id": tid,
        "customer_id": "cust-autogen",
        "customer_name": "AutoGen Test Customer",
        "service_type": "Weekly Pool",
        "frequency": "weekly", "day_of_week": date.today().weekday(),
        "start_date": start,
        "end_date": None,
        "recurrence_never_ends": True,
        "price_cents": 12000, "active": True,
        "last_generated_through": None,
    })
    yield tid, tpl_id
    for c in ("tenants", "recurring_job_templates", "jobs"):
        sync_db[c].delete_many({"tenant_id": tid})


def _seed_job(sync_db, *, tenant_id, template_id, scheduled_date, status="scheduled"):
    jid = f"job-{uuid.uuid4().hex[:10]}"
    sync_db.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "recurring_template_id": template_id,
        "scheduled_date": scheduled_date, "status": status,
        "service_type": "Weekly Pool",
    })
    return jid


def _make_motor_db():
    cli=AsyncIOMotorClient(_env("MONGO_URL"))
    return cli[_env("DB_NAME") or "aquaterra"]


def _extend(job_id, tenant_id, **kw):
    from services import recurring_autogen as ra
    # Reset the per-template lock so tests don't share state.
    ra._TEMPLATE_LOCKS.clear()
    return _run(lambda: ra.maybe_extend_recurring_series(job_id, tenant_id, db_handle=_make_motor_db(), **kw))


def test_completing_last_open_job_generates_four_more(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    # One scheduled job on today's date, marked completed manually.
    jid = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                     scheduled_date=date.today().isoformat(), status="completed")
    report = _extend(jid, tenant_id)
    assert report is not None
    assert report["inserted"] == 4, report
    future = list(sync_db.jobs.find({
        "tenant_id": tenant_id, "recurring_template_id": tpl_id,
        "status": "scheduled",
    }).sort("scheduled_date", 1))
    assert len(future) == 4
    for f in future:
        assert f.get("auto_generated_by") == "recurring_autogen_on_complete"


def test_not_last_open_job_is_a_noop(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    # Two future scheduled jobs; complete one, the OTHER is still open.
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    jid_completed = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                                scheduled_date=date.today().isoformat(),
                                status="completed")
    _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                scheduled_date=tomorrow, status="scheduled")
    report = _extend(jid_completed, tenant_id)
    assert report is None
    # Only the original 2 remain, no new ones inserted.
    assert sync_db.jobs.count_documents({
        "tenant_id": tenant_id, "recurring_template_id": tpl_id,
    }) == 2


def test_stopped_series_does_not_extend(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    sync_db.recurring_job_templates.update_one(
        {"id": tpl_id}, {"$set": {"active": False, "stopped_at": "2026-01-01"}},
    )
    jid = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                     scheduled_date=date.today().isoformat(), status="completed")
    report = _extend(jid, tenant_id)
    assert report is None
    assert sync_db.jobs.count_documents({
        "tenant_id": tenant_id, "recurring_template_id": tpl_id,
        "status": "scheduled",
    }) == 0


def test_end_date_caps_generation(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    # Set end_date 2 weeks out with never_ends=False → generator should
    # emit exactly 2 weekly occurrences instead of 4.
    end_iso = (date.today() + timedelta(days=15)).isoformat()
    sync_db.recurring_job_templates.update_one(
        {"id": tpl_id},
        {"$set": {"recurrence_never_ends": False, "end_date": end_iso}},
    )
    jid = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                     scheduled_date=date.today().isoformat(), status="completed")
    report = _extend(jid, tenant_id)
    assert report is not None
    assert report["inserted"] == 2, report


def test_concurrent_completes_do_not_double_generate(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    # Two "last complete" fires racing — the in-process lock plus the
    # partial-unique index must combine to yield exactly 4 total.
    jid_a = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                        scheduled_date=date.today().isoformat(), status="completed")
    jid_b = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                        scheduled_date=(date.today() - timedelta(days=1)).isoformat(),
                        status="completed")
    from services import recurring_autogen as ra
    ra._TEMPLATE_LOCKS.clear()
    async def _race():
        return await asyncio.gather(
            ra.maybe_extend_recurring_series(jid_a, tenant_id, db_handle=_make_motor_db()),
            ra.maybe_extend_recurring_series(jid_b, tenant_id, db_handle=_make_motor_db()),
        )
    results = _run(_race)
    total_inserted = sum((r or {}).get("inserted", 0) for r in results)
    total_skipped = sum((r or {}).get("skipped", 0) for r in results)
    # First fire hydrates 4; second walks the same 4 dates and is
    # deduped by the partial-unique index → skipped=4, inserted=0.
    assert total_inserted == 4
    assert total_skipped in (0, 4)
    # Store must show exactly 4 auto-generated scheduled rows.
    assert sync_db.jobs.count_documents({
        "tenant_id": tenant_id, "recurring_template_id": tpl_id,
        "status": "scheduled",
    }) == 4


def test_non_recurring_job_is_a_noop(sync_db, tenant_with_template):
    tenant_id, _tpl = tenant_with_template
    jid = f"job-{uuid.uuid4().hex[:10]}"
    sync_db.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "scheduled_date": date.today().isoformat(), "status": "completed",
        # explicitly no recurring_template_id
    })
    report = _extend(jid, tenant_id)
    assert report is None


def test_monthly_nth_weekday_template_uses_own_cadence(sync_db, tenant_with_template):
    tenant_id, tpl_id = tenant_with_template
    # Flip the fixture template to monthly · 2nd Tuesday of the month.
    sync_db.recurring_job_templates.update_one(
        {"id": tpl_id},
        {"$set": {
            "frequency": "monthly",
            "monthly_pattern": "nth_weekday",
            "monthly_nth_week": "second",
            "monthly_weekday": 1,  # Tue
            "day_of_week": None,
        }},
    )
    jid = _seed_job(sync_db, tenant_id=tenant_id, template_id=tpl_id,
                     scheduled_date=date.today().isoformat(), status="completed")
    report = _extend(jid, tenant_id)
    assert report is not None
    assert report["inserted"] == 4
    # Every generated date must be a Tuesday in the 8-14 window (2nd Tue).
    for iso in report["dates"]:
        d = date.fromisoformat(iso)
        assert d.weekday() == 1, f"{iso} not a Tuesday"
        assert 8 <= d.day <= 14, f"{iso} outside 2nd-Tuesday window"
