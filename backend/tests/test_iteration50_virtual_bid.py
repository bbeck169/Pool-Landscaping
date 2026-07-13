"""Iteration 50 — Virtual Bid backend tests.

Coverage:
- GET /api/property/lookup — admin & technician allowed (returns photos + facts),
  customer role -> 403, address < 5 chars -> 400.
- POST /api/property/save with create_lead=true -> lead_created + lead_id, and
  the new lead is visible in GET /api/leads with source 'Virtual Bid'.
- POST /api/property/save with customer_id and lead_id attaches the property; the
  filtered GET /api/property/saved returns it; DELETE removes it.

Uses the public preview ingress (EXPO_PUBLIC_BACKEND_URL). Zillow provider is
LIVE — a 429 is treated as provider throttling, NOT a code bug.
"""

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUST = ("customer@aquaterra.com", "password123")

SAMPLE_ADDRESS = "1600 Pennsylvania Ave NW, Washington, DC 20500"


# ----- helpers -----
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("access_token") or body.get("token")
    assert tok, f"no token in login response: {body}"
    return tok


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(*TECH)


@pytest.fixture(scope="module")
def cust_tok():
    return _login(*CUST)


# ----- Property lookup (Zillow) -----
class TestPropertyLookup:
    def test_admin_lookup_returns_photos_and_facts(self, admin_tok):
        r = requests.get(
            f"{BASE_URL}/api/property/lookup",
            params={"address": SAMPLE_ADDRESS},
            headers=_hdr(admin_tok),
            timeout=40,
        )
        if r.status_code == 429:
            pytest.skip("Zillow provider throttling (429) — not a code bug")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        assert isinstance(data.get("photos"), list) and len(data["photos"]) >= 1, "expected at least 1 photo"
        for k in ("beds", "baths", "sqft"):
            assert k in data, f"missing {k} in response"
        # detail_url usually present
        assert data.get("address")

    def test_technician_lookup_allowed(self, tech_tok):
        r = requests.get(
            f"{BASE_URL}/api/property/lookup",
            params={"address": SAMPLE_ADDRESS},
            headers=_hdr(tech_tok),
            timeout=40,
        )
        if r.status_code == 429:
            pytest.skip("Zillow provider throttling (429)")
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        assert isinstance(r.json().get("photos"), list)

    def test_customer_lookup_forbidden(self, cust_tok):
        r = requests.get(
            f"{BASE_URL}/api/property/lookup",
            params={"address": SAMPLE_ADDRESS},
            headers=_hdr(cust_tok),
            timeout=20,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_short_address_returns_400(self, admin_tok):
        r = requests.get(
            f"{BASE_URL}/api/property/lookup",
            params={"address": "1600"},
            headers=_hdr(admin_tok),
            timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"


# ----- Property save (create lead) -----
class TestPropertySaveCreateLead:
    _created_lead_id = None
    _created_prop_id = None

    def test_save_creates_lead(self, admin_tok):
        payload = {
            "address": f"TEST_VBID {SAMPLE_ADDRESS}",
            "price": 350000,
            "beds": 3,
            "baths": 2,
            "sqft": 2500,
            "photos": ["https://photos.zillowstatic.com/fp/x.jpg"],
            "create_lead": True,
        }
        r = requests.post(f"{BASE_URL}/api/property/save", json=payload, headers=_hdr(admin_tok), timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("lead_created") is True
        assert body.get("lead_id")
        TestPropertySaveCreateLead._created_lead_id = body["lead_id"]
        prop = body.get("property") or {}
        TestPropertySaveCreateLead._created_prop_id = prop.get("id")
        assert prop.get("photos") and len(prop["photos"]) >= 1

    def test_lead_visible_in_leads_list(self, admin_tok):
        assert TestPropertySaveCreateLead._created_lead_id, "prior test must have created a lead"
        r = requests.get(f"{BASE_URL}/api/leads", headers=_hdr(admin_tok), timeout=20)
        assert r.status_code == 200
        leads = r.json()
        match = next((l for l in leads if l.get("id") == TestPropertySaveCreateLead._created_lead_id), None)
        assert match, "created lead not returned by /api/leads"
        assert match.get("source") == "Virtual Bid", f"expected source 'Virtual Bid', got {match.get('source')}"

    def test_cleanup_created_lead_and_prop(self, admin_tok):
        # delete saved property
        pid = TestPropertySaveCreateLead._created_prop_id
        if pid:
            requests.delete(f"{BASE_URL}/api/property/saved/{pid}", headers=_hdr(admin_tok), timeout=15)
        # delete lead
        lid = TestPropertySaveCreateLead._created_lead_id
        if lid:
            requests.delete(f"{BASE_URL}/api/leads/{lid}", headers=_hdr(admin_tok), timeout=15)


# ----- Property save attach / list / delete -----
class TestPropertyAttach:
    _customer_id = None
    _saved_id = None

    def test_pick_a_customer(self, admin_tok):
        r = requests.get(f"{BASE_URL}/api/customers", headers=_hdr(admin_tok), timeout=20)
        assert r.status_code == 200
        cs = r.json()
        assert cs, "no customers seeded"
        TestPropertyAttach._customer_id = cs[0]["id"]

    def test_save_attached_to_customer(self, admin_tok):
        assert TestPropertyAttach._customer_id
        payload = {
            "address": "TEST_VBID Attach Address 123",
            "price": 500000,
            "beds": 4,
            "baths": 3,
            "sqft": 3000,
            "photos": ["https://photos.zillowstatic.com/fp/attach.jpg"],
            "customer_id": TestPropertyAttach._customer_id,
        }
        r = requests.post(f"{BASE_URL}/api/property/save", json=payload, headers=_hdr(admin_tok), timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("lead_created") is False
        prop = body.get("property") or {}
        assert prop.get("customer_id") == TestPropertyAttach._customer_id
        TestPropertyAttach._saved_id = prop["id"]

    def test_list_saved_by_customer(self, admin_tok):
        assert TestPropertyAttach._customer_id
        r = requests.get(
            f"{BASE_URL}/api/property/saved",
            params={"customer_id": TestPropertyAttach._customer_id},
            headers=_hdr(admin_tok),
            timeout=20,
        )
        assert r.status_code == 200
        results = r.json()
        assert any(p.get("id") == TestPropertyAttach._saved_id for p in results), "saved property not listed"

    def test_delete_saved(self, admin_tok):
        assert TestPropertyAttach._saved_id
        r = requests.delete(
            f"{BASE_URL}/api/property/saved/{TestPropertyAttach._saved_id}",
            headers=_hdr(admin_tok),
            timeout=15,
        )
        assert r.status_code == 200
        # verify gone
        r2 = requests.get(
            f"{BASE_URL}/api/property/saved",
            params={"customer_id": TestPropertyAttach._customer_id},
            headers=_hdr(admin_tok),
            timeout=20,
        )
        assert r2.status_code == 200
        assert not any(p.get("id") == TestPropertyAttach._saved_id for p in r2.json())
