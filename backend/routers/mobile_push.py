"""Phase 15C — Mobile device token registration + Expo push (best-effort).

Accepts token registration from the Expo app. If `EXPO_PUSH_ACCESS_TOKEN` is
set on the server, a matching helper can send push messages via
`send_push_to_user(user_id, title, body)`. If unset, the helper is a friendly
no-op (returns `{"pushed": False, "reason": "expo-token-not-configured"}`).
"""
import os
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, get_current_user, require_admin

router = APIRouter()


class RegisterTokenIn(BaseModel):
    token: str = Field(..., min_length=8)
    platform: Optional[str] = None  # "ios" | "android" | "web"
    device_name: Optional[str] = None


@router.post("/mobile-tokens")
async def register_token(body: RegisterTokenIn, user: dict = Depends(get_current_user)):
    # Idempotent upsert keyed by token — one row per device.
    now = now_iso()
    existing = await db.mobile_tokens.find_one({"token": body.token}, {"_id": 0})
    if existing:
        await db.mobile_tokens.update_one(
            {"token": body.token},
            {"$set": {"user_id": user["id"], "platform": body.platform or existing.get("platform"),
                      "device_name": body.device_name or existing.get("device_name"),
                      "last_seen": now}}
        )
        return {"ok": True, "updated": True, "id": existing["id"]}
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "token": body.token,
        "platform": body.platform,
        "device_name": body.device_name,
        "created_at": now,
        "last_seen": now,
    }
    await db.mobile_tokens.insert_one(doc)
    return {"ok": True, "created": True, "id": doc["id"]}


@router.delete("/mobile-tokens")
async def unregister_token(token: str, user: dict = Depends(get_current_user)):
    r = await db.mobile_tokens.delete_one({"token": token, "user_id": user["id"]})
    return {"deleted": r.deleted_count}


async def send_push_to_user(user_id: str, title: str, body: str, data: Optional[dict] = None) -> dict:
    """Fires an Expo push to every registered device for the given user.
    Silent no-op if `EXPO_PUSH_ACCESS_TOKEN` is unset."""
    access = os.environ.get("EXPO_PUSH_ACCESS_TOKEN")
    if not access:
        return {"pushed": False, "reason": "expo-token-not-configured"}
    tokens = await db.mobile_tokens.find({"user_id": user_id}, {"_id": 0}).to_list(50)
    if not tokens:
        return {"pushed": False, "reason": "no-registered-devices"}
    messages = [
        {"to": t["token"], "title": title, "body": body, "data": data or {}, "sound": "default"}
        for t in tokens if t.get("token")
    ]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                "https://exp.host/--/api/v2/push/send",
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
                json=messages,
            )
        return {"pushed": True, "count": len(messages), "status": r.status_code}
    except Exception as e:
        logger.warning(f"Expo push failed: {e}")
        return {"pushed": False, "reason": str(e)[:120]}


@router.get("/mobile-tokens/mine")
async def list_my_tokens(user: dict = Depends(get_current_user)):
    return await db.mobile_tokens.find({"user_id": user["id"]}, {"_id": 0}).to_list(50)
