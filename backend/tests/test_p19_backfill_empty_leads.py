"""Feb-2026 · P19 — backfill-script coverage.

Pins:
  1. Two empty leads + matching submissions with aliased field data
     land the correct fields on commit.
  2. Idempotency — a second run finds no candidates.
  3. Lead with no matching submission → skipped_no_submission.
  4. Lead with an EMPTY submission → skipped_no_new_data.
  5. Dry-run (default) writes nothing; --commit flips to writes.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from migrations.task_p19_backfill_empty_website_visitor_leads import backfill

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_empty_lead(*, tid: str, ts: datetime, source: str = "Lead") -> str:
    lid = f"p19-lead-{uuid.uuid4().hex[:8]}"
    _sync.leads.insert_one({
        "id": lid, "tenant_id": tid,
        "name": "Website Visitor",
        "phone": "", "email": "", "address": "",
        "source": source, "status": "new",
        "created_at": ts.isoformat(),
    })
    return lid


def _seed_submission(*, tid: str, ts: datetime, vals: dict) -> str:
    sid = f"p19-sub-{uuid.uuid4().hex[:8]}"
    _sync.form_submissions.insert_one({
        "id": sid, "tenant_id": tid,
        "form_id": "p19-form", "values": vals,
        "created_at": ts.isoformat(),
    })
    return sid


@pytest.fixture
def p19_env():
    tid = f"p19-t-{uuid.uuid4().hex[:8]}"
    yield {"tenant_id": tid}
    _sync.leads.delete_many({"tenant_id": tid})
    _sync.form_submissions.delete_many({"tenant_id": tid})


# ── 1. Happy path — 2 leads with aliased submissions get backfilled ─
def test_backfills_two_leads_with_aliased_submissions(p19_env):
    tid = p19_env["tenant_id"]
    t0 = datetime.now(timezone.utc)
    lid1 = _seed_empty_lead(tid=tid, ts=t0)
    _seed_submission(tid=tid, ts=t0 + timedelta(seconds=1), vals={
        "full_name": "Alice Backfill",
        "phone_number": "+15555550021",
        "email_address": "alice@example.com",
        "details": "Backfill me please.",
    })
    lid2 = _seed_empty_lead(tid=tid, ts=t0 + timedelta(minutes=1))
    _seed_submission(tid=tid, ts=t0 + timedelta(minutes=1, seconds=2), vals={
        "full_name": "Bob Backfill",
        "phone_number": "+15555550022",
        "requested_service": "Landscape",
    })
    stats = _run(backfill(commit=True))
    assert stats["backfilled"] >= 2
    l1 = _sync.leads.find_one({"id": lid1})
    l2 = _sync.leads.find_one({"id": lid2})
    assert l1["name"] == "Alice Backfill"
    assert l1["phone"] == "+15555550021"
    assert l1["email"] == "alice@example.com"
    assert l1["message"] == "Backfill me please."
    assert l2["name"] == "Bob Backfill"
    assert l2["phone"] == "+15555550022"
    assert l2["service_interest"] == "Landscape"


# ── 2. Idempotency — second run touches nothing ─────────────────
def test_second_run_is_a_no_op(p19_env):
    tid = p19_env["tenant_id"]
    t0 = datetime.now(timezone.utc)
    _seed_empty_lead(tid=tid, ts=t0)
    _seed_submission(tid=tid, ts=t0, vals={"full_name": "Idem"})
    _run(backfill(commit=True))
    stats2 = _run(backfill(commit=True))
    # After the first commit, no lead still carries the "Website
    # Visitor" name + empty contact combo — candidate set is empty.
    assert stats2["total_candidates"] == 0
    assert stats2["backfilled"] == 0


# ── 3. No matching submission → skipped_no_submission ───────────
def test_lead_with_no_matching_submission_is_skipped(p19_env):
    tid = p19_env["tenant_id"]
    t0 = datetime.now(timezone.utc)
    _seed_empty_lead(tid=tid, ts=t0)
    # Only THIS tenant's submission exists — far outside the ±5 min window.
    _seed_submission(tid=tid, ts=t0 - timedelta(hours=2),
                        vals={"full_name": "Too Old"})
    stats = _run(backfill(commit=True))
    tenant_candidates = _sync.leads.count_documents(
        {"tenant_id": tid, "name": "Website Visitor"})
    assert tenant_candidates == 1, "row must remain unmodified"
    assert stats["skipped_no_submission"] >= 1


# ── 4. Empty submission → skipped_no_new_data ───────────────────
def test_lead_with_empty_submission_is_skipped(p19_env):
    tid = p19_env["tenant_id"]
    t0 = datetime.now(timezone.utc)
    _seed_empty_lead(tid=tid, ts=t0)
    _seed_submission(tid=tid, ts=t0, vals={"unrecognised_field": "x"})
    stats = _run(backfill(commit=True))
    assert stats["skipped_no_new_data"] >= 1
    l = _sync.leads.find_one({"tenant_id": tid, "name": "Website Visitor"})
    assert l is not None, "row must remain unmodified"
    assert l["phone"] == ""


# ── 5. Dry-run writes nothing; --commit does ────────────────────
def test_dry_run_writes_nothing_but_reports_candidates(p19_env):
    tid = p19_env["tenant_id"]
    t0 = datetime.now(timezone.utc)
    _seed_empty_lead(tid=tid, ts=t0)
    _seed_submission(tid=tid, ts=t0,
                        vals={"full_name": "Dry", "phone_number": "+15555550099"})
    stats_dry = _run(backfill(commit=False))
    assert stats_dry["dry_run"] is True
    assert stats_dry["total_candidates"] >= 1
    # In dry-run, backfilled counter still ticks (planned writes) but
    # the DB row is unchanged.
    l_after_dry = _sync.leads.find_one({"tenant_id": tid})
    assert l_after_dry["name"] == "Website Visitor"
    assert l_after_dry["phone"] == ""
    # Now commit for real.
    stats_commit = _run(backfill(commit=True))
    assert stats_commit["dry_run"] is False
    l_after_commit = _sync.leads.find_one({"tenant_id": tid})
    assert l_after_commit["name"] == "Dry"
    assert l_after_commit["phone"] == "+15555550099"
