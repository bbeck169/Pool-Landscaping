"""Phase KB1.5 · Feb-2026 — Copilot dispatcher hardening.

Locks the three behaviours the P0 fix ships:

  1. Empty / malformed body from the emergent platform fallback is
     retried EXACTLY ONCE.  If the retry also comes back empty, the
     visible ``.content`` string is the user-facing message — NEVER
     ``[emergent fallback error: emergent_empty_json]``.

  2. Valid JSON on the first attempt is passed through untouched
     (no retry, no rewrite).

  3. ``parse_json`` is threaded from the top-level caller
     (Copilot's ``parse_json=False`` chat surface) all the way
     through ``dispatch_ai_completion`` → ``_emergent_platform_fallback``
     → the inner ``call_llm_with_fallback`` — so a plain-text Claude
     reply never gets JSON-mode-rejected as "empty".

The mocked path exercised here is the ``tenant_id`` = None branch
of ``call_llm_with_fallback`` (no BYO probe) so we hit the
platform fallback directly without any tenant setup.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ─── 1. Retry-once on empty body ───────────────────────────────────
@pytest.mark.anyio
async def test_platform_fallback_retries_once_on_empty_body():
    from services.ai import dispatcher as _d

    call_count = {"n": 0}

    async def _fake_call_llm(**kwargs):
        call_count["n"] += 1
        # First call: empty JSON (the pre-fix classic).
        if call_count["n"] == 1:
            return {"error": "emergent_empty_json"}
        # Retry: valid text response.
        return {"raw": {"text": "Second-try reply from Claude."},
                 "provider": "emergent"}

    with patch.object(_d, "get_tenant_ai_provider",
                        new_callable=AsyncMock, return_value=None), \
         patch("services.llm_provider.call_llm_with_fallback",
                 side_effect=_fake_call_llm):
        result = await _d.dispatch_ai_completion(
            tenant_id="t-1",
            system_prompt="you are helpful",
            user_text="hello",
            parse_json=False,
        )
    assert call_count["n"] == 2, "retry did not fire exactly once"
    assert result.content == "Second-try reply from Claude."
    # Error banner must NOT leak on a successful retry.
    assert "[emergent fallback error" not in (result.content or "")


# ─── 2. Both attempts empty → user-facing content, not the wrapper ─
@pytest.mark.anyio
async def test_platform_fallback_surfaces_user_facing_error_on_double_empty():
    from services.ai import dispatcher as _d

    async def _fake_call_llm(**kwargs):
        # Both attempts fail identically.
        return {"error": "emergent_empty_json"}

    with patch.object(_d, "get_tenant_ai_provider",
                        new_callable=AsyncMock, return_value=None), \
         patch("services.llm_provider.call_llm_with_fallback",
                 side_effect=_fake_call_llm):
        result = await _d.dispatch_ai_completion(
            tenant_id="t-1",
            system_prompt="you are helpful",
            user_text="hello",
            parse_json=False,
        )
    # The internal wrapper MUST NOT leak.
    assert "emergent_empty_json" not in (result.content or ""), \
        "internal error string leaked to user-visible content"
    assert "[emergent fallback error" not in (result.content or "")
    # And the visible content IS the user-facing message.
    assert "unexpected response" in (result.content or "").lower()
    # The raw error is still preserved on ``result.raw`` for
    # observability dashboards.
    assert result.raw and result.raw.get("error") == "emergent_empty_json"


# ─── 3. Valid response on first attempt — happy path unchanged ─────
@pytest.mark.anyio
async def test_platform_fallback_happy_path_no_retry_no_rewrite():
    from services.ai import dispatcher as _d

    call_count = {"n": 0}

    async def _fake_call_llm(**kwargs):
        call_count["n"] += 1
        return {"raw": {"text": "Brand voice is friendly, direct, no fluff."},
                 "provider": "emergent"}

    with patch.object(_d, "get_tenant_ai_provider",
                        new_callable=AsyncMock, return_value=None), \
         patch("services.llm_provider.call_llm_with_fallback",
                 side_effect=_fake_call_llm):
        result = await _d.dispatch_ai_completion(
            tenant_id="t-1",
            system_prompt="you are helpful",
            user_text="what is your brand voice?",
            parse_json=False,
        )
    assert call_count["n"] == 1, "retry fired on a successful call"
    assert result.content == "Brand voice is friendly, direct, no fluff."


# ─── 4. ``parse_json`` threads through end-to-end ──────────────────
@pytest.mark.anyio
async def test_parse_json_false_is_forwarded_to_llm_provider():
    """Copilot passes ``parse_json=False``; the platform fallback
    MUST propagate that through so plain-text Claude replies aren't
    JSON-mode-rejected."""
    from services.ai import dispatcher as _d

    captured_kwargs = []

    async def _fake_call_llm(**kwargs):
        captured_kwargs.append(kwargs)
        return {"raw": {"text": "ok"}, "provider": "emergent"}

    with patch.object(_d, "get_tenant_ai_provider",
                        new_callable=AsyncMock, return_value=None), \
         patch("services.llm_provider.call_llm_with_fallback",
                 side_effect=_fake_call_llm):
        await _d.dispatch_ai_completion(
            tenant_id="t-1",
            system_prompt="s", user_text="u",
            parse_json=False,
        )
    assert captured_kwargs, "call_llm_with_fallback was never invoked"
    # Every inner call MUST carry parse_json=False.
    for kw in captured_kwargs:
        assert kw.get("parse_json") is False, (
            f"parse_json not forwarded: {kw!r}")


# ─── 5. Rate-limit / 429-shaped error surfaces user-friendly copy ──
@pytest.mark.anyio
async def test_platform_fallback_maps_429_shaped_error_to_friendly_copy():
    from services.ai import dispatcher as _d

    async def _fake_call_llm(**kwargs):
        # The Emergent 429 path returns an ``error`` field with
        # "rate_limit" verbatim.  It is NOT in the retryable set
        # (retry would just hit the same limit), so ONE call.
        return {"error": "rate_limit_exceeded"}

    with patch.object(_d, "get_tenant_ai_provider",
                        new_callable=AsyncMock, return_value=None), \
         patch("services.llm_provider.call_llm_with_fallback",
                 side_effect=_fake_call_llm):
        result = await _d.dispatch_ai_completion(
            tenant_id="t-1",
            system_prompt="s", user_text="u",
            parse_json=False,
        )
    # No wrapper leak.
    assert "[emergent fallback error" not in (result.content or "")
    assert "rate_limit_exceeded" not in (result.content or "")
    # User sees the friendly message.
    assert "unexpected response" in (result.content or "").lower()
