"""Phase P39 · Feb-2026 — Telematics webhook receiver + vehicle-links CRUD.

Endpoints (all `/api/`-prefixed, all tenant-scoped):

  * ``GET  /tenants/me/integrations/telematics/webhook-url``
      — returns the tenant's signed webhook URL for a given provider.
  * ``POST /tenants/me/integrations/telematics_{provider}/webhook``
      — Mojio + Geotab webhook receiver.  Verifies signed URL token,
        then provider-specific signature, then persists a
        ``gps_pings`` row.
  * ``GET  /tenants/me/integrations/telematics/vehicle-links``
      — list existing ``external_vehicle_id → technician`` links
        with per-row ``last_seen_at`` + ``unmapped_pings_count``
        (Change 2 · rich mgmt table).
  * ``POST /tenants/me/integrations/telematics/vehicle-links``
      — create a link.  Body carries ``backfill: bool`` (default
        True) — when True, historical unmapped pings for that
        vehicle are atomically re-attributed to the mapped tech.
  * ``DELETE /tenants/me/integrations/telematics/vehicle-links/{id}``
      — hard delete a link (matches ``deleted_at``-free CRUD shape
        used by ``routers.gps_ingest``).
  * ``GET  /tenants/me/integrations/telematics/unmapped-vehicles``
      — distinct ``external_vehicle_id`` values that have surfaced
        in ``gps_pings`` with ``user_id`` null within the last 30
        days, decorated with ``last_seen_at`` + ``unmapped_pings_count``.

Schema notes
------------
* ``gps_pings.user_id`` is the codebase's canonical "which user
  emitted this ping" field.  The P39 brief refers to this as
  ``technician_user_id``; we use the actual column name here for
  parity with every other gps_* reader.  ``user_id`` is ``None`` for
  telematics pings whose vehicle isn't yet mapped to a tech.
* ``gps_pings.external_vehicle_id`` is a NEW field carried only by
  telematics-sourced rows.  Non-telematics ping readers ignore it.
* ``gps_pings.source`` gets the discriminator values
  ``"telematics_mojio"``, ``"telematics_geotab_webhook"``, and
  ``"telematics_geotab_poll"`` so analytics can distinguish delivery
  path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

from services.telematics import (
    GEOTAB_PROVIDER_KEY,
    MOJIO_PROVIDER_KEY,
    UnknownTelematicsProvider,
    get_provider,
    get_provider_by_short_name,
    short_name_for,
)
from services.telematics._helpers import load_provider_config
from services.telematics.webhook_url import (
    MissingSigningSecret,
    build_webhook_url,
    resolve_base_origin,
    verify_token,
)


router = APIRouter()


# ═════════════════════════════════════════════════════════════════
# Constants + tiny helpers
# ═════════════════════════════════════════════════════════════════
_WRITE_ROLES = {"admin", "super_admin", "manager"}
_READ_ROLES = {"admin", "super_admin", "manager", "technician"}
_UNMAPPED_WINDOW_DAYS = 30
_MOJIO_TS_REPLAY_WINDOW_SEC = 300  # 5 minutes


def _require_write_role(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")


def _require_read_role(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _READ_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")


def _iso_utc_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


# ═════════════════════════════════════════════════════════════════
# Response models
# ═════════════════════════════════════════════════════════════════
class WebhookURLResponse(BaseModel):
    provider: str
    provider_key: str
    url: str
    origin_source: str  # "env" (PUBLIC_BACKEND_ORIGIN) | "request"


class VehicleLinkRow(BaseModel):
    id: str
    tenant_id: str
    external_vehicle_id: str
    technician_user_id: str
    created_at: str
    updated_at: str
    last_seen_at: Optional[str] = None
    unmapped_pings_count: int = 0


class VehicleLinksResponse(BaseModel):
    links: List[VehicleLinkRow]


class CreateVehicleLinkBody(BaseModel):
    external_vehicle_id: str = Field(..., min_length=1)
    technician_user_id: str = Field(..., min_length=1)
    # Change 2 · Feb-2026 — "backfill on map" checkbox.  Default True
    # matches the UI default (checked) so the natural mgmt-table
    # gesture atomically re-attributes historical unmapped pings.
    backfill: bool = True


class CreateVehicleLinkResponse(BaseModel):
    link: VehicleLinkRow
    backfilled: int


class UnmappedVehicleRow(BaseModel):
    external_vehicle_id: str
    last_seen_at: Optional[str] = None
    unmapped_pings_count: int = 0


class UnmappedVehiclesResponse(BaseModel):
    vehicles: List[UnmappedVehicleRow]


class WebhookAckResponse(BaseModel):
    ok: bool
    status: str  # "persisted" | "duplicate"
    ping_id: Optional[str] = None


# ═════════════════════════════════════════════════════════════════
# Signature verification helpers
# ═════════════════════════════════════════════════════════════════
def _mojio_verify_signature(
    *, raw_body: bytes,
    headers: Dict[str, str],
    webhook_secret: str,
) -> bool:
    """HMAC-SHA256(body, secret) — Mojio signs the raw body bytes.

    Accepts BOTH ``sha256=<hex>`` and bare ``<hex>`` header formats,
    and falls through a small list of common header names.
    """
    if not webhook_secret:
        return False
    header_names = (
        "x-mojio-signature",
        "x-signature",
        "x-webhook-signature",
    )
    received: Optional[str] = None
    for name in header_names:
        v = headers.get(name)
        if isinstance(v, str) and v.strip():
            received = v.strip()
            break
    if not received:
        return False
    if received.lower().startswith("sha256="):
        received = received[len("sha256="):]
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def _mojio_timestamp_replay_ok(headers: Dict[str, str]) -> bool:
    """5-minute replay window on ``X-Mojio-Timestamp``.  If the header
    is absent, accept (some providers don't send it — INFO log at the
    caller)."""
    raw = headers.get("x-mojio-timestamp") or headers.get("x-timestamp")
    if not raw:
        return True
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        # Malformed header — treat as replay-safe rather than reject;
        # provider signature already gates authenticity.
        return True
    now = int(datetime.now(timezone.utc).timestamp())
    return abs(now - ts) <= _MOJIO_TS_REPLAY_WINDOW_SEC


def _geotab_verify_shared_secret(
    *, headers: Dict[str, str],
    query_secret: Optional[str],
    webhook_secret: str,
) -> bool:
    """Shared-secret comparison for MyGeotab notification-template
    webhooks.

    P39 · Feb-2026 — Geotab lacks native signed webhooks — this
    endpoint uses shared-secret-in-header (``X-Telematics-Secret``)
    or ``?secret=<value>`` query param (MyGeotab notification templates
    support URL substitution but not custom headers reliably).  A
    future phase can add a MyGeotab polling adapter for true auth —
    that adapter DOES land in P39 alongside this receiver (see
    ``services.telematics_geotab_poller``).
    """
    if not webhook_secret:
        return False
    presented = (
        headers.get("x-telematics-secret")
        or headers.get("x-webhook-secret")
        or query_secret
        or ""
    ).strip()
    if not presented:
        return False
    return hmac.compare_digest(webhook_secret, presented)


# ═════════════════════════════════════════════════════════════════
# Payload normalisation
# ═════════════════════════════════════════════════════════════════
def _kmh_to_mps(kmh: Any) -> Optional[float]:
    try:
        return float(kmh) / 3.6
    except (TypeError, ValueError):
        return None


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _normalise_mojio_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Return a canonical dict with ``external_vehicle_id``, ``lat``,
    ``lon``, ``heading``, ``speed_mps``, ``captured_at``, ``event_id``.

    Mojio's real payload shape varies by webhook event type; this
    normaliser handles both a "Location" event and a raw ``position``
    envelope.  Unknown shapes return an empty dict.
    """
    if not isinstance(body, dict):
        return {}
    device = body.get("device")
    device_id_fallback = (
        device.get("id") if isinstance(device, dict) else None
    )
    vid = (
        body.get("VehicleId")
        or body.get("vehicle_id")
        or body.get("device_id")
        or device_id_fallback
    )
    lat = _f(body.get("Latitude") or body.get("lat") or body.get("latitude"))
    lon = _f(body.get("Longitude") or body.get("lon") or body.get("lng") or body.get("longitude"))
    heading = _f(body.get("Heading") or body.get("heading") or body.get("bearing"))
    speed_raw = body.get("SpeedKmh") or body.get("speed_kmh") or body.get("speed")
    speed_mps = _kmh_to_mps(speed_raw) if speed_raw is not None else None
    ts = (
        body.get("Timestamp")
        or body.get("timestamp")
        or body.get("captured_at")
        or body.get("dateTime")
    )
    event_id = body.get("EventId") or body.get("event_id") or body.get("id")
    if not vid or lat is None or lon is None or not ts:
        return {}
    return {
        "external_vehicle_id": str(vid),
        "lat": lat,
        "lon": lon,
        "heading": heading,
        "speed_mps": speed_mps,
        "captured_at": str(ts),
        "event_id": str(event_id) if event_id else None,
    }


def _normalise_geotab_webhook_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """Geotab notification-template payloads carry a flat shape the
    admin defines in MyGeotab.  We use the P39 recommended template
    fields: ``deviceId``, ``latitude``, ``longitude``, ``dateTime``,
    ``speed``, ``bearing``, ``notificationId``.
    """
    if not isinstance(body, dict):
        return {}
    vid = body.get("deviceId") or body.get("DeviceId") or body.get("device_id")
    lat = _f(body.get("latitude") or body.get("Latitude"))
    lon = _f(body.get("longitude") or body.get("Longitude"))
    heading = _f(body.get("bearing") or body.get("Bearing") or body.get("heading"))
    speed_kmh = body.get("speed") or body.get("Speed")
    speed_mps = _kmh_to_mps(speed_kmh) if speed_kmh is not None else None
    ts = body.get("dateTime") or body.get("DateTime") or body.get("captured_at")
    event_id = body.get("notificationId") or body.get("NotificationId") or body.get("event_id")
    if not vid or lat is None or lon is None or not ts:
        return {}
    return {
        "external_vehicle_id": str(vid),
        "lat": lat,
        "lon": lon,
        "heading": heading,
        "speed_mps": speed_mps,
        "captured_at": str(ts),
        "event_id": str(event_id) if event_id else None,
    }


# ═════════════════════════════════════════════════════════════════
# Vehicle → technician resolution
# ═════════════════════════════════════════════════════════════════
async def resolve_vehicle_technician(
    *, tenant_id: str, external_vehicle_id: str,
) -> Optional[str]:
    """Return the mapped ``technician_user_id`` or ``None`` when the
    vehicle isn't mapped.  Tenant-scoped."""
    row = await db.telematics_vehicle_links.find_one(
        {"tenant_id": tenant_id, "external_vehicle_id": external_vehicle_id},
        {"_id": 0, "technician_user_id": 1},
    )
    return row.get("technician_user_id") if row else None


# ═════════════════════════════════════════════════════════════════
# Ping persistence (shared by webhook receiver + poller)
# ═════════════════════════════════════════════════════════════════
async def persist_telematics_ping(
    *, tenant_id: str,
    provider_short: str,
    source: str,
    normalised: Dict[str, Any],
) -> Dict[str, Any]:
    """Insert (or dedup) a normalised telematics ping into ``gps_pings``.

    Returns ``{"status": "persisted"|"duplicate", "ping_id": <id>|None,
    "vehicle_mapped": bool}``.  Dedup on ``(tenant_id,
    external_vehicle_id, captured_at)`` — unique compound index
    ``gps_pings_dedup_bg`` enforces it at the storage layer.
    """
    from pymongo.errors import DuplicateKeyError

    vid = normalised["external_vehicle_id"]
    user_id = await resolve_vehicle_technician(
        tenant_id=tenant_id, external_vehicle_id=vid,
    )
    if user_id is None:
        logger.info(
            "[p39-telematics] unmapped_vehicle=%s tenant=%s provider=%s "
            "source=%s — persisting ping with user_id=null",
            vid, tenant_id, provider_short, source,
        )

    pid = new_id()
    doc: Dict[str, Any] = {
        "id": pid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "clock_in_id": None,
        "lat": normalised["lat"],
        "lon": normalised["lon"],
        "accuracy_m": None,
        "heading": normalised.get("heading"),
        "speed_mps": normalised.get("speed_mps"),
        "source": source,
        "captured_at": normalised["captured_at"],
        "received_at": now_iso(),
        "device_id": vid,
        "app_version": None,
        # P39-specific columns:
        "external_vehicle_id": vid,
        "telematics_provider": provider_short,
        "telematics_event_id": normalised.get("event_id"),
    }
    try:
        await db.gps_pings.insert_one(doc)
        return {
            "status": "persisted",
            "ping_id": pid,
            "vehicle_mapped": user_id is not None,
        }
    except DuplicateKeyError:
        # ``gps_pings_dedup_bg`` unique index tripped — a poll or
        # webhook re-delivery arrived for the same
        # ``(tenant_id, external_vehicle_id, captured_at)``.  Idempotent
        # 200 with a distinct status.
        return {
            "status": "duplicate",
            "ping_id": None,
            "vehicle_mapped": user_id is not None,
        }


# ═════════════════════════════════════════════════════════════════
# GET /webhook-url
# ═════════════════════════════════════════════════════════════════
@router.get(
    "/tenants/me/integrations/telematics/webhook-url",
    response_model=WebhookURLResponse,
    operation_id="tenants.integrations.telematics.webhook_url",
)
async def get_webhook_url(
    request: Request,
    provider: str = Query(..., description="mojio | geotab"),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    try:
        meta = get_provider_by_short_name(provider)
    except UnknownTelematicsProvider:
        raise HTTPException(400, detail=f"unknown telematics provider: {provider}")

    scheme = (
        request.headers.get("x-forwarded-proto")
        or request.url.scheme
        or "https"
    )
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
        or ""
    )
    origin, from_env = resolve_base_origin(scheme, host)
    if not origin or "localhost" in origin.lower() and not from_env:
        # Deny minting a webhook URL from a request that would produce
        # a localhost origin — the URL is meant to be copy-pasted into
        # a provider's dashboard.
        logger.error(
            "[p39-telematics] refusing to mint webhook URL — no "
            "PUBLIC_BACKEND_ORIGIN env set AND request host resolves "
            "to localhost (host=%s)", host,
        )
        raise HTTPException(
            500,
            detail="PUBLIC_BACKEND_ORIGIN is not set and the request "
                   "does not carry a public host header — cannot mint "
                   "webhook URL.",
        )
    try:
        url = build_webhook_url(
            base_origin=origin,
            tenant_id=tenant["id"],
            provider_short=meta.short_name,
        )
    except MissingSigningSecret as e:
        logger.error("[p39-telematics] %s", str(e))
        raise HTTPException(500, detail=str(e))
    return WebhookURLResponse(
        provider=meta.short_name,
        provider_key=meta.provider_key,
        url=url,
        origin_source="env" if from_env else "request",
    )


# ═════════════════════════════════════════════════════════════════
# POST /telematics_{provider}/webhook
# ═════════════════════════════════════════════════════════════════
@router.post(
    "/tenants/me/integrations/telematics_{provider_short}/webhook",
    response_model=WebhookAckResponse,
    operation_id="tenants.integrations.telematics.webhook",
)
async def telematics_webhook(
    provider_short: str,
    request: Request,
    tid: str = Query(..., description="tenant id"),
    t: str = Query(..., description="signed URL token"),
    secret: Optional[str] = Query(
        None,
        description=(
            "Geotab-only fallback for the shared secret.  MyGeotab "
            "notification templates support URL substitution but "
            "not custom headers reliably."
        ),
    ),
):
    # ── Step 1 · tenant + URL-token resolution ────────────────
    try:
        provider_meta = get_provider_by_short_name(provider_short)
    except UnknownTelematicsProvider:
        raise HTTPException(404, detail=f"unknown telematics provider: {provider_short}")

    try:
        token_ok = verify_token(
            tenant_id=tid, provider_short=provider_short, token=t,
        )
    except MissingSigningSecret as e:
        logger.error("[p39-telematics] %s", str(e))
        raise HTTPException(500, detail=str(e))
    if not token_ok:
        logger.warning(
            "[p39-telematics] webhook 401 — invalid url token "
            "tid=%s provider=%s",
            tid, provider_short,
        )
        raise HTTPException(401, detail="invalid tenant token")

    # Look up the tenant + its provider config (we NEED the webhook
    # secret to verify the provider signature).
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0, "id": 1})
    if not tenant:
        raise HTTPException(404, detail="tenant not found")
    config = await load_provider_config(
        tenant_id=tid, provider_key=provider_meta.provider_key,
    )
    if not config or not config.get("webhook_secret"):
        raise HTTPException(400, detail="telematics provider not configured")
    webhook_secret = str(config.get("webhook_secret") or "")

    raw_body = await request.body()
    lower_headers: Dict[str, str] = {
        k.lower(): v for k, v in request.headers.items()
    }

    # ── Step 2 · provider signature verification ───────────────
    if provider_meta.provider_key == MOJIO_PROVIDER_KEY:
        if not _mojio_verify_signature(
            raw_body=raw_body,
            headers=lower_headers,
            webhook_secret=webhook_secret,
        ):
            logger.warning(
                "[p39-telematics] mojio webhook 401 — invalid signature "
                "tid=%s bytes=%s", tid, len(raw_body),
            )
            raise HTTPException(401, detail="invalid signature")
        if not _mojio_timestamp_replay_ok(lower_headers):
            logger.warning(
                "[p39-telematics] mojio webhook 401 — timestamp replay "
                "window exceeded tid=%s", tid,
            )
            raise HTTPException(401, detail="stale timestamp")
    elif provider_meta.provider_key == GEOTAB_PROVIDER_KEY:
        if not _geotab_verify_shared_secret(
            headers=lower_headers,
            query_secret=secret,
            webhook_secret=webhook_secret,
        ):
            logger.warning(
                "[p39-telematics] geotab webhook 401 — invalid shared "
                "secret tid=%s", tid,
            )
            raise HTTPException(401, detail="invalid shared secret")
    else:
        raise HTTPException(500, detail="unrecognised telematics provider")

    # ── Step 3 · parse + normalise body ─────────────────────────
    try:
        body_json = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(400, detail="invalid JSON body")

    if provider_meta.provider_key == MOJIO_PROVIDER_KEY:
        normalised = _normalise_mojio_payload(body_json)
        source = "telematics_mojio"
    else:
        normalised = _normalise_geotab_webhook_payload(body_json)
        source = "telematics_geotab_webhook"

    if not normalised:
        raise HTTPException(
            400,
            detail="payload missing required fields (device id / lat / lon / ts)",
        )

    # ── Step 4 · persist ────────────────────────────────────────
    res = await persist_telematics_ping(
        tenant_id=tid,
        provider_short=provider_meta.short_name,
        source=source,
        normalised=normalised,
    )
    return WebhookAckResponse(
        ok=True, status=res["status"], ping_id=res["ping_id"],
    )


# ═════════════════════════════════════════════════════════════════
# Vehicle-links stats helpers (Change 2 · Feb-2026)
# ═════════════════════════════════════════════════════════════════
async def _decorate_vehicle_stats(
    *, tenant_id: str,
    external_vehicle_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Return ``{vid: {"last_seen_at": iso|None, "unmapped_pings_count": N}}``.

    One aggregation across the ``gps_pings`` collection so N links
    become 1 DB roundtrip.
    """
    if not external_vehicle_ids:
        return {}
    pipeline = [
        {"$match": {
            "tenant_id": tenant_id,
            "external_vehicle_id": {"$in": external_vehicle_ids},
        }},
        {"$group": {
            "_id": "$external_vehicle_id",
            "last_seen_at": {"$max": "$captured_at"},
            "unmapped_pings_count": {
                "$sum": {
                    "$cond": [
                        {"$eq": ["$user_id", None]},
                        1,
                        0,
                    ]
                }
            },
        }},
    ]
    out: Dict[str, Dict[str, Any]] = {}
    async for row in db.gps_pings.aggregate(pipeline):
        out[row["_id"]] = {
            "last_seen_at": row.get("last_seen_at"),
            "unmapped_pings_count": int(row.get("unmapped_pings_count") or 0),
        }
    return out


# ═════════════════════════════════════════════════════════════════
# GET /vehicle-links
# ═════════════════════════════════════════════════════════════════
@router.get(
    "/tenants/me/integrations/telematics/vehicle-links",
    response_model=VehicleLinksResponse,
    operation_id="tenants.integrations.telematics.vehicle_links.list",
)
async def list_vehicle_links(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_read_role(user)
    tid = tenant["id"]
    rows: List[Dict[str, Any]] = []
    async for row in db.telematics_vehicle_links.find(
        {"tenant_id": tid}, {"_id": 0},
    ).sort("external_vehicle_id", 1):
        rows.append(row)
    vids = [r["external_vehicle_id"] for r in rows]
    stats = await _decorate_vehicle_stats(
        tenant_id=tid, external_vehicle_ids=vids,
    )
    out: List[VehicleLinkRow] = []
    for row in rows:
        s = stats.get(row["external_vehicle_id"]) or {}
        out.append(VehicleLinkRow(
            id=row["id"],
            tenant_id=row["tenant_id"],
            external_vehicle_id=row["external_vehicle_id"],
            technician_user_id=row["technician_user_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seen_at=s.get("last_seen_at"),
            unmapped_pings_count=int(s.get("unmapped_pings_count") or 0),
        ))
    return VehicleLinksResponse(links=out)


# ═════════════════════════════════════════════════════════════════
# POST /vehicle-links — create link (+ optional backfill)
# ═════════════════════════════════════════════════════════════════
@router.post(
    "/tenants/me/integrations/telematics/vehicle-links",
    response_model=CreateVehicleLinkResponse,
    operation_id="tenants.integrations.telematics.vehicle_links.create",
)
async def create_vehicle_link(
    body: CreateVehicleLinkBody,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    tid = tenant["id"]

    # Validate technician belongs to this tenant.
    tech = await db.users.find_one(
        {"id": body.technician_user_id, "tenant_id": tid},
        {"_id": 0, "id": 1, "role": 1},
    )
    if not tech:
        raise HTTPException(400, detail="technician not found for this tenant")

    from pymongo.errors import DuplicateKeyError
    lid = new_id()
    ts = now_iso()
    doc = {
        "id": lid,
        "tenant_id": tid,
        "external_vehicle_id": body.external_vehicle_id,
        "technician_user_id": body.technician_user_id,
        "created_at": ts,
        "updated_at": ts,
    }
    try:
        await db.telematics_vehicle_links.insert_one(doc)
    except DuplicateKeyError:
        # ``telematics_vehicle_links_dedup_bg`` unique compound index.
        raise HTTPException(
            409,
            detail=(
                f"vehicle_id={body.external_vehicle_id} already linked "
                f"for this tenant"
            ),
        )

    backfilled = 0
    if body.backfill:
        res = await db.gps_pings.update_many(
            {
                "tenant_id": tid,
                "external_vehicle_id": body.external_vehicle_id,
                "user_id": None,
            },
            {"$set": {"user_id": body.technician_user_id}},
        )
        backfilled = int(getattr(res, "modified_count", 0) or 0)
        logger.info(
            "[p39-telematics] vehicle_link_create backfilled=%s "
            "tenant=%s vid=%s → tech=%s",
            backfilled, tid, body.external_vehicle_id,
            body.technician_user_id,
        )

    return CreateVehicleLinkResponse(
        link=VehicleLinkRow(
            id=lid,
            tenant_id=tid,
            external_vehicle_id=body.external_vehicle_id,
            technician_user_id=body.technician_user_id,
            created_at=ts,
            updated_at=ts,
            last_seen_at=None,
            unmapped_pings_count=0,
        ),
        backfilled=backfilled,
    )


# ═════════════════════════════════════════════════════════════════
# DELETE /vehicle-links/{id}
# ═════════════════════════════════════════════════════════════════
@router.delete(
    "/tenants/me/integrations/telematics/vehicle-links/{link_id}",
    operation_id="tenants.integrations.telematics.vehicle_links.delete",
)
async def delete_vehicle_link(
    link_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_write_role(user)
    res = await db.telematics_vehicle_links.delete_one(
        {"id": link_id, "tenant_id": tenant["id"]},
    )
    if getattr(res, "deleted_count", 0) == 0:
        raise HTTPException(404, detail="link not found")
    return {"removed": True, "id": link_id}


# ═════════════════════════════════════════════════════════════════
# GET /unmapped-vehicles
# ═════════════════════════════════════════════════════════════════
@router.get(
    "/tenants/me/integrations/telematics/unmapped-vehicles",
    response_model=UnmappedVehiclesResponse,
    operation_id="tenants.integrations.telematics.unmapped_vehicles",
)
async def list_unmapped_vehicles(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_read_role(user)
    tid = tenant["id"]
    cutoff = _iso_utc_days_ago(_UNMAPPED_WINDOW_DAYS)
    pipeline = [
        {"$match": {
            "tenant_id": tid,
            "user_id": None,
            "external_vehicle_id": {"$ne": None, "$exists": True},
            "received_at": {"$gte": cutoff},
        }},
        {"$group": {
            "_id": "$external_vehicle_id",
            "last_seen_at": {"$max": "$captured_at"},
            "unmapped_pings_count": {"$sum": 1},
        }},
        {"$sort": {"last_seen_at": -1}},
    ]
    out: List[UnmappedVehicleRow] = []
    async for row in db.gps_pings.aggregate(pipeline):
        out.append(UnmappedVehicleRow(
            external_vehicle_id=row["_id"],
            last_seen_at=row.get("last_seen_at"),
            unmapped_pings_count=int(row.get("unmapped_pings_count") or 0),
        ))
    return UnmappedVehiclesResponse(vehicles=out)
