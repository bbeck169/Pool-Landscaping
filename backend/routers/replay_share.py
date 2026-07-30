"""Phase 2 · Feb-2026 — 24 h Route Replay share links (ADMIN-ONLY rework).

Endpoints (all authed, all tenant-scoped, ADMIN or SUPER_ADMIN only)
-------------------------------------------------------------------
    POST   /gps/replay/share
    GET    /gps/replay/shares?user_id=&date=
    GET    /gps/replay/share/{share_id}
    POST   /gps/replay/share/{share_id}/revoke

Policy note (Feb-2026 rework)
-----------------------------
The original spec exposed the replay to unauthenticated customers via
``GET /api/public/replay/{share_id}``. The human owner reversed that
policy: "no one should see any GPS information except Admin and Super
Admin". The public route is gone, the rate limiter is gone (authed
callers don't need it), and role gating is tightened so Manager /
Dispatcher / Technician / Customer all get 403 even though many of
them still have access to the LIVE replay through the existing GPS
admin pages. This restriction only applies to share URLs.

Storage
-------
Collection ``route_replay_shares`` (unchanged from the pre-rework
schema — TTL logic and view_count/last_viewed_at still meaningful for
audit of admin-to-admin sharing):
    {tenant_id, share_id, user_id, replay_date, created_by,
     created_at, expires_at, revoked_at?,
     view_count, last_viewed_at?, viewer_ip_hash_last?}
"""
from __future__ import annotations

import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user

router = APIRouter()

# ── Config
_MAX_TTL_HOURS = 24
_DEFAULT_TTL_HOURS = 24
_SHARE_ID_LEN = 16  # base62 chars → ~93 bits of entropy
_ALPHABET = string.ascii_letters + string.digits

# Tightened from the pre-rework role set. Manager / Dispatcher /
# Technician / Customer are explicitly denied even though many of them
# retain access to the LIVE replay via existing admin pages.
_ALLOWED_ROLES = {"admin", "super_admin", "owner"}

_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    coll = db["route_replay_shares"]
    await coll.create_index("share_id", unique=True)
    await coll.create_index([("tenant_id", 1), ("expires_at", -1)])
    await coll.create_index([("tenant_id", 1), ("user_id", 1), ("replay_date", 1)])
    _indexes_ready = True


# ── Helpers ─────────────────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip() or "?"
    return (request.client.host if request.client else "?")


def _ip_hash(raw_ip: str, salt: str) -> str:
    return hashlib.sha256(f"{raw_ip}|{salt}".encode("utf-8")).hexdigest()


def _mk_share_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_SHARE_ID_LEN))


def _require_admin(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, detail="admin_or_super_admin_only")


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, detail="tenant scope required")
    return tid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(v: Any) -> Optional[datetime]:
    """Motor returns BSON datetimes as *naive* — normalise to tz-aware."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:                                                       # noqa: BLE001
        return None


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _public_base_url(request: Request) -> str:
    override = os.environ.get("PUBLIC_APP_BASE_URL", "").rstrip("/")
    if override:
        return override
    origin = request.headers.get("origin") or ""
    if origin:
        return origin.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


# ═══════════════════════ 1) Create share ════════════════════════════
class ShareCreateBody(BaseModel):
    user_id: str = Field(..., min_length=1)
    replay_date: str = Field(..., min_length=10, max_length=10,
                              pattern=r"^\d{4}-\d{2}-\d{2}$")
    ttl_hours: Optional[int] = Field(None, ge=1, le=_MAX_TTL_HOURS)


@router.post("/gps/replay/share", operation_id="replayShare.create",
              tags=["replay-share"])
async def create_share(body: ShareCreateBody, request: Request,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()

    tech = await db.users.find_one(
        {"id": body.user_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1})
    if not tech:
        raise HTTPException(404, detail="technician_not_found")

    now = _now()
    ttl = body.ttl_hours or _DEFAULT_TTL_HOURS
    expires_at = now + timedelta(hours=min(ttl, _MAX_TTL_HOURS))

    share_id = _mk_share_id()
    await db.route_replay_shares.insert_one({
        "tenant_id": tenant_id,
        "share_id": share_id,
        "user_id": body.user_id,
        "replay_date": body.replay_date,
        "created_by": caller.get("id") or "",
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "view_count": 0,
        "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    })

    base = _public_base_url(request)
    return {
        "share_id": share_id,
        "share_url": f"{base}/replay/{share_id}",
        "revoke_url": f"{base}/api/gps/replay/share/{share_id}/revoke",
        "expires_at": expires_at.isoformat(),
        "user_id": body.user_id,
        "replay_date": body.replay_date,
    }


# ═══════════════════════ 2) List shares ═════════════════════════════
@router.get("/gps/replay/shares", operation_id="replayShare.list",
             tags=["replay-share"])
async def list_shares(user_id: str = Query(...),
                       date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
                       caller: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()
    items: List[Dict[str, Any]] = []
    async for r in db.route_replay_shares.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "replay_date": date},
            {"_id": 0}).sort("created_at", -1).limit(20):
        now = _now()
        status = "active"
        if r.get("revoked_at"):
            status = "revoked"
        else:
            exp = _as_utc(r.get("expires_at"))
            if exp and exp <= now:
                status = "expired"
        r["status"] = status
        r.pop("viewer_ip_hash_last", None)
        items.append(r)
    return {"items": items, "total": len(items)}


# ═══════════════════════ 3) Revoke ══════════════════════════════════
@router.post("/gps/replay/share/{share_id}/revoke",
              operation_id="replayShare.revoke",
              tags=["replay-share"])
async def revoke_share(share_id: str = Path(..., min_length=8, max_length=32),
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()
    r = await db.route_replay_shares.find_one_and_update(
        {"share_id": share_id, "tenant_id": tenant_id,
          "revoked_at": None},
        {"$set": {"revoked_at": _now()}},
        return_document=True,
    )
    if not r:
        raise HTTPException(404, detail="share_not_found_or_already_revoked")
    return {"ok": True, "share_id": share_id,
            "revoked_at": r["revoked_at"].isoformat()}


# ═══════════════════════ 4) Authed GET ══════════════════════════════
# Feb-2026 rework: replaces the deleted unauthenticated
# ``GET /public/replay/{share_id}`` endpoint. Admin-or-Super-Admin
# only. Same payload shape and PII masking as before. Tenant scope is
# enforced — you can only fetch a share that lives in your own tenant.
_PING_LIMIT = 5000
_PII_ON_STOP = {
    "phone", "phone_number", "email", "home_address",
    "attributed_customer_email", "attributed_customer_phone",
    "reviewer_notes", "notes",
}


async def _build_share_payload(share: Dict[str, Any]) -> Dict[str, Any]:
    tenant_id = share["tenant_id"]
    user_id = share["user_id"]
    date = share["replay_date"]
    day_start = f"{date}T00:00:00+00:00"
    day_end = f"{date}T23:59:59+00:00"

    tech_name = ""
    tech = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "display_name": 1})
    if tech:
        tech_name = tech.get("display_name") or tech.get("name") or "Technician"

    tenant_name = ""
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "name": 1})
    if tenant:
        tenant_name = tenant.get("name") or ""

    stops: List[Dict[str, Any]] = []
    async for s in db.driver_stops.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "started_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0}).sort("started_at", 1):
        for k in list(s.keys()):
            if k in _PII_ON_STOP:
                s.pop(k, None)
        stops.append(s)

    pings: List[Dict[str, Any]] = []
    total_pings = await db.gps_pings.count_documents(
        {"tenant_id": tenant_id, "user_id": user_id,
          "captured_at": {"$gte": day_start, "$lte": day_end}})
    step = 1
    if total_pings > _PING_LIMIT:
        step = (total_pings // _PING_LIMIT) + 1
    i = 0
    async for p in db.gps_pings.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "captured_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0, "lat": 1, "lon": 1, "captured_at": 1}
            ).sort("captured_at", 1):
        if i % step == 0:
            pings.append({"lat": float(p["lat"]), "lon": float(p["lon"]),
                           "captured_at": p.get("captured_at")})
        i += 1
        if len(pings) >= _PING_LIMIT:
            break

    fences: List[Dict[str, Any]] = []
    async for g in db.geofence_events.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "ts": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0}).sort("ts", 1):
        fences.append({
            "geofence_id": g.get("geofence_id"),
            "geofence_name": g.get("geofence_name") or "",
            "event": g.get("event"),
            "ts": _iso(g.get("ts")),
        })

    first_ping_at = pings[0]["captured_at"] if pings else None
    last_ping_at = pings[-1]["captured_at"] if pings else None
    playback_duration_s = 0
    if first_ping_at and last_ping_at:
        try:
            a = datetime.fromisoformat(str(first_ping_at).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(last_ping_at).replace("Z", "+00:00"))
            playback_duration_s = max(0, int((b - a).total_seconds()))
        except Exception:                                                  # noqa: BLE001
            playback_duration_s = 0

    return {
        "share_id": share["share_id"],
        "user_id": user_id,
        "user_name": tech_name,
        "tenant_name": tenant_name,
        "replay_date": date,
        "from": day_start,
        "to": day_end,
        "stops": stops,
        "pings": pings,
        "pings_total": total_pings,
        "pings_downsample_step": step,
        "geofence_events": fences,
        "first_ping_at": first_ping_at,
        "last_ping_at": last_ping_at,
        "playback_duration_s": playback_duration_s,
        "expires_at": _iso(share.get("expires_at")),
        "read_only": True,
    }


@router.get("/gps/replay/share/{share_id}",
             operation_id="replayShare.get",
             tags=["replay-share"])
async def get_share(share_id: str = Path(..., min_length=8, max_length=32),
                     request: Request = None,
                     caller: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()

    share = await db.route_replay_shares.find_one(
        {"share_id": share_id, "tenant_id": tenant_id}, {"_id": 0})
    if not share:
        # 404 (not 403) so we don't leak share-existence across tenants.
        raise HTTPException(404, detail="share_not_found")

    now = _now()
    if share.get("revoked_at"):
        raise HTTPException(410, detail="share_revoked")
    exp = _as_utc(share.get("expires_at"))
    if exp and exp <= now:
        raise HTTPException(410, detail="share_expired")

    payload = await _build_share_payload(share)

    # Increment view counters (audit trail of admin-to-admin sharing).
    ip = _client_ip(request) if request is not None else "?"
    ip_h = _ip_hash(ip, share_id)
    await db.route_replay_shares.update_one(
        {"share_id": share_id},
        {"$inc": {"view_count": 1},
         "$set": {"last_viewed_at": now, "viewer_ip_hash_last": ip_h}},
    )
    payload["view_count"] = int(share.get("view_count", 0)) + 1
    return payload
