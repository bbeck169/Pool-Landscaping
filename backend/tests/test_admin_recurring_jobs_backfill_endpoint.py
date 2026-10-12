"""Feb-2026 · P0 · POST /api/admin/recurring-jobs/backfill-horizon pytest.

Covers the super-admin HTTP wrapper around the shared horizon-backfill
service. The service itself is covered by the existing CLI regression
in ``test_recurring_cron_cursor_fix.py``; this file validates the
HTTP contract (auth, validation, audit, idempotency through the HTTP
path).

Test cases:
  1. 403 for role=admin
  2. 403 for role=manager
  3. 403 for role=technician
  4. 403 for role=customer
  5. 200 for role=super_admin + dry_run=true — no DB writes
  6. 200 for super_admin + dry_run=false — commit path (idempotent on
     preview: inserted=0, missing=0 because preview has been healed)
  7. 200 for super_admin with tenant_id scope — scoped sweep
  8. 422 for days_ahead=0 (Pydantic min bound)
  9. 422 for days_ahead=31 (Pydantic max bound)
  10. Two audit_logs rows are emitted per invocation (invoke + complete)
      with the correct action + actor_user_id + payload + result.

Live HTTP + sync pymongo pattern — matches
``test_admin_users_unlock_promote.py`` et al.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)

_PATH = "/admin/recurring-jobs/backfill-horizon"


# ─── auth helpers ───────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(email: str):
    return {"Authorization": f"Bearer {_login(email)}"}


# ─── fixtures ───────────────────────────────────────────────────────
@pytest.fixture
def mongo():
    c = MongoClient(_MONGO_URL)
    yield c[_DB_NAME]
    c.close()


@pytest.fixture
def super_admin_user_id(mongo):
    row = mongo.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "id": 1})
    assert row and row.get("id"), "super_admin seed missing"
    return row["id"]


@pytest.fixture
def aquaterra_tenant_id(mongo):
    row = mongo.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    assert row and row.get("tenant_id"), "aquaterra tenant missing"
    return row["tenant_id"]


# ─── 1-4 · auth gate (403 for every non-super-admin role) ───────────
@pytest.mark.parametrize("email", [
    "admin@aquaterra.com",
    "manager@aquaterra.com",
    "mike@aquaterra.com",
    "customer@aquaterra.com",
])
def test_backfill_horizon_requires_super_admin(email):
    r = requests.post(
        f"{API}{_PATH}",
        headers=_headers(email),
        json={"days_ahead": 14, "dry_run": True, "tenant_id": None},
        timeout=15,
    )
    assert r.status_code == 403, (
        f"role={email} expected 403 got {r.status_code}: {r.text}")


# ─── 5 · dry-run · no DB writes ─────────────────────────────────────
def test_backfill_horizon_dry_run_no_writes(mongo):
    jobs_before = mongo.jobs.count_documents({})
    r = requests.post(
        f"{API}{_PATH}",
        headers=_headers("super@aquaterra.com"),
        json={"days_ahead": 14, "dry_run": True, "tenant_id": None},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "dry_run"
    assert body["days_ahead"] == 14
    assert body["tenant_scope"] is None
    # Service always populates these keys even on dry_run.
    for k in ("templates_processed", "expected_dates_total",
               "already_present", "missing", "soft_deleted_present",
               "inserted", "race_dedup", "insert_errors",
               "errored_templates", "warnings"):
        assert k in body, f"missing summary key {k!r}"
    # Dry-run must never write.
    assert body["inserted"] == 0
    jobs_after = mongo.jobs.count_documents({})
    assert jobs_after == jobs_before, (
        f"dry-run must not write — before={jobs_before} after={jobs_after}")


# ─── 6 · commit · idempotent on healed preview ──────────────────────
def test_backfill_horizon_commit_idempotent_on_healed_preview(mongo):
    """Preview was healed by the operator CLI before this endpoint
    landed, so a fresh commit call MUST be a no-op (missing=0,
    inserted=0). Running it twice back-to-back hits the HTTP
    idempotency path once more.
    """
    hdrs = _headers("super@aquaterra.com")
    jobs_before = mongo.jobs.count_documents({})

    r1 = requests.post(
        f"{API}{_PATH}", headers=hdrs,
        json={"days_ahead": 14, "dry_run": False, "tenant_id": None},
        timeout=60,
    )
    assert r1.status_code == 200, r1.text
    s1 = r1.json()
    assert s1["mode"] == "commit"
    # Healed-preview guarantee: nothing to backfill.
    assert s1["missing"] == 0, f"preview must be healed · got {s1}"
    assert s1["inserted"] == 0

    r2 = requests.post(
        f"{API}{_PATH}", headers=hdrs,
        json={"days_ahead": 14, "dry_run": False, "tenant_id": None},
        timeout=60,
    )
    assert r2.status_code == 200, r2.text
    s2 = r2.json()
    assert s2["missing"] == 0
    assert s2["inserted"] == 0

    jobs_after = mongo.jobs.count_documents({})
    assert jobs_after == jobs_before, (
        f"idempotent commit must not write — "
        f"before={jobs_before} after={jobs_after}")


# ─── 7 · tenant_id scope — scoped sweep ─────────────────────────────
def test_backfill_horizon_tenant_scope(aquaterra_tenant_id):
    r = requests.post(
        f"{API}{_PATH}",
        headers=_headers("super@aquaterra.com"),
        json={"days_ahead": 14, "dry_run": True,
              "tenant_id": aquaterra_tenant_id},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_scope"] == aquaterra_tenant_id
    # Every per-template row should carry the scoped tenant_id.
    for row in (body.get("per_template_detail") or []):
        assert row.get("tenant_id") == aquaterra_tenant_id


# ─── 8-9 · days_ahead validation ────────────────────────────────────
@pytest.mark.parametrize("bad", [0, 31, -1, 100])
def test_backfill_horizon_rejects_out_of_range_days_ahead(bad):
    r = requests.post(
        f"{API}{_PATH}",
        headers=_headers("super@aquaterra.com"),
        json={"days_ahead": bad, "dry_run": True, "tenant_id": None},
        timeout=15,
    )
    assert r.status_code == 422, (
        f"days_ahead={bad} expected 422 got {r.status_code}: {r.text}")


# ─── 10 · audit rows written on invoke + complete ───────────────────
def test_backfill_horizon_writes_invoke_and_complete_audit_rows(
        mongo, super_admin_user_id, aquaterra_tenant_id):
    """A single dry-run invocation must emit exactly two new
    db.audit_logs rows (``.invoke`` + ``.complete``) with matching
    actor_user_id, payload, and in the complete row a populated
    ``result`` + ``success=True``.
    """
    ts_before = datetime.now(timezone.utc).isoformat()
    # Burn a unique days_ahead value so we can filter by payload.
    unique_days_ahead = 7

    r = requests.post(
        f"{API}{_PATH}",
        headers=_headers("super@aquaterra.com"),
        json={"days_ahead": unique_days_ahead, "dry_run": True,
              "tenant_id": aquaterra_tenant_id},
        timeout=60,
    )
    assert r.status_code == 200, r.text

    # Pull the two most recent rows for this action family.
    rows = list(mongo.audit_logs.find(
        {
            "action": {"$regex": "^admin\\.recurring_jobs\\.backfill_horizon"},
            "actor_user_id": super_admin_user_id,
            "created_at": {"$gte": ts_before},
            "payload.days_ahead": unique_days_ahead,
        },
        {"_id": 0},
    ).sort("created_at", 1))

    assert len(rows) == 2, (
        f"expected exactly 2 audit rows, got {len(rows)}: {rows}")

    invoke, complete = rows[0], rows[1]
    assert invoke["action"] == (
        "admin.recurring_jobs.backfill_horizon.invoke")
    assert complete["action"] == (
        "admin.recurring_jobs.backfill_horizon.complete")

    for row in (invoke, complete):
        assert row["actor_user_id"] == super_admin_user_id
        assert row["actor_role"] == "super_admin"
        assert row["tenant_id"] == aquaterra_tenant_id
        assert row["payload"]["days_ahead"] == unique_days_ahead
        assert row["payload"]["dry_run"] is True
        assert row["payload"]["tenant_id"] == aquaterra_tenant_id

    # Invoke row MUST NOT have a result; complete row MUST.
    assert "result" not in invoke
    assert "result" in complete
    assert complete["result"]["mode"] == "dry_run"
    assert complete["result"]["days_ahead"] == unique_days_ahead
    assert complete["success"] is True
    assert complete.get("error") is None
