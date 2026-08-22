"""Feb-2026 · P27 — Mute/Unmute customer round-trip.

Six assertions covering the "silent-mode" contract:

  1. Mute happy path — admin can mute; tech + customer → 403; row now
     carries ``is_muted=True`` + ``muted_at`` + ``muted_by`` + flipped
     ``is_active=False``.
  2. Unmute permissions (P27 addendum) — admin AND super_admin can
     unmute; tech + customer → 403.
  3. Idempotent both ways — muting a muted row returns
     ``{muted: false, reason: "already_muted"}``; unmuting a live row
     returns ``{unmuted: false, reason: "not_muted"}``.
  4. Muted customer is excluded from ``customers?is_active=true``
     list queries (the primary marketing / drip audience selector).
  5. P18 lead alert is suppressed when a new lead's phone matches a
     muted customer in the same tenant.
  6. Audit-log entries land in ``audit_logs`` for both mute + unmute.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from fastapi import BackgroundTasks
from pymongo import MongoClient

from services.lead_notifications import send_lead_alert_notifications

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def super_h():
    return _hdrs("super@aquaterra.com")


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


def _seed_customer(tid: str, *, muted: bool = False,
                     phone: str = "6235550100",
                     email: str | None = None) -> str:
    cid = f"TEST_p27_c_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": tid,
        "name": f"TEST P27 {'(muted)' if muted else '(active)'}",
        "email": email or f"{cid}@example.com",
        "phone": phone,
        "is_active": True,
        "created_at": "2026-06-01T09:00:00+00:00",
    }
    if muted:
        doc["is_muted"] = True
        doc["is_active"] = False
        doc["muted_at"] = "2026-06-01T10:00:00+00:00"
    _sync.customers.insert_one(doc)
    return cid


def _cleanup(ids: list[str]) -> None:
    if ids:
        _sync.customers.delete_many({"id": {"$in": ids}})
        _sync.audit_logs.delete_many({"customer_id": {"$in": ids}})


# ─── 1. Mute happy path + RBAC ───────────────────────────────────────

def test_mute_happy_path_admin_ok_tech_403(admin_h, tech_h, aquaterra_tid):
    cid_a = _seed_customer(aquaterra_tid)
    cid_t = _seed_customer(aquaterra_tid)
    try:
        # Tech is blocked.
        r_t = requests.patch(f"{API}/customers/{cid_t}/mute",
                                headers=tech_h, timeout=15)
        assert r_t.status_code == 403, r_t.text
        body = r_t.json().get("detail") or {}
        assert body.get("detail") == "role_not_permitted"
        # Row untouched.
        assert not (_sync.customers.find_one({"id": cid_t}) or {}).get("is_muted")

        # Admin mutes.
        r = requests.patch(f"{API}/customers/{cid_a}/mute",
                              headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["muted"] is True
        assert body["customer_id"] == cid_a
        assert "muted_at" in body
        doc = _sync.customers.find_one({"id": cid_a}) or {}
        assert doc.get("is_muted") is True
        assert doc.get("is_active") is False
        assert doc.get("muted_at")
        assert doc.get("muted_by")
    finally:
        _cleanup([cid_a, cid_t])


# ─── 2. Unmute permissions (P27 addendum: admin OR super_admin) ─────

def test_unmute_permissions_admin_and_super_admin_ok_tech_403(
    super_h, admin_h, tech_h, aquaterra_tid,
):
    cid_a = _seed_customer(aquaterra_tid, muted=True)
    cid_s = _seed_customer(aquaterra_tid, muted=True)
    cid_t = _seed_customer(aquaterra_tid, muted=True)
    try:
        # Tech blocked.
        r_t = requests.patch(f"{API}/customers/{cid_t}/unmute",
                                headers=tech_h, timeout=15)
        assert r_t.status_code == 403, r_t.text
        assert (r_t.json().get("detail") or {}).get("detail") == "role_not_permitted"
        assert (_sync.customers.find_one({"id": cid_t}) or {}).get("is_muted") is True

        # Admin OK.
        r_a = requests.patch(f"{API}/customers/{cid_a}/unmute",
                                headers=admin_h, timeout=15)
        assert r_a.status_code == 200, r_a.text
        assert r_a.json()["unmuted"] is True
        doc = _sync.customers.find_one({"id": cid_a}) or {}
        assert "is_muted" not in doc or doc.get("is_muted") in (None, False, "")
        assert doc.get("is_active") is True

        # Super_admin OK.
        r_s = requests.patch(f"{API}/customers/{cid_s}/unmute",
                                headers=super_h, timeout=15)
        assert r_s.status_code == 200, r_s.text
        assert r_s.json()["unmuted"] is True
    finally:
        _cleanup([cid_a, cid_s, cid_t])


# ─── 3. Idempotent both ways ─────────────────────────────────────────

def test_mute_and_unmute_are_idempotent(admin_h, aquaterra_tid):
    cid_m = _seed_customer(aquaterra_tid, muted=True)
    cid_l = _seed_customer(aquaterra_tid, muted=False)
    try:
        # Mute on already-muted → {muted: false, already_muted}.
        r = requests.patch(f"{API}/customers/{cid_m}/mute",
                              headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["muted"] is False
        assert body["reason"] == "already_muted"

        # Unmute on non-muted → {unmuted: false, not_muted}.
        r2 = requests.patch(f"{API}/customers/{cid_l}/unmute",
                               headers=admin_h, timeout=15)
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["unmuted"] is False
        assert body2["reason"] == "not_muted"
    finally:
        _cleanup([cid_m, cid_l])


# ─── 4. Muted excluded from is_active=true audience ──────────────────

def test_muted_customer_excluded_from_active_list(admin_h, aquaterra_tid):
    live = _seed_customer(aquaterra_tid)
    muted = _seed_customer(aquaterra_tid, muted=True)
    try:
        r = requests.get(f"{API}/customers?is_active=true",
                            headers=admin_h, timeout=15)
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()}
        assert live in ids
        assert muted not in ids, \
            "muted customer must be excluded from is_active=true audience"
    finally:
        _cleanup([live, muted])


# ─── 5. P18 lead-alert suppression on muted-contact match ────────────

def test_lead_alert_suppressed_when_lead_phone_matches_muted_customer(
    aquaterra_tid,
):
    """Seed a muted customer; simulate a new lead capture where the
    inbound lead's phone matches the muted customer's phone in the
    same tenant.  ``send_lead_alert_notifications`` must skip fan-out
    and surface ``muted_suppressed_customer_id`` in the return."""
    muted_phone = "6235550190"
    muted_cid = _seed_customer(aquaterra_tid, muted=True,
                                  phone=muted_phone)
    try:
        tenant = {
            "id": aquaterra_tid,
            "lead_alert_sms_recipients": ["+16028874400"],
            "lead_alert_email_recipients": ["ops@aquaterra.com"],
        }
        lead = {
            "id": f"lead-p27-{uuid.uuid4().hex[:8]}",
            "name": "Muted Contact Trigger",
            "phone": muted_phone,
            "email": "trigger@example.com",
        }
        bg = BackgroundTasks()
        result = asyncio.get_event_loop().run_until_complete(
            send_lead_alert_notifications(
                lead=lead, tenant=tenant, background_tasks=bg,
            ),
        )
        assert result.get("muted_suppressed_customer_id") == muted_cid
        assert result["sms_queued"] == 0
        assert result["email_queued"] == 0
        assert len(bg.tasks) == 0, \
            "no fan-out tasks should have been queued"

        # Sanity: a lead from a non-muted contact does NOT suppress.
        lead2 = {**lead, "id": "lead-p27-clean", "phone": "+15558675309",
                    "email": "clean@example.com"}
        bg2 = BackgroundTasks()
        result2 = asyncio.get_event_loop().run_until_complete(
            send_lead_alert_notifications(
                lead=lead2, tenant=tenant, background_tasks=bg2,
            ),
        )
        assert result2.get("muted_suppressed_customer_id") is None
        assert result2["sms_queued"] == 1
        assert result2["email_queued"] == 1
    finally:
        _cleanup([muted_cid])


# ─── 6. Audit-log entries for mute + unmute ──────────────────────────

def test_audit_log_written_for_mute_and_unmute(admin_h, aquaterra_tid):
    cid = _seed_customer(aquaterra_tid)
    try:
        r1 = requests.patch(f"{API}/customers/{cid}/mute",
                               headers=admin_h, timeout=15)
        assert r1.status_code == 200, r1.text
        r2 = requests.patch(f"{API}/customers/{cid}/unmute",
                               headers=admin_h, timeout=15)
        assert r2.status_code == 200, r2.text

        # Wait briefly for async audit inserts.
        events: list[str] = []
        for _ in range(15):
            events = sorted(
                doc["event"]
                for doc in _sync.audit_logs.find(
                    {"customer_id": cid,
                      "event": {"$in": ["customer_mute", "customer_unmute"]}},
                )
            )
            if len(events) == 2:
                break
            time.sleep(0.05)
        assert events == ["customer_mute", "customer_unmute"], events

        mute_doc = _sync.audit_logs.find_one(
            {"event": "customer_mute", "customer_id": cid})
        assert mute_doc["tenant_id"] == aquaterra_tid
        assert mute_doc["actor_email"] == "admin@aquaterra.com"
        assert mute_doc["actor_role"] == "admin"
        assert mute_doc.get("created_at")
    finally:
        _cleanup([cid])
