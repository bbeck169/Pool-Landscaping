"""Phase 55 · Unified notifications router.

Endpoints
=========
* ``GET  /api/notifications``               — paginated list for current user
* ``GET  /api/notifications/unread-count``  — bell badge counter
* ``POST /api/notifications/{id}/read``     — flip a single row
* ``POST /api/notifications/mark-all-read`` — bulk mark
* ``DELETE /api/notifications/{id}``        — drop a row from history
* ``GET  /api/settings/notifications``      — my preferences
* ``PUT  /api/settings/notifications``      — upsert my preferences
* ``GET  /api/notifications/kinds``         — kind catalog for the prefs UI

Multi-tenant scoping: every filter carries ``tenant_id`` and, for non-admin
roles, ``user_id`` (customer role also matches ``customer_id`` so portal
users see their own inbox).

Preferences are stored in ``db.notification_preferences`` — see
``services/notifications.py`` for the merge / default semantics.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from services.notifications import (
    KIND_LABELS,
    default_prefs,
    get_user_prefs,
    set_user_prefs,
)
from utils import get_current_user, now_iso

router = APIRouter()


def _mine_filter(user: dict, tenant_id: str) -> dict:
    """Filter that returns 'notifications visible to me' — user_id match OR,
    for portal customers, customer_id match. Also honors the legacy
    ``user_id == "*"`` broadcast row from older emitters."""
    q: dict = {"tenant_id": tenant_id}
    if user.get("role") == "customer" and user.get("customer_id"):
        q["$or"] = [
            {"user_id": user["id"]},
            {"user_id": "*"},
            {"customer_id": user["customer_id"]},
        ]
    else:
        q["$or"] = [{"user_id": user["id"]}, {"user_id": "*"}]
    return q


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    kind: Optional[str] = None,
    unread_only: bool = False,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q = _mine_filter(user, tenant["id"])
    if kind:
        q["kind"] = kind
    if unread_only:
        q["read"] = {"$ne": True}
    rows = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)
    return rows


@router.get("/notifications/unread-count")
async def unread_count(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q = _mine_filter(user, tenant["id"])
    q["read"] = {"$ne": True}
    return {"count": await db.notifications.count_documents(q)}


@router.get("/notifications/kinds")
async def list_kinds(user: dict = Depends(get_current_user)):
    """Kind catalog used by the /settings/notifications UI."""
    return {"kinds": [{"key": k, "label": v} for k, v in KIND_LABELS.items()],
            "defaults": default_prefs()}


@router.post("/notifications/{nid}/read")
async def mark_read(
    nid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q = _mine_filter(user, tenant["id"])
    q["id"] = nid
    r = await db.notifications.update_one(q, {"$set": {"read": True, "read_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def mark_all_read(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q = _mine_filter(user, tenant["id"])
    q["read"] = {"$ne": True}
    r = await db.notifications.update_many(q, {"$set": {"read": True, "read_at": now_iso()}})
    return {"marked": r.modified_count}


# Legacy alias — kept because pre-Phase-55 clients hit /notifications/read-all.
@router.post("/notifications/read-all")
async def mark_all_read_legacy(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await mark_all_read(user=user, tenant=tenant)


@router.delete("/notifications/{nid}")
async def delete_notification(
    nid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    q = _mine_filter(user, tenant["id"])
    q["id"] = nid
    r = await db.notifications.delete_one(q)
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


# ─── Preferences ───────────────────────────────────────────────────────────
class PrefsBody(BaseModel):
    channels: dict


@router.get("/settings/notifications")
async def get_my_prefs(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return {
        **(await get_user_prefs(tenant["id"], user["id"])),
        "kinds": [{"key": k, "label": v} for k, v in KIND_LABELS.items()],
    }


@router.put("/settings/notifications")
async def put_my_prefs(
    body: PrefsBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await set_user_prefs(tenant["id"], user["id"], body.channels or {})
