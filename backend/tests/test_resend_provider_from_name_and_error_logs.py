"""Feb-2026 comms hotfix · ResendEmailProvider.send_email()

Locks in three properties per the P0 email-branding hotfix:

1. ``from_name`` is accepted by the signature and correctly rendered
   in the outgoing Resend payload's ``from`` field, using
   :func:`email.utils.formataddr` so display names with commas /
   quotes / brackets are RFC 5322-safe (blocks header injection).
2. Empty / ``None`` ``from_name`` falls back to the tenant's saved
   ``from_name`` config, then to the bare address (regression
   guard for existing callers that don't pass the arg).
3. Send failures are logged at ``ERROR`` level (not warning) with
   the exception type + message, masked recipient, truncated
   subject line, and the Resend ``x-request-id`` header when
   present. Failure surface remains
   ``EmailResult(status="failed", error=...)`` so existing callers
   that check ``result.status`` (``byo_passthrough``) still work.

Unit-level pytest — no HTTP boundary needed. We inject an
``httpx.MockTransport`` so we can inspect the outgoing payload and
control the response.  Async tests use the codebase-wide ``anyio``
pattern (``@pytest.mark.anyio`` + a session-scoped
``anyio_backend`` fixture that pins the loop to ``asyncio``).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx
import pytest

from services.messaging.email.resend_provider import (
    ResendEmailProvider,
    _build_from_header,
    _mask_email,
)


@pytest.fixture
def anyio_backend() -> str:
    """Force anyio to run against asyncio (matches the rest of
    the backend test suite)."""
    return "asyncio"


# ─── Helpers ──────────────────────────────────────────────────────
class _CapturingTransport:
    """httpx.MockTransport wrapper that stores every outbound POST body."""

    def __init__(self, response_status: int = 200,
                    response_json: Dict[str, Any] | None = None,
                    response_headers: Dict[str, str] | None = None,
                    raise_exc: Exception | None = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._status = response_status
        self._json = response_json or {"id": "resend_mock_id_abc"}
        self._headers = response_headers or {}
        self._raise = raise_exc

    def build(self) -> httpx.MockTransport:
        def _handler(request: httpx.Request) -> httpx.Response:
            self.calls.append({
                "url":     str(request.url),
                "method":  request.method,
                "body":    json.loads(request.content) if request.content else {},
                "headers": dict(request.headers),
            })
            if self._raise is not None:
                raise self._raise
            return httpx.Response(
                self._status, json=self._json, headers=self._headers,
            )
        return httpx.MockTransport(_handler)


@pytest.fixture
def _stub_cfg(monkeypatch):
    """Bypass secrets/config load — send_email always receives this cfg."""
    cfg = {
        "api_key":   "re_test_key_ABCDEFG",
        "from_addr": "no-reply@aquaterra.com",
        "from_name": "AquaTerra Default",
    }

    async def _fake_load(*, tenant_id, provider_key):  # noqa: ARG001
        return cfg

    # ``mark_used`` and ``log_secret_error`` write to Mongo — noop them.
    async def _noop(*args, **kwargs):  # noqa: ARG001
        return None

    monkeypatch.setattr(
        "services.messaging.email.resend_provider.load_provider_config",
        _fake_load,
    )
    monkeypatch.setattr(
        "services.messaging.email.resend_provider.mark_used", _noop,
    )
    monkeypatch.setattr(
        "services.messaging.email.resend_provider.log_secret_error", _noop,
    )
    # Turn OFF test-mode short-circuit so send actually reaches the
    # transport we're inspecting.
    monkeypatch.setattr(
        "services.messaging.email.resend_provider.email_testmode_mock",
        lambda: False,
    )
    return cfg


# ─── Pure-function tests ──────────────────────────────────────────
class TestBuildFromHeader:
    def test_plain_name(self):
        assert _build_from_header(
            "x@y.com", "AquaTerra Pools",
        ) == "AquaTerra Pools <x@y.com>"

    def test_name_with_comma_is_quoted(self):
        # formataddr quotes the display name to defuse the comma.
        header = _build_from_header("x@y.com", "Ops, LLC")
        assert header.startswith('"Ops, LLC"')
        assert header.endswith("<x@y.com>")

    def test_name_with_double_quote_is_escaped(self):
        header = _build_from_header("x@y.com", 'She said "hi"')
        # The literal double quote inside must be backslash-escaped.
        assert '\\"hi\\"' in header
        assert header.endswith("<x@y.com>")

    def test_header_injection_attempt_is_neutralized(self):
        # Classic injection payload — a CRLF followed by a forged
        # header. ``formataddr`` MUST NOT let a raw newline through.
        header = _build_from_header(
            "x@y.com", "Attacker\r\nBcc: evil@x.com",
        )
        assert "\r\n" not in header
        assert "\nBcc:" not in header
        assert header.endswith("<x@y.com>")

    def test_none_returns_bare_address(self):
        assert _build_from_header("x@y.com", None) == "x@y.com"

    def test_empty_string_returns_bare_address(self):
        assert _build_from_header("x@y.com", "") == "x@y.com"

    def test_whitespace_only_returns_bare_address(self):
        assert _build_from_header("x@y.com", "   \t\n") == "x@y.com"


class TestMaskEmail:
    def test_masks_short_local(self):
        assert _mask_email("ab@x.com") == "*@x.com"

    def test_masks_long_local(self):
        assert _mask_email("alice@example.com") == "a***e@example.com"

    def test_handles_empty(self):
        assert _mask_email("") == "***"
        assert _mask_email(None) == "***"

    def test_handles_malformed(self):
        assert _mask_email("nope") == "***"


# ─── send_email integration ───────────────────────────────────────
@pytest.mark.anyio
class TestSendEmailFromName:

    async def _run(self, transport: _CapturingTransport, **send_kwargs):
        client = httpx.AsyncClient(transport=transport.build())
        provider = ResendEmailProvider(http_client=client)
        try:
            return await provider.send_email(
                tenant_id="t_test", to=["dest@example.com"],
                subject="Hello", html_body="<p>hi</p>",
                **send_kwargs,
            )
        finally:
            await client.aclose()

    async def test_from_name_renders_correctly(self, _stub_cfg):
        cap = _CapturingTransport()
        r = await self._run(cap, from_name="AquaTerra Pools")
        assert r.status == "queued"
        assert cap.calls, "expected an outbound HTTP call"
        body = cap.calls[0]["body"]
        assert body["from"] == "AquaTerra Pools <no-reply@aquaterra.com>"

    async def test_from_name_none_falls_back_to_config_default(self, _stub_cfg):
        # Config default is "AquaTerra Default"; None arg → config wins.
        cap = _CapturingTransport()
        await self._run(cap, from_name=None)
        assert cap.calls[0]["body"]["from"] == (
            "AquaTerra Default <no-reply@aquaterra.com>"
        )

    async def test_from_name_omitted_falls_back_to_config_default(self, _stub_cfg):
        cap = _CapturingTransport()
        await self._run(cap)  # no from_name kwarg at all
        assert cap.calls[0]["body"]["from"] == (
            "AquaTerra Default <no-reply@aquaterra.com>"
        )

    async def test_from_name_empty_string_treated_as_none(self, _stub_cfg):
        # Empty string should fall through to config default, NOT
        # render as "  <addr>".
        cap = _CapturingTransport()
        await self._run(cap, from_name="")
        assert cap.calls[0]["body"]["from"] == (
            "AquaTerra Default <no-reply@aquaterra.com>"
        )

    async def test_from_name_whitespace_treated_as_none(self, _stub_cfg):
        cap = _CapturingTransport()
        await self._run(cap, from_name="   ")
        assert cap.calls[0]["body"]["from"] == (
            "AquaTerra Default <no-reply@aquaterra.com>"
        )

    async def test_config_default_absent_uses_bare_address(
            self, _stub_cfg, monkeypatch):
        # Zero config from_name → bare address in the from field.
        cfg_bare = {"api_key": "re_bare", "from_addr": "bare@x.com"}

        async def _fake_load(*, tenant_id, provider_key):  # noqa: ARG001
            return cfg_bare

        monkeypatch.setattr(
            "services.messaging.email.resend_provider.load_provider_config",
            _fake_load,
        )
        cap = _CapturingTransport()
        await self._run(cap)
        assert cap.calls[0]["body"]["from"] == "bare@x.com"

    async def test_from_name_with_comma_is_quoted(self, _stub_cfg):
        cap = _CapturingTransport()
        await self._run(cap, from_name="Ops, LLC")
        assert cap.calls[0]["body"]["from"].startswith('"Ops, LLC"')

    async def test_from_addr_call_arg_overrides_config(self, _stub_cfg):
        cap = _CapturingTransport()
        await self._run(cap, from_addr="alt@aquaterra.com",
                        from_name="AquaTerra Alt")
        assert cap.calls[0]["body"]["from"] == (
            "AquaTerra Alt <alt@aquaterra.com>"
        )


# ─── Error logging ────────────────────────────────────────────────
@pytest.mark.anyio
class TestErrorLogging:

    async def _run(self, transport: _CapturingTransport, **send_kwargs):
        client = httpx.AsyncClient(transport=transport.build())
        provider = ResendEmailProvider(http_client=client)
        try:
            return await provider.send_email(
                tenant_id="t_err",
                to=["victim@example.com"],
                subject="Very long subject " + "x" * 200,
                html_body="<p>body</p>",
                **send_kwargs,
            )
        finally:
            await client.aclose()

    async def test_exception_is_logged_at_error_level(
            self, _stub_cfg, caplog):
        cap = _CapturingTransport(
            raise_exc=httpx.ConnectError("dns explode"),
        )
        with caplog.at_level(logging.ERROR, logger="messaging.email.resend"):
            r = await self._run(cap)
        # Return contract preserved.
        assert r.status == "failed"
        assert "ConnectError" in (r.error or "")
        # Error log emitted with all the required context.
        err_records = [
            rec for rec in caplog.records
            if rec.levelno >= logging.ERROR
            and rec.name == "messaging.email.resend"
        ]
        assert err_records, "expected at least one ERROR log line"
        joined = " ".join(rec.getMessage() for rec in err_records)
        assert "ConnectError" in joined
        # PII-masked recipient (never the raw address).
        assert "victim@example.com" not in joined
        assert "v***m@example.com" in joined
        # Subject is truncated to 100 chars.
        assert "Very long subject" in joined
        assert "x" * 150 not in joined
        assert "tenant=t_err" in joined

    async def test_non_2xx_response_is_logged_at_error_level(
            self, _stub_cfg, caplog):
        cap = _CapturingTransport(
            response_status=422,
            response_json={"message": "invalid domain",
                            "name": "validation_error"},
            response_headers={"x-request-id": "req_probe_xyz789"},
        )
        with caplog.at_level(logging.ERROR, logger="messaging.email.resend"):
            r = await self._run(cap)
        assert r.status == "failed"
        assert "HTTP 422" in (r.error or "")
        err_records = [
            rec for rec in caplog.records
            if rec.levelno >= logging.ERROR
            and rec.name == "messaging.email.resend"
        ]
        assert err_records, "expected an ERROR log for non-2xx"
        joined = " ".join(rec.getMessage() for rec in err_records)
        # Resend request-id must appear so support tickets can
        # correlate.
        assert "req_probe_xyz789" in joined
        assert "status=422" in joined
        assert "victim@example.com" not in joined  # PII mask
        assert "v***m@example.com" in joined

    async def test_5xx_is_logged_at_error_level(self, _stub_cfg, caplog):
        cap = _CapturingTransport(
            response_status=503,
            response_json={"error": "temporarily unavailable"},
            response_headers={"resend-request-id": "rr_500_test"},
        )
        with caplog.at_level(logging.ERROR, logger="messaging.email.resend"):
            r = await self._run(cap)
        assert r.status == "failed"
        assert "HTTP 503" in (r.error or "")
        err_records = [
            rec for rec in caplog.records
            if rec.levelno >= logging.ERROR
            and rec.name == "messaging.email.resend"
        ]
        assert err_records
        joined = " ".join(rec.getMessage() for rec in err_records)
        assert "rr_500_test" in joined
        assert "status=503" in joined

    async def test_success_does_not_log_at_error(self, _stub_cfg, caplog):
        cap = _CapturingTransport(
            response_status=200,
            response_json={"id": "resend_ok_id_999"},
        )
        with caplog.at_level(logging.ERROR, logger="messaging.email.resend"):
            r = await self._run(cap)
        assert r.status == "queued"
        assert r.id == "resend_ok_id_999"
        err_records = [
            rec for rec in caplog.records
            if rec.levelno >= logging.ERROR
            and rec.name == "messaging.email.resend"
        ]
        assert not err_records, (
            "success path must not emit any ERROR log lines"
        )
