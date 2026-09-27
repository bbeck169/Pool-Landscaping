"""Feb-2026 · MARCO · Sub-phase B — delegation + tool-loop tests.

Locks the contracts for the multi-persona conversation + tool-call
loop machinery landed alongside the ``delegate_task`` tool:

  1. Non-orchestrator refusal — ``dispatch_tool`` returns a
     ``permission_denied`` error when a non-orchestrator persona
     attempts ``delegate_task``.
  2. MARCO successful delegation — ``_t_delegate_task`` inserts a
     system-style handoff row + a specialist reply row on the
     current conversation, updates the conversation participant
     list, and returns a compact summary to MARCO.
  3. Message stamping preserves specialist identity — the reply
     row's ``sender_employee_id`` equals the TARGET persona's id
     (not MARCO's).
  4. Shared brand_brain visible to delegatee — the target's
     effective system prompt (as passed to ``_llm_chat``)
     contains the tenant's brand_brain summary alongside the
     delegation preamble.
  5. Tool loop terminates at max iterations — a stub ``_llm_chat``
     that always emits a tool fence causes
     ``_run_orchestrator_tool_loop`` to return the ruling-
     specified terminal message after 5 iterations, and a
     warning is logged.

Loop / DB hygiene
─────────────────
Tests use ``MagicMock`` + ``AsyncMock`` + a tiny async-cursor
shim to simulate ``ai_employees`` / ``ai_employee_messages`` /
``ai_employee_conversations`` / ``brand_brain`` collections.
Zero live Mongo, zero cross-loop concerns.
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock


# ═══════════════════════════════════════════════════════════════════
# Fixture helpers
# ═══════════════════════════════════════════════════════════════════
def _run(coro):
    """Route the coroutine through the current event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class _AsyncCursor:
    def __init__(self, rows):
        self._rows = list(rows or [])
    def sort(self, *_a, **_k):
        return self
    def limit(self, *_a, **_k):
        return self
    def to_list(self, *_a, **_k):
        async def _tl():
            return list(self._rows)
        return _tl()
    def __aiter__(self):
        self._i = 0
        return self
    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row


def _mk_persona(**over) -> Dict[str, Any]:
    base = {
        "id": "casey-1",
        "tenant_id": "t-1",
        "key": "casey",
        "name": "Casey",
        "audience": "admin",
        "read_access_scope": "tenant_all",
        "orchestrator": False,
        "active": True,
        "system_prompt": "You are Casey.",
    }
    base.update(over)
    return base


def _mk_marco(**over) -> Dict[str, Any]:
    return _mk_persona(
        id="marco-1",
        key="marco_executive",
        name="MARCO: Executive Assistant AI",
        orchestrator=True,
        system_prompt="You are MARCO.",
        **over,
    )


# ═══════════════════════════════════════════════════════════════════
# 1) Non-orchestrator refusal — dispatch_tool guard rail.
# ═══════════════════════════════════════════════════════════════════
def test_dispatch_delegate_task_refuses_non_orchestrator_persona(
    monkeypatch,
):
    from services import ai_employee_tools as tools

    # Neutralise the audit + rate-limit side effects.  Rate-limit
    # counts return 0 so the guard fires cleanly; audit inserts
    # are no-ops.
    async def _no_op(_row):
        return None
    async def _zero(_q, _s):
        return 0
    async def _ready():
        return None
    monkeypatch.setattr(tools, "_audit", _no_op)
    monkeypatch.setattr(tools, "_count_since", _zero)
    monkeypatch.setattr(tools, "_ensure_indexes", _ready)

    casey = _mk_persona()   # orchestrator=False

    outcome = _run(tools.dispatch_tool(
        tenant_id="t-1",
        persona=casey,
        caller_kind="admin",
        caller_id="user-1",
        tool_name="delegate_task",
        args={"target_employee_key": "emmie",
                "task_description": "draft an email"},
        conversation_context={
            "conversation_id": "conv-1",
            "tenant_id": "t-1",
            "invoker_persona": casey,
            "user": {"id": "user-1"},
        },
    ))
    assert outcome.get("error") == "permission_denied", outcome
    assert "MARCO" in outcome.get("detail", "") or (
        "orchestrator" in outcome.get("detail", "").lower()
    )


# ═══════════════════════════════════════════════════════════════════
# 2) MARCO successful delegation — target persona's turn is
#    persisted with the target's identity + participant list is
#    updated + summary returned to MARCO.
# ═══════════════════════════════════════════════════════════════════
def test_marco_delegate_task_persists_target_reply_and_returns_summary(
    monkeypatch,
):
    """Exercises ``_t_delegate_task`` directly (bypasses the
    dispatcher's guard rails since we've locked those in test 1).
    ``_llm_chat`` is stubbed to return a deterministic specialist
    reply so we can assert the reply row exactly."""
    from services import ai_employee_tools as tools
    from routers import ai_employees as ai_emps

    marco = _mk_marco()
    casey = _mk_persona()

    # In-memory collection state so the test can assert what was
    # inserted / updated per-call.
    inserted_messages: List[Dict[str, Any]] = []
    conv_updates: List[Dict[str, Any]] = []

    db = MagicMock()

    async def _find_one_employees(query, _projection=None):
        # Return casey when the delegate_task target lookup hits.
        if query.get("key") == "casey":
            return dict(casey)
        return None
    db.ai_employees.find_one = _find_one_employees

    async def _insert_message(doc):
        inserted_messages.append(dict(doc))
        return SimpleNamespace(inserted_id="mock")
    db.ai_employee_messages.insert_one = _insert_message

    db.ai_employee_messages.find = MagicMock(
        return_value=_AsyncCursor([]),
    )

    async def _update_conv(query, update):
        conv_updates.append({"filter": dict(query), "update": dict(update)})
        return SimpleNamespace(modified_count=1)
    db.ai_employee_conversations.update_one = _update_conv

    # Stub the brand_brain resolver so the delegatee sees a
    # deterministic snippet in its system prompt (test 4 asserts
    # more precisely).
    async def _fake_bb(_tid):
        return {"tone": "friendly-professional",
                  "audience": "residential pool owners",
                  "brand_voice_snippet": "warm and specific"}
    monkeypatch.setattr(ai_emps, "_get_brand_brain", _fake_bb)

    captured_llm_call: Dict[str, Any] = {}
    async def _fake_llm(system_prompt, user_text, history):
        captured_llm_call["system_prompt"] = system_prompt
        captured_llm_call["user_text"] = user_text
        captured_llm_call["history"] = list(history)
        return {"text": "Directories update drafted — awaiting approval.",
                  "provider": "stub"}
    monkeypatch.setattr(ai_emps, "_llm_chat", _fake_llm)

    # Route ``from config import db`` used inside _t_delegate_task
    # to our mock.
    import config as _cfg
    original_db = _cfg.db
    _cfg.db = db
    try:
        result = _run(tools._t_delegate_task(
            "t-1",
            target_employee_key="casey",
            task_description="Draft an Angi listing update.",
            context={"snippet": "Address changed to Peoria"},
            conversation_context={
                "conversation_id": "conv-1",
                "tenant_id": "t-1",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
            },
        ))
    finally:
        _cfg.db = original_db

    # Summary shape.
    assert result.get("delegated_to") == "Casey"
    assert result.get("delegated_to_key") == "casey"
    assert result.get("delegated_to_employee_id") == "casey-1"
    assert "Directories update drafted" in result.get(
        "target_reply_excerpt", "",
    )

    # Exactly two messages were persisted: the system handoff +
    # the target's reply.
    assert len(inserted_messages) == 2, inserted_messages

    handoff = inserted_messages[0]
    assert handoff["role"] == "system"
    assert handoff["kind"] == "delegation_handoff"
    assert handoff["employee_id"] == "marco-1"
    assert handoff["sender_employee_id"] == "marco-1"
    assert handoff["delegated_to_employee_id"] == "casey-1"
    assert "MARCO" in handoff["text"] and "Casey" in handoff["text"]
    assert "Draft an Angi listing update." in handoff["text"]

    reply = inserted_messages[1]
    assert reply["role"] == "assistant"
    assert reply["kind"] == "delegation_reply"
    # Contract #3 — sender is the TARGET, not MARCO.
    assert reply["sender_employee_id"] == "casey-1"
    assert reply["employee_id"] == "casey-1"
    assert reply["delegated_by_employee_id"] == "marco-1"

    # Participant list update carries the target's id via $addToSet.
    add_to_set_update = next(
        (u for u in conv_updates if "$addToSet" in u["update"]),
        None,
    )
    assert add_to_set_update is not None
    assert (
        add_to_set_update["update"]["$addToSet"]
        ["participant_employee_ids"]
        == "casey-1"
    )


# ═══════════════════════════════════════════════════════════════════
# 3) Message stamping preserves specialist identity — separate
#    test with a laser-focused assertion so a regression surfaces
#    with a clear failure message.
# ═══════════════════════════════════════════════════════════════════
def test_delegate_task_reply_row_sender_is_target_not_marco(
    monkeypatch,
):
    from services import ai_employee_tools as tools
    from routers import ai_employees as ai_emps

    marco = _mk_marco()
    emmie = _mk_persona(id="emmie-9", key="emmie", name="Emmie")

    inserted: List[Dict[str, Any]] = []
    db = MagicMock()

    async def _find_one(query, _projection=None):
        if query.get("key") == "emmie":
            return dict(emmie)
        return None
    db.ai_employees.find_one = _find_one

    async def _insert_message(doc):
        inserted.append(dict(doc))
        return SimpleNamespace(inserted_id="mock")
    db.ai_employee_messages.insert_one = _insert_message

    db.ai_employee_messages.find = MagicMock(
        return_value=_AsyncCursor([]),
    )
    db.ai_employee_conversations.update_one = AsyncMock()

    async def _fake_bb(_tid):
        return {"tone": "", "audience": ""}
    monkeypatch.setattr(ai_emps, "_get_brand_brain", _fake_bb)
    async def _fake_llm(sp, ut, hi):
        return {"text": "OK", "provider": "stub"}
    monkeypatch.setattr(ai_emps, "_llm_chat", _fake_llm)

    import config as _cfg
    original_db = _cfg.db
    _cfg.db = db
    try:
        _run(tools._t_delegate_task(
            "t-1",
            target_employee_key="emmie",
            task_description="Draft an A/B subject line",
            conversation_context={
                "conversation_id": "conv-7",
                "tenant_id": "t-1",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
            },
        ))
    finally:
        _cfg.db = original_db

    reply_rows = [r for r in inserted if r["role"] == "assistant"]
    assert len(reply_rows) == 1
    row = reply_rows[0]
    assert row["sender_employee_id"] == "emmie-9", (
        "delegated reply must be stamped with the TARGET's id,"
        " NOT MARCO's — got sender_employee_id="
        f"{row['sender_employee_id']!r} (marco.id=marco-1,"
        f" emmie.id=emmie-9)"
    )
    assert row["employee_id"] == "emmie-9"


# ═══════════════════════════════════════════════════════════════════
# 4) Shared brand_brain visible to delegatee — the target's
#    effective system prompt (passed to _llm_chat) contains the
#    brand_brain summary AND the delegation preamble.
# ═══════════════════════════════════════════════════════════════════
def test_delegate_task_injects_brand_brain_into_target_system_prompt(
    monkeypatch,
):
    from services import ai_employee_tools as tools
    from routers import ai_employees as ai_emps

    marco = _mk_marco()
    buddy = _mk_persona(id="buddy-1", key="buddy", name="Buddy")

    db = MagicMock()

    async def _find_one(query, _projection=None):
        if query.get("key") == "buddy":
            return dict(buddy)
        return None
    db.ai_employees.find_one = _find_one
    db.ai_employee_messages.insert_one = AsyncMock()
    db.ai_employee_messages.find = MagicMock(
        return_value=_AsyncCursor([]),
    )
    db.ai_employee_conversations.update_one = AsyncMock()

    # Distinctive brand_brain content the test can look for.
    marker_tone = "TEST-BRAND-TONE-MARKER-9F82"
    marker_audience = "TEST-BRAND-AUDIENCE-MARKER-7C14"

    async def _fake_bb(_tid):
        return {"tone": marker_tone, "audience": marker_audience,
                  "brand_voice_snippet": ""}
    monkeypatch.setattr(ai_emps, "_get_brand_brain", _fake_bb)

    captured: Dict[str, Any] = {}
    async def _fake_llm(system_prompt, user_text, history):
        captured["system_prompt"] = system_prompt
        return {"text": "OK", "provider": "stub"}
    monkeypatch.setattr(ai_emps, "_llm_chat", _fake_llm)

    import config as _cfg
    original_db = _cfg.db
    _cfg.db = db
    try:
        _run(tools._t_delegate_task(
            "t-1",
            target_employee_key="buddy",
            task_description="Weekly brief on pipeline win rate",
            context={"quarter": "Q1 2026"},
            conversation_context={
                "conversation_id": "conv-9",
                "tenant_id": "t-1",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
            },
        ))
    finally:
        _cfg.db = original_db

    sp = captured.get("system_prompt", "")

    # Preamble present.
    assert "delegated to by" in sp
    assert "MARCO" in sp
    assert "Weekly brief on pipeline win rate" in sp
    assert "do not re-delegate" in sp

    # Target persona's OWN prompt is present.
    assert buddy["system_prompt"] in sp

    # Shared brand_brain content is present — the whole point of
    # this test.
    assert marker_tone in sp, (
        f"brand_brain tone marker missing from delegatee's system"
        f" prompt — sp head={sp[:400]!r}"
    )
    assert marker_audience in sp, (
        f"brand_brain audience marker missing from delegatee's"
        f" system prompt"
    )

    # Context dict from MARCO was inlined.
    assert "Q1 2026" in sp


# ═══════════════════════════════════════════════════════════════════
# 5) Tool loop terminates at max iterations — a stub _llm_chat
#    that always emits a tool fence should trip the cap after 5
#    iterations and return the ruling-specified terminal message.
# ═══════════════════════════════════════════════════════════════════
def test_orchestrator_tool_loop_terminates_at_cap_iterations(
    monkeypatch, caplog,
):
    from routers import ai_employees as ai_emps

    marco = _mk_marco()

    # Loop needs a db to persist tool rows + fetch history.  Mock
    # all reads/writes to no-ops.
    db = MagicMock()
    async def _insert(_doc):
        return SimpleNamespace(inserted_id="mock")
    db.ai_employee_messages.insert_one = _insert
    db.ai_employee_messages.find = MagicMock(
        return_value=_AsyncCursor([]),
    )
    original_db = ai_emps.db
    ai_emps.db = db

    # Also stub out the dispatch so we don't try to actually
    # delegate — return a plausible tool result.
    from services import ai_employee_tools as tools
    async def _fake_dispatch(**_kw):
        return {"result": {"delegated_to": "casey",
                              "target_reply_excerpt": "OK"}}
    monkeypatch.setattr(tools, "dispatch_tool", _fake_dispatch)

    # Stub _llm_chat to ALWAYS emit a tool fence — this is the
    # infinite-loop trigger.  Sub-phase B ruling #1 caps at 5
    # iters and returns the terminal message.
    _FENCE = (
        "Let me delegate this.\n"
        '```tool\n{"name":"delegate_task",'
        '"args":{"target_employee_key":"casey",'
        '"task_description":"loop"}}\n```'
    )
    llm_calls = {"n": 0}
    async def _looping_llm(_sp, _ut, _hi):
        llm_calls["n"] += 1
        return {"text": _FENCE, "provider": "stub"}
    monkeypatch.setattr(ai_emps, "_llm_chat", _looping_llm)

    try:
        with caplog.at_level(logging.WARNING, logger="pool_crm"):
            terminal = _run(ai_emps._run_orchestrator_tool_loop(
                tenant={"id": "t-1"},
                user={"id": "user-1"},
                emp=marco,
                cid="conv-loop-1",
                system_prompt="marco sys prompt",
                assistant_text=_FENCE,
            ))
    finally:
        ai_emps.db = original_db

    # Ruling #1 — terminal message string.
    assert terminal == ai_emps._ORCH_TOOL_LOOP_TERMINAL_MSG

    # Cap fired at exactly 5 iterations.
    assert llm_calls["n"] == 5, (
        f"expected exactly {ai_emps._ORCH_TOOL_LOOP_MAX_ITERS}"
        f" LLM calls, got {llm_calls['n']}"
    )

    # Warning was logged with the cap-exceeded signal.
    warnings_found = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "tool-loop depth exceeded" in rec.getMessage()
    ]
    assert warnings_found, (
        "expected a WARNING log for tool-loop depth exceeded,"
        f" got: {[r.getMessage() for r in caplog.records]}"
    )


# ═══════════════════════════════════════════════════════════════════
# 6) Bonus contract — tool_schema_prompt_snippet gates
#    delegate_task behind orchestrator=True.  Non-orchestrator
#    personas must NOT see it in their tool option list (so the
#    LLM never even tries to call it).
# ═══════════════════════════════════════════════════════════════════
def test_tool_schema_snippet_hides_delegate_task_from_non_orchestrator():
    from services.ai_employee_tools import tool_schema_prompt_snippet

    orch_snippet = tool_schema_prompt_snippet({
        "orchestrator": True,
        "read_access_scope": "tenant_all",
    })
    casey_snippet = tool_schema_prompt_snippet({
        "orchestrator": False,
        "read_access_scope": "tenant_all",
    })
    billy_snippet = tool_schema_prompt_snippet({
        "orchestrator": False,
        "read_access_scope": "customer_scoped",
    })

    assert "delegate_task" in orch_snippet
    assert "delegate_task" not in casey_snippet, (
        "non-orchestrator admin persona MUST NOT see delegate_task"
        " in the tool option list — LLM would attempt it and hit"
        " the runtime refusal"
    )
    assert "delegate_task" not in billy_snippet
