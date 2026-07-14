"""Phase 18A · Social Media Suite Foundation.

Admin-only (marketing/admin/super_admin). Posts stay in `draft` / `scheduled`
until Phase 18B wires network OAuth. No silent mocking — AI endpoints
return `mocked: false` when `EMERGENT_LLM_KEY` is set.
"""
import os
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

SUPPORTED_NETWORKS = [
    "facebook", "instagram", "twitter", "linkedin",
    "tiktok", "youtube", "gbp", "pinterest", "threads",
]
NETWORK_CHAR_LIMITS = {
    "twitter": 280, "instagram": 2200, "linkedin": 3000,
    "facebook": 5000, "tiktok": 2200, "youtube": 5000,
    "pinterest": 500, "gbp": 1500, "threads": 500,
}
# Marketing/admin/super only.
_MARKETING_ROLES = {"admin", "super_admin", "marketing"}


def require_marketing(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _MARKETING_ROLES:
        raise HTTPException(403, "Marketing/admin access required")
    return user


# ─── Pydantic models ───────────────────────────────────────────────────────
class PostIn(BaseModel):
    networks: List[str]
    caption: str
    hashtags: Optional[List[str]] = []
    media_ids: Optional[List[str]] = []
    scheduled_at: Optional[str] = None
    first_comment: Optional[str] = None
    utm: Optional[Dict[str, str]] = None


class PostPatch(BaseModel):
    networks: Optional[List[str]] = None
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None
    media_ids: Optional[List[str]] = None
    scheduled_at: Optional[str] = None
    first_comment: Optional[str] = None
    utm: Optional[Dict[str, str]] = None


class RescheduleIn(BaseModel):
    scheduled_at: str


class AiCaptionReq(BaseModel):
    topic: str
    tone: Optional[str] = "friendly-professional"
    networks: Optional[List[str]] = None
    length: Optional[str] = "medium"  # short | medium | long


class AiHashtagsReq(BaseModel):
    text: str
    network: Optional[str] = None


class MediaIn(BaseModel):
    url: str  # data URL or CDN URL
    mime: str
    width: Optional[int] = None
    height: Optional[int] = None
    duration_ms: Optional[int] = None
    size_bytes: Optional[int] = None
    tags: Optional[List[str]] = []


class TagReq(BaseModel):
    tags: List[str]


# ─── Post CRUD ─────────────────────────────────────────────────────────────
def _status_for(scheduled_at: Optional[str]) -> str:
    if not scheduled_at:
        return "draft"
    try:
        dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        return "scheduled" if dt > datetime.now(timezone.utc) else "draft"
    except Exception:
        return "draft"


@router.post("/social/posts")
async def create_post(body: PostIn,
                      user: dict = Depends(require_marketing),
                      tenant: dict = Depends(get_current_tenant)):
    for n in body.networks:
        if n not in SUPPORTED_NETWORKS:
            raise HTTPException(400, f"Unknown network: {n}")
    now = now_iso()
    status = _status_for(body.scheduled_at)
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "networks": body.networks,
        "caption": body.caption,
        "hashtags": body.hashtags or [],
        "media_ids": body.media_ids or [],
        "scheduled_at": body.scheduled_at,
        "published_at": None,
        "status": status,
        "per_network_status": {n: "draft" for n in body.networks},
        "first_comment": body.first_comment,
        "utm": body.utm or {},
        "network_metadata": {},
        "error": None,
        "created_at": now, "updated_at": now,
    }
    await db.social_posts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/social/posts")
async def list_posts(status: Optional[str] = None,
                     from_: Optional[str] = Query(None, alias="from"),
                     to: Optional[str] = None,
                     network: Optional[str] = None,
                     limit: int = 100,
                     user: dict = Depends(require_marketing),
                     tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if network:
        q["networks"] = network
    if from_ or to:
        rng = {}
        if from_: rng["$gte"] = from_
        if to: rng["$lte"] = to
        q["scheduled_at"] = rng
    return await db.social_posts.find(q, {"_id": 0}).sort(
        "scheduled_at", -1
    ).to_list(min(limit, 500))


@router.get("/social/posts/{pid}")
async def get_post(pid: str,
                    user: dict = Depends(require_marketing),
                    tenant: dict = Depends(get_current_tenant)):
    doc = await db.social_posts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Post not found")
    return doc


@router.patch("/social/posts/{pid}")
async def edit_post(pid: str, body: PostPatch,
                     user: dict = Depends(require_marketing),
                     tenant: dict = Depends(get_current_tenant)):
    existing = await db.social_posts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Post not found")
    if existing.get("status") in ("published", "publishing"):
        raise HTTPException(400, "Cannot edit a published post")
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if "scheduled_at" in upd:
        upd["status"] = _status_for(upd["scheduled_at"])
    upd["updated_at"] = now_iso()
    await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await db.social_posts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/social/posts/{pid}")
async def delete_post(pid: str,
                       user: dict = Depends(require_marketing),
                       tenant: dict = Depends(get_current_tenant)):
    await db.social_posts.delete_one({"id": pid, "tenant_id": tenant["id"]})
    return {"ok": True}


@router.post("/social/posts/{pid}/reschedule")
async def reschedule_post(pid: str, body: RescheduleIn,
                           user: dict = Depends(require_marketing),
                           tenant: dict = Depends(get_current_tenant)):
    upd = {"scheduled_at": body.scheduled_at,
           "status": _status_for(body.scheduled_at),
           "updated_at": now_iso()}
    r = await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if not r.matched_count:
        raise HTTPException(404, "Post not found")
    return await db.social_posts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.post("/social/posts/{pid}/duplicate")
async def duplicate_post(pid: str,
                          user: dict = Depends(require_marketing),
                          tenant: dict = Depends(get_current_tenant)):
    src = await db.social_posts.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not src:
        raise HTTPException(404, "Post not found")
    now = now_iso()
    dup = {
        **src, "id": new_id(),
        "status": "draft", "scheduled_at": None, "published_at": None,
        "per_network_status": {n: "draft" for n in src.get("networks") or []},
        "created_at": now, "updated_at": now,
        "created_by": user["id"],
    }
    await db.social_posts.insert_one(dup)
    dup.pop("_id", None)
    return dup


# ─── Calendar ─────────────────────────────────────────────────────────────
@router.get("/social/calendar")
async def calendar(year: int, month: int,
                    user: dict = Depends(require_marketing),
                    tenant: dict = Depends(get_current_tenant)):
    start = f"{year:04d}-{month:02d}-01T00:00:00+00:00"
    if month == 12:
        end = f"{year+1:04d}-01-01T00:00:00+00:00"
    else:
        end = f"{year:04d}-{month+1:02d}-01T00:00:00+00:00"
    rows = await db.social_posts.find(
        {"tenant_id": tenant["id"],
         "scheduled_at": {"$gte": start, "$lt": end}},
        {"_id": 0}
    ).sort("scheduled_at", 1).to_list(500)
    return {
        "year": year, "month": month,
        "posts": [{
            "id": r["id"],
            "scheduled_at": r["scheduled_at"],
            "networks": r["networks"],
            "status": r["status"],
            "caption_preview": (r.get("caption") or "")[:80],
            "media_ids": r.get("media_ids") or [],
        } for r in rows],
    }


# ─── AI caption + hashtag generation (LIVE via EMERGENT_LLM_KEY) ───────────
SYSTEM_PROMPT = (
    "You are a social-media copywriter for pool & landscape service companies. "
    "Given a topic and target network(s), produce 3 caption variants. "
    "Each variant must respect network char limits (X: 280, IG: 2200, LI: 3000, "
    "FB: keep punchy, TikTok: 2200, Pinterest: 500). Include 8–12 relevant "
    "hashtags. Return STRICT JSON only: "
    "{\"captions\": [\"...\", \"...\", \"...\"], \"hashtags\": [\"#tag1\", ...]}."
)


async def _ai_call(system: str, prompt: str) -> Optional[str]:
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = (LlmChat(api_key=key, session_id=new_id(),
                        system_message=system)
                .with_model("anthropic", "claude-sonnet-4-5"))
        resp = await chat.send_message(UserMessage(text=prompt))
        return str(resp)
    except Exception as e:
        logger.warning(f"Social AI error: {e}")
        return None


def _parse_ai_json(text: str) -> Optional[dict]:
    if not text: return None
    # strip code fences if present
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip("`").strip()
    # find outermost braces
    try:
        s = t.index("{"); e = t.rindex("}") + 1
        return json.loads(t[s:e])
    except Exception:
        return None


@router.post("/social/ai/caption")
async def ai_caption(body: AiCaptionReq,
                      user: dict = Depends(require_marketing),
                      tenant: dict = Depends(get_current_tenant)):
    nets = body.networks or ["instagram", "facebook", "linkedin"]
    prompt = (f"Topic: {body.topic}\nTone: {body.tone}\n"
              f"Target networks: {', '.join(nets)}\nLength preference: {body.length}\n"
              f"Return the JSON schema described in the system prompt only.")
    raw = await _ai_call(SYSTEM_PROMPT, prompt)
    if raw is None:
        return {"mocked": True,
                "captions": [
                    f"[MOCK] {body.topic} — set EMERGENT_LLM_KEY for real AI captions.",
                    f"[MOCK] {body.topic}",
                    f"[MOCK] {body.topic}",
                ],
                "hashtags": ["#pool", "#landscape", "#service"]}
    parsed = _parse_ai_json(raw)
    if not parsed or "captions" not in parsed:
        return {"mocked": False, "error": "AI returned non-JSON", "raw": raw[:400]}
    return {
        "mocked": False,
        "captions": parsed.get("captions", []),
        "hashtags": parsed.get("hashtags", []),
    }


@router.post("/social/ai/hashtags")
async def ai_hashtags(body: AiHashtagsReq,
                       user: dict = Depends(require_marketing),
                       tenant: dict = Depends(get_current_tenant)):
    prompt = (f"Extract 12 relevant social-media hashtags for the following "
              f"post text. Return STRICT JSON: {{\"hashtags\": [\"#tag1\", ...]}}\n"
              f"Post: {body.text[:1500]}\nNetwork hint: {body.network or 'any'}")
    raw = await _ai_call(SYSTEM_PROMPT, prompt)
    if raw is None:
        return {"mocked": True,
                "hashtags": ["#pool", "#poolservice", "#landscape",
                              "#lawncare", "#backyard", "#outdoorliving"]}
    parsed = _parse_ai_json(raw) or {}
    return {"mocked": False, "hashtags": parsed.get("hashtags", [])}


# ─── Media Library ─────────────────────────────────────────────────────────
@router.post("/social/media")
async def create_media(body: MediaIn,
                        user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "uploaded_by": user["id"],
        "url": body.url,
        "mime": body.mime,
        "width": body.width, "height": body.height,
        "duration_ms": body.duration_ms,
        "size_bytes": body.size_bytes,
        "tags": body.tags or [],
        "created_at": now_iso(),
    }
    await db.social_media_assets.insert_one(doc)
    doc.pop("_id", None)
    return doc


# Alias to match spec URL name.
@router.post("/social/media/upload")
async def create_media_alias(body: MediaIn,
                              user: dict = Depends(require_marketing),
                              tenant: dict = Depends(get_current_tenant)):
    return await create_media(body, user, tenant)


@router.get("/social/media")
async def list_media(type: Optional[str] = None,
                     tag: Optional[str] = None,
                     user: dict = Depends(require_marketing),
                     tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if type == "image":
        q["mime"] = {"$regex": "^image/"}
    elif type == "video":
        q["mime"] = {"$regex": "^video/"}
    if tag:
        q["tags"] = tag
    return await db.social_media_assets.find(q, {"_id": 0}).sort(
        "created_at", -1
    ).to_list(500)


@router.delete("/social/media/{mid}")
async def delete_media(mid: str,
                        user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    await db.social_media_assets.delete_one(
        {"id": mid, "tenant_id": tenant["id"]}
    )
    return {"ok": True}


@router.post("/social/media/{mid}/tag")
async def tag_media(mid: str, body: TagReq,
                     user: dict = Depends(require_marketing),
                     tenant: dict = Depends(get_current_tenant)):
    r = await db.social_media_assets.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"tags": body.tags}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Media not found")
    return await db.social_media_assets.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
