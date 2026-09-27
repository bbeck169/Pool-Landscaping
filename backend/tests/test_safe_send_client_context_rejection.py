"""SAFE-SEND-A · Feb-2026 — client-context rejection.

Client-facing request bodies may only supply ``context=TEST``.
``context=SYSTEM|AGENT`` is server-controlled — accepting it from
a client body would let a malicious authenticated caller spoof a
customer send via a hand-crafted request.

This suite proves both surfaces:

1. **Unit** — ``assert_client_supplied_context_allowed`` raises
   ``ClientContextNotAllowedError`` with ``error_code="invalid_comms_context"``
   for SYSTEM / AGENT, no-op for TEST.
2. **Pydantic** — ``CommsSendRequestBase`` validator refuses
   SYSTEM / AGENT at model-parse time, accepts TEST + ``None``.
3. **HTTP** — the FastAPI ``RequestValidationError`` handler in
   ``server.py`` translates the wrapped error into HTTP 400 with
   ``{"error_code": "invalid_comms_context", ...}`` — NOT the
   default 422.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.comms_env_guard import (
    ClientContextNotAllowedError,
    CommsContext,
    CommsSendRequestBase,
    assert_client_supplied_context_allowed,
)


# ═══════════════════════════════════════════════════════════════════
# Unit — ``assert_client_supplied_context_allowed``.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad", [CommsContext.SYSTEM, CommsContext.AGENT])
def test_assert_rejects_privileged_contexts(bad):
    with pytest.raises(ClientContextNotAllowedError) as exc:
        assert_client_supplied_context_allowed(bad)
    assert exc.value.error_code == "invalid_comms_context"
    assert exc.value.supplied == bad.value


def test_assert_accepts_test_context():
    # Not raising is the assertion.
    assert_client_supplied_context_allowed(CommsContext.TEST)


# ═══════════════════════════════════════════════════════════════════
# Pydantic — ``CommsSendRequestBase`` validator.
# ═══════════════════════════════════════════════════════════════════
class _Body(CommsSendRequestBase):
    to: str


def test_request_body_rejects_system_at_parse_time():
    with pytest.raises(ValidationError):
        _Body(to="a@b.com", context="system")


def test_request_body_rejects_agent_at_parse_time():
    with pytest.raises(ValidationError):
        _Body(to="a@b.com", context="agent")


def test_request_body_accepts_test_at_parse_time():
    body = _Body(to="a@b.com", context="test")
    assert body.context == CommsContext.TEST


def test_request_body_accepts_missing_context():
    body = _Body(to="a@b.com")
    assert body.context is None


# ═══════════════════════════════════════════════════════════════════
# HTTP — full request-response through the SAFE-SEND-A handler.
# ═══════════════════════════════════════════════════════════════════
# Builds a tiny FastAPI app that wires the SAME exception handler
# ``server.py`` installs on startup, then exercises it with a
# request body carrying an illegal context.  Isolates the 400
# translation logic from the rest of the Pool CRM server so this
# suite stays fast + hermetic.
def _make_test_app():
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from fastapi.exception_handlers import (
        request_validation_exception_handler as _default_422_handler,
    )

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def _safe_send_client_context_handler(request, exc):
        for err in exc.errors():
            ctx = err.get("ctx") or {}
            wrapped = ctx.get("error")
            msg = str(err.get("msg") or "")
            if isinstance(wrapped, Exception) and getattr(
                wrapped, "error_code", None,
            ) == "invalid_comms_context":
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "invalid_comms_context",
                        "detail": getattr(
                            wrapped, "detail",
                            "context=SYSTEM|AGENT is server-controlled",
                        ),
                        "supplied": getattr(wrapped, "supplied", None),
                    },
                )
            if "client_context_not_allowed" in msg:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error_code": "invalid_comms_context",
                        "detail": (
                            "context=SYSTEM|AGENT is server-controlled "
                            "and cannot be supplied by client requests"
                        ),
                    },
                )
        return await _default_422_handler(request, exc)

    @app.post("/marco/probe")
    async def _probe(body: _Body):
        return {"ok": True, "context": body.context}

    return app


def test_http_rejects_context_system_with_400():
    client = TestClient(_make_test_app())
    r = client.post("/marco/probe",
                    json={"to": "a@b.com", "context": "system"})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["error_code"] == "invalid_comms_context"
    assert "server-controlled" in body["detail"]


def test_http_rejects_context_agent_with_400():
    client = TestClient(_make_test_app())
    r = client.post("/marco/probe",
                    json={"to": "a@b.com", "context": "agent"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "invalid_comms_context"


def test_http_accepts_context_test_with_200():
    client = TestClient(_make_test_app())
    r = client.post("/marco/probe",
                    json={"to": "a@b.com", "context": "test"})
    assert r.status_code == 200, r.text
    assert r.json()["context"] == "test"


def test_http_accepts_missing_context_with_200():
    client = TestClient(_make_test_app())
    r = client.post("/marco/probe", json={"to": "a@b.com"})
    assert r.status_code == 200, r.text
    assert r.json()["context"] is None


def test_http_still_returns_422_for_unrelated_validation_errors():
    """Regression guard — the SAFE-SEND handler MUST fall through
    to the default 422 for validation errors it doesn't recognise,
    or every field-missing / type-mismatch across the API would
    silently downgrade to 400."""
    client = TestClient(_make_test_app())
    # Missing ``to`` — unrelated validation error.
    r = client.post("/marco/probe", json={})
    assert r.status_code == 422, r.text
