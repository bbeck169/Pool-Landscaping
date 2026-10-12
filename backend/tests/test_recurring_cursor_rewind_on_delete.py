"""Feb-2026 · pytest · delete-cursor-rewind helper (Cause C).

Pins the contract of
``services.recurring_jobs_backfill.rewind_template_cursor_on_job_delete``
so future refactors don't silently regress the self-healing behavior
added in Commit A (``0567a2685``) + Commit B (``dd9541980``).

5 cases, direct helper call (no HTTP), live preview Mongo via
test-isolated template/job docs that we create and clean up inside
each test. Pattern mirrors
``test_recurring_on_complete_safety_net.py``.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.recurring_jobs_backfill import (
    rewind_template_cursor_on_job_delete,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

# Prefix for every row this file creates so cleanup is targeted.
_PREFIX = "pytest-cursor-rewind-on-delete"
_TENANT_ID = "pytest-cursor-rewind-tenant"


@pytest.fixture
def mongo():
    from pymongo import MongoClient
    c = MongoClient(_MONGO_URL)
    db = c[_DB_NAME]
    yield db
    db.recurring_job_templates.delete_many({"notes": _PREFIX})
    db.jobs.delete_many({"notes": _PREFIX})
    c.close()


def _seed_template(
        db, *, cursor_iso: str | None,
        tpl_id: str | None = None) -> str:
    tpl_id = tpl_id or f"{_PREFIX}-tpl-{os.urandom(4).hex()}"
    db.recurring_job_templates.insert_one({
        "id": tpl_id,
        "tenant_id": _TENANT_ID,
        "customer_id": f"{_PREFIX}-cust",
        "service_type": "Weekly Pool Clean",
        "frequency": "weekly",
        "day_of_week": date.today().weekday(),
        "allow_sunday": True,
        "interval_days": 7,
        "start_date": (date.today() - timedelta(days=90)).isoformat(),
        "end_date": None,
        "is_active": True,
        "active": True,
        "last_generated_through": cursor_iso,
        "price_cents": 7500,
        "notes": _PREFIX,
    })
    return tpl_id


def _seed_job(
        db, *, tpl_id: str,
        scheduled_date: date) -> dict:
    jid = f"{_PREFIX}-job-{os.urandom(4).hex()}"
    doc = {
        "id": jid,
        "tenant_id": _TENANT_ID,
        "recurring_template_id": tpl_id,
        "scheduled_date": scheduled_date.isoformat(),
        "status": "scheduled",
        "notes": _PREFIX,
    }
    db.jobs.insert_one({**doc})
    return doc


# ─── 1 · fires on hard delete when date <= cursor ───────────────────
def test_rewind_fires_on_hard_delete_when_date_before_cursor(mongo):
    """Template cursor=today+10, deleted job scheduled for today+3.
    Helper must rewind cursor to today+2 (ISO).
    """
    today = date.today()
    cursor_iso = (today + timedelta(days=10)).isoformat()
    tpl_id = _seed_template(mongo, cursor_iso=cursor_iso)
    sched = today + timedelta(days=3)
    job = _seed_job(mongo, tpl_id=tpl_id, scheduled_date=sched)
    expected_new_cursor = (sched - timedelta(days=1)).isoformat()

    result = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )

    assert result == expected_new_cursor, (
        f"expected cursor rewind to {expected_new_cursor}, got {result!r}")
    tpl_after = mongo.recurring_job_templates.find_one(
        {"id": tpl_id}, {"_id": 0, "last_generated_through": 1,
                         "cursor_rewound_reason": 1,
                         "cursor_rewound_deleted_job_id": 1})
    assert tpl_after["last_generated_through"] == expected_new_cursor
    assert tpl_after["cursor_rewound_reason"] == "job_deleted"
    assert tpl_after["cursor_rewound_deleted_job_id"] == job["id"]


# ─── 2 · no-op when scheduled_date > cursor (future beyond cursor) ─
def test_rewind_noop_when_scheduled_date_after_cursor(mongo):
    """Cursor=today+2, deleted job scheduled for today+10. Cron
    hasn't walked past the deleted date yet; next run will cover
    it naturally. Helper must NOT touch the cursor.
    """
    today = date.today()
    cursor_iso = (today + timedelta(days=2)).isoformat()
    tpl_id = _seed_template(mongo, cursor_iso=cursor_iso)
    job = _seed_job(mongo, tpl_id=tpl_id,
                     scheduled_date=today + timedelta(days=10))

    result = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )

    assert result is None, "helper should no-op when date > cursor"
    tpl_after = mongo.recurring_job_templates.find_one(
        {"id": tpl_id}, {"_id": 0, "last_generated_through": 1})
    assert tpl_after["last_generated_through"] == cursor_iso, (
        f"cursor must be unchanged, got {tpl_after['last_generated_through']}")


# ─── 3 · no-op on non-recurring job (template_id=None) ─────────────
def test_rewind_noop_on_non_recurring_job(mongo):
    """One-off job with recurring_template_id=None → helper returns
    None immediately, no DB writes.
    """
    job = {
        "id": f"{_PREFIX}-oneoff-{os.urandom(4).hex()}",
        "tenant_id": _TENANT_ID,
        "scheduled_date": date.today().isoformat(),
        "recurring_template_id": None,
        "notes": _PREFIX,
    }

    result = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )
    assert result is None


# ─── 4 · no-op when template already deleted ───────────────────────
def test_rewind_noop_when_template_missing(mongo):
    """Deleted job references a template that no longer exists →
    helper returns None (nothing to rewind on; next cron skips it
    anyway).
    """
    sched = date.today() + timedelta(days=3)
    job = {
        "id": f"{_PREFIX}-orphan-{os.urandom(4).hex()}",
        "tenant_id": _TENANT_ID,
        "recurring_template_id": f"{_PREFIX}-missing-template",
        "scheduled_date": sched.isoformat(),
        "notes": _PREFIX,
    }

    result = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )
    assert result is None


# ─── 5 · idempotent / race-guarded under repeated calls ─────────────
def test_rewind_idempotent_under_race(mongo):
    """Call helper TWICE with the same target. Second call should
    be a no-op because the Mongo filter guard
    ``last_generated_through: {$gt: new_cursor_iso}`` fails the
    second time (cursor is already at target, not > target).
    """
    today = date.today()
    cursor_iso = (today + timedelta(days=10)).isoformat()
    tpl_id = _seed_template(mongo, cursor_iso=cursor_iso)
    sched = today + timedelta(days=3)
    job = _seed_job(mongo, tpl_id=tpl_id, scheduled_date=sched)
    expected_new_cursor = (sched - timedelta(days=1)).isoformat()

    r1 = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )
    r2 = asyncio.get_event_loop().run_until_complete(
        rewind_template_cursor_on_job_delete(
            job=job, tenant_id=_TENANT_ID, actor_user_id="pytest"),
    )

    assert r1 == expected_new_cursor, (
        f"first call must rewind, got {r1!r}")
    assert r2 is None, (
        f"second call must no-op via $gt guard, got {r2!r}")
    tpl_after = mongo.recurring_job_templates.find_one(
        {"id": tpl_id}, {"_id": 0, "last_generated_through": 1})
    assert tpl_after["last_generated_through"] == expected_new_cursor
