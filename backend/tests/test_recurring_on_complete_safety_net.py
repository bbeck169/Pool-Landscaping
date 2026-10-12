"""Feb-2026 · pytest · on-complete safety-net helper.

Pins the contract of
``services.recurring_jobs_backfill.materialize_next_from_completed_job``
so future refactors don't silently regress the self-healing
behavior added in Commit 5 (``5ef59cce4``).

4 cases, direct helper call (no HTTP), live preview Mongo via
test-isolated template + job docs that we create and clean up
inside each test. Pattern mirrors the live-Mongo style used in
``test_admin_recurring_jobs_backfill_endpoint.py``.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values

from services.recurring_jobs_backfill import (
    materialize_next_from_completed_job,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

# Prefix for every row this file creates so cleanup is targeted.
_PREFIX = "pytest-on-complete-safety-net"


# ─── Mongo fixture (sync pymongo for seeding, matches other tests) ─
@pytest.fixture
def mongo():
    from pymongo import MongoClient
    c = MongoClient(_MONGO_URL)
    db = c[_DB_NAME]
    yield db
    # Hard cleanup — only rows this file inserted.
    db.recurring_job_templates.delete_many({"notes": _PREFIX})
    db.jobs.delete_many({"notes": _PREFIX})
    db.customers.delete_many({"name": _PREFIX})
    c.close()


# ─── Seed helpers ───────────────────────────────────────────────────
def _seed_customer(db, tenant_id: str) -> str:
    cust_id = f"{_PREFIX}-cust-{os.urandom(4).hex()}"
    db.customers.insert_one({
        "id": cust_id,
        "tenant_id": tenant_id,
        "name": _PREFIX,
        "address": "123 Pytest Lane",
    })
    return cust_id


def _seed_template(db, tenant_id: str, customer_id: str,
                     *, is_active: bool = True,
                     end_date: str | None = None) -> str:
    tpl_id = f"{_PREFIX}-tpl-{os.urandom(4).hex()}"
    today = date.today()
    db.recurring_job_templates.insert_one({
        "id": tpl_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": _PREFIX,
        "service_type": "Weekly Pool Clean",
        "frequency": "weekly",
        "day_of_week": today.weekday(),
        "allow_sunday": True,
        "interval_days": 7,
        "start_date": (today - timedelta(days=90)).isoformat(),
        "end_date": end_date,
        "is_active": is_active,
        "active": is_active,
        "price_cents": 7500,
        "notes": _PREFIX,
    })
    return tpl_id


def _seed_completed_parent_job(
        db, tenant_id: str, template_id: str, customer_id: str,
        *, parent_date: date) -> dict:
    jid = f"{_PREFIX}-job-{os.urandom(4).hex()}"
    doc = {
        "id": jid,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": _PREFIX,
        "title": "Weekly Pool Clean",
        "service_type": "Weekly Pool Clean",
        "scheduled_date": parent_date.isoformat(),
        "status": "completed",
        "recurring_template_id": template_id,
        "price": 75.0,
        "notes": _PREFIX,
    }
    db.jobs.insert_one({**doc})
    return doc


_TENANT_ID = "pytest-safety-net-tenant"


# ─── 1 · fires when cron missed the next occurrence ─────────────────
def test_safety_net_fires_when_cron_missed_next_occurrence(mongo):
    """Parent job completed on anchor date; walker expects the next
    occurrence 7 days later; db.jobs has nothing for that date →
    helper must insert exactly one scheduled job with
    backfilled_by='on_complete_safety_net'.
    """
    parent_date = date.today()
    cust_id = _seed_customer(mongo, _TENANT_ID)
    tpl_id = _seed_template(mongo, _TENANT_ID, cust_id)
    parent = _seed_completed_parent_job(
        mongo, _TENANT_ID, tpl_id, cust_id, parent_date=parent_date)
    expected_next_date = (parent_date + timedelta(days=7)).isoformat()

    inserted = asyncio.get_event_loop().run_until_complete(
        materialize_next_from_completed_job(
            job=parent, tenant_id=_TENANT_ID, actor_user_id="pytest-user"),
    )

    assert inserted is not None, "helper should have inserted a new job"
    assert inserted["scheduled_date"] == expected_next_date
    assert inserted["status"] == "scheduled"
    assert inserted["backfilled_by"] == "on_complete_safety_net"
    assert inserted["recurring_template_id"] == tpl_id

    # DB side-effect check — exactly one new scheduled job for the
    # template at the next_date.
    rows = list(mongo.jobs.find(
        {"tenant_id": _TENANT_ID,
         "recurring_template_id": tpl_id,
         "scheduled_date": expected_next_date,
         "status": "scheduled"},
        {"_id": 0},
    ))
    assert len(rows) == 1, (
        f"expected exactly 1 new scheduled job, got {len(rows)}: {rows}")


# ─── 2 · no-op when cron already materialized the next occurrence ──
def test_safety_net_noop_when_cron_already_materialized(mongo):
    """A pre-existing (non-soft-deleted) scheduled job at the next
    date → helper short-circuits to None, no second row inserted.
    """
    parent_date = date.today()
    cust_id = _seed_customer(mongo, _TENANT_ID)
    tpl_id = _seed_template(mongo, _TENANT_ID, cust_id)
    parent = _seed_completed_parent_job(
        mongo, _TENANT_ID, tpl_id, cust_id, parent_date=parent_date)
    expected_next_date = (parent_date + timedelta(days=7)).isoformat()
    # Pre-seed what the cron would have inserted.
    mongo.jobs.insert_one({
        "id": f"{_PREFIX}-preexisting-{os.urandom(4).hex()}",
        "tenant_id": _TENANT_ID,
        "recurring_template_id": tpl_id,
        "scheduled_date": expected_next_date,
        "status": "scheduled",
        "notes": _PREFIX,
    })

    inserted = asyncio.get_event_loop().run_until_complete(
        materialize_next_from_completed_job(
            job=parent, tenant_id=_TENANT_ID, actor_user_id="pytest-user"),
    )

    assert inserted is None, "helper must no-op when job already exists"

    rows = list(mongo.jobs.find(
        {"tenant_id": _TENANT_ID,
         "recurring_template_id": tpl_id,
         "scheduled_date": expected_next_date},
        {"_id": 0, "id": 1},
    ))
    assert len(rows) == 1, (
        f"idempotency failed — duplicate row inserted: {rows}")


# ─── 3 · no-op when template is paused ──────────────────────────────
def test_safety_net_noop_when_template_paused(mongo):
    """Template with ``is_active=False`` → helper short-circuits
    without consulting the walker. Mirrors the pause-the-template
    operator action.
    """
    parent_date = date.today()
    cust_id = _seed_customer(mongo, _TENANT_ID)
    tpl_id = _seed_template(mongo, _TENANT_ID, cust_id, is_active=False)
    parent = _seed_completed_parent_job(
        mongo, _TENANT_ID, tpl_id, cust_id, parent_date=parent_date)

    inserted = asyncio.get_event_loop().run_until_complete(
        materialize_next_from_completed_job(
            job=parent, tenant_id=_TENANT_ID, actor_user_id="pytest-user"),
    )

    assert inserted is None, "paused template must not re-materialize"

    rows = list(mongo.jobs.find(
        {"tenant_id": _TENANT_ID, "recurring_template_id": tpl_id,
         "status": "scheduled"},
        {"_id": 0, "id": 1},
    ))
    assert rows == [], f"paused template produced jobs: {rows}"


# ─── 4 · no-op on a non-recurring job (template_id=None) ───────────
def test_safety_net_noop_when_job_has_no_recurring_template_id(mongo):
    """One-off job (not recurring) → immediate None return, no DB
    writes. Guards the hot path for every PUT /jobs/{jid} transition
    against needless work.
    """
    parent = {
        "id": f"{_PREFIX}-oneoff-{os.urandom(4).hex()}",
        "tenant_id": _TENANT_ID,
        "scheduled_date": date.today().isoformat(),
        "status": "completed",
        "recurring_template_id": None,
        "notes": _PREFIX,
    }

    inserted = asyncio.get_event_loop().run_until_complete(
        materialize_next_from_completed_job(
            job=parent, tenant_id=_TENANT_ID, actor_user_id="pytest-user"),
    )

    assert inserted is None, "non-recurring job must short-circuit"
