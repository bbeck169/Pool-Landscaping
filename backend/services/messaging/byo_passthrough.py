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


async def _byo_required_fields_present(
    provider: Any, tenant_id: str, db=None,
) -> bool:
    """Return True iff every required secret field on the provider's
    ``config_fields`` schema resolves to a non-blank string in the
    tenant's saved config.

    Feb-2026 · P0 comms hotfix — the tenant-BYO write path
    (``save_provider_config``) marks the row ``connected=True`` as
    soon as ``validate_config`` accepts the input, even though the
    key is never live-probed. Users who typed a mangled Resend key
    (or blanked the field after a partial save) end up with a
    ``connected=True`` row whose ``api_key`` is empty / whitespace.
    ``get_tenant_*_provider`` then hands back a provider whose every
    outbound call raises with an empty-auth error, and the
    passthrough returns ``_envelope_failed(...)`` — which the
    adapter treats as authoritative and NEVER falls back to the
    platform provider. Result: both channels silently break the
    moment BYOP is "connected" but not valid.

    This guard runs before the BYO provider is invoked. When it
    returns False, the caller returns ``None`` and the send falls
    through to the platform key. When it returns True, the send
    routes through the BYO provider as usual (cap-exceeded and
    genuine send failures continue to surface via envelopes).
    """
    try:
        from ._helpers import load_provider_config
        cfg = await load_provider_config(
            tenant_id=tenant_id,
            provider_key=getattr(provider, "provider_key", ""),
            db=db,
        ) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[byo] config load failed tenant=%s provider=%s: %s",
                    tenant_id, getattr(provider, "provider_key", "?"), exc)
        return False
    schema = getattr(provider, "config_fields", {}) or {}
    for name, meta in schema.items():
        if not meta.get("required"):
            continue
        val = cfg.get(name)
        if not isinstance(val, str) or not val.strip():
            log.warning(
                "[byo] tenant=%s provider=%s required field %r is "
                "blank/missing — falling back to platform provider",
                tenant_id, getattr(provider, "provider_key", "?"), name,
            )
            return False
    return True

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


# Feb-2026 · P0 comms hotfix — substrings we treat as "the BYO
# provider's credentials are broken" and therefore we should fall
# back to the platform provider rather than bubble a failed
# envelope. Kept coarse on purpose — over-matching here means one
# extra platform send, under-matching leaves the user with silent
# failures. Prefer the former.
_CREDENTIAL_ERROR_MARKERS = (
    "unauthorized",
    "unauthorised",
    "401",
    "403",
    "authentication",
    "invalid api key",
    "invalid_api_key",
    "no resend config",
    "no ringcentral config",
    "no twilio config",
    "no textmagic config",
    "tenantmessagingnotconnected",
    "missing required",
    "missing api",
    "empty api",
    "invalid credentials",
    "invalid_credentials",
    "api key not valid",
    "api_key is required",
)


def _looks_like_credential_failure(error: Optional[str]) -> bool:
    """Return True when the BYO provider raised an error whose
    text looks like an authentication / credential issue rather
    than a legitimate send-time failure."""
    if not error:
        return False
    e = error.lower()
    return any(marker in e for marker in _CREDENTIAL_ERROR_MARKERS)


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

    # Feb-2026 · P0 comms hotfix — fall back to platform when the
    # tenant's BYO row is "connected" on paper but has empty
    # required credentials (see :func:`_byo_required_fields_present`).
    if not await _byo_required_fields_present(provider, tenant_id, db=db):
        return None

    provider_key = getattr(provider, "provider_key", "unknown")
    # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit.
    # BYO probe still fires (this branch = tenant HAS a BYO provider
    # configured), only the provider's outbound HTTP call is skipped.
    # Deterministic envelope so idempotency + delivery-status
    # classification behave identically to a real send.
    from .testmode import is_messaging_testmode, mock_email_envelope
    if is_messaging_testmode():
        env = mock_email_envelope(
            tenant_id=tenant_id, to=to, subject=subject,
            routed_via="tenant_byo_testmode_mock",
        )
        env["provider"] = provider_key
        return env
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
        # Feb-2026 · P0 comms hotfix — credential-shaped failures
        # (auth 401/403, "unauthorized", missing key) mean the BYO
        # row itself is broken; fall through to the platform key
        # instead of returning a failed envelope that would strand
        # the send. Non-credential failures still return the
        # envelope so ops can see real provider errors.
        if _looks_like_credential_failure(err):
            log.warning(
                "[byo] email tenant=%s provider=%s credential-shaped "
                "failure — falling back to platform: %s",
                tenant_id, provider_key, err,
            )
            return None
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

    # Feb-2026 · P0 comms hotfix — same guard as the email path.
    if not await _byo_required_fields_present(provider, tenant_id, db=db):
        return None

    provider_key = getattr(provider, "provider_key", "unknown")
    # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit.
    # See mirror comment in ``try_dispatch_email_tenant_byo``.
    from .testmode import is_messaging_testmode, mock_sms_envelope
    if is_messaging_testmode():
        env = mock_sms_envelope(
            tenant_id=tenant_id, to=to, body=body,
            routed_via="tenant_byo_testmode_mock",
        )
        env["provider"] = provider_key
        return env
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
        if _looks_like_credential_failure(err):
            log.warning(
                "[byo] sms tenant=%s provider=%s credential-shaped "
                "failure — falling back to platform: %s",
                tenant_id, provider_key, err,
            )
            return None
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
