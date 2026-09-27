"""Feb-2026 · Pool Service PS-A — post-submit tech-edit tests.

Guards the PS-A relaxation of the "already submitted" 409 gate in
``routers/service_reports.py::patch_service_report``:

    * Techs assigned to a job may PATCH their OWN submitted report;
      every field write lands an ``audit_logs`` row with event
      ``service_report_post_submit_edit``.
    * Admins / super_admins retain the pre-PS-A behaviour — 409 on
      post-submit PATCH (documented as "retain existing edit path").
    * Techs NOT assigned to the job (or cross-tenant) still get 403
      via ``_authorize_report``.
    * Admin-only ``GET /api/service-reports/{id}/audit`` surfaces
      the audit rows; techs get 403.

Uses the live-HTTP + seeded-tenant pattern from
``tests/test_service_report.py``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_user():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def admin_h(admin_user):
    return {"Authorization": f"Bearer {admin_user['access_token']}"}


@pytest.fixture(scope="module")
def tech_user():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tech_h(tech_user):
    return {"Authorization": f"Bearer {tech_user['access_token']}"}


@pytest.fixture(scope="module")
def tech2_user():
    return _login("carlos@aquaterra.com")


@pytest.fixture(scope="module")
def tech2_h(tech2_user):
    return {"Authorization": f"Bearer {tech2_user['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    """Cross-tenant fixture — matches the graceful-skip pattern in
    tests/test_service_report.py (the sunbelt tenant isn't always
    seeded in a fresh pod)."""
    try:
        return {"Authorization": f"Bearer "
                                    f"{_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin seeded in this environment")


def _make_job(dbc, tech_id: str, tenant_slug: str = "aquaterra") -> str:
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    assert tenant, f"tenant {tenant_slug} missing"
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant["id"],
        "customer_id": None,
        "customer_name": "TEST_ ps-a cust",
        "title": "PS-A test job",
        "service_type": "Weekly Pool Service",
        "job_type": "Weekly Pool Service",
        "status": "scheduled",
        "technician_id": tech_id,
        "photos": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup_job(dbc, jid: str):
    """Purge job + report + PS-A audit trail so tests don't
    accumulate rows in the shared demo DB."""
    dbc.jobs.delete_one({"id": jid})
    reports = list(dbc.service_reports.find(
        {"job_id": jid}, {"_id": 0, "id": 1},
    ))
    report_ids = [r["id"] for r in reports if r.get("id")]
    dbc.service_reports.delete_many({"job_id": jid})
    if report_ids:
        dbc.audit_logs.delete_many({
            "event": "service_report_post_submit_edit",
            "payload.report_id": {"$in": report_ids},
        })


def _bootstrap_and_submit(dbc, tech_h, jid: str) -> str:
    """GET the report to bootstrap, seed a chemical reading, then
    POST /submit.  Returns the ``report_id``."""
    r = requests.get(f"{API}/jobs/{jid}/service-report",
                        headers=tech_h, timeout=20)
    assert r.status_code == 200, r.text
    rep = r.json()

    # Seed minimum-viable checklist so submit doesn't 4xx on a
    # tenant with strict submit gating.  Pool jobs require the
    # full core chemistry set (pH + chlorine + alkalinity + CYA)
    # per ``chemistry_core_readings_missing`` gate — supply all
    # four so submit lands cleanly.
    r = requests.patch(f"{API}/jobs/{jid}/service-report", headers=tech_h, json={
        "chemical_readings": [
            {"name": "pH", "value": 7.4, "unit": "", "ts": None},
            {"name": "Chlorine", "value": 3.0, "unit": "ppm", "ts": None},
            {"name": "Alkalinity", "value": 100, "unit": "ppm", "ts": None},
            {"name": "CYA", "value": 40, "unit": "ppm", "ts": None},
        ],
        "checklist_items": [{"id": "brush", "label": "Brush walls",
                              "done": True}],
        "notes": "pre-submit note",
    }, timeout=20)
    assert r.status_code == 200, r.text

    r = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers=tech_h, timeout=30,
    )
    assert r.status_code == 200, r.text
    return rep["id"]


# ═══════════════════════════════════════════════════════════════════
# (a) admin PATCH pre-submit still works (regression).
# ═══════════════════════════════════════════════════════════════════
def test_admin_patch_pre_submit_still_works(admin_h, tech_h,
                                                  tech_user, dbc):
    tid = (tech_user["user"].get("technician_id")
              or tech_user["user"]["id"])
    jid = _make_job(dbc, tid)
    try:
        # Bootstrap under tech scope so the report row is keyed to
        # the tech (matches routers/service_reports._authorize_report).
        requests.get(f"{API}/jobs/{jid}/service-report",
                        headers=tech_h, timeout=20)
        # Admin PATCH pre-submit — the admin path uses the job's
        # technician_id to scope the row, so this is a regression
        # check that admin can still edit an in-flight report.
        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=admin_h,
                              json={"notes": "admin pre-submit note"},
                              timeout=20)
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "admin pre-submit note"
    finally:
        _cleanup_job(dbc, jid)


# ═══════════════════════════════════════════════════════════════════
# (b) Tech PATCH on assigned + submitted report → 200 + audit row.
# ═══════════════════════════════════════════════════════════════════
def test_tech_can_patch_own_submitted_report_and_writes_audit(
    tech_h, tech_user, dbc,
):
    tid = (tech_user["user"].get("technician_id")
              or tech_user["user"]["id"])
    jid = _make_job(dbc, tid)
    try:
        report_id = _bootstrap_and_submit(dbc, tech_h, jid)

        # Confirm the row is genuinely submitted.
        row = dbc.service_reports.find_one({"id": report_id})
        assert row and row.get("submitted_at"), (
            "test setup failed — report not marked submitted"
        )

        # Post-submit PATCH by the assigned tech — must succeed
        # under PS-A (previously 409).
        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=tech_h,
                              json={"notes": "corrected chemistry note",
                                      "internal_notes": "adjusted post-submit"},
                              timeout=20)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["notes"] == "corrected chemistry note"
        assert got["internal_notes"] == "adjusted post-submit"

        # Audit row landed with the right shape.
        audits = list(dbc.audit_logs.find({
            "event": "service_report_post_submit_edit",
            "payload.report_id": report_id,
        }))
        assert len(audits) == 1, (
            "exactly one audit row expected per post-submit save"
        )
        a = audits[0]
        assert a["actor_id"] == tech_user["user"]["id"]
        assert a["actor_role"] == "technician"
        # Field diff captures both fields changed.
        diffs = a["payload"]["field_diffs"]
        assert "notes" in diffs
        assert diffs["notes"]["old"] == "pre-submit note"
        assert diffs["notes"]["new"] == "corrected chemistry note"
        assert "internal_notes" in diffs
    finally:
        _cleanup_job(dbc, jid)


# ═══════════════════════════════════════════════════════════════════
# (c) Tech PATCH on UNASSIGNED submitted report → 403 (already
# handled by _authorize_report, but PS-A must not regress this).
# ═══════════════════════════════════════════════════════════════════
def test_unassigned_tech_cannot_patch_someone_elses_submitted_report(
    tech_h, tech2_h, tech_user, dbc,
):
    # Job assigned to mike; carlos (tech2) tries to PATCH it.
    mike_tid = (tech_user["user"].get("technician_id")
                    or tech_user["user"]["id"])
    jid = _make_job(dbc, mike_tid)
    try:
        _bootstrap_and_submit(dbc, tech_h, jid)

        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=tech2_h,
                              json={"notes": "not my job"},
                              timeout=20)
        assert r.status_code == 403, r.text
    finally:
        _cleanup_job(dbc, jid)


# ═══════════════════════════════════════════════════════════════════
# (d) Admin post-submit PATCH still 409 (retain existing edit path).
# ═══════════════════════════════════════════════════════════════════
def test_admin_post_submit_patch_still_locked(admin_h, tech_h,
                                                     tech_user, dbc):
    tid = (tech_user["user"].get("technician_id")
              or tech_user["user"]["id"])
    jid = _make_job(dbc, tid)
    try:
        _bootstrap_and_submit(dbc, tech_h, jid)

        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=admin_h,
                              json={"notes": "admin post-submit"},
                              timeout=20)
        assert r.status_code == 409, r.text
    finally:
        _cleanup_job(dbc, jid)


# ═══════════════════════════════════════════════════════════════════
# (e) Cross-tenant tech attempt → 403.  A sunbelt admin's job on
# aquaterra tenant is unreachable via the tenant filter — falls
# through to the 404 "Job not found" branch which is the intended
# defence.  We assert the endpoint refuses (not 200).
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_tech_cannot_patch(sunbelt_admin_h, tech_h,
                                                tech_user, dbc):
    tid = (tech_user["user"].get("technician_id")
              or tech_user["user"]["id"])
    jid = _make_job(dbc, tid)
    try:
        _bootstrap_and_submit(dbc, tech_h, jid)

        # Sunbelt admin (different tenant) tries to PATCH an
        # aquaterra job.  The tenant filter drops the job into the
        # 404 branch.
        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=sunbelt_admin_h,
                              json={"notes": "cross-tenant"},
                              timeout=20)
        assert r.status_code == 404, r.text
    finally:
        _cleanup_job(dbc, jid)


# ═══════════════════════════════════════════════════════════════════
# (f) GET /api/service-reports/{id}/audit — admin-only.
# ═══════════════════════════════════════════════════════════════════
def test_audit_endpoint_admin_only(admin_h, tech_h, tech_user, dbc):
    tid = (tech_user["user"].get("technician_id")
              or tech_user["user"]["id"])
    jid = _make_job(dbc, tid)
    try:
        report_id = _bootstrap_and_submit(dbc, tech_h, jid)
        # Land one post-submit edit so the audit collection has a row.
        r = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=tech_h,
                              json={"notes": "audit-endpoint seed"},
                              timeout=20)
        assert r.status_code == 200, r.text

        # Admin — 200 + at least one row.
        r_admin = requests.get(
            f"{API}/service-reports/{report_id}/audit",
            headers=admin_h, timeout=20,
        )
        assert r_admin.status_code == 200, r_admin.text
        body = r_admin.json()
        assert body["total"] >= 1
        assert any(
            row["event"] == "service_report_post_submit_edit"
            for row in body["items"]
        )

        # Technician — 403.
        r_tech = requests.get(
            f"{API}/service-reports/{report_id}/audit",
            headers=tech_h, timeout=20,
        )
        assert r_tech.status_code == 403, r_tech.text
        assert r_tech.json()["detail"] == "admin_only"
    finally:
        _cleanup_job(dbc, jid)
