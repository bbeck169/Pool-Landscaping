"""Phase I1.7.d · Feb-2026 — Lumino BYO payments provider.

Lumino is Aquaterra's proprietary tenant-provider adapter (separate
from ``services.payments.lumino_provider`` which handles Zapier /
reconciliation glue). The BYO variant is a pure HMAC-SHA256 stub —
the platform-side integration will supply real base-URL + auth
semantics when we retire the Zapier glue in I1.7.e.

Webhook signature: HMAC-SHA256(body, webhook_secret), header
``X-Lumino-Signature: {hex}``.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

import httpx

from services.secrets import mark_used

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


log = logging.getLogger("payments_byo.lumino")


class LuminoProvider(PaymentsByoProvider):
    provider_key = "pay_lumino"
    short_name = "lumino"
    primary_secret_field = "api_key"
    webhook_signature_header = "x-lumino-signature"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":            {"required": True, "secret": True,  "label": "Lumino API Key"},
        "account_id":         {"required": True, "secret": False, "label": "Lumino Account ID"},
        "environment":        {"required": False, "secret": False, "label": "Environment (sandbox|production)"},
        "webhook_secret":     {"required": True, "secret": True,  "label": "Webhook Signing Secret"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    def _base_url(self, cfg: Dict[str, Any]) -> str:
        env = (cfg.get("environment") or "sandbox").lower()
        return ("https://api.lumino.aquaterra.internal/v1" if env == "production"
                else "https://api.sandbox.lumino.aquaterra.internal/v1")

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantPaymentsNotConnected(f"Tenant {tenant_id} has no Lumino config")
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
            await mark_used(tenant_id, self.provider_key)
            return ChargeResult(
                id=f"lm_ch_test_{idk[:12]}", status="succeeded",
                amount_cents=amount_cents, currency=currency.upper(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "idempotency_key": idk},
            )
        # Non-mock path — placeholder for real Lumino REST client.
        client = await self._client()
        try:
            r = await client.post(
                f"{self._base_url(cfg)}/charges",
                headers={"Authorization": f"Bearer {cfg.get('api_key', '')}",
                         "Content-Type": "application/json",
                         "Idempotency-Key": idk},
                json={"amount_cents": amount_cents, "currency": currency.upper(),
                        "account_id": cfg.get("account_id", ""),
                        "description": description or ""},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                return ChargeResult(
                    id="", status="failed", amount_cents=amount_cents,
                    currency=currency, provider_key=self.provider_key,
                    tenant_id=tenant_id, error=f"lumino HTTP {r.status_code}", raw=j,
                )
            await mark_used(tenant_id, self.provider_key)
            return ChargeResult(
                id=str(j.get("id", "")),
                status=str(j.get("status", "succeeded")),
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
                id=f"lm_rf_test_{idk[:12]}", charge_id=charge_id,
                status="succeeded", amount_cents=int(amount_cents or 0),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        client = await self._client()
        try:
            r = await client.post(
                f"{self._base_url(cfg)}/refunds",
                headers={"Authorization": f"Bearer {cfg.get('api_key', '')}",
                         "Content-Type": "application/json",
                         "Idempotency-Key": idk},
                json={"charge_id": charge_id,
                        "amount_cents": int(amount_cents or 0),
                        "reason": reason or ""},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                return RefundResult(
                    id="", charge_id=charge_id, status="failed",
                    amount_cents=int(amount_cents or 0),
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    error=f"lumino HTTP {r.status_code}", raw=j,
                )
            return RefundResult(
                id=str(j.get("id", "")), charge_id=charge_id,
                status=str(j.get("status", "succeeded")),
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
        signing_key = cfg.get("webhook_secret", "")
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        provided = hdrs.get(self.webhook_signature_header, "")
        if not provided:
            raise WebhookSignatureInvalid("missing lumino signature header")
        expected = hmac_sha256_hex(secret=signing_key, payload=payload)
        if not constant_time_equals(expected, provided):
            raise WebhookSignatureInvalid("bad lumino signature")
        try:
            body = json.loads(payload.decode("utf-8"))
        except Exception:
            body = {}
        return WebhookEvent(
            id=str(body.get("id") or uuid.uuid4().hex),
            event_type=str(body.get("event_type") or body.get("type") or "unknown"),
            provider_key=self.provider_key, tenant_id=tenant_id, raw=body,
        )

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Lumino config saved for this tenant.",
                checked_at=now_iso(),
            )
        if payments_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        # Non-mock probe hits /account and expects 200.
        client = await self._client()
        try:
            r = await client.get(
                f"{self._base_url(cfg)}/account",
                headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"},
            )
            ok = (r.status_code == 200)
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=ok,
                message="Lumino /account OK." if ok else f"Lumino probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Lumino probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
