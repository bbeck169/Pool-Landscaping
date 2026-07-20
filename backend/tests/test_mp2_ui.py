"""MP2 UI — Multi-Property Web + Mobile smoke (Feb-2026 ship).

Backend-facing smoke tests that back the new UI surfaces:
    * ``GET  /api/customers`` now includes ``properties_count`` per row.
    * ``GET  /api/jobs`` enriches each job with ``property_label`` +
      ``property_address`` (used by mobile schedule chips + Job Detail).
    * Job create with the property picker payload persists property_id.
    * Master Billing card / Preview / Consolidate happy path still
      round-trips end-to-end from the UI's perspective (endpoints
      shape unchanged since MP1.5, but this smoke pins them).
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def customer(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"MP2UI {marker}",
        "first_name": "TEST_MP2", "last_name": f"UI{marker}",
        "email": f"mp2ui_{marker}@example.com",
        "phone": "+14805559999",
        "address": "42 UI Way",
        "address_line1": "42 UI Way",
        "city": "Peoria", "state": "AZ", "postal_code": "85383",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    doc = r.json()
    yield doc
    for p in requests.get(f"{API}/customers/{doc['id']}/properties",
                            headers=admin_headers, timeout=15).json() or []:
        requests.delete(f"{API}/properties/{p['id']}",
                          headers=admin_headers, timeout=15)
    requests.delete(f"{API}/customers/{doc['id']}",
                      headers=admin_headers, timeout=15)


def _add_prop(admin_headers, cid, label):
    r = requests.post(f"{API}/customers/{cid}/properties",
                        headers=admin_headers, json={
        "label": label,
        "address": {"line1": f"{label} 100 Way", "city": "Peoria",
                     "state": "AZ", "postal_code": "85383"},
    }, timeout=15)
    assert r.status_code == 201, r.text
    return r.json()


# ─── properties_count on /customers ────────────────────────────────────

def test_customer_list_carries_properties_count(admin_headers, customer):
    _add_prop(admin_headers, customer["id"], "Alpha")
    _add_prop(admin_headers, customer["id"], "Bravo")
    r = requests.get(f"{API}/customers", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    row = next((c for c in r.json() if c["id"] == customer["id"]), None)
    assert row is not None
    assert row["properties_count"] == 2


def test_customer_list_properties_count_soft_deletes_excluded(admin_headers, customer):
    p1 = _add_prop(admin_headers, customer["id"], "Keep")
    p2 = _add_prop(admin_headers, customer["id"], "Toss")
    requests.delete(f"{API}/properties/{p2['id']}",
                      headers=admin_headers, timeout=15)
    r = requests.get(f"{API}/customers", headers=admin_headers, timeout=15)
    row = next((c for c in r.json() if c["id"] == customer["id"]), None)
    assert row is not None
    assert row["properties_count"] == 1


def test_customer_list_zero_when_no_properties(admin_headers):
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"NoProps {marker}",
        "first_name": "TEST_NOPRP", "last_name": f"N{marker}",
    }, timeout=15)
    assert r.status_code in (200, 201)
    cid = r.json()["id"]
    try:
        r = requests.get(f"{API}/customers", headers=admin_headers, timeout=15)
        row = next((c for c in r.json() if c["id"] == cid), None)
        assert row is not None
        assert row["properties_count"] == 0
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


# ─── property_label / property_address enrichment on /jobs ────────────

def test_jobs_list_enriches_property_label_and_address(admin_headers, customer):
    p = _add_prop(admin_headers, customer["id"], "MobileTest")
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": p["id"],
        "title": "TEST_property_enrich",
        "status": "scheduled",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    jid = r.json()["id"]
    try:
        r = requests.get(f"{API}/jobs", headers=admin_headers, timeout=15)
        j = next((x for x in r.json() if x["id"] == jid), None)
        assert j is not None
        assert j.get("property_label") == "MobileTest"
        assert j.get("property_address")
        assert "MobileTest 100 Way" in j["property_address"]
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)


def test_jobs_without_property_id_have_no_enrichment(admin_headers):
    """Legacy jobs on customers with 0 properties must not error out;
    the enrichment fields simply remain absent."""
    marker = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/customers", headers=admin_headers, json={
        "name": f"NoPropCust {marker}",
        "first_name": "TEST_NP", "last_name": f"N{marker}",
    }, timeout=15)
    cid = r.json()["id"]
    try:
        r = requests.post(f"{API}/jobs", headers=admin_headers, json={
            "customer_id": cid,
            "title": "TEST_no_property_enrich",
            "status": "scheduled",
        }, timeout=15)
        assert r.status_code in (200, 201), r.text
        jid = r.json()["id"]
        r = requests.get(f"{API}/jobs", headers=admin_headers, timeout=15)
        j = next((x for x in r.json() if x["id"] == jid), None)
        assert j is not None
        assert j.get("property_label") in (None, "")
        requests.delete(f"{API}/jobs/{jid}", headers=admin_headers, timeout=15)
    finally:
        requests.delete(f"{API}/customers/{cid}",
                          headers=admin_headers, timeout=15)


# ─── Job create with picker payload ────────────────────────────────────

def test_job_create_via_picker_persists_property_id(admin_headers, customer):
    p1 = _add_prop(admin_headers, customer["id"], "PickerA")
    _add_prop(admin_headers, customer["id"], "PickerB")
    r = requests.post(f"{API}/jobs", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": p1["id"],
        "title": "TEST_picker_persist",
        "status": "scheduled",
    }, timeout=15)
    assert r.status_code in (200, 201), r.text
    assert r.json()["property_id"] == p1["id"]
    requests.delete(f"{API}/jobs/{r.json()['id']}",
                      headers=admin_headers, timeout=15)


# ─── Master Billing card round-trip ────────────────────────────────────

def test_master_billing_card_e2e(admin_headers, customer):
    p = _add_prop(admin_headers, customer["id"], "BillProp")
    r = requests.patch(f"{API}/customers/{customer['id']}/master-billing",
                         headers=admin_headers, json={
        "mode": "consolidated",
    }, timeout=15)
    assert r.status_code == 200
    r = requests.post(f"{API}/invoices/preview-recipient",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
    }, timeout=15)
    assert r.status_code == 200
    rec = r.json()["recipient"]
    assert rec["mode"] == "consolidated"
    # Create a small pending invoice so consolidate has something to work with.
    r = requests.post(f"{API}/quotes", headers=admin_headers, json={
        "customer_id": customer["id"],
        "property_id": p["id"],
        "title": "TEST_cons",
        "doc_type": "invoice",
        "line_items": [{"description": "svc", "quantity": 1,
                          "unit_price": 15, "category": "Pool"}],
    }, timeout=15)
    assert r.status_code in (200, 201)
    r = requests.get(f"{API}/customers/{customer['id']}/pending-invoices",
                       headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["pending_count"] >= 1
    r = requests.post(f"{API}/invoices/consolidate",
                        headers=admin_headers, json={
        "customer_id": customer["id"],
        "period": "2026-02",
    }, timeout=15)
    assert r.status_code == 200
    assert r.json()["ok"] is True
