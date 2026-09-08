"""Feb-2026 · Task 6 · Portal magic-link for the "Send service records"
admin action on the Customer detail page.

Distinct ``sub`` claim (``service_records_view``) so a leaked token
CANNOT be replayed as any other portal-scoped magic link
(``job_view``, ``portal_invoice_pay``, ``portal_estimate_view``,
``portal_home``, ``add_card``). Verified by the sibling helper +
wired into ``routers.portal_auto_login._classify_and_verify`` so
redemption lands the customer directly on
``/portal/service-reports`` — the existing portal-side list surface.

Public API mirrors ``services.portal_magic_links``::

    mint_service_records_token(customer_id, tenant_id, *, ttl_hours=168)
        → str        # signed HS256 JWT

    verify_service_records_token(token) → dict
        # {customer_id, tenant_id, exp, iat} on success.
        # Raises HTTPException(401) on any failure.

    build_service_records_url(base_url, customer_id, tenant_id,
                                ttl_hours=168)
        → str        # {base}/api/portal/auto-login?t=<jwt>&redirect=/portal/service-reports

Reusable within TTL (NOT single-use) — same idiom as add-card /
invoice-pay / estimate-view. Ops can revoke by rotating
``JWT_SECRET``. Default TTL is 168 hours (7 days) per the Task 6
spec.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from config import JWT_ALGO, JWT_SECRET

_TOKEN_SUB = "service_records_view"
_DEFAULT_TTL_HOURS = 168  # 7 days
_REDIRECT_PATH = "/portal/service-reports"


def mint_service_records_token(
    customer_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> str:
    if not (customer_id and tenant_id):
        raise ValueError("customer_id and tenant_id are required")
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_service_records_token(token: str) -> dict:
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
    if not all(payload.get(k) for k in ("customer_id", "tenant_id")):
        raise HTTPException(401, "token_malformed")
    return payload


def build_service_records_url(
    base_url: str, customer_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> str:
    """Full portal auto-login URL that drops the customer on the
    Service Records list. Consumers who need to defend against a
    mint failure should call ``mint_service_records_token`` in a
    try/except rather than letting this helper raise.
    """
    token = mint_service_records_token(
        customer_id, tenant_id, ttl_hours=ttl_hours,
    )
    base = (base_url or "").rstrip("/")
    return f"{base}/api/portal/auto-login?t={token}&redirect={_REDIRECT_PATH}"


REDIRECT_PATH = _REDIRECT_PATH
