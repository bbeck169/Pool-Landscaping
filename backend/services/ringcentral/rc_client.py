"""Phase 6 · RingCentral service client — JWT-bearer OAuth + HTTPX.

Wraps the RC REST API for the CRM. Uses raw ``httpx.AsyncClient`` (not
the sync RC Python SDK) so we can share the app's existing async
plumbing.

Auth
====
* JWT bearer: ``POST {RC_SERVER_URL}/restapi/oauth/token`` with
  ``grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`` +
  ``assertion=<RC_JWT>``, HTTP Basic (client_id + client_secret).
* Access token is cached in-process (per-tenant). Refresh proactively
  60 seconds before ``expires_in``.

Rate limit
==========
* On 429 read ``Retry-After``; up to 3 retries with exponential-ish
  backoff (`Retry-After` × attempt); WARN log on hit.

Secret handling
===============
* JWT + client_secret NEVER echoed to logs / HTTP responses. Startup
  banner logs only the masked JWT ``sub`` (last 4 of extension id).

TODO
====
Per-tenant DB-backed RC credentials (``RingCentralService('tenant-x')``
would then load overrides from ``tenants`` collection). Ship env-based
today; DB path when we onboard a second tenant with its own RC account.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any, Dict, Optional

import httpx

from config import logger

_TOKEN_CACHE: Dict[str, Dict[str, Any]] = {}


class RingCentralError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"RingCentral error {status}: {str(body)[:200]}")


class RingCentralService:
    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self.server_url = (os.getenv("RC_SERVER_URL") or "https://platform.ringcentral.com").rstrip("/")
        self.client_id = os.getenv("RC_CLIENT_ID") or ""
        self.client_secret = os.getenv("RC_CLIENT_SECRET") or ""
        self.jwt = os.getenv("RC_JWT") or ""
        self.mode = os.getenv("RC_MODE") or "live"

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.jwt)

    async def _fetch_access_token(self) -> Dict[str, Any]:
        if not self.is_configured():
            raise RingCentralError(503, "RingCentral not configured")
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=15) as cx:
            r = await cx.post(
                f"{self.server_url}/restapi/oauth/token",
                headers={"Authorization": f"Basic {auth}",
                          "Content-Type": "application/x-www-form-urlencoded",
                          "Accept": "application/json"},
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self.jwt,
                },
            )
        if r.status_code != 200:
            # Redact body; RC error bodies do not echo the JWT but be
            # defensive anyway.
            body = r.text[:300]
            logger.warning(f"[phase6] RC token exchange failed status={r.status_code}")
            raise RingCentralError(r.status_code, body)
        return r.json()

    async def get_token(self, force: bool = False) -> str:
        cached = _TOKEN_CACHE.get(self.tenant_id)
        now = time.time()
        if cached and not force and cached.get("expires_at", 0) - 60 > now:
            return cached["access_token"]
        payload = await self._fetch_access_token()
        tok = {
            "access_token": payload["access_token"],
            "expires_at": now + int(payload.get("expires_in") or 3600),
        }
        _TOKEN_CACHE[self.tenant_id] = tok
        return tok["access_token"]

    async def _request(self, method: str, path: str, *,
                        json: Optional[dict] = None,
                        params: Optional[dict] = None,
                        retry_401: bool = True) -> Any:
        for attempt in range(1, 4):
            token = await self.get_token()
            async with httpx.AsyncClient(timeout=20) as cx:
                r = await cx.request(
                    method, f"{self.server_url}{path}",
                    headers={"Authorization": f"Bearer {token}",
                             "Accept": "application/json",
                             "Content-Type": "application/json"},
                    json=json, params=params,
                )
            if r.status_code == 429 and attempt < 3:
                backoff = int(r.headers.get("Retry-After") or "1") * attempt
                logger.warning(f"[phase6] RC 429 — retry_in={backoff}s attempt={attempt}")
                await asyncio.sleep(backoff)
                continue
            if r.status_code == 401 and retry_401 and attempt < 3:
                await self.get_token(force=True)
                continue
            if r.status_code >= 400:
                raise RingCentralError(r.status_code, _safe_body(r))
            if not r.content:
                return None
            try:
                return r.json()
            except Exception:
                return r.text
        raise RingCentralError(429, "Rate limit exceeded")

    async def ring_out(self, from_number: str, to_number: str) -> Dict[str, Any]:
        body = {"from": {"phoneNumber": from_number},
                "to": {"phoneNumber": to_number},
                "playPrompt": False}
        return await self._request(
            "POST", "/restapi/v1.0/account/~/extension/~/ring-out",
            json=body,
        )

    async def get_my_extension(self) -> Dict[str, Any]:
        return await self._request("GET", "/restapi/v1.0/account/~/extension/~")

    async def create_subscription(self, webhook_url: str,
                                    verification_token: str,
                                    event_filters: list[str]) -> Dict[str, Any]:
        delivery: Dict[str, Any] = {"transportType": "WebHook", "address": webhook_url}
        if verification_token:
            # RC accepts alphanumeric 8-64 chars, but some accounts reject
            # it via the CMN-101 code. Omit when not needed — the built-in
            # ``Validation-Token`` handshake still authenticates the setup.
            delivery["verificationToken"] = verification_token
        body = {
            "eventFilters": event_filters,
            "deliveryMode": delivery,
            "expiresIn": 630720000,
        }
        try:
            return await self._request("POST", "/restapi/v1.0/subscription", json=body)
        except RingCentralError as e:
            if verification_token and "verificationToken" in str(e.body):
                # Retry without the token (some RC accounts reject it).
                delivery.pop("verificationToken", None)
                return await self._request("POST", "/restapi/v1.0/subscription", json=body)
            raise

    async def list_subscriptions(self) -> Dict[str, Any]:
        return await self._request("GET", "/restapi/v1.0/subscription")

    async def delete_subscription(self, subscription_id: str) -> None:
        await self._request(
            "DELETE", f"/restapi/v1.0/subscription/{subscription_id}",
        )


def _safe_body(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return r.text[:400]


def log_startup_banner() -> None:
    jwt = os.getenv("RC_JWT") or ""
    sub_last4 = "----"
    try:
        import base64 as _b64, json as _json
        payload_b64 = jwt.split(".")[1] + "=="
        claims = _json.loads(_b64.urlsafe_b64decode(payload_b64.encode()))
        sub_last4 = (claims.get("sub") or "")[-4:]
    except Exception:
        pass
    server = (os.getenv("RC_SERVER_URL") or "").replace("https://", "")
    logger.info(f"[phase6] ringcentral mode={os.getenv('RC_MODE') or 'unset'} "
                f"sub=…{sub_last4} server={server}")
