"""Feb-2026 · Task B · ``routers/jobs.create_job`` graceful E11000.

Source-inspection + live-server contract test.

Rationale: the 409 branch is defensive coverage — the ``JobIn`` model
does not expose ``recurring_template_id`` to end callers, so the branch
is unreachable through the normal POST /api/jobs surface. Any TestClient
attempt to fake the DB collision runs into Motor loop-binding issues
(known flake pattern in this repo). We instead:

  1. Assert the exception handler exists in source and matches spec —
     wraps the ``db.jobs.insert_one`` call, catches ``DuplicateKeyError``,
     re-raises as HTTPException(409) with the expected message.
  2. Assert the happy path is unchanged — a real POST /api/jobs still
     returns 200 with a valid id (Terry Hernandez fixture).

The underlying partial-unique index correctness is already verified by
``test_partial_index_still_dedups_recurring_occurrences`` (13-case suite).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    for ln in Path("/app/frontend/.env").read_text().splitlines():
        if ln.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = ln.split("=", 1)[1].strip().strip('"')
            break
BASE_URL = (BASE_URL or "").rstrip("/")
API = f"{BASE_URL}/api"

SUPER = {"email": "super@aquaterra.com", "password": "password123"}
TERRY = "83a42be6-0b12-43df-9c92-94904576d86f"


def _tok() -> str:
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login", json=SUPER, timeout=30)
            if r.status_code == 200:
                return r.json()["access_token"]
        except requests.RequestException:
            pass
    pytest.skip("backend unreachable")


def _read_src() -> str:
    return Path("/app/backend/routers/jobs.py").read_text()


# ── Source contract ─────────────────────────────────────────────────
def test_create_job_imports_duplicate_key_error():
    src = _read_src()
    assert "from pymongo.errors import DuplicateKeyError" in src, (
        "DuplicateKeyError import missing — the 409 handler can't work "
        "without the exception class in scope."
    )


def test_create_job_wraps_insert_in_try_except_duplicate_key():
    src = _read_src()
    # The create_job insert must be inside a try/except that catches
    # DuplicateKeyError and re-raises as HTTPException(409).
    assert (
        "try:\n        await db.jobs.insert_one(doc)\n"
        "    except DuplicateKeyError:" in src
    ), "insert_one is not wrapped in the expected try/except pattern"


def test_create_job_raises_409_with_expected_message():
    src = _read_src()
    # The message text is a product-facing string — assert both the
    # 409 status_code and the exact user-visible message so we catch
    # accidental UX regressions.
    assert "status_code=409" in src
    assert (
        "A job for this recurring template already exists on this date."
        in src
    )


# ── Live contract ───────────────────────────────────────────────────
def test_create_job_happy_path_still_returns_200():
    """The try/except must NOT change the happy path — a normal POST
    (no recurring_template_id, no collision) still returns 200 with a
    real id."""
    from pymongo import MongoClient
    tok = _tok()
    r = requests.post(
        f"{API}/jobs",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        json={
            "title": "task-b-happy",
            "customer_id": TERRY,
            "service_type": "Pool Cleaning",
            "scheduled_date": "2030-06-01",
            "price": 0,
            "status": "scheduled",
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    jid = r.json().get("id")
    assert jid
    # cleanup
    mongo_url = None
    for ln in Path("/app/backend/.env").read_text().splitlines():
        if ln.startswith("MONGO_URL="):
            mongo_url = ln.split("=", 1)[1].strip().strip('"')
            break
    if mongo_url:
        cli = MongoClient(mongo_url)
        cli["aquaterra"].jobs.delete_one({"id": jid})
        cli.close()
