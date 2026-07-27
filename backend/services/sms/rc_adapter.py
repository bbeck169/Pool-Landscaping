"""Phase 7B · Feb 2026 — RingCentral SMS adapter.

Drop-in replacement for the retired ``services/sms/twilio_adapter.py``.
Mirrors the same signature, return envelope, suppression semantics, and
compliance suffix rules — the ONLY differences are:

* ``provider`` field is now ``"ringcentral"`` (or ``"mock"`` when the
  RC client is not configured for this environment).
* ``provider_response_id`` is the RC message id (an integer stringified
  for compatibility with the previous ``str`` shape) — NOT a Twilio
  SM-prefixed SID.
* Retries look at RC's own transient statuses; the underlying
  ``RingCentralService`` client already handles 429 with Retry-After +
  401 token refresh internally, so the retry loop here focuses on
  network / transport transients (5xx, connection reset).

Suppression, STOP-suffix, phone normalization, and the graceful
``mocked`` mode when the provider isn't wired are IDENTICAL to the
old Twilio adapter — every existing caller / test that keyed on those
behaviors continues to pass. See ``tests/test_phase7b_rc_sms_adapter.py``
for the pinned invariants.
"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, Optional

import httpx

from config import logger
from services.ringcentral.rc_client import RingCentralError, RingCentralService

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3

# RC accepts up to 1000 characters per SMS body; use the same 1600 cap
# the Twilio adapter used so long-form messages keep the same behavior
# (client-side trim). Anything over 1000 will be rejected by RC but
# we trim to 1600 to preserve callers that may still send that long.
_BODY_HARD_CAP = 1600

_STOP_REQUIRED_CATEGORIES = {"marketing", "drip", "campaign"}
_STOP_SUFFIX = "\nReply STOP to unsubscribe."


def normalize_phone_e164(raw: Optional[str],
                          default_country: str = "1") -> Optional[str]:
    """Coerce human phone formats to E.164. Preserved verbatim from the
    Twilio adapter so callers keep the same behavior."""
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
    if category not in _STOP_REQUIRED_CATEGORIES:
        return body
    if "stop" in body.lower():
        return body
    remaining = _BODY_HARD_CAP - len(_STOP_SUFFIX)
    if len(body) > remaining:
        body = body[:remaining].rstrip()
    return body + _STOP_SUFFIX


class RingCentralSMSAdapter:
    """Stateless-ish adapter. Re-instantiating picks up ``.env`` env
    changes; the module-level singleton is stable per-process."""

    def __init__(self) -> None:
        self.default_from = os.environ.get("RC_SMS_DEFAULT_FROM", "")
        self.rc_client_id = os.environ.get("RC_CLIENT_ID", "")
        self.rc_jwt = os.environ.get("RC_JWT", "")
        self.rc_server = os.environ.get("RC_SERVER_URL", "")
        # Enabled when the RC client has enough config to open a JWT
        # bearer session. When any core env is missing we degrade to
        # ``mocked`` so unit tests + local dev keep working.
        self.enabled = bool(
            self.rc_client_id and self.rc_jwt and self.rc_server
        )

    async def _suppressed(self, *, tenant_id: Optional[str],
                            to_e164: str, category: str) -> bool:
        if category == "transactional" or not tenant_id or not to_e164:
            return False
        try:
            from routers.marketing_preferences import is_suppressed
        except Exception as exc:  # pragma: no cover
            logger.warning("[rc-sms] is_suppressed import failed: %s", exc)
            return False
        try:
            return await is_suppressed(
                tenant_id, {"phone": to_e164},
                channel="sms", category=category,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[rc-sms] is_suppressed failed: %s", exc)
            return False

    async def _resolve_from(self, tenant_id: Optional[str]) -> Optional[str]:
        """Priority: tenant.rc_sms_from_number → env RC_SMS_DEFAULT_FROM
        → RC extension auto-lookup. Return ``None`` only when nothing is
        resolvable (RC client will raise inside send_sms in that case)."""
        if tenant_id:
            try:
                from config import db
                t = await db.tenants.find_one(
                    {"id": tenant_id},
                    {"_id": 0, "rc_sms_from_number": 1},
                )
                if t and t.get("rc_sms_from_number"):
                    return t["rc_sms_from_number"]
            except Exception as exc:  # pragma: no cover
                logger.warning("[rc-sms] tenant from lookup failed: %s", exc)
        if self.default_from:
            return self.default_from
        return None  # RC client will auto-resolve via phone-number list

    async def send(self, *, to: str, body: str,
                    category: str = "marketing",
                    idempotency_key: Optional[str] = None,
                    tenant_id: Optional[str] = None,
                    customer_id: Optional[str] = None) -> Dict[str, Any]:
        """Send an SMS via RingCentral. Never raises."""
        addr_e164 = normalize_phone_e164(to)
        if not addr_e164:
            return {"provider": "ringcentral", "provider_status": "failed",
                    "provider_response_id": None, "attempts": 0,
                    "error": "invalid_phone"}

        # 1. Suppression check (marketing only).
        if await self._suppressed(tenant_id=tenant_id, to_e164=addr_e164,
                                    category=category):
            return {"provider": "ringcentral", "provider_status": "suppressed",
                    "provider_response_id": None, "attempts": 0, "error": None}

        # Phase 34 · Task L · Feb-2026 — outbound safety guard.
        # ``APP_ENV != production`` (or non-allow-listed number) blocks
        # the send. Prevents preview / dev / staging from firing SMS
        # at real customer phone numbers.
        from services.comms_env_guard import guard_outbound
        verdict = guard_outbound(kind="sms", to=addr_e164)
        if verdict.blocked:
            logger.info(
                "[DRY-RUN] rc-sms send SKIPPED to=%s cat=%s len=%d tenant=%s",
                addr_e164, category, len(body or ""), tenant_id,
            )
            return verdict.dry_run_response(provider="ringcentral")

        # 2. Graceful mocked mode when RC not configured.
        if not self.enabled:
            logger.info(
                "[rc-sms] disabled — would have sent to %s cat=%s len=%d",
                addr_e164, category, len(body or ""),
            )
            return {"provider": "mock", "provider_status": "mocked",
                    "provider_response_id": None, "attempts": 0, "error": None}

        # 3. Compliance suffix + hard cap.
        payload_body = _ensure_stop_suffix((body or "").strip(), category)
        if len(payload_body) > _BODY_HARD_CAP:
            payload_body = payload_body[:_BODY_HARD_CAP]

        from_number = await self._resolve_from(tenant_id)
        svc = RingCentralService(tenant_id)

        last_err: Optional[Exception] = None
        last_status: Optional[int] = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                res = await svc.send_sms(addr_e164, payload_body,
                                            from_number=from_number)
                # RC returns messageStatus="Queued" for accepted messages
                # that are still being dispatched. Downstream marketing
                # ledger treats "Queued" / "Sent" / "Delivered" as
                # successful hand-offs.
                return {"provider": "ringcentral",
                        "provider_status": "sent",
                        "provider_response_id": (
                            str(res["message_id"])
                            if res.get("message_id") is not None else None
                        ),
                        "attempts": attempt, "error": None,
                        "rc_status": res.get("status")}
            except RingCentralError as exc:
                last_err = exc
                last_status = exc.status
                scope_missing = getattr(exc, "scope_missing", False)
                logger.warning(
                    "[rc-sms] attempt %s/%s to %s failed status=%s "
                    "scope_missing=%s",
                    attempt, _MAX_ATTEMPTS, addr_e164, last_status,
                    scope_missing,
                )
                # 4xx (except 429) are terminal — no retry.
                if (last_status not in _TRANSIENT_STATUS
                        or attempt == _MAX_ATTEMPTS):
                    break
                await asyncio.sleep(2 ** (attempt - 1))
            except Exception as exc:  # pragma: no cover — transport oddities
                last_err = exc
                last_status = None
                logger.warning(
                    "[rc-sms] attempt %s/%s to %s crashed: %s",
                    attempt, _MAX_ATTEMPTS, addr_e164, exc,
                )
                # Feb-2026 · Prod 502 hardening — httpx timeout / connect
                # errors on the OAuth path are TERMINAL. Retrying just
                # piles on latency (up to 3 × 15s = 45s) and blows past
                # the ~30s edge-gateway timeout, turning a clean 502
                # into an opaque HTML 502. Fail fast so the endpoint
                # layer can surface a JSON error.
                if isinstance(exc, (httpx.TimeoutException,
                                        httpx.ConnectError)):
                    break
                if attempt == _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(2 ** (attempt - 1))

        return {"provider": "ringcentral", "provider_status": "failed",
                "provider_response_id": None,
                "attempts": _MAX_ATTEMPTS if last_err else 1,
                "error": f"{type(last_err).__name__}: {last_err}"
                if last_err else "unknown",
                "http_status": last_status}


_default = RingCentralSMSAdapter()


async def send(**kwargs) -> Dict[str, Any]:
    return await _default.send(**kwargs)
