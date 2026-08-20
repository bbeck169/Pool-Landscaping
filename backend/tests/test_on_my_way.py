"""Feb-2026 · Phase 1 — Tech "On my way" SMS endpoint tests.

Covers the seven acceptance criteria in the spec:
    1. Happy path WITH ETA (Directions API mocked)
    2. Happy path WITHOUT ETA (no coords sent → message omits ETA sentence)
    3. Once-per-job-per-day guard
    4. Blocked customer → ``customer_blocked``
    5. ``sms_opt_in=false`` → ``sms_opt_in_false``
    6. Missing phone → ``no_phone``
    7. Role gate: portal/customer role → 403

Uses the live-backend HTTP pattern established in the sibling tests
(``test_add_card_magic_link.py``, ``test_portal_identity_isolation.py``).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from utils import hash_password


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend():
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


TENANT_ID = f"TEST_omw_{uuid.uuid4().hex[:6]}"
CUST_ID   = f"cust_omw_{uuid.uuid4().hex[:6]}"
TECH_UID  = f"tech_omw_{uuid.uuid4().hex[:6]}"
JOB_ID    = f"job_omw_{uuid.uuid4().hex[:6]}"
PROP_ID   = f"prop_omw_{uuid.uuid4().hex[:6]}"
PORTAL_UID = f"portal_omw_{uuid.uuid4().hex[:6]}"
PORTAL_EMAIL = f"portal_{uuid.uuid4().hex[:6]}@omwtest.example.com"
TECH_EMAIL   = f"tech_{uuid.uuid4().hex[:6]}@omwtest.example.com"


def _seed(*, sms_opt_in: bool = True, blocked: bool = False,
            phone: str = "+15550001234"):
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": CUST_ID})
            await db.users.delete_many({"id": {"$in": [TECH_UID, PORTAL_UID]}})
            await db.jobs.delete_many({"id": JOB_ID})
            await db.properties.delete_many({"id": PROP_ID})
            await db.communications.delete_many({"job_id": JOB_ID})
            await db.tenants.insert_one({
                "id": TENANT_ID, "name": "OMW Test Co",
                "company_name": "OMW Test Co", "active": True,
            })
            await db.users.insert_many([
                {"id": TECH_UID, "tenant_id": TENANT_ID,
                 "name": "Mike Rivera", "first_name": "Mike",
                 "email": TECH_EMAIL,
                 "password_hash": hash_password("password123"),
                 "role": "technician", "active": True},
                {"id": PORTAL_UID, "tenant_id": TENANT_ID,
                 "name": "Portal Person", "email": PORTAL_EMAIL,
                 "password_hash": hash_password("password123"),
                 "role": "customer", "customer_id": CUST_ID, "active": True},
            ])
            cust = {
                "id": CUST_ID, "tenant_id": TENANT_ID,
                "name": "Jane Doe", "first_name": "Jane",
                "email": f"jane_{uuid.uuid4().hex[:4]}@omwtest.example.com",
                "phone": phone, "is_demo_account": True,
            }
            if not sms_opt_in:
                cust["sms_opt_in"] = False
            if blocked:
                cust["blocked"] = True
            await db.customers.insert_one(cust)
            await db.properties.insert_one({
                "id": PROP_ID, "tenant_id": TENANT_ID, "customer_id": CUST_ID,
                "address": {
                    "line1": "22 Vistancia Blvd", "city": "Peoria",
                    "state": "AZ", "postal_code": "85383",
                },
                "lat": 33.780, "lng": -112.309,
            })
            await db.jobs.insert_one({
                "id": JOB_ID, "tenant_id": TENANT_ID,
                "customer_id": CUST_ID, "property_id": PROP_ID,
                "technician_id": TECH_UID,
                "status": "scheduled",
            })
        finally:
            c.close()
    _run(_go())


def _cleanup():
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            await db.tenants.delete_many({"id": TENANT_ID})
            await db.customers.delete_many({"id": CUST_ID})
            await db.users.delete_many({"id": {"$in": [TECH_UID, PORTAL_UID]}})
            await db.jobs.delete_many({"id": JOB_ID})
            await db.properties.delete_many({"id": PROP_ID})
            await db.communications.delete_many({"job_id": JOB_ID})
        finally:
            c.close()
    _run(_go())


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def _post(job_id: str, tok: str, body):
    return requests.post(
        f"{API}/jobs/{job_id}/on-my-way",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": "application/json"},
        json=body, timeout=10,
    )


def _last_comm():
    async def _go():
        c = AsyncIOMotorClient(_ENV["MONGO_URL"])
        db = c[_ENV["DB_NAME"]]
        try:
            return await db.communications.find_one(
                {"job_id": JOB_ID, "template_key": "tech_on_my_way"},
                {"_id": 0},
            )
        finally:
            c.close()
    return _run(_go())


# ─── 1. happy path WITH ETA ─────────────────────────────────────────
def test_happy_path_with_eta():
    """The endpoint runs in a separate uvicorn process, so we can't
    monkeypatch the Directions client from the test process. Instead
    we assert the observable contract: when origin coords are
    supplied AND the property has geocoded coords, the endpoint
    returns a positive integer ETA (capped at 90) and the SMS body
    contains ``"about X minutes"``. This validates the render path
    end-to-end against the real Google Routes v2 client the
    production endpoint uses."""
    _seed()
    try:
        tok = _login(TECH_EMAIL)
        r = _post(JOB_ID, tok, {
            "origin_lat": 33.71, "origin_lng": -112.24,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent"] is True
        # Google Routes API is enabled on preview; expect a real
        # positive ETA within the 90-minute cap.
        eta = body["eta_minutes"]
        assert isinstance(eta, int) and 1 <= eta <= 90, f"unexpected eta={eta!r}"
        comm = _last_comm()
        assert comm is not None
        assert comm["template_key"] == "tech_on_my_way"
        assert "Mike"        in comm["body"]
        assert "OMW Test Co" in comm["body"]
        # Body includes the ETA sentence (any positive integer).
        assert "about" in comm["body"] and " minutes" in comm["body"]
        assert f"{eta} minutes" in comm["body"]
        assert "22 Vistancia Blvd" in comm["body"]
        assert "Reply STOP"  in comm["body"]
    finally:
        _cleanup()


# ─── 2. happy path WITHOUT ETA ──────────────────────────────────────
def test_happy_path_without_eta():
    _seed()
    try:
        tok = _login(TECH_EMAIL)
        r = _post(JOB_ID, tok, {})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["sent"] is True
        assert body["eta_minutes"] is None
        comm = _last_comm()
        assert comm is not None
        assert "minutes" not in comm["body"]
        assert "on my way to" in comm["body"]
    finally:
        _cleanup()


# ─── 3. once-per-job-per-day guard ──────────────────────────────────
def test_once_per_job_per_day_guard():
    _seed()
    try:
        tok = _login(TECH_EMAIL)
        r1 = _post(JOB_ID, tok, {})
        assert r1.json()["sent"] is True
        r2 = _post(JOB_ID, tok, {})
        assert r2.status_code == 200
        assert r2.json() == {"sent": False, "reason": "already_sent_today"}
        # No second communications row.
        async def _count():
            c = AsyncIOMotorClient(_ENV["MONGO_URL"])
            db = c[_ENV["DB_NAME"]]
            try:
                return await db.communications.count_documents(
                    {"job_id": JOB_ID, "template_key": "tech_on_my_way"}
                )
            finally:
                c.close()
        assert _run(_count()) == 1
    finally:
        _cleanup()


# ─── 4. blocked customer ────────────────────────────────────────────
def test_blocked_customer_short_circuits():
    _seed(blocked=True)
    try:
        tok = _login(TECH_EMAIL)
        r = _post(JOB_ID, tok, {})
        assert r.status_code == 200
        assert r.json() == {"sent": False, "reason": "customer_blocked"}
    finally:
        _cleanup()


# ─── 5. sms_opt_in=false ────────────────────────────────────────────
def test_sms_opt_in_false_short_circuits():
    _seed(sms_opt_in=False)
    try:
        tok = _login(TECH_EMAIL)
        r = _post(JOB_ID, tok, {})
        assert r.status_code == 200
        assert r.json() == {"sent": False, "reason": "sms_opt_in_false"}
    finally:
        _cleanup()


# ─── 6. missing phone ───────────────────────────────────────────────
def test_missing_phone_short_circuits():
    _seed(phone="")
    try:
        tok = _login(TECH_EMAIL)
        r = _post(JOB_ID, tok, {})
        assert r.status_code == 200
        assert r.json() == {"sent": False, "reason": "no_phone"}
    finally:
        _cleanup()


# ─── 7. role gate: portal customer → 403 ────────────────────────────
def test_portal_role_forbidden():
    _seed()
    try:
        tok = _login(PORTAL_EMAIL)
        r = _post(JOB_ID, tok, {})
        assert r.status_code == 403, r.text
    finally:
        _cleanup()
