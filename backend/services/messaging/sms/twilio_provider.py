"""Phase I1.7.b · Feb-2026 — Twilio SMS provider."""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Any, Dict, List, Optional

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from .._helpers import (
    email_testmode_mock,  # noqa: F401  (unused but keeps the parallel-import symmetric)
    load_provider_config,
    now_iso,
    sms_testmode_mock,
)
from ..models import (
    ConnectionHealth,
    MessagingError,
    SmsInboundEvent,
    SmsResult,
    SmsStatus,
    TenantMessagingNotConnected,
)
from .base import SmsProvider


log = logging.getLogger("messaging.sms.twilio")

_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioSmsProvider(SmsProvider):
    provider_key = "twilio"
    primary_secret_field = "auth_token"

    config_fields: Dict[str, Dict[str, Any]] = {
        "account_sid":  {"required": True,  "secret": False, "label": "Twilio Account SID"},
        "auth_token":   {"required": True,  "secret": True,  "label": "Auth Token"},
        "from_number":  {"required": True,  "secret": False, "label": "From number (E.164)"},
        "messaging_service_sid": {"required": False, "secret": False, "label": "Messaging Service SID (optional)"},
        "status_callback_url":   {"required": False, "secret": False, "label": "Delivery-status webhook URL"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client   # injectable for tests

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no Twilio config")
        return cfg

    async def send_sms(
        self, *, tenant_id: str, to: str, body: str,
        media_urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SmsResult:
        if sms_testmode_mock():
            return SmsResult(
                id=f"SM_test_{uuid.uuid4().hex[:24]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        sid = cfg["account_sid"]
        tok = cfg["auth_token"]
        auth_header = "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()
        data: Dict[str, Any] = {"To": to, "Body": body}
        if cfg.get("messaging_service_sid"):
            data["MessagingServiceSid"] = cfg["messaging_service_sid"]
        else:
            data["From"] = cfg["from_number"]
        if media_urls:
            data["MediaUrl"] = media_urls
        if cfg.get("status_callback_url"):
            data["StatusCallback"] = cfg["status_callback_url"]
        client = await self._client()
        try:
            r = await client.post(
                f"{_TWILIO_API_BASE}/Accounts/{sid}/Messages.json",
                data=data,
                headers={"Authorization": auth_header,
                          "Content-Type": "application/x-www-form-urlencoded"},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"TWILIO_{r.status_code}",
                    message=f"send_sms HTTP {r.status_code}",
                )
                return SmsResult(
                    id="", status="failed", to=to,
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    raw=j,
                    error=f"twilio HTTP {r.status_code}",
                )
            await mark_used(tenant_id, self.provider_key)
            return SmsResult(
                id=j.get("sid", ""),
                status=(j.get("status") or "queued"),
                to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except MessagingError:
            raise
        except Exception as e:
            log.warning("twilio send_sms failed: %s", type(e).__name__)
            await log_secret_error(
                tenant_id, self.provider_key,
                code="TWILIO_EXCEPTION",
                message=type(e).__name__,
            )
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
        sid = cfg["account_sid"]
        tok = cfg["auth_token"]
        auth_header = "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()
        client = await self._client()
        try:
            r = await client.get(
                f"{_TWILIO_API_BASE}/Accounts/{sid}/Messages/{message_id}.json",
                headers={"Authorization": auth_header},
            )
            j = r.json() if r.content else {}
            return SmsStatus(
                id=message_id,
                status=(j.get("status") or "unknown"),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> SmsInboundEvent:
        # Twilio signs inbound webhooks via ``X-Twilio-Signature`` —
        # verification requires the request URL, POST params and the
        # tenant's ``auth_token``. That's a router-layer concern
        # (needs the raw request URL); this method decodes the body
        # into an event given a pre-verified payload.
        try:
            fields = dict(headers)
            # Twilio uses form-urlencoded — decode manually.
            from urllib.parse import parse_qs
            params = {k: v[0] if v else "" for k, v in parse_qs(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload).items()}
            return SmsInboundEvent(
                id=params.get("MessageSid", ""),
                from_number=params.get("From", ""),
                to_number=params.get("To", ""),
                body=params.get("Body", ""),
                provider_key=self.provider_key,
                tenant_id=None,
                raw={"params": params, "headers": fields},
            )
        except Exception as e:
            raise MessagingError(f"twilio webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Twilio config saved for this tenant.",
                checked_at=now_iso(),
            )
        if sms_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, connected_account_id_masked=cfg.get("account_sid", "")[:5] + "…",
                message="mock", checked_at=now_iso(),
            )
        sid = cfg["account_sid"]
        tok = cfg["auth_token"]
        auth_header = "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()
        client = await self._client()
        try:
            r = await client.get(
                f"{_TWILIO_API_BASE}/Accounts/{sid}.json",
                headers={"Authorization": auth_header},
            )
            if r.status_code == 200:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, connected_account_id_masked=f"{sid[:5]}…{sid[-4:]}" if len(sid) > 8 else sid,
                    message="Twilio Account.retrieve returned OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Twilio probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Twilio probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
