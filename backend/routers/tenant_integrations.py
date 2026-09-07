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
    connection_summary as _connection_summary,
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
from services.messaging._helpers import (
    load_provider_config as _load_messaging_config,
    save_provider_config,
)
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
# Phase I1.7.c.1 · Feb-2026 — AI BYO providers.
from services.ai import (
    AIProviderUsage,
    AIUsageResponse,
    InvalidAIProviderConfig,
    UnknownAIProvider,
    get_ai_provider,
    get_ai_provider_by_short_name,
    get_provider_field_schemas as _ai_provider_field_schemas,
    get_provider_model_options as _ai_provider_model_options,
    list_registered_ai_provider_keys,
    list_short_names as _ai_short_names,
    short_name_for as _ai_short_name_for,
)
from services.ai._helpers import (
    current_period_yyyymm as _ai_period,
    save_provider_config as save_ai_provider_config,
)
from services.ai.usage import (
    SOFT_WARN_RATIO as _AI_SOFT_WARN_RATIO,
    _compute_status as _ai_compute_status,
    get_all_usage_rows as _ai_get_all_usage_rows,
    get_provider_meta as _ai_get_provider_meta,
    remove_provider_meta as _ai_remove_provider_meta,
    upsert_provider_meta as _ai_upsert_provider_meta,
)
# Phase I1.7.c.2 · Feb-2026 — Maps BYO providers.
from services.maps import (
    MapsProviderUsage,
    MapsUsageResponse,
    InvalidMapsProviderConfig,
    UnknownMapsProvider,
    get_maps_provider,
    get_provider_field_schemas as _maps_provider_field_schemas,
    list_registered_maps_provider_keys,
    list_short_names as _maps_short_names,
    short_name_for as _maps_short_name_for,
)
from services.maps._helpers import (
    current_period_yyyymm as _maps_period,
    save_provider_config as save_maps_provider_config,
)
from services.maps.usage import (
    _compute_status as _maps_compute_status,
    get_all_usage_rows as _maps_get_all_usage_rows,
    get_provider_meta as _maps_get_provider_meta,
    remove_provider_meta as _maps_remove_provider_meta,
    upsert_provider_meta as _maps_upsert_provider_meta,
)
# Phase I1.7.c.3 · Feb-2026 — Tenant Calendars BYO (Google + Outlook).
# Skip Apple/CalDAV/iCloud per phase scope. Polling-only for MVP;
# webhooks scheduled as an I1.7.e follow-up.
from services.calendars import (
    CalendarProviderUsage,
    CalendarUsageResponse,
    InvalidCalendarProviderConfig,
    UnknownCalendarProvider,
    TechnicianCalendarLinkSummary,
    get_calendar_provider,
    get_provider_field_schemas as _cal_provider_field_schemas,
    list_registered_calendar_provider_keys,
    list_short_names as _cal_short_names,
    short_name_for as _cal_short_name_for,
    build_state_token as _cal_build_state,
    verify_state_token as _cal_verify_state,
    OAuthStateError as _CalOAuthStateError,
    OAuthStateExpired as _CalOAuthStateExpired,
    OAuthStateReplayed as _CalOAuthStateReplayed,
    OAuthStateTampered as _CalOAuthStateTampered,
)
from services.calendars._helpers import (
    current_period_yyyymm as _cal_period,
    calendars_testmode_mock as _cal_testmode,
)
from services.calendars.usage import (
    _compute_status as _cal_compute_status,
    get_all_usage_rows as _cal_get_all_usage_rows,
    get_provider_meta as _cal_get_provider_meta,
    remove_provider_meta as _cal_remove_provider_meta,
    upsert_provider_meta as _cal_upsert_provider_meta,
)
from services.calendars.technician_link import (
    ensure_indexes as _cal_ensure_link_indexes,
    upsert_link as _cal_upsert_link,
    get_link as _cal_get_link,
    list_links_for_tenant as _cal_list_links_for_tenant,
    remove_link as _cal_remove_link,
    summary_from_row as _cal_summary_from_row,
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
_AI_KEYS = set(list_registered_ai_provider_keys())
_MAPS_KEYS = set(list_registered_maps_provider_keys())
_CAL_KEYS = set(list_registered_calendar_provider_keys())


def _kind_for(provider_key: str) -> str:
    if provider_key in _SMS_KEYS:
        return "sms"
    if provider_key in _EMAIL_KEYS:
        return "email"
    if provider_key in _AI_KEYS:
        return "ai"
    if provider_key in _MAPS_KEYS:
        return "maps"
    if provider_key in _CAL_KEYS:
        return "calendars"
    return "payments"


def _resolve_provider(provider_key: str):
    kind = _kind_for(provider_key)
    try:
        if kind == "sms":
            return kind, get_sms_provider(provider_key)
        if kind == "email":
            return kind, get_email_provider(provider_key)
        if kind == "ai":
            return kind, get_ai_provider(provider_key)
        if kind == "maps":
            return kind, get_maps_provider(provider_key)
        if kind == "calendars":
            return kind, get_calendar_provider(provider_key)
        return kind, get_provider(provider_key)
    except (UnknownProvider, UnknownMessagingProvider, UnknownAIProvider,
             UnknownMapsProvider, UnknownCalendarProvider):
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
    # Phase I1.7.c.1 — AI provider metadata sidecar also needs cleanup.
    if _kind_for(provider_key) == "ai":
        short = _ai_short_name_for(provider_key) or provider_key
        try:
            await _ai_remove_provider_meta(tenant_id=tenant["id"], provider=short)
        except Exception:
            pass
    # Phase I1.7.c.2 — Maps provider metadata sidecar cleanup.
    if _kind_for(provider_key) == "maps":
        short = _maps_short_name_for(provider_key) or provider_key
        try:
            await _maps_remove_provider_meta(tenant_id=tenant["id"], provider=short)
        except Exception:
            pass
    # Phase I1.7.c.3 — Calendars: DELETE at the tenant level tears
    # down every per-technician link AND the provider sidecar so
    # "disconnect provider" from the settings UI wipes the whole
    # provider footprint. Per-tech disconnect uses the dedicated
    # /calendars_{provider}/disconnect endpoint below.
    if _kind_for(provider_key) == "calendars":
        short = _cal_short_name_for(provider_key) or provider_key
        try:
            links = await _cal_list_links_for_tenant(
                tenant_id=tenant["id"], provider_key=provider_key,
            )
            for lk in links:
                await _cal_remove_link(
                    tenant_id=tenant["id"],
                    technician_user_id=lk.get("technician_user_id", ""),
                    provider_key=provider_key,
                )
            await _cal_remove_provider_meta(tenant_id=tenant["id"], provider=short)
            # Signal removal even when there was no tenant-level
            # ``tenant_secrets`` row (calendars store secrets per-tech,
            # so the top-level ``remove_secret`` above almost always
            # reports ``removed=False``).
            removed = removed or bool(links)
        except Exception:
            pass
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
    # Phase I1.7.c.1 — AI providers only. Cap semantics:
    #   None => unlimited (default)
    #   0    => block all (explicit kill-switch)
    #   >0   => hard block at ``used >= cap`` (tokens_total).
    # Ignored for non-AI providers.
    monthly_token_cap: Optional[int] = None
    # Phase I1.7.c.2 — Maps providers only. Same semantics as above,
    # but the counter is request-count instead of tokens. Ignored
    # for non-Maps providers.
    monthly_request_cap: Optional[int] = None
    # Phase I1.7.c.3 — Calendars providers only. Same semantics as
    # above; counter is sync-op count (push_event + pull_delta) instead
    # of tokens / requests. Ignored for non-Calendars providers.
    monthly_sync_op_cap: Optional[int] = None


class SaveIntegrationResponse(BaseModel):
    provider_key: str
    saved: bool
    connected_account_id_masked: Optional[str] = None


async def _preserve_stored_secrets(
    *, tenant_id: str, provider_key: str,
    incoming_config: Dict[str, Any],
    schema: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Fix-2026-02 · post-tester merge helper — preserve stored secrets
    on partial edits.

    Historically the PUT handler rejected any request whose ``config``
    payload didn't include every ``required=True`` field. That broke
    the natural "adjust the cap / model / from-number without
    re-typing the api_key" gesture. This helper makes partial edits
    UNIFORM across every provider (AI / SMS / Email):

    * If the provider is **already connected** for this tenant, load
      its stored decrypted config and merge the incoming payload on
      top — incoming NON-BLANK values win, blanks preserve the
      stored value. Validation still runs against the merged result,
      so a genuinely-missing required field on an *unconnected*
      provider still gets a 400/422.

    * Only secret-shaped values are ever preserved from storage.
      Non-secret fields on the incoming payload are taken at face
      value; if they arrive blank AND are marked required, the
      merged config surfaces that as a validation failure the way
      it did before this patch.

    ``incoming_config`` MAY be mutated in place. The helper returns
    the merged dict for convenience.
    """
    stored = await _load_messaging_config(
        tenant_id=tenant_id, provider_key=provider_key,
    )
    if not stored:
        return incoming_config
    merged: Dict[str, Any] = dict(stored)
    for k, v in (incoming_config or {}).items():
        if isinstance(v, str) and not v.strip():
            # Blank string on a known field — preserve stored value
            # if the field is marked ``secret=True``; otherwise keep
            # the blank (lets tenants deliberately clear an optional
            # non-secret field like ``default_model``).
            meta = schema.get(k) or {}
            if meta.get("secret"):
                continue
            merged[k] = v
        elif v is None:
            # ``None`` = "not provided"; preserve stored for secrets.
            meta = schema.get(k) or {}
            if meta.get("secret"):
                continue
            merged[k] = v
        else:
            merged[k] = v
    # If the incoming payload omitted a secret field entirely and we
    # have a stored value, ``merged`` already contains the stored
    # value (via ``dict(stored)`` init) — nothing more to do.
    return merged


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
    if kind == "ai":
        # I1.7.c.1 — AI providers accept the same body shape as
        # messaging providers, PLUS optional ``default_model`` and
        # ``monthly_token_cap`` (see ``SaveIntegrationBody``).
        _, ai_provider = _resolve_provider(provider_key)
        schema = getattr(ai_provider, "config_fields", {}) or {}
        # Fix-2026-02 — preserve stored api_key on partial edits.
        merged_config = await _preserve_stored_secrets(
            tenant_id=tenant["id"], provider_key=provider_key,
            incoming_config=dict(body.config or {}),
            schema=schema,
        )
        try:
            await save_ai_provider_config(
                tenant_id=tenant["id"], provider_key=provider_key,
                config=merged_config, schema=schema,
                primary_secret_field=getattr(ai_provider, "primary_secret_field", None),
            )
        except InvalidAIProviderConfig as e:
            raise HTTPException(status_code=400, detail=str(e))
        short = _ai_short_name_for(provider_key) or provider_key
        # Persist the sidecar (cap + default_model) — plaintext so the
        # cap-check on dispatch avoids a decrypt on every call.
        cap = body.monthly_token_cap
        if cap is not None:
            try:
                cap = int(cap)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="monthly_token_cap must be an integer or null",
                )
            if cap < 0:
                raise HTTPException(
                    status_code=400,
                    detail="monthly_token_cap must be >= 0 (null = unlimited, 0 = block all)",
                )
        default_model = merged_config.get("default_model") if isinstance(merged_config, dict) else None
        await _ai_upsert_provider_meta(
            tenant_id=tenant["id"], provider=short,
            monthly_token_cap=cap, default_model=default_model,
        )
        return SaveIntegrationResponse(
            provider_key=provider_key, saved=True,
            connected_account_id_masked=None,
        )
    if kind == "maps":
        # I1.7.c.2 — Maps providers mirror the AI branch: reuse
        # ``_preserve_stored_secrets``, share the cap-parse rules,
        # persist metadata (cap + provider-specific extras like
        # ``region_bias`` / ``style``) in ``tenant_maps_provider``.
        _, maps_provider = _resolve_provider(provider_key)
        schema = getattr(maps_provider, "config_fields", {}) or {}
        merged_config = await _preserve_stored_secrets(
            tenant_id=tenant["id"], provider_key=provider_key,
            incoming_config=dict(body.config or {}),
            schema=schema,
        )
        try:
            await save_maps_provider_config(
                tenant_id=tenant["id"], provider_key=provider_key,
                config=merged_config, schema=schema,
                primary_secret_field=getattr(maps_provider, "primary_secret_field", None),
            )
        except InvalidMapsProviderConfig as e:
            raise HTTPException(status_code=400, detail=str(e))
        short = _maps_short_name_for(provider_key) or provider_key
        cap = body.monthly_request_cap
        if cap is not None:
            try:
                cap = int(cap)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="monthly_request_cap must be an integer or null",
                )
            if cap < 0:
                raise HTTPException(
                    status_code=400,
                    detail="monthly_request_cap must be >= 0 (null = unlimited, 0 = block all)",
                )
        # Non-secret extras (region_bias, style, …) surface in the
        # sidecar so the settings UI can render them without a decrypt.
        extras: Dict[str, Any] = {}
        for name, meta in (schema or {}).items():
            if not meta.get("secret"):
                v = merged_config.get(name)
                if v is not None:
                    extras[name] = v
        await _maps_upsert_provider_meta(
            tenant_id=tenant["id"], provider=short,
            monthly_request_cap=cap, extras=extras,
        )
        return SaveIntegrationResponse(
            provider_key=provider_key, saved=True,
            connected_account_id_masked=None,
        )
    if kind == "calendars":
        # I1.7.c.3 — Calendars are per-technician OAuth. The
        # ``PUT /calendars_{provider}`` endpoint only persists tenant-
        # level cap + non-secret extras (e.g. default_calendar_id) —
        # the OAuth tokens are stored per-tech via /oauth/callback.
        _, cal_provider = _resolve_provider(provider_key)
        schema = getattr(cal_provider, "config_fields", {}) or {}
        cap = body.monthly_sync_op_cap
        if cap is not None:
            try:
                cap = int(cap)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="monthly_sync_op_cap must be an integer or null",
                )
            if cap < 0:
                raise HTTPException(
                    status_code=400,
                    detail="monthly_sync_op_cap must be >= 0 (null = unlimited, 0 = block all)",
                )
        short = _cal_short_name_for(provider_key) or provider_key
        # Non-secret extras from the incoming config (default_calendar_id, …).
        extras: Dict[str, Any] = {}
        for name, meta in (schema or {}).items():
            if meta.get("secret"):
                continue
            if name == "monthly_sync_op_cap":
                continue
            v = (body.config or {}).get(name)
            if v is not None:
                extras[name] = v
        await _cal_upsert_provider_meta(
            tenant_id=tenant["id"], provider=short,
            monthly_sync_op_cap=cap, extras=extras,
        )
        return SaveIntegrationResponse(
            provider_key=provider_key, saved=True,
            connected_account_id_masked=None,
        )
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
    # Fix-2026-02 — preserve stored secrets on partial edits so a
    # tenant can e.g. change the twilio ``from_number`` without
    # re-typing the auth token.
    merged_config = await _preserve_stored_secrets(
        tenant_id=tenant["id"], provider_key=provider_key,
        incoming_config=dict(body.config or {}),
        schema=schema,
    )
    # Pick a public account id automatically if the caller didn't
    # supply one: prefer the first non-secret field's value.
    pub = body.public_account_id
    if not pub:
        for name, meta in schema.items():
            if meta.get("required") and not meta.get("secret"):
                v = merged_config.get(name)
                if v is not None and str(v).strip():
                    pub = str(v)
                    break
    try:
        await save_provider_config(
            tenant_id=tenant["id"], provider_key=provider_key,
            config=merged_config, schema=schema, public_account_id=pub,
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
    kind: str  # "sms" | "email" | "ai" | "maps"
    fields: List[ProviderFieldSchemaEntry]
    # I1.7.c.1 — models dropdown options (empty for non-AI providers).
    models: List[str] = []


class ProviderSchemasResponse(BaseModel):
    sms: List[ProviderSchema]
    email: List[ProviderSchema]
    ai: List[ProviderSchema] = []
    maps: List[ProviderSchema] = []
    calendars: List[ProviderSchema] = []


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
    ai_models_map = _ai_provider_model_options()
    ai_schemas = [
        ProviderSchema(provider_key=k, kind="ai",
                          fields=_to_field_entries(v),
                          models=ai_models_map.get(k, []))
        for k, v in _ai_provider_field_schemas().items()
    ]
    maps_schemas = [
        ProviderSchema(provider_key=k, kind="maps",
                          fields=_to_field_entries(v))
        for k, v in _maps_provider_field_schemas().items()
    ]
    cal_schemas = [
        ProviderSchema(provider_key=k, kind="calendars",
                          fields=_to_field_entries(v))
        for k, v in _cal_provider_field_schemas().items()
    ]
    return ProviderSchemasResponse(
        sms=sms_schemas, email=email_schemas,
        ai=ai_schemas, maps=maps_schemas,
        calendars=cal_schemas,
    )


# ── GET /tenants/me/integrations/ai/usage (I1.7.c.1) ─────────────
@router.get(
    "/tenants/me/integrations/ai/usage",
    response_model=AIUsageResponse,
    operation_id="tenants.integrations.ai.usage",
)
async def get_tenant_ai_usage(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Return per-provider monthly token usage + cap for the current
    tenant. Includes rows for BOTH configured providers (with their
    ``monthly_token_cap``) and any providers with usage rows this
    period. Rows with ``pct_used >= 0.8`` surface a ``warn`` status;
    rows at or above cap surface ``blocked`` — the FE renders these
    in a progress bar (green / amber / red).
    """
    _require_read_role(user)
    period = _ai_period()
    tid = tenant["id"]
    # Merge: any provider with metadata (configured) OR any provider
    # with usage this month gets a row.
    providers_present = set()
    metas: Dict[str, Dict[str, Any]] = {}
    for short in _ai_short_names():
        m = await _ai_get_provider_meta(tenant_id=tid, provider=short)
        if m:
            providers_present.add(short)
            metas[short] = m
    usage_rows = await _ai_get_all_usage_rows(tenant_id=tid, period_yyyymm=period)
    usage_by_short: Dict[str, Dict[str, Any]] = {
        r["provider"]: r for r in usage_rows if r.get("provider")
    }
    providers_present.update(usage_by_short.keys())
    out: List[AIProviderUsage] = []
    for short in sorted(providers_present):
        meta = metas.get(short) or {}
        usage = usage_by_short.get(short) or {}
        cap_raw = meta.get("monthly_token_cap")
        cap = int(cap_raw) if cap_raw is not None else None
        used = int(usage.get("tokens_total", 0) or 0)
        pct = None
        if cap is not None and cap > 0:
            pct = round(used / cap, 4)
        status_val = _ai_compute_status(used=used, cap=cap)
        out.append(AIProviderUsage(
            provider=short,
            period_yyyymm=period,
            tokens_prompt=int(usage.get("tokens_prompt", 0) or 0),
            tokens_completion=int(usage.get("tokens_completion", 0) or 0),
            tokens_total=used,
            monthly_token_cap=cap,
            default_model=meta.get("default_model"),
            connected=short in metas,
            pct_used=pct,
            status=status_val,
        ))
    return AIUsageResponse(tenant_id=tid, period_yyyymm=period, providers=out)


# ── GET /tenants/me/integrations/maps/usage (I1.7.c.2) ───────────
@router.get(
    "/tenants/me/integrations/maps/usage",
    response_model=MapsUsageResponse,
    operation_id="tenants.integrations.maps.usage",
)
async def get_tenant_maps_usage(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Per-provider monthly request counters + cap for the current
    tenant. Counters are broken down per operation
    (``geocode``, ``route``, ``static_map``) with a rolled-up
    ``total`` — the cap is enforced against ``total``. Status flags
    mirror AI: ``ok`` / ``warn`` (>=80%) / ``blocked`` (>=100%)."""
    _require_read_role(user)
    period = _maps_period()
    tid = tenant["id"]
    providers_present = set()
    metas: Dict[str, Dict[str, Any]] = {}
    for short in _maps_short_names():
        m = await _maps_get_provider_meta(tenant_id=tid, provider=short)
        if m:
            providers_present.add(short)
            metas[short] = m
    usage_rows = await _maps_get_all_usage_rows(tenant_id=tid, period_yyyymm=period)
    usage_by_short: Dict[str, Dict[str, Any]] = {
        r["provider"]: r for r in usage_rows if r.get("provider")
    }
    providers_present.update(usage_by_short.keys())
    out: List[MapsProviderUsage] = []
    for short in sorted(providers_present):
        meta = metas.get(short) or {}
        usage = usage_by_short.get(short) or {}
        cap_raw = meta.get("monthly_request_cap")
        cap = int(cap_raw) if cap_raw is not None else None
        used = int(usage.get("total", 0) or 0)
        pct = None
        if cap is not None and cap > 0:
            pct = round(used / cap, 4)
        out.append(MapsProviderUsage(
            provider=short,
            period_yyyymm=period,
            geocode=int(usage.get("geocode", 0) or 0),
            route=int(usage.get("route", 0) or 0),
            static_map=int(usage.get("static_map", 0) or 0),
            total=used,
            monthly_request_cap=cap,
            connected=short in metas,
            pct_used=pct,
            status=_maps_compute_status(used=used, cap=cap),
        ))
    return MapsUsageResponse(tenant_id=tid, period_yyyymm=period, providers=out)


# ── Phase I1.7.c.3 · Calendars BYO (Google Calendar + Outlook) ──
# All routes here are per-technician OAuth flows. Cap semantics
# match AI/Maps (null=unlimited, 0=block, >0=hard-block at >=cap,
# warn at 80%). Counters: push_event, pull_delta, total.

def _cal_settle_frontend_url(status_str: str, provider_short: str,
                              technician_user_id: str, error: str = "") -> str:
    """Compose the callback-completion redirect URL. Uses
    ``APP_PUBLIC_URL`` if set, otherwise a same-origin path so the
    preview environment stays inside the ingress."""
    base = (os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    path = (f"/settings/integrations?calendar_connect={status_str}"
            f"&provider={provider_short}"
            f"&technician_user_id={technician_user_id}")
    if error:
        # Never echo the raw exception message — surface a bucket.
        path += f"&error={error}"
    return f"{base}{path}" if base else path


def _cal_require_start_role(
    *, user: Dict[str, Any], technician_user_id: str,
) -> None:
    """super/admin can start OAuth for any technician in their tenant.
    A technician can start OAuth for themselves (self-service).
    Everyone else → 403."""
    role = user.get("role")
    if role in ("super_admin", "admin"):
        return
    if user.get("id") == technician_user_id:
        return
    raise HTTPException(
        status_code=403,
        detail="only admins can initiate OAuth for other technicians",
    )


class CalendarsUsageAndLinksResponse(BaseModel):
    tenant_id: str
    period_yyyymm: str
    providers: List[CalendarProviderUsage]
    technicians: List[TechnicianCalendarLinkSummary]


class OAuthStartResponse(BaseModel):
    """Returned by the JSON variant of /oauth/start (browsers usually
    hit the 302 variant below; SPAs / tests can grab the URL here)."""
    provider_key: str
    provider: str
    technician_user_id: str
    auth_url: str
    state: str


class CalendarDisconnectBody(BaseModel):
    technician_user_id: str


# ── GET /tenants/me/integrations/calendars_{provider}/oauth/start ─
@router.get(
    "/tenants/me/integrations/calendars_{provider_short}/oauth/start",
    operation_id="tenants.integrations.calendars.oauth.start",
)
async def calendars_oauth_start(
    provider_short: str,
    technician_user_id: str = Query(..., min_length=1),
    format: str = Query(
        "redirect",
        pattern="^(redirect|json)$",
        description="``redirect`` returns 302 to the provider auth URL. "
                    "``json`` returns the URL as JSON.",
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    provider_key = f"calendars_{provider_short}"
    if provider_key not in _CAL_KEYS:
        raise HTTPException(status_code=404,
                             detail=f"unknown calendars provider: {provider_short}")
    _cal_require_start_role(user=user, technician_user_id=technician_user_id)
    provider = get_calendar_provider(provider_key)
    state = _cal_build_state(
        tenant_id=tenant["id"],
        technician_user_id=technician_user_id,
        provider_short=provider_short,
    )
    try:
        auth_url = provider.build_auth_url(state=state)
    except InvalidCalendarProviderConfig as e:
        raise HTTPException(status_code=503, detail=str(e))
    if format == "json":
        return OAuthStartResponse(
            provider_key=provider_key,
            provider=provider_short,
            technician_user_id=technician_user_id,
            auth_url=auth_url,
            state=state,
        )
    return RedirectResponse(url=auth_url, status_code=302)


# ── GET /tenants/me/integrations/calendars_{provider}/oauth/callback
# Public — the OAuth provider hits this. Role gating is enforced
# via the signed state token (bound to tenant + technician + provider).
@router.get(
    "/tenants/me/integrations/calendars_{provider_short}/oauth/callback",
    operation_id="tenants.integrations.calendars.oauth.callback",
)
async def calendars_oauth_callback(
    provider_short: str,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
):
    provider_key = f"calendars_{provider_short}"
    if provider_key not in _CAL_KEYS:
        raise HTTPException(status_code=404,
                             detail=f"unknown calendars provider: {provider_short}")
    if error:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="provider_error"), status_code=302)
    if not code or not state:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="missing_params"), status_code=302)
    try:
        payload = await _cal_verify_state(state, expect_provider_short=provider_short)
    except _CalOAuthStateExpired:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="state_expired"), status_code=302)
    except _CalOAuthStateReplayed:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="state_replayed"), status_code=302)
    except _CalOAuthStateTampered:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="state_invalid"), status_code=302)
    except _CalOAuthStateError:
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, "unknown", error="state_invalid"), status_code=302)
    tenant_id = payload["t"]
    technician_user_id = payload["u"]
    provider = get_calendar_provider(provider_key)
    try:
        tokens = await provider.exchange_code(code=code)
    except InvalidCalendarProviderConfig as e:
        log.warning("[calendars] exchange_code config error: %s", e)
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, technician_user_id,
            error="config_missing"), status_code=302)
    except Exception as e:  # noqa: BLE001
        log.warning("[calendars] exchange_code failed: %s", e)
        return RedirectResponse(url=_cal_settle_frontend_url(
            "error", provider_short, technician_user_id,
            error="exchange_failed"), status_code=302)
    await _cal_upsert_link(
        tenant_id=tenant_id,
        technician_user_id=technician_user_id,
        provider_key=provider_key,
        provider=provider_short,
        tokens=tokens,
        connected_email=tokens.get("connected_email"),
        calendar_id=tokens.get("calendar_id"),
    )
    # Ensure the provider metadata sidecar row exists (cap=None so
    # the account starts as UNLIMITED until admin sets a value).
    try:
        existing = await _cal_get_provider_meta(
            tenant_id=tenant_id, provider=provider_short,
        )
        if not existing:
            await _cal_upsert_provider_meta(
                tenant_id=tenant_id, provider=provider_short,
                monthly_sync_op_cap=None,
            )
    except Exception:
        pass
    return RedirectResponse(url=_cal_settle_frontend_url(
        "success", provider_short, technician_user_id), status_code=302)


# ── POST /tenants/me/integrations/calendars_{provider}/disconnect ─
# Per-technician disconnect. Body: {technician_user_id: "..."}.
@router.post(
    "/tenants/me/integrations/calendars_{provider_short}/disconnect",
    response_model=DeleteResponse,
    operation_id="tenants.integrations.calendars.disconnect",
)
async def calendars_disconnect_technician(
    provider_short: str,
    body: CalendarDisconnectBody,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    provider_key = f"calendars_{provider_short}"
    if provider_key not in _CAL_KEYS:
        raise HTTPException(status_code=404,
                             detail=f"unknown calendars provider: {provider_short}")
    # Same role rules as /oauth/start — admin can disconnect anyone;
    # a technician can disconnect themselves.
    _cal_require_start_role(user=user, technician_user_id=body.technician_user_id)
    removed = await _cal_remove_link(
        tenant_id=tenant["id"],
        technician_user_id=body.technician_user_id,
        provider_key=provider_key,
    )
    return DeleteResponse(removed=removed, provider_key=provider_key)


# ── GET /tenants/me/integrations/calendars/usage ────────────────
@router.get(
    "/tenants/me/integrations/calendars/usage",
    response_model=CalendarsUsageAndLinksResponse,
    operation_id="tenants.integrations.calendars.usage",
)
async def get_tenant_calendars_usage(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_read_role(user)
    tid = tenant["id"]
    period = _cal_period()

    providers_present = set()
    metas: Dict[str, Dict[str, Any]] = {}
    for short in _cal_short_names():
        m = await _cal_get_provider_meta(tenant_id=tid, provider=short)
        if m:
            providers_present.add(short)
            metas[short] = m
    usage_rows = await _cal_get_all_usage_rows(tenant_id=tid, period_yyyymm=period)
    usage_by_short: Dict[str, Dict[str, Any]] = {
        r["provider"]: r for r in usage_rows if r.get("provider")
    }
    providers_present.update(usage_by_short.keys())
    # Count connected technicians per provider (from technician_link).
    links = await _cal_list_links_for_tenant(tenant_id=tid)
    conn_counts: Dict[str, int] = {}
    for lk in links:
        conn_counts[lk.get("provider", "")] = conn_counts.get(lk.get("provider", ""), 0) + 1
        providers_present.add(lk.get("provider", ""))
    providers_out: List[CalendarProviderUsage] = []
    for short in sorted(x for x in providers_present if x):
        meta = metas.get(short) or {}
        usage = usage_by_short.get(short) or {}
        cap_raw = meta.get("monthly_sync_op_cap")
        cap = int(cap_raw) if cap_raw is not None else None
        used = int(usage.get("total", 0) or 0)
        pct = None
        if cap is not None and cap > 0:
            pct = round(used / cap, 4)
        providers_out.append(CalendarProviderUsage(
            provider=short,
            period_yyyymm=period,
            push_event=int(usage.get("push_event", 0) or 0),
            pull_delta=int(usage.get("pull_delta", 0) or 0),
            total=used,
            monthly_sync_op_cap=cap,
            connected_technicians=int(conn_counts.get(short, 0)),
            pct_used=pct,
            status=_cal_compute_status(used=used, cap=cap),
        ))
    # Per-technician link summaries (safe — no tokens).
    #
    # Enrich with technician display name / email when available so
    # the frontend card can show "Carlos M. <carlos@…>" instead of a
    # bare uuid.
    tech_summaries: List[TechnicianCalendarLinkSummary] = []
    if links:
        tech_ids = [lk.get("technician_user_id") for lk in links if lk.get("technician_user_id")]
        users_by_id: Dict[str, Dict[str, Any]] = {}
        if tech_ids:
            async for u in db.users.find(
                {"id": {"$in": tech_ids}, "tenant_id": tid},
                {"_id": 0, "id": 1, "name": 1, "email": 1},
            ):
                users_by_id[u.get("id", "")] = u
        for lk in links:
            u = users_by_id.get(lk.get("technician_user_id", "")) or {}
            tech_summaries.append(_cal_summary_from_row(
                lk,
                technician_name=u.get("name"),
                technician_email=u.get("email"),
            ))
    return CalendarsUsageAndLinksResponse(
        tenant_id=tid, period_yyyymm=period,
        providers=providers_out, technicians=tech_summaries,
    )


# ── Boot: ensure Calendar OAuth state indexes exist ─────────────
# The router module is imported at server-startup; the ensure_indexes
# helper is idempotent so repeated boots are cheap. Wrapped in a
# ``try`` so a Mongo hiccup can't wedge FastAPI import.
async def _cal_boot_indexes() -> None:  # pragma: no cover — boot-time only
    try:
        from services.calendars.dispatcher import ensure_indexes as _ei
        await _ei(db)
    except Exception as e:
        log.warning("[calendars] boot ensure_indexes failed: %s", e)


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
