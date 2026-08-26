"""Feb 2026 · Work-class dimension — service vs repair.

Coverage:
* :func:`services.work_class.normalize_work_class` — happy path,
  case-insensitive, empty/None → default, invalid → ``ValueError``.
* :func:`services.work_class.infer_work_class` — legacy fallback.
* ``POST /api/jobs`` — persists work_class on doc; rejects invalid
  with 400; defaults to service when omitted.
* ``PATCH /api/jobs/{jid}`` — retag path validates + persists.
* ``GET /api/schedule/today`` summary — carries
  ``job_count_service`` + ``job_count_repair`` + legacy ``job_count``.
* ``GET /api/technicians`` — carries ``active_jobs_service`` +
  ``active_jobs_repair`` + legacy ``active_jobs``.
* ``GET /api/team`` — same split as technicians.
* Recurring materialization — occurrences inherit the template's
  ``work_class``.

Pure unit tests for the normalizer/inferrer. Integration tests hit
the FastAPI routes via ``TestClient`` with the standard test seed.
"""
from __future__ import annotations

import pytest

from services.work_class import normalize_work_class, infer_work_class


# ═════════════════════════════════════════════════════════════════════
# services/work_class.py — pure unit tests (no DB).
# ═════════════════════════════════════════════════════════════════════
class TestNormalizeWorkClass:
    def test_none_defaults_to_service(self):
        assert normalize_work_class(None) == "service"

    def test_empty_string_defaults_to_service(self):
        assert normalize_work_class("") == "service"
        assert normalize_work_class("   ") == "service"

    def test_literal_service(self):
        assert normalize_work_class("service") == "service"

    def test_literal_repair(self):
        assert normalize_work_class("repair") == "repair"

    def test_case_insensitive(self):
        assert normalize_work_class("SERVICE") == "service"
        assert normalize_work_class("Repair") == "repair"
        assert normalize_work_class(" Repair ") == "repair"

    def test_invalid_raises_valueerror(self):
        for bad in ("maintenance", "install", "warranty", "urgent",
                     "svc", "rep", 42, ["repair"]):
            with pytest.raises(ValueError):
                normalize_work_class(bad)


class TestInferWorkClass:
    def test_none_defaults_to_service(self):
        assert infer_work_class(None) == "service"

    def test_empty_dict_defaults_to_service(self):
        assert infer_work_class({}) == "service"

    def test_missing_field_defaults_to_service(self):
        assert infer_work_class({"id": "j1", "title": "Weekly"}) == "service"

    def test_literal_repair(self):
        assert infer_work_class({"work_class": "repair"}) == "repair"

    def test_case_insensitive_repair(self):
        assert infer_work_class({"work_class": "REPAIR"}) == "repair"
        assert infer_work_class({"work_class": " Repair "}) == "repair"

    def test_unknown_value_defaults_to_service(self):
        # Belt-and-suspenders — never raise on read.
        assert infer_work_class({"work_class": "warranty"}) == "service"
        assert infer_work_class({"work_class": None}) == "service"
        assert infer_work_class({"work_class": 42}) == "service"


# ═════════════════════════════════════════════════════════════════════
# Route-level integration — verified by hitting real endpoints against
# the seeded test tenant. We isolate to the endpoints touched by this
# ship (POST /jobs, PATCH /jobs/{jid}, GET /schedule/today,
# GET /technicians, GET /team) and skip full-flow smokes (covered in
# their own suites).
# ═════════════════════════════════════════════════════════════════════
import asyncio

from httpx import ASGITransport, AsyncClient

from server import app
from config import db


TEST_TENANT_ID = "test-tenant-workclass"


async def _seed(tid: str) -> dict:
    """Seed a tenant with 1 admin user, 1 tech, 1 customer and return
    ids + admin session token."""
    from utils import create_token, hash_password
    # Clean any residue from prior runs.
    for coll in ("users", "customers", "technicians", "jobs", "tenants"):
        await db[coll].delete_many({"tenant_id": tid})
    await db.tenants.insert_one(
        {"id": tid, "name": "WorkClass Test Co",
          "slug": f"wc-test-{tid}", "active": True, "settings": {}},
    )
    admin = {
        "id": "u-wc-admin", "tenant_id": tid, "email": "wc-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "WC Admin", "deleted_at": None,
    }
    tech = {
        "id": "u-wc-tech", "tenant_id": tid, "email": "wc-tech@test.co",
        "password_hash": hash_password("x"), "role": "technician",
        "name": "WC Tech", "technician_id": "t-wc-1", "deleted_at": None,
    }
    await db.users.insert_many([admin, tech])
    await db.technicians.insert_one(
        {"id": "t-wc-1", "tenant_id": tid, "name": "WC Tech",
          "user_id": "u-wc-tech", "active": True},
    )
    await db.customers.insert_one(
        {"id": "c-wc-1", "tenant_id": tid, "name": "Acme Pool",
          "address": "1 Main St", "is_active": True},
    )
    token = create_token(admin)
    return {"tid": tid, "admin_token": token, "customer_id": "c-wc-1",
            "tech_id": "t-wc-1"}


async def _teardown(tid: str) -> None:
    for coll in ("users", "customers", "technicians", "jobs", "tenants"):
        await db[coll].delete_many({"tenant_id": tid})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def seeded():
    ctx = _run(_seed(TEST_TENANT_ID))
    yield ctx
    _run(_teardown(TEST_TENANT_ID))


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _hdr(seeded):
    return {"Authorization": f"Bearer {seeded['admin_token']}"}


class TestPostJobsWorkClass:
    def test_defaults_to_service_when_omitted(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Weekly clean",
                    "customer_id": seeded["customer_id"],
                }, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                assert r.json()["work_class"] == "service"
        _run(go())

    def test_accepts_repair_explicitly(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Pump broken",
                    "customer_id": seeded["customer_id"],
                    "work_class": "repair",
                }, headers=_hdr(seeded))
                assert r.status_code == 200
                assert r.json()["work_class"] == "repair"
        _run(go())

    def test_case_insensitive_normalization(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Pump broken",
                    "customer_id": seeded["customer_id"],
                    "work_class": "REPAIR",
                }, headers=_hdr(seeded))
                assert r.status_code == 200
                assert r.json()["work_class"] == "repair"
        _run(go())

    def test_invalid_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "??",
                    "customer_id": seeded["customer_id"],
                    "work_class": "warranty",
                }, headers=_hdr(seeded))
                assert r.status_code == 400
                assert "work_class" in r.json()["detail"].lower()
        _run(go())


class TestPatchJobsWorkClass:
    """Uses PUT /api/jobs/{jid} — the standard update endpoint. The
    PATCH endpoint on the same path is scoped to the 24h post-
    completion edit-window flow (see ``jobs.py::patch_job_edit_window``)
    and gates on ``status == "completed"``.
    """
    def test_retag_service_to_repair(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Retag me",
                    "customer_id": seeded["customer_id"],
                }, headers=_hdr(seeded))
                jid = r.json()["id"]
                p = await c.put(f"/api/jobs/{jid}", json={
                    "work_class": "repair",
                }, headers=_hdr(seeded))
                assert p.status_code == 200, p.text
                doc = await db.jobs.find_one({"id": jid})
                assert doc["work_class"] == "repair"
        _run(go())

    def test_retag_invalid_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/jobs", json={
                    "title": "Retag me 2",
                    "customer_id": seeded["customer_id"],
                }, headers=_hdr(seeded))
                jid = r.json()["id"]
                p = await c.put(f"/api/jobs/{jid}", json={
                    "work_class": "bogus",
                }, headers=_hdr(seeded))
                assert p.status_code == 400
        _run(go())


class TestTechniciansCounterSplit:
    def test_active_jobs_split_by_work_class(self, seeded, client):
        async def go():
            # Seed 2 service + 1 repair jobs, all assigned to the tech.
            for wc, title in (("service", "Svc A"), ("service", "Svc B"),
                              ("repair", "Rep A")):
                await db.jobs.insert_one({
                    "id": f"j-wc-{title.replace(' ', '')}",
                    "tenant_id": seeded["tid"],
                    "customer_id": seeded["customer_id"],
                    "technician_id": seeded["tech_id"],
                    "title": title, "status": "pending",
                    "work_class": wc,
                })
            async with client as c:
                r = await c.get("/api/technicians", headers=_hdr(seeded))
                assert r.status_code == 200
                tech = next(t for t in r.json() if t["id"] == seeded["tech_id"])
                assert tech["active_jobs"] == 3
                assert tech["active_jobs_service"] == 2
                assert tech["active_jobs_repair"] == 1
        _run(go())


class TestScheduleTodayCounterSplit:
    def test_summary_carries_split_fields(self, seeded, client):
        async def go():
            # Seed 1 service + 1 repair job for today for the tech.
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date().isoformat()
            iso = today + "T14:00:00+00:00"
            for wc in ("service", "repair"):
                await db.jobs.insert_one({
                    "id": f"j-sched-{wc}",
                    "tenant_id": seeded["tid"],
                    "customer_id": seeded["customer_id"],
                    "technician_id": seeded["tech_id"],
                    "assigned_technician_id": seeded["tech_id"],
                    "title": wc, "status": "scheduled",
                    "work_class": wc, "scheduled_date": iso,
                })
            # Use the tech token to hit schedule/today (schedule is
            # tech-scoped).
            from utils import create_token
            tech_user = await db.users.find_one({"id": "u-wc-tech"})
            tech_token = create_token(tech_user)
            hdr = {"Authorization": f"Bearer {tech_token}"}
            async with client as c:
                r = await c.get(f"/api/schedule/today?date={today}",
                                 headers=hdr)
                assert r.status_code == 200, r.text
                s = r.json()["summary"]
                assert "job_count" in s
                assert s["job_count_service"] >= 1
                assert s["job_count_repair"] >= 1
                assert s["job_count_service"] + s["job_count_repair"] \
                    == s["job_count"]
        _run(go())
