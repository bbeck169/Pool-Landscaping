"""Feb-2026 · Business Signup SP1 — email-verify token mint/verify.

Thin wrapper over the existing ``services.portal_magic_links`` JWT
idiom (same secret, same algorithm, same signature model). Adds a
new ``sub="signup_email_verify"`` scope with a 48h TTL — signup
customers need time to check their inbox from work / a slow email
provider.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

import jwt
from fastapi import HTTPException

from config import JWT_ALGO, JWT_SECRET


_SUB = "signup_email_verify"
_TTL_HOURS = 48


def mint_signup_verify_token(
    *, tenant_id: str, admin_user_id: str, admin_email: str,
    ttl_hours: int = _TTL_HOURS,
) -> str:
    """Mint a signed JWT that unlocks the ``POST /api/signup/verify``
    endpoint. Reusable within its TTL — a customer clicking the
    same link twice works (idempotent verify path). Rotates via
    ``JWT_SECRET`` rotation like every other magic-link token.
    """
    if not (tenant_id and admin_user_id and admin_email):
        raise ValueError("tenant_id, admin_user_id, and admin_email are required")
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _SUB,
        "tenant_id": tenant_id,
        "admin_user_id": admin_user_id,
        "admin_email": admin_email.lower(),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_signup_verify_token(token: str) -> Dict[str, str]:
    """Decode + validate a signup-verify JWT.

    Returns the ``{tenant_id, admin_user_id, admin_email}`` claims.
    Raises :class:`fastapi.HTTPException` with a stable ``detail``:

        * 401 ``"token_invalid_or_expired"`` — bad signature, expired,
          or malformed.
        * 401 ``"token_wrong_scope"`` — wrong ``sub`` (e.g. a
          job-view token replayed here).
        * 401 ``"token_malformed"`` — missing required claims.
    """
    if not token:
        raise HTTPException(401, "token_invalid_or_expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != _SUB:
        raise HTTPException(401, "token_wrong_scope")
    if not all(payload.get(k) for k in ("tenant_id", "admin_user_id", "admin_email")):
        raise HTTPException(401, "token_malformed")
    return {
        "tenant_id": payload["tenant_id"],
        "admin_user_id": payload["admin_user_id"],
        "admin_email": payload["admin_email"],
    }
