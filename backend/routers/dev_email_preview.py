"""Phase P53 · Feb-2026 — Dev-only referral BOOM email preview.

Serves the fully-rendered BOOM celebration email HTML at
``GET /api/dev/email-preview/referral-reward`` so the design team
can visual-smoke the template before it lands in a real customer's
inbox.

Gates:
    * Registration-time — ``server.py`` skips ``include_router`` on
      this module whenever ``APP_ENV == "production"``. Registration
      is the stronger of the two guards: the route is not mounted
      at all, so any request in prod resolves to 404 NOT FOUND at
      the FastAPI layer.
    * Runtime — belt-and-suspenders check inside the handler. If a
      caller sneaks the router in via a manual include (e.g. a
      pytest fixture that force-mounts everything), the handler
      still returns 404 in prod. This mirrors the pattern in
      ``routers/resend_webhooks.py`` (K79 dev routes).

Stub merge context (per P53 spec 53.4):
    * CUSTOMER_FIRST_NAME    → "Alex"
    * REFERRAL_FRIEND_NAME   → "Prasad Mikkilineni"
    * REFERRAL_CREDIT_AMOUNT → "$55.00"
    * CUSTOMER_CREDIT_BALANCE → "$110.00"
    * COMPANY_NAME           → "Pool & Landscaping of Vistancia"
    * PORTAL_REFERRALS_URL   → resolved by the same helper the
                                 production send path calls
                                 (``PUBLIC_APP_URL``-aware).

No auth in dev — the route is dev-only by construction.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from services.email.theming import wrap_html_in_shell
from services.marketing.merge_tags import render_template
from services.referral_watcher import (
    _REFERRAL_EMAIL_BODY,
    _absolute_portal_referrals_url,
)


router = APIRouter()


# ─── Stub context — matches the P53 brief exactly ───────────────────
_STUB_CTX = {
    "CUSTOMER_FIRST_NAME": "Alex",
    "REFERRAL_FRIEND_NAME": "Prasad Mikkilineni",
    "REFERRAL_CREDIT_AMOUNT": "$55.00",
    "CUSTOMER_CREDIT_BALANCE": "$110.00",
    "COMPANY_NAME": "Pool & Landscaping of Vistancia",
}


def _is_prod() -> bool:
    """Runtime env detection — matches the codebase-wide
    ``APP_ENV == "production"`` convention (grep-verified against
    ~30 call-sites in ``backend/routers/`` and
    ``backend/services/``).

    Escape hatch: ``ENABLE_DEV_EMAIL_PREVIEW=true`` overrides the
    APP_ENV gate so the preview pod (which currently ships
    ``APP_ENV=production`` in its ``.env`` as a legacy config-drift
    artifact) can still expose the route without flipping the
    global APP_ENV. When the override is set, this function returns
    ``False`` regardless of APP_ENV."""
    if (os.environ.get("ENABLE_DEV_EMAIL_PREVIEW") or "").strip().lower() \
            in ("1", "true", "yes"):
        return False
    return (os.environ.get("APP_ENV") or "").strip().lower() == "production"


def render_boom_preview_html() -> str:
    """Render the BOOM email exactly as the production send path
    would — same body constant, same merge tag renderer, same
    ``wrap_html_in_shell`` helper. Zero PII: all fields come from
    ``_STUB_CTX``. Reused by the dev preview route + the send-
    preview CLI."""
    ctx = {**_STUB_CTX,
           "PORTAL_REFERRALS_URL": _absolute_portal_referrals_url()}
    body, _unresolved = render_template(_REFERRAL_EMAIL_BODY, ctx)
    return wrap_html_in_shell(body, branding=None)


@router.get("/dev/email-preview/referral-reward",
             response_class=HTMLResponse)
async def referral_reward_preview() -> HTMLResponse:
    """Renders the BOOM celebration email in the browser.

    * 404 in production (belt-and-suspenders).
    * 200 with rendered HTML in preview/dev.
    """
    if _is_prod():
        # Match FastAPI's own 404 shape so the response is
        # indistinguishable from an unmounted route.
        raise HTTPException(status_code=404, detail="Not Found")
    html = render_boom_preview_html()
    return HTMLResponse(content=html, status_code=200)
