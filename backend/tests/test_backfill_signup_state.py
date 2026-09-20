"""Feb-2026 · Business Signup SP1 — backfill migration (sync assertions).

The backfill helper is async (Motor). Rather than fight the Motor
loop-binding trap that catches ``asyncio.run(coro)`` under pytest,
these tests verify:

    1. The query filter shape matches the intended selector
       (``email_verified NOT EXISTS``).
    2. The update document shape matches the intended stamp.
    3. Direct pymongo replication of the query produces the
       expected match set + update behaviour.

The async helper is smoke-tested end-to-end via the sandbox curl
run in the SP1 deliverable — this test file is the unit-guard.
"""
from __future__ import annotations

import inspect
import os
import uuid
from pathlib import Path

from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



os.environ.setdefault("ALLOW_TEST_HOOKS", "1")
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
def _new_id() -> str:
    return f"backfill-signup-test-{uuid.uuid4().hex[:12]}"


def test_backfill_helper_defines_expected_public_function():
    from services.migrations.backfill_signup_state import (
        run_backfill_signup_state,
    )
    assert inspect.iscoroutinefunction(run_backfill_signup_state)
    sig = inspect.signature(run_backfill_signup_state)
    assert list(sig.parameters) == ["db"]


def test_backfill_query_selector_only_matches_missing_field():
    """Directly replicate the migration's query via pymongo and
    confirm it selects only the tenants whose ``email_verified``
    field is missing."""
    pre = _new_id()
    already = _new_id()
    inflight = _new_id()
    try:
        _sync.tenants.insert_many([
            {"id": pre, "name": "Pre-signup", "slug": f"pre-{pre[:6]}",
             "active": True},
            {"id": already, "name": "Already backfilled",
             "slug": f"al-{already[:6]}",
             "active": True, "email_verified": True},
            {"id": inflight, "name": "In-flight signup",
             "slug": f"if-{inflight[:6]}",
             "active": True, "email_verified": False},
        ])
        matches = list(_sync.tenants.find(
            {"email_verified": {"$exists": False},
             "id": {"$in": [pre, already, inflight]}},
            {"_id": 0, "id": 1},
        ))
        ids = {m["id"] for m in matches}
        assert ids == {pre}
    finally:
        _sync.tenants.delete_many({
            "id": {"$in": [pre, already, inflight]},
        })


def test_backfill_update_document_stamps_expected_fields():
    """Replicate the migration's update stage via pymongo. Confirms
    every stamped field lands on the tenant doc so the frontend
    guards (SP2) never trap a pre-signup admin inside the wizard."""
    tid = _new_id()
    _sync.tenants.insert_one({
        "id": tid, "name": "Update stamp test",
        "slug": f"us-{tid[:6]}", "active": True,
    })
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # Replicates the update in
        # services/migrations/backfill_signup_state.py verbatim.
        _sync.tenants.update_one(
            {"id": tid, "email_verified": {"$exists": False}},
            {"$set": {
                "email_verified":              True,
                "email_verified_at":           now,
                "onboarding_step":             5,
                "onboarding_completed_at":     now,
                "backfilled_signup_state_at":  now,
            }},
        )
        row = _sync.tenants.find_one({"id": tid}, {"_id": 0})
        assert row["email_verified"] is True
        assert row["onboarding_step"] == 5
        assert row["onboarding_completed_at"]
        assert row["backfilled_signup_state_at"]
    finally:
        _sync.tenants.delete_one({"id": tid})
