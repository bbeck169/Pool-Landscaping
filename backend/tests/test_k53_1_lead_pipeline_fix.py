"""Feb-2026 · K53.1 — Path A alias-widening + guard-skip contract.

Ships alongside ``services/lead_extraction.py``'s widened alias
tables and ``routers/marketing.py``'s new ``(email or phone)``
guard.  See ``/app/memory/PHASE_K53_LEADS_PIPELINE_DIAGNOSIS.md``
and ``/app/memory/PHASE_K53_1_LEAD_PIPELINE_FIX.md`` for context.

Pins:
  1. Path A submissions using the K53.1 new aliases
     (``your_email``, ``cell_phone_number``, ``home_address``,
     ``how_can_we_help``, ``customer_name``) round-trip onto the
     lead doc — no ``"Website Visitor"`` placeholder.
  2. Path A submissions with an unmatched ``name`` field but a
     valid ``email`` OR ``phone`` still create a real lead
     (name fell back to the sentinel is fine — contact fields
     land correctly).
  3. Path A submissions with NEITHER email NOR phone are
     guard-skipped: submission stored, no lead created,
     response ``lead_created=False`` + ``reason=no_contact_captured``.
  4. ``submission_id`` is persisted on the lead doc so the
     "trace back to raw submission" audit is possible.
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
def k531_public_form():
    """Seed a K53.1 test form scoped to the aquaterra tenant."""
    tenant = _sync.tenants.find_one({"slug": "aquaterra"})
    assert tenant, "aquaterra tenant fixture missing"
    fid = f"k531-form-{uuid.uuid4().hex[:8]}"
    slug = f"k531-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    _sync.forms.insert_one({
        "id": fid, "tenant_id": tenant["id"],
        "slug": slug, "name": "K531 Test Form",
        "status": "published", "destination": "lead",
        "created_at": now,
    })
    yield {"form_id": fid, "slug": slug, "tenant_id": tenant["id"]}
    _sync.forms.delete_many({"id": fid})
    _sync.form_submissions.delete_many({"form_id": fid})
    _sync.leads.delete_many({
        "tenant_id": tenant["id"], "source": "K531 Test Form",
    })


def _latest_lead(*, tid: str) -> dict | None:
    return _sync.leads.find_one(
        {"tenant_id": tid, "source": "K531 Test Form"},
        sort=[("created_at", -1)],
    )


# ── 1. Widened aliases · tenant-authored labels land on the lead ────
def test_k531_your_email_cell_phone_customer_name_aliases(k531_public_form):
    """Common tenant labels (``customer_name`` / ``your_email`` /
    ``cell_phone_number`` / ``home_address`` / ``how_can_we_help``)
    must resolve via the K53.1 alias table."""
    r = requests.post(
        f"{API}/public/forms/{k531_public_form['slug']}/submit",
        json={"values": {
            "customer_name": "Chase K531",
            "your_email": "chase@example.com",
            "cell_phone_number": "+15555550031",
            "home_address": "789 Widened Way",
            "how_can_we_help": "K53.1 alias check — please quote a spring open.",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("lead_created", True) is not False, (
        f"K53.1 widened aliases must create a real lead;"
        f" got {body!r}"
    )
    # Feb-2026 · K53.2 — Path A happy-path response must explicitly
    # surface ``lead_created: True`` so callers can distinguish
    # created vs guard-skipped without also parsing the presence of
    # a lead row.  Matches Path B (``routers/marketing_forms``) shape.
    assert body.get("lead_created") is True, (
        f"K53.2 Path A happy-path must include lead_created=True;"
        f" got {body!r}"
    )
    lead = _latest_lead(tid=k531_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Chase K531", (
        f"``customer_name`` alias must land on lead.name; "
        f"got {lead['name']!r}"
    )
    assert lead["email"] == "chase@example.com", (
        f"``your_email`` alias must land on lead.email;"
        f" got {lead['email']!r}"
    )
    assert lead["phone"] == "+15555550031", (
        f"``cell_phone_number`` alias must land on lead.phone;"
        f" got {lead['phone']!r}"
    )
    assert lead["address"] == "789 Widened Way", (
        f"``home_address`` alias must land on lead.address;"
        f" got {lead['address']!r}"
    )
    assert lead["message"] == (
        "K53.1 alias check — please quote a spring open."
    ), (
        f"``how_can_we_help`` alias must land on lead.message;"
        f" got {lead['message']!r}"
    )
    assert lead.get("submission_id"), (
        "K53.1 lead insert must persist submission_id so the raw"
        " form_submissions row can be traced back."
    )


# ── 2. Guard-skip · no email + no phone → no lead created ──────────
def test_k531_no_contact_guard_skips_lead_insert(k531_public_form):
    """K53.1 Fix B: Path A must NOT insert a ``"Website Visitor"``
    placeholder when extraction yields neither email nor phone.

    Submission still lands in ``db.form_submissions``.  Response
    carries ``lead_created=False`` + ``reason=no_contact_captured``."""
    r = requests.post(
        f"{API}/public/forms/{k531_public_form['slug']}/submit",
        json={"values": {
            # A tenant-authored form where the visitor only left a
            # message and their name.  No contact channel captured
            # → guard-skip must fire.
            "customer_name": "Dana Guard",
            "how_can_we_help": "Just curious about pricing.",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("lead_created") is False, (
        f"K53.1 guard-skip must return lead_created=False;"
        f" got {body!r}"
    )
    assert body.get("reason") == "no_contact_captured", (
        f"K53.1 guard-skip must return reason=no_contact_captured;"
        f" got {body!r}"
    )
    lead = _latest_lead(tid=k531_public_form["tenant_id"])
    assert lead is None, (
        f"K53.1 guard-skip must NOT insert any lead row;"
        f" found {lead!r}"
    )
    # Submission still lands in form_submissions — it's the audit trail.
    subs = list(_sync.form_submissions.find({
        "form_id": k531_public_form["form_id"],
    }))
    assert any(
        s.get("values", {}).get("customer_name") == "Dana Guard"
        for s in subs
    ), (
        "K53.1 guard-skip must still write the raw submission to"
        " form_submissions — nothing is truly lost."
    )


# ── 3. Guard-allow · phone-only submission still creates lead ──────
def test_k531_phone_only_submission_creates_lead(k531_public_form):
    """Phone alone is sufficient to bypass the guard.  Matches the
    widget path's guard (``routers/marketing_forms.py:501`` — the
    original ``(email or phone)`` predicate)."""
    r = requests.post(
        f"{API}/public/forms/{k531_public_form['slug']}/submit",
        json={"values": {
            "your_phone": "+15555550032",
            "how_can_we_help": "Please call me back.",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("lead_created", True) is not False
    lead = _latest_lead(tid=k531_public_form["tenant_id"])
    assert lead is not None
    assert lead["phone"] == "+15555550032"
    assert lead["email"] == ""      # missing but not required
    # Name fell back to the sentinel; that's the intended contract.
    assert lead["name"] in ("Website Visitor",), (
        f"With no name field, name should fall back to the"
        f" WEBSITE_VISITOR_FALLBACK sentinel; got {lead['name']!r}"
    )
    assert lead["message"] == "Please call me back."


# ── 4. Fix A+ · raw human labels normalize into the alias table ────
def test_k531_raw_human_labels_normalize(k531_public_form):
    """Fix A+ — tenants who author form fields with a raw
    ``f.name = "Cell Phone"`` (title case, space) still land on
    the lead doc because ``extract_contact_fields`` normalizes the
    payload keys before running the alias lookup.

    Mirrors what the widget POSTs when the form-builder writes the
    field's ``name`` attribute as a human-readable label."""
    r = requests.post(
        f"{API}/public/forms/{k531_public_form['slug']}/submit",
        json={"values": {
            "Customer Name": "Ellie Raw",
            "Your Email": "ellie@example.com",
            "Cell Phone": "+15555550041",
            "Home Address": "42 Raw St",
            "How can we help?": "K53.1 Fix A+ raw-label normalization.",
        }},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("lead_created", True) is not False, (
        f"Fix A+ must accept raw human labels; got {body!r}"
    )
    lead = _latest_lead(tid=k531_public_form["tenant_id"])
    assert lead is not None
    assert lead["name"] == "Ellie Raw"
    assert lead["email"] == "ellie@example.com"
    assert lead["phone"] == "+15555550041"
    assert lead["address"] == "42 Raw St"
    assert lead["message"] == "K53.1 Fix A+ raw-label normalization."
