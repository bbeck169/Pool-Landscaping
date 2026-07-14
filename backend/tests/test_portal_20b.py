"""Phase 20B.1 — Portal chats + appointments + photos."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def customer_h(): return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_customer_h():
    try:
        return {"Authorization": f"Bearer {_login('customer@sunbelt.com')['access_token']}"}
    except Exception:
        pytest.skip("no sunbelt customer seeded")


# ─── 20B.1a · Portal Chats ─────────────────────────────────────────────
def test_portal_chat_flow_and_isolation(customer_h, admin_h, tech_h, dbc):
    # Customer creates + posts first message
    r = requests.post(f"{API}/portal/chats", headers=customer_h,
                      json={"subject": "Test 20B1a",
                            "first_message": "Hi, chlorine question"}, timeout=15)
    assert r.status_code == 200, r.text
    chat = r.json()
    cid = chat["id"]
    assert chat["subject"] == "Test 20B1a"

    # Customer lists → sees own
    lst = requests.get(f"{API}/portal/chats", headers=customer_h, timeout=15).json()
    assert any(c["id"] == cid for c in lst)

    # Admin lists → sees the chat (tenant-scoped)
    alist = requests.get(f"{API}/portal/chats", headers=admin_h, timeout=15).json()
    assert any(c["id"] == cid for c in alist)

    # Admin fetches messages
    m = requests.get(f"{API}/portal/chats/{cid}/messages", headers=admin_h, timeout=15).json()
    assert len(m["messages"]) == 1 and m["messages"][0]["sender_role"] == "customer"

    # Admin replies
    reply = requests.post(f"{API}/portal/chats/{cid}/messages", headers=admin_h,
                          json={"body": "Sure, happy to help"}, timeout=15)
    assert reply.status_code == 200
    assert reply.json()["sender_role"] == "admin"

    # Customer marks read
    rr = requests.post(f"{API}/portal/chats/{cid}/read", headers=customer_h, timeout=15)
    assert rr.status_code == 200

    # Tech gets 403 on portal chats
    tr = requests.get(f"{API}/portal/chats", headers=tech_h, timeout=15)
    assert tr.status_code == 403

    dbc.portal_chat_messages.delete_many({"chat_id": cid})
    dbc.portal_chats.delete_one({"id": cid})


def test_portal_chat_tenant_isolation(customer_h, sunbelt_customer_h, dbc):
    r = requests.post(f"{API}/portal/chats", headers=customer_h,
                      json={"subject": "Aqua only", "first_message": "hi"}, timeout=15).json()
    cid = r["id"]
    # Sunbelt customer cannot see or fetch this chat.
    lst = requests.get(f"{API}/portal/chats", headers=sunbelt_customer_h, timeout=15).json()
    assert all(c["id"] != cid for c in lst)
    fetch = requests.get(f"{API}/portal/chats/{cid}/messages",
                         headers=sunbelt_customer_h, timeout=15)
    assert fetch.status_code == 404

    dbc.portal_chat_messages.delete_many({"chat_id": cid})
    dbc.portal_chats.delete_one({"id": cid})


# ─── 20B.1b · Portal Appointments ──────────────────────────────────────
def test_portal_appointment_flow(customer_h, admin_h, tech_h, dbc):
    # Availability responds
    av = requests.get(f"{API}/portal/availability?date_range=7",
                      headers=customer_h, timeout=15).json()
    assert "windows" in av and len(av["windows"]) > 0
    win = next((w for w in av["windows"] if not w["full"]), av["windows"][0])

    # Customer books
    body = {"service_type": "Pool Cleaning", "preferred_date": win["date"],
            "preferred_window": win["window"], "notes": "test 20B1b"}
    ap = requests.post(f"{API}/portal/appointments", headers=customer_h,
                       json=body, timeout=15).json()
    assert ap["status"] == "pending"
    aid = ap["id"]

    # Tech is blocked from listing appointments
    tr = requests.get(f"{API}/portal/appointments", headers=tech_h, timeout=15)
    assert tr.status_code == 403

    # Admin confirms → job auto-created
    c = requests.post(f"{API}/portal/appointments/{aid}/confirm",
                      headers=admin_h, timeout=15).json()
    assert c["status"] == "confirmed" and c["job_id"]
    j = dbc.jobs.find_one({"id": c["job_id"]})
    assert j and j["source_appointment_id"] == aid

    # Second book → reject with reason
    ap2 = requests.post(f"{API}/portal/appointments", headers=customer_h,
                        json=body, timeout=15).json()
    r2 = requests.post(f"{API}/portal/appointments/{ap2['id']}/reject",
                       headers=admin_h,
                       json={"reason": "no availability that day"}, timeout=15)
    assert r2.status_code == 200

    dbc.portal_appointments.delete_many({"id": {"$in": [aid, ap2["id"]]}})
    dbc.jobs.delete_one({"id": c["job_id"]})


def test_portal_appointment_tenant_isolation(customer_h, sunbelt_customer_h, dbc):
    av = requests.get(f"{API}/portal/availability?date_range=7",
                      headers=customer_h, timeout=15).json()
    win = next((w for w in av["windows"] if not w["full"]), av["windows"][0])
    ap = requests.post(f"{API}/portal/appointments", headers=customer_h,
                      json={"service_type": "X", "preferred_date": win["date"],
                            "preferred_window": win["window"]}, timeout=15).json()
    # Sunbelt customer sees own list only, not the Aquaterra appt.
    sun_list = requests.get(f"{API}/portal/appointments",
                             headers=sunbelt_customer_h, timeout=15).json()
    assert all(a["id"] != ap["id"] for a in sun_list)
    dbc.portal_appointments.delete_one({"id": ap["id"]})


# ─── 20B.1c · Portal Photos ────────────────────────────────────────────
def test_portal_photos_scoped_to_customer(customer_h, admin_h, tech_h, dbc):
    # Seed a service report with 2 photos on a job owned by this customer.
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    cust = dbc.customers.find_one({"tenant_id": tenant["id"],
                                    "email": "customer@aquaterra.com"})
    if not cust:
        pytest.skip("customer@aquaterra.com not seeded as a customer")
    jid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    dbc.jobs.insert_one({"id": jid, "tenant_id": tenant["id"],
                          "customer_id": cust["id"], "title": "Photo Test Job",
                          "service_type": "Weekly Pool Service",
                          "scheduled_start": datetime.now(timezone.utc).isoformat(),
                          "status": "completed"})
    dbc.service_reports.insert_one({
        "id": rid, "tenant_id": tenant["id"], "job_id": jid,
        "photos": [{"url": "https://x.example/a.jpg", "caption": "before"},
                   {"url": "https://x.example/b.jpg", "caption": "after"}],
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })
    try:
        r = requests.get(f"{API}/portal/photos", headers=customer_h, timeout=15).json()
        urls = [p["url"] for p in r["photos"]]
        assert "https://x.example/a.jpg" in urls
        assert "https://x.example/b.jpg" in urls

        # Tech gets 403.
        tr = requests.get(f"{API}/portal/photos", headers=tech_h, timeout=15)
        assert tr.status_code == 403
        # Admin also cannot use customer-only endpoint → 403 too.
        ar = requests.get(f"{API}/portal/photos", headers=admin_h, timeout=15)
        assert ar.status_code == 403
    finally:
        dbc.service_reports.delete_one({"id": rid})
        dbc.jobs.delete_one({"id": jid})
