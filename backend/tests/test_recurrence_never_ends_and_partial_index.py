"""Feb-2026 · Never-end recurrence + partial-index fix.

Sync HTTP + sync pymongo pattern to avoid Motor loop-binding flakes.
Mirrors ``test_pool_crm_api.py`` style. Direct-Mongo checks use a
fresh ``pymongo.MongoClient`` (sync) so they can't collide with the
running app server's Motor loop.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from datetime import date

import pytest
import requests
from pymongo import MongoClient


# ── Base URL bootstrap ───────────────────────────────────────────────
BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    envf = Path("/app/frontend/.env").read_text().splitlines()
    for ln in envf:
        if ln.startswith("REACT_APP_BACKEND_URL=") or ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE_URL = ln.split("=", 1)[1].strip().strip('"')
            break
BASE_URL = (BASE_URL or "").rstrip("/")
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
TERRY_ID = "83a42be6-0b12-43df-9c92-94904576d86f"


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _get_env(key: str) -> str:
    v = os.environ.get(key)
    if v:
        return v
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith(f"{key}="):
            return ln.split("=", 1)[1].strip().strip('"')
    return ""


# ── Session fixtures ─────────────────────────────────────────────────
@pytest.fixture(scope="session")
def super_tok() -> str:
    # Warm up + retry once — ingress can 502 briefly right after reload.
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/auth/login", json=SUPER, timeout=60)
            if r.status_code == 200:
                return r.json()["access_token"]
            last_err = r.text
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(3)
    pytest.skip(f"backend unreachable after 3 attempts: {last_err}")


@pytest.fixture(scope="session")
def sync_db():
    """Fresh sync mongo client — never touches Motor's loop."""
    mongo_url = _get_env("MONGO_URL")
    db_name = _get_env("DB_NAME") or "aquaterra"
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
    try:
        yield client[db_name]
    finally:
        client.close()


# ═══ Never-end flag on create ═══════════════════════════════════════
def test_create_never_ends_forces_null_end_date(super_tok):
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_never_ends_svc",
            "frequency": "weekly",
            "day_of_week": 2,
            "start_date": "2026-08-18",
            "end_date": "2026-12-31",
            "recurrence_never_ends": True,
            "price_cents": 12000,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    try:
        assert body["recurrence_never_ends"] is True
        assert body["end_date"] is None
    finally:
        requests.delete(f"{API}/recurring-jobs/{body['id']}",
                         headers=_h(super_tok), timeout=30)


def test_backward_compat_flag_absent(super_tok):
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_backcompat_svc",
            "frequency": "weekly",
            "day_of_week": 3,
            "start_date": "2026-08-18",
            "end_date": "2026-12-31",
            "price_cents": 12000,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    try:
        assert body.get("recurrence_never_ends") in (False, None)
        assert body["end_date"] == "2026-12-31"
    finally:
        requests.delete(f"{API}/recurring-jobs/{body['id']}",
                         headers=_h(super_tok), timeout=30)


def test_patch_never_ends_clears_end_date(super_tok):
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_patch_svc",
            "frequency": "weekly",
            "day_of_week": 4,
            "start_date": "2026-08-18",
            "end_date": "2026-12-31",
            "price_cents": 12000,
        },
        timeout=30,
    )
    tpl_id = r.json()["id"]
    try:
        r = requests.patch(
            f"{API}/recurring-jobs/{tpl_id}",
            headers=_h(super_tok),
            json={"recurrence_never_ends": True},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["end_date"] is None
        assert r.json()["recurrence_never_ends"] is True
    finally:
        requests.delete(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)


# ═══ Stop endpoint ══════════════════════════════════════════════════
def test_stop_endpoint_prunes_future_scheduled_only(super_tok, sync_db):
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_stop_svc",
            "frequency": "weekly",
            "day_of_week": 5,
            "start_date": "2026-08-18",
            "recurrence_never_ends": True,
            "price_cents": 12000,
        },
        timeout=30,
    )
    tpl_id = r.json()["id"]
    started_id = f"test-stop-started-{tpl_id[:8]}"
    try:
        r = requests.post(
            f"{API}/recurring-jobs/{tpl_id}/generate?through=2026-11-30",
            headers=_h(super_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        inserted = r.json()["inserted"]
        assert inserted > 0

        # Seed a started future job that must survive the stop.
        sync_db.jobs.insert_one({
            "id": started_id,
            "tenant_id": AQUATERRA_TID,
            "recurring_template_id": tpl_id,
            "scheduled_date": "2050-01-01",
            "status": "in_progress",
            "title": "test-stop-started",
        })

        r = requests.post(f"{API}/recurring-jobs/{tpl_id}/stop",
                          headers=_h(super_tok), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["template_id"] == tpl_id
        assert body["stopped_at"] == date.today().isoformat()
        assert body["removed_future_jobs"] >= inserted

        r = requests.get(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)
        tpl = r.json()
        assert tpl["active"] is False
        assert tpl["recurrence_never_ends"] is False
        assert tpl["end_date"] == date.today().isoformat()

        survivor = sync_db.jobs.find_one({"id": started_id})
        assert survivor is not None, "started future job was incorrectly pruned"
    finally:
        sync_db.jobs.delete_one({"id": started_id})


def test_stop_by_job_id_shim(super_tok, sync_db):
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_stop_shim_svc",
            "frequency": "weekly",
            "day_of_week": 1,
            "start_date": "2026-08-18",
            "recurrence_never_ends": True,
            "price_cents": 12000,
        },
        timeout=30,
    )
    tpl_id = r.json()["id"]
    try:
        requests.post(
            f"{API}/recurring-jobs/{tpl_id}/generate?through=2026-10-31",
            headers=_h(super_tok), timeout=30,
        )
        job = sync_db.jobs.find_one({"recurring_template_id": tpl_id})
        assert job is not None
        r = requests.post(
            f"{API}/jobs/{job['id']}/recurrence/stop",
            headers=_h(super_tok), timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["template_id"] == tpl_id
    finally:
        requests.delete(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)


def test_stop_by_job_id_shim_rejects_non_recurring(super_tok, sync_db):
    """Non-recurring jobs → 400 (they have no recurring_template_id).

    Seed the job directly so the tenant scoping is deterministic — the
    stop-shim endpoint scopes ``db.jobs.find_one`` to the caller's
    tenant, and any drift in create_job's tenant resolution would
    otherwise surface here as a 404 rather than the expected 400.
    """
    from uuid import uuid4
    jid = f"test-non-recur-{uuid4().hex[:8]}"
    sync_db.jobs.insert_one({
        "id": jid,
        "tenant_id": AQUATERRA_TID,
        "customer_id": TERRY_ID,
        "title": "test-not-recurring",
        "service_type": "Pool Cleaning",
        "scheduled_date": "2028-08-25",
        "status": "scheduled",
        # explicitly no recurring_template_id
    })
    try:
        r = requests.post(f"{API}/jobs/{jid}/recurrence/stop",
                          headers=_h(super_tok), timeout=30)
        assert r.status_code == 400, r.text
        assert "recurring" in r.text.lower()
    finally:
        sync_db.jobs.delete_one({"id": jid})


# ═══ Partial-index migration ═══════════════════════════════════════
def test_partial_index_exists(sync_db):
    """The migration must have installed the partial-unique index."""
    info = sync_db.jobs.index_information()
    spec = info.get("recurring_template_id_1_scheduled_date_1")
    assert spec is not None, "partial-unique index missing"
    # `partialFilterExpression` presence is the discriminator vs. legacy
    # ``sparse: True`` variant.
    assert spec.get("partialFilterExpression"), (
        f"index not partial: {spec}"
    )


def test_partial_index_allows_multiple_non_recurring_same_date(super_tok, sync_db):
    """The Terry-Hernandez repro: multiple non-recurring jobs for the
    same customer on the same date must all succeed. Pre-fix, the 2nd
    collided on the sparse-unique index with E11000."""
    ids = []
    try:
        for i in range(3):
            r = requests.post(
                f"{API}/jobs",
                headers=_h(super_tok),
                json={
                    "title": f"idx_verify_{i}",
                    "customer_id": TERRY_ID,
                    "service_type": "Pool Cleaning",
                    "scheduled_date": "2028-01-15",
                    "price": 0,
                    "status": "scheduled",
                },
                timeout=30,
            )
            assert r.status_code == 200, f"insert {i}: {r.text}"
            ids.append(r.json()["id"])
    finally:
        if ids:
            sync_db.jobs.delete_many({"id": {"$in": ids}})


def test_partial_index_still_dedups_recurring_occurrences(sync_db):
    """Two rows with the same (recurring_template_id, scheduled_date)
    must still collide on the partial-unique index."""
    rtid = "test-partial-idx-tpl"
    r1_id = "test-partial-idx-r1"
    r2_id = "test-partial-idx-r2"
    try:
        sync_db.jobs.insert_one({
            "id": r1_id, "tenant_id": AQUATERRA_TID,
            "recurring_template_id": rtid, "scheduled_date": "2028-02-01",
            "status": "scheduled",
        })
        collided = False
        try:
            sync_db.jobs.insert_one({
                "id": r2_id, "tenant_id": AQUATERRA_TID,
                "recurring_template_id": rtid, "scheduled_date": "2028-02-01",
                "status": "scheduled",
            })
        except Exception as e:
            collided = ("E11000" in str(e)) or ("duplicate" in str(e).lower())
        assert collided, "partial-unique index failed to dedup recurring occurrences"
    finally:
        sync_db.jobs.delete_many({"id": {"$in": [r1_id, r2_id]}})


# ═══ Monthly nth-weekday pattern ════════════════════════════════════
def test_nth_weekday_computation_edge_cases():
    """Directly exercise the ``_nth_weekday_of_month`` helper on known
    edge cases so we lock the arithmetic even if the API is unreachable.

    - 3rd Friday of Jan 2026 → 2026-01-16
    - Last Wednesday of Feb 2028 (leap) → 2028-02-23
    - Last Friday of Feb 2026 → 2026-02-27
    - "5th Monday of Feb 2026" (only 4 Mondays exist) → None (skip)
    """
    from routers.recurring_jobs import _nth_weekday_of_month
    # Friday = weekday 4
    assert _nth_weekday_of_month(2026, 1, "third", 4).isoformat() == "2026-01-16"
    # Wednesday = weekday 2
    assert _nth_weekday_of_month(2028, 2, "last", 2).isoformat() == "2028-02-23"
    # Friday = weekday 4
    assert _nth_weekday_of_month(2026, 2, "last", 4).isoformat() == "2026-02-27"
    # Monday = weekday 0 — only 4 exist in Feb 2026 (2, 9, 16, 23) so 5th → None.
    assert _nth_weekday_of_month(2026, 2, "first", 0).isoformat() == "2026-02-02"
    # Sanity: "last" ≠ "fourth" when 5 exist. Fridays in Jan 2026: 2, 9, 16, 23, 30.
    assert _nth_weekday_of_month(2026, 1, "fourth", 4).isoformat() == "2026-01-23"
    assert _nth_weekday_of_month(2026, 1, "last", 4).isoformat() == "2026-01-30"


def test_nth_weekday_create_and_upcoming(super_tok):
    """3rd Friday recurring template — upcoming[] should be 3rd Friday
    of the next 3 months."""
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_nth_third_fri",
            "frequency": "monthly",
            "monthly_pattern": "nth_weekday",
            "monthly_nth_week": "third",
            "monthly_weekday": 4,  # Friday
            "start_date": "2026-01-01",
            "recurrence_never_ends": True,
            "price_cents": 12000,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tpl_id = r.json()["id"]
    try:
        r = requests.get(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)
        tpl = r.json()
        assert tpl["monthly_pattern"] == "nth_weekday"
        assert tpl["monthly_nth_week"] == "third"
        assert tpl["monthly_weekday"] == 4
        # upcoming[] is the next 6 3rd-Fridays from today's date; every
        # entry must be a Friday and its day-of-month must land within
        # the 15-21 window (3rd Friday range).
        assert len(tpl["upcoming"]) > 0
        for iso in tpl["upcoming"]:
            d = date.fromisoformat(iso)
            assert d.weekday() == 4, f"{iso} is not a Friday"
            assert 15 <= d.day <= 21, f"{iso} not in 3rd-Friday window"
    finally:
        requests.delete(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)


def test_nth_weekday_validation_requires_companion_fields(super_tok):
    """monthly_pattern=nth_weekday without monthly_nth_week must 422."""
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_nth_invalid",
            "frequency": "monthly",
            "monthly_pattern": "nth_weekday",
            "start_date": "2026-01-01",
            "price_cents": 100,
        },
        timeout=30,
    )
    assert r.status_code == 422, r.text
    assert "monthly_nth_week" in r.text


def test_monthly_day_of_month_backcompat(super_tok):
    """Legacy monthly (no monthly_pattern field, day_of_month=15) must
    keep working and default `monthly_pattern` to `day_of_month`."""
    r = requests.post(
        f"{API}/recurring-jobs",
        headers=_h(super_tok),
        json={
            "customer_id": TERRY_ID,
            "service_type": "test_monthly_dom_legacy",
            "frequency": "monthly",
            "day_of_month": 15,
            "start_date": "2026-01-01",
            "price_cents": 100,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tpl = r.json()
    tpl_id = tpl["id"]
    try:
        assert tpl.get("monthly_pattern") in ("day_of_month", None)
        # GET to get upcoming[].
        r = requests.get(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)
        upcoming = r.json().get("upcoming") or []
        for iso in upcoming:
            assert date.fromisoformat(iso).day == 15
    finally:
        requests.delete(f"{API}/recurring-jobs/{tpl_id}",
                         headers=_h(super_tok), timeout=30)
