"""Phase F5 · Feb-2026 — backfill must never overwrite an admin's
manually-typed value on a previously-empty lead."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.migrations import leads_backfill_from_form_submissions_v1 as mig
# Reuse the fakes from the dry-run suite.
from tests.test_lead_backfill_dry_run import (
    _FakeDb, _FakeColl, _match, _FakeCursor, _iso, _seed_lead_pair,
)


def test_prefilled_email_is_not_overwritten():
    """An admin manually typed an email on the empty "Website Visitor"
    row (perhaps from a phone call).  The backfill must NOT replace
    it with the form-submission's alternate email."""
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alt@example.com",
                              "phone": "555-2222"},
                     current_email="original@example.com",
                     current_phone="555-1111")
    r = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    updated = db.leads._rows[0]
    assert updated["email"] == "original@example.com", \
        "backfill overwrote a pre-typed email"
    assert updated["phone"] == "555-1111", \
        "backfill overwrote a pre-typed phone"
    # But it DID fill the still-blank fields.
    assert updated["name"] == "Alice Baker"
    assert updated["first_name"] == "Alice"
    assert updated["last_name"] == "Baker"


def test_admin_renamed_lead_is_not_touched_at_all():
    """If an admin renamed the lead away from the "Website Visitor"
    sentinel, the F5 search predicate no longer matches (name is
    non-sentinel AND non-empty), so the row is skipped ENTIRELY —
    we never guess about arbitrarily-named leads.  This matches
    the brief's ``name == 'Website Visitor' OR all-empty`` search
    contract."""
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com"},
                     current_name="Alice from Peoria (referral)")
    r = asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    # Zero candidates — the search predicate never returned this row.
    assert r["candidates_total"] == 0
    assert r["changed"] == 0
    # And the lead is untouched.
    updated = db.leads._rows[0]
    assert updated["name"] == "Alice from Peoria (referral)"
    assert updated.get("email", "") == ""
    assert updated.get("first_name", "") == ""


def test_whitespace_only_pre_typed_value_is_treated_as_blank():
    """Some admins type spaces to "clear" a field; we should treat
    that as blank and let the backfill fill from the submission."""
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com"},
                     current_email="   ")
    asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    updated = db.leads._rows[0]
    assert updated["email"] == "alice@example.com"


def test_website_visitor_sentinel_name_is_replaced():
    """The literal sentinel string ``"Website Visitor"`` is treated as
    blank so the backfill can overwrite it with a real name."""
    db = _FakeDb()
    now = datetime.now(timezone.utc)
    _seed_lead_pair(db, lead_id="L1", sub_id="S1", lead_created_at=_iso(now),
                     values={"first_name": "Alice", "last_name": "Baker",
                              "email": "alice@example.com"})
    asyncio.get_event_loop().run_until_complete(
        mig.apply_backfill(db, rate_limit_per_sec=0),
    )
    updated = db.leads._rows[0]
    assert updated["name"] == "Alice Baker"
