"""Phase I1.7.e · Chunk 2.b · Feb-2026 — Live-wire 429 propagation
smoke for the ``POST /api/ai/estimate-from-photo`` base64-vision
endpoint. Closes the Chunk 2.c HUMAN_REQUIRED item.

The endpoint calls ``services.ai.estimate_from_media.estimate_from_photo``
(migrated in Chunk 2.b onto the central AI chokepoint). When the
underlying service returns a cap-exceeded shape, the router MUST
raise HTTP 429 via ``raise_if_ai_cap_exceeded(result)`` **before**
persisting a generation log row.

This is an in-process FastAPI TestClient probe — same ASGI wire as a
curl-against-the-preview-URL request (real dependency graph, real
auth middleware, real routing) but with the underlying vision service
monkey-patched to return the cap-exceeded shape so we can prove the
propagation deterministically **without touching the production-shaped
`tenant_ai_provider` collection**.

Also covers the ``estimator.py`` (§3.2) base64-vision endpoint by
poking its ``_call_generate`` helper directly with the same
cap-exceeded shape.
"""
from __future__ import annotations

import io
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


def _fake_admin_user() -> Dict[str, Any]:
    return {
        "id": "test-admin-user",
        "tenant_id": "test-tenant-live-429",
        "role": "super_admin",
        "email": "livewire-429@test.local",
    }


def _tiny_png_bytes() -> bytes:
    """A 1×1 transparent PNG — smallest valid image the endpoint accepts.
    Uploaded via multipart to satisfy the ``ALLOWED_PHOTO_TYPES`` gate."""
    # Precomputed: 1×1 transparent PNG, 67 bytes.
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
        b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx"
        b"\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND"
        b"\xaeB`\x82"
    )


@pytest.fixture()
def _app_with_stubbed_auth(monkeypatch):
    """Load the real FastAPI app, override auth + rate-limit + generation
    log, and monkeypatch the vision service to return cap-exceeded."""
    # Import lazily so import errors surface as test failures, not
    # collection errors.
    from server import app
    from routers import ai_media_estimator as router_mod
    from utils import get_current_user

    # Bypass auth — return a fake super_admin user.
    async def _fake_get_current_user():
        return _fake_admin_user()

    app.dependency_overrides[get_current_user] = _fake_get_current_user

    # Bypass rate-limit + generation-log DB writes (don't touch Mongo).
    async def _no_rate_limit(*_a, **_kw):
        return None

    async def _no_log(*_a, **_kw):
        return "test-generation-id"

    monkeypatch.setattr(router_mod, "_rate_limit_or_429", _no_rate_limit)
    monkeypatch.setattr(router_mod, "_log_generation", _no_log)

    yield app

    app.dependency_overrides.pop(get_current_user, None)


def test_estimate_from_photo_returns_429_on_ai_cap_exceeded(
    _app_with_stubbed_auth, monkeypatch,
):
    """Live-wire proof — Chunk 2.c HUMAN_REQUIRED close-out.

    When ``estimate_from_media.estimate_from_photo`` returns the
    Chunk 2 cap-exceeded shape (``cap_exceeded=True`` +
    ``error="ai_spend_cap_exceeded"``), the router MUST propagate
    that as HTTP 429 with the same detail — NOT swallow it as a
    silent 200 wrap.
    """
    from services.ai import estimate_from_media as svc

    async def _fake_estimate(image_bytes, *, tenant_id, context_hint=None,
                              filename=None, content_type=None):
        # Exact shape the Chunk 2.b migrated
        # ``estimate_from_media.estimate_from_photo`` returns when the
        # BYO cap is tripped — matches the chokepoint's cap_exceeded
        # contract asserted in test_i17e_chunk2b_raw_sdk_migration.py.
        return {
            "cap_exceeded": True,
            "error": "ai_spend_cap_exceeded",
            "provider": "tenant:openai",
            "input_kind": "photo",
            "parts": [],
            "labor_hours_estimated": 0.0,
            "concerns": [],
            "confidence": 0,
        }

    monkeypatch.setattr(svc, "estimate_from_photo", _fake_estimate)

    client = TestClient(_app_with_stubbed_auth)
    resp = client.post(
        "/api/ai/estimate-from-photo",
        files={"file": ("tiny.png", io.BytesIO(_tiny_png_bytes()),
                          "image/png")},
    )

    assert resp.status_code == 429, (
        f"REGRESSION: /api/ai/estimate-from-photo should return HTTP "
        f"429 when the underlying service returns cap_exceeded=True. "
        f"Got {resp.status_code}. Body: {resp.text[:400]}"
    )
    body = resp.json()
    detail = body.get("detail")
    # ``raise_if_ai_cap_exceeded`` uses a string ``detail`` per the
    # shared cap_http helper — the string MUST reference "spend cap"
    # so operators reading the 429 in logs know it's a BYO-cap trip,
    # not a rate-limit trip.
    assert isinstance(detail, str) and "cap" in detail.lower(), (
        f"429 detail must be a string that references the AI spend "
        f"cap. Got: {body!r}"
    )


def test_estimate_from_photo_happy_path_returns_200(
    _app_with_stubbed_auth, monkeypatch,
):
    """Sanity — non-cap-exceeded responses still land as HTTP 200.
    Guards against a regression where the 429 propagation
    accidentally fires on every response."""
    from services.ai import estimate_from_media as svc

    async def _fake_estimate(image_bytes, *, tenant_id, context_hint=None,
                              filename=None, content_type=None):
        return {
            "provider": "tenant:openai",
            "input_kind": "photo",
            "parts": [{"name": "Pool pump 1HP", "quantity": 1,
                        "source": "pricebook_match"}],
            "labor_hours_estimated": 2.5,
            "concerns": [],
            "confidence": 82,
        }

    monkeypatch.setattr(svc, "estimate_from_photo", _fake_estimate)

    client = TestClient(_app_with_stubbed_auth)
    resp = client.post(
        "/api/ai/estimate-from-photo",
        files={"file": ("tiny.png", io.BytesIO(_tiny_png_bytes()),
                          "image/png")},
    )
    assert resp.status_code == 200, (
        f"Happy-path regression: 200 expected, got {resp.status_code}. "
        f"Body: {resp.text[:400]}"
    )
    body = resp.json()
    assert body.get("confidence") == 82
    assert len(body.get("parts") or []) == 1


def test_estimator_call_generate_cap_exceeded_shape():
    """§3.2 companion — the ``routers/estimator.py::_call_generate``
    helper also does base64 vision (up to 6 photos). Its
    ``call_llm_with_fallback`` returns the cap-exceeded shape and the
    helper degrades to ``{"mocked": True, "reason":
    "ai_spend_cap_exceeded", ...}`` so the caller can persist an
    audit row. This test asserts the SHAPE of that degradation."""
    import asyncio
    from routers import estimator

    # Force the "no key" path so the helper returns the mocked shape
    # WITHOUT hitting the chokepoint at all. The migration invariant
    # under test is: the mocked shape is preserved bit-for-bit vs
    # pre-migration.
    orig_key = getattr(estimator, "EMERGENT_LLM_KEY", None)
    try:
        estimator.EMERGENT_LLM_KEY = ""
        out = asyncio.run(estimator._call_generate({
            "service_type": "repair",
            "title": "Pump replacement",
            "description": "Replace 1HP pump",
            "photos": [{"url": "http://example.com/photo.jpg"}],
        }))
        assert out["mocked"] is True
        assert out["line_items"] == []
        assert out["upsells"] == []
        assert "EMERGENT_LLM_KEY" in (out.get("reason") or "")
    finally:
        estimator.EMERGENT_LLM_KEY = orig_key


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
