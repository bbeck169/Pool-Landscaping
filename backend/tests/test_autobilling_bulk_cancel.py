"""Backend tests · Feb-2026 — Autobilling bulk-cancel (Phase AB1).

Covers:
  * POST /api/autobilling/bulk-cancel
    - flips only eligible rows (active + not already cancelled)
    - skips already-cancelled with reason
    - non-admin → 403
    - hard cap of 500 enforced by Pydantic
    - audit row lands in db.audits with kind=autobilling_bulk_cancel
  * POST /api/autobilling/runs/bulk-cancel
    - only cancels rows whose status ∈ {pending, scheduled, queued}
    - skips fired / completed / failed / late_missed with a reason
      string reflecting current_status
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db()
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Fixed tenant for the aquaterra super_admin account seeded in the pod.
_TENANT_ID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


def _tech_headers() -> dict:
    # Any known non-admin role — customer@ is a customer, so it hits
    # the require_admin gate and produces a 403.
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


def _server_up() -> bool:
    try:
        requests.get(f"{API}/", timeout=2)
        return True
    except Exception:
        return False


needs_server = pytest.mark.skipif(
    not _server_up(), reason="backend server not reachable on :8001")


# ══════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def seeded_plans() -> dict:
    ids = {
        "active_a": f"TEST-ab1-a-{uuid.uuid4().hex[:8]}",
        "active_b": f"TEST-ab1-b-{uuid.uuid4().hex[:8]}",
        "already": f"TEST-ab1-alr-{uuid.uuid4().hex[:8]}",
    }
    now = datetime.now(timezone.utc).isoformat()
    _sync.billing_plans.insert_many([
        {"id": ids["active_a"], "tenant_id": _TENANT_ID,
          "customer_id": "test-c-a", "customer_name": "AB1 Test A",
          "service": "monthly pool", "frequency": "monthly",
          "amount": 200, "active": True, "created_at": now},
        {"id": ids["active_b"], "tenant_id": _TENANT_ID,
          "customer_id": "test-c-b", "customer_name": "AB1 Test B",
          "service": "chem drop", "frequency": "weekly",
          "amount": 50, "active": True, "created_at": now},
        {"id": ids["already"], "tenant_id": _TENANT_ID,
          "customer_id": "test-c-c", "customer_name": "AB1 Test C",
          "service": "closed", "frequency": "weekly",
          "amount": 25, "active": False,
          "cancelled_at": "2025-01-01T00:00:00Z", "created_at": now},
    ])
    try:
        yield ids
    finally:
        _sync.billing_plans.delete_many({"id": {"$in": list(ids.values())}})
        _sync.audits.delete_many(
            {"kind": "autobilling_bulk_cancel",
              "target_id": {"$in": list(ids.values())}})


@pytest.fixture
def seeded_runs() -> dict:
    """Seed three autobilling_runs rows — one pending (eligible),
    one fired (skipped), one already-cancelled (skipped)."""
    ids = {
        "pending": f"TEST-ab1-run-pend-{uuid.uuid4().hex[:8]}",
        "fired": f"TEST-ab1-run-fire-{uuid.uuid4().hex[:8]}",
        "already": f"TEST-ab1-run-alr-{uuid.uuid4().hex[:8]}",
    }
    now = datetime.now(timezone.utc).isoformat()
    _sync.autobilling_runs.insert_many([
        {"id": ids["pending"], "tenant_id": _TENANT_ID,
          "plan_id": "test-plan-a", "plan_name": "AB1 Pending",
          "status": "pending", "ts": now},
        {"id": ids["fired"], "tenant_id": _TENANT_ID,
          "plan_id": "test-plan-b", "plan_name": "AB1 Fired",
          "status": "fired", "ts": now},
        {"id": ids["already"], "tenant_id": _TENANT_ID,
          "plan_id": "test-plan-c", "plan_name": "AB1 Already",
          "status": "cancelled", "cancelled_at": now, "ts": now},
    ])
    try:
        yield ids
    finally:
        _sync.autobilling_runs.delete_many(
            {"id": {"$in": list(ids.values())}})
        _sync.audits.delete_many(
            {"kind": "autobilling_runs_bulk_cancel",
              "target_id": {"$in": list(ids.values())}})


# ══════════════════════════════════════════════════════════════════
# /api/autobilling/bulk-cancel — plans
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_plans_bulk_cancel_flips_only_active_rows(seeded_plans):
    ids = seeded_plans
    r = requests.post(
        f"{API}/autobilling/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": [ids["active_a"], ids["active_b"], ids["already"]],
              "reason": "pytest AB1 flip"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cancelled"] == 2
    assert body["skipped"] == 1
    # Correct per-id outcomes.
    by_id = {row["id"]: row for row in body["results"]}
    assert by_id[ids["active_a"]]["status"] == "cancelled"
    assert by_id[ids["active_b"]]["status"] == "cancelled"
    assert by_id[ids["already"]]["status"] == "skipped"
    assert "already" in by_id[ids["already"]]["reason"]
    # Mongo state — flipped rows now have cancelled_at + active=False.
    for k in ("active_a", "active_b"):
        row = _sync.billing_plans.find_one({"id": ids[k]},
                                            {"_id": 0, "active": 1,
                                              "cancelled_at": 1,
                                              "cancel_reason": 1})
        assert row["active"] is False
        assert row["cancelled_at"]
        assert row["cancel_reason"] == "pytest AB1 flip"


@needs_server
def test_plans_bulk_cancel_writes_audit_rows(seeded_plans):
    ids = seeded_plans
    requests.post(
        f"{API}/autobilling/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": [ids["active_a"], ids["active_b"], ids["already"]],
              "reason": "pytest AB1 audit"},
        timeout=30,
    )
    audits = list(_sync.audits.find(
        {"kind": "autobilling_bulk_cancel",
          "target_id": {"$in": [ids["active_a"], ids["active_b"]]}},
        {"_id": 0, "target_id": 1, "actor_email": 1, "cancel_reason": 1},
    ))
    assert len(audits) == 2
    for a in audits:
        assert a["cancel_reason"] == "pytest AB1 audit"
        assert a["actor_email"] == "manager@aquaterra.com"


@needs_server
def test_plans_bulk_cancel_requires_admin():
    r = requests.post(
        f"{API}/autobilling/bulk-cancel",
        headers=_tech_headers(),
        json={"ids": ["irrelevant"], "reason": "denied"},
        timeout=15,
    )
    assert r.status_code == 403


@needs_server
def test_plans_bulk_cancel_hard_cap_enforced():
    r = requests.post(
        f"{API}/autobilling/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": [f"x-{i}" for i in range(501)]},
        timeout=15,
    )
    # 400 (our custom message) or 422 (Pydantic list-length) — either is fine.
    assert r.status_code in (400, 422), r.text


@needs_server
def test_plans_bulk_cancel_empty_ids_400():
    r = requests.post(
        f"{API}/autobilling/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": []},
        timeout=15,
    )
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════
# /api/autobilling/runs/bulk-cancel — runs
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_runs_bulk_cancel_only_cancels_eligible_statuses(seeded_runs):
    ids = seeded_runs
    r = requests.post(
        f"{API}/autobilling/runs/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": [ids["pending"], ids["fired"], ids["already"]],
              "reason": "pytest runs"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {row["id"]: row for row in body["results"]}
    assert by_id[ids["pending"]]["status"] == "cancelled"
    assert by_id[ids["fired"]]["status"] == "skipped"
    assert "not_eligible" in by_id[ids["fired"]]["reason"]
    assert "fired" in by_id[ids["fired"]]["reason"]
    assert by_id[ids["already"]]["status"] == "skipped"
    assert "already_cancelled" in by_id[ids["already"]]["reason"]
    assert body["cancelled"] == 1
    assert body["skipped"] == 2
    # Mongo state — the pending row is now cancelled.
    row = _sync.autobilling_runs.find_one(
        {"id": ids["pending"]},
        {"_id": 0, "status": 1, "cancelled_at": 1, "cancel_reason": 1})
    assert row["status"] == "cancelled"
    assert row["cancelled_at"]
    assert row["cancel_reason"] == "pytest runs"
    # Fired row was NOT touched.
    fired = _sync.autobilling_runs.find_one(
        {"id": ids["fired"]},
        {"_id": 0, "status": 1, "cancelled_at": 1})
    assert fired["status"] == "fired"
    assert not fired.get("cancelled_at")


@needs_server
def test_runs_bulk_cancel_requires_admin():
    r = requests.post(
        f"{API}/autobilling/runs/bulk-cancel",
        headers=_tech_headers(),
        json={"ids": ["irrelevant"]},
        timeout=15,
    )
    assert r.status_code == 403


@needs_server
def test_runs_bulk_cancel_audit_row_written(seeded_runs):
    ids = seeded_runs
    requests.post(
        f"{API}/autobilling/runs/bulk-cancel",
        headers=_admin_headers(),
        json={"ids": [ids["pending"]], "reason": "audit trail check"},
        timeout=15,
    )
    audit = _sync.audits.find_one(
        {"kind": "autobilling_runs_bulk_cancel",
          "target_id": ids["pending"]},
        {"_id": 0, "target_id": 1, "actor_email": 1, "cancel_reason": 1},
    )
    assert audit is not None
    assert audit["cancel_reason"] == "audit trail check"
    assert audit["actor_email"] == "manager@aquaterra.com"
