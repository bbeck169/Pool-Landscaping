"""Feb-2026 · Portal magic-link tokens for customer deep links.

Mirrors the ``add_card`` pattern in :mod:`services.add_card_links` —
same JWT idiom, same TTL semantics, reusable within the TTL window
(NOT single-use). Kept in a separate module so the auth surface for
different portal purposes stays isolated (a leaked ``job_view`` token
can NEVER be replayed as an ``add_card`` token because the ``sub``
claim is checked on verify).

Public API::

    mint_job_view_token(customer_id, job_id, tenant_id, ttl_hours=24)
        → str   (a signed HS256 JWT)

    verify_job_view_token(token) → dict
        Returns ``{customer_id, job_id, tenant_id, exp, iat}`` on
        success. Raises :class:`fastapi.HTTPException(401, ...)` on
        any failure (bad signature / expired / wrong sub).

    build_job_view_url(base_url, customer_id, job_id, tenant_id,
                       ttl_hours=24)
        → str   (the full ``{base}/portal/jobs/{job_id}?t=<jwt>`` URL)

The portal-side frontend consumes the token by POST-ing (or GET-ing)
to a portal-side endpoint that ultimately calls
:func:`verify_job_view_token` — this module deliberately does NOT own
that endpoint (frontend integration is out of scope for the door-
hanger phase).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import HTTPException

from config import JWT_ALGO, JWT_SECRET

_TOKEN_SUB = "job_view"
_DEFAULT_TTL_HOURS = 24


def mint_job_view_token(
    customer_id: str, job_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> str:
    """Mint a short-lived JWT that unlocks read-only access to a
    single job's service report in the customer portal.

    The token is REUSABLE within its TTL — matches the add-card
    magic-link contract. Ops can revoke by rotating ``JWT_SECRET``.
    """
    if not (customer_id and job_id and tenant_id):
        raise ValueError("customer_id, job_id, and tenant_id are required")
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB,
        "customer_id": customer_id,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_job_view_token(token: str) -> dict:
    """Decode + validate a job-view JWT.

    Raises :class:`HTTPException(401)` with a stable ``detail`` string
    for each failure mode:

    * ``"token_invalid_or_expired"`` — bad signature, expired, or
      malformed. Callers surface this as a friendly "Your link has
      expired — please log in" redirect.
    * ``"token_wrong_scope"``       — wrong ``sub`` (e.g. an add-card
      token replayed here). Same 401 status.
    * ``"token_malformed"``         — missing required claims.
    """
    if not token:
        raise HTTPException(401, "token_invalid_or_expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != _TOKEN_SUB:
        raise HTTPException(401, "token_wrong_scope")
    if not all(payload.get(k) for k in ("customer_id", "job_id", "tenant_id")):
        raise HTTPException(401, "token_malformed")
    return payload


def build_job_view_url(
    base_url: str, customer_id: str, job_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> str:
    """Build the full portal deep-link URL.

    Feb-2026 hotfix — the URL now points at the backend redemption
    interstitial (``GET /api/portal/auto-login?t=…``) instead of the
    portal SPA directly.  The interstitial verifies the token, mints
    a customer-scoped access token, seeds it into ``localStorage``,
    and JS-navigates to ``/portal/service-reports/{sr_id}`` (or
    ``/portal/login?reason=link_expired`` on failure).  This closes
    the P0 "button 404s" bug where the raw ``/portal/jobs/{jid}``
    URL had no portal-side route.

    Callers who need to defend against a mint failure (e.g. the door-
    hanger email builder) should call ``mint_job_view_token`` directly
    in a try/except and omit the CTA on failure rather than letting
    this helper raise inside the builder.
    """
    token = mint_job_view_token(
        customer_id, job_id, tenant_id, ttl_hours=ttl_hours,
    )
    return f"{base_url.rstrip('/')}/api/portal/auto-login?t={token}"
