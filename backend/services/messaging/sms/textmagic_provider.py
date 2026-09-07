"""Phase I1.7.b · Feb-2026 — TextMagic SMS provider."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from .._helpers import load_provider_config, now_iso, sms_testmode_mock
from ..models import (
    ConnectionHealth,
    MessagingError,
    SmsInboundEvent,
    SmsResult,
    SmsStatus,
    TenantMessagingNotConnected,
)
from .base import SmsProvider


log = logging.getLogger("messaging.sms.textmagic")

_TM_API_BASE = "https://rest.textmagic.com/api/v2"


class TextMagicSmsProvider(SmsProvider):
    provider_key = "textmagic"
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "username":  {"required": True, "secret": False, "label": "TextMagic username"},
        "api_key":   {"required": True, "secret": True,  "label": "API key"},
        "from_number": {"required": False, "secret": False, "label": "From number (optional)"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no TextMagic config")
        return cfg

    def _headers(self, cfg: Dict[str, Any]) -> Dict[str, str]:
        return {"X-TM-Username": cfg["username"], "X-TM-Key": cfg["api_key"]}

    async def send_sms(
        self, *, tenant_id: str, to: str, body: str,
        media_urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SmsResult:
        if sms_testmode_mock():
            return SmsResult(
                id=f"TM_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        data: Dict[str, Any] = {"text": body, "phones": to}
        if cfg.get("from_number"):
            data["from"] = cfg["from_number"]
        client = await self._client()
        try:
            r = await client.post(
                f"{_TM_API_BASE}/messages",
                data=data,
                headers=self._headers(cfg),
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"TEXTMAGIC_{r.status_code}",
                    message=f"send_sms HTTP {r.status_code}",
                )
                return SmsResult(
                    id="", status="failed", to=to,
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    raw=j, error=f"textmagic HTTP {r.status_code}",
                )
            await mark_used(tenant_id, self.provider_key)
            return SmsResult(
                id=str(j.get("id") or ""),
                status="queued",
                to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except Exception as e:
            log.warning("textmagic send_sms failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="TEXTMAGIC_EXCEPTION",
                                     message=type(e).__name__)
            return SmsResult(
                id="", status="failed", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={}, error=type(e).__name__,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def get_status(
        self, *, tenant_id: str, message_id: str,
    ) -> SmsStatus:
        if sms_testmode_mock():
            return SmsStatus(id=message_id, status="delivered",
                              provider_key=self.provider_key, tenant_id=tenant_id,
                              raw={"mock": True})
        cfg = await self._cfg(tenant_id)
        client = await self._client()
        try:
            r = await client.get(
                f"{_TM_API_BASE}/messages/{message_id}",
                headers=self._headers(cfg),
            )
            j = r.json() if r.content else {}
            return SmsStatus(
                id=message_id, status=(j.get("status") or "unknown"),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> SmsInboundEvent:
        import json
        try:
            body_text = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            data = json.loads(body_text)
            return SmsInboundEvent(
                id=str(data.get("id", "")),
                from_number=data.get("sender", ""),
                to_number=data.get("receiver", ""),
                body=data.get("text", ""),
                provider_key=self.provider_key, tenant_id=None,
                raw=data,
            )
        except Exception as e:
            raise MessagingError(f"textmagic webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No TextMagic config saved for this tenant.",
                checked_at=now_iso(),
            )
        if sms_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        client = await self._client()
        try:
            r = await client.get(f"{_TM_API_BASE}/user", headers=self._headers(cfg))
            if r.status_code == 200:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="TextMagic User.get returned OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"TextMagic probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"TextMagic probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
