"""Stripe probe · P0e Stage 2 S2-3 — distinct error-branch regression.

Mocks the Stripe SDK's six documented exception classes against
``StripeProvider.test_connection`` and asserts each one produces:

  · the expected ``error_code``
  · the expected ``error_class``
  · a user-facing ``message`` that doesn't collapse to the generic
    ``"Stripe probe failed: <ClassName>"`` text that triggered the
    user report
  · a ``remediation`` string the admin UI can render verbatim
  · the correct ``mode`` inferred from the token prefix

Also pins the SUCCESS shape (masked account id + mode detection).
"""
from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest


# ────────────────────────────────────────────────────────────────────
# Minimal in-process stub for the ``stripe`` SDK's exception
# hierarchy. The production code imports ``stripe`` at module load
# and holds a reference as ``self._stripe``; monkey-patching that
# reference per-test lets us drive each exception branch without
# touching the real SDK.
# ────────────────────────────────────────────────────────────────────
class _StubBaseError(Exception):
    pass
class _StubAuthenticationError(_StubBaseError):
    pass
class _StubPermissionError(_StubBaseError):
    pass
class _StubRateLimitError(_StubBaseError):
    pass
class _StubAPIConnectionError(_StubBaseError):
    pass
class _StubInvalidRequestError(_StubBaseError):
    pass


def _mk_stub_sdk(raiser=None, retrieve_payload=None):
    """Build a lightweight namespace with ``.error.*`` + ``.Account.
    retrieve`` wired to either raise or return a payload."""
    err_ns = types.SimpleNamespace(
        AuthenticationError=_StubAuthenticationError,
        PermissionError=_StubPermissionError,
        RateLimitError=_StubRateLimitError,
        APIConnectionError=_StubAPIConnectionError,
        InvalidRequestError=_StubInvalidRequestError,
        StripeError=_StubBaseError,
    )
    def _acct_retrieve(**kwargs):
        if raiser is not None:
            raise raiser
        return retrieve_payload or {"id": "acct_1A2B3C4D5E6F7560"}
    account_ns = types.SimpleNamespace(retrieve=_acct_retrieve)
    return types.SimpleNamespace(error=err_ns, Account=account_ns,
                                   OAuth=types.SimpleNamespace())


@pytest.fixture
def stripe_provider(monkeypatch):
    from services.payments.tenant_stripe import StripeConnectProvider

    inst = StripeConnectProvider()

    # Stub out ``_tenant_access_token`` so we don't need Mongo.
    async def _tok(tenant_id):
        return "sk_live_test_token_abcdef1234"
    monkeypatch.setattr(inst, "_tenant_access_token", _tok)

    # ``_blocking`` just forwards to the function since our stubs
    # are already synchronous.
    async def _blocking(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(inst, "_blocking", _blocking)

    return inst


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ────────────────────────────────────────────────────────────────────
# 1 · Success — masked account id + mode detection.
# ────────────────────────────────────────────────────────────────────
def test_probe_success_returns_masked_account_and_mode(stripe_provider):
    stripe_provider._stripe = _mk_stub_sdk(
        retrieve_payload={"id": "acct_1AbCdEfGhIjK7560"},
    )
    r = _run(stripe_provider.test_connection(tenant_id="t-ok"))
    assert r.ok is True
    assert r.error_code is None
    assert r.mode == "live"
    assert r.connected_account_id_masked == "acct_…7560"
    assert "live" in r.message


def test_probe_success_detects_test_mode(stripe_provider, monkeypatch):
    async def _tok(tenant_id): return "sk_test_abcdef1234"
    monkeypatch.setattr(stripe_provider, "_tenant_access_token", _tok)
    stripe_provider._stripe = _mk_stub_sdk(
        retrieve_payload={"id": "acct_testaccount1234567560"},
    )
    r = _run(stripe_provider.test_connection(tenant_id="t-test"))
    assert r.ok is True
    assert r.mode == "test"
    assert "test" in r.message


# ────────────────────────────────────────────────────────────────────
# 2 · No-token short-circuit — stripe_not_connected code.
# ────────────────────────────────────────────────────────────────────
def test_probe_no_token_returns_not_connected_code(stripe_provider, monkeypatch):
    async def _no_tok(tenant_id): return None
    monkeypatch.setattr(stripe_provider, "_tenant_access_token", _no_tok)
    stripe_provider._stripe = _mk_stub_sdk()
    r = _run(stripe_provider.test_connection(tenant_id="t-missing"))
    assert r.ok is False
    assert r.error_code == "stripe_not_connected"
    assert "Connect Stripe" in r.remediation


# ────────────────────────────────────────────────────────────────────
# 3 · AuthenticationError → stripe_key_invalid_or_revoked.
# ────────────────────────────────────────────────────────────────────
def test_probe_authentication_error_distinct_code(stripe_provider):
    err = _StubAuthenticationError("Invalid API Key provided: sk_live_...")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-auth"))
    assert r.ok is False
    assert r.error_code == "stripe_key_invalid_or_revoked"
    assert r.error_class == "AuthenticationError"
    # Message is specific, NOT the generic "Stripe probe failed: X".
    assert "rejected" in r.message
    assert "Re-enter Stripe Key" in r.message
    assert "Stripe probe failed:" not in r.message, (
        "message collapsed back to the generic text — user won't see "
        "the actionable remediation"
    )
    assert r.remediation
    assert "OAuth" in r.remediation or "Reconnect" in r.remediation


# ────────────────────────────────────────────────────────────────────
# 4 · PermissionError → stripe_key_missing_scopes.
# ────────────────────────────────────────────────────────────────────
def test_probe_permission_error_distinct_code(stripe_provider):
    err = _StubPermissionError("The key is not authorized to access …")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-perm"))
    assert r.ok is False
    assert r.error_code == "stripe_key_missing_scopes"
    assert r.error_class == "PermissionError"
    assert "lacks required permissions" in r.message
    assert "restricted key" in r.message


# ────────────────────────────────────────────────────────────────────
# 5 · RateLimitError → stripe_rate_limited.
# ────────────────────────────────────────────────────────────────────
def test_probe_rate_limit_distinct_code(stripe_provider):
    err = _StubRateLimitError("Too many requests")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-rate"))
    assert r.error_code == "stripe_rate_limited"
    assert r.error_class == "RateLimitError"
    assert "rate-limiting" in r.message


# ────────────────────────────────────────────────────────────────────
# 6 · APIConnectionError → stripe_connectivity_error.
# ────────────────────────────────────────────────────────────────────
def test_probe_api_connection_error_distinct_code(stripe_provider):
    err = _StubAPIConnectionError("Connection to api.stripe.com failed")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-conn"))
    assert r.error_code == "stripe_connectivity_error"
    assert r.error_class == "APIConnectionError"
    assert "Could not reach" in r.message


# ────────────────────────────────────────────────────────────────────
# 7 · InvalidRequestError with account mismatch → stripe_account_mismatch.
# ────────────────────────────────────────────────────────────────────
def test_probe_account_mismatch_distinct_code(stripe_provider):
    err = _StubInvalidRequestError(
        "No such account: acct_1X; the account belongs to a different "
        "Stripe account"
    )
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-mismatch"))
    assert r.error_code == "stripe_account_mismatch"
    assert r.error_class == "InvalidRequestError"
    assert "different account" in r.message.lower()
    assert "reconnect" in r.remediation.lower()


# ────────────────────────────────────────────────────────────────────
# 8 · Generic InvalidRequestError → stripe_api_error.
# ────────────────────────────────────────────────────────────────────
def test_probe_generic_invalid_request_falls_to_api_error(stripe_provider):
    err = _StubInvalidRequestError("Missing required parameter: id")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-badreq"))
    assert r.error_code == "stripe_api_error"
    assert r.error_class == "InvalidRequestError"


# ────────────────────────────────────────────────────────────────────
# 9 · Any other StripeError → stripe_api_error with class name.
# ────────────────────────────────────────────────────────────────────
def test_probe_unknown_stripe_error_is_api_error(stripe_provider):
    err = _StubBaseError("some new stripe error")
    stripe_provider._stripe = _mk_stub_sdk(raiser=err)
    r = _run(stripe_provider.test_connection(tenant_id="t-weird"))
    assert r.error_code == "stripe_api_error"
    assert r.error_class == "_StubBaseError"


# ────────────────────────────────────────────────────────────────────
# 10 · Legacy generic message is NEVER returned on any branch.
# ────────────────────────────────────────────────────────────────────
def test_probe_never_returns_bare_class_name_message(stripe_provider):
    """The pre-fix message was literally ``f"Stripe probe failed:
    {type(e).__name__}"`` which rendered as ``"Stripe probe failed:
    AuthenticationError"``. That exact string MUST NOT appear on any
    error branch now — every branch has a specific user-facing
    message."""
    for exc in (
        _StubAuthenticationError("x"),
        _StubPermissionError("x"),
        _StubRateLimitError("x"),
        _StubAPIConnectionError("x"),
        _StubInvalidRequestError("x"),
        _StubBaseError("x"),
    ):
        stripe_provider._stripe = _mk_stub_sdk(raiser=exc)
        r = _run(stripe_provider.test_connection(tenant_id="t-legacy"))
        assert "Stripe probe failed:" not in r.message, (
            f"error branch for {type(exc).__name__} regressed to "
            f"the generic text: {r.message!r}"
        )
