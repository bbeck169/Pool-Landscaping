"""Feb-2026 hotfix · Door-hanger portal auto-login interstitial.

Path: ``GET /api/portal/auto-login?t=<jwt>&redirect=/portal/…``

Redeems a ``job_view`` magic-link JWT (minted by
:mod:`services.portal_magic_links`) into a customer-scoped
access token, seeds it into the portal SPA's ``localStorage``,
and JavaScript-redirects the browser to the target service-
report page.

Why an HTML interstitial (not a bare ``302``)?
==============================================
The rest of the app authenticates with a **Bearer JWT stored in
``localStorage["token"]``** — the codebase does NOT use session
cookies (see ``frontend/src/api.js`` and ``backend/utils.create_token``).
A pure ``302 Location: /portal/…`` cannot log the customer in
because the SPA reads its auth from ``localStorage``, which the
browser will not populate on a server-side redirect.  This
interstitial page runs one line of JavaScript to seed the JWT
BEFORE navigating; the visual effect is still a single click →
land-logged-in.

Failure modes are always ``302``-style redirects to
``/portal/login?reason=link_expired`` — no interstitial page is
rendered in that case (the token was never valid).

Open-redirect guard
===================
``redirect`` query param is honoured ONLY when it starts with
``/portal/``.  Anything else falls back to the canonical
``/portal/service-reports/{sr_id}`` path resolved from the
token's ``job_id``.

Logging contract
================
Every request emits ONE structured log line:
``[portal_auto_login] outcome=<success|expired|invalid|wrong_scope>
customer_id=<id> job_id=<id> service_report_id=<id?> from_ip=<ip>``.
The raw ``t`` value is NEVER logged.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import db
from services.portal_magic_links import (
    verify_job_view_token,
    verify_invoice_pay_token,
    verify_estimate_view_token,
    verify_portal_home_token,
)

logger = logging.getLogger("portal.auto_login")

router = APIRouter()

_LOGIN_EXPIRED_URL = "/portal/login?reason=link_expired"


def _classify_and_verify(token: str):
    """Feb-2026 · Slice 7 — probe the token against every known
    portal scope (``job_view``, ``portal_invoice_pay``,
    ``portal_estimate_view``) and return
    ``(resource_type, payload)`` on the first match. Returns
    ``(None, None)`` when the token is expired / tampered / minted
    for an unknown scope. Cross-scope replay is blocked here: an
    invoice token will be REJECTED by the estimate verifier (and
    vice versa) and will only match its own scope.
    """
    for kind, verify in (
        ("job", verify_job_view_token),
        ("invoice", verify_invoice_pay_token),
        ("estimate", verify_estimate_view_token),
        ("portal_home", verify_portal_home_token),
    ):
        try:
            return kind, verify(token)
        except Exception:
            continue
    return None, None


def _safe_redirect(candidate: Optional[str], default: str) -> str:
    """Reject any candidate that doesn't start with ``/portal/`` —
    prevents an attacker from crafting a link that logs the
    customer in and bounces them off-site."""
    if not candidate:
        return default
    if not candidate.startswith("/portal/"):
        return default
    return candidate


def _log(outcome: str, *, customer_id: Optional[str] = None,
         resource_type: Optional[str] = None,
         resource_id: Optional[str] = None,
         from_ip: Optional[str] = None) -> None:
    logger.info(
        "[portal_auto_login] outcome=%s customer_id=%s "
        "resource_type=%s resource_id=%s from_ip=%s",
        outcome, customer_id, resource_type, resource_id, from_ip,
    )


def _expired_response() -> RedirectResponse:
    """302 → the portal login page with the link-expired reason so
    the frontend shows the friendly banner."""
    return RedirectResponse(url=_LOGIN_EXPIRED_URL, status_code=302)


def _interstitial_html(*, access_token: str, redirect_to: str) -> str:
    """One-shot HTML that seeds ``localStorage["token"]`` then
    ``window.location.replace``s to the portal target.  Kept dead
    simple + inline so a Content-Security-Policy strict-src-none
    tenant can still opt-in later by rewriting this string."""
    # ``json.dumps`` would encode the token safely, but we generated
    # this JWT ourselves (only base64url + dots) so escaping the
    # single quote at insertion time is enough.  ``redirect_to`` is
    # validated upstream by ``_safe_redirect``.
    safe_tok = access_token.replace("\\", "\\\\").replace("'", "\\'")
    safe_redir = redirect_to.replace("\\", "\\\\").replace("'", "\\'")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Signing you in…</title>"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "</head><body style=\"font-family:system-ui,sans-serif;"
        "text-align:center;padding-top:48px;color:#334155;\">"
        "<p>Signing you in…</p>"
        f"<script>try{{"
        f"localStorage.setItem('token','{safe_tok}');"
        f"}}catch(e){{}}"
        f"window.location.replace('{safe_redir}');"
        "</script>"
        "</body></html>"
    )


async def _resolve_service_report_id(tenant_id: str, job_id: str) -> Optional[str]:
    """The portal's canonical detail page is keyed by
    ``service_report.id``, not ``job.id``.  Look it up now so the
    interstitial can navigate straight to the report.  Returns
    ``None`` if no report has been created for the job yet — the
    caller falls back to the portal home."""
    doc = await db.service_reports.find_one(
        {"tenant_id": tenant_id, "job_id": job_id},
        {"_id": 0, "id": 1},
    )
    return (doc or {}).get("id")


@router.get("/portal/auto-login")
async def portal_auto_login(
    request: Request,
    t: str = "",
    redirect: Optional[str] = None,
):
    """Redeem a portal magic-link token into an auto-login
    interstitial page.

    Feb-2026 · Slice 7 — the route now handles THREE token scopes:
    ``job_view`` (door hanger), ``portal_invoice_pay`` (invoice
    email CTA), ``portal_estimate_view`` (estimate email CTA).
    Cross-scope replay is blocked in :func:`_classify_and_verify` —
    each scope only matches its own verifier.

    Never raises — every failure surfaces as a ``302`` to the
    portal login page with ``reason=link_expired``.
    """
    from_ip = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )

    # 1) Classify + verify token.
    resource_type, payload = _classify_and_verify(t)
    if not payload:
        _log("expired", from_ip=from_ip)
        return _expired_response()

    customer_id = payload.get("customer_id")
    tenant_id = payload.get("tenant_id")

    # 2) Confirm the customer + login user exist.
    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1},
    )
    if not customer:
        _log("wrong_scope", customer_id=customer_id,
             resource_type=resource_type, from_ip=from_ip)
        return _expired_response()
    cust_user = await db.users.find_one(
        {"customer_id": customer_id, "role": "customer",
         "tenant_id": tenant_id},
        {"_id": 0, "password_hash": 0},
    )
    if not cust_user:
        _log("no_login_user", customer_id=customer_id,
             resource_type=resource_type, from_ip=from_ip)
        return _expired_response()

    # 3) Resolve the destination path per resource type.
    if resource_type == "job":
        job_id = payload.get("job_id")
        sr_id = await _resolve_service_report_id(tenant_id, job_id)
        default_target = (
            f"/portal/service-reports/{sr_id}" if sr_id else "/portal/home"
        )
        resource_id = job_id
    elif resource_type == "invoice":
        invoice_id = payload.get("invoice_id")
        default_target = f"/portal/invoices/{invoice_id}"
        resource_id = invoice_id
    elif resource_type == "estimate":
        estimate_id = payload.get("estimate_id")
        default_target = f"/portal/estimates/{estimate_id}"
        resource_id = estimate_id
    elif resource_type == "portal_home":
        # Feb-2026 · Slice 2D — ToS-update blast (and any future
        # notification that lands the customer at home without a
        # specific resource anchor). The OnboardingGate rendered by
        # AppLayout will detect any newly-pending ToS in
        # ``/customer-portal/onboarding-state`` and open the accept
        # modal automatically.
        default_target = "/portal/home"
        resource_id = None
    else:  # pragma: no cover — defensive
        _log("expired", customer_id=customer_id, from_ip=from_ip)
        return _expired_response()

    # 4) Open-redirect guard — ``redirect`` query param honoured
    #    ONLY when it starts with ``/portal/``, otherwise the
    #    token-derived destination wins.
    redirect_to = _safe_redirect(redirect, default_target)

    # 5) Mint the customer-scoped access token via the SAME helper
    #    ``auth_response`` uses so we don't fork the session logic.
    from utils import create_token
    access_token = create_token(cust_user)

    _log("success", customer_id=customer_id,
         resource_type=resource_type, resource_id=resource_id,
         from_ip=from_ip)
    return HTMLResponse(
        content=_interstitial_html(
            access_token=access_token, redirect_to=redirect_to,
        ),
        status_code=200,
    )
