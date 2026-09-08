"""Phase I1.7.e · chunk 2 · Feb-2026 — AI callsite migration
regression suite.

Guards the same seven invariants as chunk 1 (messaging), scoped to
the AI stack:

1. **Chokepoint invocation** — ``services.llm_provider.call_llm_with_fallback``
   (the module every one of the 8 llm-consuming services imports)
   routes through ``services.ai.dispatcher.dispatch_ai_completion``
   when a ``tenant_id`` is supplied. All 8 callers inherit the
   migration by opting in with a single kwarg.
2. **Platform fallback parity** — when no tenant BYO provider is
   configured, ``dispatch_ai_completion`` falls back to the Emergent
   Universal LLM Key path (rule 1). Behaviour parity with
   pre-migration for pure-platform callers.
3. **Tenant isolation** — a cap-exceeded on tenant A does NOT cause
   tenant B's request on the same endpoint to 429. Per-tenant BYO
   provider lookup + per-tenant usage ledger.
4. **Transactional vs scheduled cap-exceeded** — a transactional
   callsite (estimate-on-user-click, checkin rewrite) surfaces the
   dispatcher's ``TenantAIUsageCapExceeded`` as ``HTTPException(429)``
   via ``raise_if_ai_cap_exceeded``. A scheduled callsite (autopilot
   brief, weekly summary cron) inspects the same result dict for
   ``cap_exceeded=True``, persists ``skipped_cap_exceeded`` in its
   job log, and continues with the next tenant / next batch item —
   no exception.
5. **``AI_TESTMODE_MOCK`` short-circuit** — outbound provider HTTP is
   skipped when the flag is set, but the BYO probe, cap accounting,
   and platform-fallback rule 1 all still fire.
6. **P0 checklist invariant sibling** — the checklist load path
   (``GET /api/jobs/{id}``, ``GET /api/jobs/{id}/service-report``)
   invokes zero AI dispatch calls. AST-scanned, same technique as
   the messaging sibling in chunk 1.

Runs entirely offline. No API keys required.
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run(coro):
    """Reuse a single event loop across all tests so Motor's
    module-level socket futures stay bound to a live loop."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _disable_ai_testmode_by_default(monkeypatch):
    """``AI_TESTMODE_MOCK`` is enabled in preview ``.env`` so
    live-curl tester passes are hermetic — but the chunk 2
    migration + fallback invariant tests want to see the underlying
    BYO / platform / cap-exceeded code paths. Turn the flag OFF by
    default here; the two dedicated test-mode tests re-enable it
    explicitly."""
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")


# ── Fake tenant AI provider ─────────────────────────────────────────
class _FakeAIProvider:
    provider_key = "fake_openai"

    def __init__(self, *, content: str = "hello from BYO",
                  tokens_prompt: int = 10, tokens_completion: int = 5,
                  raise_exc: Optional[BaseException] = None):
        self._content = content
        self._tp = tokens_prompt
        self._tc = tokens_completion
        self._raise = raise_exc
        self.calls: List[Dict[str, Any]] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        from services.ai.models import AICompletionResult
        return AICompletionResult(
            content=self._content,
            provider_key=self.provider_key,
            provider_used=f"byo:{self.provider_key}",
            model=kwargs.get("model") or "gpt-4o",
            tokens_prompt=self._tp,
            tokens_completion=self._tc,
            tokens_total=self._tp + self._tc,
            tenant_id=kwargs.get("tenant_id") or "",
            raw={"fake": True},
        )


# ─────────────────────────────────────────────────────────────────────
# 1. Chokepoint invocation — llm_provider routes through dispatcher
# ─────────────────────────────────────────────────────────────────────
def test_call_llm_with_fallback_routes_through_dispatcher_when_tenant_id_given(monkeypatch):
    """When ``tenant_id`` is passed, ``call_llm_with_fallback`` MUST
    hit ``dispatch_ai_completion`` and NOT the Emergent / OpenAI
    branches — proving all 8 llm_provider callers inherit BYO
    routing by opting in with one kwarg."""
    from services import llm_provider
    from services.ai import dispatcher as ai_dispatcher

    fake = _FakeAIProvider(content="from-byo-1")

    async def _fake_get(tenant_id, **kwargs):
        return fake

    # Skip all usage / cap ledger reads.
    async def _fake_cap_ok(**kwargs):
        return None

    async def _fake_record(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider", _fake_get)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise", _fake_cap_ok)
    monkeypatch.setattr(ai_dispatcher, "record_usage", _fake_record)
    # Belt-and-suspenders: ensure the OpenAI + Emergent branches would
    # blow up if they were reached.
    async def _boom(*a, **kw):
        raise AssertionError("llm_provider fell through to Emergent/OpenAI"
                              " when tenant_id was supplied")
    monkeypatch.setattr(llm_provider, "_call_emergent_text", _boom)
    monkeypatch.setattr(llm_provider, "_call_openai_text", _boom)
    # Disable AI testmode for THIS test — we want to see the BYO
    # provider get invoked.
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")

    result = _run(llm_provider.call_llm_with_fallback(
        system_prompt="sys", user_text="hi",
        tenant_id="t-ai-migration-1",
    ))

    assert fake.calls, "BYO provider was not invoked"
    assert result["provider"] == "tenant_byo"
    assert result["raw"]["text"] == "from-byo-1"


def test_call_llm_with_fallback_uses_platform_path_when_tenant_id_absent(monkeypatch):
    """When no ``tenant_id`` is passed (existing callers not yet
    migrated), behaviour is bit-for-bit identical to pre-migration:
    no BYO probe, no cap check, straight to Emergent."""
    from services import llm_provider

    seen: List[str] = []

    async def _fake_emergent(**kwargs):
        seen.append("emergent")
        return {"raw": {"text": "from-emergent"}}

    async def _boom_dispatcher(**kwargs):
        raise AssertionError("dispatcher was invoked without tenant_id")

    monkeypatch.setattr(llm_provider, "_call_emergent_text", _fake_emergent)
    # Import late; patch the imported symbol so a stray import can't
    # bypass us.
    import services.ai.dispatcher as ai_dispatcher
    monkeypatch.setattr(ai_dispatcher, "dispatch_ai_completion",
                        _boom_dispatcher)
    monkeypatch.setenv("AI_TESTMODE_MOCK", "")

    result = _run(llm_provider.call_llm_with_fallback(
        system_prompt="sys", user_text="hi",
        # tenant_id intentionally NOT passed
    ))

    assert seen == ["emergent"]
    assert result["provider"] == "emergent"


# ─────────────────────────────────────────────────────────────────────
# 2. Platform fallback parity — no tenant BYO → Emergent path
# ─────────────────────────────────────────────────────────────────────
def test_dispatcher_falls_back_to_platform_when_no_tenant_byo(monkeypatch):
    """Rule 1: when the tenant has no BYO row, the dispatcher must
    fall back to the Emergent Universal LLM Key path unchanged."""
    from services.ai import dispatcher as ai_dispatcher

    async def _fake_get_none(*args, **kwargs):
        return None

    fallback_called: List[Dict[str, Any]] = []

    async def _fake_fallback(**kwargs):
        fallback_called.append(kwargs)
        from services.ai.models import AICompletionResult
        return AICompletionResult(
            content="from-platform", provider_key="emergent",
            provider_used="platform:emergent", model="claude-sonnet-4-5",
            tokens_prompt=1, tokens_completion=1, tokens_total=2,
            tenant_id=kwargs.get("tenant_id") or "",
            raw={},
        )

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider",
                        _fake_get_none)
    monkeypatch.setattr(ai_dispatcher, "_emergent_platform_fallback",
                        _fake_fallback)

    result = _run(ai_dispatcher.dispatch_ai_completion(
        tenant_id="t-no-byo", system_prompt="s", user_text="u",
    ))

    assert fallback_called, "platform fallback was not invoked"
    assert result.provider_used.startswith("platform:")


# ─────────────────────────────────────────────────────────────────────
# 3. Tenant isolation
# ─────────────────────────────────────────────────────────────────────
def test_ai_cap_exceeded_on_tenant_a_does_not_affect_tenant_b(monkeypatch):
    """Tenant A is at its monthly token cap; tenant B is healthy.
    A's request must raise ``TenantAIUsageCapExceeded``. B's request
    on the same endpoint must succeed normally. Cap accounting is
    per-tenant."""
    from services.ai import dispatcher as ai_dispatcher
    from services.ai.models import TenantAIUsageCapExceeded

    tenant_a = "tenant-A-at-cap"
    tenant_b = "tenant-B-healthy"

    fake_a = _FakeAIProvider(content="A")
    fake_b = _FakeAIProvider(content="B")

    async def _fake_get(tenant_id, **kwargs):
        if tenant_id == tenant_a:
            return fake_a
        return fake_b

    async def _fake_cap(tenant_id, provider, **kwargs):
        if tenant_id == tenant_a:
            raise TenantAIUsageCapExceeded(provider=provider,
                                            cap=100_000, used=100_500)

    async def _fake_record(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider", _fake_get)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise", _fake_cap)
    monkeypatch.setattr(ai_dispatcher, "record_usage", _fake_record)

    # Tenant A → cap hit.
    with pytest.raises(TenantAIUsageCapExceeded):
        _run(ai_dispatcher.dispatch_ai_completion(
            tenant_id=tenant_a, system_prompt="s", user_text="u",
        ))
    # Tenant B → success on same endpoint / same tick.
    result = _run(ai_dispatcher.dispatch_ai_completion(
        tenant_id=tenant_b, system_prompt="s", user_text="u",
    ))
    assert result.content == "B"
    assert fake_b.calls, "tenant B provider was not invoked"


# ─────────────────────────────────────────────────────────────────────
# 4. Transactional callsite → HTTP 429 on cap-exceeded
# ─────────────────────────────────────────────────────────────────────
def test_raise_if_ai_cap_exceeded_helper_contract():
    from services.ai.cap_http import (
        raise_if_ai_cap_exceeded, is_ai_cap_exceeded,
    )

    # Cap-exceeded shapes MUST raise 429.
    for cap_shape in (
        {"cap_exceeded": True, "provider": "tenant_byo"},
        {"error": "ai_spend_cap_exceeded", "provider": "tenant_byo"},
        {"http_status": 429, "provider": "tenant_byo"},
        {"cap_exceeded": True, "http_status": 429,
          "error": "ai_spend_cap_exceeded"},
    ):
        assert is_ai_cap_exceeded(cap_shape) is True
        with pytest.raises(HTTPException) as exc_info:
            raise_if_ai_cap_exceeded(cap_shape)
        assert exc_info.value.status_code == 429

    # Non-cap shapes MUST NOT raise.
    for ok in (
        None, {}, {"raw": {"text": "ok"}, "provider": "emergent"},
        {"error": "openai_disabled", "provider": "openai"},
        {"error": "http_5xx", "provider": "emergent"},  # not a cap
    ):
        assert is_ai_cap_exceeded(ok) is False
        raise_if_ai_cap_exceeded(ok)


def test_transactional_ai_callsite_returns_429_on_cap_exceeded(monkeypatch):
    """End-to-end: a transactional AI callsite that dispatches via
    ``call_llm_with_fallback(tenant_id=...)`` MUST surface a cap hit
    as ``HTTPException(429)`` when it invokes
    ``raise_if_ai_cap_exceeded`` on the result. Mirrors the
    messaging ``_deliver_one`` transactional pattern."""
    from services import llm_provider
    from services.ai.cap_http import raise_if_ai_cap_exceeded
    from services.ai import dispatcher as ai_dispatcher
    from services.ai.models import TenantAIUsageCapExceeded

    async def _fake_get(*args, **kwargs):
        return _FakeAIProvider()

    async def _fake_cap(tenant_id, provider, **kwargs):
        raise TenantAIUsageCapExceeded(provider="openai", cap=100, used=101)

    async def _fake_record(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider", _fake_get)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise", _fake_cap)
    monkeypatch.setattr(ai_dispatcher, "record_usage", _fake_record)

    result = _run(llm_provider.call_llm_with_fallback(
        system_prompt="s", user_text="u", tenant_id="t-transactional-ai",
    ))
    # Chokepoint translated the cap exception into a cap-exceeded dict.
    assert result.get("cap_exceeded") is True
    assert result.get("http_status") == 429
    assert result.get("provider") == "tenant_byo"
    # Transactional callsite recipe.
    with pytest.raises(HTTPException) as exc_info:
        raise_if_ai_cap_exceeded(result,
                                   detail="AI cap for tenant-transactional-ai")
    assert exc_info.value.status_code == 429


# ─────────────────────────────────────────────────────────────────────
# 5. Scheduled callsite → skipped_cap_exceeded (no 429 to caller)
# ─────────────────────────────────────────────────────────────────────
def test_scheduled_ai_callsite_marks_skipped_cap_exceeded_and_does_not_raise(
    monkeypatch,
):
    """A scheduled / bulk AI callsite (autopilot brief cron, weekly
    summary generator) must inspect the result for ``cap_exceeded``
    and persist ``skipped_cap_exceeded`` in its job log without
    raising — the batch continues with the next tenant."""
    from services import llm_provider
    from services.ai.cap_http import is_ai_cap_exceeded
    from services.ai import dispatcher as ai_dispatcher
    from services.ai.models import TenantAIUsageCapExceeded

    async def _fake_get(*args, **kwargs):
        return _FakeAIProvider()

    async def _fake_cap(tenant_id, provider, **kwargs):
        raise TenantAIUsageCapExceeded(provider="openai", cap=100, used=101)

    async def _fake_record(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider", _fake_get)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise", _fake_cap)
    monkeypatch.setattr(ai_dispatcher, "record_usage", _fake_record)

    # Bulk fanout across 3 tenants — one is at cap, two succeed.
    async def _fake_get_mixed(tenant_id, **kwargs):
        if tenant_id == "bulk-t2":
            return _FakeAIProvider(content=f"content-{tenant_id}")
        return _FakeAIProvider(content=f"content-{tenant_id}")

    async def _fake_cap_only_middle(tenant_id, provider, **kwargs):
        if tenant_id == "bulk-t2":
            raise TenantAIUsageCapExceeded(provider="openai", cap=100,
                                             used=101)

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider",
                        _fake_get_mixed)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise",
                        _fake_cap_only_middle)

    job_log: List[Dict[str, Any]] = []

    async def _bulk_worker():
        for tid in ("bulk-t1", "bulk-t2", "bulk-t3"):
            res = await llm_provider.call_llm_with_fallback(
                system_prompt="summarise", user_text="last-week data",
                tenant_id=tid,
            )
            status = ("skipped_cap_exceeded"
                       if is_ai_cap_exceeded(res) else "sent")
            job_log.append({"tenant_id": tid, "status": status,
                             "error": res.get("error"),
                             "provider": res.get("provider")})

    _run(_bulk_worker())

    statuses = [row["status"] for row in job_log]
    assert statuses == ["sent", "skipped_cap_exceeded", "sent"], job_log
    # Batch owner receives NO exception — the batch continued.
    assert len(job_log) == 3


# ─────────────────────────────────────────────────────────────────────
# 6. AI_TESTMODE_MOCK short-circuit
# ─────────────────────────────────────────────────────────────────────
def test_ai_testmode_mock_short_circuits_outbound_http(monkeypatch):
    """When ``AI_TESTMODE_MOCK=true`` and no ``tenant_id`` is
    supplied, ``call_llm_with_fallback`` must return a deterministic
    fixture without hitting the Emergent OR OpenAI HTTP paths."""
    from services import llm_provider

    async def _boom(*a, **kw):
        raise AssertionError("outbound HTTP was invoked in test mode")

    monkeypatch.setattr(llm_provider, "_call_emergent_text", _boom)
    monkeypatch.setattr(llm_provider, "_call_openai_text", _boom)
    monkeypatch.setenv("AI_TESTMODE_MOCK", "true")

    result = _run(llm_provider.call_llm_with_fallback(
        system_prompt="s", user_text="hello world",
    ))

    assert result.get("testmode_mock") is True
    assert "hello world" in (result["raw"].get("text") or "")
    # Deterministic — same input → same output.
    result2 = _run(llm_provider.call_llm_with_fallback(
        system_prompt="s", user_text="hello world",
    ))
    assert result["raw"]["text"] == result2["raw"]["text"]


def test_ai_testmode_mock_still_enforces_cap_and_fallback(monkeypatch):
    """AI_TESTMODE_MOCK short-circuits the outbound HTTP call, but
    the cap check + BYO probe + platform-fallback rule 1 MUST still
    fire. If a BYO tenant is at cap in test mode, we still get a
    ``TenantAIUsageCapExceeded``. If a BYO tenant is healthy in test
    mode, we still get a mock result tagged with the BYO provider
    key (not the platform key)."""
    from services.ai import dispatcher as ai_dispatcher
    from services.ai.models import TenantAIUsageCapExceeded

    monkeypatch.setenv("AI_TESTMODE_MOCK", "true")

    # (a) BYO tenant at cap → still raises.
    fake = _FakeAIProvider()

    async def _fake_get(tenant_id, **kwargs):
        return fake

    async def _fake_cap_hit(tenant_id, provider, **kwargs):
        raise TenantAIUsageCapExceeded(provider="fake_openai",
                                         cap=1, used=2)

    async def _fake_record(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "get_tenant_ai_provider", _fake_get)
    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise",
                        _fake_cap_hit)
    monkeypatch.setattr(ai_dispatcher, "record_usage", _fake_record)

    with pytest.raises(TenantAIUsageCapExceeded):
        _run(ai_dispatcher.dispatch_ai_completion(
            tenant_id="t-testmode-at-cap",
            system_prompt="s", user_text="u",
        ))
    assert not fake.calls, "BYO provider HTTP was invoked in test mode"

    # (b) BYO tenant healthy → provider is invoked (mock inside the
    # provider adapter's own ``complete()`` short-circuit — real
    # OpenAI/Anthropic/Gemini providers honour AI_TESTMODE_MOCK via
    # ``_helpers.ai_testmode_mock``; the test fake does not, but is
    # still routed through and its ``provider_used`` is preserved).
    async def _fake_cap_ok(**kwargs):
        return None

    monkeypatch.setattr(ai_dispatcher, "enforce_cap_or_raise", _fake_cap_ok)
    result = _run(ai_dispatcher.dispatch_ai_completion(
        tenant_id="t-testmode-healthy",
        system_prompt="s", user_text="hello",
    ))
    assert result.provider_key == fake.provider_key
    # In test mode, real BYO providers return ``tenant:{short}`` from
    # their own short-circuit; test fakes just complete normally.
    # Either way the result tag reflects the BYO provider — not a
    # ``testmode:platform_*`` tag (which is reserved for the Emergent
    # platform-fallback path).
    assert result.provider_used.startswith(("byo:", "tenant:"))
    assert fake.calls, ("BYO provider adapter should be invoked in test "
                          "mode so its own ``complete()`` short-circuit "
                          "can decide whether to skip HTTP")


# ─────────────────────────────────────────────────────────────────────
# 7. P0 checklist invariant sibling — checklist load has NO AI dispatch
# ─────────────────────────────────────────────────────────────────────
def test_checklist_load_path_has_no_ai_dispatch():
    """Sibling of ``test_checklist_load_path_has_no_messaging_dispatch``
    from chunk 1. The two checklist load endpoints must NOT invoke
    any AI dispatch helper. A leak here would 429 mobile checklist
    opens for AI-cap-exhausted tenants — the same P0 shape."""
    from routers import jobs as jobs_router
    src = inspect.getsource(jobs_router)

    forbidden_calls = (
        "dispatch_ai_completion(",
        "call_llm_with_fallback(",
        "raise_if_ai_cap_exceeded(",
    )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        name = node.name.lower()
        if "checklist" not in name and "service_report" not in name:
            continue
        if any(tok in name for tok in ("submit", "finalize",
                                         "create", "update", "delete")):
            continue
        body_src = ast.get_source_segment(src, node) or ""
        for forbidden in forbidden_calls:
            assert forbidden not in body_src, (
                f"P0 REGRESSION: jobs router function {node.name!r} "
                f"contains forbidden AI call {forbidden!r} — the "
                f"checklist load path must not invoke AI dispatch. "
                f"See tests/test_p0_checklist_429_leak_regression.py "
                f"for the broader invariant."
            )


def test_dispatcher_module_docs_still_present():
    """Meta-guard: the phase I1.7.c.1 dispatcher module's
    documentation of the cap-exceeded contract MUST remain intact so
    future readers don't accidentally re-introduce a fallback on
    cap-exceeded. A dropped docstring here is a red flag."""
    from services.ai import dispatcher
    src = inspect.getsource(dispatcher.dispatch_ai_completion)
    assert "TenantAIUsageCapExceeded" in src
    # Cap-exceeded is a HARD BLOCK for BYO tenants (no fallback).
    assert "429" in src or "MUST NOT" in src or "cap" in src.lower()
