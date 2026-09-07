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
# Phase I1.7.b · Feb-2026 — SMS + Email BYO providers.
from services.messaging._helpers import save_provider_config
from services.messaging.email.registry import (
    get_email_provider,
    get_provider_field_schemas as _email_provider_field_schemas,
    list_registered_email_provider_keys,
)
from services.messaging.models import (
    InvalidProviderConfig,
    UnknownMessagingProvider,
)
from services.messaging.sms.registry import (
    get_sms_provider,
    get_provider_field_schemas as _sms_provider_field_schemas,
    list_registered_sms_provider_keys,
)


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


# ── Provider-key resolution across registries ───────────────────
_SMS_KEYS = set(list_registered_sms_provider_keys())
_EMAIL_KEYS = set(list_registered_email_provider_keys())


def _kind_for(provider_key: str) -> str:
    if provider_key in _SMS_KEYS:
        return "sms"
    if provider_key in _EMAIL_KEYS:
        return "email"
    return "payments"


def _resolve_provider(provider_key: str):
    """Return the concrete adapter for ``provider_key`` from whichever
    registry knows it. Raises ``HTTPException(404)`` on unknown key.

    Returns a tuple ``(kind, provider)`` where ``kind`` is
    ``"payments" | "sms" | "email"`` so callers can pick the correct
    ``test_connection`` signature.
    """
    kind = _kind_for(provider_key)
    try:
        if kind == "sms":
            return kind, get_sms_provider(provider_key)
        if kind == "email":
            return kind, get_email_provider(provider_key)
        return kind, get_provider(provider_key)
    except (UnknownProvider, UnknownMessagingProvider):
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider_key}")


# ── Kind-alias hint for common URL mistakes (I1.7.b.fix) ─────────
_KIND_ALIASES = {
    "sms": "sms",
    "email": "email",
    "messaging": "sms",
}


def _friendly_unknown_provider_error(provider_key: str) -> str:
    """Return a helpful message when a caller PUTs to a category
    kind (``/sms``, ``/email``) instead of a concrete provider key
    (``/twilio``, ``/resend``, …). Falls back to a generic message
    when the key isn't a known alias."""
    alias = _KIND_ALIASES.get(provider_key.lower())
    if alias == "sms":
        keys = ", ".join(sorted(_SMS_KEYS))
        return (f"unknown provider key '{provider_key}'. Did you mean "
                f"one of: {keys}? See "
                f"/api/tenants/me/integrations/schemas for the full "
                f"provider list.")
    if alias == "email":
        keys = ", ".join(sorted(_EMAIL_KEYS))
        return (f"unknown provider key '{provider_key}'. Did you mean "
                f"one of: {keys}? See "
                f"/api/tenants/me/integrations/schemas for the full "
                f"provider list.")
    return (f"unknown provider key '{provider_key}'. See "
            f"/api/tenants/me/integrations/schemas for the full "
            f"provider list.")


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
    kind, provider = _resolve_provider(provider_key)
    result = await provider.test_connection(tenant_id=tenant["id"])
    # SMS/Email ConnectionHealth is a sibling shape; convert to the
    # payments ConnectionHealth Pydantic model (same fields) for a
    # uniform response.
    return ConnectionHealth(**result.model_dump())


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


# ── PUT /tenants/me/integrations/{key} (I1.7.b) ──────────────────
class SaveIntegrationBody(BaseModel):
    """Body for saving a tenant messaging-provider config.

    ``config`` is the ``{field_name: value}`` dict matching the
    provider's ``config_fields`` schema. Values include BOTH the
    secret and public fields — everything ends up encrypted at rest.
    """
    config: Dict[str, Any]
    # Optional public identifier stored on the row (e.g. Twilio
    # ``account_sid``, SMTP ``username``) so the UI can display it
    # without decrypting the blob.
    public_account_id: Optional[str] = None


class SaveIntegrationResponse(BaseModel):
    provider_key: str
    saved: bool
    connected_account_id_masked: Optional[str] = None


@router.put(
    "/tenants/me/integrations/{provider_key}",
    response_model=SaveIntegrationResponse,
    operation_id="tenants.integrations.save",
)
async def save_tenant_integration(
    provider_key: str,
    body: SaveIntegrationBody,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Save (encrypt + persist) a messaging-provider config for the
    current tenant. Payment providers (``stripe``) use the OAuth
    ``/connect-link → /callback`` flow instead — this endpoint
    refuses the ``stripe`` key on purpose.
    """
    _require_write_role(user)
    # I1.7.b.fix — dedicated messages for common URL mistakes.
    if provider_key.lower() in _KIND_ALIASES:
        raise HTTPException(
            status_code=400,
            detail=_friendly_unknown_provider_error(provider_key),
        )
    kind = _kind_for(provider_key)
    if kind not in ("sms", "email"):
        # Every non-messaging key ends up here. ``stripe`` (payment
        # provider) uses OAuth; everything else is unknown.
        if provider_key == "stripe":
            raise HTTPException(
                status_code=400,
                detail="Stripe uses the OAuth /connect-link flow — "
                       "call GET /api/integrations/stripe/connect-link "
                       "instead of PUT /api/tenants/me/integrations/stripe.",
            )
        raise HTTPException(
            status_code=400,
            detail=_friendly_unknown_provider_error(provider_key),
        )
    # Resolve the provider to grab its field schema.
    _, provider = _resolve_provider(provider_key)
    schema = getattr(provider, "config_fields", {}) or {}
    # Pick a public account id automatically if the caller didn't
    # supply one: prefer the first non-secret field's value.
    pub = body.public_account_id
    if not pub:
        for name, meta in schema.items():
            if meta.get("required") and not meta.get("secret"):
                v = body.config.get(name)
                if v is not None and str(v).strip():
                    pub = str(v)
                    break
    try:
        await save_provider_config(
            tenant_id=tenant["id"], provider_key=provider_key,
            config=body.config, schema=schema, public_account_id=pub,
            primary_secret_field=getattr(provider, "primary_secret_field", None),
        )
    except InvalidProviderConfig as e:
        # ``str(e)`` only names the fields — never their values.
        raise HTTPException(status_code=400, detail=str(e))
    # Mask the public id for the response so the UI can render it.
    masked = None
    if pub:
        masked = f"{pub[:5]}…{pub[-4:]}" if len(pub) > 8 else pub
    return SaveIntegrationResponse(
        provider_key=provider_key, saved=True,
        connected_account_id_masked=masked,
    )


# ── GET /tenants/me/integrations/schemas (I1.7.b) ────────────────
class ProviderFieldSchemaEntry(BaseModel):
    name: str
    required: bool
    secret: bool
    label: str


class ProviderSchema(BaseModel):
    provider_key: str
    kind: str  # "sms" | "email"
    fields: List[ProviderFieldSchemaEntry]


class ProviderSchemasResponse(BaseModel):
    sms: List[ProviderSchema]
    email: List[ProviderSchema]


def _to_field_entries(fields: Dict[str, Dict[str, Any]]) -> List[ProviderFieldSchemaEntry]:
    out: List[ProviderFieldSchemaEntry] = []
    for name, meta in fields.items():
        out.append(ProviderFieldSchemaEntry(
            name=name,
            required=bool(meta.get("required", False)),
            secret=bool(meta.get("secret", False)),
            label=str(meta.get("label", name)),
        ))
    return out


@router.get(
    "/tenants/me/integrations/schemas",
    response_model=ProviderSchemasResponse,
    operation_id="tenants.integrations.schemas",
)
async def integrations_schemas(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Return the field schemas for every SMS + Email provider so
    the settings UI can render dynamic forms. NEVER echoes any
    stored value — schemas describe the shape, not the data."""
    _require_read_role(user)
    sms_schemas = [
        ProviderSchema(provider_key=k, kind="sms",
                          fields=_to_field_entries(v))
        for k, v in _sms_provider_field_schemas().items()
    ]
    email_schemas = [
        ProviderSchema(provider_key=k, kind="email",
                          fields=_to_field_entries(v))
        for k, v in _email_provider_field_schemas().items()
    ]
    return ProviderSchemasResponse(sms=sms_schemas, email=email_schemas)


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
