"""MA2 · Feb-2026 — adjacent regression for the ``language`` kwarg
added to ``services.ai.estimate_from_media._whisper_transcribe``.

The core MA2 endpoint is exercised in ``test_audio_transcribe.py``
where Whisper is fully monkeypatched. These two adjacent tests lock
in the helper's own contract:

  1. When ``language`` is ``None`` (default), the request form data
     does NOT include a ``language`` field. Preserves the pre-MA2
     behaviour (Whisper auto-detect) for existing callers like
     ``services.ai.estimate_from_media.estimate_from_voice``.
  2. When ``language="es"`` is passed, the field IS included in the
     form data. Confirms the new kwarg actually reaches the wire.

Both tests bypass the ``TEST_LLM_MOCK`` env branch (which short-
circuits before httpx) by setting ``OPENAI_API_KEY`` and stubbing
``httpx.AsyncClient`` at the module-scope so we can capture the
``data=`` kwarg passed to ``.post()``.

Manual bash only per session mandate — no testing_agent.
Run::

    pytest backend/tests/test_whisper_language_kwarg.py -xvs
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional


class _FakeResp:
    status_code = 200
    text = ""

    def json(self):
        return {"text": "hello world"}


class _FakeAsyncClient:
    """Async context-manager that records the last ``.post()`` kwargs."""

    def __init__(self, captured: Dict[str, Any], **_kwargs):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, *, headers=None, files=None, data=None):
        self._captured["url"] = url
        self._captured["headers"] = dict(headers or {})
        self._captured["data"] = dict(data or {})
        self._captured["files_keys"] = sorted((files or {}).keys())
        return _FakeResp()


def _install_fake_httpx(monkeypatch, captured: Dict[str, Any]) -> None:
    import services.ai.estimate_from_media as _mod
    monkeypatch.setattr(_mod, "httpx", type("httpx", (), {
        "AsyncClient": lambda **kw: _FakeAsyncClient(captured, **kw),
    }))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key")
    # Ensure TEST_LLM_MOCK doesn't short-circuit the httpx branch.
    monkeypatch.delenv("TEST_LLM_MOCK", raising=False)


def test_whisper_transcribe_language_none_omits_form_field(monkeypatch):
    from services.ai.estimate_from_media import _whisper_transcribe
    captured: Dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, captured)
    out = asyncio.run(
        _whisper_transcribe(b"audio-bytes",
                              filename="memo.webm",
                              content_type="audio/webm")
    )
    assert out.get("text") == "hello world"
    # ``language`` must NOT be in the form data when kwarg is None.
    assert "language" not in captured["data"], (
        f"language leaked into form data: {captured['data']!r}"
    )
    # Sanity: the model field is still present.
    assert captured["data"].get("model") == "whisper-1"


def test_whisper_transcribe_language_kwarg_threads_into_form_data(monkeypatch):
    from services.ai.estimate_from_media import _whisper_transcribe
    captured: Dict[str, Any] = {}
    _install_fake_httpx(monkeypatch, captured)
    out = asyncio.run(
        _whisper_transcribe(b"audio-bytes",
                              filename="memo.webm",
                              content_type="audio/webm",
                              language="es")
    )
    assert out.get("text") == "hello world"
    assert captured["data"].get("language") == "es"
    assert captured["data"].get("model") == "whisper-1"
