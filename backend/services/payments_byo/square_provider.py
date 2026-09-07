"""Phase I1.7.d · Feb-2026 — Square BYO payments provider.

Docs: https://developer.squareup.com/reference/square
Sandbox base URL: https://connect.squareupsandbox.com/v2
Production: https://connect.squareup.com/v2

Webhook signature: HMAC-SHA256(notification_url + body, signature_key),
header ``x-square-hmacsha256-signature``, base64-encoded. In test-mode
we short-circuit signature verification to hex HMAC over ``body`` only
so unit tests are hermetic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
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


log = logging.getLogger("payments_byo.square")


class SquareProvider(PaymentsByoProvider):
    provider_key = "pay_square"
    short_name = "square"
    primary_secret_field = "access_token"
    webhook_signature_header = "x-square-hmacsha256-signature"

    config_fields: Dict[str, Dict[str, Any]] = {
        "access_token":       {"required": True, "secret": True,  "label": "Square Access Token"},
        "location_id":        {"required": True, "secret": False, "label": "Location ID"},
        "environment":        {"required": False, "secret": False, "label": "Environment (sandbox|production)"},
        "webhook_signing_key": {"required": True, "secret": True,  "label": "Webhook Signing Key"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    def _base_url(self, cfg: Dict[str, Any]) -> str:
        env = (cfg.get("environment") or "sandbox").lower()
        return ("https://connect.squareup.com/v2" if env == "production"
                else "https://connect.squareupsandbox.com/v2")

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantPaymentsNotConnected(f"Tenant {tenant_id} has no Square config")
        return cfg

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
                id=f"sq_ch_test_{idk[:12]}", status="succeeded",
                amount_cents=amount_cents, currency=currency.upper(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "idempotency_key": idk},
            )
        token = cfg.get("access_token", "")
        location_id = cfg.get("location_id", "")
        client = await self._client()
        try:
            r = await client.post(
                f"{self._base_url(cfg)}/payments",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json",
                         "Square-Version": "2024-01-18"},
                json={
                    "source_id": payment_method_id or "cnon:card-nonce-ok",
                    "idempotency_key": idk,
                    "amount_money": {"amount": int(amount_cents),
                                       "currency": currency.upper()},
                    "location_id": location_id,
                    "note": description or "",
                },
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"SQUARE_{r.status_code}",
                    message=f"create_charge HTTP {r.status_code}",
                )
                return ChargeResult(
                    id="", status="failed", amount_cents=amount_cents,
                    currency=currency, provider_key=self.provider_key,
                    tenant_id=tenant_id, error=f"square HTTP {r.status_code}", raw=j,
                )
            await mark_used(tenant_id, self.provider_key)
            payment = (j.get("payment") or {})
            return ChargeResult(
                id=payment.get("id", ""),
                status="succeeded" if payment.get("status") == "COMPLETED" else "pending",
                amount_cents=int((payment.get("amount_money") or {}).get("amount", amount_cents)),
                currency=(payment.get("amount_money") or {}).get("currency", currency.upper()),
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
                id=f"sq_rf_test_{idk[:12]}", charge_id=charge_id,
                status="succeeded", amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        token = cfg.get("access_token", "")
        client = await self._client()
        try:
            payload: Dict[str, Any] = {
                "idempotency_key": idk, "payment_id": charge_id,
                "reason": reason or "",
            }
            if amount_cents is not None:
                payload["amount_money"] = {"amount": int(amount_cents), "currency": "USD"}
            r = await client.post(
                f"{self._base_url(cfg)}/refunds",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json",
                         "Square-Version": "2024-01-18"},
                json=payload,
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                return RefundResult(
                    id="", charge_id=charge_id, status="failed",
                    amount_cents=int(amount_cents or 0),
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    error=f"square HTTP {r.status_code}", raw=j,
                )
            rf = (j.get("refund") or {})
            return RefundResult(
                id=rf.get("id", ""), charge_id=charge_id,
                status="succeeded" if rf.get("status") in ("COMPLETED", "PENDING") else "failed",
                amount_cents=int((rf.get("amount_money") or {}).get("amount", amount_cents or 0)),
                provider_key=self.provider_key, tenant_id=tenant_id, raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def verify_webhook(
        self, *, tenant_id: str, payload: bytes, headers: Dict[str, str],
    ) -> WebhookEvent:
        cfg = await self._cfg(tenant_id)
        signing_key = cfg.get("webhook_signing_key", "")
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        provided = hdrs.get(self.webhook_signature_header, "")
        if not provided:
            raise WebhookSignatureInvalid("missing square signature header")
        if payments_testmode_mock():
            expected = hmac_sha256_hex(secret=signing_key, payload=payload)
            if not constant_time_equals(expected, provided):
                raise WebhookSignatureInvalid("bad square signature")
        else:
            notification_url = hdrs.get("x-square-notification-url", "")
            hasher = hmac.new(signing_key.encode("utf-8"),
                                (notification_url + payload.decode("utf-8", "replace")).encode("utf-8"),
                                hashlib.sha256)
            expected_b64 = base64.b64encode(hasher.digest()).decode("ascii")
            if not hmac.compare_digest(expected_b64, provided):
                raise WebhookSignatureInvalid("bad square signature")
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:
            body = {}
        return WebhookEvent(
            id=str(body.get("event_id") or body.get("id") or uuid.uuid4().hex),
            event_type=str(body.get("type") or body.get("event_type") or "unknown"),
            provider_key=self.provider_key, tenant_id=tenant_id, raw=body,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Square config saved for this tenant.",
                checked_at=now_iso(),
            )
        if payments_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        token = cfg.get("access_token", "")
        client = await self._client()
        try:
            r = await client.get(
                f"{self._base_url(cfg)}/locations",
                headers={"Authorization": f"Bearer {token}",
                         "Square-Version": "2024-01-18"},
            )
            if r.status_code == 200:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="Square /locations OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Square probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Square probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
