"""Feb 2026 · P0 iOS close-job 422 · contract test.

Reproduces the exact scenario that surfaced on ``app.plofv.com``
iOS TestFlight: a POOL job whose service_report is missing the
five canonical chemistry readings.  Submit MUST reject with a
structured HTTP 422 body whose ``detail`` is a DICT (not string,
not array) so the mobile ``api.ts`` handler at
``/app/mobile/src/api.ts`` can unwrap it and render a human-
readable error instead of the generic "Request failed (422)".

Backward-compat contract
------------------------
The mobile client + web client + any 3rd-party integration reads:

* ``detail.detail == "chemistry_core_readings_missing"``  (stable key)
* ``detail.message``                                       (human string)
* ``detail.missing_fields  : list[str]``                   (short kebab)
* ``detail.missing_labels  : list[str]``                   (display case)

Changing the shape without a coordinated mobile release breaks the
close-job UX. This test locks the contract in place.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



BASE = "http://localhost:8001"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = _shared_db() if (_MONGO_URL and _DB_NAME) else None
def _mk_tenant() -> str:
    tid = f"P0_tenant_{uuid.uuid4().hex}"
    _sync.tenants.insert_one({
        "id": tid, "slug": f"p0-{uuid.uuid4().hex[:8]}",
        "name": "P0 Tenant", "active": True,
    })
    return tid


def _mk_user_admin(tid: str) -> str:
    from utils import hash_password
    email = f"p0-adm-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": f"P0_user_{uuid.uuid4().hex}",
        "email": email, "role": "super_admin",
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": "P0 Admin",
        "failed_login_attempts": 0, "active": True,
    })
    return email


def _mk_user_tech(tid: str) -> str:
    """Seed a technician user + return ``(email, user_id)``. The
    user_id doubles as the ``tech_id`` on jobs + service reports so
    ``_authorize_report`` in the submit handler resolves cleanly."""
    from utils import hash_password
    uid = f"P0_tech_{uuid.uuid4().hex}"
    email = f"p0-tech-{uuid.uuid4().hex[:8]}@example.com"
    _sync.users.insert_one({
        "id": uid, "email": email, "role": "technician",
        "password_hash": hash_password("password123"),
        "tenant_id": tid, "name": "P0 Tech",
        "technician_id": uid,
        "failed_login_attempts": 0, "active": True,
    })
    return email, uid


def _token_for(email: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": email, "password": "password123",
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _seed_pool_job(tid: str, tech_id: str) -> str:
    cid = f"cs_{uuid.uuid4().hex}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "P0 Cust",
        "email": "p0c@example.com",
        "service_line": "pool", "is_active": True,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    })
    jid = f"job_{uuid.uuid4().hex}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": cid, "customer_name": "P0 Cust",
        "service_type": "Pool Service", "service_line": "pool",
        "status": "scheduled",
        "assigned_to": tech_id, "technician_id": tech_id,
        "scheduled_date": "2026-02-27",
        "created_at": "2026-02-27T00:00:00+00:00",
    })
    return jid


def _seed_report(tid: str, jid: str, tech_id: str,
                    *, readings: list = None,
                    submitted: bool = False) -> str:
    sr_id = f"sr_{uuid.uuid4().hex}"
    doc = {
        "id": sr_id, "tenant_id": tid, "job_id": jid, "tech_id": tech_id,
        "chemical_readings": readings if readings is not None else [],
        "chemicals_added": [],
        "checklist_items": [
            {"key": "skim_surface", "label": "Skim surface", "checked": True},
        ],
        "notes": "",
        "created_at": "2026-02-27T00:00:00+00:00",
        "updated_at": "2026-02-27T00:00:00+00:00",
    }
    if submitted:
        doc["submitted_at"] = "2026-02-27T01:00:00+00:00"
    _sync.service_reports.insert_one(doc)
    return sr_id


def _cleanup(tid: str):
    if _sync is None:
        return
    for coll in ("tenants", "customers", "jobs", "service_reports", "users"):
        _sync[coll].delete_many({"tenant_id": tid})
    _sync.tenants.delete_many({"id": tid})


# ═══════════════════════════════════════════════════════════════════════
def test_pool_close_missing_readings_returns_structured_422():
    """Reproduces the iOS TestFlight repro exactly — only an
    ``Enzymes`` reading, no core five. Verifies the 422 body shape
    the mobile client depends on."""
    tid = _mk_tenant()
    try:
        tech_email, tech_id = _mk_user_tech(tid)
        jid = _seed_pool_job(tid, tech_id)
        _seed_report(tid, jid, tech_id, readings=[
            {"key": "enzymes", "name": "Enzymes", "value": 0},
        ])
        tok = _token_for(tech_email)
        r = httpx.post(
            f"{BASE}/api/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"},
            json={}, timeout=30,
        )
        assert r.status_code == 422, r.text
        body = r.json()
        # Contract keys mobile depends on.
        outer = body.get("detail")
        assert isinstance(outer, dict), \
            f"detail must be a DICT for the mobile unwrapper — got {type(outer)}"
        assert outer.get("detail") == "chemistry_core_readings_missing"
        assert isinstance(outer.get("missing_fields"), list)
        assert set(outer["missing_fields"]) == {
            "chlorine", "alkalinity", "ph", "cya",
        }
        assert isinstance(outer.get("missing_labels"), list)
        assert set(outer["missing_labels"]) == {
            "Chlorine", "Alkalinity", "pH", "CYA",
        }
        assert isinstance(outer.get("message"), str)
        assert "chemistry" in outer["message"].lower() \
            or "readings" in outer["message"].lower()
    finally:
        _cleanup(tid)


def test_pool_close_with_all_readings_succeeds_200():
    """Positive path — same job with all 5 canonical readings
    present must return 200. Locks the successful shape and
    verifies the gate does not false-positive."""
    tid = _mk_tenant()
    try:
        tech_email, tech_id = _mk_user_tech(tid)
        jid = _seed_pool_job(tid, tech_id)
        _seed_report(tid, jid, tech_id, readings=[
            {"key": "free_chlorine",   "value": 2.5},
            {"key": "alkalinity",      "value": 80},
            {"key": "ph",              "value": 7.4},
            {"key": "cyanuric_acid",   "value": 40},
            {"key": "enzymes",         "value": 0},  # extra non-canonical
        ])
        tok = _token_for(tech_email)
        r = httpx.post(
            f"{BASE}/api/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"},
            json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Response is the submitted report doc.
        assert body.get("job_id") == jid
        assert body.get("submitted_at"), body
        # Job status flipped to completed by the same handler.
        job = _sync.jobs.find_one({"id": jid})
        assert (job.get("status") or "").lower() == "completed"
    finally:
        _cleanup(tid)


def test_repair_class_pool_job_skips_chemistry_gate():
    """Repair-mode pool jobs (work_class == "repair") must skip the
    chemistry gate per the product spec. A repair report with zero
    readings should still close cleanly."""
    tid = _mk_tenant()
    try:
        tech_email, tech_id = _mk_user_tech(tid)
        jid = _seed_pool_job(tid, tech_id)
        # Flip the job + report to repair class.
        _sync.jobs.update_one({"id": jid},
                                 {"$set": {"work_class": "repair"}})
        _seed_report(tid, jid, tech_id, readings=[])
        _sync.service_reports.update_one(
            {"job_id": jid, "tenant_id": tid},
            {"$set": {"work_class": "repair"}},
        )
        tok = _token_for(tech_email)
        r = httpx.post(
            f"{BASE}/api/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"},
            json={}, timeout=30,
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(tid)


def test_pool_close_partial_readings_returns_only_missing_labels():
    """Techs frequently miss a subset of readings (e.g. forgot CYA).
    The 422 body must precisely list the MISSING labels so mobile
    can prompt: "Cannot close — CYA missing" instead of listing all
    five."""
    tid = _mk_tenant()
    try:
        tech_email, tech_id = _mk_user_tech(tid)
        jid = _seed_pool_job(tid, tech_id)
        _seed_report(tid, jid, tech_id, readings=[
            {"key": "free_chlorine",  "value": 2.5},
            {"key": "alkalinity",     "value": 80},
            {"key": "ph",             "value": 7.4},
            # cyanuric_acid intentionally missing
        ])
        tok = _token_for(tech_email)
        r = httpx.post(
            f"{BASE}/api/jobs/{jid}/service-report/submit",
            headers={"Authorization": f"Bearer {tok}"},
            json={}, timeout=30,
        )
        assert r.status_code == 422, r.text
        outer = r.json().get("detail")
        assert outer.get("missing_fields") == ["cya"]
        assert outer.get("missing_labels") == ["CYA"]
    finally:
        _cleanup(tid)
