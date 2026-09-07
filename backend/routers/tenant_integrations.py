"""Phase I1.7.a · Feb-2026 — Tenant-integrations router.

Endpoints (all prefixed ``/api``):

    GET    /tenants/me/integrations
           → List<ConnectionSummary>  (never returns plaintext)

    POST   /tenants/me/integrations/{provider_key}/test
           → ConnectionHealth

    DELETE /tenants/me/integrations/{provider_key}
           → { removed: bool }

    GET    /integrations/stripe/connect-link
           → { url, state }   (admin+)

    GET    /integrations/stripe/callback?code=...&state=...
           → redirects the browser to the FE integrations page
             with ``?connect=success|error`` (public — Stripe posts
             the redirect here).

    POST   /integrations/stripe/webhook
           → { received: True }  (public — Stripe posts here)

Role gating: read endpoints allow admin+manager+super_admin.
Writes (connect-link, delete, test) require admin+ / super_admin.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user
from services.secrets import (
    ConnectionSummary,
    list_connections,
    remove_secret,
    put_secret,
    log_error as log_secret_error,
)
from services.secrets.models import ConnectionType
from services.payments.tenant_base import (
    ConnectionHealth,
    TenantPaymentError,
    UnknownProvider,
)
from services.payments.tenant_registry import get_provider
from services.payments.tenant_stripe import build_connect_link


log = logging.getLogger("integrations")
router = APIRouter(tags=["TenantIntegrations"])


_OAUTH_STATE_TTL_SECONDS = 900   # 15 min


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _require_write_role(user: Dict[str, Any]) -> None:
    role = user.get("role")
    if role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="admin+ only")


def _require_read_role(user: Dict[str, Any]) -> None:
    role = user.get("role")
    if role not in ("admin", "manager", "super_admin"):
        raise HTTPException(status_code=403, detail="admin/manager/super_admin only")


# ── Response models ──────────────────────────────────────────────
class IntegrationsListResponse(BaseModel):
    integrations: List[ConnectionSummary]
    tenant_id: str


class ConnectLinkResponse(BaseModel):
    url: str
    state: str


class DeleteResponse(BaseModel):
    removed: bool
    provider_key: str


# ── GET /tenants/me/integrations ─────────────────────────────────
@router.get(
    "/tenants/me/integrations",
    response_model=IntegrationsListResponse,
    operation_id="tenants.integrations.list",
)
async def list_tenant_integrations(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_read_role(user)
    summaries = await list_connections(tenant["id"])
    return IntegrationsListResponse(
        integrations=summaries,
        tenant_id=tenant["id"],
    )


# ── POST /tenants/me/integrations/{key}/test ─────────────────────
@router.post(
    "/tenants/me/integrations/{provider_key}/test",
    response_model=ConnectionHealth,
    operation_id="tenants.integrations.test",
)
async def test_tenant_integration(
    provider_key: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    try:
        provider = get_provider(provider_key)
    except UnknownProvider:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider_key}")
    result = await provider.test_connection(tenant_id=tenant["id"])
    return result


# ── DELETE /tenants/me/integrations/{key} ────────────────────────
@router.delete(
    "/tenants/me/integrations/{provider_key}",
    response_model=DeleteResponse,
    operation_id="tenants.integrations.delete",
)
async def delete_tenant_integration(
    provider_key: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    removed = await remove_secret(tenant["id"], provider_key)
    return DeleteResponse(removed=removed, provider_key=provider_key)


# ── GET /integrations/stripe/connect-link ────────────────────────
@router.get(
    "/integrations/stripe/connect-link",
    response_model=ConnectLinkResponse,
    operation_id="integrations.stripe.connectLink",
)
async def stripe_connect_link(
    request: Request,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    state = uuid.uuid4().hex
    # Persist state → tenant mapping so the callback can verify.
    await db.oauth_pending.insert_one({
        "id": state,
        "state": state,
        "tenant_id": tenant["id"],
        "provider_key": "stripe",
        "user_id": user["id"],
        "expires_at": (_now() + timedelta(seconds=_OAUTH_STATE_TTL_SECONDS)).isoformat(),
        "created_at": _now_iso(),
    })
    # Prefer the request's origin so the redirect returns to the
    # right pod URL in preview + prod without any static config.
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/integrations/stripe/callback"
    testmode_mock = os.environ.get("STRIPE_TESTMODE_MOCK_CONNECT", "").strip().lower() in ("1", "true", "yes")
    if testmode_mock:
        # Short-circuit: the FE hits this URL directly and lands
        # back on the callback with a synthetic ``code``.
        url = f"{redirect_uri}?code=mock_stripe_code_{state[:8]}&state={state}"
    else:
        try:
            url = build_connect_link(state=state, redirect_uri=redirect_uri)
        except TenantPaymentError as e:
            raise HTTPException(status_code=503, detail=str(e))
    return ConnectLinkResponse(url=url, state=state)


# ── GET /integrations/stripe/callback ────────────────────────────
@router.get(
    "/integrations/stripe/callback",
    operation_id="integrations.stripe.callback",
)
async def stripe_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
):
    """Exchange the ``code`` for a Stripe connected-account
    ``stripe_user_id`` + ``access_token``. Persist via
    ``services.secrets``. Redirect to the FE ``/settings/integrations``
    page with a status flag."""
    pending = await db.oauth_pending.find_one({"state": state, "provider_key": "stripe"})
    fe_base = str(request.base_url).rstrip("/")
    fail_redirect = f"{fe_base}/settings/integrations?connect=error"
    ok_redirect = f"{fe_base}/settings/integrations?connect=success"
    if not pending:
        return RedirectResponse(url=fail_redirect + "&reason=state_unknown", status_code=302)
    expires_at = pending.get("expires_at")
    try:
        exp_dt = datetime.fromisoformat(expires_at)
    except Exception:
        exp_dt = None
    if exp_dt and exp_dt < _now():
        await db.oauth_pending.delete_one({"state": state})
        return RedirectResponse(url=fail_redirect + "&reason=state_expired", status_code=302)

    tenant_id = pending["tenant_id"]
    testmode_mock = os.environ.get("STRIPE_TESTMODE_MOCK_CONNECT", "").strip().lower() in ("1", "true", "yes")
    if testmode_mock:
        # Store a synthetic connected account so the FE can render
        # a "Connected" state without leaving the pod.
        try:
            await put_secret(
                tenant_id, "stripe",
                plaintext=f"sk_test_mock_{uuid.uuid4().hex[:20]}",
                connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
                connected_account_id=f"acct_test_{uuid.uuid4().hex[:12]}",
            )
            await db.oauth_pending.delete_one({"state": state})
        except Exception as e:
            await log_secret_error(
                tenant_id, "stripe",
                code="MOCK_CONNECT_PERSIST_FAILED", message=str(e))
            return RedirectResponse(url=fail_redirect + "&reason=persist_failed", status_code=302)
        return RedirectResponse(url=ok_redirect, status_code=302)

    from services.payments.tenant_stripe import StripeConnectProvider
    provider = StripeConnectProvider()
    try:
        data = await provider.exchange_oauth_code(code=code)
    except TenantPaymentError as e:
        log.warning("stripe callback exchange failed: %s", type(e).__name__)
        await log_secret_error(
            tenant_id, "stripe",
            code="OAUTH_EXCHANGE_FAILED", message=type(e).__name__)
        return RedirectResponse(url=fail_redirect + "&reason=exchange_failed", status_code=302)

    access_token = data.get("access_token")
    connected_account_id = data.get("stripe_user_id")
    if not access_token or not connected_account_id:
        await log_secret_error(
            tenant_id, "stripe",
            code="OAUTH_MISSING_FIELDS",
            message="stripe token response missing access_token / stripe_user_id",
        )
        return RedirectResponse(url=fail_redirect + "&reason=missing_fields", status_code=302)

    await put_secret(
        tenant_id, "stripe",
        plaintext=access_token,
        connection_type=ConnectionType.OAUTH_STRIPE_CONNECT,
        connected_account_id=connected_account_id,
    )
    await db.oauth_pending.delete_one({"state": state})
    return RedirectResponse(url=ok_redirect, status_code=302)


# ── POST /integrations/stripe/webhook ────────────────────────────
@router.post(
    "/integrations/stripe/webhook",
    operation_id="integrations.stripe.webhook",
)
async def stripe_webhook(request: Request):
    """Verify signature, dedupe by event.id, log. This is intentionally
    thin — event routing to per-tenant handlers is I1.7.a.2 (follow-up
    subphase). Today we just prove the pipe is wired end-to-end."""
    from services.payments.tenant_stripe import StripeConnectProvider
    provider = StripeConnectProvider()
    payload = await request.body()
    headers = dict(request.headers.items())
    try:
        event = await provider.verify_webhook(payload=payload, headers=headers)
    except TenantPaymentError as e:
        return Response(
            content=f'{{"detail":"verify_failed","reason":"{type(e).__name__}"}}',
            status_code=400,
            media_type="application/json",
        )
    # Idempotency: dedupe by event.id in ``stripe_webhook_events``.
    if event.id:
        existing = await db.stripe_webhook_events.find_one({"event_id": event.id})
        if existing:
            return {"received": True, "duplicate": True}
        await db.stripe_webhook_events.insert_one({
            "id": uuid.uuid4().hex,
            "event_id": event.id,
            "event_type": event.event_type,
            "provider_key": event.provider_key,
            "at": _now_iso(),
        })
    return {"received": True, "duplicate": False}
