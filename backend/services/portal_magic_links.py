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
# Phase P34 · Feb-2026 — Magic-link TTL unification.
#
# All four magic-link helpers now default to 168 hours (7 days). The
# pre-P34 shape had context-appropriate TTLs (24h/48h/72h/48h) that
# were correct in isolation but caused a UX inconsistency: a customer
# who received a portal-home link on Monday and a related invoice
# email on Wednesday couldn't tell why the Monday link stopped
# working while the Wednesday one still did. 168h across all four
# resolves that ambiguity without materially widening the security
# window — each token is still ``sub``-scoped (see the P32 audit) so
# a leaked ``portal_invoice_pay`` still can't be replayed against a
# ``portal_home`` verifier.
_DEFAULT_TTL_HOURS = 168


def mint_job_view_token(
    customer_id: str, job_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
    preview: bool = False,
) -> str:
    """Mint a short-lived JWT that unlocks read-only access to a
    single job's service report in the customer portal.

    The token is REUSABLE within its TTL — matches the add-card
    magic-link contract. Ops can revoke by rotating ``JWT_SECRET``.

    ``preview=True`` embeds a ``preview: True`` claim that causes
    :func:`verify_job_view_token` to reject the token with
    HTTPException(400, "preview_token_cannot_be_redeemed"). Used by
    the marketing composer preview so a URL that LOOKS real
    surfaces in the preview pane without any accidentally-copied
    preview link ever being redeemable as a real session.
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
    if preview:
        payload["preview"] = True
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
    if payload.get("preview"):
        # Preview tokens are minted by the marketing composer preview
        # so the surfaced URL LOOKS real but never resolves to a real
        # customer session. Any redemption attempt is rejected here.
        raise HTTPException(400, "preview_token_cannot_be_redeemed")
    return payload


def build_job_view_url(
    base_url: str, customer_id: str, job_id: str, tenant_id: str,
    *, ttl_hours: int = _DEFAULT_TTL_HOURS,
    preview: bool = False,
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
        preview=preview,
    )
    return f"{base_url.rstrip('/')}/api/portal/auto-login?t={token}"


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 7 — Invoice pay-link + Estimate accept-link
# auto-login. Sibling mint/verify helpers with distinct ``sub`` claims
# so a leaked invoice token can NEVER be replayed as an estimate token
# and vice versa (cross-scope guard tested in
# ``test_portal_magic_links.py``).
# ═══════════════════════════════════════════════════════════════════════
_TOKEN_SUB_INVOICE_PAY = "portal_invoice_pay"
_TOKEN_SUB_ESTIMATE_VIEW = "portal_estimate_view"
_INVOICE_TTL_HOURS = 168      # P34 · unified to 7 days
_ESTIMATE_TTL_HOURS = 168     # P34 · unified to 7 days


def mint_invoice_pay_token(
    customer_id: str, invoice_id: str, tenant_id: str,
    *, ttl_hours: int = _INVOICE_TTL_HOURS,
) -> str:
    """Mint a short-lived JWT that auto-logs a customer into the
    portal and drops them on ``/portal/invoices/{invoice_id}``.

    Distinct ``sub`` claim (``portal_invoice_pay``) so a leaked
    token cannot be replayed on the estimate flow or the door-hanger
    ``job_view`` flow. TTL default is 48h (invoices usually give the
    customer a bit more runway than the 24h door-hanger window).
    """
    if not (customer_id and invoice_id and tenant_id):
        raise ValueError(
            "customer_id, invoice_id, and tenant_id are required",
        )
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB_INVOICE_PAY,
        "customer_id": customer_id,
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_invoice_pay_token(token: str) -> dict:
    """Decode + validate a portal-invoice-pay JWT.

    Rejects (with 401 ``token_wrong_scope``) any token whose ``sub``
    isn't ``portal_invoice_pay`` — protects against replay of an
    estimate token, job_view token, add_card token, or the legacy
    public-pay-sheet ``invoice_pay`` token on the auto-login route.
    """
    if not token:
        raise HTTPException(401, "token_invalid_or_expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != _TOKEN_SUB_INVOICE_PAY:
        raise HTTPException(401, "token_wrong_scope")
    if not all(payload.get(k) for k in
               ("customer_id", "invoice_id", "tenant_id")):
        raise HTTPException(401, "token_malformed")
    return payload


def mint_estimate_view_token(
    customer_id: str, estimate_id: str, tenant_id: str,
    *, ttl_hours: int = _ESTIMATE_TTL_HOURS,
) -> str:
    """Mint a short-lived JWT that auto-logs a customer into the
    portal and drops them on ``/portal/estimates/{estimate_id}``.

    Distinct ``sub`` claim (``portal_estimate_view``) so an invoice
    token or job_view token cannot be replayed here. TTL default is
    72h (estimates often need the customer + a decision-maker on the
    same account to review).
    """
    if not (customer_id and estimate_id and tenant_id):
        raise ValueError(
            "customer_id, estimate_id, and tenant_id are required",
        )
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB_ESTIMATE_VIEW,
        "customer_id": customer_id,
        "estimate_id": estimate_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_estimate_view_token(token: str) -> dict:
    if not token:
        raise HTTPException(401, "token_invalid_or_expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != _TOKEN_SUB_ESTIMATE_VIEW:
        raise HTTPException(401, "token_wrong_scope")
    if not all(payload.get(k) for k in
               ("customer_id", "estimate_id", "tenant_id")):
        raise HTTPException(401, "token_malformed")
    return payload


def build_invoice_pay_url(
    base_url: str, customer_id: str, invoice_id: str, tenant_id: str,
    *, ttl_hours: int = _INVOICE_TTL_HOURS,
) -> str:
    """Full portal auto-login URL for the invoice pay-link email.

    Callers that need to defend against a mint failure should call
    ``mint_invoice_pay_token`` directly in a try/except and omit the
    CTA on failure rather than letting this helper raise inside the
    builder — same idiom as ``build_job_view_url``.
    """
    token = mint_invoice_pay_token(
        customer_id, invoice_id, tenant_id, ttl_hours=ttl_hours,
    )
    return f"{base_url.rstrip('/')}/api/portal/auto-login?t={token}"


def build_estimate_view_url(
    base_url: str, customer_id: str, estimate_id: str, tenant_id: str,
    *, ttl_hours: int = _ESTIMATE_TTL_HOURS,
) -> str:
    token = mint_estimate_view_token(
        customer_id, estimate_id, tenant_id, ttl_hours=ttl_hours,
    )
    return f"{base_url.rstrip('/')}/api/portal/auto-login?t={token}"


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 2D — Portal-home auto-login (ToS-update blast + any
# future notification that lands the customer on their portal home
# without a specific resource anchor). Distinct ``sub`` claim so it
# can't be replayed as any of the three resource-scoped tokens.
# ═══════════════════════════════════════════════════════════════════════
_TOKEN_SUB_PORTAL_HOME = "portal_home"
_PORTAL_HOME_TTL_HOURS = 168   # P34 · unified to 7 days


def mint_portal_home_token(
    customer_id: str, tenant_id: str,
    *, ttl_hours: int = _PORTAL_HOME_TTL_HOURS,
    preview: bool = False,
) -> str:
    if not (customer_id and tenant_id):
        raise ValueError("customer_id and tenant_id are required")
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB_PORTAL_HOME,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    if preview:
        payload["preview"] = True
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_portal_home_token(token: str) -> dict:
    if not token:
        raise HTTPException(401, "token_invalid_or_expired")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != _TOKEN_SUB_PORTAL_HOME:
        raise HTTPException(401, "token_wrong_scope")
    if not all(payload.get(k) for k in ("customer_id", "tenant_id")):
        raise HTTPException(401, "token_malformed")
    if payload.get("preview"):
        # Preview tokens are minted by the marketing composer preview
        # so the surfaced URL LOOKS real but never resolves to a real
        # customer session. Any redemption attempt is rejected here.
        raise HTTPException(400, "preview_token_cannot_be_redeemed")
    return payload


def build_portal_home_url(
    base_url: str, customer_id: str, tenant_id: str,
    *, ttl_hours: int = _PORTAL_HOME_TTL_HOURS,
    preview: bool = False,
) -> str:
    token = mint_portal_home_token(
        customer_id, tenant_id, ttl_hours=ttl_hours,
        preview=preview,
    )
    return f"{base_url.rstrip('/')}/api/portal/auto-login?t={token}"


# ═══════════════════════════════════════════════════════════════════════
# Phase P32.1 · Feb-2026 — Portal-invite signed magic-link.
#
# Emitted by the admin-driven portal-invite send path
# (``routers/portal_admin.py::_do_portal_provision``). Distinct
# ``sub`` claim (``portal_invite``) so a leaked estimate/invoice/
# job_view/portal_home token can NEVER be replayed on the invite
# flow, and vice versa.
#
# TTL is 168h (7 days) — unified across every magic-link surface
# in P34. Do NOT diverge to 14d / 24h / anything else.
#
# ``invitation_id`` is the ``invitations`` collection's primary key.
# The auto-login handler uses it to enforce SINGLE-USE redemption:
# the invitations row's ``status`` starts as ``"sent"`` and flips
# to ``"accepted"`` on redemption. Every subsequent redemption of
# the same token — even inside the 168h window — is rejected with
# ``invitation_already_used_or_revoked``. That single-use rule is
# what makes the widened TTL safe.
#
# ``verify_portal_invite_token`` returns ``None`` on any failure
# (expired, tampered, wrong ``sub``, malformed claims) rather than
# raising HTTPException. The auto-login handler's error paths need
# to distinguish between "invalid token" and "used token", and a
# nullable return keeps that branching flat.
# ═══════════════════════════════════════════════════════════════════════
_TOKEN_SUB_PORTAL_INVITE = "portal_invite"
_PORTAL_INVITE_TTL_HOURS = 168   # unified per P34 — do NOT diverge


def mint_portal_invite_token(
    tenant_id: str, customer_id: str, invited_by_user_id: str,
    invitation_id: str,
    *, ttl_hours: int = _PORTAL_INVITE_TTL_HOURS,
) -> str:
    """Mint a P32.1 portal-invite JWT. Claims: ``sub``, ``tid``
    (tenant_id), ``cid`` (customer_id), ``iby`` (invited_by_user_id),
    ``iid`` (invitation_id), ``iat``, ``exp``.

    Claim key naming intentionally diverges from the other portal
    scopes (short ``tid`` / ``cid`` / ``iby`` / ``iid`` instead of
    ``tenant_id`` / ``customer_id`` / ...) to keep the URL length
    tight — invite emails are more link-length-sensitive than the
    resource-scoped magic-links used elsewhere. Verify + auto-login
    handler read these short keys directly (see
    ``verify_portal_invite_token``).
    """
    if not (tenant_id and customer_id and invited_by_user_id
            and invitation_id):
        raise ValueError(
            "tenant_id, customer_id, invited_by_user_id, and "
            "invitation_id are all required",
        )
    ttl = max(60, int(ttl_hours) * 3600)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": _TOKEN_SUB_PORTAL_INVITE,
        "tid": tenant_id,
        "cid": customer_id,
        "iby": invited_by_user_id,
        "iid": invitation_id,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_portal_invite_token(token: str) -> Optional[dict]:
    """Decode + validate a P32.1 portal-invite JWT.

    Returns the claims dict on success. Returns ``None`` on ANY
    failure (expired signature, tampered signature, wrong ``sub``,
    missing required claim). Never raises — see the module comment
    for the auto-login branching rationale.

    Never logs the raw token in any error path (leak risk).
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.PyJWTError:
        return None
    if payload.get("sub") != _TOKEN_SUB_PORTAL_INVITE:
        return None
    for key in ("tid", "cid", "iby", "iid"):
        if not payload.get(key):
            return None
    return payload


def build_portal_invite_url(
    base_url: str, tenant_id: str, customer_id: str,
    invited_by_user_id: str, invitation_id: str,
    *, ttl_hours: int = _PORTAL_INVITE_TTL_HOURS,
) -> str:
    """Return the customer-facing ``AcceptInvite`` URL. Routes to the
    React ``/portal/accept-invite`` page which owns the friendly
    error surface + kicks the browser to the interstitial auto-login
    handler on success."""
    token = mint_portal_invite_token(
        tenant_id, customer_id, invited_by_user_id, invitation_id,
        ttl_hours=ttl_hours,
    )
    return (
        f"{base_url.rstrip('/')}/portal/accept-invite?token={token}"
    )


def hash_portal_invite_token(token: str) -> str:
    """SHA-256 hex digest of the raw token. The ``invitations``
    collection stores this hash — never the raw token — so a
    database dump can't be replayed as a valid magic-link. The
    auto-login handler recomputes the hash on redemption to look
    the invitation row up."""
    import hashlib
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()
