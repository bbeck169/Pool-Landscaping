"""Feb-2026 · Repair-mode service report — backend contract.

Covers the ``work_class == "repair"`` branch across the service-
report + jobs endpoints:

* GET  /jobs/{jid}/service-report bootstraps a report whose
  ``work_class`` inherits from the parent job.
* PATCH accepts + normalizes ``work_class`` (rejects invalid values).
* POST /jobs/{jid}/service-report/submit skips the chemistry gate
  when the report is tagged repair (no missing-readings 400).
* PUT  /jobs/{jid} status → completed skips the chemistry gate
  when the job is tagged repair.
* Portal-side redaction still strips ``internal_notes`` (regression
  guard for the customer-portal safety contract).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from utils import create_token, hash_password


TID = "test-tenant-repair-log"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed() -> dict:
    for coll in ("users", "customers", "properties", "jobs",
                  "tenants", "service_reports", "technicians"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.delete_many({"id": TID})
    await db.tenants.insert_one({
        "id": TID, "name": "Repair Log Tenant",
        "slug": "rl-test", "active": True, "settings": {},
    })
    admin = {
        "id": "u-rl-admin", "tenant_id": TID,
        "email": "rl-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "RL Admin", "deleted_at": None,
    }
    tech = {
        "id": "u-rl-tech", "tenant_id": TID,
        "email": "rl-tech@test.co",
        "password_hash": hash_password("x"), "role": "technician",
        "name": "RL Tech", "technician_id": "tech-rl",
        "deleted_at": None,
    }
    await db.users.insert_many([admin, tech])
    await db.technicians.insert_one({
        "id": "tech-rl", "tenant_id": TID, "name": "RL Tech",
    })
    await db.customers.insert_one({
        "id": "c-rl", "tenant_id": TID, "name": "Repair Customer",
        "is_active": True,
    })
    # Two jobs — one repair, one standard service.
    await db.jobs.insert_many([
        {"id": "j-repair", "tenant_id": TID, "customer_id": "c-rl",
          "title": "Broken pump", "work_class": "repair",
          "service_type": "Pool Repair", "job_type": "pool",
          "status": "scheduled", "technician_id": "tech-rl"},
        {"id": "j-service", "tenant_id": TID, "customer_id": "c-rl",
          "title": "Weekly", "work_class": "service",
          "service_type": "Pool Cleaning", "job_type": "pool",
          "status": "scheduled", "technician_id": "tech-rl"},
    ])
    return {
        "admin_token": create_token(admin),
        "tech_token": create_token(tech),
    }


async def _teardown():
    for coll in ("users", "customers", "properties", "jobs",
                  "tenants", "service_reports", "technicians"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.delete_many({"id": TID})


@pytest.fixture(scope="module")
def seeded():
    ctx = _run(_seed())
    yield ctx
    _run(_teardown())


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app),
                        base_url="http://test")


def _hdr(seeded, who="admin_token"):
    return {"Authorization": f"Bearer {seeded[who]}"}


class TestRepairModeReportBootstrap:
    def test_bootstrap_inherits_work_class_from_repair_job(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/jobs/j-repair/service-report",
                                    headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                rep = r.json()
                assert rep.get("work_class") == "repair"
        _run(go())

    def test_bootstrap_inherits_work_class_from_service_job(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/jobs/j-service/service-report",
                                    headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                rep = r.json()
                assert rep.get("work_class") == "service"
        _run(go())


class TestRepairModePatch:
    def test_patch_normalizes_work_class(self, seeded, client):
        async def go():
            async with client as c:
                # Bootstrap first.
                await c.get("/api/jobs/j-repair/service-report",
                              headers=_hdr(seeded))
                # Case-insensitive normalize.
                r = await c.patch(
                    "/api/jobs/j-repair/service-report",
                    json={"work_class": "REPAIR",
                            "internal_notes": "wrench in gear",
                            "customer_notes": "fixed the pump"},
                    headers=_hdr(seeded),
                )
                assert r.status_code == 200, r.text
                doc = await db.service_reports.find_one(
                    {"tenant_id": TID, "job_id": "j-repair"},
                    {"_id": 0},
                )
                assert doc["work_class"] == "repair"
                assert doc["internal_notes"] == "wrench in gear"
                assert doc["customer_notes"] == "fixed the pump"
        _run(go())

    def test_patch_rejects_invalid_work_class(self, seeded, client):
        async def go():
            async with client as c:
                await c.get("/api/jobs/j-repair/service-report",
                              headers=_hdr(seeded))
                r = await c.patch(
                    "/api/jobs/j-repair/service-report",
                    json={"work_class": "not-a-real-value"},
                    headers=_hdr(seeded),
                )
                assert r.status_code == 400
        _run(go())


class TestRepairModeSubmitSkipsChemistryGate:
    def test_submit_repair_report_without_readings_succeeds(self, seeded, client):
        """A repair report with no chemistry readings must submit
        cleanly. Prior behavior blocked pool-typed submits at the
        gate; the repair branch now bypasses."""
        async def go():
            async with client as c:
                # Bootstrap. On repair jobs the doc has
                # ``work_class == "repair"`` from the fixture.
                await c.get("/api/jobs/j-repair/service-report",
                              headers=_hdr(seeded))
                # Zero chemistry readings — normally would 400 for a
                # pool-typed job.
                r = await c.post(
                    "/api/jobs/j-repair/service-report/submit",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 200, r.text
                doc = await db.service_reports.find_one(
                    {"tenant_id": TID, "job_id": "j-repair"},
                    {"_id": 0},
                )
                assert doc.get("submitted_at") is not None
        _run(go())

    def test_submit_service_report_still_requires_chemistry(self, seeded, client):
        """Regression guard — the pool-mode gate must STILL fire on a
        normal service report. Bypass is scoped to repair only.
        """
        async def go():
            async with client as c:
                await c.get("/api/jobs/j-service/service-report",
                              headers=_hdr(seeded))
                r = await c.post(
                    "/api/jobs/j-service/service-report/submit",
                    headers=_hdr(seeded),
                )
                # 422 = chemistry_core_readings_missing (existing gate
                # semantics; kept for regression coverage).
                assert r.status_code in (400, 422)
                assert ("chemistry" in r.text.lower()
                        or "reading" in r.text.lower())
        _run(go())


class TestRepairModeCompleteJobSkipsChemistryGate:
    def test_put_completed_on_repair_skips_gate(self, seeded, client):
        """A ``PUT /jobs/{id}`` status→completed on a repair job must
        NOT hit the readings-missing 400."""
        async def go():
            async with client as c:
                # Reset status to scheduled so we exercise the
                # transition.
                await db.jobs.update_one(
                    {"id": "j-repair", "tenant_id": TID},
                    {"$set": {"status": "scheduled"}},
                )
                r = await c.put("/api/jobs/j-repair",
                                    json={"status": "completed"},
                                    headers=_hdr(seeded))
                assert r.status_code == 200, r.text
        _run(go())


class TestPortalRedactionUnchanged:
    def test_internal_notes_still_stripped_for_customer(self):
        """Regression guard on ``_redact_report_for_customer`` — the
        function must never leak ``internal_notes``, repair-mode or
        otherwise. Direct unit-level assertion (no HTTP round-trip)."""
        from routers.service_reports import _redact_report_for_customer
        sr = {
            "id": "sr-x", "work_class": "repair",
            "internal_notes": "SECRET — customer must not see this",
            "customer_notes": "All fixed, thanks.",
            "photos": [], "videos": [],
        }
        redacted = _redact_report_for_customer(sr)
        assert "internal_notes" not in redacted
        # Customer-safe fields survive.
        assert redacted.get("customer_notes") == "All fixed, thanks."
        assert redacted.get("work_class") == "repair"
