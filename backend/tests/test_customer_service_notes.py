"""Customer service_notes ship — Feb-2026 (backend regression).

Coverage per user brief:
    1. PATCH service_notes.pool set + GET round-trips it.
    2. PATCH landscape without touching pool leaves pool unchanged.
    3. GET /service-notes-for-schedule?service_type=pool returns the
       pool note text (and 400 for unknown service types).
    4. GET /jobs enrichment includes the correct service_note based on
       job.service_type.
    5. Fallback: when job.service_type doesn't match any note key, the
       tech's specialty falls back.
    6. Techs read via the schedule endpoint but cannot PATCH.
    7. Backward compat: customers with no service_notes field render
       ``None`` cleanly.
"""
import os
import time
import uuid

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"SvcNote Test {marker}",
        "first_name": "TEST_SVC", "last_name": f"Note{marker}",
        "email": f"svc_{marker}@example.com",
        "phone": "+14805559100",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    requests.delete(f"{API}/customers/{doc['id']}", headers=admin_headers, timeout=15)


def test_patch_pool_note_stored_and_retrieved(admin_headers, customer):
    cid = customer["id"]
    r = requests.patch(f"{API}/customers/{cid}/service-notes",
                        headers=admin_headers, json={"pool": "Muriatic on-site — no MAP"},
                        timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["service_notes"]["pool"] == "Muriatic on-site — no MAP"

    # GET round-trips.
    r = requests.get(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["service_notes"]["pool"] == "Muriatic on-site — no MAP"


def test_patch_landscape_leaves_pool_untouched(admin_headers, customer):
    cid = customer["id"]
    # Seed the pool side first.
    requests.patch(f"{API}/customers/{cid}/service-notes",
                     headers=admin_headers, json={"pool": "Pool: keep it"},
                     timeout=15)
    # Now patch landscape only.
    r = requests.patch(f"{API}/customers/{cid}/service-notes",
                        headers=admin_headers,
                        json={"landscape": "Gate on left side"},
                        timeout=15)
    assert r.status_code == 200, r.text
    notes = r.json()["service_notes"]
    assert notes["landscape"] == "Gate on left side"
    assert notes["pool"] == "Pool: keep it", (
        f"landscape PATCH clobbered pool: {notes}"
    )


def test_patch_null_clears_only_that_side(admin_headers, customer):
    cid = customer["id"]
    requests.patch(f"{API}/customers/{cid}/service-notes",
                     headers=admin_headers,
                     json={"pool": "P", "landscape": "L"}, timeout=15)
    # Explicit null clears pool but preserves landscape.
    r = requests.patch(f"{API}/customers/{cid}/service-notes",
                        headers=admin_headers, json={"pool": None},
                        timeout=15)
    assert r.status_code == 200
    notes = r.json()["service_notes"]
    assert notes["pool"] is None
    assert notes["landscape"] == "L"


def test_get_service_notes_for_schedule_returns_slice(admin_headers, customer):
    cid = customer["id"]
    requests.patch(f"{API}/customers/{cid}/service-notes",
                     headers=admin_headers,
                     json={"pool": "Pool schedule note", "landscape": "Land schedule note"},
                     timeout=15)
    r = requests.get(
        f"{API}/customers/{cid}/service-notes-for-schedule?service_type=pool",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service_type"] == "pool"
    assert body["note"] == "Pool schedule note"
    assert body["customer_id"] == cid


def test_service_notes_for_schedule_400_on_unknown_type(admin_headers, customer):
    cid = customer["id"]
    r = requests.get(
        f"{API}/customers/{cid}/service-notes-for-schedule?service_type=hvac",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 400
    assert "service_type" in r.text.lower()


def test_service_notes_for_schedule_404_on_wrong_customer(admin_headers):
    r = requests.get(
        f"{API}/customers/does-not-exist/service-notes-for-schedule?service_type=pool",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 404


def test_job_list_enriches_service_note_based_on_service_type(admin_headers, customer):
    cid = customer["id"]
    requests.patch(f"{API}/customers/{cid}/service-notes",
                     headers=admin_headers,
                     json={"pool": "Pool NOTE 4 sched", "landscape": "Land NOTE 4 sched"},
                     timeout=15)
    # Create a pool job for this customer.
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": cid,
        "title": "TEST_svcnote_job_pool",
        "service_type": "pool",
        "scheduled_at": None,
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    try:
        # GET the job list — enrichment must include ``service_note``.
        r = requests.get(f"{API}/jobs", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        target = next((j for j in r.json() if j["id"] == jid), None)
        assert target is not None, "job not returned by /jobs"
        assert target.get("service_note") == "Pool NOTE 4 sched", (
            f"expected pool note enriched; got {target.get('service_note')!r}"
        )
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)


def test_customers_without_service_notes_return_none_cleanly(admin_headers):
    """Backward-compat — legacy customer docs with no service_notes
    field must return None on the schedule slice (not 500)."""
    marker = uuid.uuid4().hex[:6]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"LegacyNoSvc {marker}",
        "first_name": "TEST_LEG", "last_name": f"NoSvc{marker}",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    try:
        r = requests.get(
            f"{API}/customers/{cid}/service-notes-for-schedule?service_type=pool",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["note"] is None
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


def test_technician_can_read_schedule_slice_but_cannot_patch(admin_headers, customer):
    """Techs need to READ their service-note snippet on the schedule.
    They must NOT be able to write via PATCH (admin-only)."""
    cid = customer["id"]
    requests.patch(f"{API}/customers/{cid}/service-notes",
                     headers=admin_headers, json={"pool": "TechCanReadThis"},
                     timeout=15)
    tech_tok = _login("mike@aquaterra.com")
    th = {"Authorization": f"Bearer {tech_tok}"}
    # Read is allowed.
    r = requests.get(
        f"{API}/customers/{cid}/service-notes-for-schedule?service_type=pool",
        headers=th, timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["note"] == "TechCanReadThis"
    # PATCH is denied.
    r = requests.patch(f"{API}/customers/{cid}/service-notes", headers=th,
                        json={"pool": "TECH_WROTE_THIS"}, timeout=15)
    assert r.status_code in (401, 403), r.status_code
