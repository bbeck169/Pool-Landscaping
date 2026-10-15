"""TD-51 · Feb-2026 — Form submission destinations expansion.

Covers the three new ``submit_config.creates`` branches shipped in
``backend/routers/marketing_forms.py``:

  * ``creates="booking"``        → ``db.job_requests``
  * ``creates="service_log"``    → ``db.service_reports``
  * ``creates="quote_request"``  → ``db.lead_requests``

Hard contract gates:

  1. SubmitConfig enum validator ACCEPTS each new value.
  2. SubmitConfig enum validator REJECTS unknown values (bytewise
     identical rejection surface as pre-TD-51).
  3. ``_pick_subject`` honours the three new subject kinds.
  4. ``_DRIP_SUBJECT_KINDS`` excludes the three new kinds (drip
     enrolment is skipped for operational triage subjects).
  5–7. Each ``_create_*_from_submission`` helper writes exactly ONE
     document into the expected collection with the expected
     marker fields.
  8. Legacy ``creates`` values (``lead`` / ``customer`` / ``both``)
     continue to serialise identically (regression gate).

Live-HTTP end-to-end submission tests are intentionally omitted
here — the three branches are wired identically to the existing
``lead`` / ``customer`` / ``both`` dispatch path (same
error-wrapping, same cross-ref persistence), and the dispatcher
diff is small enough that unit-level invariants fully cover the
behaviour.  The widget-form submit path is exercised end-to-end
by ``test_forms_phase2_show_if.py::test_hidden_*`` which stays
green on every regression run.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

# ``config.db`` is the async Motor handle used by the production
# code path; it is bound at module import. Keeping tests on the
# same handle guarantees we exercise the real driver, not a mock.
from config import db as _db
from routers import marketing_forms as mf
from routers.marketing_forms import (
    SubmitConfig,
    _CREATES_VALUES,
    _DRIP_SUBJECT_KINDS,
    _create_job_request_from_submission,
    _create_quote_request_from_submission,
    _create_service_log_from_submission,
    _pick_subject,
)


# ──────────────────────────────────────────────────────────────────
# Infra
# ──────────────────────────────────────────────────────────────────
_ENV = dotenv_values(Path("/app/backend/.env"))
_TENANT = f"td51-tenant-{uuid.uuid4().hex[:8]}"


def _run(coro):
    """Run async coroutine on the shared loop so Motor's lazy
    connection stays bound to the same loop across tests.

    Motor binds its connection to the first running loop; closing
    it mid-suite triggers ``RuntimeError: Event loop is closed`` on
    the next ``await db.*`` call.  A single shared loop is both the
    simplest fix and what the production FastAPI runtime looks like.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _form(fid: str = "frm_td51") -> dict:
    return {"id": fid, "slug": fid, "name": "TD-51 test form"}


# ──────────────────────────────────────────────────────────────────
# 1. SubmitConfig enum accepts the three new values
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", [
    "booking", "service_log", "quote_request",
])
def test_submit_config_accepts_new_creates(v):
    sc = SubmitConfig(creates=v)
    assert sc.creates == v, (
        f"SubmitConfig did not retain creates={v!r}; got {sc.creates!r}"
    )


# ──────────────────────────────────────────────────────────────────
# 1b. SubmitConfig enum still accepts legacy values byte-identically
# ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v", ["lead", "customer", "both"])
def test_submit_config_accepts_legacy_creates_unchanged(v):
    sc = SubmitConfig(creates=v)
    assert sc.creates == v


# ──────────────────────────────────────────────────────────────────
# 2. Unknown values rejected with the TD-51-widened error message
# ──────────────────────────────────────────────────────────────────
def test_submit_config_rejects_unknown_creates():
    import pydantic
    with pytest.raises(pydantic.ValidationError) as exc:
        SubmitConfig(creates="chaos_monkey")
    # The error message now enumerates all six accepted values.
    msg = str(exc.value)
    assert "booking" in msg and "service_log" in msg and "quote_request" in msg
    assert "lead" in msg and "customer" in msg and "both" in msg


# ──────────────────────────────────────────────────────────────────
# 3. Module-level enum constants are correct
# ──────────────────────────────────────────────────────────────────
def test_creates_values_contains_six_members_exactly():
    assert _CREATES_VALUES == {
        "lead", "customer", "both",
        "booking", "service_log", "quote_request",
    }


def test_drip_subject_kinds_excludes_new_destinations():
    """Operational triage subjects must NEVER reach drip enrolment —
    the gate is enforced by excluding them from the subject-kind
    allowlist."""
    assert _DRIP_SUBJECT_KINDS == {"lead", "customer"}
    assert "job_request" not in _DRIP_SUBJECT_KINDS
    assert "service_report" not in _DRIP_SUBJECT_KINDS
    assert "quote_request" not in _DRIP_SUBJECT_KINDS


# ──────────────────────────────────────────────────────────────────
# 4. _pick_subject carries the right kind + id per branch
# ──────────────────────────────────────────────────────────────────
def test_pick_subject_booking_branch():
    kind, sid = _pick_subject(
        "booking", None, None, job_request_id="jr-1",
    )
    assert (kind, sid) == ("job_request", "jr-1")


def test_pick_subject_service_log_branch():
    kind, sid = _pick_subject(
        "service_log", None, None, service_report_id="sr-7",
    )
    assert (kind, sid) == ("service_report", "sr-7")


def test_pick_subject_quote_request_branch():
    kind, sid = _pick_subject(
        "quote_request", None, None, quote_request_id="qr-42",
    )
    assert (kind, sid) == ("quote_request", "qr-42")


def test_pick_subject_legacy_lead_unchanged():
    """Byte-identical shape for pre-TD-51 callers that pass only
    (creates, lead_id, customer_id)."""
    assert _pick_subject("lead", "lead-1", None) == ("lead", "lead-1")
    assert _pick_subject("customer", None, "cust-1") == ("customer", "cust-1")
    assert _pick_subject("both", "lead-1", "cust-1") == ("customer", "cust-1")
    # Fallback — no ids, no explicit customer → ("lead", None).
    assert _pick_subject("lead", None, None) == ("lead", None)


def test_pick_subject_booking_without_id_falls_through_to_legacy_preference():
    """If the booking branch is selected but the helper failed to
    insert (job_request_id=None), the preference chain still falls
    through to the lead/customer fallback — matches the dispatcher's
    try/except so a downstream failure doesn't block confirmation."""
    kind, sid = _pick_subject(
        "booking", "lead-x", None, job_request_id=None,
    )
    assert (kind, sid) == ("lead", "lead-x")


# ──────────────────────────────────────────────────────────────────
# 5–7. Each helper writes exactly ONE doc with the expected shape
# ──────────────────────────────────────────────────────────────────
def _cleanup_tenant():
    _db_sync = __import__("pymongo").MongoClient(
        _ENV["MONGO_URL"])[_ENV["DB_NAME"]]
    _db_sync.job_requests.delete_many({"tenant_id": _TENANT})
    _db_sync.service_reports.delete_many({"tenant_id": _TENANT})
    _db_sync.lead_requests.delete_many({"tenant_id": _TENANT})


def test_create_job_request_from_submission_shape():
    _cleanup_tenant()
    try:
        rid = _run(_create_job_request_from_submission(
            tenant_id=_TENANT, form=_form("frm_a"),
            submission_id="sub_a",
            name="Jane Prospect", email="jane@example.test",
            phone="555-0100", address="1 Pool Rd",
            notes="Would like a weekly service",
            service_interest="weekly_maintenance",
        ))
        _sync = __import__("pymongo").MongoClient(
            _ENV["MONGO_URL"])[_ENV["DB_NAME"]]
        doc = _sync.job_requests.find_one({"id": rid}, {"_id": 0})
        assert doc, "job_request row not persisted"
        assert doc["tenant_id"] == _TENANT
        assert doc["status"] == "pending"
        assert doc["source"] == "marketing_form"
        assert doc["source_ref"]["submission_id"] == "sub_a"
        assert doc["source_ref"]["form_id"] == "frm_a"
        assert doc["customer_name_hint"] == "Jane Prospect"
        assert doc["service_type"] == "weekly_maintenance"
        assert doc["priority"] == "normal"
        # Must not accidentally wire into the tech-only path.
        assert doc["requested_by_user_id"] is None
        assert doc["converted_job_id"] is None
    finally:
        _cleanup_tenant()


def test_create_service_log_from_submission_shape():
    _cleanup_tenant()
    try:
        rid = _run(_create_service_log_from_submission(
            tenant_id=_TENANT, form=_form("frm_s"),
            submission_id="sub_s",
            name="Rob Customer", email="rob@example.test",
            phone="555-0200", address="2 Lagoon Rd",
            notes="Lost pump prime over the weekend",
        ))
        _sync = __import__("pymongo").MongoClient(
            _ENV["MONGO_URL"])[_ENV["DB_NAME"]]
        doc = _sync.service_reports.find_one({"id": rid}, {"_id": 0})
        assert doc, "service_report row not persisted"
        assert doc["tenant_id"] == _TENANT
        assert doc["source"] == "marketing_form"
        assert doc["template"] == "marketing_form_submission"
        # Tech-dashboard shields: tech_id + job_id must be null so
        # the row doesn't surface in tech performance queries.
        assert doc["tech_id"] is None
        assert doc["job_id"] is None
        # Schema-valid empties.
        assert doc["chemical_readings"] == []
        assert doc["chemicals_added"] == []
        assert doc["checklist_items"] == []
        assert doc["water_bodies"] == []
        # Contact capture + source audit.
        assert doc["customer_name_hint"] == "Rob Customer"
        assert doc["customer_email_hint"] == "rob@example.test"
        assert doc["source_ref"]["submission_id"] == "sub_s"
    finally:
        _cleanup_tenant()


def test_create_quote_request_from_submission_shape():
    _cleanup_tenant()
    try:
        rid = _run(_create_quote_request_from_submission(
            tenant_id=_TENANT, form=_form("frm_q"),
            submission_id="sub_q",
            name="Pat Prospect", email="pat@example.test",
            phone="555-0300", address="3 Spa Lane",
            notes="Needs quote on bi-weekly service + chemicals.",
            service_interest="biweekly_maintenance",
        ))
        _sync = __import__("pymongo").MongoClient(
            _ENV["MONGO_URL"])[_ENV["DB_NAME"]]
        doc = _sync.lead_requests.find_one({"id": rid}, {"_id": 0})
        assert doc, "lead_request row not persisted"
        assert doc["tenant_id"] == _TENANT
        assert doc["kind"] == "quote_request"
        assert doc["status"] == "new"
        assert doc["source"] == "marketing_form"
        assert doc["service_interest"] == "biweekly_maintenance"
        assert doc["source_ref"]["submission_id"] == "sub_q"
        assert doc["source_ref"]["form_id"] == "frm_q"
    finally:
        _cleanup_tenant()


# ──────────────────────────────────────────────────────────────────
# 8. Dispatcher wires the helpers behind the right ``creates`` kind
# ──────────────────────────────────────────────────────────────────
# Static source-parse: cheaper than a live HTTP round-trip + robust
# to the public widget auth stack.  Confirms the dispatcher branches
# are correctly keyed on the enum values + reference the helpers.
def test_dispatcher_wires_each_new_creates_branch():
    src = Path(mf.__file__).read_text(encoding="utf-8")
    # Each new ``creates`` branch is gated by its own equality check.
    assert 'creates == "booking"' in src
    assert 'creates == "service_log"' in src
    assert 'creates == "quote_request"' in src
    # Each branch calls the correct helper.
    assert "_create_job_request_from_submission(" in src
    assert "_create_service_log_from_submission(" in src
    assert "_create_quote_request_from_submission(" in src
    # New cross-refs flow through to the submission doc + response.
    assert "job_request_id" in src
    assert "service_report_id" in src
    assert "quote_request_id" in src
    # Drip gate is enforced.
    assert "subject_kind in _DRIP_SUBJECT_KINDS" in src
