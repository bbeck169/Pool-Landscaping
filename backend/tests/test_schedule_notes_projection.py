"""Feb-2026 · Schedule surface — job-level ``notes`` on ``GET /api/jobs``.

Contract:
* ``notes`` is present on the job row when the underlying doc has a
  non-empty string value.
* Values longer than 500 chars are capped server-side and the row
  carries ``notes_truncated=True``.
* Values <=500 chars come through untouched with
  ``notes_truncated=False``.

Sync ``pymongo`` + live ``requests`` — matches the routes-enriched /
recurring-autogen test styles that already ship in this suite.
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from pymongo import MongoClient


BASE_URL = ""
for ln in Path("/app/frontend/.env").read_text().splitlines():
    if ln.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = ln.split("=", 1)[1].strip().strip('"').rstrip("/")
        break
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
AQUATERRA_TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


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


@pytest.fixture(scope="module")
def super_token():
    r = requests.post(f"{API}/auth/login", json=SUPER, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture()
def seeded_jobs(sync_db):
    """Seed three jobs — short notes, exactly-500 notes, and >500 notes."""
    tag = uuid4().hex[:10]
    short_id = f"notes-short-{tag}"
    exact_id = f"notes-exact-{tag}"
    long_id  = f"notes-long-{tag}"
    date_iso = "2026-08-19"
    sync_db.jobs.insert_many([
        {"id": short_id, "tenant_id": AQUATERRA_TID,
         "customer_id": "notes-cust", "customer_name": "Notes Fixture",
         "scheduled_date": date_iso, "status": "scheduled",
         "service_type": "Weekly Pool",
         "notes": "short note"},
        {"id": exact_id, "tenant_id": AQUATERRA_TID,
         "customer_id": "notes-cust", "customer_name": "Notes Fixture",
         "scheduled_date": date_iso, "status": "scheduled",
         "service_type": "Weekly Pool",
         "notes": "x" * 500},
        {"id": long_id,  "tenant_id": AQUATERRA_TID,
         "customer_id": "notes-cust", "customer_name": "Notes Fixture",
         "scheduled_date": date_iso, "status": "scheduled",
         "service_type": "Weekly Pool",
         "notes": "y" * 900},
    ])
    yield {"short": short_id, "exact": exact_id, "long": long_id,
             "date": date_iso}
    sync_db.jobs.delete_many({"id": {"$in": [short_id, exact_id, long_id]}})


def _by_id(rows, jid):
    for r in rows:
        if r.get("id") == jid:
            return r
    return None


def test_short_notes_pass_through_untruncated(super_token, seeded_jobs):
    r = requests.get(
        f"{API}/jobs?scheduled_date={seeded_jobs['date']}",
        headers={"Authorization": f"Bearer {super_token}"},
        timeout=15,
    )
    r.raise_for_status()
    row = _by_id(r.json(), seeded_jobs["short"])
    assert row is not None, "seeded short-notes job missing from /api/jobs"
    assert row.get("notes") == "short note"
    assert row.get("notes_truncated") is False


def test_notes_are_capped_at_500_and_flag_set(super_token, seeded_jobs):
    r = requests.get(
        f"{API}/jobs?scheduled_date={seeded_jobs['date']}",
        headers={"Authorization": f"Bearer {super_token}"},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    long_row = _by_id(body, seeded_jobs["long"])
    exact_row = _by_id(body, seeded_jobs["exact"])
    # 900-char note: capped to 500 and flagged truncated.
    assert len(long_row["notes"]) == 500
    assert long_row["notes_truncated"] is True
    # Exactly-500-char note: passes through, NOT flagged truncated.
    assert len(exact_row["notes"]) == 500
    assert exact_row["notes_truncated"] is False
