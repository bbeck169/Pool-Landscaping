"""Feb-2026 · P17 — widget/legacy public-form lead-intake field capture.

Prod symptom (``app.plofv.com/leads``): widget submissions were
landing as leads with EMPTY contact columns + a hardcoded
"Website Visitor" fallback name.  Root cause was the pre-P17
naive ``vals.get("phone", "")`` / ``vals.get("email", "")``
extraction in ``routers/marketing.py`` legacy endpoints — any form
whose fields used the common ``full_name`` / ``email_address`` /
``phone_number`` aliases silently dropped every field.

Pins:
  1. A payload using the CANONICAL keys (``name``, ``phone``,
     ``email``) round-trips onto the lead doc.
  2. A payload using COMMON ALIASES (``full_name``,
     ``phone_number``, ``email_address``) also round-trips —
     proving the extraction is now tolerant.
  3. ``message`` + ``service_interest`` are persisted so the drawer
     can render them.
  4. Legacy leads without the new fields still list-fetch cleanly
     (backward-compat for the 2 empty prod rows).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


@pytest.fixture
def p17_public_form():
    """Seed a published public form scoped to the aquaterra tenant."""
    tenant = _sync.tenants.find_one({"slug": "aquaterra"})
    assert tenant, "aquaterra tenant fixture missing"
    fid = f"p17-form-{uuid.uuid4().hex[:8]}"
    slug = f"p17-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    _sync.forms.insert_one({
        "id": fid, "tenant_id": tenant["id"],
        "slug": slug, "name": "P17 Test Form",
        "status": "published", "destination": "lead",
        "created_at": now,
    })
    yield {"form_id": fid, "slug": slug, "tenant_id": tenant["id"]}
    _sync.forms.delete_many({"id": fid})
    _sync.form_submissions.delete_many({"form_id": fid})
    _sync.leads.delete_many({"tenant_id": tenant["id"],
                              "source": "P17 Test Form"})


def _find_lead(*, tid: str) -> dict:
    """Fetch the most-recently-created P17 test lead for this tenant."""
    return _sync.leads.find_one(
        {"tenant_id": tid, "source": "P17 Test Form"},
        sort=[("created_at", -1)],
    )


# ── 1. Canonical field keys still work (pre-P17 happy path) ──────
def test_canonical_field_keys_land_on_lead(p17_public_form):
    r = requests.post(
        f"{API}/public/forms/{p17_public_form['slug']}/submit",
        json={"values": {
            "name": "Alice Canonical",
            "phone": "+15555550001",
            "email": "alice@example.com",
            "message": "Please quote weekly pool service.",
            "service_interest": "Pool",
            "address": "123 Canonical Ln",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Alice Canonical"
    assert lead["phone"] == "+15555550001"
    assert lead["email"] == "alice@example.com"
    assert lead["message"] == "Please quote weekly pool service."
    assert lead["service_interest"] == "Pool"
    assert lead["address"] == "123 Canonical Ln"


# ── 2. Common aliases now land (the pre-P17 silent-drop bug) ─────
def test_common_field_aliases_now_land_on_lead(p17_public_form):
    r = requests.post(
        f"{API}/public/forms/{p17_public_form['slug']}/submit",
        json={"values": {
            "full_name": "Bob Aliased",
            "phone_number": "+15555550002",
            "email_address": "bob@example.com",
            "details": "Alias-cased inquiry — pre-P17 this was DROPPED.",
            "requested_service": "Landscape",
            "street_address": "456 Alias Rd",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Bob Aliased", (
        f"``full_name`` alias must land on lead.name; got {lead['name']!r}"
    )
    assert lead["phone"] == "+15555550002"
    assert lead["email"] == "bob@example.com"
    assert lead["message"] == "Alias-cased inquiry — pre-P17 this was DROPPED."
    assert lead["service_interest"] == "Landscape"
    assert lead["address"] == "456 Alias Rd"


# ── 3. Missing-everything payload still creates a lead (backcompat) ──
def test_completely_empty_payload_still_creates_website_visitor(p17_public_form):
    """Pins the pre-P17 fallback: submissions with no recognisable
    contact field still land as a ``Website Visitor`` row — matches
    the 2 empty prod rows the user reported. Backward-compat: the
    drawer must not crash on these rows."""
    r = requests.post(
        f"{API}/public/forms/{p17_public_form['slug']}/submit",
        json={"values": {"unrecognised_field": "ignored"}},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Website Visitor"
    assert lead["phone"] == ""
    assert lead["email"] == ""
    assert lead["message"] == ""
    assert lead["service_interest"] is None


# ── 4. GET /api/leads/{id} exposes every new field ───────────────
def test_get_lead_by_id_exposes_message_and_service_interest(p17_public_form):
    r = requests.post(
        f"{API}/public/forms/{p17_public_form['slug']}/submit",
        json={"values": {
            "full_name": "Carol Round-Trip",
            "phone_number": "+15555550003",
            "message": "Round-trip test.",
            "requested_service": "Pool + Landscape",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    lid = lead["id"]

    # Read-path via the admin API — proves the drawer's fetch will
    # see every field the write path landed.
    from passlib.context import CryptContext  # noqa: F401  # already installed
    tok = requests.post(f"{API}/auth/login",
                          json={"email": "admin@aquaterra.com",
                                 "password": "password123"},
                          timeout=15).json()["access_token"]
    hdrs = {"Authorization": f"Bearer {tok}"}
    got = requests.get(f"{API}/leads/{lid}", headers=hdrs, timeout=15)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["message"] == "Round-trip test.", body
    assert body["service_interest"] == "Pool + Landscape", body
    assert body["phone"] == "+15555550003"
    assert body["name"] == "Carol Round-Trip"
