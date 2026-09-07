"""Phase I1.7.b · Feb-2026 — RingCentral SMS provider (tenant-scoped).

Wraps the existing platform RingCentral integration (``services.
ringcentral.rc_client`` / ``services.sms.rc_adapter``). A tenant that
provides its own RingCentral credentials via the settings UI gets
routed through this provider; otherwise the ``dispatch`` layer will
fall back to the platform default and log to
``platform_messaging_fallback_log``.

Note: RingCentral SMS operates over the RC OAuth-issued platform
extension. The ``config`` stored per-tenant is the JWT / password
grant used to instantiate a per-tenant SDK client. Because the SDK
call surface is synchronous and heavy, the concrete send path is
delegated to a small async wrapper so tests can inject a mock client.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

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


log = logging.getLogger("messaging.sms.ringcentral")


class RingCentralSmsProvider(SmsProvider):
    provider_key = "ringcentral"

    config_fields: Dict[str, Dict[str, Any]] = {
        "server_url":   {"required": True, "secret": False, "label": "Server URL (e.g. https://platform.ringcentral.com)"},
        "client_id":    {"required": True, "secret": False, "label": "App Client ID"},
        "client_secret": {"required": True, "secret": True, "label": "App Client Secret"},
        "jwt_token":    {"required": True, "secret": True,  "label": "JWT token (or username/password auth)"},
        "from_number":  {"required": True, "secret": False, "label": "From number (E.164)"},
    }

    def __init__(self, sdk_factory: Optional[Any] = None) -> None:
        self._factory = sdk_factory   # injectable for tests

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no RingCentral config")
        return cfg

    def _get_platform(self, cfg: Dict[str, Any]) -> Any:
        if self._factory is not None:
            return self._factory(cfg)
        # Real path uses the ringcentral SDK. Keep the import lazy so
        # test-mode never has to pull the SDK.
        from ringcentral import SDK  # type: ignore
        rc = SDK(cfg["client_id"], cfg["client_secret"], cfg["server_url"])
        platform = rc.platform()
        platform.login(jwt=cfg["jwt_token"])
        return platform

    async def send_sms(
        self, *, tenant_id: str, to: str, body: str,
        media_urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SmsResult:
        if sms_testmode_mock():
            return SmsResult(
                id=f"rc_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        try:
            platform = self._get_platform(cfg)
            req = {
                "from": {"phoneNumber": cfg["from_number"]},
                "to": [{"phoneNumber": to}],
                "text": body or "",
            }
            if media_urls:
                # RC needs a separate attachment endpoint for MMS;
                # for the adapter surface we degrade to text-with-url
                # so the message still delivers on SMS-only accounts.
                req["text"] = (req["text"] + "\n" + "\n".join(media_urls)).strip()
            resp = platform.post("/restapi/v1.0/account/~/extension/~/sms", req)
            j: Dict[str, Any] = {}
            try:
                j = resp.json_dict() if hasattr(resp, "json_dict") else (resp.json() if hasattr(resp, "json") else {})
            except Exception:
                j = {}
            await mark_used(tenant_id, self.provider_key)
            return SmsResult(
                id=str(j.get("id") or ""),
                status=(j.get("messageStatus") or "queued").lower(),
                to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except Exception as e:
            log.warning("ringcentral send_sms failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="RC_EXCEPTION",
                                     message=type(e).__name__)
            return SmsResult(
                id="", status="failed", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={}, error=type(e).__name__,
            )

    async def get_status(self, *, tenant_id: str, message_id: str) -> SmsStatus:
        if sms_testmode_mock():
            return SmsStatus(id=message_id, status="delivered",
                              provider_key=self.provider_key, tenant_id=tenant_id,
                              raw={"mock": True})
        cfg = await self._cfg(tenant_id)
        try:
            platform = self._get_platform(cfg)
            resp = platform.get(f"/restapi/v1.0/account/~/extension/~/message-store/{message_id}")
            j = resp.json_dict() if hasattr(resp, "json_dict") else {}
            return SmsStatus(
                id=message_id,
                status=(j.get("messageStatus") or "unknown").lower(),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except Exception as e:
            raise MessagingError(f"rc get_status failed: {type(e).__name__}") from e

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> SmsInboundEvent:
        import json
        try:
            data = json.loads(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload)
            body_obj = (data.get("body") or {})
            return SmsInboundEvent(
                id=str(body_obj.get("id", data.get("uuid", ""))),
                from_number=(body_obj.get("from") or {}).get("phoneNumber", ""),
                to_number=((body_obj.get("to") or [{}])[0] or {}).get("phoneNumber", ""),
                body=body_obj.get("subject", ""),
                provider_key=self.provider_key, tenant_id=None,
                raw=data,
            )
        except Exception as e:
            raise MessagingError(f"rc webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No RingCentral config saved for this tenant.",
                checked_at=now_iso(),
            )
        if sms_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        try:
            platform = self._get_platform(cfg)
            resp = platform.get("/restapi/v1.0/account/~/extension/~")
            _ = resp.json_dict() if hasattr(resp, "json_dict") else None
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="RingCentral extension.get OK.",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"RingCentral probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
