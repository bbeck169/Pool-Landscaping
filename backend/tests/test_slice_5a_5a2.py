"""Phase 5A + 5A.2 · Backend regression tests.

Coverage
========
Phase 5A
    * GET /api/checklists/daily — pool tech, landscape tech, admin+query,
      service_line normalisation, invalid values.
    * Field Estimator gate — 403 for technician, 200 for admin.
    * Property Lookup gate  — 403 for technician, 200 for admin.

Phase 5A.2
    * GET /api/workstream/jobs — 200 admin, 403 tech/manager/customer,
      default-completed-only, non-completed status → 400.
    * GET /api/jobs/{jid}/service-log — 200 admin, 403 tech, 404 unknown,
      chemical cost computation (pool), landscape swaps in service notes.
    * POST /api/jobs/{jid}/email-door-hanger — 200 first send, 429 in
      cooldown window, marketing_deliveries row shape verified.

All tests hit the running backend on localhost:8001 (matches other
Feb-2026 suites).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import requests

API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]


def _jwt_secret() -> str:
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return os.environ["JWT_SECRET"]


def _mk_token(user_id: str, role: str, email: str = "u@example.com") -> str:
    return jwt.encode(
        {"sub": user_id, "email": email, "role": role,
         "exp": datetime.now(timezone.utc) + timedelta(hours=2)},
        _jwt_secret(), algorithm="HS256",
    )


def _hdr(tok: str, slug: str) -> dict:
    return {"Authorization": f"Bearer {tok}",
             "X-Tenant-Slug": slug,
             "Content-Type": "application/json"}


# ─── Seed fixture ─────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def env():
    from utils import new_id, now_iso
    tid_pool = f"TEST_pooltech_{uuid.uuid4().hex[:8]}"
    tid_land = f"TEST_landtech_{uuid.uuid4().hex[:8]}"
    tid_admin = f"TEST_admin_{uuid.uuid4().hex[:8]}"
    tid_mgr = f"TEST_mgr_{uuid.uuid4().hex[:8]}"
    tid_cust = f"TEST_cust_{uuid.uuid4().hex[:8]}"

    tenant_id = f"TEST_tenant_{uuid.uuid4().hex[:8]}"
    slug = f"test-5a-{uuid.uuid4().hex[:6]}"

    prop_id = f"TEST_prop_{uuid.uuid4().hex[:8]}"
    cust_id = f"TEST_custid_{uuid.uuid4().hex[:8]}"
    tech_pool_id = f"TEST_techdb_{uuid.uuid4().hex[:8]}"

    # Pool completed job (with chemistry + chemicals).
    pool_job = f"TEST_jobP_{uuid.uuid4().hex[:8]}"
    land_job = f"TEST_jobL_{uuid.uuid4().hex[:8]}"

    db = _db()

    async def _seed():
        await db.tenants.insert_one({
            "id": tenant_id, "name": "TEST 5A tenant",
            "slug": slug, "active": True,
            "created_at": now_iso(),
        })
        await db.users.insert_many([
            {"id": tid_pool, "email": f"pool_{tid_pool}@ex.com",
             "role": "technician", "department": "pool",
             "tenant_id": tenant_id, "technician_id": tech_pool_id,
             "active": True, "created_at": now_iso()},
            {"id": tid_land, "email": f"land_{tid_land}@ex.com",
             "role": "technician", "department": "landscaping",
             "tenant_id": tenant_id, "active": True, "created_at": now_iso()},
            {"id": tid_admin, "email": f"admin_{tid_admin}@ex.com",
             "role": "admin", "tenant_id": tenant_id,
             "active": True, "created_at": now_iso()},
            {"id": tid_mgr, "email": f"mgr_{tid_mgr}@ex.com",
             "role": "manager", "tenant_id": tenant_id,
             "active": True, "created_at": now_iso()},
            {"id": tid_cust, "email": f"cust_{tid_cust}@ex.com",
             "role": "customer", "tenant_id": tenant_id,
             "customer_id": cust_id, "active": True, "created_at": now_iso()},
        ])
        await db.customers.insert_one({
            "id": cust_id, "tenant_id": tenant_id,
            "name": "TEST Homeowner",
            "email": f"custmail_{cust_id}@ex.com",
            "phone": "+16238878060",
            "created_at": now_iso(),
        })
        await db.properties.insert_one({
            "id": prop_id, "tenant_id": tenant_id,
            "customer_id": cust_id, "label": "Main property",
            "address": {"line1": "1 Palm Ln", "city": "Peoria",
                          "state": "AZ", "postal_code": "85383"},
            "created_at": now_iso(),
        })
        await db.technicians.insert_one({
            "id": tech_pool_id, "tenant_id": tenant_id,
            "name": "Mike Rivera", "department": "pool",
            "phone": "+16238878060", "created_at": now_iso(),
        })
        # Pool completed job with 3 chemicals + full readings.
        await db.jobs.insert_many([
            {
                "id": pool_job, "tenant_id": tenant_id,
                "status": "completed", "customer_id": cust_id,
                "property_id": prop_id, "technician_id": tech_pool_id,
                "customer_name": "TEST Homeowner",
                "service_type": "Pool service",
                "title": "Pool weekly service",
                "scheduled_date": "2026-02-15",
                "started_at": "2026-02-15T18:00:00Z",
                "completed_at": "2026-02-15T18:14:00Z",
                "chemical_readings": {
                    "total_chlorine": 3.0, "free_chlorine": 2.5,
                    "ph": 7.4, "alkalinity": 100, "conditioner": 40,
                },
                "chemicals_added": [
                    {"name": "Chlorine Tablets", "quantity": 2, "unit": ""},
                    {"name": "Liquid Chlorine", "quantity": 1, "unit": "Gallon"},
                    {"name": "Liquid Acid", "quantity": 1, "unit": "Gallon"},
                ],
                "checklist": [
                    {"key": "skimmed_pool", "label": "Skimmed Pool", "done": True},
                    {"key": "brush_pool", "label": "Brush Pool", "done": True},
                    {"key": "tested_chemicals", "label": "Tested Chemicals", "done": True},
                ],
                "created_at": now_iso(),
            },
            {
                "id": land_job, "tenant_id": tenant_id,
                "status": "completed", "customer_id": cust_id,
                "property_id": prop_id, "technician_id": None,
                "customer_name": "TEST Homeowner",
                "service_type": "Landscape service",
                "title": "Landscape weekly",
                "scheduled_date": "2026-02-15",
                "service_notes": "Trimmed roses; irrigation OK.",
                "checklist": [
                    {"key": "mowed_grass", "label": "Mowed Grass", "done": True},
                ],
                "created_at": now_iso(),
            },
            # An in_progress job used for the status-rejection test.
            {"id": f"TEST_ip_{uuid.uuid4().hex[:6]}", "tenant_id": tenant_id,
             "status": "in_progress", "created_at": now_iso()},
        ])
    _run(_seed())

    yield {
        "tenant_id": tenant_id, "slug": slug,
        "pool_tech": tid_pool, "land_tech": tid_land,
        "admin": tid_admin, "manager": tid_mgr, "customer": tid_cust,
        "pool_job": pool_job, "land_job": land_job,
    }

    async def _cleanup():
        await db.tenants.delete_one({"id": tenant_id})
        await db.users.delete_many({"tenant_id": tenant_id})
        await db.customers.delete_many({"tenant_id": tenant_id})
        await db.properties.delete_many({"tenant_id": tenant_id})
        await db.jobs.delete_many({"tenant_id": tenant_id})
        await db.technicians.delete_many({"tenant_id": tenant_id})
        await db.marketing_deliveries.delete_many({"tenant_id": tenant_id})
        await db.service_checklists.delete_many({"tenant_id": tenant_id})
    _run(_cleanup())


# ─── Phase 5A · GET /api/checklists/daily ────────────────────────────
def test_checklist_pool_tech_gets_pool(env):
    tok = _mk_token(env["pool_tech"], "technician")
    r = requests.get(f"{API}/checklists/daily",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "pool"
    labels = [it["label"] for it in j["items"]]
    assert labels == [
        "Skimmed Pool", "Brush Pool", "Checked Skimmer Basket",
        "Checked Pump Basket", "Tested Chemicals", "Checked Equipment",
        "Secured all Gates",
    ]
    assert j["count"] == 7


def test_checklist_landscape_tech_gets_landscape(env):
    tok = _mk_token(env["land_tech"], "technician")
    r = requests.get(f"{API}/checklists/daily",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "landscape"
    labels = [it["label"] for it in j["items"]]
    assert labels == [
        "Sprayed or Pulled Weeds", "Checked Irrigation", "Trimmed Bushes",
        "Mowed Grass", "Edged Grass", "Blow Property", "Raked Rocks",
        "Locked Gate", "Trimmed Trees", "Irrigation Repair",
    ]
    assert j["count"] == 10


def test_checklist_admin_query_landscape(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/checklists/daily?service_line=landscape",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200
    assert r.json()["service_line"] == "landscape"


def test_checklist_normalisation_landscaping_alias(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/checklists/daily?service_line=landscaping",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200
    assert r.json()["service_line"] == "landscape"


def test_checklist_invalid_service_line_400(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/checklists/daily?service_line=garbage",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 400


# ─── Phase 5A · tech gates ────────────────────────────────────────────
def test_field_estimator_denies_technician(env):
    tok = _mk_token(env["pool_tech"], "technician")
    r = requests.get(f"{API}/estimator/rate-catalog",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_field_estimator_allows_admin(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/estimator/rate-catalog",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200


def test_property_lookup_denies_technician(env):
    tok = _mk_token(env["pool_tech"], "technician")
    r = requests.get(f"{API}/property/saved",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_property_lookup_allows_admin(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/property/saved",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200


# ─── Phase 5A.2 · Workstream jobs RBAC + completed-only ──────────────
def test_workstream_jobs_admin_200(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/workstream/jobs",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    for row in j["jobs"]:
        assert row["status"] == "completed"


def test_workstream_jobs_technician_403(env):
    tok = _mk_token(env["pool_tech"], "technician")
    r = requests.get(f"{API}/workstream/jobs",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_workstream_jobs_manager_403(env):
    tok = _mk_token(env["manager"], "manager")
    r = requests.get(f"{API}/workstream/jobs",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_workstream_jobs_customer_403(env):
    tok = _mk_token(env["customer"], "customer")
    r = requests.get(f"{API}/workstream/jobs",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_workstream_jobs_non_completed_status_400(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/workstream/jobs?status=in_progress",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 400
    r2 = requests.get(f"{API}/workstream/jobs?status=all",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r2.status_code == 400


def test_workstream_jobs_completed_status_ok(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/workstream/jobs?status=completed",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200


# ─── Phase 5A.2 · service-log aggregator ─────────────────────────────
def test_service_log_admin_pool(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/jobs/{env['pool_job']}/service-log",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "pool"
    assert j["log_details"]["customer_name"] == "TEST Homeowner"
    # 14 minutes between 18:00 and 18:14.
    assert j["log_details"]["time_spent_minutes"] == 14
    # Chemical cost: 2*1.20 + 1*8.00 + 1*8.00 = 18.40. If the seeded
    # default price map hits, cost_usd == 18.40. Test allows either the
    # tenant override or the default.
    assert j["chemical_cost_usd"] in (18.40, 18.4)
    # Water test rows present in stable order.
    labels = [r["label"] for r in j["water_test"]]
    assert labels == ["Total Chlorine", "Free Chlorine", "Ph Balance",
                        "Alkalinity", "Conditioner"]
    # Checklist has 7 pool items, order preserved.
    items = j["checklist_state"]["items"]
    assert [it["label"] for it in items] == [
        "Skimmed Pool", "Brush Pool", "Checked Skimmer Basket",
        "Checked Pump Basket", "Tested Chemicals", "Checked Equipment",
        "Secured all Gates",
    ]
    completed_flags = {it["label"]: it["completed"] for it in items}
    assert completed_flags["Skimmed Pool"] is True
    assert completed_flags["Tested Chemicals"] is True
    assert completed_flags["Secured all Gates"] is False


def test_service_log_landscape_swaps_notes(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/jobs/{env['land_job']}/service-log",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["service_line"] == "landscape"
    assert j["water_test"] == []
    assert j["chemicals_used"] == []
    assert j["service_notes"] == "Trimmed roses; irrigation OK."


def test_service_log_technician_403(env):
    tok = _mk_token(env["pool_tech"], "technician")
    r = requests.get(f"{API}/jobs/{env['pool_job']}/service-log",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_service_log_manager_403(env):
    # Manager not admin — the door-hanger + service-log endpoints are
    # admin-only per Phase 5A.2. This is stricter than the refund gate.
    tok = _mk_token(env["manager"], "manager")
    r = requests.get(f"{API}/jobs/{env['pool_job']}/service-log",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 403


def test_service_log_missing_job_404(env):
    tok = _mk_token(env["admin"], "admin")
    r = requests.get(f"{API}/jobs/does-not-exist/service-log",
                        headers=_hdr(tok, env["slug"]), timeout=10)
    assert r.status_code == 404


# ─── Phase 5A.2 · door hanger send + cooldown ────────────────────────
def test_email_door_hanger_and_cooldown(env):
    tok = _mk_token(env["admin"], "admin")
    r1 = requests.post(f"{API}/jobs/{env['pool_job']}/email-door-hanger",
                         headers=_hdr(tok, env["slug"]), timeout=15)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["ok"] is True
    assert j1["recipient"].endswith("@ex.com")
    delivery_id = j1["delivery_id"]

    # marketing_deliveries row shape
    async def _check():
        db = _db()
        row = await db.marketing_deliveries.find_one(
            {"id": delivery_id, "tenant_id": env["tenant_id"]},
            {"_id": 0},
        )
        assert row is not None
        assert row["kind"] == "transactional"
        assert row["trigger_entity"]["kind"] == "job_door_hanger"
        assert row["trigger_entity"]["id"] == env["pool_job"]
        assert row["channel"] == "email"
    _run(_check())

    # Second send within cooldown → 429.
    r2 = requests.post(f"{API}/jobs/{env['pool_job']}/email-door-hanger",
                         headers=_hdr(tok, env["slug"]), timeout=15)
    assert r2.status_code == 429
    j2 = r2.json()
    assert j2["reason"] == "cooldown"
    assert j2["last_delivery_id"] == delivery_id


def test_email_door_hanger_customer_no_email_400(env):
    from utils import new_id, now_iso
    db = _db()
    # Seed a job for a customer with no email.
    cust_no_email = f"TEST_noemail_{uuid.uuid4().hex[:6]}"
    job_no_email = f"TEST_jobne_{uuid.uuid4().hex[:6]}"

    async def _seed():
        await db.customers.insert_one({
            "id": cust_no_email, "tenant_id": env["tenant_id"],
            "name": "No Email", "email": "",
            "created_at": now_iso(),
        })
        await db.jobs.insert_one({
            "id": job_no_email, "tenant_id": env["tenant_id"],
            "status": "completed", "customer_id": cust_no_email,
            "created_at": now_iso(),
        })
    _run(_seed())

    tok = _mk_token(env["admin"], "admin")
    r = requests.post(f"{API}/jobs/{job_no_email}/email-door-hanger",
                        headers=_hdr(tok, env["slug"]), timeout=15)
    assert r.status_code == 400

    async def _cleanup():
        await db.customers.delete_one({"id": cust_no_email})
        await db.jobs.delete_one({"id": job_no_email})
    _run(_cleanup())
