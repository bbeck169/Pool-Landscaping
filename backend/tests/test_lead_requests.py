"""Phase 15B slot-in — Lead Request Distributor."""
import os
from pathlib import Path

import requests
from dotenv import dotenv_values

_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestLeadRequestGeneration:
    def test_generate_link_ok(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link", "custom_message": "TEST_LR test", "expiry_hours": 48},
                          timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] and d["sent"] and d["url"].startswith("http")
        assert d["dispatch"]["expires_at"]

    def test_generate_sms_graceful_when_twilio_missing(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "sms", "to": "+15551234567",
                                "custom_message": "TEST_LR sms", "expiry_hours": 48},
                          timeout=15).json()
        # If RC isn't configured, sent should be False with a reason.
        # If it happens to be live, sent may be True.
        if not r["sent"]:
            assert r["reason"] in ("sms-not-configured", "twilio-not-configured", None) or "sms" in (r["reason"] or "").lower() or "not configured" in (r["reason"] or "").lower()
        assert r["url"].startswith("http")

    def test_generate_email_graceful(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "email", "to": "prospect@example.com",
                                "custom_message": "TEST_LR email", "expiry_hours": 24},
                          timeout=20).json()
        # Should not raise regardless of Resend state.
        assert r["url"].startswith("http")

    def test_generate_forbidden_for_tech(self):
        h = _login(*TECH)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link"}, timeout=10)
        assert r.status_code in (401, 403)


class TestPublicFlow:
    def test_public_get_then_submit_creates_lead(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link", "custom_message": "TEST_LR flow"}, timeout=15).json()
        token = r["token"]

        # Public GET
        pub = requests.get(f"{BASE}/api/public/lead-request/{token}", timeout=15)
        assert pub.status_code == 200
        body = pub.json()
        assert body["personal_message"] == "TEST_LR flow"
        assert body["form"]["fields"]
        assert body["branding"]["business_name"]

        # Submit
        payload = {
            "first_name": "TEST", "last_name": "Prospect",
            "cell_phone": "5551112222", "email": "test-lr@example.com",
            "address": "123 Elm", "city": "Peoria", "state": "AZ", "zip": "85383",
            "notes": "TEST_LR interested",
        }
        sub = requests.post(f"{BASE}/api/public/lead-request/{token}/submit",
                            data=payload, timeout=15)
        assert sub.status_code == 200
        lead_id = sub.json()["lead_id"]
        assert lead_id

        # Lead exists with correct source
        leads = requests.get(f"{BASE}/api/leads", headers=h, timeout=15).json()
        lead = next((l for l in leads if l.get("id") == lead_id), None)
        assert lead
        assert lead["source"] == "lead-request-link"
        assert lead["dispatched_by"]

        # Dispatch updated with submitted_at and resulting_lead_id
        dispatches = requests.get(f"{BASE}/api/lead-requests", headers=h, timeout=15).json()
        d = next((x for x in dispatches if x["generated_token"] == token), None)
        assert d and d["submitted_at"] and d["resulting_lead_id"] == lead_id

    def test_revoked_link_404(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link", "custom_message": "TEST_LR revoke"}, timeout=15).json()
        did, token = r["dispatch"]["id"], r["token"]
        requests.post(f"{BASE}/api/lead-requests/{did}/revoke", headers=h, timeout=10)
        pub = requests.get(f"{BASE}/api/public/lead-request/{token}", timeout=10)
        assert pub.status_code == 404

    def test_double_submit_410(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link", "custom_message": "TEST_LR double"}, timeout=15).json()
        token = r["token"]
        payload = {
            "first_name": "A", "last_name": "B", "cell_phone": "1", "email": "e@e",
            "address": "x", "city": "y", "state": "z", "zip": "1", "notes": "n",
        }
        requests.post(f"{BASE}/api/public/lead-request/{token}/submit", data=payload, timeout=15)
        second = requests.post(f"{BASE}/api/public/lead-request/{token}/submit", data=payload, timeout=15)
        assert second.status_code in (410, 400)

    def test_missing_required_fields(self):
        h = _login(*ADMIN)
        r = requests.post(f"{BASE}/api/lead-requests/generate", headers=h,
                          json={"method": "link", "custom_message": "TEST_LR miss"}, timeout=15).json()
        token = r["token"]
        r2 = requests.post(f"{BASE}/api/public/lead-request/{token}/submit",
                           data={"first_name": "Only"}, timeout=15)
        assert r2.status_code == 400


def test_zzz_cleanup():
    """Purge TEST_LR data."""
    from motor.motor_asyncio import AsyncIOMotorClient
    import asyncio
    mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    db_name = os.environ.get("DB_NAME") or "test_database"
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    async def _clean():
        await db.leads.delete_many({"notes": {"$regex": "TEST_LR", "$options": "i"}})
        await db.leads.delete_many({"first_name": "TEST"})
        await db.lead_request_dispatches.delete_many({"custom_message": {"$regex": "TEST_LR", "$options": "i"}})
    asyncio.run(_clean())
    client.close()
