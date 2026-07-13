"""Iteration 27 backend tests:

Covers:
- GET /api/card RBAC + payload shape for admin / technician / customer
- PUT /api/card/company (admin only) persistence + RBAC
- PUT /api/card/personal (technician only) persistence + RBAC
- POST /api/leads allowed for admin + technician (both), forbidden for customer
- GET /api/leads (admin) reflects newly created lead + created_by
- GET /api/jobs enrichment: technician sees gate_code + account_notes;
  customer role never sees them and internal_notes stripped
- POST /api/customers accepts gate_code (admin) and PUT preserves it
"""
import os
import pytest
import requests
from pathlib import Path
from dotenv import dotenv_values

# Backend URL from frontend .env (public url) — this is what the app uses
_FE_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
BASE_URL = (
    dotenv_values(_FE_ENV).get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
).rstrip("/")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUST = {"email": "customer@aquaterra.com", "password": "password123"}


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tokens():
    return {"admin": _login(**ADMIN), "tech": _login(**TECH), "cust": _login(**CUST)}


# ---------------- /api/card ----------------
class TestCard:
    def test_admin_card(self, tokens):
        r = requests.get(f"{BASE_URL}/api/card", headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit_company"] is True
        assert d["can_edit_personal"] is False
        assert d["personal"] is None
        assert "name" in d["company"] and d["company"]["name"]

    def test_tech_card(self, tokens):
        r = requests.get(f"{BASE_URL}/api/card", headers=_hdr(tokens["tech"]))
        assert r.status_code == 200
        d = r.json()
        assert d["can_edit_personal"] is True
        assert d["can_edit_company"] is False
        p = d["personal"]
        assert p is not None
        for k in ("name", "title", "phone", "email"):
            assert k in p and p[k] not in (None, "")

    def test_customer_card(self, tokens):
        r = requests.get(f"{BASE_URL}/api/card", headers=_hdr(tokens["cust"]))
        assert r.status_code == 200
        d = r.json()
        assert d["personal"] is None
        assert d["can_edit_company"] is False
        assert d["can_edit_personal"] is False
        assert d["company"]["name"]

    def test_put_company_admin_persists(self, tokens):
        new_tag = "TEST_ tagline " + os.urandom(3).hex()
        r = requests.put(
            f"{BASE_URL}/api/card/company",
            headers=_hdr(tokens["admin"]),
            json={"tagline": new_tag},
        )
        assert r.status_code == 200, r.text
        assert r.json()["tagline"] == new_tag
        # Read back via GET
        r2 = requests.get(f"{BASE_URL}/api/card", headers=_hdr(tokens["admin"]))
        assert r2.json()["company"]["tagline"] == new_tag

    def test_put_company_forbidden_for_tech_and_customer(self, tokens):
        for who in ("tech", "cust"):
            r = requests.put(
                f"{BASE_URL}/api/card/company",
                headers=_hdr(tokens[who]),
                json={"tagline": "should not save"},
            )
            assert r.status_code == 403, f"{who} got {r.status_code}"

    def test_put_personal_tech_persists(self, tokens):
        new_title = "TEST_ Senior Pool Tech " + os.urandom(2).hex()
        r = requests.put(
            f"{BASE_URL}/api/card/personal",
            headers=_hdr(tokens["tech"]),
            json={"title": new_title},
        )
        assert r.status_code == 200, r.text
        r2 = requests.get(f"{BASE_URL}/api/card", headers=_hdr(tokens["tech"]))
        assert r2.json()["personal"]["title"] == new_title

    def test_put_personal_forbidden_admin_and_customer(self, tokens):
        for who in ("admin", "cust"):
            r = requests.put(
                f"{BASE_URL}/api/card/personal",
                headers=_hdr(tokens[who]),
                json={"title": "nope"},
            )
            assert r.status_code == 403, f"{who} got {r.status_code}: {r.text}"


# ---------------- /api/leads ----------------
class TestLeads:
    created_ids = []

    def test_admin_can_create_lead(self, tokens):
        payload = {"name": "TEST_ Admin Lead", "source": "Google", "notes": "TEST_admin"}
        r = requests.post(f"{BASE_URL}/api/leads", headers=_hdr(tokens["admin"]), json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == payload["name"]
        assert d["created_by"]
        TestLeads.created_ids.append(d["id"])

    def test_tech_can_create_lead(self, tokens):
        payload = {"name": "TEST_ Tech Lead", "source": "Referral", "notes": "TEST_tech"}
        r = requests.post(f"{BASE_URL}/api/leads", headers=_hdr(tokens["tech"]), json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == payload["name"]
        assert d["created_by"]
        TestLeads.created_ids.append(d["id"])

    def test_customer_cannot_create_lead(self, tokens):
        r = requests.post(
            f"{BASE_URL}/api/leads",
            headers=_hdr(tokens["cust"]),
            json={"name": "TEST_ Cust Lead"},
        )
        assert r.status_code == 403

    def test_admin_lead_list_contains_new(self, tokens):
        r = requests.get(f"{BASE_URL}/api/leads", headers=_hdr(tokens["admin"]))
        assert r.status_code == 200
        ids = {l["id"] for l in r.json()}
        for cid in TestLeads.created_ids:
            assert cid in ids

    def test_tech_cannot_list_leads(self, tokens):
        r = requests.get(f"{BASE_URL}/api/leads", headers=_hdr(tokens["tech"]))
        assert r.status_code == 403


# ---------------- /api/jobs enrichment ----------------
class TestJobsEnrichment:
    def test_tech_sees_gate_and_notes(self, tokens):
        r = requests.get(f"{BASE_URL}/api/jobs", headers=_hdr(tokens["tech"]))
        assert r.status_code == 200
        jobs = r.json()
        assert jobs, "expected mike's assigned jobs to be present"
        # At least one job must expose the enrichment fields (mike's jobs have gate_code seed)
        any_gate = any(j.get("gate_code") for j in jobs)
        any_notes = any(j.get("account_notes") for j in jobs)
        assert any_gate, "expected at least one tech job to have gate_code"
        assert any_notes, "expected at least one tech job to have account_notes"

    def test_customer_no_enrichment_and_no_internal_notes(self, tokens):
        r = requests.get(f"{BASE_URL}/api/jobs", headers=_hdr(tokens["cust"]))
        assert r.status_code == 200
        for j in r.json():
            assert "gate_code" not in j, "customer must not see gate_code"
            assert "account_notes" not in j, "customer must not see account_notes"
            assert "internal_notes" not in j, "customer must not see internal_notes"


# ---------------- /api/customers accepts gate_code ----------------
class TestCustomersGateCode:
    created_id = None

    def test_create_customer_with_gate_code(self, tokens):
        payload = {
            "name": "TEST_ GateCode Customer",
            "email": "TEST_gate@example.com",
            "phone": "555-000-0001",
            "address": "1 Test Ln",
            "gate_code": "#9911",
            "notes": "Beware of dog.",
        }
        r = requests.post(f"{BASE_URL}/api/customers", headers=_hdr(tokens["admin"]), json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["gate_code"] == "#9911"
        assert d["notes"] == payload["notes"]
        TestCustomersGateCode.created_id = d["id"]

        # GET back to confirm persistence
        r2 = requests.get(
            f"{BASE_URL}/api/customers/{d['id']}", headers=_hdr(tokens["admin"])
        )
        assert r2.status_code == 200
        assert r2.json()["gate_code"] == "#9911"

    def test_update_customer_updates_gate_code(self, tokens):
        cid = TestCustomersGateCode.created_id
        assert cid, "create test must run first"
        upd = {
            "name": "TEST_ GateCode Customer",
            "email": "TEST_gate@example.com",
            "phone": "555-000-0001",
            "address": "1 Test Ln",
            "gate_code": "#7788",
            "notes": "Updated notes.",
        }
        r = requests.put(
            f"{BASE_URL}/api/customers/{cid}", headers=_hdr(tokens["admin"]), json=upd
        )
        assert r.status_code == 200, r.text
        assert r.json()["gate_code"] == "#7788"
        # GET to verify
        r2 = requests.get(
            f"{BASE_URL}/api/customers/{cid}", headers=_hdr(tokens["admin"])
        )
        assert r2.json()["gate_code"] == "#7788"


# ---------------- Module teardown: restore card_settings ----------------
@pytest.fixture(scope="module", autouse=True)
def _restore_card_settings():
    """After this module runs, wipe any card_settings docs so the app returns
    to its DEFAULT_COMPANY / tech-derived defaults."""
    yield
    try:
        from pymongo import MongoClient
        from dotenv import dotenv_values as _dv
        env = _dv(Path(__file__).resolve().parents[1] / ".env")
        mc = MongoClient(env.get("MONGO_URL"))
        mc[env.get("DB_NAME")]["card_settings"].delete_many({})
        mc.close()
    except Exception as e:  # noqa: BLE001
        print(f"[iteration27 teardown] card_settings cleanup failed: {e}")
