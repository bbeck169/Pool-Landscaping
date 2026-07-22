"""Feb 2026 · Slice S — Twilio SMS adapter (real send).

Mirrors the Slice N Resend adapter architecture:
* Category-aware suppression pre-check (:pyclass:`marketing_suppressions`).
* Non-blocking send via ``asyncio.to_thread`` around the sync SDK.
* Retry with exponential backoff on 429 / 5xx (max 3 attempts).
* Idempotency-key + status-callback headers forwarded.
* Compliance: auto-appends ``Reply STOP to unsubscribe`` to marketing
  + drip categories; transactional messages are exempt.

Returns a standardised delivery record consumable by
``marketing_deliveries``:

.. code-block:: python

    {
        "provider": "twilio" | "mock",
        "provider_status": "sent" | "suppressed" | "failed" | "mocked",
        "provider_response_id": str | None,   # Twilio's message SID
        "attempts": int,
        "error": str | None,
    }
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, Optional

from config import logger

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3

# Twilio hard cap per message body (concatenated SMS also caps here).
_BODY_HARD_CAP = 1600

# Categories that require the compliance opt-out suffix per Twilio
# guidance.  Transactional / review-request / one-off account messages
# do not require it (they're user-initiated / expected).
_STOP_REQUIRED_CATEGORIES = {"marketing", "drip", "campaign"}
_STOP_SUFFIX = "\nReply STOP to unsubscribe."


def normalize_phone_e164(raw: Optional[str],
                          default_country: str = "1") -> Optional[str]:
    """Coerce human phone formats to E.164.  Returns ``None`` when the
    input has fewer than 10 digits — Twilio rejects short numbers with a
    permanent 400 anyway.

    Accepts:
        (623) 887-8060  →  +16238878060
        623.887.8060    →  +16238878060
        +16238878060    →  +16238878060
        16238878060     →  +16238878060
    """
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("+"):
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) < 10:
            return None
        return "+" + digits
    digits = re.sub(r"[^\d]", "", s)
    if len(digits) == 10:
        return f"+{default_country}{digits}"
    if len(digits) == 11:
        return f"+{digits}"
    if len(digits) < 10:
        return None
    return f"+{digits}"


def _ensure_stop_suffix(body: str, category: str) -> str:
    """Auto-append the opt-out suffix on marketing/drip categories when
    the body doesn't already include it (case-insensitive)."""
    if category not in _STOP_REQUIRED_CATEGORIES:
        return body
    if "stop" in body.lower():
        return body
    remaining = _BODY_HARD_CAP - len(_STOP_SUFFIX)
    if len(body) > remaining:
        body = body[:remaining].rstrip()
    return body + _STOP_SUFFIX


class TwilioSMSAdapter:
    """Stateless-ish adapter.  Re-instantiating picks up ``.env`` env
    changes; the module-level singleton is stable per-process."""

    def __init__(self) -> None:
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.api_key_sid = os.environ.get("TWILIO_API_KEY_SID", "")
        self.api_key_secret = os.environ.get("TWILIO_API_KEY_SECRET", "")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
        self.status_callback = os.environ.get("TWILIO_STATUS_CALLBACK_URL") or None
        # Prefer API-Key auth (more granular + rotatable). Fall back to
        # the account SID + main auth token if API keys aren't set.
        placeholder = self.account_sid.startswith(("AC_placeholder", "AC000000"))
        has_api_key = bool(self.api_key_sid and self.api_key_secret)
        has_auth_token = bool(self.auth_token)
        self.enabled = (
            bool(self.account_sid and self.from_number)
            and (has_api_key or has_auth_token)
            and not placeholder
        )

    async def _suppressed(self, *, tenant_id: Optional[str],
                            to_e164: str, category: str) -> bool:
        if category == "transactional" or not tenant_id or not to_e164:
            return False
        try:
            from routers.marketing_preferences import is_suppressed
        except Exception as exc:  # pragma: no cover
            logger.warning("[twilio] is_suppressed import failed: %s", exc)
            return False
        try:
            return await is_suppressed(
                tenant_id, {"phone": to_e164},
                channel="sms", category=category,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[twilio] is_suppressed failed: %s", exc)
            return False

    async def send(self, *, to: str, body: str,
                    category: str = "marketing",
                    idempotency_key: Optional[str] = None,
                    tenant_id: Optional[str] = None,
                    customer_id: Optional[str] = None) -> Dict[str, Any]:
        """Send an SMS via Twilio.  Never raises."""
        addr_e164 = normalize_phone_e164(to)
        if not addr_e164:
            return {"provider": "twilio", "provider_status": "failed",
                    "provider_response_id": None, "attempts": 0,
                    "error": "invalid_phone"}

        # 1. Suppression check (marketing only).
        if await self._suppressed(tenant_id=tenant_id, to_e164=addr_e164,
                                    category=category):
            return {"provider": "twilio", "provider_status": "suppressed",
                    "provider_response_id": None, "attempts": 0, "error": None}

        # 2. Graceful mocked mode.
        if not self.enabled:
            logger.info(
                "[twilio] disabled — would have sent to %s cat=%s len=%d",
                addr_e164, category, len(body or ""),
            )
            return {"provider": "mock", "provider_status": "mocked",
                    "provider_response_id": None, "attempts": 0, "error": None}

        # 3. Compliance suffix + hard cap.
        payload_body = _ensure_stop_suffix((body or "").strip(), category)
        if len(payload_body) > _BODY_HARD_CAP:
            payload_body = payload_body[:_BODY_HARD_CAP]

        create_kwargs: Dict[str, Any] = {
            "to": addr_e164,
            "from_": self.from_number,
            "body": payload_body,
        }
        if self.status_callback:
            create_kwargs["status_callback"] = self.status_callback

        last_err = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                from twilio.rest import Client
                # Prefer API-Key auth if configured.
                if self.api_key_sid and self.api_key_secret:
                    client = Client(self.api_key_sid,
                                     self.api_key_secret,
                                     self.account_sid)
                else:
                    client = Client(self.account_sid, self.auth_token)
                msg = await asyncio.to_thread(
                    client.messages.create, **create_kwargs,
                )
                return {"provider": "twilio", "provider_status": "sent",
                        "provider_response_id": getattr(msg, "sid", None),
                        "attempts": attempt, "error": None}
            except Exception as exc:  # pragma: no cover — network path
                last_err = exc
                code = _extract_status(exc)
                logger.warning(
                    "[twilio] attempt %s/%s to %s failed status=%s err=%s",
                    attempt, _MAX_ATTEMPTS, addr_e164, code, exc,
                )
                if code not in _TRANSIENT_STATUS or attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(2 ** (attempt - 1))

        return {"provider": "twilio", "provider_status": "failed",
                "provider_response_id": None,
                "attempts": _MAX_ATTEMPTS if last_err else 1,
                "error": f"{type(last_err).__name__}: {last_err}"
                if last_err else "unknown"}


def _extract_status(exc: Any) -> Optional[int]:
    code = getattr(exc, "status", None)
    if isinstance(code, int):
        return code
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    return None


_default = TwilioSMSAdapter()


async def send(**kwargs) -> Dict[str, Any]:
    return await _default.send(**kwargs)
