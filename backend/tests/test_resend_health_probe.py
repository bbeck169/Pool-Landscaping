"""Phase 27.1 · Feb 2026 — Resend health probe diagnostic upgrade.

Verifies the enhanced ``GET /api/settings/integrations/health/resend``
endpoint surfaces:

* 200 → ``ok: true`` + verified domains list + count
* 400 → ``ok: false`` + parsed ``resend_error`` object
* 401 → same shape as 400
* 500 → ``response_body`` snippet when the body isn't JSON
* NEVER echoes the ``RESEND_API_KEY`` value back
* Missing key short-circuits without hitting Resend
* Network error reports "unreachable" in the message

All Resend calls are mocked via ``httpx.MockTransport`` — no live
traffic, no live sends.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import patch

import httpx

_TEST_KEY = "re_TEST123_deadbeef_dontleak_XXXXXXXXXX"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patched_init_factory(handler):
    orig = httpx.AsyncClient.__init__

    def _init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig(self, *args, **kwargs)
    return _init


def _mk_handler(status: int, body: str,
                content_type: str = "application/json"):
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body,
                              headers={"content-type": content_type})
    return _handler


def _call_probe():
    from routers.google import integration_health
    os.environ.setdefault("RESEND_API_KEY", _TEST_KEY)
    if os.environ.get("RESEND_API_KEY") != _TEST_KEY:
        os.environ["RESEND_API_KEY"] = _TEST_KEY
    return _run(integration_health("resend", admin={"role": "super_admin"}))


def test_health_200_returns_domain_list():
    os.environ["RESEND_API_KEY"] = _TEST_KEY
    body = ('{"data":[{"name":"plofv.com","status":"verified","region":"us-east-1"},'
            '{"name":"resend.dev","status":"pending","region":"us-east-1"}]}')
    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_mk_handler(200, body))):
        out = _call_probe()
    assert out["ok"] is True
    assert out["message"] == "HTTP 200"
    assert out["domain_count"] == 2
    names = {d["name"] for d in out["domains"]}
    assert "plofv.com" in names
    statuses = {d["status"] for d in out["domains"]}
    assert "verified" in statuses


def test_health_400_surfaces_resend_error_name():
    os.environ["RESEND_API_KEY"] = _TEST_KEY
    body = ('{"name":"validation_error","message":"API key is invalid",'
             '"statusCode":400}')
    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_mk_handler(400, body))):
        out = _call_probe()
    assert out["ok"] is False
    assert out["message"] == "HTTP 400"
    assert out["resend_error"]["name"] == "validation_error"
    assert out["resend_error"]["message"] == "API key is invalid"
    assert out["resend_error"]["statusCode"] == 400


def test_health_401_surfaces_resend_error_name():
    os.environ["RESEND_API_KEY"] = _TEST_KEY
    body = ('{"name":"missing_api_key","message":"Missing API key in the '
             'request Authorization header","statusCode":401}')
    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_mk_handler(401, body))):
        out = _call_probe()
    assert out["ok"] is False
    assert out["message"] == "HTTP 401"
    assert out["resend_error"]["name"] == "missing_api_key"


def test_health_500_returns_body_snippet_when_not_json():
    os.environ["RESEND_API_KEY"] = _TEST_KEY
    body = "<html><body>Internal Server Error</body></html>"
    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_mk_handler(500, body, "text/html"))):
        out = _call_probe()
    assert out["ok"] is False
    assert out["message"] == "HTTP 500"
    assert out["resend_error"] is None
    assert "Internal Server Error" in out["response_body"]


def test_health_masks_api_key_if_echoed_in_body():
    """Guardrail — the endpoint must NEVER echo the key value even if
    Resend puts it in an error message."""
    os.environ["RESEND_API_KEY"] = _TEST_KEY
    body = (f'{{"name":"invalid","message":"key {_TEST_KEY} rejected",'
             f'"statusCode":400}}')
    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_mk_handler(400, body))):
        out = _call_probe()
    dumped = json.dumps(out)
    assert _TEST_KEY not in dumped
    assert "re_TEST12" not in dumped   # prefix substring guard


def test_health_missing_key_short_circuits():
    os.environ.pop("RESEND_API_KEY", None)
    from routers.google import integration_health
    out = _run(integration_health("resend", admin={"role": "super_admin"}))
    assert out["ok"] is False
    assert out["message"] == "RESEND_API_KEY unset"


def test_health_network_error_reports_reason():
    os.environ["RESEND_API_KEY"] = _TEST_KEY

    def _handler(_):
        raise httpx.ConnectError("DNS resolution failed")

    with patch("httpx.AsyncClient.__init__",
                _patched_init_factory(_handler)):
        out = _call_probe()
    assert out["ok"] is False
    assert "unreachable" in out["message"].lower()
