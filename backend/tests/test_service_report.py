"""Phase 18B follow-up · Service Report backend tests."""
import os
from pathlib import Path
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
import bcrypt
import uuid

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
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
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    # Sprint 3a · Feb 2026 — the `sunbelt` demo tenant is a permanent
    # cross-tenant fixture in production seed DBs but is not created by
    # any in-repo seed script; some pods (including fresh forks) start
    # without it. Align with `test_estimator.py::sunbelt_admin_h` and
    # skip gracefully when the tenant admin isn't reachable, so the
    # tenant-isolation test doesn't ERROR at fixture setup on those
    # environments.
    try:
        return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt admin seeded in this environment")


def _make_job_direct(dbc, tenant_slug: str, tech_id_field: str, service_type: str,
                     customer_id: str = None) -> str:
    """Create a job doc directly in Mongo, scoped to the given tenant + tech."""
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    assert tenant, f"tenant {tenant_slug} missing"
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant["id"],
        "customer_id": customer_id,
        "customer_name": "TEST_ svc report cust",
        "title": service_type,
        "service_type": service_type,
        "job_type": service_type,
        "status": "scheduled",
        "technician_id": tech_id_field,
        "photos": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup_job(dbc, jid: str):
    dbc.jobs.delete_one({"id": jid})
    dbc.service_reports.delete_many({"job_id": jid})


def test_get_service_report_pool_template(admin_h, tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Weekly Pool Service")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "pool"
        assert any(f["name"] == "pH" for f in data["chemical_readings"])
        assert len(data["checklist_items"]) >= 6
        # Phase 18B follow-up 2: pool template must surface source-repo enrichment
        assert "chemical_reading_fields" in data
        assert "chemicals_catalog" in data
        assert "chemical_units" in data
        # Reading fields carry picker options
        ph = next(f for f in data["chemical_reading_fields"] if f["key"] == "ph")
        assert ph["type"] == "select"
        assert "7.4" in ph["options"] and "7.6" in ph["options"]
        assert ph["ideal"] == "7.4–7.6"
        # Catalog has all 13 source-repo chemicals + unit dropdown
        assert len(data["chemicals_catalog"]) == 13
        names = [k["name"] for k in data["chemicals_catalog"]]
        for expected in ["Liquid Chlorine", "Chlorine Tablets", "Shock (Cal-Hypo)",
                         "Muriatic Acid", "Cyanuric Acid"]:
            assert expected in names
        assert data["chemical_units"] == ["gal", "lbs", "oz", "tabs"]
        # Tablet chemicals have whole-number amount options; others have 0.5-step
        tabs = next(k for k in data["chemicals_catalog"] if k["name"] == "Chlorine Tablets")
        assert tabs["amount_options"][0] == "1" and tabs["amount_options"][-1] == "10"
        liquid = next(k for k in data["chemicals_catalog"] if k["name"] == "Liquid Chlorine")
        assert liquid["amount_options"][0] == "0.5"
    finally:
        _cleanup_job(dbc, jid)


def test_pool_template_catalog_persist_roundtrip(tech_h, tech_user, dbc):
    """PATCH with a catalog-based chemical row must round-trip via GET."""
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Weekly Pool Service")
    try:
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        r = requests.patch(f"{API}/jobs/{jid}/service-report", headers=tech_h, json={
            "chemicals_added": [
                {"id": "a1", "name": "Muriatic Acid", "amount": "8", "unit": "oz"},
                {"id": "a2", "name": "Chlorine Tablets", "amount": "3", "unit": "tabs"},
            ],
        }, timeout=15)
        assert r.status_code == 200, r.text
        got = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15).json()
        assert [c["name"] for c in got["chemicals_added"]] == ["Muriatic Acid", "Chlorine Tablets"]
        assert got["chemicals_added"][0]["amount"] == "8"
        assert got["chemicals_added"][0]["unit"] == "oz"
        assert got["chemicals_added"][1]["unit"] == "tabs"
    finally:
        _cleanup_job(dbc, jid)


def test_get_service_report_landscape_template(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Monthly Landscaping")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "landscape"
        assert data["chemical_readings"] == []
        assert len(data["checklist_items"]) >= 6
    finally:
        _cleanup_job(dbc, jid)


def test_get_service_report_generic_template(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Other")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["template"] == "generic"
        assert data["chemical_readings"] == []
    finally:
        _cleanup_job(dbc, jid)


def test_photo_cap_at_10(admin_h, tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool cleaning")
    try:
        # bootstrap
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        # Push 10 photos ok
        for i in range(10):
            r = requests.post(f"{API}/jobs/{jid}/photos", headers=tech_h, json={
                "data": "data:image/png;base64,iVBORw0KGgo=",
                "label": f"p{i}",
            }, timeout=15)
            assert r.status_code == 200, r.text
        # 11th blocked
        r = requests.post(f"{API}/jobs/{jid}/photos", headers=tech_h, json={
            "data": "data:image/png;base64,iVBORw0KGgo=",
        }, timeout=15)
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["remaining_slots"] == 0
        assert "10-photo cap" in detail["msg"]
    finally:
        _cleanup_job(dbc, jid)


def test_autosave_patch_persists(tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool service")
    try:
        requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
        r = requests.patch(f"{API}/jobs/{jid}/service-report", headers=tech_h, json={
            "chemical_readings": [{"name": "pH", "value": 7.4, "unit": "", "ts": None}],
            "notes": "TEST_ autosave",
        }, timeout=15)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15).json()
        assert r2["notes"] == "TEST_ autosave"
        ph = next((x for x in r2["chemical_readings"] if x["name"] == "pH"), None)
        assert ph and float(ph["value"]) == 7.4
    finally:
        _cleanup_job(dbc, jid)


def test_submit_locks_report(admin_h, tech_h, tech_user, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool weekly")
    try:
        # Sprint 3a · Feb 2026 — PATCH the four "Required Four"
        # chemistry readings before submitting so the CHEM1 gate
        # ({free_cl, ph, alkalinity, cya}) doesn't 422 the test.
        # The bootstrap GET seeds the readings shape; we overlay
        # values on the canonical keys before submit.
        bootstrap = requests.get(f"{API}/jobs/{jid}/service-report",
                                    headers=tech_h, timeout=15).json()
        readings = list(bootstrap.get("chemical_readings") or [])
        _required_values = {
            "chlorine": 2.5,
            "ph": 7.5,
            "alkalinity": 100,
            "cyanuric": 40,
        }
        for row in readings:
            k = row.get("key")
            if k in _required_values:
                row["value"] = _required_values[k]
        pr = requests.patch(f"{API}/jobs/{jid}/service-report",
                              headers=tech_h,
                              json={"chemical_readings": readings},
                              timeout=15)
        assert pr.status_code == 200, pr.text
        r = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                          headers=tech_h, timeout=15)
        assert r.status_code == 200 and r.json()["submitted_at"]
        # CLEAN-4 · Feb 2026 — PATCH after submit → 409 for the
        # admin / super_admin lock path. Phase PS-A (Feb-2026)
        # intentionally relaxed the lock for the owning
        # technician (see routers/service_reports.py L584-591),
        # so a tech_h PATCH here would return 200. The test name
        # intent — "submit locks the report" — is preserved by
        # exercising the admin lock path which still 409s.
        r2 = requests.patch(f"{API}/jobs/{jid}/service-report", headers=admin_h,
                            json={"notes": "should fail"}, timeout=15)
        assert r2.status_code == 409
        # Job status rolled forward
        job = dbc.jobs.find_one({"id": jid})
        assert job["status"] == "completed"
        assert job.get("service_report_submitted_at")
    finally:
        _cleanup_job(dbc, jid)


def test_tenant_isolation_and_customer_forbidden(tech_h, tech_user, sunbelt_admin_h,
                                                 customer_h, dbc):
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Pool")
    try:
        # sunbelt admin sees 404 (leak-proof)
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                         headers=sunbelt_admin_h, timeout=15)
        assert r.status_code == 404
        # customer role → 403
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                         headers=customer_h, timeout=15)
        assert r.status_code in (403, 404)
    finally:
        _cleanup_job(dbc, jid)


# ═════════════════════════════════════════════════════════════════════
# Feb 2026 — Chemical readings restoration + algae round-trip
# ═════════════════════════════════════════════════════════════════════

def test_empty_tenant_template_falls_back_to_pool_defaults(admin_h, tech_h, tech_user, dbc):
    """A tenant that accidentally saved ``chemical_reading_fields=[]``
    on the pool template must NOT wipe chemistry from subsequent
    reports — ``_get_template`` coalesces an empty list back to the
    hard-coded defaults. Regression protection for the Feb 2026 fix.
    """
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    assert tenant
    # Save a bad template + assert the report still surfaces defaults.
    dbc.service_report_templates.update_one(
        {"tenant_id": tenant["id"], "kind": "pool"},
        {"$set": {"tenant_id": tenant["id"], "kind": "pool",
                    "chemical_reading_fields": [],  # the bad state
                    "chemicals_catalog": [],
                    "chemical_units": [],
                    "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Weekly Pool Service")
    try:
        r = requests.get(f"{API}/jobs/{jid}/service-report",
                         headers=tech_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "pool"
        keys = [f["key"] for f in data["chemical_reading_fields"]]
        # Every canonical chemistry field must still be present.
        # CLEAN-4 · Feb 2026 — post Phase P17.1 the canonical key
        # for chlorine is ``chlorine`` again (end-to-end rename
        # reverted the Sprint 3a CHEM1 intermediate across the
        # chemistry gate, template schema, and the front-end
        # reading rows). Assertion matches the current canonical.
        for expected in ("chlorine", "ph", "alkalinity", "cyanuric",
                          "calcium_hardness", "salt", "water_temp"):
            assert expected in keys, (
                f"chemistry field '{expected}' missing after tenant saved "
                f"empty chemical_reading_fields — Feb 2026 regression"
            )
        # Chemicals catalog also restored.
        assert len(data["chemicals_catalog"]) >= 5
    finally:
        _cleanup_job(dbc, jid)
        # Clean up the bad template so downstream tests aren't affected.
        dbc.service_report_templates.delete_one(
            {"tenant_id": tenant["id"], "kind": "pool"},
        )


def test_algae_field_round_trips_alongside_chemistry(admin_h, tech_h, tech_user, dbc):
    """Confirm ``observations.visible_algae`` persists through PATCH +
    GET and coexists with chemistry updates."""
    tid = tech_user["user"].get("technician_id") or tech_user["user"]["id"]
    jid = _make_job_direct(dbc, "aquaterra", tid, "Weekly Pool Service")
    try:
        r0 = requests.get(f"{API}/jobs/{jid}/service-report",
                          headers=tech_h, timeout=15)
        assert r0.status_code == 200, r0.text
        initial = r0.json()
        readings = list(initial.get("chemical_readings") or [])
        assert readings, "bootstrap must return chemistry rows"
        # Populate a couple of chemistry values + set algae=light.
        # CLEAN-4 · Feb 2026 — post Phase P17.1 the canonical key
        # for chlorine is ``chlorine`` again (Sprint 3a CHEM1
        # intermediate was reverted end-to-end).
        for row in readings:
            if row.get("key") == "chlorine":
                row["value"] = 2.5
            if row.get("key") == "ph":
                row["value"] = 7.5

        r1 = requests.patch(
            f"{API}/jobs/{jid}/service-report",
            headers={**tech_h, "Content-Type": "application/json"},
            json={"chemical_readings": readings,
                   "observations": {"visible_algae": "light",
                                    "algae_notes": "TEST_light on skimmer"}},
            timeout=15,
        )
        assert r1.status_code == 200, r1.text

        r2 = requests.get(f"{API}/jobs/{jid}/service-report",
                          headers=tech_h, timeout=15)
        after = r2.json()
        assert after["observations"]["visible_algae"] == "light"
        assert after["observations"]["algae_notes"] == "TEST_light on skimmer"
        chl = next(x for x in after["chemical_readings"] if x.get("key") == "chlorine")
        ph = next(x for x in after["chemical_readings"] if x.get("key") == "ph")
        assert chl["value"] == 2.5
        assert ph["value"] == 7.5
    finally:
        _cleanup_job(dbc, jid)
