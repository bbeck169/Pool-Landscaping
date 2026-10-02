"""Jobs Overhaul Phase 3b · PUT /jobs/{jid} ``scheduled_start``.

Pins the backend side of the inline Start Time editor on the
JobDetail Scheduled row. ``scheduled_start`` is a plain ISO
datetime string (same shape as ``scheduled_date`` — no datetime
parsing at the model layer; downstream read paths handle the
format).

Harness mirrors ``test_job_costing_overrides.py``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ENV_BASE = os.environ.get("JOB_SCHEDULED_START_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def super_session() -> dict:
    s = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {s['access_token']}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {s['access_token']}"},
        "tenant_id": me.get("tenant_id"),
    }


@pytest.fixture()
def seeded_job(super_session):
    tenant_id = super_session["tenant_id"]
    cid = f"cust-sstart-{uuid.uuid4()}"
    jid = f"job-sstart-{uuid.uuid4()}"
    docs = {
        "customer": {
            "id": cid, "tenant_id": tenant_id,
            "name": "Scheduled Start Co.", "is_active": True,
            "address": "11 Clock Ln",
        },
        "job": {
            "id": jid, "tenant_id": tenant_id,
            "customer_id": cid, "customer_name": "Scheduled Start Co.",
            "address": "11 Clock Ln",
            "title": "ph3b-scheduled_start seeded",
            "service_type": "Pool Cleaning",
            "status": "scheduled",
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
            "notes": "pre-existing note stays",
            "work_class": "service",
        },
    }

    async def _seed():
        await db.customers.insert_one(dict(docs["customer"]))
        await db.jobs.insert_one(dict(docs["job"]))
    _run(_seed())

    yield {"cid": cid, "jid": jid}

    async def _teardown():
        await db.customers.delete_many({"id": cid})
        await db.jobs.delete_many({"id": jid})
    _run(_teardown())


def test_put_scheduled_start_persists_iso_string_verbatim(
    super_session, seeded_job,
):
    iso = "2026-11-01T15:30:00.000Z"
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"scheduled_start": iso},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    stored = _run(db.jobs.find_one(
        {"id": seeded_job["jid"]}, {"_id": 0, "scheduled_start": 1},
    ))
    assert stored["scheduled_start"] == iso


def test_partial_put_with_only_scheduled_start_leaves_other_fields_intact(
    super_session, seeded_job,
):
    iso = "2026-12-15T09:00:00.000Z"
    pre = _run(db.jobs.find_one({"id": seeded_job["jid"]}, {"_id": 0}))
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"scheduled_start": iso},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    post = _run(db.jobs.find_one({"id": seeded_job["jid"]}, {"_id": 0}))
    # Confirm the new field landed.
    assert post["scheduled_start"] == iso
    # Confirm the untouched fields are byte-identical.
    for k in (
        "customer_id", "customer_name", "address", "title",
        "service_type", "status", "scheduled_date", "notes", "work_class",
    ):
        assert post.get(k) == pre.get(k), (
            f"field {k!r} drifted on scheduled_start-only PUT: "
            f"pre={pre.get(k)!r} post={post.get(k)!r}"
        )
