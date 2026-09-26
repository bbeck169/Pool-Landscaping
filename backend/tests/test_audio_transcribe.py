"""MA2 · Feb-2026 — POST /audio/transcribe regression suite.

In-process. Uses ``httpx.ASGITransport + @pytest.mark.anyio`` per
the Feb 2026 baseline (see ``test_admin_migration_dunning_stage_cta_endpoint``).
Overrides ``require_tech_or_above`` and ``get_current_tenant`` via
``app.dependency_overrides`` so no real JWT / DB user resolution is
needed. Whisper is patched via ``unittest.mock.patch`` at the router
module's local binding (``routers.audio_transcribe._whisper_transcribe``)
so no live OpenAI traffic is generated.

Manual bash only per session mandate — no testing_agent.
Run::

    pytest backend/tests/test_audio_transcribe.py -xvs

9 test cases covering:
  1. Happy path — 200 with mocked transcript + echoed language + null duration
  2. Missing file field         → 422 (FastAPI's own validation error)
  3. Unsupported content-type   → 400 with code UNSUPPORTED_CONTENT_TYPE
  4. File >25 MB                → 413 with code AUDIO_TOO_LARGE
  5. Whisper upstream error     → 502 with code WHISPER_UPSTREAM_ERROR
  6. Missing OPENAI_API_KEY     → 500 with code WHISPER_CONFIG_ERROR
  7. Language passthrough       → helper called with language='es'
  8. Non-tech role (customer)   → 403 (require_tech_or_above guard)
  9. Unauthed (no auth override)→ 401/403 from the real auth dep
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── stub identities ─────────────────────────────────────────────────
_TECH = {"id": "u-tech", "email": "tech@ex.test",
          "role": "technician", "technician_id": "u-tech",
          "tenant_id": "t1"}
_CUSTOMER = {"id": "u-cust", "email": "cust@ex.test",
              "role": "customer", "tenant_id": "t1"}
_TENANT = {"id": "t1", "slug": "acme", "name": "Acme"}


async def _override_tech():
    return _TECH


async def _override_customer():
    return _CUSTOMER


async def _override_tenant():
    return _TENANT


async def _build_client(*, role: str = "technician", override_auth: bool = True):
    """Return the wired-up FastAPI app with dep overrides applied.

    ``override_auth=False`` skips the auth dep override so the real
    ``require_tech_or_above`` fires against the request headers —
    used by test 9 (unauthed request).
    """
    from server import app
    from routers.pool_calculators import require_tech_or_above
    from routers.tenants import get_current_tenant

    app.dependency_overrides.clear()
    if override_auth:
        chooser = _override_tech if role == "technician" else _override_customer
        app.dependency_overrides[require_tech_or_above] = chooser
    app.dependency_overrides[get_current_tenant] = _override_tenant
    return app


def _fake_whisper_ok(*, text: str = "hello world", captured: dict | None = None):
    async def _fake(audio_bytes, filename="memo.webm",
                     content_type="audio/webm", language=None):
        if captured is not None:
            captured["audio_bytes_len"] = len(audio_bytes)
            captured["filename"] = filename
            captured["content_type"] = content_type
            captured["language"] = language
        return {"text": text}
    return _fake


def _fake_whisper_error(err: str, reason: str = "boom"):
    async def _fake(audio_bytes, filename="memo.webm",
                     content_type="audio/webm", language=None):
        return {"error": err, "reason": reason}
    return _fake


# ═══ 1. Happy path ════════════════════════════════════════════════
async def test_happy_path_returns_transcript_and_metadata():
    app = await _build_client()
    fake = _fake_whisper_ok(text="the pool pump is leaking")
    with patch("routers.audio_transcribe._whisper_transcribe", fake):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/audio/transcribe?language=en",
                files={"file": ("memo.webm", b"fake-audio-bytes", "audio/webm")},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transcript"] == "the pool pump is leaking"
    assert body["language"] == "en"
    assert body["duration_sec"] is None
    assert body["model"] == "whisper-1"


# ═══ 2. Missing file → 422 (FastAPI validation) ═══════════════════
async def test_missing_file_returns_422():
    app = await _build_client()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r = await ac.post("/api/audio/transcribe", data={})
    # FastAPI's own File(...) validation returns 422 for missing
    # required multipart fields (the ruling on this endpoint said
    # 400 in the spec, but FastAPI's default validation surface is
    # 422 — coded to reality, flagged in delivery report).
    assert r.status_code == 422, r.text


# ═══ 3. Unsupported content-type → 400 ════════════════════════════
async def test_unsupported_content_type_returns_400():
    app = await _build_client()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r = await ac.post(
            "/api/audio/transcribe",
            files={"file": ("evil.exe", b"\x00\x01\x02", "application/octet-stream")},
        )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "UNSUPPORTED_CONTENT_TYPE"


# ═══ 4. Oversize file → 413 ════════════════════════════════════════
async def test_oversize_file_returns_413():
    app = await _build_client()
    # 25 MB + 1 byte.
    huge = b"\x00" * (25 * 1024 * 1024 + 1)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r = await ac.post(
            "/api/audio/transcribe",
            files={"file": ("big.webm", huge, "audio/webm")},
        )
    assert r.status_code == 413, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "AUDIO_TOO_LARGE"


# ═══ 5. Whisper upstream error → 502 ══════════════════════════════
async def test_whisper_upstream_error_returns_502():
    app = await _build_client()
    fake = _fake_whisper_error("whisper_error", "HTTP 500: boom")
    with patch("routers.audio_transcribe._whisper_transcribe", fake):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/audio/transcribe",
                files={"file": ("memo.webm", b"fake", "audio/webm")},
            )
    assert r.status_code == 502, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "WHISPER_UPSTREAM_ERROR"


# ═══ 6. Missing OPENAI_API_KEY → 500 ══════════════════════════════
async def test_missing_openai_key_returns_500_whisper_config_error():
    app = await _build_client()
    fake = _fake_whisper_error("voice_provider_disabled",
                                 "OPENAI_API_KEY not configured")
    with patch("routers.audio_transcribe._whisper_transcribe", fake):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/audio/transcribe",
                files={"file": ("memo.webm", b"fake", "audio/webm")},
            )
    assert r.status_code == 500, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "WHISPER_CONFIG_ERROR"


# ═══ 7. Language passthrough ══════════════════════════════════════
async def test_language_query_param_threads_into_helper():
    app = await _build_client()
    captured: Dict[str, Any] = {}
    fake = _fake_whisper_ok(text="hola", captured=captured)
    with patch("routers.audio_transcribe._whisper_transcribe", fake):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/audio/transcribe?language=es",
                files={"file": ("memo.webm", b"fake", "audio/webm")},
            )
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "es"
    assert captured.get("language") == "es"
    # Sanity: bytes made it through unaltered.
    assert captured.get("audio_bytes_len") == 4


# ═══ 8. Non-tech role → 403 ═══════════════════════════════════════
async def test_non_tech_role_forbidden():
    # ``_build_client`` with role='customer' installs an override
    # that returns a user with role=customer. But that override
    # bypasses require_tech_or_above (returns the user directly).
    # To actually assert the role gate, clear the dep override and
    # let the real ``require_tech_or_above`` see the customer user.
    from server import app
    from routers.pool_calculators import require_tech_or_above
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    async def _override_get_user():
        return _CUSTOMER

    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = _override_get_user
    app.dependency_overrides[get_current_tenant] = _override_tenant
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/audio/transcribe",
                files={"file": ("memo.webm", b"fake", "audio/webm")},
            )
        assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()


# ═══ 9. Unauthed (no auth override) → 401 or 403 ══════════════════
async def test_unauthed_request_rejected():
    # No overrides at all — real auth chain runs. Missing bearer
    # token surfaces as either 401 (middleware) or 403 (FastAPI's
    # HTTPBearer default). Accept either.
    from server import app
    app.dependency_overrides.clear()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as ac:
        r = await ac.post(
            "/api/audio/transcribe",
            files={"file": ("memo.webm", b"fake", "audio/webm")},
        )
    assert r.status_code in (401, 403), r.text
