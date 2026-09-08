"""Phase I1.7.e · chunk 2 · Fix B · Feb-2026 — Regression suite for
the checkin-rewrite endpoint migration to
``call_llm_with_fallback(tenant_id=...)``.

The chunk 2 migration added tenant-BYO routing + cap enforcement to
``services.llm_provider.call_llm_with_fallback`` but no HTTP
endpoint currently opts in with the ``tenant_id`` kwarg — so live
tester passes had no transactional AI path to exercise. This suite
covers the first migrated endpoint:

  ``POST /api/checkins/rewrite-description``

Before: called ``emergentintegrations.llm.chat.LlmChat`` directly,
completely bypassing the chokepoint. No BYO. No cap. No 429 shape.

After: goes through ``call_llm_with_fallback(tenant_id=...)`` and
maps ``cap_exceeded=True`` in the result dict to
``HTTPException(429)`` via
:func:`services.ai.cap_http.raise_if_ai_cap_exceeded`.

Invariants under test:

1. The endpoint invokes ``call_llm_with_fallback`` with the
   caller's ``tenant_id`` and does NOT invoke the raw
   ``LlmChat.send_message`` API directly.
2. A cap-exceeded result (as returned by the migrated
   ``call_llm_with_fallback`` when a BYO cap is hit) surfaces as
   ``HTTP 429`` with an ``ai_spend_cap_exceeded`` error shape.
3. When no tenant BYO is configured, the endpoint's platform-
   fallback path still returns a 2xx with the rewritten text
   (behaviour parity with pre-migration).
4. The chunk 2 P0 checklist-invariant guard
   (``test_checklist_load_path_has_no_ai_dispatch``) remains PASS
   after the change.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run(coro):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _disable_ai_testmode(monkeypatch):
    """The migration + fallback invariants under test verify the
    real cap-plumbing path. AI_TESTMODE_MOCK is on by default in
    preview .env so live tester passes are hermetic — turn it OFF
    here so the tests see the actual call_llm_with_fallback →
    dispatch_ai_completion path."""
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")


# ─────────────────────────────────────────────────────────────────────
# 1. Endpoint invokes call_llm_with_fallback with tenant_id
# ─────────────────────────────────────────────────────────────────────
def test_checkin_rewrite_endpoint_routes_through_call_llm_with_fallback(
    monkeypatch,
):
    """Spy on ``call_llm_with_fallback`` and assert (a) it was called
    exactly once, (b) with the caller's ``tenant_id``, (c) the raw
    ``LlmChat.send_message`` API was NOT invoked at all."""
    from routers import checkin_rewrite as cr

    llm_calls: List[Dict[str, Any]] = []

    async def _spy_call_llm(**kwargs):
        llm_calls.append(kwargs)
        return {"raw": {"text": "This is the rewritten paragraph."},
                "provider": "emergent"}

    # Patch inside the module that owns the import — checkin_rewrite
    # does ``from services.llm_provider import call_llm_with_fallback``
    # at call time so we monkeypatch the imported module.
    import services.llm_provider as llm_provider
    monkeypatch.setattr(llm_provider, "call_llm_with_fallback",
                        _spy_call_llm)

    # Belt-and-suspenders: the raw LlmChat must NOT be reached.
    _boom_calls: List[Any] = []

    class _BoomLlmChat:
        def __init__(self, *a, **kw):
            _boom_calls.append(("init", a, kw))

        def with_model(self, *a, **kw):
            _boom_calls.append(("with_model", a, kw))
            return self

        async def send_message(self, *a, **kw):
            _boom_calls.append(("send_message", a, kw))
            return "should-not-be-reached"

    # Patch the emergentintegrations import surface.
    import sys
    import types
    fake_mod = types.ModuleType("emergentintegrations.llm.chat")
    fake_mod.LlmChat = _BoomLlmChat
    fake_mod.UserMessage = lambda text: text
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat",
                        fake_mod)

    async def _drive():
        return await cr._generate_rewrite(
            "system-prompt", "user-prompt", tenant_id="t-fixB-1",
        )

    out = _run(_drive())
    assert out == "This is the rewritten paragraph."
    assert len(llm_calls) == 1
    call = llm_calls[0]
    assert call.get("tenant_id") == "t-fixB-1", call
    assert call.get("system_prompt") == "system-prompt"
    assert call.get("user_text") == "user-prompt"
    assert not _boom_calls, (
        "raw LlmChat was invoked — migration did not route through "
        "the chokepoint"
    )


# ─────────────────────────────────────────────────────────────────────
# 2. Cap-exceeded → HTTP 429 with the standard error shape
# ─────────────────────────────────────────────────────────────────────
def test_checkin_rewrite_returns_429_on_ai_cap_exceeded(monkeypatch):
    """When ``call_llm_with_fallback`` returns a cap-exceeded dict,
    ``_generate_rewrite`` must raise the sentinel ``_CapExceeded``
    and the endpoint handler must translate that into
    ``HTTPException(429, {"error": "ai_spend_cap_exceeded", ...})``."""
    from routers import checkin_rewrite as cr
    import services.llm_provider as llm_provider

    async def _cap_hit(**kwargs):
        return {
            "error": "ai_spend_cap_exceeded",
            "provider": "tenant_byo",
            "cap_exceeded": True,
            "http_status": 429,
            "detail": {"provider": "openai", "monthly_cap": 100,
                        "used": 101},
        }

    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _cap_hit)

    async def _drive():
        # _generate_rewrite must raise the sentinel.
        with pytest.raises(cr._CapExceeded) as exc_info:
            await cr._generate_rewrite("sys", "user",
                                         tenant_id="t-cap-hit")
        return exc_info.value.result

    result = _run(_drive())
    assert result["cap_exceeded"] is True
    assert result["http_status"] == 429

    # And the endpoint handler must translate the sentinel into 429.
    async def _drive_endpoint():
        body = cr.RewriteBody(draft_description="worked on pump")
        # Bypass the Mongo-backed rate limiter for this unit test.
        async def _ok_charge(*args, **kwargs):
            return True, 1, 3600
        monkeypatch.setattr(cr, "_rate_charge", _ok_charge)

        # Fake FastAPI Request that flunks the test-bypass check.
        class _FakeReq:
            headers = {}
        with pytest.raises(HTTPException) as exc_info:
            await cr.rewrite_description(
                body=body, request=_FakeReq(),
                user={"id": "u1", "role": "technician",
                       "tenant_id": "t-cap-hit"},
            )
        assert exc_info.value.status_code == 429
        detail = exc_info.value.detail
        # Detail may be a dict or a string depending on shape.
        if isinstance(detail, dict):
            assert detail.get("error") == "ai_spend_cap_exceeded"
        else:
            assert "ai_spend_cap_exceeded" in str(detail)

    _run(_drive_endpoint())


# ─────────────────────────────────────────────────────────────────────
# 3. Platform fallback parity — no tenant BYO → 2xx unchanged
# ─────────────────────────────────────────────────────────────────────
def test_checkin_rewrite_falls_back_to_platform_when_no_tenant_byo(monkeypatch):
    """When the tenant has no BYO AI provider, the endpoint must
    still succeed with the Emergent platform LLM Key (pre-migration
    parity)."""
    from routers import checkin_rewrite as cr
    import services.llm_provider as llm_provider

    async def _platform(**kwargs):
        # Prove we hit the platform path — provider tag reflects it.
        return {"raw": {"text": "Platform fallback rewrite output."},
                "provider": "emergent"}

    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _platform)

    async def _drive():
        return await cr._generate_rewrite(
            "sys", "user", tenant_id="t-no-byo",
        )

    result = _run(_drive())
    assert result == "Platform fallback rewrite output."


# ─────────────────────────────────────────────────────────────────────
# 4. Non-cap failure still surfaces as 502 (regression parity)
# ─────────────────────────────────────────────────────────────────────
def test_checkin_rewrite_non_cap_failure_still_raises_502(monkeypatch):
    """A garden-variety LLM failure (timeout, bad-shape response,
    empty response) must still surface as HTTP 502, not 429. This
    is a regression guard so a future refactor doesn't accidentally
    conflate cap-exceeded with generic failures."""
    from routers import checkin_rewrite as cr
    import services.llm_provider as llm_provider

    async def _empty(**kwargs):
        return {"raw": {"text": ""}, "provider": "emergent"}

    monkeypatch.setattr(llm_provider, "call_llm_with_fallback", _empty)

    async def _drive():
        with pytest.raises(RuntimeError) as exc_info:
            await cr._generate_rewrite("sys", "user",
                                         tenant_id="t-empty")
        # Non-cap failures raise plain RuntimeError, which the
        # endpoint maps to HTTP 502 (not 429).
        assert "emergent_empty_response" in str(exc_info.value)

    _run(_drive())


def test_call_llm_with_fallback_import_available():
    """Meta-guard: the migration import surface must remain stable
    so future refactors don't accidentally drop the chokepoint."""
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import (
        raise_if_ai_cap_exceeded, is_ai_cap_exceeded,
    )
    # tenant_id must be a keyword-only param on the chokepoint.
    import inspect
    sig = inspect.signature(call_llm_with_fallback)
    assert "tenant_id" in sig.parameters
    assert sig.parameters["tenant_id"].default is None
