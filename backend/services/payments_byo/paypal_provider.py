"""Phase I1.7.d · Feb-2026 — PayPal BYO payments provider.

Docs: https://developer.paypal.com/api/rest/
Sandbox: https://api-m.sandbox.paypal.com
Production: https://api-m.paypal.com

Webhook verification: PayPal recommends POST /v1/notifications/verify-webhook-signature
using ``PAYPAL-TRANSMISSION-ID / -SIG / -TIME / -CERT-URL`` + auth_algo. In
test-mode we short-circuit to HMAC-SHA256(payload) with the tenant's
``webhook_id`` as the shared secret so unit tests are hermetic.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from ._helpers import (
    constant_time_equals,
    hmac_sha256_hex,
    load_provider_config,
    now_iso,
    payments_testmode_mock,
)
from .models import (
    ChargeResult,
    ConnectionHealth,
    RefundResult,
    TenantPaymentsNotConnected,
    WebhookEvent,
    WebhookSignatureInvalid,
)
from .tenant_base import PaymentsByoProvider


log = logging.getLogger("payments_byo.paypal")


class PayPalProvider(PaymentsByoProvider):
    provider_key = "pay_paypal"
    short_name = "paypal"
    primary_secret_field = "client_secret"
    webhook_signature_header = "paypal-transmission-sig"

    config_fields: Dict[str, Dict[str, Any]] = {
        "client_id":        {"required": True, "secret": False, "label": "PayPal Client ID"},
        "client_secret":    {"required": True, "secret": True,  "label": "PayPal Client Secret"},
        "environment":      {"required": False, "secret": False, "label": "Environment (sandbox|production)"},
        "webhook_id":       {"required": True, "secret": True,  "label": "Webhook ID / Signing Secret"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    def _base_url(self, cfg: Dict[str, Any]) -> str:
        env = (cfg.get("environment") or "sandbox").lower()
        return ("https://api-m.paypal.com" if env == "production"
                else "https://api-m.sandbox.paypal.com")

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantPaymentsNotConnected(f"Tenant {tenant_id} has no PayPal config")
        return cfg

    async def _oauth_token(self, cfg: Dict[str, Any], client: httpx.AsyncClient) -> str:
        r = await client.post(
            f"{self._base_url(cfg)}/v1/oauth2/token",
            auth=(cfg.get("client_id", ""), cfg.get("client_secret", "")),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        r.raise_for_status()
        return (r.json() or {}).get("access_token", "")

    async def create_charge(
        self, *, tenant_id: str, amount_cents: int, currency: str,
        customer_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> ChargeResult:
        cfg = await self._cfg(tenant_id)
        idk = idempotency_key or uuid.uuid4().hex
        if payments_testmode_mock():
            return ChargeResult(
                id=f"pp_ord_test_{idk[:12]}", status="succeeded",
                amount_cents=amount_cents, currency=currency.upper(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "idempotency_key": idk},
            )
        client = await self._client()
        try:
            token = await self._oauth_token(cfg, client)
            amt = f"{amount_cents / 100:.2f}"
            r = await client.post(
                f"{self._base_url(cfg)}/v2/checkout/orders",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json",
                         "PayPal-Request-Id": idk},
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [{
                        "amount": {"currency_code": currency.upper(), "value": amt},
                        "description": description or "",
                    }],
                },
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"PAYPAL_{r.status_code}",
                    message=f"create_charge HTTP {r.status_code}",
                )
                return ChargeResult(
                    id="", status="failed", amount_cents=amount_cents,
                    currency=currency, provider_key=self.provider_key,
                    tenant_id=tenant_id, error=f"paypal HTTP {r.status_code}", raw=j,
                )
            await mark_used(tenant_id, self.provider_key)
            return ChargeResult(
                id=j.get("id", ""),
                status="succeeded" if j.get("status") in ("COMPLETED", "APPROVED") else "pending",
                amount_cents=amount_cents, currency=currency.upper(),
                provider_key=self.provider_key, tenant_id=tenant_id, raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def refund_charge(
        self, *, tenant_id: str, charge_id: str,
        amount_cents: Optional[int] = None,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> RefundResult:
        cfg = await self._cfg(tenant_id)
        idk = idempotency_key or uuid.uuid4().hex
        if payments_testmode_mock():
            return RefundResult(
                id=f"pp_rf_test_{idk[:12]}", charge_id=charge_id,
                status="succeeded", amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        client = await self._client()
        try:
            token = await self._oauth_token(cfg, client)
            payload: Dict[str, Any] = {"note_to_payer": reason or ""}
            if amount_cents is not None:
                payload["amount"] = {"value": f"{amount_cents / 100:.2f}",
                                        "currency_code": "USD"}
            r = await client.post(
                f"{self._base_url(cfg)}/v2/payments/captures/{charge_id}/refund",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json",
                         "PayPal-Request-Id": idk},
                json=payload,
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                return RefundResult(
                    id="", charge_id=charge_id, status="failed",
                    amount_cents=int(amount_cents or 0),
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    error=f"paypal HTTP {r.status_code}", raw=j,
                )
            return RefundResult(
                id=j.get("id", ""), charge_id=charge_id,
                status="succeeded" if j.get("status") in ("COMPLETED", "PENDING") else "failed",
                amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key, tenant_id=tenant_id, raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def verify_webhook(
        self, *, tenant_id: str, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        cfg = await self._cfg(tenant_id)
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        provided = hdrs.get(self.webhook_signature_header, "")
        webhook_id = cfg.get("webhook_id", "")
        if not provided:
            raise WebhookSignatureInvalid("missing paypal signature header")
        if payments_testmode_mock():
            expected = hmac_sha256_hex(secret=webhook_id, payload=payload)
            if not constant_time_equals(expected, provided):
                raise WebhookSignatureInvalid("bad paypal signature")
        else:
            client = await self._client()
            try:
                token = await self._oauth_token(cfg, client)
                verify_body = {
                    "auth_algo": hdrs.get("paypal-auth-algo", ""),
                    "cert_url": hdrs.get("paypal-cert-url", ""),
                    "transmission_id": hdrs.get("paypal-transmission-id", ""),
                    "transmission_sig": provided,
                    "transmission_time": hdrs.get("paypal-transmission-time", ""),
                    "webhook_id": webhook_id,
                    "webhook_event": json.loads(payload.decode("utf-8", "replace") or "{}"),
                }
                vr = await client.post(
                    f"{self._base_url(cfg)}/v1/notifications/verify-webhook-signature",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json=verify_body,
                )
                if vr.status_code >= 400 or (vr.json() or {}).get("verification_status") != "SUCCESS":
                    raise WebhookSignatureInvalid("paypal verification api rejected signature")
            finally:
                if self._http is None:
                    await client.aclose()
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:
            body = {}
        return WebhookEvent(
            id=str(body.get("id") or uuid.uuid4().hex),
            event_type=str(body.get("event_type") or "unknown"),
            provider_key=self.provider_key, tenant_id=tenant_id, raw=body,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No PayPal config saved for this tenant.",
                checked_at=now_iso(),
            )
        if payments_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        client = await self._client()
        try:
            _ = await self._oauth_token(cfg, client)
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="PayPal oauth2/token OK.",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"PayPal probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
