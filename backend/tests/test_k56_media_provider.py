"""Phase K56 · Feb-2026 — image-gen provider unit tests.

Guards:
  1. ``EmergentFallbackProvider.generate`` calls Emergent via
     ``LlmChat`` with the (provider, model) tuple + the
     ``modalities=["image","text"]`` param, and pulls the response
     via ``send_message_multimodal_response``.  This regression
     locks the K56 fix (previously wired to
     ``("google", "nano-banana-2")`` which returned HTTP 502).
  2. The image-model id is env-overridable via
     ``EMERGENT_IMAGE_MODEL`` and falls through to the playbook
     default when the env is unset.
  3. ``routers.media_gen._daily_limit`` reads the canonical env var
     first, then dual-reads the deprecated one, then falls back
     to 100.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────
# Import the module under test.
# ─────────────────────────────────────────────────────────────────────
sys.path.insert(0, "/app/backend")

from services import media_provider as mp  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers — stub the emergentintegrations.llm.chat surface.
# ─────────────────────────────────────────────────────────────────────
def _install_stub_chat(image_list, monkeypatch):
    """Install a fake ``emergentintegrations.llm.chat`` module that
    records the (provider, model, params) chosen and returns the
    supplied ``image_list`` from
    ``send_message_multimodal_response``."""
    calls = {"provider": None, "model": None,
              "params": None, "messages": []}

    class _Chat:
        def __init__(self, *_, **__):
            pass

        def with_model(self, provider, model):
            calls["provider"] = provider
            calls["model"] = model
            return self

        def with_params(self, **kwargs):
            calls["params"] = kwargs
            return self

        async def send_message_multimodal_response(self, msg):
            calls["messages"].append(msg)
            return "", image_list

    class _UserMessage:
        def __init__(self, text=None, file_contents=None):
            self.text = text
            self.file_contents = file_contents

    class _ImageContent:
        def __init__(self, b64):
            self.b64 = b64

    fake = types.ModuleType("emergentintegrations.llm.chat")
    fake.LlmChat = _Chat
    fake.UserMessage = _UserMessage
    fake.ImageContent = _ImageContent

    parent = types.ModuleType("emergentintegrations.llm")
    parent.chat = fake
    root = types.ModuleType("emergentintegrations")
    root.llm = parent

    monkeypatch.setitem(sys.modules, "emergentintegrations", root)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm", parent)
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat", fake)
    return calls


# ─────────────────────────────────────────────────────────────────────
# 1) generate() → correct provider/model tuple + modalities.
# ─────────────────────────────────────────────────────────────────────
def test_generate_uses_gemini_provider_and_default_model(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
    monkeypatch.delenv("EMERGENT_IMAGE_MODEL", raising=False)
    calls = _install_stub_chat(
        image_list=[{"mime_type": "image/png", "data": "AAAA"}],
        monkeypatch=monkeypatch,
    )

    prov = mp.EmergentFallbackProvider()
    result = asyncio.run(prov.generate(
        tenant_id="t1", prompt="a blue circle", aspect_ratio="1:1",
    ))

    assert calls["provider"] == "gemini"
    assert calls["model"] == mp.EMERGENT_IMAGE_MODEL_DEFAULT
    assert calls["model"] == "gemini-3.1-flash-image-preview"
    assert calls["params"] == {"modalities": ["image", "text"]}
    assert result["provider"] == "emergent_fallback"
    assert result["tool_used"] == "gemini-3.1-flash-image-preview"
    assert result["image_urls"] == ["data:image/png;base64,AAAA"]


# ─────────────────────────────────────────────────────────────────────
# 2) EMERGENT_IMAGE_MODEL env override wins.
# ─────────────────────────────────────────────────────────────────────
def test_generate_honours_env_override(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
    monkeypatch.setenv("EMERGENT_IMAGE_MODEL", "gemini-3-pro-image-preview")
    calls = _install_stub_chat(
        image_list=[{"mime_type": "image/jpeg", "data": "BBBB"}],
        monkeypatch=monkeypatch,
    )

    prov = mp.EmergentFallbackProvider()
    result = asyncio.run(prov.generate(
        tenant_id="t1", prompt="a red square",
    ))

    assert calls["model"] == "gemini-3-pro-image-preview"
    assert result["tool_used"] == "gemini-3-pro-image-preview"
    assert result["image_urls"] == ["data:image/jpeg;base64,BBBB"]


# ─────────────────────────────────────────────────────────────────────
# 3) empty images list + no data URI in text → ProviderError.
# ─────────────────────────────────────────────────────────────────────
def test_generate_raises_when_no_image_returned(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
    _install_stub_chat(image_list=[], monkeypatch=monkeypatch)

    prov = mp.EmergentFallbackProvider()
    with pytest.raises(mp.ProviderError) as exc:
        asyncio.run(prov.generate(tenant_id="t1", prompt="x"))
    assert "emergent_no_image_in_response" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# 4) missing EMERGENT_LLM_KEY → ProviderError before any call.
# ─────────────────────────────────────────────────────────────────────
def test_generate_requires_emergent_key(monkeypatch):
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
    prov = mp.EmergentFallbackProvider()
    with pytest.raises(mp.ProviderError) as exc:
        asyncio.run(prov.generate(tenant_id="t1", prompt="x"))
    assert "emergent_key_missing" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# 5) search/remove_background unsupported on Emergent provider.
# ─────────────────────────────────────────────────────────────────────
def test_search_unsupported():
    prov = mp.EmergentFallbackProvider()
    with pytest.raises(mp.ProviderError) as exc:
        asyncio.run(prov.search(tenant_id="t1", query="pool"))
    assert "no_search_support" in str(exc.value)


def test_remove_background_unsupported():
    prov = mp.EmergentFallbackProvider()
    with pytest.raises(mp.ProviderError) as exc:
        asyncio.run(prov.remove_background(
            tenant_id="t1", source_image_url="x"))
    assert "no_remove_bg_support" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# 6) _daily_limit — canonical env wins.
# ─────────────────────────────────────────────────────────────────────
def test_daily_limit_reads_canonical_env(monkeypatch):
    from routers import media_gen
    monkeypatch.setenv("AI_MEDIA_DAILY_IMAGE_LIMIT", "42")
    monkeypatch.setenv("SUPERCOOL_DAILY_IMAGE_LIMIT", "999")
    assert media_gen._daily_limit() == 42


# ─────────────────────────────────────────────────────────────────────
# 7) _daily_limit — legacy env still honoured (dual-read window).
# ─────────────────────────────────────────────────────────────────────
def test_daily_limit_dual_reads_legacy_env(monkeypatch):
    from routers import media_gen
    monkeypatch.delenv("AI_MEDIA_DAILY_IMAGE_LIMIT", raising=False)
    monkeypatch.setenv("SUPERCOOL_DAILY_IMAGE_LIMIT", "77")
    # Reset the module-level "warned" latch so the deprecation
    # WARN can fire deterministically in the second assertion.
    media_gen._LEGACY_LIMIT_WARNED = False
    assert media_gen._daily_limit() == 77


# ─────────────────────────────────────────────────────────────────────
# 8) _daily_limit — no env → default 100.
# ─────────────────────────────────────────────────────────────────────
def test_daily_limit_defaults_to_100_when_env_missing(monkeypatch):
    from routers import media_gen
    monkeypatch.delenv("AI_MEDIA_DAILY_IMAGE_LIMIT", raising=False)
    monkeypatch.delenv("SUPERCOOL_DAILY_IMAGE_LIMIT", raising=False)
    assert media_gen._daily_limit() == 100
