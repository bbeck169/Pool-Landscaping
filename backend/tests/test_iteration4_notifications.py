"""Iteration 4: Technician 'On My Way' + In-app customer notifications."""
import os
import pytest
import requests

BASE_URL = os.environ['EXPO_PUBLIC_BACKEND_URL'].rstrip('/')
API = f"{BASE_URL}/api"


def _login(session, email, password):
    r = session.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def admin_token():
    s = requests.Session()
    return _login(s, "admin@aquaterra.com", "password123")["access_token"]


@pytest.fixture(scope="module")
def tech_token():
    s = requests.Session()
    return _login(s, "mike@aquaterra.com", "password123")["access_token"]


@pytest.fixture(scope="module")
def customer_token():
    s = requests.Session()
    return _login(s, "customer@aquaterra.com", "password123")["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- helper: create fresh service request from Jennifer Carson ----------
def _fresh_request(customer_token, title):
    r = requests.post(
        f"{API}/service-requests",
        headers=_h(customer_token),
        json={"service_type": "Pool Cleaning", "title": title, "notes": "TEST_iter4"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Notifications scoping + read flow ----------
class TestNotificationsScoping:
    def test_read_all_baseline(self, customer_token):
        # Clear existing notifications so subsequent tests start clean
        r = requests.post(f"{API}/notifications/read-all", headers=_h(customer_token))
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_unread_count_zero_after_read_all(self, customer_token):
        r = requests.get(f"{API}/notifications/unread-count", headers=_h(customer_token))
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_list_notifications_shape(self, customer_token):
        r = requests.get(f"{API}/notifications", headers=_h(customer_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- PUT /jobs triggers all three notifications in one call ----------
class TestJobUpdateTriggersNotifications:
    def test_approve_assign_and_schedule_creates_three_notifications(
        self, customer_token, admin_token, tech_token
    ):
        # Baseline: mark existing customer notifications read
        requests.post(f"{API}/notifications/read-all", headers=_h(customer_token))

        # 1. Customer creates a fresh service request (status=requested)
        job = _fresh_request(customer_token, "TEST_Iter4_ApproveAssign")
        jid = job["id"]
        assert job["status"] == "requested"

        # 2. Get technician id (Mike)
        me_tech = requests.get(f"{API}/auth/me", headers=_h(tech_token)).json()
        tech_id = me_tech["technician_id"]
        assert tech_id

        # 3. Admin PUT — approve + assign + schedule in one call
        r = requests.put(
            f"{API}/jobs/{jid}",
            headers=_h(admin_token),
            json={"status": "pending", "technician_id": tech_id, "scheduled_date": "2026-02-01"},
        )
        assert r.status_code == 200, r.text
        updated = r.json()
        assert updated["status"] == "pending"
        assert updated["technician_id"] == tech_id
        assert updated["scheduled_date"] == "2026-02-01"

        # 4. Customer should now have 3 unread notifications
        cnt = requests.get(f"{API}/notifications/unread-count", headers=_h(customer_token)).json()["count"]
        assert cnt >= 3, f"expected >=3 unread notifications, got {cnt}"

        notifs = requests.get(f"{API}/notifications", headers=_h(customer_token)).json()
        # Find notifications tied to this job
        job_notifs = [n for n in notifs if n.get("job_id") == jid]
        titles = {n["title"] for n in job_notifs}
        assert "Request approved" in titles
        assert "Technician assigned" in titles
        assert "Service scheduled" in titles

        # Each notification must be scoped to this customer
        for n in job_notifs:
            assert n["read"] is False
            assert n["customer_id"] == job["customer_id"]

        # Stash for downstream on-my-way test
        pytest._iter4_job_id = jid
        pytest._iter4_tech_id = tech_id


# ---------- POST /jobs/{id}/on-my-way ----------
class TestOnMyWay:
    def test_customer_forbidden(self, customer_token):
        jid = getattr(pytest, "_iter4_job_id", None)
        assert jid, "prev test must have set job id"
        r = requests.post(f"{API}/jobs/{jid}/on-my-way", headers=_h(customer_token))
        assert r.status_code == 403

    def test_technician_not_assigned_forbidden(self, admin_token, customer_token):
        # Create a NEW job assigned to nobody (still requested) and try as tech
        job = _fresh_request(customer_token, "TEST_Iter4_UnassignedOMW")
        # Fresh service request has no technician_id → mike is not assigned
        s = requests.Session()
        tech_tok = _login(s, "mike@aquaterra.com", "password123")["access_token"]
        r = requests.post(f"{API}/jobs/{job['id']}/on-my-way", headers=_h(tech_tok))
        assert r.status_code == 403

    def test_assigned_technician_success_and_sms_noop(self, tech_token, customer_token):
        jid = getattr(pytest, "_iter4_job_id", None)
        assert jid
        # Mark all read so we can measure the new unread reliably
        requests.post(f"{API}/notifications/read-all", headers=_h(customer_token))

        r = requests.post(f"{API}/jobs/{jid}/on-my-way", headers=_h(tech_token))
        # Twilio env vars absent → must still return 200 (SMS silently no-ops)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["notified"] is True

        # Customer should see the new "Technician on the way" notification
        notifs = requests.get(f"{API}/notifications", headers=_h(customer_token)).json()
        matches = [n for n in notifs if n["job_id"] == jid and n["title"] == "Technician on the way"]
        assert len(matches) >= 1
        assert matches[0]["read"] is False

    def test_admin_can_trigger_on_my_way(self, admin_token, customer_token):
        jid = getattr(pytest, "_iter4_job_id", None)
        r = requests.post(f"{API}/jobs/{jid}/on-my-way", headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["notified"] is True

    def test_job_not_found(self, tech_token):
        r = requests.post(f"{API}/jobs/does-not-exist/on-my-way", headers=_h(tech_token))
        assert r.status_code == 404


# ---------- Cross-customer scoping ----------
class TestCrossCustomerScoping:
    def test_signup_new_customer_has_no_notifications(self):
        s = requests.Session()
        # unique email per run
        import time
        email = f"test_iter4_{int(time.time())}@example.com"
        r = s.post(
            f"{API}/auth/signup",
            json={"name": "TEST_Iter4 Cust B", "email": email, "password": "password123"},
        )
        assert r.status_code == 200, r.text
        tok_b = r.json()["access_token"]

        # Customer B should have zero notifications (isolated from Jennifer's)
        r = requests.get(f"{API}/notifications", headers=_h(tok_b))
        assert r.status_code == 200
        assert r.json() == []

        r = requests.get(f"{API}/notifications/unread-count", headers=_h(tok_b))
        assert r.status_code == 200
        assert r.json()["count"] == 0
