"""Feb-2026 · Phase B · Image generation router.

Exposes:
  POST /api/media/image/generate
  POST /api/media/image/edit
  POST /api/media/image/search
  POST /api/media/image/remove-background
  GET  /api/media/library
  DELETE /api/media/library/{image_id}

All admin+ gated. Rate-limited to ``SUPERCOOL_DAILY_IMAGE_LIMIT``
(default 100) generations per tenant per UTC day, tracked in
``media_gen_quotas``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id
from services import media_provider as _mp


router = APIRouter(tags=["Phase B · Image Generation"])


def _daily_limit() -> int:
    try:
        return max(1, int(os.environ.get("SUPERCOOL_DAILY_IMAGE_LIMIT") or 100))
    except (TypeError, ValueError):
        return 100


def _admin_or_403(user: dict) -> None:
    if (user or {}).get("role") not in {"admin", "super_admin", "manager"}:
        raise HTTPException(403, "Admin only")


def _ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def _rate_limit_or_429(tenant_id: str) -> Dict[str, Any]:
    ymd = _ymd()
    row = await db.media_gen_quotas.find_one(
        {"tenant_id": tenant_id, "ymd": ymd}, {"_id": 0}) or {}
    used = int(row.get("count") or 0)
    limit = _daily_limit()
    if used >= limit:
        raise HTTPException(
            429, {"error": "daily_limit_reached",
                    "limit": limit, "used": used,
                    "reason": f"Reached daily image-gen limit ({limit}). "
                                "Resets at 00:00 UTC."})
    return {"used": used, "limit": limit, "ymd": ymd}


async def _bump_quota(tenant_id: str) -> None:
    await db.media_gen_quotas.update_one(
        {"tenant_id": tenant_id, "ymd": _ymd()},
        {"$inc": {"count": 1}, "$set": {"updated_at": now_iso()}},
        upsert=True,
    )


async def _persist_library_entry(*, tenant_id: str, user_id: str,
                                    prompt: str, image_url: str,
                                    image_id: str, provider: str,
                                    tool_used: str,
                                    surface: str = "library",
                                    aspect_ratio: Optional[str] = None,
                                    source_image_url: Optional[str] = None
                                    ) -> Dict[str, Any]:
    doc = {
        "id": image_id,
        "tenant_id": tenant_id,
        "media_type": "image",
        "url": image_url,
        "prompt": prompt,
        "provider": provider,
        "tool_used": tool_used,
        "surface": surface,
        "source_image_url": source_image_url,
        "aspect_ratio": aspect_ratio,
        "created_by_user_id": user_id,
        "created_at": now_iso(),
        "deleted_at": None,
    }
    await db.generated_media.insert_one({**doc})
    return doc


# ─────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────
class GenerateIn(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    aspect_ratio: Optional[str] = Field(default=None,
        description="One of 16:9, 9:16, 4:3, 3:4, 1:1, 21:9, 3:2, 2:3")
    reference_image_url: Optional[str] = None
    tenant_context: Optional[str] = None
    surface: Optional[str] = Field(default="library")


class EditIn(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    source_image_url: str
    aspect_ratio: Optional[str] = None
    surface: Optional[str] = Field(default="library")


class SearchIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    count: int = Field(default=6, ge=1, le=10)
    provider: str = Field(default="both",
                            description="unsplash | pexels | both")


class RemoveBgIn(BaseModel):
    source_image_url: str


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────
@router.post("/media/image/generate", operation_id="media.image.generate")
async def image_generate(body: GenerateIn,
                            user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    quota = await _rate_limit_or_429(tenant_id)
    provider = await _mp.pick_provider(tenant_id)
    try:
        result = await provider.generate(
            tenant_id=tenant_id, prompt=body.prompt,
            aspect_ratio=body.aspect_ratio,
            image_url=body.reference_image_url,
        )
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    if not result.get("image_urls"):
        raise HTTPException(502, "no_image_returned")
    try:
        image_id, saved_url = await _mp._persist_image(result["image_urls"][0])
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    await _bump_quota(tenant_id)
    entry = await _persist_library_entry(
        tenant_id=tenant_id, user_id=user.get("id") or "?",
        prompt=body.prompt, image_url=saved_url, image_id=image_id,
        provider=result.get("provider"),
        tool_used=result.get("tool_used"),
        surface=body.surface or "library",
        aspect_ratio=body.aspect_ratio,
        source_image_url=body.reference_image_url,
    )
    return {"image_id": image_id, "url": saved_url,
             "prompt": body.prompt,
             "tool_used": result.get("tool_used"),
             "provider": result.get("provider"),
             "aspect_ratio": body.aspect_ratio,
             "surface": entry["surface"],
             "created_at": entry["created_at"],
             "quota": {"used": quota["used"] + 1, "limit": quota["limit"]}}


@router.post("/media/image/edit", operation_id="media.image.edit")
async def image_edit(body: EditIn,
                        user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    quota = await _rate_limit_or_429(tenant_id)
    provider = await _mp.pick_provider(tenant_id)
    try:
        result = await provider.generate(
            tenant_id=tenant_id, prompt=body.prompt,
            aspect_ratio=body.aspect_ratio,
            image_url=body.source_image_url,
        )
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    if not result.get("image_urls"):
        raise HTTPException(502, "no_image_returned")
    try:
        image_id, saved_url = await _mp._persist_image(result["image_urls"][0])
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    await _bump_quota(tenant_id)
    entry = await _persist_library_entry(
        tenant_id=tenant_id, user_id=user.get("id") or "?",
        prompt=body.prompt, image_url=saved_url, image_id=image_id,
        provider=result.get("provider"),
        tool_used=result.get("tool_used"),
        surface=body.surface or "library",
        aspect_ratio=body.aspect_ratio,
        source_image_url=body.source_image_url,
    )
    return {"image_id": image_id, "url": saved_url,
             "prompt": body.prompt, "provider": result.get("provider"),
             "tool_used": result.get("tool_used"),
             "surface": entry["surface"],
             "created_at": entry["created_at"],
             "quota": {"used": quota["used"] + 1, "limit": quota["limit"]}}


@router.post("/media/image/search", operation_id="media.image.search")
async def image_search(body: SearchIn,
                          user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    provider = await _mp.pick_provider(tenant_id)
    try:
        result = await provider.search(
            tenant_id=tenant_id, query=body.query,
            count=body.count, provider=body.provider,
        )
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    return {"results": result.get("results") or [],
             "provider": result.get("provider"),
             "tool_used": result.get("tool_used"),
             "query": body.query}


@router.post("/media/image/remove-background",
              operation_id="media.image.removeBackground")
async def image_remove_bg(body: RemoveBgIn,
                            user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    provider = await _mp.pick_provider(tenant_id)
    try:
        result = await provider.remove_background(
            tenant_id=tenant_id, source_image_url=body.source_image_url)
    except _mp.ProviderError as e:
        raise HTTPException(502, str(e))
    return result


@router.get("/media/library", operation_id="media.library.list")
async def media_library(surface: Optional[str] = None,
                          limit: int = 24,
                          offset: int = 0,
                          user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    q: Dict[str, Any] = {"tenant_id": tenant_id, "deleted_at": None}
    if surface:
        q["surface"] = surface
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    cursor = db.generated_media.find(q, {"_id": 0}) \
        .sort("created_at", -1).skip(offset).limit(limit)
    items = await cursor.to_list(limit)
    total = await db.generated_media.count_documents(q)
    quota_row = await db.media_gen_quotas.find_one(
        {"tenant_id": tenant_id, "ymd": _ymd()}, {"_id": 0}) or {}
    return {"items": items, "total": total, "limit": limit, "offset": offset,
             "quota": {"used": int(quota_row.get("count") or 0),
                        "limit": _daily_limit(), "ymd": _ymd()}}


@router.delete("/media/library/{image_id}",
                operation_id="media.library.delete")
async def media_library_delete(image_id: str,
                                  user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")
    r = await db.generated_media.update_one(
        {"id": image_id, "tenant_id": tenant_id, "deleted_at": None},
        {"$set": {"deleted_at": now_iso(),
                    "deleted_by_user_id": user.get("id")}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True, "image_id": image_id}


# ─────────────────────────────────────────────────────────────────────
# Startup index hook (called from server.py)
# ─────────────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await db.generated_media.create_index(
            [("tenant_id", 1), ("surface", 1), ("created_at", -1)])
        await db.media_gen_quotas.create_index(
            [("tenant_id", 1), ("ymd", 1)], unique=True)
    except Exception as e:
        logger.info(f"[media_gen] ensure_indexes noop: {e}")
