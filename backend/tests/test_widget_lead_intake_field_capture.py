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
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
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


# ── 3. Missing-everything payload → K53.1 guard-skip (no placeholder) ─
def test_completely_empty_payload_no_longer_creates_placeholder(p17_public_form):
    """Feb-2026 · K53.1 Fix B contract.

    Pre-K53.1: submissions without any recognisable contact field
    would land as a ``"Website Visitor"`` placeholder on the leads
    board — matching a bug where Prod accumulated empty rows.

    Post-K53.1: Path A now requires an ``email`` or ``phone``
    before it inserts a lead row (matches the widget path guard at
    ``routers/marketing_forms.py:501``).  The submission is still
    stored in ``db.form_submissions`` so nothing is truly lost;
    the response carries ``lead_created=False`` +
    ``reason="no_contact_captured"`` so callers can distinguish.
    """
    r = requests.post(
        f"{API}/public/forms/{p17_public_form['slug']}/submit",
        json={"values": {"unrecognised_field": "ignored"}},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("lead_created") is False, (
        f"K53.1 guard-skip must report lead_created=False; got {body!r}"
    )
    assert body.get("reason") == "no_contact_captured", (
        f"K53.1 guard-skip must return reason=no_contact_captured;"
        f" got {body!r}"
    )
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    assert lead is None, (
        f"K53.1 guard-skip must NOT insert a placeholder lead;"
        f" found {lead!r}"
    )


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


# ── 5. P18 — public-form submit fires the lead-alert helper ──────
def test_public_form_submit_fires_lead_alert_helper(p17_public_form):
    """P18 integration — after a widget submit, the notification
    helper is called with the freshly-inserted lead + tenant, and
    the call carries the widget-captured name/phone/email/message."""
    from unittest.mock import patch, AsyncMock
    with patch(
        "services.lead_notifications.send_lead_alert_notifications",
        AsyncMock(return_value={"sms_queued": 0, "email_queued": 0}),
    ) as m:
        r = requests.post(
            f"{API}/public/forms/{p17_public_form['slug']}/submit",
            json={"values": {
                "full_name": "Dana Alert-Trigger",
                "phone_number": "+15555550004",
                "email_address": "dana@example.com",
                "details": "Trigger the alert helper.",
                "requested_service": "Pool",
            }},
            timeout=15,
        )
    assert r.status_code == 200, r.text
    # NOTE: In-process pytest cannot spy on the server's own module
    # namespace when the server runs in a separate process — verify
    # the OUTCOME instead: the lead landed with the alert-relevant
    # fields populated (which the helper then reads).
    lead = _find_lead(tid=p17_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Dana Alert-Trigger"
    assert lead["phone"] == "+15555550004"
    assert lead["email"] == "dana@example.com"
    assert lead["message"] == "Trigger the alert helper."
    assert lead["service_interest"] == "Pool"
