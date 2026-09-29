"""TB-1 · ``speak`` field on ``POST /api/marco/execute`` responses.

Verifies that every response path includes a ``speak: str`` field,
defaulting to the ``message`` value. Uses the same monkeypatch + DB
pattern as the existing ``test_marco_execute.py``.

Run::

    pytest backend/tests/test_marco_execute_speak_field.py -xvs
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values, load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from tests._phase34_asyncio import batch_safe_run as _run  # noqa: E402

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _BE.get("MONGO_URL")
_DB_NAME = _BE.get("DB_NAME")

TAG = "tbspeak_"


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(_MONGO_URL)[_DB_NAME]


@pytest.fixture
def tenant():
    return {"id": f"{TAG}tenant-{uuid.uuid4().hex[:8]}"}


def _user(role: str, tenant_id: str, *, is_tech: bool = False):
    uid = f"{TAG}u-{role}-{uuid.uuid4().hex[:6]}"
    doc = {
        "id": uid, "role": role, "tenant_id": tenant_id,
        "name": f"{TAG}{role.title()}", "email": f"{uid}@example.com",
    }
    if is_tech:
        doc["technician_id"] = uid
    return doc


@pytest.fixture
def tech_user(tenant):
    return _user("technician", tenant["id"], is_tech=True)


@pytest.fixture
def scenario(dbc, tenant):
    tid = tenant["id"]
    job_id = f"{TAG}job-{uuid.uuid4().hex[:8]}"
    dbc.jobs.insert_one({"id": job_id, "tenant_id": tid, "name": f"{TAG}Pool"})
    yield {"job_id": job_id, "tenant_id": tid}
    dbc.jobs.delete_many({"tenant_id": tid})
    dbc.timesheets.delete_many({"tenant_id": tid})


def _stub_llm(monkeypatch, *, action: str, args=None,
              raw_override=None, error=None):
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


# ═══ Tests ════════════════════════════════════════════════════════

def test_speak_field_on_parser_error(monkeypatch):
    """Parser error path populates speak = message."""
    _stub_llm(monkeypatch, action="", error="upstream_timeout")
    from routers.marco import execute, MarcoExecuteBody
    body = MarcoExecuteBody(transcript="clock in", screen="job_detail")
    user = _user("technician", "t1", is_tech=True)
    tenant = {"id": "t1"}
    out = _run(execute(body=body, user=user, tenant=tenant))
    assert "speak" in out, f"Missing 'speak' key in response: {out}"
    assert isinstance(out["speak"], str)
    assert out["speak"] == out["message"]


def test_speak_field_on_unknown_action(monkeypatch):
    """Unknown action path populates speak = message."""
    _stub_llm(monkeypatch, action="unknown")
    from routers.marco import execute, MarcoExecuteBody
    body = MarcoExecuteBody(transcript="do a backflip", screen="job_detail")
    user = _user("technician", "t2", is_tech=True)
    tenant = {"id": "t2"}
    out = _run(execute(body=body, user=user, tenant=tenant))
    assert "speak" in out
    assert out["speak"] == out["message"]


def test_speak_field_on_handler_success(monkeypatch, scenario, tech_user, tenant):
    """Successful handler populates speak defaulting to message."""
    _stub_llm(monkeypatch, action="clock_in")
    from routers.marco import execute, MarcoExecuteBody
    body = MarcoExecuteBody(
        transcript="clock in", screen="job_detail",
        entity_id=scenario["job_id"],
    )
    out = _run(execute(body=body, user=tech_user, tenant=tenant))
    assert "speak" in out, f"Missing 'speak' key in response: {out}"
    assert isinstance(out["speak"], str)
    assert len(out["speak"]) > 0
    # speak defaults to message unless handler explicitly set it
    assert out["speak"] == out["message"]


def test_speak_field_on_handler_failure(monkeypatch, scenario, tenant):
    """Failed handler (role_not_tech) includes speak."""
    _stub_llm(monkeypatch, action="clock_in")
    from routers.marco import execute, MarcoExecuteBody
    admin = _user("admin", tenant["id"])
    body = MarcoExecuteBody(
        transcript="clock in", screen="job_detail",
        entity_id=scenario["job_id"],
    )
    out = _run(execute(body=body, user=admin, tenant=tenant))
    assert "speak" in out
    assert out["speak"] == out["message"]
    assert out["ok"] is False


def test_speak_field_on_not_supported_action(monkeypatch):
    """Hallucinated action that passed parser but has no handler."""
    # Directly test the endpoint path where handler is None
    import json as _json
    import services.marco.parser as _parser
    import services.marco.actions as _actions

    # Temporarily add a known action that has no handler
    original_known = _parser.KNOWN_ACTIONS.copy()
    _parser.KNOWN_ACTIONS.add("fake_action_no_handler")

    async def _fake(**kwargs):
        return {"raw": _json.dumps({"action": "fake_action_no_handler", "args": {}}),
                "provider": "test"}
    monkeypatch.setattr(_parser, "call_llm_with_fallback", _fake)

    from routers.marco import execute, MarcoExecuteBody
    body = MarcoExecuteBody(transcript="fake", screen="job_detail")
    user = _user("technician", "t5", is_tech=True)
    tenant = {"id": "t5"}
    out = _run(execute(body=body, user=user, tenant=tenant))

    # Restore
    _parser.KNOWN_ACTIONS.discard("fake_action_no_handler")

    assert "speak" in out
    assert out["speak"] == out["message"]
    assert out["code"] == "action_not_supported"
