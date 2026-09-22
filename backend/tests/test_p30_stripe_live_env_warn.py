"""Phase P30 addendum · Feb-2026 — boot-time Stripe live-mode env WARN.

Locks in ``_p30_warn_stripe_live_env_gaps`` behaviour:

1. ``STRIPE_MODE=test`` (or unset) → helper returns 0, no WARN.
2. ``STRIPE_MODE=live`` + all envs correctly shaped → returns 0,
   no WARN.
3. ``STRIPE_MODE=live`` + missing ``PUBLIC_FRONTEND_ORIGIN`` → 1
   WARN mentioning the env name.
4. ``STRIPE_MODE=live`` + ``STRIPE_SECRET_KEY_LIVE`` starts with
   ``sk_test_`` → 1 WARN mentioning the prefix mismatch.
5. ``STRIPE_MODE=live`` + neither ``STRIPE_WEBHOOK_SECRET_LIVE`` nor
   the generic ``STRIPE_WEBHOOK_SECRET`` set → 1 WARN.
6. ``STRIPE_MODE=live`` + ``STRIPE_WEBHOOK_SECRET`` fallback set
   with correct ``whsec_`` prefix → no WARN for the webhook env.
7. ``STRIPE_MODE=live`` + ``STRIPE_WEBHOOK_SECRET`` fallback set
   but wrong prefix → 1 WARN.
"""
from __future__ import annotations

import logging

import pytest

from server import (
    _p30_warn_stripe_live_env_gaps,
    _P30_STRIPE_LIVE_ENVS,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with all P30 stripe envs unset — the helper
    is env-driven so isolation matters."""
    monkeypatch.delenv("STRIPE_MODE", raising=False)
    for env_name, _ in _P30_STRIPE_LIVE_ENVS:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    yield


def test_p30_env_warn_test_mode_quiet(monkeypatch, caplog):
    monkeypatch.setenv("STRIPE_MODE", "test")
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 0
    # No STARTUP warns fired from THIS helper.
    assert not any(
        "STRIPE_MODE=live" in rec.message
        for rec in caplog.records
    )


def test_p30_env_warn_mode_unset_quiet(caplog):
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 0


def test_p30_env_warn_live_all_correct(monkeypatch, caplog):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_live_correctkey123",
    )
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_SECRET_LIVE", "whsec_correctwebhook",
    )
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 0


def test_p30_env_warn_missing_public_frontend_origin(
    monkeypatch, caplog,
):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_live_correctkey",
    )
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_SECRET_LIVE", "whsec_correctwebhook",
    )
    # PUBLIC_FRONTEND_ORIGIN deliberately absent.
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 1
    assert any(
        "PUBLIC_FRONTEND_ORIGIN" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )


def test_p30_env_warn_test_prefix_on_live_secret_key(
    monkeypatch, caplog,
):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_test_ohnothisistestmode",
    )
    monkeypatch.setenv(
        "STRIPE_WEBHOOK_SECRET_LIVE", "whsec_correctwebhook",
    )
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 1
    assert any(
        "STRIPE_SECRET_KEY_LIVE" in rec.message
        and "sk_live_" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )


def test_p30_env_warn_missing_webhook_secret_both(monkeypatch, caplog):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_live_correctkey",
    )
    # NO webhook secret env set at all.
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 1
    assert any(
        "STRIPE_WEBHOOK_SECRET_LIVE" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )


def test_p30_env_warn_generic_webhook_secret_fallback_ok(
    monkeypatch, caplog,
):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_live_correctkey",
    )
    # LIVE-specific webhook env absent BUT generic fallback set.
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_fallback_ok")
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 0


def test_p30_env_warn_generic_webhook_secret_wrong_prefix(
    monkeypatch, caplog,
):
    monkeypatch.setenv("STRIPE_MODE", "live")
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")
    monkeypatch.setenv(
        "STRIPE_SECRET_KEY_LIVE", "sk_live_correctkey",
    )
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "not_a_whsec_string")
    with caplog.at_level(logging.WARNING):
        n = _p30_warn_stripe_live_env_gaps()
    assert n == 1
    assert any(
        "STRIPE_WEBHOOK_SECRET" in rec.message
        and "whsec_" in rec.message
        for rec in caplog.records
        if rec.levelno == logging.WARNING
    )
