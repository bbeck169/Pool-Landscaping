"""Feb-2026 · Payment Processor Failover · StripeByoProvider.

Thin adapter that lets ``services.payments_byo``'s primary/backup
failover router treat Stripe as a first-class BYO peer alongside
Square / PayPal / Authorize.Net / Lumino.

Why an adapter (not a rewrite): the customer-facing pay path already
runs through ``services.payments.stripe_charge``'s free functions
(``charge_card_on_file``, ``create_setup_intent``, refund helpers).
This class forwards to those helpers so the failover router speaks a
uniform contract (``PaymentsByoProvider``) while every existing
call-site keeps working byte-identically.

Auth: Stripe is env-driven at the pod level (``STRIPE_SECRET_KEY_*``);
we do NOT store per-tenant Stripe secrets in ``services.secrets``.
``test_connection`` therefore probes the pod's Stripe API key with
``Account.retrieve`` rather than reading a tenant-scoped config blob.

Scope note (Ticket Feb-2026 Payment Processors, Option 1): only the
four operations that admit a meaningful cross-provider failover are
implemented on this class — ``create_charge``, ``refund_charge``,
``verify_webhook``, ``test_connection``. Stripe-idiomatic operations
(``create_setup_intent``, ``list_payment_methods``, etc.) stay on
``stripe_charge`` and are NOT part of the failover surface.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

from services.payments import stripe_charge as _sc

from ._helpers import now_iso, payments_testmode_mock
from .models import (
    ChargeResult,
    ConnectionHealth,
    RefundResult,
    WebhookEvent,
    WebhookSignatureInvalid,
)
from .tenant_base import PaymentsByoProvider


log = logging.getLogger("payments_byo.stripe")


class StripeByoProvider(PaymentsByoProvider):
    """Stripe adapter for the payments-BYO failover router."""

    provider_key = "pay_stripe"
    short_name = "stripe"
    #: Stripe is env-driven — no per-tenant secret field.
    primary_secret_field = None
    webhook_signature_header = "stripe-signature"

    #: Presented as informational only. The Ticket UI reads
    #: ``is_configured`` from :meth:`is_configured` (env check),
    #: not from stored tenant secrets.
    config_fields: Dict[str, Dict[str, Any]] = {}

    # ── Configuration probes ──────────────────────────────────────
    @staticmethod
    def is_configured() -> bool:
        """True when the pod has a Stripe secret key resolved.

        Read-only environment probe — never touches Mongo. Mirrors
        ``stripe_charge._select_secret_key`` so the settings UI
        matches actual charge-time behaviour.
        """
        mode = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
        env_key = "STRIPE_SECRET_KEY_LIVE" if mode == "live" else "STRIPE_SECRET_KEY_TEST"
        return bool(
            (os.environ.get(env_key) or "").strip()
            or (os.environ.get("STRIPE_API_KEY") or "").strip()
        )

    # ── Payments-BYO contract ─────────────────────────────────────
    async def create_charge(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> ChargeResult:
        """Forward to ``stripe_charge.charge_card_on_file``.

        Mirrors the shape ``StripeRouter.post_charge`` uses so this
        adapter can slot in as a canary at the same call site.

        ``customer_id`` + ``payment_method_id`` are REQUIRED for
        Stripe — off_session card charges have no meaning without
        them. Missing either surfaces as a normalized ``failed``
        :class:`ChargeResult` (not an exception) so the failover
        router can distinguish "provider transient" from "user
        input bad".
        """
        idk = idempotency_key or uuid.uuid4().hex
        if payments_testmode_mock():
            return ChargeResult(
                id=f"stripe_ch_test_{idk[:12]}",
                status="succeeded",
                amount_cents=amount_cents,
                currency=currency.lower(),
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "idempotency_key": idk},
            )
        if not (customer_id and payment_method_id):
            return ChargeResult(
                id="", status="failed",
                amount_cents=amount_cents, currency=currency.lower(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                error="stripe requires customer_id and payment_method_id",
                raw={},
            )
        try:
            res = await _sc.charge_card_on_file(
                tenant_id=tenant_id,
                customer_id=customer_id,
                payment_method_id=payment_method_id,
                amount_cents=amount_cents,
                currency=currency.lower(),
                description=description,
                metadata=metadata or None,
                idempotency_key=idk,
            )
        except _sc.ChargeAlreadySucceededError as exc:
            # Feb-2026 · double-charge guard from stripe_charge. Not a
            # transient error — the failover router MUST NOT retry
            # on backup because the primary succeeded. Surface as
            # succeeded so the caller renders "already paid".
            return ChargeResult(
                id=exc.payment_intent_id or "",
                status="succeeded",
                amount_cents=amount_cents,
                currency=currency.lower(),
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                error=None,
                raw={"already_paid": True},
            )
        return ChargeResult(
            id=str(res.get("payment_intent_id") or ""),
            status=str(res.get("status") or "unknown"),
            amount_cents=int(res.get("amount_cents") or amount_cents),
            currency=str(res.get("currency") or currency.lower()),
            provider_key=self.provider_key,
            tenant_id=tenant_id,
            raw=res,
        )

    async def refund_charge(
        self, *, tenant_id: str, charge_id: str,
        amount_cents: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> RefundResult:
        """Refund a Stripe PaymentIntent.

        Feb-2026 · Payment Processor ticket · Option 1: uses the raw
        Stripe SDK (through ``stripe_charge._to_thread`` + the
        module-level ``_stripe`` handle) so pytest can stub the
        client in tests without a live Stripe key.
        """
        idk = idempotency_key or uuid.uuid4().hex
        if payments_testmode_mock():
            return RefundResult(
                id=f"stripe_re_test_{idk[:12]}",
                charge_id=charge_id, status="succeeded",
                amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        try:
            _sc._init_api_key()
            kwargs: Dict[str, Any] = {
                "payment_intent": charge_id,
                "idempotency_key": idk,
            }
            if amount_cents is not None:
                kwargs["amount"] = int(amount_cents)
            if reason:
                kwargs["reason"] = reason
            resp = await _sc._to_thread(_sc._stripe.Refund.create, **kwargs)
            data = _sc._asdict(resp)
            return RefundResult(
                id=str(data.get("id") or ""),
                charge_id=charge_id,
                status=str(data.get("status") or "unknown"),
                amount_cents=int(data.get("amount") or (amount_cents or 0)),
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                raw=data,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "stripe refund_charge failed tenant=%s charge=%s: %s",
                tenant_id, charge_id, type(exc).__name__,
            )
            return RefundResult(
                id="", charge_id=charge_id, status="failed",
                amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                error=f"stripe refund failed: {type(exc).__name__}",
                raw={},
            )

    async def verify_webhook(
        self, *, tenant_id: str, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        """Verify a Stripe webhook envelope using the pod's shared
        secret. The failover router only needs the normalized
        :class:`WebhookEvent` output; the existing Stripe webhook
        handler (``stripe_router.post_webhook``) remains the source
        of truth for the actual event-dispatch pipeline."""
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        sig = hdrs.get(self.webhook_signature_header, "")
        if not sig:
            raise WebhookSignatureInvalid("missing stripe-signature header")
        try:
            event = _sc.verify_and_parse_webhook(payload=payload, sig_header=sig)
        except Exception as exc:  # noqa: BLE001
            raise WebhookSignatureInvalid(
                f"stripe webhook verify failed: {type(exc).__name__}"
            ) from exc
        return WebhookEvent(
            id=str(event.get("id") or ""),
            event_type=str(event.get("type") or "unknown"),
            provider_key=self.provider_key,
            tenant_id=tenant_id,
            raw=event,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        """Env-key health probe (``stripe.Account.retrieve``).

        Runs in the caller's request context; times itself so the
        settings UI can render "Connected · 128ms" per the Test
        Connection button spec.
        """
        if not self.is_configured():
            return ConnectionHealth(
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                ok=False,
                message="Stripe secret key is not configured on this pod.",
                checked_at=now_iso(),
            )
        if payments_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                ok=True,
                connected_account_id_masked=None,
                message="mock",
                checked_at=now_iso(),
            )
        try:
            _sc._init_api_key()
            resp = await _sc._to_thread(_sc._stripe.Account.retrieve)
            data = _sc._asdict(resp)
            acct = str(data.get("id") or "")
            masked = (
                f"{acct[:5]}…{acct[-4:]}"
                if acct and len(acct) > 8
                else acct or None
            )
            return ConnectionHealth(
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                ok=True,
                connected_account_id_masked=masked,
                message="Stripe Account.retrieve returned OK.",
                checked_at=now_iso(),
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionHealth(
                provider_key=self.provider_key,
                tenant_id=tenant_id,
                ok=False,
                message=f"Stripe probe failed: {type(exc).__name__}",
                checked_at=now_iso(),
            )
