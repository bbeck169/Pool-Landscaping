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
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import jwt

from config import db, JWT_ALGO, JWT_SECRET
from services.portal_magic_links import (
    verify_job_view_token,
    verify_invoice_pay_token,
    verify_estimate_view_token,
    verify_portal_home_token,
    verify_portal_invite_token,
    hash_portal_invite_token,
)
from services.service_records_link import (
    verify_service_records_token,
    REDIRECT_PATH as _SERVICE_RECORDS_REDIRECT,
)

logger = logging.getLogger("portal.auto_login")

router = APIRouter()

_LOGIN_EXPIRED_URL = "/portal/login?reason=link_expired"
_LOGIN_REVOKED_URL = "/portal/login?reason=link_revoked"

# ─── Feb 2026 · IP rate limit for magic-link redemption ─────────────
# In-process rolling-window limiter: 20 redemption attempts per minute
# per IP. Prevents an attacker who scrapes a leaked token list from
# brute-forcing scope replays / stale tokens without adding an external
# dependency (Redis is not in the stack). Applied BEFORE JWT verify so
# tampered tokens still count against the budget.
_MAGIC_RATE_MAX_PER_MIN = 20
_MAGIC_IP_HITS: Dict[str, Deque[datetime]] = defaultdict(deque)


def _check_magic_rate_limit(ip: str) -> bool:
    """Return True if the request is within budget, False if the
    caller has exceeded 20 attempts in the last 60 seconds."""
    if not ip:
        return True  # never lock out on a request without an IP hint.
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=60)
    q = _MAGIC_IP_HITS[ip]
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= _MAGIC_RATE_MAX_PER_MIN:
        return False
    q.append(now)
    return True


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
        ("service_records", verify_service_records_token),
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


def _peek_scope_and_id(token: str) -> tuple[str, str]:
    """Feb-2026 · P0 Pay-link routing fix — decode the token WITHOUT
    verifying ``exp`` so we can determine whether an expired /
    tampered token was a ``portal_invoice_pay`` token pointed at a
    known invoice id.  Used ONLY to route to the public pay page
    instead of the auth wall — the token is still fully rejected
    for auto-login purposes.

    Returns ``(scope, resource_id)`` or ``("", "")`` when the token
    can't even be peeked (tampered signature, malformed claims,
    etc).  Never raises.
    """
    if not token:
        return "", ""
    try:
        payload = jwt.decode(
            token, JWT_SECRET,
            algorithms=[JWT_ALGO],
            options={"verify_exp": False},
        )
    except Exception:  # noqa: BLE001
        return "", ""
    sub = str(payload.get("sub") or "")
    if sub == "portal_invoice_pay" and payload.get("invoice_id"):
        return "invoice", str(payload["invoice_id"])
    if sub == "invoice_pay" and payload.get("invoice_id"):
        return "invoice", str(payload["invoice_id"])
    return "", ""


def _invoice_expired_public_response(invoice_id: str) -> RedirectResponse:
    """Feb-2026 · P0 Pay-link routing fix — when a legacy invoice
    auto-login token has expired/tampered but the invoice id is
    still recoverable, bounce the customer to the public pay page
    (``/pay/invoice/{id}``) instead of the portal login screen. The
    public page renders the "This payment link is no longer valid"
    friendly copy (no ``token=`` on the URL → PublicInvoicePay
    branches to its missing-token state).  Payments never require
    login — see DIAG_PAY_LINK_LOGIN_REDIRECT_BUG.md.
    """
    return RedirectResponse(
        url=f"/pay/invoice/{invoice_id}?msg=link_expired",
        status_code=302,
    )


def _revoked_response() -> RedirectResponse:
    """Task 6b · Feb 2026 — 302 → the portal login page with the
    ``link_revoked`` reason so the frontend renders the friendly
    "This link has been revoked" banner instead of the generic
    expired copy.
    """
    return RedirectResponse(url=_LOGIN_REVOKED_URL, status_code=302)


# ═══════════════════════════════════════════════════════════════════════
# Phase P32.1 · Feb-2026 — Portal-invite redemption helpers.
# ═══════════════════════════════════════════════════════════════════════
_INVITE_ERROR_URL = "/portal/accept-invite?error={code}"


def _invite_error(code: str) -> RedirectResponse:
    """302 → the React ``AcceptInvite`` page with a specific error
    code so the FE can render the right friendly copy. Codes used:
    ``expired`` (invalid / tampered / outside 168h window),
    ``used`` (status != ``sent`` — accepted / revoked / expired
    lifecycle stamp)."""
    return RedirectResponse(
        url=_INVITE_ERROR_URL.format(code=code), status_code=302,
    )


async def _redeem_portal_invite(
    payload: dict, *, raw_token: str, from_ip: Optional[str],
) -> HTMLResponse | RedirectResponse:
    """Single-use redemption of a P32.1 portal-invite JWT.

    Steps:
      1. Look up the ``invitations`` row by ``token_hash``. Absent
         or ``status != "sent"`` → ``error=used`` bounce.
      2. Resolve the customer + login user (tenant-scoped). Missing
         either → ``error=used`` (existence-hiding for cross-tenant).
      3. Flip the invitations row to ``status="accepted"``,
         ``accepted_at=now``. Uses a conditional
         ``update_one({..., status: "sent"})`` so a concurrent
         double-click is rejected atomically.
      4. Mint the session token via the same ``create_token``
         helper the other scopes use.
      5. Return the interstitial HTML that seeds ``localStorage``
         and navigates to ``/portal/home``.
    """
    tenant_id = payload.get("tid")
    customer_id = payload.get("cid")

    # 1) Look up the invitations row by token hash (tenant-scoped).
    inv = await db.invitations.find_one(
        {"tenant_id": tenant_id,
          "customer_id": customer_id,
          "token_hash": hash_portal_invite_token(raw_token)},
        {"_id": 0},
    )
    if not inv or inv.get("status") != "sent":
        _log("invite_used_or_revoked", customer_id=customer_id,
              resource_type="invite", from_ip=from_ip)
        return _invite_error("used")

    # 2) Confirm the customer + login user exist (tenant-scoped).
    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1},
    )
    if not customer:
        _log("invite_customer_missing", customer_id=customer_id,
              resource_type="invite", from_ip=from_ip)
        return _invite_error("used")
    cust_user = await db.users.find_one(
        {"customer_id": customer_id, "role": "customer",
          "tenant_id": tenant_id},
        {"_id": 0, "password_hash": 0},
    )
    if not cust_user:
        _log("invite_no_login_user", customer_id=customer_id,
              resource_type="invite", from_ip=from_ip)
        return _invite_error("used")

    # 3) Atomically flip status "sent" → "accepted". Concurrent
    #    double-click on the email link is rejected by the
    #    conditional match — only ONE of the racing requests
    #    performs the update.
    now_iso_str = datetime.now(timezone.utc).isoformat()
    res = await db.invitations.update_one(
        {"id": inv["id"], "tenant_id": tenant_id, "status": "sent"},
        {"$set": {"status": "accepted",
                    "accepted_at": now_iso_str}},
    )
    if res.modified_count == 0:
        _log("invite_race_lost", customer_id=customer_id,
              resource_type="invite", from_ip=from_ip)
        return _invite_error("used")

    # 4) Mint the customer-scoped access token.
    from utils import create_token
    access_token = create_token(cust_user)
    _log("invite_success", customer_id=customer_id,
          resource_type="invite", resource_id=inv["id"],
          from_ip=from_ip)
    return HTMLResponse(
        content=_interstitial_html(
            access_token=access_token, redirect_to="/portal/home",
        ),
        status_code=200,
    )



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

    # 0) Rate limit — 20 attempts/min/IP. Applied BEFORE JWT verify
    #    so tampered tokens still count against the budget.
    if not _check_magic_rate_limit(from_ip or ""):
        _log("rate_limited", from_ip=from_ip)
        return _expired_response()

    # 1) Classify + verify token.
    # Phase P32.1 · Feb-2026 — Portal-invite tokens are handled up
    # here (BEFORE the generic classify-and-verify sweep) because
    # they need one extra piece of state the other scopes don't:
    # a lookup in the ``invitations`` collection to enforce SINGLE-
    # USE redemption. Once the invitations row's ``status`` flips
    # from ``sent`` to ``accepted``, every subsequent redemption of
    # the same token — even inside the 168h window — is rejected
    # with ``invitation_already_used_or_revoked``.
    #
    # Failure modes:
    #   * expired / tampered / wrong-sub → 302 to
    #     ``/portal/accept-invite?error=expired``.
    #   * invitations row absent / status != ``sent`` → 302 to
    #     ``/portal/accept-invite?error=used``.
    #   * customer + login user resolved → interstitial HTML that
    #     seeds the session (same as portal-home flow) + marks the
    #     invitations row ``accepted``.
    invite_payload = verify_portal_invite_token(t)
    if invite_payload is not None:
        return await _redeem_portal_invite(
            invite_payload, raw_token=t, from_ip=from_ip,
        )

    # Feb-2026 · Slice 7 — invoice + estimate + job_view + portal_home
    # + service_records scopes. Cross-scope replay guarded inside
    # each verifier (see ``_classify_and_verify``).
    resource_type, payload = _classify_and_verify(t)
    if not payload:
        # Feb-2026 · P0 Pay-link routing fix — invoice-scoped tokens
        # that expired must land the customer on the public pay
        # page, not the portal login wall.  Peek at the sub claim
        # ignoring exp; only bounce to /pay/invoice on a matching
        # scope + recoverable invoice id.
        peek_scope, peek_id = _peek_scope_and_id(t)
        if peek_scope == "invoice" and peek_id:
            _log("expired_invoice_to_public", from_ip=from_ip,
                  resource_type="invoice", resource_id=peek_id)
            return _invoice_expired_public_response(peek_id)
        # Phase P32.1 · Feb-2026 — an expired/tampered
        # ``portal_invite`` token must land the customer on the
        # AcceptInvite page with ``error=expired`` (friendlier
        # copy than the generic ``/portal/login?reason=link_expired``
        # banner). Peek at the sub claim ignoring exp so we can
        # route without letting the token itself authenticate.
        try:
            peek_payload = jwt.decode(
                t, JWT_SECRET, algorithms=[JWT_ALGO],
                options={"verify_exp": False},
            )
            if str(peek_payload.get("sub") or "") == "portal_invite":
                _log("invite_expired", from_ip=from_ip,
                      resource_type="invite")
                return _invite_error("expired")
        except Exception:  # noqa: BLE001
            pass
        _log("expired", from_ip=from_ip)
        return _expired_response()

    customer_id = payload.get("customer_id")
    tenant_id = payload.get("tenant_id")

    # 1b) Task 6b · Feb 2026 — service-records tokens may have been
    #     revoked by an admin. Check the denylist BEFORE minting a
    #     session so a revoked link cannot log the customer in.
    #     Scope-narrow: only the ``service_records`` resource_type
    #     participates in this denylist; other portal magic-link
    #     scopes are unaffected.
    if resource_type == "service_records":
        from services.service_records_link import hash_token
        revoked_hit = await db.customer_link_sends.find_one(
            {"tenant_id": tenant_id,
             "customer_id": customer_id,
             "token_hash": hash_token(t),
             "revoked_at": {"$ne": None}},
            {"_id": 0, "id": 1, "revoked_at": 1},
        )
        if revoked_hit:
            _log("revoked", customer_id=customer_id,
                  resource_type=resource_type,
                  resource_id=revoked_hit.get("id"),
                  from_ip=from_ip)
            return _revoked_response()

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
    elif resource_type == "service_records":
        # Feb-2026 · Task 6 — "Send service records link" from the
        # Customer admin page drops the customer on the existing
        # portal service-records list. No new portal surface was
        # invented for this ship.
        default_target = _SERVICE_RECORDS_REDIRECT
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
