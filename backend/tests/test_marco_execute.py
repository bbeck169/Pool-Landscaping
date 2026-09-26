"""MA1 · Feb-2026 — MARCO backend regression suite.

In-process, no live server, no LLM calls. Uses real Mongo for the DB
seed (matches the codebase's testing pattern) and monkeypatches
``services.marco.parser.call_llm_with_fallback`` so the LLM branch
is deterministic + offline.

Async execution uses the ``batch_safe_run`` helper from
``tests._phase34_asyncio`` — this rebuilds the Motor client on a
session-persistent event loop so we don't hit the "Future attached to
a different loop" gotcha that anyio-per-test raises. Same pattern as
the Phase-34 tenant-tasks suite.

Manual bash only per session mandate — no testing_agent.
Run::

    pytest backend/tests/test_marco_execute.py -xvs

17 test cases covering:
* Parser: LLM upstream error, malformed JSON, hallucinated action.
* Clock: tech happy path (in / out), admin + super_admin role
  short-circuit, day-scoped write (no ``job_id``), ``job_context``
  meta wired only on ``screen=job_detail``.
* add_line_item: fuzzy match happy (score ≥ 85), no-match friendly
  error, ambiguous top-2 candidates, invoice resolution from the
  ``service_report`` screen, "no invoice for job" friendly error.
* save_note: direct-by-id on ``service_report`` screen, attach-note
  flow on ``job_detail`` screen (single open SR), multi-open-SR
  picker branch, no-open-SR friendly error.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient


# Load ``backend/.env`` up-front so ``config.py`` sees ``MONGO_URL``
# on first import — matches the i17e chunk 2.c pattern.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from tests._phase34_asyncio import batch_safe_run as _run  # noqa: E402


# ═══ env / db ═════════════════════════════════════════════════════
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _BE.get("MONGO_URL")
_DB_NAME = _BE.get("DB_NAME")

TAG = "marco_"


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(_MONGO_URL)[_DB_NAME]


# ═══ user + tenant fixtures ═══════════════════════════════════════
@pytest.fixture
def tenant() -> Dict[str, Any]:
    return {"id": f"{TAG}tenant-{uuid.uuid4().hex[:8]}"}


def _user(role: str, tenant_id: str, *, is_tech: bool = False) -> Dict[str, Any]:
    uid = f"{TAG}u-{role}-{uuid.uuid4().hex[:6]}"
    doc: Dict[str, Any] = {
        "id": uid,
        "role": role,
        "tenant_id": tenant_id,
        "name": f"{TAG}{role.title()}",
        "email": f"{uid}@example.com",
    }
    if is_tech:
        doc["technician_id"] = uid
    return doc


@pytest.fixture
def tech_user(tenant):
    return _user("technician", tenant["id"], is_tech=True)


@pytest.fixture
def admin_user(tenant):
    return _user("admin", tenant["id"])


@pytest.fixture
def super_admin_user(tenant):
    return _user("super_admin", tenant["id"])


# ═══ scenario seed ════════════════════════════════════════════════
@pytest.fixture
def scenario(dbc, tenant):
    """Seed one job + one invoice linked to that job + one open
    service report + a pricebook with one distinct item and two
    near-duplicate items (for the ambiguous-match test). Cleaned up
    at the end of each test.
    """
    tid = tenant["id"]
    job_id = f"{TAG}job-{uuid.uuid4().hex[:8]}"
    invoice_id = f"{TAG}inv-{uuid.uuid4().hex[:8]}"
    sr_id = f"{TAG}sr-{uuid.uuid4().hex[:8]}"
    orphan_job_id = f"{TAG}orphan-job-{uuid.uuid4().hex[:8]}"  # no invoice
    item_distinct_id = f"{TAG}itemD-{uuid.uuid4().hex[:8]}"
    item_ambig_a_id = f"{TAG}itemAmA-{uuid.uuid4().hex[:8]}"
    item_ambig_b_id = f"{TAG}itemAmB-{uuid.uuid4().hex[:8]}"

    dbc.jobs.insert_many([
        {"id": job_id, "tenant_id": tid, "name": f"{TAG}Smith Pool"},
        {"id": orphan_job_id, "tenant_id": tid, "name": f"{TAG}Orphan Job"},
    ])
    dbc.quotes.insert_one({
        "id": invoice_id, "tenant_id": tid, "doc_type": "invoice",
        "status": "draft", "job_id": job_id,
        "line_items": [], "tax_rate": 0.0, "discount_amount": 0.0,
        "discount_type": "fixed", "amount_paid": 0.0,
        "subtotal": 0.0, "tax": 0.0, "total": 0.0,
        "discount_value": 0.0, "remaining_balance": 0.0,
        "deleted_at": None,
    })
    dbc.service_reports.insert_one({
        "id": sr_id, "tenant_id": tid, "job_id": job_id,
        "tech_id": None,
        "internal_notes": "", "submitted_at": None,
    })
    dbc.items.insert_many([
        {"id": item_distinct_id, "tenant_id": tid,
         "name": f"{TAG}Chlorine Tablets", "price": 25.5,
         "deleted_at": None},
        {"id": item_ambig_a_id, "tenant_id": tid,
         "name": f"{TAG}Alpha Sanitizer 3", "price": 30.0,
         "deleted_at": None},
        {"id": item_ambig_b_id, "tenant_id": tid,
         "name": f"{TAG}Alpha Sanitizer 4", "price": 32.0,
         "deleted_at": None},
    ])
    yield {
        "tenant_id": tid,
        "job_id": job_id,
        "invoice_id": invoice_id,
        "service_report_id": sr_id,
        "orphan_job_id": orphan_job_id,
        "item_distinct_id": item_distinct_id,
        "item_distinct_name": f"{TAG}Chlorine Tablets",
        "item_ambig_a_id": item_ambig_a_id,
        "item_ambig_b_id": item_ambig_b_id,
    }
    # ── teardown ─────────────────────────────────────────────────
    dbc.jobs.delete_many({"tenant_id": tid})
    dbc.quotes.delete_many({"tenant_id": tid})
    dbc.service_reports.delete_many({"tenant_id": tid})
    dbc.items.delete_many({"tenant_id": tid})
    dbc.timesheets.delete_many({"tenant_id": tid})
    dbc.service_report_notes_audit.delete_many({"tenant_id": tid})


# ═══ LLM mock helper ═════════════════════════════════════════════
def _stub_llm(monkeypatch, *, action: str,
                args: Dict[str, Any] | None = None,
                raw_override: str | None = None,
                error: str | None = None):
    """Install a fake ``call_llm_with_fallback`` on the parser module.

    Returns ``{"raw": <str>, "provider": "test"}`` or an error dict.
    Patching ``services.marco.parser.call_llm_with_fallback`` (not
    the source module) so the parser's ``from services.llm_provider
    import call_llm_with_fallback`` local binding is intercepted.
    """
    import json as _json
    import services.marco.parser as _parser

    async def _fake(**kwargs):
        if error is not None:
            return {"error": error, "provider": "test"}
        if raw_override is not None:
            return {"raw": raw_override, "provider": "test"}
        payload = _json.dumps({"action": action, "args": args or {}})
        return {"raw": payload, "provider": "test"}
    monkeypatch.setattr(_parser, "call_llm_with_fallback", _fake)


# ═══ 1. PARSER — LLM upstream error ═══════════════════════════════
def test_parser_llm_upstream_error_surfaces_as_error(monkeypatch):
    from services.marco.parser import parse_transcript
    _stub_llm(monkeypatch, action="", error="upstream_timeout")
    out = _run(parse_transcript(transcript="clock in", tenant_id="t"))
    assert out.get("error") == "llm_upstream_error"
    assert "upstream_timeout" in out.get("detail", "")


# ═══ 2. PARSER — malformed JSON ═══════════════════════════════════
def test_parser_llm_malformed_json_returns_parse_error(monkeypatch):
    from services.marco.parser import parse_transcript
    _stub_llm(monkeypatch, action="", raw_override="this-is-not-json{")
    out = _run(parse_transcript(transcript="clock in", tenant_id="t"))
    assert out.get("error") == "llm_parse_error"


# ═══ 3. PARSER — hallucinated action → parse_error ═══════════════
def test_parser_rejects_hallucinated_action(monkeypatch):
    from services.marco.parser import parse_transcript
    _stub_llm(monkeypatch, action="delete_customer")
    out = _run(parse_transcript(transcript="delete Bob", tenant_id="t"))
    assert out.get("error") == "llm_parse_error"


# ═══ 4. CLOCK — tech happy path (in) ═════════════════════════════
def test_clock_in_tech_happy(scenario, tech_user, tenant, dbc):
    from services.marco.actions import handle_clock_in
    out = _run(handle_clock_in(
        user=tech_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"], args={},
    ))
    assert out["ok"] is True, out
    assert out["code"] is None
    assert "job_context" in out["meta"]
    assert out["meta"]["job_context"].endswith("Smith Pool")
    # Day-scoped write persisted.
    row = dbc.timesheets.find_one({"technician_id": tech_user["id"]})
    assert row is not None
    assert row.get("clock_in_at")
    # Ruling #3: no job_id on the timesheet.
    assert row.get("job_id") is None


# ═══ 5. CLOCK — tech happy path (out) ════════════════════════════
def test_clock_out_tech_happy(scenario, tech_user, tenant, dbc):
    from services.marco.actions import handle_clock_in, handle_clock_out
    _run(handle_clock_in(
        user=tech_user, tenant=tenant,
        screen="service_report", entity_id="", args={},
    ))
    out = _run(handle_clock_out(
        user=tech_user, tenant=tenant,
        screen="service_report", entity_id="", args={},
    ))
    assert out["ok"] is True, out
    assert out["code"] is None
    # No ``job_context`` on non-job_detail screens.
    assert "job_context" not in out["meta"]


# ═══ 6. CLOCK — admin role short-circuit ═════════════════════════
def test_clock_in_admin_role_not_tech(admin_user, tenant, scenario):
    from services.marco.actions import handle_clock_in
    out = _run(handle_clock_in(
        user=admin_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"], args={},
    ))
    assert out["ok"] is False
    assert out["code"] == "role_not_tech"


# ═══ 7. CLOCK — super_admin role short-circuit ═══════════════════
def test_clock_in_super_admin_role_not_tech(
    super_admin_user, tenant, scenario,
):
    from services.marco.actions import handle_clock_in
    out = _run(handle_clock_in(
        user=super_admin_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"], args={},
    ))
    assert out["ok"] is False
    assert out["code"] == "role_not_tech"


# ═══ 8. CLOCK — job_context ONLY on job_detail screen ════════════
def test_clock_in_job_context_only_on_job_detail(
    scenario, tech_user, tenant,
):
    from services.marco.actions import handle_clock_in
    out = _run(handle_clock_in(
        user=tech_user, tenant=tenant,
        screen="service_report", entity_id=scenario["service_report_id"],
        args={},
    ))
    assert out["ok"] is True
    assert "job_context" not in out["meta"]


# ═══ 9. LINE ITEM — fuzzy match happy (score ≥ 85) ═══════════════
def test_add_line_item_fuzzy_match_happy(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_add_line_item
    out = _run(handle_add_line_item(
        user=tech_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"],
        args={"item_query": scenario["item_distinct_name"],
              "quantity": 2},
    ))
    assert out["ok"] is True, out
    assert out["code"] is None
    assert out["meta"]["item_id"] == scenario["item_distinct_id"]
    inv = dbc.quotes.find_one({"id": scenario["invoice_id"]})
    assert len(inv.get("line_items") or []) == 1
    assert inv["line_items"][0]["quantity"] == 2


# ═══ 10. LINE ITEM — no match ═════════════════════════════════════
def test_add_line_item_no_match_friendly_error(
    scenario, tech_user, tenant,
):
    from services.marco.actions import handle_add_line_item
    out = _run(handle_add_line_item(
        user=tech_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"],
        args={"item_query": "zzz_not_a_real_pricebook_item", "quantity": 1},
    ))
    assert out["ok"] is False
    assert out["code"] == "item_not_matched"


# ═══ 11. LINE ITEM — ambiguous top-2 ═════════════════════════════
def test_add_line_item_ambiguous_top2_returns_candidates(
    scenario, tech_user, tenant,
):
    from services.marco.actions import handle_add_line_item
    query = f"{TAG}Alpha Sanitizer"
    out = _run(handle_add_line_item(
        user=tech_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["job_id"],
        args={"item_query": query, "quantity": 1},
    ))
    assert out["ok"] is False, out
    assert out["code"] == "ambiguous_item_match"
    assert len(out["meta"]["candidates"]) == 2


# ═══ 12. LINE ITEM — resolves invoice from service_report screen ══
def test_add_line_item_resolves_invoice_from_service_report(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_add_line_item
    out = _run(handle_add_line_item(
        user=tech_user, tenant=tenant,
        screen="service_report",
        entity_id=scenario["service_report_id"],
        args={"item_query": scenario["item_distinct_name"], "quantity": 1},
    ))
    assert out["ok"] is True, out
    assert out["meta"]["invoice_id"] == scenario["invoice_id"]
    inv = dbc.quotes.find_one({"id": scenario["invoice_id"]})
    assert len(inv.get("line_items") or []) == 1


# ═══ 13. LINE ITEM — no invoice for job ══════════════════════════
def test_add_line_item_no_open_invoice_for_orphan_job(
    scenario, tech_user, tenant,
):
    from services.marco.actions import handle_add_line_item
    out = _run(handle_add_line_item(
        user=tech_user, tenant=tenant,
        screen="job_detail", entity_id=scenario["orphan_job_id"],
        args={"item_query": scenario["item_distinct_name"], "quantity": 1},
    ))
    assert out["ok"] is False
    assert out["code"] == "no_open_invoice"


# ═══ 14. NOTE — direct on service_report screen ══════════════════
def test_save_note_direct_by_report_id(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_save_note
    dbc.service_reports.update_one(
        {"id": scenario["service_report_id"]},
        {"$set": {"tech_id": tech_user["id"]}},
    )
    out = _run(handle_save_note(
        user=tech_user, tenant=tenant,
        screen="service_report",
        entity_id=scenario["service_report_id"],
        args={"text": "Filter looked clogged"},
    ))
    assert out["ok"] is True, out
    assert out["meta"]["report_id"] == scenario["service_report_id"]
    sr = dbc.service_reports.find_one({"id": scenario["service_report_id"]})
    assert "Filter looked clogged" in (sr.get("internal_notes") or "")


# ═══ 15. NOTE — job_detail routes through attach-note ═══════════
def test_save_note_job_detail_attaches_to_open_sr(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_save_note
    dbc.service_reports.update_one(
        {"id": scenario["service_report_id"]},
        {"$set": {"tech_id": tech_user["id"]}},
    )
    out = _run(handle_save_note(
        user=tech_user, tenant=tenant,
        screen="job_detail",
        entity_id=scenario["job_id"],
        args={"text": "Second visit next week"},
    ))
    assert out["ok"] is True, out
    assert out["meta"]["report_id"] == scenario["service_report_id"]


# ═══ 16. NOTE — multiple open SRs → picker branch ═══════════════
def test_save_note_multiple_open_reports_returns_picker(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_save_note
    dbc.service_reports.update_one(
        {"id": scenario["service_report_id"]},
        {"$set": {"tech_id": tech_user["id"]}},
    )
    extra_sr_id = f"{TAG}sr-extra-{uuid.uuid4().hex[:8]}"
    dbc.service_reports.insert_one({
        "id": extra_sr_id, "tenant_id": tenant["id"],
        "job_id": scenario["job_id"], "tech_id": tech_user["id"],
        "internal_notes": "", "submitted_at": None,
    })
    try:
        out = _run(handle_save_note(
            user=tech_user, tenant=tenant,
            screen="job_detail",
            entity_id=scenario["job_id"],
            args={"text": "which report"},
        ))
        assert out["ok"] is False, out
        assert out["code"] == "multiple_open_service_reports"
        assert isinstance(out["meta"]["reports"], list)
        assert len(out["meta"]["reports"]) == 2
    finally:
        dbc.service_reports.delete_one({"id": extra_sr_id})


# ═══ 17. NOTE — no open SR → friendly 404 ════════════════════════
def test_save_note_no_open_report_friendly_error(
    scenario, tech_user, tenant, dbc,
):
    from services.marco.actions import handle_save_note
    # Default seed leaves ``tech_id=None`` on the sole SR → the
    # tech's query returns zero open reports.
    out = _run(handle_save_note(
        user=tech_user, tenant=tenant,
        screen="job_detail",
        entity_id=scenario["job_id"],
        args={"text": "lost note"},
    ))
    assert out["ok"] is False, out
    assert out["code"] == "no_open_service_report"
