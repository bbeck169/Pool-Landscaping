"""Phase I1.7.d · Feb-2026 — Authorize.Net BYO payments provider.

Docs: https://developer.authorize.net/api/reference/index.html
Sandbox: https://apitest.authorize.net/xml/v1/request.api
Production: https://api.authorize.net/xml/v1/request.api

Webhook signature: HMAC-SHA512(body, signature_key), header
``X-ANET-Signature: sha512={hex_uppercase}``. In test-mode we accept
the same header but as lowercase hex (matches the shared HMAC helper).
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
    hmac_sha512_hex,
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


log = logging.getLogger("payments_byo.authnet")


class AuthorizeNetProvider(PaymentsByoProvider):
    provider_key = "pay_authnet"
    short_name = "authnet"
    primary_secret_field = "transaction_key"
    webhook_signature_header = "x-anet-signature"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_login_id":       {"required": True, "secret": False, "label": "API Login ID"},
        "transaction_key":    {"required": True, "secret": True,  "label": "Transaction Key"},
        "environment":        {"required": False, "secret": False, "label": "Environment (sandbox|production)"},
        "signature_key":      {"required": True, "secret": True,  "label": "Webhook Signature Key"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    def _base_url(self, cfg: Dict[str, Any]) -> str:
        env = (cfg.get("environment") or "sandbox").lower()
        return ("https://api.authorize.net/xml/v1/request.api" if env == "production"
                else "https://apitest.authorize.net/xml/v1/request.api")

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantPaymentsNotConnected(f"Tenant {tenant_id} has no Authorize.Net config")
        return cfg

    def _auth_block(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": cfg.get("api_login_id", ""),
            "transactionKey": cfg.get("transaction_key", ""),
        }

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
                id=f"an_ch_test_{idk[:12]}", status="succeeded",
                amount_cents=amount_cents, currency=currency.upper(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "idempotency_key": idk},
            )
        client = await self._client()
        try:
            payload = {
                "createTransactionRequest": {
                    "merchantAuthentication": self._auth_block(cfg),
                    "refId": idk[:20],
                    "transactionRequest": {
                        "transactionType": "authCaptureTransaction",
                        "amount": f"{amount_cents / 100:.2f}",
                        "payment": {"opaqueData": {
                            "dataDescriptor": "COMMON.ACCEPT.INAPP.PAYMENT",
                            "dataValue": payment_method_id or "",
                        }},
                        "order": {"description": (description or "")[:255]},
                    },
                }
            }
            r = await client.post(
                self._base_url(cfg),
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            j = r.json() if r.content else {}
            resp = (j.get("transactionResponse") or {})
            if r.status_code >= 400 or (j.get("messages") or {}).get("resultCode") == "Error":
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"AUTHNET_{r.status_code}",
                    message=f"create_charge HTTP {r.status_code}",
                )
                return ChargeResult(
                    id="", status="failed", amount_cents=amount_cents,
                    currency=currency, provider_key=self.provider_key,
                    tenant_id=tenant_id, error=f"authnet HTTP {r.status_code}", raw=j,
                )
            await mark_used(tenant_id, self.provider_key)
            return ChargeResult(
                id=str(resp.get("transId", "")),
                status="succeeded" if resp.get("responseCode") == "1" else "pending",
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
                id=f"an_rf_test_{idk[:12]}", charge_id=charge_id,
                status="succeeded", amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        client = await self._client()
        try:
            payload = {
                "createTransactionRequest": {
                    "merchantAuthentication": self._auth_block(cfg),
                    "refId": idk[:20],
                    "transactionRequest": {
                        "transactionType": "refundTransaction",
                        "amount": f"{(amount_cents or 0) / 100:.2f}",
                        "refTransId": charge_id,
                    },
                }
            }
            r = await client.post(
                self._base_url(cfg),
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            j = r.json() if r.content else {}
            resp = (j.get("transactionResponse") or {})
            if r.status_code >= 400 or (j.get("messages") or {}).get("resultCode") == "Error":
                return RefundResult(
                    id="", charge_id=charge_id, status="failed",
                    amount_cents=int(amount_cents or 0),
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    error=f"authnet HTTP {r.status_code}", raw=j,
                )
            return RefundResult(
                id=str(resp.get("transId", "")), charge_id=charge_id,
                status="succeeded" if resp.get("responseCode") == "1" else "failed",
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
        signing_key = cfg.get("signature_key", "")
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        provided_raw = hdrs.get(self.webhook_signature_header, "")
        provided = provided_raw.replace("sha512=", "").strip()
        if not provided:
            raise WebhookSignatureInvalid("missing authnet signature header")
        expected = hmac_sha512_hex(secret=signing_key, payload=payload)
        if not constant_time_equals(expected, provided):
            raise WebhookSignatureInvalid("bad authnet signature")
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:
            body = {}
        return WebhookEvent(
            id=str(body.get("notificationId") or body.get("id") or uuid.uuid4().hex),
            event_type=str(body.get("eventType") or "unknown"),
            provider_key=self.provider_key, tenant_id=tenant_id, raw=body,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Authorize.Net config saved for this tenant.",
                checked_at=now_iso(),
            )
        if payments_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        client = await self._client()
        try:
            r = await client.post(
                self._base_url(cfg),
                headers={"Content-Type": "application/json"},
                json={"authenticateTestRequest": {
                    "merchantAuthentication": self._auth_block(cfg),
                }},
            )
            j = r.json() if r.content else {}
            ok = ((j.get("messages") or {}).get("resultCode") == "Ok")
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=ok,
                message="Authorize.Net authenticateTest OK." if ok else "Authorize.Net authenticateTest failed.",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Authorize.Net probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
