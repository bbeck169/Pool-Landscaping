"""Phase 39 · Step 2 · Visit Recap tests.

Covers:
1. Happy path with mocked Twilio + Resend → `sent:false` + per-channel
   `mocked:true, reason` populated for every requested channel.
2. Customer role → 403.
3. Missing all contact info → 400 with a clear message.
4. Every attempt (real or mocked) is logged to `visit_recaps_sent`.
5. Photo attachments capped at 3.
"""
import sys
from pathlib import Path

import asyncio
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def cust_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed(customer_email=None, customer_phone=None, photo_count=0):
    """Seed a customer + job + submitted service report. Returns
    `(sr_id, cid, job_id, cleanup)`. The cleanup function is idempotent
    and MUST be called from the test's `finally`."""
    async def _create():
        admin = await db.users.find_one({"email": "admin@aquaterra.com"}, {"_id": 0})
        tid = admin["tenant_id"]
        cid, jid, srid = new_id(), new_id(), new_id()
        cust = {"id": cid, "tenant_id": tid, "name": "Recap Test Customer",
                "address": "1 Recap Ln", "email": customer_email,
                "phone": customer_phone, "is_active": True,
                "created_at": now_iso()}
        await db.customers.insert_one(cust)
        job = {"id": jid, "tenant_id": tid, "customer_id": cid,
                "customer_name": cust["name"], "template": "pool",
                "service_type": "Pool Cleaning", "status": "completed",
                "scheduled_at": "2026-02-14T09:00:00Z",
                "created_at": now_iso()}
        await db.jobs.insert_one(job)
        photos = [{"url": f"https://example.com/photo{i}.jpg"}
                  for i in range(photo_count)]
        rep = {"id": srid, "tenant_id": tid, "job_id": jid,
                "tech_id": "test-tech", "submitted_at": now_iso(),
                "chemical_readings": [
                    {"key": "free_chlorine", "name": "Free Chlorine",
                     "unit": "ppm", "value": 2.1},
                    {"key": "ph", "name": "pH", "value": 7.4},
                ],
                "chemicals_added": [
                    {"chemical": "Chlorine Tablets", "quantity": 3,
                     "unit": "tabs", "raw_label": "3 Tabs"},
                    {"chemical": "Liquid Chlorine", "quantity": 0.25,
                     "unit": "gal", "raw_label": "1/4 Gallon"},
                ],
                "photos": photos}
        await db.service_reports.insert_one(rep)
        return tid, cid, jid, srid
    tid, cid, jid, srid = _run(_create())

    def cleanup():
        async def _rm():
            await db.customers.delete_one({"id": cid})
            await db.jobs.delete_one({"id": jid})
            await db.service_reports.delete_one({"id": srid})
            await db.visit_recaps_sent.delete_many({"service_report_id": srid})
        _run(_rm())
    return srid, cid, jid, cleanup


def test_happy_path_both_channels_mocked(admin_h):
    srid, cid, jid, cleanup = _seed(
        customer_email="recap@example.com", customer_phone="+15551234567")
    try:
        r = requests.post(f"{API}/service-reports/{srid}/send-recap",
                          headers=admin_h, timeout=15,
                          json={"channel": "both", "include_photos": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["channel"] == "both"
        # Both channels should be present in results and both mocked (no
        # Twilio + no Resend keys in the test env).
        assert "sms" in body["results"] and "email" in body["results"]
        assert body["results"]["sms"]["mocked"] is True
        assert body["results"]["sms"]["reason"]
        assert body["results"]["email"]["mocked"] is True
        assert body["results"]["email"]["reason"]
        assert body["sent"] is False
        assert set(body["mocked_channels"]) == {"sms", "email"}

        # Log written.
        async def _fetch_log():
            return await db.visit_recaps_sent.find_one(
                {"service_report_id": srid}, {"_id": 0})
        log = _run(_fetch_log())
        assert log is not None
        assert log["channel"] == "both"
        assert set(log["mocked_channels"]) == {"sms", "email"}
        assert log["actor_user_id"]
    finally:
        cleanup()


def test_rbac_customer_denied(cust_h):
    """Customer role can't hit send-recap."""
    srid, cid, jid, cleanup = _seed(
        customer_email="anyone@example.com", customer_phone=None)
    try:
        r = requests.post(f"{API}/service-reports/{srid}/send-recap",
                          headers=cust_h, timeout=10,
                          json={"channel": "email"})
        assert r.status_code == 403, r.text
    finally:
        cleanup()


def test_no_contact_info_returns_400(admin_h):
    srid, cid, jid, cleanup = _seed(customer_email=None, customer_phone=None)
    try:
        r = requests.post(f"{API}/service-reports/{srid}/send-recap",
                          headers=admin_h, timeout=10,
                          json={"channel": "both"})
        assert r.status_code == 400, r.text
        assert "phone" in r.json().get("detail", "").lower()
    finally:
        cleanup()


def test_photo_attach_cap_at_3(admin_h):
    """Report has 5 photos → recap payload counts only 3."""
    srid, cid, jid, cleanup = _seed(
        customer_email="cap@example.com", photo_count=5)
    try:
        r = requests.post(f"{API}/service-reports/{srid}/send-recap",
                          headers=admin_h, timeout=15,
                          json={"channel": "email", "include_photos": True})
        assert r.status_code == 200
        body = r.json()
        assert body.get("photo_count") == 3
    finally:
        cleanup()


def test_log_written_on_mocked(admin_h):
    """Every attempt — even fully mocked — must produce a log row."""
    srid, cid, jid, cleanup = _seed(customer_email="log@example.com")
    try:
        requests.post(f"{API}/service-reports/{srid}/send-recap",
                       headers=admin_h, timeout=10,
                       json={"channel": "email", "include_photos": False})
        async def _count():
            return await db.visit_recaps_sent.count_documents(
                {"service_report_id": srid})
        assert _run(_count()) == 1
    finally:
        cleanup()
