"""Task QQ · Feb 2026 — Lumino payment provider (stub, Phase 1).

Env-driven. Phase 1 lands with placeholders — callers exercising the
provider without ``LUMINO_API_TOKEN`` etc. set will raise
``PaymentProviderNotConfigured`` (so accidental non-preview use is
loud). Once real credentials are provided by the user in Phase 2 we
flesh out the actual HTTP calls per the Lumino Stripe-to-Lumino
import guide.

Preview safety: when ``APP_ENV != production`` AND the destination
customer is not on ``PAYMENTS_TEST_ALLOWLIST_CUSTOMERS``, every call
short-circuits to a synthetic ``{status: "dry_run", ...}`` payload
via ``PaymentProviderDryRun``. Callers catch this and treat the
payload as a fabricated success (no live API touched).
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from .provider_base import (
    PaymentProvider,
    PaymentProviderNotConfigured,
    PaymentProviderDryRun,
    PaymentTestScopeViolation,
)

log = logging.getLogger("lumino_provider")


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _allowlist() -> List[str]:
    raw = _env("PAYMENTS_TEST_ALLOWLIST_CUSTOMERS")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _is_production() -> bool:
    return _env("APP_ENV").lower() == "production"


# Synthetic-tenant email domains that are ALWAYS test fixtures.
# User directive · Feb 2026: NO LIVE CUSTOMERS in any test flow.
_SYNTHETIC_DOMAINS = ("@aquaterra.com", "@plofv.com")


def _is_synthetic_fixture(customer_ref: str) -> bool:
    if not customer_ref:
        return False
    cr = customer_ref.lower()
    if any(cr.endswith(d) for d in _SYNTHETIC_DOMAINS):
        return True
    return customer_ref in _allowlist()


def _enforce_test_scope(customer_ref: str, kind: str) -> None:
    """Refuse the call in non-production unless the customer is
    provably a synthetic fixture or on the explicit allow-list."""
    if _is_production():
        return
    if _is_synthetic_fixture(customer_ref):
        return
    log.error("PaymentTestScopeViolation refused %s call for customer_ref=%r "
                "(not synthetic, not on PAYMENTS_TEST_ALLOWLIST_CUSTOMERS)",
                kind, customer_ref)
    raise PaymentTestScopeViolation(
        f"non-production {kind} call targets a non-synthetic customer "
        f"({customer_ref!r}). Add to PAYMENTS_TEST_ALLOWLIST_CUSTOMERS "
        f"only after explicit go-ahead. NO LIVE CUSTOMERS in test flows."
    )


def _dry_run_response(kind: str, **fields) -> Dict[str, Any]:
    return {
        "status": "dry_run",
        "provider": "lumino",
        "kind": kind,
        "session_id": f"prev_{uuid.uuid4().hex[:16]}",
        **fields,
    }


class LuminoProvider(PaymentProvider):
    name = "lumino"

    def __init__(self):
        self.api_url = _env("LUMINO_API_URL")
        self.token = _env("LUMINO_API_TOKEN")
        self.webhook_secret = _env("LUMINO_WEBHOOK_SECRET")
        self.return_url = _env("LUMINO_RETURN_URL")
        self._configured = bool(self.api_url and self.token)
        if not self._configured:
            log.warning("LuminoProvider not configured — LUMINO_API_URL / "
                          "LUMINO_API_TOKEN missing. Every call will raise "
                          "PaymentProviderNotConfigured until env is populated.")

    # ── Preview dry-run gate ──────────────────────────────────────
    def _dry_run_or_die(self, *, kind: str, customer_ref: str,
                              **fields) -> None:
        if _is_production():
            return
        # First check the hard scope rail — refuse anything non-synthetic.
        _enforce_test_scope(customer_ref, kind)
        # Even synthetic fixtures short-circuit unless allow-listed
        # (Brian's explicit smoke-test window). The safety rail
        # above already ensures we only ever reach here for
        # synthetic OR allow-listed refs, so an "in allowlist" check
        # here means "yes, actually hit the wire".
        if customer_ref in _allowlist():
            return
        raise PaymentProviderDryRun(_dry_run_response(kind,
                                                          customer_ref=customer_ref,
                                                          **fields))

    def _require_configured(self) -> None:
        if not self._configured:
            raise PaymentProviderNotConfigured(
                "Lumino env vars missing — set LUMINO_API_URL + "
                "LUMINO_API_TOKEN before calling this method."
            )

    # ── Provider methods ──────────────────────────────────────────
    async def create_customer(self, *, email, name=None, metadata=None,
                                     idempotency_key=None):
        # Preview short-circuit uses email as the customer_ref proxy
        # (Lumino customers don't exist yet at this point).
        self._dry_run_or_die(kind="create_customer", customer_ref=email)
        self._require_configured()
        # TODO(phase2): POST {api_url}/v1/customers with Idempotency-Key.
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def create_setup_session(self, *, customer_ref, return_url,
                                         idempotency_key=None):
        self._dry_run_or_die(kind="setup_session", customer_ref=customer_ref,
                                 return_url=return_url)
        self._require_configured()
        # TODO(phase2): POST {api_url}/v1/vaulting/sessions
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def list_vaulted_methods(self, *, customer_ref):
        if not _is_production() and customer_ref not in _allowlist():
            raise PaymentProviderDryRun(_dry_run_response(
                "list_vaulted_methods", customer_ref=customer_ref, methods=[],
            ))
        self._require_configured()
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def create_payment_session(self, *, customer_ref, amount_cents,
                                          currency, description=None,
                                          metadata=None, off_session=False,
                                          method_ref=None, idempotency_key=None):
        self._dry_run_or_die(kind="payment_session",
                                 customer_ref=customer_ref,
                                 amount_cents=amount_cents,
                                 currency=currency)
        self._require_configured()
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def create_subscription(self, *, customer_ref, plan_ref,
                                        metadata=None, idempotency_key=None):
        self._dry_run_or_die(kind="subscription",
                                 customer_ref=customer_ref, plan_ref=plan_ref)
        self._require_configured()
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def cancel_subscription(self, *, subscription_ref,
                                        idempotency_key=None):
        # No customer_ref here — dry-run always in non-prod.
        if not _is_production():
            raise PaymentProviderDryRun(_dry_run_response(
                "cancel_subscription", subscription_ref=subscription_ref,
            ))
        self._require_configured()
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    async def create_refund(self, *, transaction_ref, amount_cents=None,
                                 reason=None, idempotency_key=None):
        if not _is_production():
            raise PaymentProviderDryRun(_dry_run_response(
                "refund", transaction_ref=transaction_ref,
                amount_cents=amount_cents,
            ))
        self._require_configured()
        raise PaymentProviderNotConfigured("phase2: not implemented yet")

    # ── Webhooks ──────────────────────────────────────────────────
    def verify_webhook(self, *, raw_body: bytes,
                             signature_header: str) -> bool:
        if not self.webhook_secret:
            log.warning("Lumino webhook received but LUMINO_WEBHOOK_SECRET "
                          "not set — refusing to verify.")
            return False
        digest = hmac.new(
            self.webhook_secret.encode("utf-8"),
            raw_body, hashlib.sha256,
        ).hexdigest()
        # Accept "sha256=<hex>" and bare hex — Lumino's exact format
        # to be confirmed at Phase 2 kickoff.
        candidate = (signature_header or "").split("=", 1)[-1].strip()
        return hmac.compare_digest(digest, candidate)

    def parse_webhook_event(self, *, raw_body: bytes) -> Dict[str, Any]:
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
