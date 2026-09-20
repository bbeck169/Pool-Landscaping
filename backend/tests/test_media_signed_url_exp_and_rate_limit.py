"""Phase P1.2 · Feb 2026 — Media signed-URL ``exp`` claim + SlowAPI
rate limit contract tests.

Covers the 9 acceptance-criteria cases from the P1.2 brief:
  1. HMAC valid + exp in future → 200 with content.
  2. HMAC valid + exp in past → 410 ``signature_expired``.
  3. HMAC missing → 400 ``signature_missing``.
  4. HMAC tampered → 403 ``signature_invalid``.
  5. Legacy URL (``tid=``+``sig=`` only, no ``exp=``) → 400
     ``signature_missing``.
  6. Rate limiter — 61st request within 60s from same IP → 429
     with ``Retry-After`` header.
  7. Email-channel signer emits ``exp`` ≈ 7 days out (±60s).
  8. SMS-channel signer emits ``exp`` ≈ 72 hours out (±60s).
  9. ``/api/openapi.json`` regression — endpoint still listed,
     ``exp``+``sig`` documented as params, ``tid`` NOT.

Sync pymongo handles seed/teardown to avoid Motor loop-affinity;
:func:`run_test` from :mod:`tests._f7_loop_fixture` drives the async
route through :class:`httpx.ASGITransport` so no live network is
required.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_FAKE_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512   # tiny fake PNG


def _get_app():
    from server import app
    return app


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture()
def seeded_media(dbc, monkeypatch):
    """Seed a ``marketing_media`` row via sync pymongo (no async
    loop affinity) + patch ``get_object`` in both the storage
    client + the router-local re-import."""
    tid = f"tenant-p12-{uuid.uuid4().hex[:6]}"
    mid = f"m-p12-{uuid.uuid4().hex[:8]}"
    dbc.marketing_media.insert_one({
        "id": mid, "tenant_id": tid, "uploaded_by": "u",
        "file_name": "probe.png", "mime_type": "image/png",
        "size_bytes": len(_FAKE_BYTES),
        "storage_key": f"tenants/{tid}/marketing_media/{mid}.png",
        "deleted_at": None,
    })

    def _fake_get(key):
        return _FAKE_BYTES, "image/png"

    import services.marketing_media.storage_client as _sc
    import routers.marketing_media as _mm
    monkeypatch.setattr(_sc, "get_object", _fake_get, raising=True)
    monkeypatch.setattr(_mm, "get_object", _fake_get, raising=True)

    yield {"tid": tid, "mid": mid}

    dbc.marketing_media.delete_one({"id": mid})


def _drive_get(path: str, *, remote_addr: str | None = None):
    """Fire GET through ASGITransport under a fresh loop-bound
    Motor client. Returns ``(status_code, text, headers)``."""
    async def _run(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as ac:
            hdrs = {}
            if remote_addr:
                hdrs["X-Forwarded-For"] = remote_addr
            resp = await ac.get(path, headers=hdrs)
            return (
                resp.status_code,
                resp.text,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.content,
            )
    return run_test(_run)


# ═════════════════════════════════════════════════════════════════════
# Case 1 — happy path
# ═════════════════════════════════════════════════════════════════════
def test_valid_signature_returns_200_with_content(seeded_media):
    from routers.marketing_media import _signed_download_url
    url = _signed_download_url(seeded_media["tid"], seeded_media["mid"])
    code, text, hdrs, content = _drive_get(
        url, remote_addr="203.0.113.11",
    )
    assert code == 200, text
    assert hdrs.get("content-type", "").startswith("image/png")
    assert content == _FAKE_BYTES


# ═════════════════════════════════════════════════════════════════════
# Case 2 — exp in the past → 410
# ═════════════════════════════════════════════════════════════════════
def test_expired_signature_returns_410(seeded_media):
    from routers.marketing_media import _sign_media
    past = int(time.time()) - 60
    sig = _sign_media(seeded_media["tid"], seeded_media["mid"], past)
    url = (f"/api/marketing/media/{seeded_media['mid']}/download"
           f"?exp={past}&sig={sig}")
    code, text, _hdrs, _c = _drive_get(url, remote_addr="203.0.113.12")
    assert code == 410, text
    assert "signature_expired" in text


# ═════════════════════════════════════════════════════════════════════
# Case 3 — HMAC missing (no sig / no exp) → 400
# ═════════════════════════════════════════════════════════════════════
def test_missing_signature_returns_400(seeded_media):
    code, text, _hdrs, _c = _drive_get(
        f"/api/marketing/media/{seeded_media['mid']}/download",
        remote_addr="203.0.113.13",
    )
    assert code == 400, text
    assert "signature_missing" in text


# ═════════════════════════════════════════════════════════════════════
# Case 4 — HMAC tampered → 403
# ═════════════════════════════════════════════════════════════════════
def test_tampered_signature_returns_403(seeded_media):
    from routers.marketing_media import _signed_download_url
    signed = _signed_download_url(
        seeded_media["tid"], seeded_media["mid"],
    )
    # Corrupt the last 4 hex chars of ``sig``.
    tampered = signed[:-4] + "aaaa"
    code, text, _hdrs, _c = _drive_get(
        tampered, remote_addr="203.0.113.14",
    )
    assert code == 403, text
    assert "signature_invalid" in text


# ═════════════════════════════════════════════════════════════════════
# Case 5 — legacy URL (``tid``+``sig`` only, no ``exp``) → 400
# ═════════════════════════════════════════════════════════════════════
def test_legacy_url_without_exp_is_rejected(seeded_media):
    """A pre-P1.2 URL still living in an inbox somewhere. MUST NOT
    verify — leaking one legacy URL should not create permanent
    exposure."""
    code, text, _hdrs, _c = _drive_get(
        f"/api/marketing/media/{seeded_media['mid']}/download"
        f"?tid={seeded_media['tid']}&sig=deadbeef",
        remote_addr="203.0.113.15",
    )
    assert code == 400, text
    assert "signature_missing" in text


# ═════════════════════════════════════════════════════════════════════
# Case 6 — rate limiter (60/minute per IP → 61st is 429)
# ═════════════════════════════════════════════════════════════════════
def test_rate_limiter_60_per_minute_per_ip(seeded_media):
    from routers.marketing_media import _signed_download_url, limiter
    # Reset any leftover counter from other tests on this IP.
    if limiter is not None:
        try:
            limiter.reset()
        except Exception:
            pass
    url = _signed_download_url(seeded_media['tid'], seeded_media['mid'])
    ip = "198.51.100.99"
    codes: list[int] = []
    for _i in range(61):
        code, _t, _h, _c = _drive_get(url, remote_addr=ip)
        codes.append(code)
    assert codes[:60] == [200] * 60, (
        f"first 60 should all be 200; got: {codes[:60]}"
    )
    assert codes[60] == 429, f"61st should be 429, got {codes[60]}"
    # 62nd — confirm Retry-After header lands on the 429.
    code, _t, hdrs, _c = _drive_get(url, remote_addr=ip)
    assert code == 429
    assert "retry-after" in hdrs, (
        f"429 response missing Retry-After header; hdrs={list(hdrs)}"
    )


# ═════════════════════════════════════════════════════════════════════
# Case 7 — Email TTL ≈ 7 days
# ═════════════════════════════════════════════════════════════════════
def test_email_channel_signer_emits_7_day_exp():
    from routers.marketing_media import (
        _signed_download_url, MEDIA_URL_TTL_EMAIL_SECONDS,
    )
    from urllib.parse import urlparse, parse_qs
    before = int(time.time())
    url = _signed_download_url("t", "m")   # default = email TTL
    after = int(time.time())
    exp = int(parse_qs(urlparse(url).query)["exp"][0])
    assert MEDIA_URL_TTL_EMAIL_SECONDS == 7 * 86400
    # ±60s tolerance for clock drift / slow CI runs.
    assert before + MEDIA_URL_TTL_EMAIL_SECONDS - 60 <= exp
    assert exp <= after + MEDIA_URL_TTL_EMAIL_SECONDS + 60


# ═════════════════════════════════════════════════════════════════════
# Case 8 — SMS TTL ≈ 72 hours
# ═════════════════════════════════════════════════════════════════════
def test_sms_channel_signer_emits_72_hour_exp():
    from routers.marketing_media import (
        _signed_download_url, MEDIA_URL_TTL_SMS_SECONDS,
    )
    from urllib.parse import urlparse, parse_qs
    before = int(time.time())
    url = _signed_download_url("t", "m",
                                 ttl_seconds=MEDIA_URL_TTL_SMS_SECONDS)
    after = int(time.time())
    exp = int(parse_qs(urlparse(url).query)["exp"][0])
    assert MEDIA_URL_TTL_SMS_SECONDS == 72 * 3600
    assert before + MEDIA_URL_TTL_SMS_SECONDS - 60 <= exp
    assert exp <= after + MEDIA_URL_TTL_SMS_SECONDS + 60


# ═════════════════════════════════════════════════════════════════════
# Case 9 — OpenAPI schema regression
# ═════════════════════════════════════════════════════════════════════
def test_openapi_schema_still_lists_download_endpoint():
    from server import app
    schema = app.openapi()
    paths = schema.get("paths") or {}
    assert "/api/marketing/media/{mid}/download" in paths
    op = paths["/api/marketing/media/{mid}/download"].get("get") or {}
    params = {p["name"]: p for p in (op.get("parameters") or [])
                if p.get("in") == "query"}
    assert "exp" in params, "exp query param missing from OpenAPI"
    assert "sig" in params, "sig query param missing from OpenAPI"
    assert "tid" not in params, (
        "P1.2 dropped ``tid`` from the URL shape but OpenAPI "
        "still advertises it"
    )


# ═════════════════════════════════════════════════════════════════════
# Constants + env-var overrides — documentation guard
# ═════════════════════════════════════════════════════════════════════
def test_ttl_constants_and_env_var_override_names():
    from routers.marketing_media import (
        MEDIA_URL_TTL_EMAIL_SECONDS, MEDIA_URL_TTL_SMS_SECONDS,
    )
    assert MEDIA_URL_TTL_EMAIL_SECONDS == 7 * 86400
    assert MEDIA_URL_TTL_SMS_SECONDS == 72 * 3600
    # And confirm the env-var NAMES are the documented ones.
    import inspect
    import routers.marketing_media as _mm
    src = inspect.getsource(_mm)
    assert 'os.environ.get("MEDIA_URL_TTL_EMAIL_SECONDS"' in src
    assert 'os.environ.get("MEDIA_URL_TTL_SMS_SECONDS"' in src
