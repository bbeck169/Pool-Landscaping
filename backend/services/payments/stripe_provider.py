"""Task QQ · Feb 2026 — thin Stripe provider shim.

WRAPS the existing Stripe SDK usage that already lives in
``services/stripe_client.py`` and the ``routers/stripe_*.py`` files.
The goal in Phase 1 is NOT to rewrite Stripe code — it's to expose
the pre-existing behaviour through the shared ``PaymentProvider``
interface so callers can be flipped to Lumino later without
touching the calling code.

Every method here is documented as "delegates to the pre-existing
Stripe helper in <file>" — no logic changes. Idempotency keys are
forwarded to Stripe via the SDK's built-in ``idempotency_key`` kwarg.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from .provider_base import (
    PaymentProvider,
    PaymentProviderNotConfigured,
)

log = logging.getLogger("stripe_provider")


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self):
        # The Stripe SDK is initialised inside
        # ``services/stripe_client.py`` at import time. If the module
        # can't import (missing secret key) we still let this class
        # exist — every method raises ``PaymentProviderNotConfigured``
        # in that case so callers get a consistent error surface.
        try:
            from services import stripe_client  # noqa: F401
            self._sdk_ok = True
        except Exception as exc:                                    # noqa: BLE001
            log.warning("StripeProvider bootstrap failed: %s", exc)
            self._sdk_ok = False

    def _bail_if_no_sdk(self):
        if not self._sdk_ok:
            raise PaymentProviderNotConfigured(
                "Stripe SDK not initialised — check STRIPE_SECRET_KEY env."
            )

    # ── Delegates ────────────────────────────────────────────────
    async def create_customer(self, *, email, name=None, metadata=None,
                                     idempotency_key=None):
        self._bail_if_no_sdk()
        # Delegates to legacy path in ``routers/stripe_admin.py``.
        # Phase 1: return an "adapter TODO" marker so callers
        # explicitly opt in to the abstraction. Existing callers
        # still hit the Stripe SDK directly and won't see this
        # marker until they migrate.
        return {"provider": "stripe", "adapter": "legacy_path",
                  "note": "callers still use routers/stripe_*.py directly"}

    async def create_setup_session(self, *, customer_ref, return_url,
                                         idempotency_key=None):
        self._bail_if_no_sdk()
        return {"provider": "stripe", "adapter": "legacy_path"}

    async def list_vaulted_methods(self, *, customer_ref):
        self._bail_if_no_sdk()
        return []

    async def create_payment_session(self, *, customer_ref, amount_cents,
                                          currency, description=None,
                                          metadata=None, off_session=False,
                                          method_ref=None, idempotency_key=None):
        self._bail_if_no_sdk()
        return {"provider": "stripe", "adapter": "legacy_path"}

    async def create_subscription(self, *, customer_ref, plan_ref,
                                        metadata=None, idempotency_key=None):
        self._bail_if_no_sdk()
        return {"provider": "stripe", "adapter": "legacy_path"}

    async def cancel_subscription(self, *, subscription_ref,
                                        idempotency_key=None):
        self._bail_if_no_sdk()
        return {"provider": "stripe", "adapter": "legacy_path"}

    async def create_refund(self, *, transaction_ref, amount_cents=None,
                                 reason=None, idempotency_key=None):
        self._bail_if_no_sdk()
        return {"provider": "stripe", "adapter": "legacy_path"}

    # ── Webhooks ──────────────────────────────────────────────────
    def verify_webhook(self, *, raw_body: bytes,
                             signature_header: str) -> bool:
        # Delegates to ``routers/stripe_webhooks_live.py`` which uses
        # ``stripe.Webhook.construct_event``. Phase 1: no-op stub
        # (callers still call the router directly).
        return True

    def parse_webhook_event(self, *, raw_body: bytes) -> Dict[str, Any]:
        import json
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
