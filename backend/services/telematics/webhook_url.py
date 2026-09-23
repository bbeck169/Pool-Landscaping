"""Phase P39 · Feb-2026 — HMAC URL-token signing for telematics webhooks.

The webhook URL handed to a tenant embeds a durable, non-expiring
HMAC token so we can verify the ``tenant_id`` + ``provider`` came
from us before we do any work:

    /api/tenants/me/integrations/telematics_{provider}/webhook
        ?tid={tenant_id}
        &t={hmac_sha256(tenant_id + provider, SECRET)[:32]}

Rotation:
  * Token rotates only when ``TELEMATICS_URL_SIGNING_SECRET`` rotates.
  * Old URLs stop working after rotation — admins must re-copy the
    new URL from the settings UI.  Documented in ``.env.example``.

Startup safety:
  * If the env var is missing, ``mint_token`` / ``verify_token`` raise
    ``MissingSigningSecret``.  Callers surface this as HTTP 500 (the
    webhook endpoint refuses to mint or verify).
"""
from __future__ import annotations

import hmac
import hashlib
import os
from typing import Tuple


class MissingSigningSecret(RuntimeError):
    """Raised when ``TELEMATICS_URL_SIGNING_SECRET`` is unset."""


_SIGNING_SECRET_ENV = "TELEMATICS_URL_SIGNING_SECRET"
_TOKEN_LEN = 32


def _resolve_secret() -> bytes:
    raw = os.environ.get(_SIGNING_SECRET_ENV) or ""
    if not raw.strip():
        raise MissingSigningSecret(
            f"{_SIGNING_SECRET_ENV} is not set — cannot mint or verify "
            f"telematics webhook URLs.  Set the env var to a random "
            f"32-byte value (base64 encoded) and restart."
        )
    # We treat the raw env value as bytes directly — the HMAC output
    # doesn't care about the encoding of the key.  Callers documented
    # as "base64-encoded 32 bytes" for symmetry with SECRETS_MASTER_KEY.
    return raw.encode("utf-8")


def mint_token(tenant_id: str, provider_short: str) -> str:
    """Return the URL-embedded token for ``(tenant_id, provider_short)``.

    ``provider_short`` is the provider short-name (``"mojio"``,
    ``"geotab"``) not the full ``telematics_*`` key — matches what
    appears in the URL path segment.
    """
    key = _resolve_secret()
    payload = f"{tenant_id}|{provider_short}".encode("utf-8")
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return digest[:_TOKEN_LEN]


def verify_token(
    *, tenant_id: str, provider_short: str, token: str,
) -> bool:
    """Constant-time comparison of the presented token against the
    canonical one for ``(tenant_id, provider_short)``.  Returns
    ``False`` when the presented token is malformed / mismatched.
    """
    if not isinstance(token, str) or not token:
        return False
    try:
        expected = mint_token(tenant_id, provider_short)
    except MissingSigningSecret:
        raise
    return hmac.compare_digest(expected, token)


def build_webhook_url(
    *, base_origin: str,
    tenant_id: str,
    provider_short: str,
) -> str:
    """Construct the full copyable webhook URL for a tenant + provider.

    ``base_origin`` should be the fully-qualified public origin of the
    backend (e.g. ``"https://api.plofv.com"``) — the caller derives
    this either from the ``PUBLIC_BACKEND_ORIGIN`` env var or from the
    incoming request's scheme + host.  Never falls back to
    ``localhost``; the caller MUST provide a real origin.
    """
    token = mint_token(tenant_id, provider_short)
    return (
        f"{base_origin.rstrip('/')}"
        f"/api/tenants/me/integrations/telematics_{provider_short}/webhook"
        f"?tid={tenant_id}&t={token}"
    )


def resolve_base_origin(request_scheme: str, request_host: str) -> Tuple[str, bool]:
    """Return ``(origin, from_env)`` — prefers ``PUBLIC_BACKEND_ORIGIN``
    when set, else derives from the incoming request.  Never returns a
    ``localhost`` origin — a preview / prod deploy either sets the env
    var explicitly or is reached through a public ingress host.
    """
    env_val = (os.environ.get("PUBLIC_BACKEND_ORIGIN") or "").strip().rstrip("/")
    if env_val:
        return (env_val, True)
    scheme = (request_scheme or "https").strip()
    host = (request_host or "").strip()
    return (f"{scheme}://{host}", False)
