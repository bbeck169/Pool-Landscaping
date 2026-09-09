"""Feb-2026 · P0 comms hotfix → generalized BYO empty-credential
fallback helpers.

Extracted from ``services.messaging.byo_passthrough`` so the same
guard + credential-failure heuristic can gate the AI and Maps BYO
dispatchers without duplicating the substring list. Behaviour is
identical for messaging (imported by that module for backwards
compat).

Public surface:
  * :func:`byo_required_fields_present` — inspect a provider
    object's ``config_fields`` schema + the tenant's saved config
    and return ``False`` when any ``required=True`` field is
    missing / ``None`` / empty string / whitespace-only.
  * :func:`looks_like_credential_failure` — coarse substring
    match on an error string to decide "BYO auth broken → fall
    back to platform" vs "real send-time / API failure → surface".

Cap-exceeded detection stays in ``byo_passthrough`` — this module
is credential-shape-only so we don't accidentally weaken cap
semantics on the AI or Maps dispatchers.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional


log = logging.getLogger("byo.common")


# Substrings we treat as "the BYO provider's credentials are
# broken" and therefore signal a fall-back to the platform
# provider. Kept coarse on purpose — over-matching here means one
# extra platform call, under-matching leaves the user with silent
# failures. Prefer the former.
CREDENTIAL_ERROR_MARKERS = (
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
    "no openai config",
    "no anthropic config",
    "no gemini config",
    "no google maps config",
    "no mapbox config",
    "tenantmessagingnotconnected",
    "tenantainotconnected",
    "tenantmapsnotconnected",
    "missing required",
    "missing api",
    "empty api",
    "invalid credentials",
    "invalid_credentials",
    "api key not valid",
    "api_key is required",
    "incorrect api key",
    "incorrect_api_key",
)


def looks_like_credential_failure(error: Optional[str]) -> bool:
    """Return True when the BYO provider raised an error whose
    text looks like an auth / credentials issue rather than a
    legitimate send-time failure."""
    if not error:
        return False
    e = error.lower()
    return any(marker in e for marker in CREDENTIAL_ERROR_MARKERS)


async def byo_required_fields_present(
    provider: Any,
    tenant_id: str,
    *,
    config_loader: Callable[..., Awaitable[Optional[dict]]],
    db=None,
) -> bool:
    """Return True iff every required secret field on the
    provider's ``config_fields`` schema resolves to a non-blank
    string in the tenant's saved config.

    ``config_loader`` is passed in so each caller (messaging / AI /
    maps) uses ITS OWN ``load_provider_config`` helper — the
    encrypted secrets store is shared but each dispatcher scopes
    the read differently. Signature must accept keyword arguments
    ``tenant_id``, ``provider_key``, and optionally ``db``.

    Guarantees:
      * Never raises. On lookup failure, returns ``False`` (safer
        to fall back than to blast the platform key).
      * Ignores optional fields (``required=False`` or missing).
      * Treats ``None`` / empty string / whitespace-only as
        missing.
    """
    provider_key = getattr(provider, "provider_key", None) or ""
    try:
        cfg = await config_loader(
            tenant_id=tenant_id,
            provider_key=provider_key,
            db=db,
        ) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "[byo.common] config load failed tenant=%s provider=%s: %s",
            tenant_id, provider_key, exc,
        )
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
                tenant_id, provider_key, name,
            )
            return False
    return True
