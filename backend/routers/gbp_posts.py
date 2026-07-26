"""Feb-2026 · Phase 20 P1 — GBP post drafter with AI-generated image.

Google Business Profile API does NOT permit programmatic posting
so this router does DRAFTING only. Every draft is copy-paste ready
and image-ready — the admin posts manually via GBP.

Endpoints:
* POST /api/marketing/gbp-posts/generate  (gbpPosts.generate)
* GET  /api/marketing/gbp-posts           (gbpPosts.list)
* PATCH /api/marketing/gbp-posts/{id}     (gbpPosts.update)
* DELETE /api/marketing/gbp-posts/{id}    (gbpPosts.delete)
* POST /api/marketing/gbp-posts/{id}/schedule  (gbpPosts.schedule)
* GET  /api/marketing/gbp-posts/scheduled-today  (gbpPosts.scheduledToday)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter(tags=["GBP Posts"])

_TENANT_TZ = ZoneInfo("America/Phoenix")
_PURPOSES = {"promo", "event", "new_service", "seasonal_tip",
              "featured_customer", "update"}
_TONES = {"friendly", "professional", "promotional"}


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


def _season() -> str:
    m = datetime.now(_TENANT_TZ).month
    if m in (12, 1, 2): return "winter"
    if m in (3, 4, 5):  return "spring"
    if m in (6, 7, 8):  return "summer"
    return "fall"


class GenerateIn(BaseModel):
    purpose: str = "update"
    topic_hint: Optional[str] = None
    tone: str = "friendly"
    cta_type: Optional[str] = None


def _fallback_draft(business_card: Dict[str, Any], body_in: GenerateIn) -> Dict[str, Any]:
    company = business_card.get("company_name") or "our team"
    area = business_card.get("service_area") or "the area"
    season = _season()
    hint = body_in.topic_hint or f"our {body_in.purpose.replace('_', ' ')} for {season}"
    return {
        "headline": f"{company} · {season.title()} update",
        "body_150w": (
            f"Hi neighbors — a quick note from {company}. {hint.capitalize()}. "
            f"We're proudly serving {area} with the same crew you know and trust. "
            f"If we can help, give us a call today."
        ),
        "cta_text": body_in.cta_type or "Call now",
        "image_prompt": (
            f"A crisp, warm photo depicting {hint}, "
            f"for a {season} {body_in.purpose} post from {company}."
        ),
    }


async def _llm_draft(tenant_id: str, card: Dict[str, Any], body_in: GenerateIn) -> Dict[str, Any]:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return _fallback_draft(card, body_in)
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        from routers.ai_brain import build_system_prompt
        sys_prompt = await build_system_prompt(tenant_id)
        chat = (
            LlmChat(api_key=key, session_id=f"gbp-{tenant_id}-{new_id()}",
                     system_message=sys_prompt or "You are a helpful assistant.")
            .with_model("anthropic", "claude-sonnet-4-5-20250929")
            .with_max_tokens(600)
        )
        prompt = (
            f"Draft a Google Business Profile post.\n"
            f"Purpose: {body_in.purpose}\n"
            f"Tone: {body_in.tone}\n"
            f"CTA type: {body_in.cta_type or 'None'}\n"
            f"Topic hint: {body_in.topic_hint or 'none'}\n"
            f"Season (for context): {_season()}\n\n"
            f"Return STRICT JSON with keys: headline (max 60 chars), "
            f"body_150w (120-160 words), cta_text (max 20 chars), "
            f"image_prompt (a photorealistic image description). "
            f"No prose outside the JSON."
        )
        raw = (await chat.send_message(UserMessage(text=prompt))) or ""
        import json as _json
        # Best-effort JSON extract.
        raw = raw.strip()
        if "```" in raw:
            # peel a fenced block if the model returned one.
            parts = raw.split("```")
            for p in parts:
                p = p.strip()
                if p.startswith("{"):
                    raw = p; break
                if p.startswith("json"):
                    raw = p[4:].strip(); break
        try:
            j = _json.loads(raw)
        except Exception:
            return _fallback_draft(card, body_in)
        return {
            "headline":     str(j.get("headline") or "")[:100] or _fallback_draft(card, body_in)["headline"],
            "body_150w":    str(j.get("body_150w") or "") or _fallback_draft(card, body_in)["body_150w"],
            "cta_text":     str(j.get("cta_text") or body_in.cta_type or "Call now")[:40],
            "image_prompt": str(j.get("image_prompt") or "") or _fallback_draft(card, body_in)["image_prompt"],
        }
    except Exception as e:
        logger.warning(f"[gbp-draft] LLM failed: {e}")
        return _fallback_draft(card, body_in)


async def _generate_image(prompt: str, tenant_id: str) -> Optional[str]:
    """Best-effort nano-banana image gen. Returns URL or None."""
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        # Nano banana lives under Gemini image gen. Use the shared
        # library entry — return URL if the SDK exposes one.
        # The image URL persists in media_library so it's stable.
        try:
            from services.image_gen_nano_banana import generate as _gen
            url = await _gen(prompt=prompt, tenant_id=tenant_id,
                              size="1024x1024", quality="medium")
            return url
        except Exception:
            return None
    except Exception:
        return None


@router.post("/marketing/gbp-posts/generate", status_code=201,
              operation_id="gbpPosts.generate")
async def generate(body: GenerateIn,
                    user: Dict[str, Any] = Depends(get_current_user),
                    tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    if body.purpose not in _PURPOSES:
        raise HTTPException(400, f"purpose must be one of {sorted(_PURPOSES)}")
    if body.tone not in _TONES:
        raise HTTPException(400, f"tone must be one of {sorted(_TONES)}")
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    draft = await _llm_draft(tenant["id"], card, body)
    img_url = await _generate_image(draft["image_prompt"], tenant["id"])
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "purpose": body.purpose,
        "tone": body.tone,
        "topic_hint": body.topic_hint,
        "cta_type": body.cta_type,
        **draft,
        "image_url": img_url,
        "status": "draft",
        "scheduled_for": None,
        "generated_at": now_iso(),
        "generated_by": user.get("id"),
    }
    await db.gbp_post_drafts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/marketing/gbp-posts", operation_id="gbpPosts.list")
async def list_posts(user: Dict[str, Any] = Depends(get_current_user),
                      tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    rows = await db.gbp_post_drafts.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("generated_at", -1).to_list(200)
    return {"items": rows, "total": len(rows)}


class UpdateIn(BaseModel):
    headline: Optional[str] = None
    body_150w: Optional[str] = None
    cta_text: Optional[str] = None
    status: Optional[str] = None
    # Feb-2026 · Phase B follow-up — allow the "Generate branded image"
    # composer modal to attach a freshly generated image to an existing
    # draft. The Content Studio route already writes the image to
    # ``generated_media``; we just persist its public URL here so the
    # draft card and any downstream GBP copy-paste flow picks it up.
    image_url: Optional[str] = None


@router.patch("/marketing/gbp-posts/{pid}", operation_id="gbpPosts.update")
async def update_post(pid: str, body: UpdateIn,
                       user: Dict[str, Any] = Depends(get_current_user),
                       tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    row = await db.gbp_post_drafts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if patch:
        if "status" in patch and patch["status"] not in {"draft", "posted", "archived"}:
            raise HTTPException(400, "status must be draft|posted|archived")
        patch["updated_at"] = now_iso()
        if patch.get("status") == "posted":
            patch["posted_at"] = now_iso()
        await db.gbp_post_drafts.update_one({"id": pid}, {"$set": patch})
    fresh = await db.gbp_post_drafts.find_one({"id": pid}, {"_id": 0})
    return fresh


@router.delete("/marketing/gbp-posts/{pid}", operation_id="gbpPosts.delete")
async def delete_post(pid: str,
                       user: Dict[str, Any] = Depends(get_current_user),
                       tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    r = await db.gbp_post_drafts.delete_one(
        {"id": pid, "tenant_id": tenant["id"]},
    )
    return {"ok": True, "deleted": r.deleted_count}


class ScheduleIn(BaseModel):
    scheduled_for: str = Field(..., description="ISO date/time")


@router.post("/marketing/gbp-posts/{pid}/schedule",
              operation_id="gbpPosts.schedule")
async def schedule_post(pid: str, body: ScheduleIn,
                         user: Dict[str, Any] = Depends(get_current_user),
                         tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    r = await db.gbp_post_drafts.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"scheduled_for": body.scheduled_for,
                    "updated_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Not found")
    return {"ok": True, "scheduled_for": body.scheduled_for}


@router.get("/marketing/gbp-posts/scheduled-today",
             operation_id="gbpPosts.scheduledToday")
async def scheduled_today(user: Dict[str, Any] = Depends(get_current_user),
                           tenant: Dict[str, Any] = Depends(get_current_tenant)):
    _require_admin(user)
    today = datetime.now(_TENANT_TZ).date().isoformat()
    rows = await db.gbp_post_drafts.find({
        "tenant_id": tenant["id"],
        "status": "draft",
        "scheduled_for": {"$gte": today, "$lt": today + "T23:59:59"},
    }, {"_id": 0}).to_list(50)
    return {"date": today, "total": len(rows), "items": rows}
