"""Phase L2.5 · Feb-2026 — live submit-handler wire-in contract.

Locks the schema-aware wire-in on the public-form submit path
(``POST /api/public/forms/{slug}/submit``):

* The submit handler uses ``extract_contact_fields_with_schema`` +
  ``lead_row_from_form_values_with_schema`` (not the bare pre-L2
  helpers).
* Auto-generated field ids (``field_9`` / ``field_Service
  Address_5``) with human-readable labels round-trip onto the lead
  doc — ``address`` populated from the "Service Address" label,
  ``notes`` populated from the "Description of Services Needed"
  label.
* The classic L2.5 anti-match bug — a "Service Address" label
  stomping ``service_interest`` — is captured.

Uses the same requests-based fixture pattern as
``test_k53_1_lead_pipeline_fix.py`` so we exercise the actual live
FastAPI stack (not a unit-level mock).
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
def l25_public_form():
    """Seed a form with the classic modern-widget shape: every
    contact field carries an auto-generated id + a human label.
    Scoped to the aquaterra tenant so we reuse the existing seed."""
    tenant = _sync.tenants.find_one({"slug": "aquaterra"})
    assert tenant, "aquaterra tenant fixture missing"
    fid = f"l25-form-{uuid.uuid4().hex[:8]}"
    slug = f"l25-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    _sync.forms.insert_one({
        "id": fid, "tenant_id": tenant["id"],
        "slug": slug, "name": "L2.5 Test Form",
        "status": "published", "destination": "lead",
        "fields": [
            {"id": "field_1",                 "label": "Full Name"},
            {"id": "field_2",                 "label": "Email"},
            {"id": "field_3",                 "label": "Phone"},
            {"id": "field_Service Address_5", "label": "Service Address"},
            {"id": "field_9",
             "label": "Description of Services Needed"},
        ],
        "created_at": now,
    })
    yield {"form_id": fid, "slug": slug, "tenant_id": tenant["id"]}
    _sync.forms.delete_many({"id": fid})
    _sync.form_submissions.delete_many({"form_id": fid})
    _sync.leads.delete_many({
        "tenant_id": tenant["id"], "source": "L2.5 Test Form",
    })


def _latest_lead(*, tid: str) -> dict | None:
    return _sync.leads.find_one(
        {"tenant_id": tid, "source": "L2.5 Test Form"},
        sort=[("created_at", -1)],
    )


# ─── (1) Wire-in proof: schema-aware helpers actually fire ──────
def test_l25_public_submit_hydrates_address_and_notes_via_labels(l25_public_form):
    """Values keyed by auto-generated field ids must land on the
    lead doc via label matching — proves the live handler swapped
    to ``extract_contact_fields_with_schema`` + the schema-aware
    row builder."""
    r = requests.post(
        f"{API}/public/forms/{l25_public_form['slug']}/submit",
        json={"values": {
            "field_1":                 "Jane L25",
            "field_2":                 "jane.l25@example.com",
            "field_3":                 "+15555550125",
            "field_Service Address_5": "42 Wallaby Way, Sydney",
            "field_9":
                "Weekly pool + spa; interested in Betta skimmer install.",
        }},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    assert body.get("ok") is True
    assert body.get("lead_created") is True

    lead = _latest_lead(tid=l25_public_form["tenant_id"])
    assert lead is not None, "no lead row was created"

    # Address label resolves to `address` + mirrored `service_address`.
    assert lead["address"] == "42 Wallaby Way, Sydney"
    assert lead["service_address"] == "42 Wallaby Way, Sydney"
    # Description label resolves to `notes` (mirrored from `message`
    # inside ``lead_row_from_form_values_with_schema``).
    assert lead["notes"] == (
        "Weekly pool + spa; interested in Betta skimmer install."
    )
    # Contact fields still resolve via the label branch too.
    assert lead["name"] == "Jane L25"
    assert lead["email"] == "jane.l25@example.com"
    assert lead["phone"] == "+15555550125"


# ─── (2) Anti-match: address label MUST NOT hijack service_interest ──
def test_l25_service_address_label_does_not_hijack_service_interest(l25_public_form):
    """The Service Address value must NEVER land on the lead's
    ``service_interest`` field.  This is the exact regression the
    Phase L2.5 anti-match table was added to prevent."""
    r = requests.post(
        f"{API}/public/forms/{l25_public_form['slug']}/submit",
        json={"values": {
            "field_1":                 "Rex L25",
            "field_2":                 "rex.l25@example.com",
            "field_3":                 "+15555550126",
            "field_Service Address_5": "999 Anti-Match Ave, Phoenix, AZ",
            "field_9":                 "Please quote a spring open.",
        }},
        timeout=15,
    )
    r.raise_for_status()
    lead = _latest_lead(tid=l25_public_form["tenant_id"])
    assert lead is not None
    # Positive assertion: address landed correctly.
    assert lead["address"] == "999 Anti-Match Ave, Phoenix, AZ"
    # Anti-match invariant: the address value must not appear on
    # any of the semantic-service fields.
    assert "Anti-Match Ave" not in (lead.get("service_interest") or "")
    assert "Anti-Match Ave" not in (lead.get("notes") or "")


# ─── (3) Explicit key still wins (precedence regression guard) ────
def test_l25_explicit_address_key_beats_service_address_label(l25_public_form):
    """Pre-L2 behaviour must be preserved: when the incoming payload
    has both a canonical key AND an auto-generated field id with a
    matching label, the canonical key wins."""
    r = requests.post(
        f"{API}/public/forms/{l25_public_form['slug']}/submit",
        json={"values": {
            "field_1":                 "Cass L25",
            "field_2":                 "cass.l25@example.com",
            "field_3":                 "+15555550127",
            # Explicit ``address`` key — should win.
            "address":                 "100 Main St · direct key",
            # Auto-generated Service Address field — should NOT win.
            "field_Service Address_5": "200 Backup Ave · label match losing",
            "field_9":                 "Winter closing please.",
        }},
        timeout=15,
    )
    r.raise_for_status()
    lead = _latest_lead(tid=l25_public_form["tenant_id"])
    assert lead is not None
    assert lead["address"] == "100 Main St · direct key"
    assert "Backup Ave" not in (lead["address"] or "")


# ─── (4) Handler source references the schema-aware helpers ──────
def test_marketing_router_source_uses_schema_aware_helpers():
    """Regression guard: nothing prevents a future refactor from
    accidentally reverting to the bare pre-L2 helpers.  Static-scan
    the live router source so this test fails loudly if that
    happens."""
    src = Path(__file__).resolve().parents[1] / "routers" / "marketing.py"
    body = src.read_text()
    # Both live submit handlers must import + call the L2 helpers.
    assert "extract_contact_fields_with_schema" in body, (
        "marketing.py no longer imports extract_contact_fields_with_schema"
    )
    assert "lead_row_from_form_values_with_schema" in body, (
        "marketing.py no longer imports lead_row_from_form_values_with_schema"
    )


def test_marketing_forms_router_source_uses_schema_aware_extractor():
    src = Path(__file__).resolve().parents[1] / "routers" / "marketing_forms.py"
    body = src.read_text()
    assert "extract_contact_fields_with_schema" in body, (
        "marketing_forms.py no longer imports extract_contact_fields_with_schema"
    )
