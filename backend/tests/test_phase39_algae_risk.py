"""Phase 39 · Algae-risk auto-flag tests.

Covers:
1. Two consecutive `free_chlorine <= 0.5` submissions → `algae_risk_flags`
   entry appears via GET /api/reports/algae-risk.
2. Mixed (one low, one normal) → no flag.
3. `resolve` clears the flag.
4. `schedule-shock` creates a Shock Treatment job AND resolves the flag.
5. RBAC: customer role can't hit /reports/algae-risk.
"""
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

TENANT_HINT = "aquaterra"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def cust_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


# ─── Direct-DB helpers so we don't have to rig up a full submit pipeline ─
from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402
from routers.reports import evaluate_algae_risk  # noqa: E402


def _mk_customer(tenant_id: str, name="Algae Risk Test"):
    cid = new_id()
    doc = {"id": cid, "tenant_id": tenant_id, "name": name,
           "address": "123 Test Ln", "email": None, "phone": None,
           "is_active": True, "created_at": now_iso()}
    return doc, cid


def _mk_report(tenant_id: str, job_id: str, cl_ppm: float, submitted_at: str):
    return {"id": new_id(), "tenant_id": tenant_id, "job_id": job_id,
             "tech_id": "test-tech", "submitted_at": submitted_at,
             "chemical_readings": [
                 {"key": "free_chlorine", "name": "Free Chlorine",
                  "unit": "ppm", "value": cl_ppm},
             ]}


import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_two_low_chlorine_reports_flag():
    """Two consecutive submissions with FC ≤ 0.5 must write a flag."""
    async def _body():
        admin = await db.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
        assert admin, "admin seed missing"
        tenant_id = admin["tenant_id"]

        cust, cid = _mk_customer(tenant_id)
        await db.customers.insert_one(cust)
        try:
            job1_id, job2_id = new_id(), new_id()
            await db.jobs.insert_many([
                {"id": job1_id, "tenant_id": tenant_id, "customer_id": cid,
                 "template": "pool", "service_type": "Pool Cleaning",
                 "status": "completed", "created_at": now_iso()},
                {"id": job2_id, "tenant_id": tenant_id, "customer_id": cid,
                 "template": "pool", "service_type": "Pool Cleaning",
                 "status": "completed", "created_at": now_iso()},
            ])
            await db.service_reports.insert_many([
                _mk_report(tenant_id, job1_id, 0.5, "2026-02-01T10:00:00Z"),
                _mk_report(tenant_id, job2_id, 0.2, "2026-02-08T10:00:00Z"),
            ])
            await db.algae_risk_flags.delete_many(
                {"tenant_id": tenant_id, "customer_id": cid})
            flag_id = await evaluate_algae_risk(tenant_id, cid)
            assert flag_id, "evaluate_algae_risk should have written a flag"
            stored = await db.algae_risk_flags.find_one(
                {"tenant_id": tenant_id, "customer_id": cid,
                 "resolved": False}, {"_id": 0})
            assert stored is not None
            assert len(stored["evidence"]) == 2
            assert stored["evidence"][0]["free_chlorine"] <= 0.5
        finally:
            await db.customers.delete_one({"id": cid})
            await db.service_reports.delete_many(
                {"tenant_id": tenant_id,
                 "job_id": {"$in": [job1_id, job2_id]}})
            await db.jobs.delete_many({"id": {"$in": [job1_id, job2_id]}})
            await db.algae_risk_flags.delete_many(
                {"tenant_id": tenant_id, "customer_id": cid})
    _run(_body())


def test_mixed_no_flag():
    """One low + one normal → no flag."""
    async def _body():
        admin = await db.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
        tenant_id = admin["tenant_id"]
        cust, cid = _mk_customer(tenant_id, name="Mixed Test")
        await db.customers.insert_one(cust)
        try:
            j1, j2 = new_id(), new_id()
            await db.jobs.insert_many([
                {"id": j1, "tenant_id": tenant_id, "customer_id": cid,
                 "template": "pool", "status": "completed"},
                {"id": j2, "tenant_id": tenant_id, "customer_id": cid,
                 "template": "pool", "status": "completed"},
            ])
            await db.service_reports.insert_many([
                _mk_report(tenant_id, j1, 0.1, "2026-02-01T10:00:00Z"),
                _mk_report(tenant_id, j2, 2.5, "2026-02-08T10:00:00Z"),
            ])
            await db.algae_risk_flags.delete_many(
                {"tenant_id": tenant_id, "customer_id": cid})
            flag_id = await evaluate_algae_risk(tenant_id, cid)
            assert flag_id is None
            assert await db.algae_risk_flags.find_one(
                {"tenant_id": tenant_id, "customer_id": cid}) is None
        finally:
            await db.customers.delete_one({"id": cid})
            await db.service_reports.delete_many(
                {"tenant_id": tenant_id,
                 "job_id": {"$in": [j1, j2]}})
            await db.jobs.delete_many({"id": {"$in": [j1, j2]}})
    _run(_body())


def test_rbac_customer_denied(cust_h):
    r = requests.get(f"{API}/reports/algae-risk", headers=cust_h, timeout=10)
    assert r.status_code == 403, r.text


def test_list_and_resolve_and_shock(admin_h):
    """End-to-end: seed a flag → GET lists it → dismiss removes it →
    seed again → schedule-shock creates a job and resolves."""
    # First, admin's tenant.
    me = requests.get(f"{API}/auth/me", headers=admin_h, timeout=10).json()
    tenant_id = me["tenant_id"]

    # Fixture: create customer + jobs + 2 low reports.
    cid = new_id()
    j1, j2 = new_id(), new_id()
    now = now_iso()
    seed_docs = {
        "customers": [
            {"id": cid, "tenant_id": tenant_id, "name": "Algae API Test",
             "address": "555 Chemical Ct", "is_active": True,
             "created_at": now, "updated_at": now},
        ],
        "jobs": [
            {"id": j1, "tenant_id": tenant_id, "customer_id": cid,
             "template": "pool", "status": "completed"},
            {"id": j2, "tenant_id": tenant_id, "customer_id": cid,
             "template": "pool", "status": "completed"},
        ],
        "service_reports": [
            {"id": new_id(), "tenant_id": tenant_id, "job_id": j1,
             "submitted_at": "2026-02-01T10:00:00Z",
             "chemical_readings": [{"key": "free_chlorine", "value": 0.3}]},
            {"id": new_id(), "tenant_id": tenant_id, "job_id": j2,
             "submitted_at": "2026-02-08T10:00:00Z",
             "chemical_readings": [{"key": "free_chlorine", "value": 0.5}]},
        ],
        "algae_risk_flags": [
            {"id": new_id(), "tenant_id": tenant_id, "customer_id": cid,
             "resolved": False, "flagged_at": now, "updated_at": now,
             "evidence": [
                 {"report_id": None, "free_chlorine": 0.3,
                  "date": "2026-02-01T10:00:00Z"},
                 {"report_id": None, "free_chlorine": 0.5,
                  "date": "2026-02-08T10:00:00Z"}],
             "resolved_at": None, "resolved_by": None,
             "resolution_kind": None},
        ],
    }

    # Insert via direct API for asyncio-friendly test order.
    import asyncio
    async def _seed():
        for coll, rows in seed_docs.items():
            if rows:
                await db[coll].insert_many(rows)
    asyncio.get_event_loop().run_until_complete(_seed())

    try:
        # 1. GET lists the row.
        r = requests.get(f"{API}/reports/algae-risk", headers=admin_h, timeout=10).json()
        cust_ids = {row["customer_id"] for row in r["items"]}
        assert cid in cust_ids, f"missing seeded customer_id={cid} in {cust_ids}"

        # 2. Dismiss → 200 + flag resolved.
        r = requests.post(f"{API}/reports/algae-risk/{cid}/resolve",
                          headers=admin_h, timeout=10)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # A second dismiss now 404s (no open flag).
        r2 = requests.post(f"{API}/reports/algae-risk/{cid}/resolve",
                           headers=admin_h, timeout=10)
        assert r2.status_code == 404

        # 3. Re-flag then schedule-shock.
        async def _reflag():
            await db.algae_risk_flags.insert_one({
                "id": new_id(), "tenant_id": tenant_id,
                "customer_id": cid, "resolved": False,
                "flagged_at": now, "updated_at": now,
                "evidence": [], "resolved_at": None,
                "resolved_by": None, "resolution_kind": None,
            })
        asyncio.get_event_loop().run_until_complete(_reflag())
        r = requests.post(f"{API}/reports/algae-risk/{cid}/schedule-shock",
                          headers=admin_h, timeout=10)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload.get("job_id"), payload
        # Job should exist and be a Shock Treatment.
        job = requests.get(f"{API}/jobs/{payload['job_id']}",
                            headers=admin_h, timeout=10).json()
        assert (job.get("service_type") or "").lower().startswith("shock")
        # Flag should be resolved with resolution_kind="scheduled_shock".
        async def _flag_row():
            return await db.algae_risk_flags.find_one(
                {"tenant_id": tenant_id, "customer_id": cid,
                 "resolution_kind": "scheduled_shock"}, {"_id": 0})
        flag = asyncio.get_event_loop().run_until_complete(_flag_row())
        assert flag and flag.get("resolved") is True

        # Cleanup that job so it doesn't clutter schedule.
        requests.delete(f"{API}/jobs/{payload['job_id']}",
                         headers=admin_h, timeout=10)
    finally:
        async def _cleanup():
            await db.customers.delete_one({"id": cid})
            await db.jobs.delete_many({"customer_id": cid})
            await db.service_reports.delete_many({"tenant_id": tenant_id,
                                                    "job_id": {"$in": [j1, j2]}})
            await db.algae_risk_flags.delete_many({"customer_id": cid})
        asyncio.get_event_loop().run_until_complete(_cleanup())
