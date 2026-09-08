"""Phase I1.7.e · chunk 1 · Feb-2026 — Tenant-BYO passthrough shim
for the four centralized messaging adapters.

Every existing SMS + email adapter in the codebase
(``services.comms_email_adapter``, ``services.comms_sms_adapter``,
``services.email.resend_adapter``, ``services.sms.rc_adapter``)
calls ``try_dispatch_email_tenant_byo`` / ``try_dispatch_sms_tenant_byo``
BEFORE its own last-mile SDK call. When the tenant has a BYO provider
configured, the send is routed through that provider and a
normalized envelope is returned (in a shape all four adapters can
consume). When no tenant provider is configured, the helper returns
``None`` and the caller proceeds with its existing platform path.

Cap-exceeded semantics (transactional vs bulk difference is enforced
at the callsite — this helper only NORMALIZES the signal):

  * The tenant's BYO provider returns HTTP 429 or an error containing
    ``429`` / ``cap`` / ``quota`` → envelope with
    ``provider_status="cap_exceeded"``, ``status="cap_exceeded"``,
    ``http_status=429``.
  * Transactional callsites use :func:`raise_if_cap_exceeded` to
    re-raise as ``HTTPException(429)`` up the FastAPI stack.
  * Bulk callsites (mass_messaging, marketing campaigns) map the
    envelope status to ``skipped_cap_exceeded`` in the delivery
    ledger and continue with the next recipient — no exception.

Tenant isolation invariant: :func:`try_dispatch_email_tenant_byo` /
:func:`try_dispatch_sms_tenant_byo` read the target tenant's provider
row on every call, so a cap exhaustion on tenant A cannot cause
tenant B's send to 429. The provider object itself is cached at the
registry layer but the cap accounting lives in the provider's own
upstream API (Twilio / SendGrid / Mailgun / etc.); its 429 response
is scoped to the tenant whose credentials were used.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .email.registry import get_tenant_email_provider
from .sms.registry import get_tenant_sms_provider


log = logging.getLogger("messaging.byo_passthrough")

CAP_EXCEEDED_STATUS = "cap_exceeded"
CAP_EXCEEDED_HTTP_STATUS = 429

# Substrings we treat as a cap / quota hit when they appear in a
# provider error message. Kept intentionally coarse — provider error
# copy is not standardized, and false positives here fail-safe (the
# transactional callsite will 429 instead of silently succeeding).
_CAP_ERROR_MARKERS = (
    "429",
    "too many requests",
    "monthly cap",
    "cap exceeded",
    "quota exceeded",
    "rate limit",
    "rate_limit",
    "limit reached",
)


def _looks_like_cap_hit(status: Optional[str], error: Optional[str]) -> bool:
    """Return True when the (status, error) pair from a tenant BYO
    provider indicates the tenant's outbound cap was hit."""
    s = (status or "").lower()
    if s in {"cap_exceeded", "over_quota", "quota_exceeded", "rate_limited"}:
        return True
    e = (error or "").lower()
    if not e:
        return False
    return any(marker in e for marker in _CAP_ERROR_MARKERS)


def _envelope_ok(*, provider_key: str, message_id: Optional[str],
                  raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a success envelope compatible with BOTH the legacy
    platform-adapter shape (``status`` / ``provider_id``) AND the
    modern adapter shape (``provider`` / ``provider_status`` /
    ``provider_response_id``)."""
    return {
        # Legacy platform-adapter shape (comms_email_adapter,
        # comms_sms_adapter):
        "status": "sent",
        "provider_id": message_id,
        # Modern adapter shape (resend_adapter, rc_adapter,
        # mass_messaging._classify_provider_status):
        "provider": provider_key,
        "provider_status": "sent",
        "provider_response_id": message_id,
        "attempts": 1,
        "error": None,
        "routed_via": "tenant_byo",
        "raw": raw,
    }


def _envelope_cap(*, provider_key: str, error: Optional[str]) -> Dict[str, Any]:
    return {
        "status": CAP_EXCEEDED_STATUS,
        "provider_id": None,
        "provider": provider_key,
        "provider_status": CAP_EXCEEDED_STATUS,
        "provider_response_id": None,
        "attempts": 1,
        "error": error or "monthly cap exceeded",
        "http_status": CAP_EXCEEDED_HTTP_STATUS,
        "routed_via": "tenant_byo",
    }


def _envelope_failed(*, provider_key: str, error: str) -> Dict[str, Any]:
    return {
        "status": "failed",
        "provider_id": None,
        "provider": provider_key,
        "provider_status": "failed",
        "provider_response_id": None,
        "attempts": 1,
        "error": error,
        "routed_via": "tenant_byo",
    }


# ─── Public probe helpers ─────────────────────────────────────────────
async def try_dispatch_email_tenant_byo(
    *,
    tenant_id: Optional[str],
    to: str,
    subject: str,
    html: Optional[str] = None,
    text: Optional[str] = None,
    from_addr: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db=None,
) -> Optional[Dict[str, Any]]:
    """Attempt a tenant-BYO email send. Return ``None`` when no
    tenant provider is configured (caller proceeds with its existing
    platform path). Return a normalized envelope when the BYO
    provider handled it (or hit its cap / errored). Never raises."""
    if not tenant_id or not to:
        return None
    try:
        provider = await get_tenant_email_provider(tenant_id, db=db)
    except Exception as exc:  # noqa: BLE001
        log.warning("[byo] email provider lookup failed tenant=%s: %s",
                    tenant_id, exc)
        return None
    if provider is None:
        return None

    provider_key = getattr(provider, "provider_key", "unknown")
    try:
        result = await provider.send_email(
            tenant_id=tenant_id,
            to=[to],
            subject=subject,
            html_body=html,
            text_body=text,
            from_addr=from_addr,
            from_name=from_name,
            attachments=None,
            reply_to=reply_to,
            metadata=metadata,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        if _looks_like_cap_hit(None, err):
            log.info("[byo] email cap-exceeded via exception tenant=%s "
                      "provider=%s: %s", tenant_id, provider_key, err)
            return _envelope_cap(provider_key=provider_key, error=err)
        log.warning("[byo] email BYO raised tenant=%s provider=%s: %s",
                    tenant_id, provider_key, err)
        return _envelope_failed(provider_key=provider_key, error=err)

    status = getattr(result, "status", None)
    err = getattr(result, "error", None)
    if _looks_like_cap_hit(status, err):
        log.info("[byo] email cap-exceeded tenant=%s provider=%s status=%s",
                 tenant_id, provider_key, status)
        return _envelope_cap(provider_key=provider_key, error=err)
    if status in ("sent", "queued", "delivered"):
        return _envelope_ok(
            provider_key=provider_key,
            message_id=getattr(result, "id", None),
            raw=getattr(result, "raw", {}) or {},
        )
    return _envelope_failed(
        provider_key=provider_key,
        error=err or f"tenant_byo_status={status}",
    )


async def try_dispatch_sms_tenant_byo(
    *,
    tenant_id: Optional[str],
    to: str,
    body: str,
    media_urls: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db=None,
) -> Optional[Dict[str, Any]]:
    """Attempt a tenant-BYO SMS send. Same contract as
    :func:`try_dispatch_email_tenant_byo`."""
    if not tenant_id or not to:
        return None
    try:
        provider = await get_tenant_sms_provider(tenant_id, db=db)
    except Exception as exc:  # noqa: BLE001
        log.warning("[byo] sms provider lookup failed tenant=%s: %s",
                    tenant_id, exc)
        return None
    if provider is None:
        return None

    provider_key = getattr(provider, "provider_key", "unknown")
    try:
        result = await provider.send_sms(
            tenant_id=tenant_id,
            to=to,
            body=body,
            media_urls=media_urls,
            metadata=metadata,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        if _looks_like_cap_hit(None, err):
            log.info("[byo] sms cap-exceeded via exception tenant=%s "
                      "provider=%s: %s", tenant_id, provider_key, err)
            return _envelope_cap(provider_key=provider_key, error=err)
        log.warning("[byo] sms BYO raised tenant=%s provider=%s: %s",
                    tenant_id, provider_key, err)
        return _envelope_failed(provider_key=provider_key, error=err)

    status = getattr(result, "status", None)
    err = getattr(result, "error", None)
    if _looks_like_cap_hit(status, err):
        log.info("[byo] sms cap-exceeded tenant=%s provider=%s status=%s",
                 tenant_id, provider_key, status)
        return _envelope_cap(provider_key=provider_key, error=err)
    if status in ("sent", "queued", "delivered"):
        return _envelope_ok(
            provider_key=provider_key,
            message_id=getattr(result, "id", None),
            raw=getattr(result, "raw", {}) or {},
        )
    return _envelope_failed(
        provider_key=provider_key,
        error=err or f"tenant_byo_status={status}",
    )


# ─── Callsite-side helpers ───────────────────────────────────────────
def is_cap_exceeded(envelope: Optional[Dict[str, Any]]) -> bool:
    """Return True when the send envelope indicates a cap-exceeded
    (429) result from a tenant BYO provider."""
    if not envelope:
        return False
    if envelope.get("status") == CAP_EXCEEDED_STATUS:
        return True
    if envelope.get("provider_status") == CAP_EXCEEDED_STATUS:
        return True
    if envelope.get("http_status") == CAP_EXCEEDED_HTTP_STATUS:
        return True
    return False


def raise_if_cap_exceeded(envelope: Optional[Dict[str, Any]],
                            *, detail: str = "Monthly messaging cap exceeded "
                                              "for this tenant") -> None:
    """Raise ``HTTPException(429)`` when the envelope indicates cap
    exhaustion. Transactional HTTP callsites should invoke this
    immediately after their adapter call so a cap hit surfaces as
    the correct HTTP status. Bulk / worker callsites should NOT call
    this — they must persist ``skipped_cap_exceeded`` in the ledger
    and continue with the next recipient."""
    if is_cap_exceeded(envelope):
        raise HTTPException(status_code=CAP_EXCEEDED_HTTP_STATUS,
                             detail=detail)
