"""Iteration 21 - Tests for:
  1) One-tap booking (POST /me/book) creates a requested job + clears slots + confirmation msg
  2) AI pause toggle per conversation (POST /communications/{cid}/ai-toggle)
  3) generate_ai_reply returns slots only for scheduling intents
"""
import os
import time
import pytest
import requests
from dotenv import dotenv_values
from pathlib import Path
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env"
).get("EXPO_PUBLIC_BACKEND_URL")
BASE_URL = (BASE_URL or "").rstrip("/")
API = f"{BASE_URL}/api"

CUSTOMER_EMAIL = "customer@aquaterra.com"
ADMIN_EMAIL = "admin@aquaterra.com"
PASSWORD = "password123"
CUSTOMER_ID = "fc1e3e5a-7b4e-4cf6-83b4-b7e5cb2f6cd6"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def customer_token():
    r = requests.post(f"{API}/auth/login", json={"email": CUSTOMER_EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def _reset_and_cleanup():
    """Ensure ai_paused=false before + purge chat-created jobs after."""
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    client = MongoClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]
    db.customers.update_one({"id": CUSTOMER_ID}, {"$set": {"ai_paused": False}})
    yield
    db.customers.update_one({"id": CUSTOMER_ID}, {"$set": {"ai_paused": False}})
    db.jobs.delete_many({"customer_id": CUSTOMER_ID, "title": "Service Request"})
    db.messages.delete_many({"customer_id": CUSTOMER_ID, "text": {"$regex": "^(TESTMSG_|✅ Great)"}})
    client.close()


# ---------- 1) One-tap booking + billing has no slots ----------
class TestSchedulingAndBooking:
    def test_scheduling_message_returns_slots(self, customer_token):
        payload = {"text": "TESTMSG_Can you schedule a cleaning next week?"}
        r = requests.post(f"{API}/me/messages", json=payload, headers=_h(customer_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ai_reply") is not None, "Marina should reply for scheduling intent"
        slots = data["ai_reply"].get("slots")
        assert slots and len(slots) > 0, f"Slots must be attached for scheduling intent, got {slots}"
        assert all("date" in s and "label" in s and "window" in s for s in slots)
        # store first slot for booking test
        pytest.first_slot = slots[0]
        pytest.ai_msg_id = data["ai_reply"]["id"]

    def test_billing_message_has_no_slots(self, customer_token):
        payload = {"text": "TESTMSG_how much do I owe?"}
        r = requests.post(f"{API}/me/messages", json=payload, headers=_h(customer_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ai_reply") is not None
        assert not data["ai_reply"].get("slots"), (
            f"Billing message should NOT return slots. Got: {data['ai_reply'].get('slots')}"
        )

    def test_book_creates_requested_job_and_clears_slots(self, customer_token):
        slot = getattr(pytest, "first_slot", None)
        assert slot is not None, "Need a slot from prior test"
        r = requests.post(
            f"{API}/me/book",
            json={"date": slot["date"], "label": slot["label"]},
            headers=_h(customer_token),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        confirm = r.json().get("message")
        assert confirm and confirm.get("ai") is True
        assert "requested" in confirm["text"].lower() or "✅" in confirm["text"]

        # Verify: job with status='requested' exists for this customer
        env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
        client = MongoClient(env["MONGO_URL"])
        db = client[env["DB_NAME"]]
        jobs = list(db.jobs.find({"customer_id": CUSTOMER_ID, "status": "requested", "title": "Service Request"}))
        assert len(jobs) >= 1, "Booking should create a 'requested' job"
        # Verify slots cleared on all customer messages
        remaining = db.messages.count_documents({"customer_id": CUSTOMER_ID, "slots": {"$exists": True}})
        client.close()
        assert remaining == 0, f"All slot buttons should be cleared, found {remaining}"

    def test_booked_job_visible_to_admin_schedule(self, admin_token):
        r = requests.get(f"{API}/jobs", headers=_h(admin_token), timeout=15)
        assert r.status_code == 200
        found = [j for j in r.json() if j.get("customer_id") == CUSTOMER_ID and j.get("status") == "requested"]
        assert len(found) >= 1


# ---------- 2) AI pause per conversation ----------
class TestAIPauseToggle:
    def test_thread_returns_ai_paused_field(self, admin_token):
        r = requests.get(f"{API}/communications/{CUSTOMER_ID}", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        assert "ai_paused" in r.json()

    def test_toggle_paused_and_no_ai_reply(self, admin_token, customer_token):
        # Pause
        r = requests.post(
            f"{API}/communications/{CUSTOMER_ID}/ai-toggle?paused=true",
            headers=_h(admin_token), timeout=10,
        )
        assert r.status_code == 200
        assert r.json().get("ai_paused") is True

        # Customer sends -> ai_reply should be None
        r2 = requests.post(
            f"{API}/me/messages",
            json={"text": "TESTMSG_are you there? schedule please"},
            headers=_h(customer_token), timeout=30,
        )
        assert r2.status_code == 200
        assert r2.json().get("ai_reply") is None, "AI must not reply when paused"

        # Thread now shows ai_paused=true
        r3 = requests.get(f"{API}/communications/{CUSTOMER_ID}", headers=_h(admin_token), timeout=10)
        assert r3.json().get("ai_paused") is True

    def test_resume_and_ai_replies_again(self, admin_token, customer_token):
        r = requests.post(
            f"{API}/communications/{CUSTOMER_ID}/ai-toggle?paused=false",
            headers=_h(admin_token), timeout=10,
        )
        assert r.status_code == 200
        assert r.json().get("ai_paused") is False

        r2 = requests.post(
            f"{API}/me/messages",
            json={"text": "TESTMSG_thanks, one more question about my pool"},
            headers=_h(customer_token), timeout=30,
        )
        assert r2.status_code == 200
        assert r2.json().get("ai_reply") is not None, "AI should reply once resumed"
        # Non-scheduling message -> no slots
        assert not r2.json()["ai_reply"].get("slots")

    def test_admin_manual_reply_still_works(self, admin_token):
        r = requests.post(
            f"{API}/communications/{CUSTOMER_ID}/reply",
            json={"text": "TESTMSG_admin manual reply"},
            headers=_h(admin_token), timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("sender") == "business"
        assert body.get("ai") is not True  # human reply, not AI
