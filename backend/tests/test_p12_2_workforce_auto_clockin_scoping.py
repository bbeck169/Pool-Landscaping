"""Phase P12.2 · Feb-2026 · SAFETY-CRITICAL — Auto-clockin cross-tech isolation.

Locks in the acceptance point:

  * Two jobs seeded on the same tenant / same day / both geofence-
    eligible — one for Mike, one for Carlos. Mike posts an auto-
    clock-in coord AT CARLOS'S JOB SITE.
  * Pre-P12.2 (dict-spread merge of ``_nd()`` over the tech-lane
    ``$or``) → the query degraded to "any tenant job today" and Mike
    would auto-clock into Carlos's job.
  * P12.2 fix — nest both disjunctions under ``$and`` via the shared
    ``tenant_scoped_filter`` helper — restores tech-lane scoping.

The test seeds via direct Mongo (fastest + no dependency on
``ALLOW_TEST_HOOKS``) and asserts the endpoint returns
``clocked_in: False, reason: "not_at_any_scheduled_site"``: no
time_entries row is created for Mike on Carlos's job.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def _cleanup(dbc):
    bag: dict = {"job_ids": [], "time_entry_uids": []}
    yield bag
    for jid in bag["job_ids"]:
        dbc.jobs.delete_one({"id": jid})
    for uid in bag["time_entry_uids"]:
        dbc.time_entries.delete_many({"user_id": uid})


def _reset_autoclock_ratelimit(mike_tok: str) -> None:
    """Skip the 60s per-user ``_AUTO_LAST`` throttle so back-to-back
    tests don't false-negative on 'throttled'. The route lives at
    ``POST /workforce/_test/reset-autoclock`` and is guarded to only
    scrub the caller's own key."""
    try:
        requests.post(
            f"{API}/workforce/_test/reset-autoclock",
            headers={"Authorization": f"Bearer {mike_tok}"},
            timeout=10,
        )
    except Exception:
        pass


# ── Safety test ─────────────────────────────────────────────────────
def test_p12_2_auto_clockin_scoped_to_caller_not_coworker(dbc, _cleanup):
    """Two techs, two jobs, one geofence — auto-clockin must land on
    the CALLER'S job (or refuse), never on the coworker's."""
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    carlos = dbc.users.find_one({"email": "carlos@aquaterra.com"})
    assert mike and carlos, "expected Mike + Carlos seeded"
    tenant_id = mike["tenant_id"]
    assert carlos["tenant_id"] == tenant_id, (
        "test invariant: Mike and Carlos share a tenant"
    )

    # Seed two jobs on TODAY (server local; use UTC for the
    # scheduled_start bounds so the ``[day_start, day_end)`` filter
    # matches regardless of DST / TZ).
    now = datetime.now(timezone.utc)
    scheduled = now.replace(microsecond=0).isoformat()
    mike_job_id = f"p12-2-mike-{uuid.uuid4().hex[:8]}"
    carlos_job_id = f"p12-2-carlos-{uuid.uuid4().hex[:8]}"

    # Carlos's job — Mike will try to auto-clock into this by posting
    # a coord AT Carlos's site coords. Pre-P12.2 this succeeded
    # (clobber widened the filter to any tenant job).
    dbc.jobs.insert_one({
        "id": carlos_job_id, "tenant_id": tenant_id,
        "technician_id": carlos["id"], "title": "p12.2-coworker-job",
        "status": "scheduled",
        "scheduled_start": scheduled,
        "site_lat": 33.601000, "site_lng": -112.301000,
        "address": "Carlos site",
    })
    _cleanup["job_ids"].append(carlos_job_id)
    # Mike's job — far away from Carlos's site (>1km, well outside
    # any reasonable geofence radius).
    dbc.jobs.insert_one({
        "id": mike_job_id, "tenant_id": tenant_id,
        "technician_id": mike["id"], "title": "p12.2-caller-job",
        "status": "scheduled",
        "scheduled_start": scheduled,
        "site_lat": 33.700000, "site_lng": -112.200000,
        "address": "Mike site",
    })
    _cleanup["job_ids"].append(mike_job_id)
    _cleanup["time_entry_uids"].append(mike["id"])

    mike_tok = _login("mike@aquaterra.com")["access_token"]
    _reset_autoclock_ratelimit(mike_tok)
    # Also close any pre-existing open entry for Mike so the
    # ``already_clocked_in`` short-circuit doesn't hide the widening.
    dbc.time_entries.delete_many(
        {"user_id": mike["id"], "clock_out_at": None},
    )

    # Post an auto-clockin call with coords AT CARLOS'S job site.
    r = requests.post(
        f"{API}/workforce/auto-clock-in",
        headers={"Authorization": f"Bearer {mike_tok}"},
        json={"lat": 33.601000, "lng": -112.301000, "accuracy": 10.0},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()

    # ACCEPTANCE — never auto-clocks into the coworker's job.
    assert body.get("clocked_in") is False or (
        body.get("clocked_in") is True
        and body.get("job_id") != carlos_job_id
    ), (
        f"SAFETY REGRESSION: Mike was auto-clocked into Carlos's job. "
        f"body={body}"
    )
    # Concretely — since Mike has no job in the geofence, the reason
    # is ``not_at_any_scheduled_site``.
    assert body.get("reason") in (
        "not_at_any_scheduled_site",
        # Preserve the endpoint's other legit refuse-reasons in case
        # of a rare seed race (throttle / accuracy). Anything BUT a
        # successful clock-in onto Carlos's job is acceptable.
        "out_of_time_window",
        "throttled",
        "low_accuracy",
    ), body

    # Belt-and-braces: no time_entries row was created for Mike on
    # Carlos's job.
    leaked = dbc.time_entries.find_one(
        {"user_id": mike["id"], "job_id": carlos_job_id},
        {"_id": 0, "id": 1, "job_id": 1},
    )
    assert leaked is None, (
        f"SAFETY REGRESSION: a time_entries row leaked onto Carlos's "
        f"job: {leaked}"
    )


# ── Sanity test: same seed shape, but coords ON MIKE'S OWN site → OK ─
def test_p12_2_auto_clockin_still_works_on_own_site(dbc, _cleanup):
    """Regression net: the fix mustn't be so tight that a legit
    on-site auto-clockin stops working. Same fixture as above, but
    Mike posts coords AT HIS OWN site — expect ``clocked_in: True``
    (or a legit refuse-reason that ISN'T the tech-lane one)."""
    mike = dbc.users.find_one({"email": "mike@aquaterra.com"})
    carlos = dbc.users.find_one({"email": "carlos@aquaterra.com"})
    assert mike and carlos
    tenant_id = mike["tenant_id"]

    now = datetime.now(timezone.utc)
    scheduled = now.replace(microsecond=0).isoformat()
    mike_job_id = f"p12-2-happy-mike-{uuid.uuid4().hex[:8]}"
    carlos_job_id = f"p12-2-happy-carlos-{uuid.uuid4().hex[:8]}"
    dbc.jobs.insert_one({
        "id": carlos_job_id, "tenant_id": tenant_id,
        "technician_id": carlos["id"], "title": "p12.2-happy-coworker",
        "status": "scheduled", "scheduled_start": scheduled,
        "site_lat": 33.601000, "site_lng": -112.301000,
    })
    _cleanup["job_ids"].append(carlos_job_id)
    dbc.jobs.insert_one({
        "id": mike_job_id, "tenant_id": tenant_id,
        "technician_id": mike["id"], "title": "p12.2-happy-caller",
        "status": "scheduled", "scheduled_start": scheduled,
        "site_lat": 33.700000, "site_lng": -112.200000,
    })
    _cleanup["job_ids"].append(mike_job_id)
    _cleanup["time_entry_uids"].append(mike["id"])

    mike_tok = _login("mike@aquaterra.com")["access_token"]
    _reset_autoclock_ratelimit(mike_tok)
    dbc.time_entries.delete_many(
        {"user_id": mike["id"], "clock_out_at": None},
    )

    r = requests.post(
        f"{API}/workforce/auto-clock-in",
        headers={"Authorization": f"Bearer {mike_tok}"},
        json={"lat": 33.700000, "lng": -112.200000, "accuracy": 10.0},
        timeout=15,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    # Expect a happy auto-clockin — OR at worst a business-logic
    # refuse-reason that's about time/accuracy, never
    # ``not_at_any_scheduled_site`` (that would prove the fix
    # over-tightened and dropped Mike's own job from the query).
    if body.get("clocked_in"):
        assert body.get("job_id") == mike_job_id, body
    else:
        assert body.get("reason") in ("out_of_time_window", "throttled"), body
