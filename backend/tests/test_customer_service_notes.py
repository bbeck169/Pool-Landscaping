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


def test_first_patch_on_customer_without_service_notes_succeeds(admin_headers):
    """Tester regression fix — legacy customer docs have no ``service_notes``
    key. The projection ``{_id:0, service_notes:1}`` returned ``{}``
    for them, and the old ``if not existing:`` guard raised 404. This
    test seeds a fresh customer WITHOUT service_notes and asserts the
    first PATCH lands cleanly."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"FirstPatch {marker}",
        "first_name": "TEST_FP", "last_name": f"FirstPatch{marker}",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    # Sanity — this fresh customer must not have service_notes yet.
    try:
        first = requests.patch(f"{API}/customers/{cid}/service-notes",
                                 headers=admin_headers,
                                 json={"pool": "First-write pool note"}, timeout=15)
        assert first.status_code == 200, (
            f"first-write PATCH must succeed on legacy customer; got "
            f"{first.status_code} {first.text}"
        )
        assert first.json()["service_notes"]["pool"] == "First-write pool note"
    finally:
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)


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


def test_jobs_endpoint_respects_limit_query_param(admin_headers):
    """Feb-2026 hygiene fix — tester found ``GET /api/jobs?limit=20``
    returned 1000 items because the value was ignored. Pin the fix."""
    r = requests.get(f"{API}/jobs?limit=3", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert len(r.json()) <= 3, f"limit=3 returned {len(r.json())} items"
    r = requests.get(f"{API}/jobs?limit=1", headers=admin_headers, timeout=15)
    assert len(r.json()) <= 1


def test_schedule_today_carries_service_note(admin_headers):
    """Feb-2026 Note-pill ship — techs on their /schedule/today feed must
    see the specialty-specific note enriched onto each job item so the
    mobile Schedule row can render the pill without an extra RPC."""
    tech_tok = _login("mike@aquaterra.com")
    th = {"Authorization": f"Bearer {tech_tok}"}
    r = requests.get(f"{API}/schedule/today", headers=th, timeout=15)
    assert r.status_code == 200
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    # Field must be present on every job-typed item (may be None when
    # neither the customer nor the tech's specialty resolves a note).
    for it in (items or []):
        if it.get("type") == "job":
            assert "service_note" in it, (
                f"schedule/today job missing 'service_note': keys={list(it.keys())}"
            )



def test_resolver_substring_matches_weekly_pool_service(admin_headers, customer):
    """Feb-2026 tester fix — legacy jobs carry values like ``"Weekly Pool
    Service"`` in service_type / job_type. The resolver must substring-
    match those onto the ``"pool"`` note key so the pill renders."""
    from routers.customers import _resolve_service_note
    cust = {"service_notes": {"pool": "POOL_NOTE_XYZ",
                                "landscape": "LAND_NOTE_ABC"}}
    # Direct key hit.
    assert _resolve_service_note(cust, "pool", None) == "POOL_NOTE_XYZ"
    # Substring — the actual regression from prod data.
    assert _resolve_service_note(cust, "Weekly Pool Service", None) == "POOL_NOTE_XYZ"
    assert _resolve_service_note(cust, "Landscape Maintenance", None) == "LAND_NOTE_ABC"
    # No match, no specialty fallback → None.
    assert _resolve_service_note(cust, "Roof Repair", None) is None
    # Specialty fallback kicks in when service_type doesn't match.
    tech = {"specialties": ["pool"]}
    assert _resolve_service_note(cust, "Roof Repair", tech) == "POOL_NOTE_XYZ"


def test_schedule_today_resolves_service_note_from_job_type_alias(admin_headers):
    """End-to-end regression for the tester finding: seed a customer with
    a pool note + a job whose ``job_type == 'pool'`` (no ``service_type``
    set) assigned to a specific tech. GET /schedule/today as that tech
    and assert both ``service_note`` and ``job_type`` are present + not
    null."""
    from pymongo import MongoClient
    from dotenv import dotenv_values
    from datetime import datetime, timezone
    env = dotenv_values("/app/backend/.env")
    client = MongoClient(env["MONGO_URL"])
    db_ = client[env["DB_NAME"]]

    marker = uuid.uuid4().hex[:8]
    # Seed customer with a note.
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"NoteSchedule {marker}",
        "first_name": "TEST_NS", "last_name": f"Sched{marker}",
        "service_notes": {"pool": f"POOL_TEST_{marker}"},
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]

    # Resolve mike's user id + tenant.
    tech_tok = _login("mike@aquaterra.com")
    tech_who = requests.get(f"{API}/auth/me",
                              headers={"Authorization": f"Bearer {tech_tok}"},
                              timeout=15).json()
    tid = tech_who["tenant_id"]
    mike_id = tech_who["id"]

    # Insert a job assigned to mike, scheduled today, with job_type=pool
    # (no service_type) so we're testing the alias resolution path.
    # ``/schedule/today`` queries ``scheduled_date`` with a full ISO
    # datetime range so we must use that shape (matches the seed data).
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    jid = uuid.uuid4().hex
    db_.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": cid, "assigned_technician_id": mike_id,
        "title": f"TEST_ns_{marker}", "job_type": "pool",
        "customer_name": f"NoteSchedule {marker}",
        "status": "scheduled",
        "scheduled_date": now_iso,
    })
    try:
        r = requests.get(f"{API}/schedule/today",
                           headers={"Authorization": f"Bearer {tech_tok}"},
                           timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data.get("items") if isinstance(data, dict) else data
        target = next((it for it in (items or []) if it.get("id") == jid), None)
        assert target is not None, (
            f"seeded job not returned by /schedule/today for mike; items={items!r}"
        )
        # Both fields must land on the serialized item.
        assert target.get("job_type") == "pool", (
            f"job_type dropped from serialized item: {target}"
        )
        assert target.get("service_note") == f"POOL_TEST_{marker}", (
            f"service_note not resolved via job_type alias: "
            f"got {target.get('service_note')!r}, item={target}"
        )
    finally:
        db_.jobs.delete_one({"id": jid})
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)
        client.close()


def test_jobs_list_resolves_service_note_from_job_type_alias(admin_headers):
    """Defense-in-depth — same alias fallback must work for /api/jobs
    enrichment. Seed a customer + a job whose only type field is
    ``job_type`` and assert /jobs surfaces the correct service_note."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"JobsNote {marker}",
        "first_name": "TEST_JN", "last_name": f"Jobs{marker}",
        "service_notes": {"pool": f"JOBS_POOL_{marker}"},
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": cid,
        "title": f"TEST_jobs_note_{marker}",
        "job_type": "pool",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    try:
        r = requests.get(f"{API}/jobs", headers=admin_headers, timeout=15)
        target = next((j for j in r.json() if j.get("id") == jid), None)
        assert target is not None, "seeded job not in /jobs list"
        assert target.get("service_note") == f"JOBS_POOL_{marker}", (
            f"expected pool note via job_type alias; got {target.get('service_note')!r}"
        )
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)
        requests.delete(f"{API}/customers/{cid}", headers=admin_headers, timeout=15)

