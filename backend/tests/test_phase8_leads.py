"""Phase 8 · Feb 2026 — Leads System Overhaul coverage.

Runs against the live backend. Covers:
  · Admin create → timeline entry recorded.
  · Public intake happy path + validation guards.
  · Public intake without either email OR phone → 400.
  · Public intake missing name → 400.
  · Close Won pipeline (create + merge branches + idempotency).
  · Close Lost validation (missing / short reason).
  · Status transition timeline recorded.
  · Add-note appends + timeline entry.
  · Archive filter default hides converted leads.
  · Role gates (technician + customer → 403).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
API = "http://localhost:8001/api"
# Phase 9 hotfix — public leads route now enforces an Origin allowlist.
# Aquaterra's ``widget_allowed_domains`` includes this preview URL, so
# every public-intake test must send a matching Origin header.
_OK_ORIGIN = "https://poolscape-audit.preview.emergentagent.com"
_ORIGIN_HDR = {"Origin": _OK_ORIGIN}

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[
        os.environ.get("DB_NAME", "aquaterra")
    ]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    return r.json()["access_token"]


def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _create_lead(tok: str, **overrides) -> Dict[str, Any]:
    payload = {
        "name": "Phase8 Test " + uuid.uuid4().hex[:6],
        "email": f"phase8-{uuid.uuid4().hex[:6]}@example.com",
        "phone": f"+1408555{uuid.uuid4().int % 10000:04d}",
        "service_interest": "Pool",
        "service_address": "1 Test Ln",
        "notes": "unit-test",
        "source": "admin_manual",
    }
    payload.update(overrides)
    r = requests.post(f"{API}/leads", headers=_hdr(tok),
                       json=payload, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup(lead_ids=(), customer_ids=()):
    async def _run_clean():
        db = _db()
        if lead_ids:
            await db.leads.delete_many({"id": {"$in": list(lead_ids)}})
        if customer_ids:
            for cid in customer_ids:
                await db.customers.delete_one({"id": cid})
                await db.marketing_deliveries.delete_many({
                    "trigger_entity.customer_id": cid,
                })
                await db.marketing_enrollments.delete_many({
                    "trigger_entity.customer_id": cid,
                })
    _run(_run_clean())


# ═══════════════════════════ Create ═════════════════════════════════
def test_admin_create_lead_writes_timeline():
    tok = _login("admin@aquaterra.com")
    lead = _create_lead(tok)
    assert lead["status"] == "New"
    assert lead["source"] == "admin_manual"
    assert lead["service_interest"] == "Pool"
    assert isinstance(lead.get("timeline"), list)
    assert len(lead["timeline"]) == 1
    assert lead["timeline"][0]["kind"] == "created"
    _cleanup(lead_ids=[lead["id"]])


def test_admin_create_requires_name():
    tok = _login("admin@aquaterra.com")
    r = requests.post(f"{API}/leads", headers=_hdr(tok),
                       json={"name": "", "email": "x@y.com"}, timeout=15)
    assert r.status_code == 400


def test_admin_create_requires_email_or_phone():
    tok = _login("admin@aquaterra.com")
    r = requests.post(f"{API}/leads", headers=_hdr(tok),
                       json={"name": "no-contact"}, timeout=15)
    assert r.status_code == 400


# ═══════════════════════════ Public intake ══════════════════════════
def test_public_intake_happy_path():
    r = requests.post(f"{API}/public/leads", json={
        "name": "Public Prospect", "email": f"pub-{uuid.uuid4().hex[:6]}@example.com",
        "service_interest": "Landscape", "notes": "from website",
    }, headers=_ORIGIN_HDR, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert "lead_id" in j
    async def _check():
        db = _db()
        row = await db.leads.find_one({"id": j["lead_id"]}, {"_id": 0})
        return row
    row = _run(_check())
    assert row["source"] == "website_form"
    assert set(j.keys()) == {"ok", "lead_id"}
    _cleanup(lead_ids=[j["lead_id"]])


def test_public_intake_missing_name():
    r = requests.post(f"{API}/public/leads",
                       json={"email": "x@y.com"},
                       headers=_ORIGIN_HDR, timeout=15)
    assert r.status_code in (400, 422)


def test_public_intake_missing_email_and_phone():
    r = requests.post(f"{API}/public/leads",
                       json={"name": "Nobody"},
                       headers=_ORIGIN_HDR, timeout=15)
    assert r.status_code == 400


# ═══════════════════════════ Phase 9 hotfix — Origin allowlist ═══════
def test_public_intake_missing_origin_denied():
    """Phase 9 hotfix — no Origin header at all → 403."""
    r = requests.post(f"{API}/public/leads",
                       json={"name": "Sneaky", "email": "a@b.com"},
                       timeout=15)
    assert r.status_code == 403, r.text


def test_public_intake_disallowed_origin_denied():
    r = requests.post(f"{API}/public/leads",
                       json={"name": "Attacker", "email": "a@b.com"},
                       headers={"Origin": "https://evil.example.com"},
                       timeout=15)
    assert r.status_code == 403


def test_public_intake_referer_fallback_accepted():
    """Ingress that strips Origin but preserves Referer must still let
    a legitimate request through."""
    r = requests.post(f"{API}/public/leads",
                       json={"name": "Referer OK",
                              "email": f"ref-{uuid.uuid4().hex[:6]}@example.com"},
                       headers={"Referer": _OK_ORIGIN + "/public/leads"},
                       timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    _cleanup(lead_ids=[j["lead_id"]])


# ═══════════════════════════ Close Won — create branch ═══════════════
def test_close_won_creates_new_customer():
    tok = _login("admin@aquaterra.com")
    unique = uuid.uuid4().hex[:6]
    lead = _create_lead(tok, email=f"cw-new-{unique}@example.com",
                          phone=f"+1602555{uuid.uuid4().int % 10000:04d}")
    r = requests.post(f"{API}/leads/{lead['id']}/close-won",
                       headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["was_merged"] is False
    assert j["customer_id"]
    # All 3 notification ids should populate on a fresh conversion.
    n = j["notifications"]
    assert n["email"], "email delivery id missing"
    assert n["sms"], "sms delivery id missing"
    assert n["drip_enrollment_id"], "drip enrollment id missing"
    _cleanup(lead_ids=[lead["id"]], customer_ids=[j["customer_id"]])


# ═══════════════════════════ Close Won — merge by email ═════════════
def test_close_won_merges_by_email_and_fills_missing():
    tok = _login("admin@aquaterra.com")
    unique = uuid.uuid4().hex[:6]
    email = f"cw-merge-{unique}@example.com"
    # Seed an existing customer with partial data.
    async def _seed():
        db = _db()
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        cid = uuid.uuid4().hex
        await db.customers.insert_one({
            "id": cid, "tenant_id": tenant["id"],
            "name": "Existing Buyer", "email": email,
            "phone": "", "address": "",
        })
        return cid, tenant["id"]
    cid, _tid = _run(_seed())
    lead = _create_lead(tok, email=email,
                          phone="+16025557878",
                          service_address="99 New Ave",
                          notes="lead note to merge")
    r = requests.post(f"{API}/leads/{lead['id']}/close-won",
                       headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["was_merged"] is True
    assert j["customer_id"] == cid
    async def _verify():
        db = _db()
        c = await db.customers.find_one({"id": cid}, {"_id": 0})
        return c
    cust = _run(_verify())
    # Missing fields got filled from the lead.
    assert cust["phone"] == "+16025557878"
    assert cust["address"] == "99 New Ave"
    # Populated field was NOT overwritten.
    assert cust["name"] == "Existing Buyer"
    # Notes copied into customer timeline.
    assert any(ev.get("kind") == "note_from_lead"
                 for ev in (cust.get("timeline") or []))
    _cleanup(lead_ids=[lead["id"]], customer_ids=[cid])


# ═══════════════════════════ Close Won — idempotency ═════════════════
def test_close_won_is_idempotent():
    tok = _login("admin@aquaterra.com")
    unique = uuid.uuid4().hex[:6]
    lead = _create_lead(tok, email=f"cw-idem-{unique}@example.com")
    first = requests.post(f"{API}/leads/{lead['id']}/close-won",
                            headers=_hdr(tok), timeout=30).json()
    second = requests.post(f"{API}/leads/{lead['id']}/close-won",
                             headers=_hdr(tok), timeout=30).json()
    assert first["customer_id"] == second["customer_id"]
    assert second.get("idempotent") is True
    # Second call must NOT create new deliveries or drip enrollments.
    assert second["notifications"]["email"] is None
    assert second["notifications"]["sms"] is None
    assert second["notifications"]["drip_enrollment_id"] is None
    _cleanup(lead_ids=[lead["id"]], customer_ids=[first["customer_id"]])


# ═══════════════════════════ Close Lost validation ═══════════════════
def test_close_lost_requires_reason():
    tok = _login("admin@aquaterra.com")
    lead = _create_lead(tok)
    r = requests.post(f"{API}/leads/{lead['id']}/close-lost",
                       headers=_hdr(tok),
                       json={"loss_reason": ""}, timeout=15)
    assert r.status_code == 400
    r = requests.post(f"{API}/leads/{lead['id']}/close-lost",
                       headers=_hdr(tok),
                       json={"loss_reason": "hi"}, timeout=15)  # <3 chars
    assert r.status_code == 400
    r = requests.post(f"{API}/leads/{lead['id']}/close-lost",
                       headers=_hdr(tok),
                       json={"loss_reason": "Chose competitor"},
                       timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "Closed Lost"
    assert j["loss_reason"] == "Chose competitor"
    _cleanup(lead_ids=[lead["id"]])


# ═══════════════════════════ Status transitions timeline ═════════════
def test_status_transitions_recorded_in_timeline():
    tok = _login("admin@aquaterra.com")
    lead = _create_lead(tok)
    r = requests.patch(f"{API}/leads/{lead['id']}", headers=_hdr(tok),
                        json={"status": "Contacted"}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    events = [e for e in (j.get("timeline") or [])
                if e.get("kind") == "status_change"]
    assert events
    last = events[-1]
    assert last["payload"]["from"] == "New"
    assert last["payload"]["to"] == "Contacted"
    assert j.get("contacted_at")
    _cleanup(lead_ids=[lead["id"]])


# ═══════════════════════════ Note append ═════════════════════════════
def test_add_note_appends_and_writes_timeline():
    tok = _login("admin@aquaterra.com")
    lead = _create_lead(tok)
    r = requests.post(f"{API}/leads/{lead['id']}/note",
                       headers=_hdr(tok),
                       json={"text": "Called them, VM."}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "Called them, VM." in (j.get("notes") or "")
    kinds = [e.get("kind") for e in (j.get("timeline") or [])]
    assert "note_added" in kinds
    _cleanup(lead_ids=[lead["id"]])


# ═══════════════════════════ Archive default hides converted ═════════
def test_archived_leads_hidden_by_default_after_close_won():
    tok = _login("admin@aquaterra.com")
    unique = uuid.uuid4().hex[:6]
    lead = _create_lead(tok, name=f"Archive Sentinel {unique}",
                          email=f"arch-{unique}@example.com")
    resp = requests.post(f"{API}/leads/{lead['id']}/close-won",
                           headers=_hdr(tok), timeout=30).json()
    cid = resp["customer_id"]
    # Default listing shouldn't include archived leads.
    r = requests.get(f"{API}/leads?search={unique}",
                      headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert not any(row["id"] == lead["id"] for row in rows)
    # With include_archived=1 it must show up.
    r2 = requests.get(f"{API}/leads?search={unique}&include_archived=1",
                       headers=_hdr(tok), timeout=15)
    assert any(row["id"] == lead["id"] for row in r2.json()["rows"])
    _cleanup(lead_ids=[lead["id"]], customer_ids=[cid])


# ═══════════════════════════ Role gates ══════════════════════════════
def test_technician_cannot_list_leads():
    tok = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/leads", headers=_hdr(tok), timeout=15)
    assert r.status_code == 403


def test_customer_cannot_close_won():
    tok = _login("customer@aquaterra.com")
    r = requests.post(f"{API}/leads/nonexistent/close-won",
                       headers=_hdr(tok), timeout=15)
    assert r.status_code == 403


def test_manager_can_convert_leads():
    tok = _login("manager@aquaterra.com")
    lead = _create_lead(tok, email=f"mgr-{uuid.uuid4().hex[:6]}@example.com")
    r = requests.post(f"{API}/leads/{lead['id']}/close-won",
                       headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    _cleanup(lead_ids=[lead["id"]], customer_ids=[j["customer_id"]])
