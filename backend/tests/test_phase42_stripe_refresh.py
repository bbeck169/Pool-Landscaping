"""Phase 42 · Stripe refresh regression tests (Feb 2026).

Focus areas — all mocked, no live Stripe calls:
  * `_UnconfiguredStripeError` on missing key (fail-fast at first use).
  * `_asdict()` v15-safe helper — tolerates dict, StripeObject-with-
    `.to_dict_recursive`, and attribute-only fallback.
  * `SetupIntent.create` gets a deterministic idempotency key.
  * Webhook signature failure returns 400 via the router.
  * Startup log line format.
"""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest


# ── _asdict helper ─────────────────────────────────────────────────────
def test_asdict_handles_plain_dict():
    from services.payments.stripe_charge import _asdict
    assert _asdict({"a": 1, "b": 2}) == {"a": 1, "b": 2}


def test_asdict_handles_to_dict_recursive():
    from services.payments.stripe_charge import _asdict
    obj = SimpleNamespace(to_dict_recursive=lambda: {"id": "pi_1", "amount": 100})
    assert _asdict(obj) == {"id": "pi_1", "amount": 100}


def test_asdict_falls_back_to_to_dict():
    from services.payments.stripe_charge import _asdict
    obj = SimpleNamespace(to_dict=lambda: {"id": "si_1"})
    assert _asdict(obj) == {"id": "si_1"}


def test_asdict_none_returns_empty_dict():
    from services.payments.stripe_charge import _asdict
    assert _asdict(None) == {}


# ── Fail-fast on unconfigured key ──────────────────────────────────────
def test_unconfigured_stripe_raises(monkeypatch):
    from services.payments import stripe_charge
    # Wipe all Stripe env vars so `_select_secret_key` returns None.
    for k in [
        "STRIPE_SECRET_KEY_LIVE", "STRIPE_SECRET_KEY_TEST", "STRIPE_API_KEY",
    ]:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(stripe_charge._UnconfiguredStripeError):
        stripe_charge._init_api_key()


def test_init_api_key_sets_version_and_logs(monkeypatch, caplog):
    from services.payments import stripe_charge
    # Pod env has real STRIPE_SECRET_KEY_* set — wipe them so our
    # test key wins deterministically.
    monkeypatch.delenv("STRIPE_SECRET_KEY_LIVE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY_TEST", raising=False)
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_ABC123XYZ7890abcd")
    monkeypatch.setenv("STRIPE_MODE", "test")
    # Reset the one-shot startup guard so this test's init logs.
    stripe_charge._STARTUP_LOGGED = False
    with caplog.at_level(logging.INFO, logger="stripe_charge"):
        stripe_charge._init_api_key()
    # Version pinned centrally.
    assert stripe_charge.STRIPE_API_VERSION == "2026-03-25.dahlia"
    # Startup line format includes api_version and last-4.
    log_line = " ".join(r.getMessage() for r in caplog.records)
    assert "api_version 2026-03-25.dahlia" in log_line
    assert "...abcd" in log_line


def test_no_sk_test_emergent_hardcoded_fallback():
    """Regression net — the pre-Phase-42 hardcoded fallback must be
    gone. Silent placeholder keys deferred real failures to request
    time; fail-fast is loud and immediate."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..",
                     "services", "payments", "stripe_charge.py"),
        "r", encoding="utf-8",
    ).read()
    assert "sk_test_emergent" not in src, (
        "sk_test_emergent hardcoded fallback re-introduced — see Phase 42 CHANGELOG."
    )


# ── Idempotency key on SetupIntent.create ──────────────────────────────
def test_setup_intent_uses_idempotency_key():
    """The Phase 42 refactor added a deterministic idempotency key
    derived from (tenant_id, customer_id, YYYYMMDD) — verify it's
    threaded through."""
    src = open(
        os.path.join(os.path.dirname(__file__), "..",
                     "services", "payments", "stripe_charge.py"),
        "r", encoding="utf-8",
    ).read()
    assert "idempotency_key=_si_idem" in src
    assert 'f"si:{tenant_id}:{customer_id}:"' in src


# ── Webhook signature validation returns 400 ───────────────────────────
def test_wrong_signature_raises_via_verify_and_parse(monkeypatch):
    """verify_and_parse_webhook propagates the SDK's
    SignatureVerificationError; the router catches → 400."""
    from services.payments import stripe_charge

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setenv("STRIPE_MODE", "test")

    class _FakeSigErr(Exception):
        pass

    class _FakeWebhook:
        @staticmethod
        def construct_event(payload, sig, secret):  # noqa: ARG004
            raise _FakeSigErr("no valid signature found")

    fake_stripe = MagicMock()
    fake_stripe.Webhook = _FakeWebhook
    monkeypatch.setattr(stripe_charge, "_stripe", fake_stripe)

    with pytest.raises(_FakeSigErr):
        stripe_charge.verify_and_parse_webhook(
            payload=b'{"id":"evt_1"}',
            sig_header="t=1,v1=bogus",
        )
