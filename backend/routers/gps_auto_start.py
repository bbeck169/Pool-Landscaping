"""Feb-2026 · P37a — GPS auto-start job timers.

Bundles the settings + consent endpoints for the P37a backend
foundation. The auto-start endpoint itself (``POST /jobs/{jid}/arrive``)
lives in ``routers/jobs.py`` and reuses the helpers in this module for
its gates. Keeping settings + consent + helpers co-located makes the
P37b / P37c hooks (web settings page, mobile consent modal) trivial.

Endpoints:
    GET  /api/settings/gps-auto-start          — any staff read
    PATCH /api/settings/gps-auto-start         — super_admin / admin / manager
    GET  /api/tech-gps-consent/me              — current user's grant / revoke history
    POST /api/tech-gps-consent                 — grant or revoke (body {granted: bool})

Helpers (imported by ``routers/jobs.py::job_arrive``):
    * :func:`is_gps_auto_start_enabled(tenant)`  — tenant flag
    * :func:`get_arrival_radius_m(tenant)`       — with default fallback
    * :func:`has_active_consent(user_id, tenant_id)` — bool
    * :func:`rate_limit_check(user_id, job_id)`  — 60s per-(user,job) cache
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso


# Phase 6 · Feb-2026 — radius default bumped from 75m → 150m per
# the Job Timer bugs-batch brief. Operators reported out-of-radius
# false negatives on sprawling pool/landscape properties where the
# geocoded site center and the tech's parked-truck GPS fix are
# routinely 90–120m apart. Default stays tenant-overridable via
# ``arrival_radius_meters``.
DEFAULT_ARRIVAL_RADIUS_M = 150

router = APIRouter(tags=["gps-auto-start"])


# ═════════════════════════════════════════════════════════════════
# Helpers (imported by routers/jobs.py)
# ═════════════════════════════════════════════════════════════════

def is_gps_auto_start_enabled(tenant: dict) -> bool:
    return bool(tenant.get("gps_auto_start_enabled", False))


def get_arrival_radius_m(tenant: dict) -> int:
    val = tenant.get("arrival_radius_meters") or DEFAULT_ARRIVAL_RADIUS_M
    try:
        v = int(val)
        return max(10, min(v, 5000))  # bounded sanity
    except (TypeError, ValueError):
        return DEFAULT_ARRIVAL_RADIUS_M


async def has_active_consent(user_id: str, tenant_id: str) -> bool:
    """Latest consent row for the user is a non-revoked grant."""
    row = await db.tech_gps_consents.find_one(
        {"user_id": user_id, "tenant_id": tenant_id,
          "granted": True, "revoked_at": None},
        {"_id": 0, "id": 1, "granted": 1, "revoked_at": 1},
    )
    return bool(row)


# In-memory rate-limit cache — matches the Phase 20A.3 pattern used by
# ``/workforce/auto-clock-in``. Per-worker; that's OK for a 60s window.
_RATE_LIMIT_CACHE: dict[tuple[str, str], float] = {}
_RATE_LIMIT_WINDOW_S = 60


def rate_limit_check(user_id: str, job_id: str) -> bool:
    """Returns True when the call is allowed (outside the 60s window),
    False when it should be throttled. Stamps the cache on success."""
    key = (user_id, job_id)
    now_e = time.time()
    last = _RATE_LIMIT_CACHE.get(key, 0.0)
    if now_e - last < _RATE_LIMIT_WINDOW_S:
        return False
    _RATE_LIMIT_CACHE[key] = now_e
    return True


# ═════════════════════════════════════════════════════════════════
# Tenant settings — GET / PATCH /api/settings/gps-auto-start
# ═════════════════════════════════════════════════════════════════

class GpsAutoStartPatch(BaseModel):
    gps_auto_start_enabled: Optional[bool] = None
    arrival_radius_meters:  Optional[int] = None


@router.get("/settings/gps-auto-start")
async def get_gps_auto_start_settings(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Any authenticated staff can read (needed by both the mobile
    # consent screen and the web settings page).
    if user.get("role") not in ("technician", "admin", "manager", "super_admin"):
        raise HTTPException(403, "Not allowed")
    return {
        "gps_auto_start_enabled": is_gps_auto_start_enabled(tenant),
        "arrival_radius_meters": get_arrival_radius_m(tenant),
    }


@router.patch("/settings/gps-auto-start")
async def patch_gps_auto_start_settings(
    body: GpsAutoStartPatch,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"detail": "role_not_permitted",
                      "message": "Only admin / manager / super_admin can edit GPS auto-start."},
        )
    upd: dict = {}
    if body.gps_auto_start_enabled is not None:
        upd["gps_auto_start_enabled"] = bool(body.gps_auto_start_enabled)
    if body.arrival_radius_meters is not None:
        if not (10 <= int(body.arrival_radius_meters) <= 5000):
            raise HTTPException(
                status_code=400,
                detail={"detail": "invalid_radius",
                          "message": "arrival_radius_meters must be between 10 and 5000."},
            )
        upd["arrival_radius_meters"] = int(body.arrival_radius_meters)

    if not upd:
        return {"gps_auto_start_enabled": is_gps_auto_start_enabled(tenant),
                 "arrival_radius_meters": get_arrival_radius_m(tenant)}

    upd["updated_at"] = now_iso()
    upd["updated_by"] = user.get("id")
    await db.tenants.update_one({"id": tenant["id"]}, {"$set": upd})

    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_id": user.get("id"), "actor_email": user.get("email"),
            "event": "gps_auto_start_settings_update",
            "at": now_iso(), "payload": upd,
        })
    except Exception:
        pass

    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    return {
        "gps_auto_start_enabled": is_gps_auto_start_enabled(fresh or {}),
        "arrival_radius_meters": get_arrival_radius_m(fresh or {}),
    }


# ═════════════════════════════════════════════════════════════════
# Tech consent — GET /me + POST (grant | revoke)
# ═════════════════════════════════════════════════════════════════

class TechGpsConsentIn(BaseModel):
    granted: bool
    method: Optional[str] = None  # e.g. "mobile_onboarding", "manual_revoke"


@router.get("/tech-gps-consent/me")
async def get_my_gps_consent(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    rows = await db.tech_gps_consents.find(
        {"user_id": user["id"], "tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("granted_at", -1).to_list(20)
    active = await has_active_consent(user["id"], tenant["id"])
    return {"active": bool(active), "history": rows}


@router.post("/tech-gps-consent")
async def post_gps_consent(
    body: TechGpsConsentIn,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Grant OR revoke (do not delete — audit trail is immutable)."""
    now = now_iso()
    ua = request.headers.get("user-agent", "") if request else ""
    ip = (request.client.host if request and request.client else "") or ""

    if body.granted:
        # Any prior active grant is superseded by this row; we do NOT
        # revoke prior rows retroactively — they simply age out of
        # ``has_active_consent`` because the new grant is the newest.
        # But to keep the query simple and consistent, we revoke any
        # dangling prior grants FIRST so exactly one active row exists.
        await db.tech_gps_consents.update_many(
            {"user_id": user["id"], "tenant_id": tenant["id"],
              "granted": True, "revoked_at": None},
            {"$set": {"revoked_at": now,
                        "revoked_reason": "superseded_by_new_grant"}},
        )
        doc = {
            "id": new_id(), "user_id": user["id"], "tenant_id": tenant["id"],
            "granted": True, "granted_at": now, "revoked_at": None,
            "ip": ip, "user_agent": ua,
            "method": body.method or "unspecified",
        }
        await db.tech_gps_consents.insert_one(doc)
        event = "tech_gps_consent_grant"
    else:
        # Revoke the currently active grant (if any) — no-op if none.
        r = await db.tech_gps_consents.update_one(
            {"user_id": user["id"], "tenant_id": tenant["id"],
              "granted": True, "revoked_at": None},
            {"$set": {"revoked_at": now,
                        "revoked_reason": body.method or "user_revoked"}},
        )
        if r.matched_count == 0:
            # Persist an explicit "declined" row so the settings + audit
            # surfaces show the intent even without a prior grant.
            await db.tech_gps_consents.insert_one({
                "id": new_id(), "user_id": user["id"],
                "tenant_id": tenant["id"], "granted": False,
                "granted_at": None, "revoked_at": now,
                "ip": ip, "user_agent": ua,
                "method": body.method or "declined_before_grant",
            })
        event = "tech_gps_consent_revoke"

    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "actor_id": user.get("id"), "actor_email": user.get("email"),
            "event": event, "at": now,
            "payload": {"granted": body.granted,
                          "method": body.method or "unspecified"},
        })
    except Exception:
        pass

    active = await has_active_consent(user["id"], tenant["id"])
    return {"ok": True, "active": bool(active), "granted": bool(body.granted)}
