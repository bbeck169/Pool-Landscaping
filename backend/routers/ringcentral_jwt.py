"""Phase 6 · RingCentral JWT-bearer router — voice + subscriptions.

Complements the pre-existing OAuth-based ``routers/ringcentral.py`` from
Phase 52/54. New endpoints exposed under ``/api/rc/*`` to avoid path
collisions; the shared webhook still lives at
``/api/ringcentral/webhook`` (handled by the older router).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from services.ringcentral.rc_client import RingCentralError, RingCentralService
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_TELEPHONY_FILTER = "/restapi/v1.0/account/~/telephony/sessions"
_VOICEMAIL_FILTER = "/restapi/v1.0/account/~/extension/~/message-store"


def _require_admin(u: dict) -> None:
    if (u or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")


def _call_allowed(u: dict) -> None:
    if (u or {}).get("role") not in ("admin", "super_admin", "manager", "technician"):
        raise HTTPException(403, "Not allowed")


class CallBody(BaseModel):
    to_number: str
    from_number: Optional[str] = None


class LogOutboundBody(BaseModel):
    to_number: str
    from_number: str
    entity_kind: str = Field(...)
    entity_id: str
    note: Optional[str] = None


@router.post("/dev/ringcentral-ping")
async def rc_ping(user: dict = Depends(get_current_user)):
    _require_admin(user)
    svc = RingCentralService()
    try:
        ext = await svc.get_my_extension()
    except RingCentralError as e:
        logger.warning(f"[phase6] rc-ping failed status={e.status}")
        return {"ok": False, "error_status": e.status,
                 "error_body": str(e.body)[:400], "mode": svc.mode}
    return {"ok": True,
             "extension_id": ext.get("id"),
             "extension_number": ext.get("extensionNumber"),
             "account_id": (ext.get("account") or {}).get("id"),
             "status": ext.get("status"),
             "mode": svc.mode}


@router.post("/rc/call")
async def rc_call(body: CallBody,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _call_allowed(user)
    from_number = body.from_number or (user.get("phone") or "").strip()
    if not from_number:
        from_number = (tenant.get("support_phone_number") or "").strip()
    if not from_number:
        raise HTTPException(400, "No from_number resolvable")
    svc = RingCentralService(tenant["id"])
    try:
        res = await svc.ring_out(from_number, body.to_number)
    except RingCentralError as e:
        raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                             detail=f"RingCentral: {e.body}")
    return {"status": "queued", "ringout_id": res.get("id"),
             "from_number": from_number, "to_number": body.to_number}


@router.post("/rc/setup-webhooks")
async def rc_setup_webhooks(user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    url = os.getenv("RC_WEBHOOK_URL") or ""
    vtok = os.getenv("RC_VERIFICATION_TOKEN") or ""
    if not url or not vtok:
        raise HTTPException(500, "RC_WEBHOOK_URL or RC_VERIFICATION_TOKEN missing")
    existing = await db.ringcentral_subscriptions.find_one(
        {"tenant_id": tenant["id"], "address": url},
        {"_id": 0, "subscription_id": 1},
    )
    if existing:
        return {"ok": True, "created": False,
                 "subscription_id": existing["subscription_id"],
                 "reason": "already_exists"}
    svc = RingCentralService(tenant["id"])
    try:
        sub = await svc.create_subscription(url, vtok,
                                              [_TELEPHONY_FILTER, _VOICEMAIL_FILTER])
    except RingCentralError as e:
        raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                             detail=f"RingCentral: {e.body}")
    sub_id = sub.get("id")
    await db.ringcentral_subscriptions.insert_one({
        "id": new_id(), "tenant_id": tenant["id"],
        "subscription_id": sub_id, "address": url,
        "event_filters": [_TELEPHONY_FILTER, _VOICEMAIL_FILTER],
        "created_at": now_iso(),
    })
    return {"ok": True, "created": True, "subscription_id": sub_id}


@router.get("/rc/subscriptions")
async def rc_list_subs(user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    rows = await db.ringcentral_subscriptions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).to_list(50)
    return {"subscriptions": rows}


@router.delete("/rc/subscriptions/{sid}")
async def rc_delete_sub(sid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    svc = RingCentralService(tenant["id"])
    try:
        await svc.delete_subscription(sid)
    except RingCentralError as e:
        if e.status != 404:
            raise HTTPException(status_code=502 if e.status >= 500 else e.status,
                                 detail=f"RingCentral: {e.body}")
    await db.ringcentral_subscriptions.delete_one(
        {"tenant_id": tenant["id"], "subscription_id": sid},
    )
    return {"ok": True}


@router.post("/rc/log-outbound")
async def rc_log_outbound(body: LogOutboundBody,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "session_id": None,
        "direction": "Outbound",
        "status": "Intent",
        "from_number": body.from_number,
        "to_number": body.to_number,
        "attribution": {"entity_kind": body.entity_kind,
                          "entity_id": body.entity_id,
                          "note": body.note},
        "initiated_by_user_id": user.get("id"),
        "started_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.call_logs.insert_one(doc)
    return {"ok": True, "call_log_id": doc["id"]}


@router.get("/rc/timeline")
async def rc_timeline(entity_kind: str, entity_id: str, limit: int = 50,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    rows = await db.call_logs.find(
        {"tenant_id": tenant["id"],
         "attribution.entity_kind": entity_kind,
         "attribution.entity_id": entity_id},
        {"_id": 0, "raw_event": 0},
    ).sort("started_at", -1).limit(int(limit)).to_list(int(limit))
    return {"calls": rows}


@router.get("/rc/logs")
async def rc_logs(limit: int = 25,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    rows = await db.call_logs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "raw_event": 0},
    ).sort("started_at", -1).limit(int(limit)).to_list(int(limit))
    return {"calls": rows}
