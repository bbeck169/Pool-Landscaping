"""Feb-2026 · Global Custom Color Picker · per-user "recent colors" list.

Every color commit fires ``POST /users/me/recent-colors`` (fire-and-
forget from the FE). The list is capped at 8, most-recent-first,
de-duped by hex value (case-insensitive). Idempotent by value —
committing the same hex twice in a row leaves the list unchanged.

Endpoints
---------
* ``GET  /api/users/me/recent-colors`` → ``{"recent_colors": [<hex>, …]}``
* ``POST /api/users/me/recent-colors``   body ``{"color": "#RRGGBB"}``
                                          returns the updated list

Both endpoints require the caller to be logged in (any role — the
list is per-user, not per-tenant).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from config import db
from services.color import validate_color_hex_for_pin
from utils import get_current_user


router = APIRouter(prefix="/users/me", tags=["users"])
log = logging.getLogger("user_recent_colors")


MAX_RECENT_COLORS = 8


class _RecentColorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: str = Field(..., min_length=4, max_length=9)


def _normalize_list(raw: Any) -> List[str]:
    """Coerce the persisted field into a clean ``list[str]``. Non-
    string entries are silently dropped so a corrupt row can still
    be read; the next POST will rewrite the field cleanly."""
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for v in raw:
        if isinstance(v, str) and v.strip():
            out.append(v.strip().upper())
    return out


@router.get("/recent-colors")
async def get_recent_colors(user: dict = Depends(get_current_user)):
    row = await db.users.find_one(
        {"id": user["id"]}, {"_id": 0, "recent_colors": 1},
    ) or {}
    return {"recent_colors": _normalize_list(row.get("recent_colors"))}


@router.post("/recent-colors")
async def push_recent_color(
    body: _RecentColorIn,
    user: dict = Depends(get_current_user),
):
    # Validate + canonicalise. Rejects malformed hex + contrast-fails.
    canonical = validate_color_hex_for_pin(body.color)

    row = await db.users.find_one(
        {"id": user["id"]}, {"_id": 0, "recent_colors": 1},
    ) or {}
    current: List[str] = _normalize_list(row.get("recent_colors"))

    # De-dupe by value: drop any existing occurrence, then prepend.
    filtered = [c for c in current if c != canonical]
    updated = [canonical, *filtered][:MAX_RECENT_COLORS]

    if updated == current:
        return {"recent_colors": updated}

    res = await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"recent_colors": updated}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "user not found")
    return {"recent_colors": updated}


__all__ = ["router", "MAX_RECENT_COLORS"]
