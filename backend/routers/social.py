"""Phase 18A · Social Media Suite Foundation.

Admin-only (marketing/admin/super_admin). Posts stay in `draft` / `scheduled`
until Phase 18B wires network OAuth. No silent mocking — AI endpoints
return `mocked: false` when `EMERGENT_LLM_KEY` is set.

Phase 18A.1 extends this router with:
- Approval workflow (submit / approve / reject / request-changes / comment / queue)
- Bulk CSV or JSON post creation
- UTM tag builder + presets
- Short-link creator/stats/delete (public redirect lives in routers.public_social)
- Media folders, Brand kit, Alt-text (with vision AI helper)
"""
import os
import io
import csv
import json
import re
import secrets
import string
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY, APP_PUBLIC_URL
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
    alt_text: Optional[str] = None
    folder_id: Optional[str] = None


class TagReq(BaseModel):
    tags: List[str]


class MediaPatch(BaseModel):
    tags: Optional[List[str]] = None
    alt_text: Optional[str] = None
    folder_id: Optional[str] = None


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
        "alt_text": body.alt_text,
        "folder_id": body.folder_id,
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


# ═══════════════════════════════════════════════════════════════════════════
# Phase 18A.1 · Approvals · Bulk · UTM · Short-links · Library upgrades
# ═══════════════════════════════════════════════════════════════════════════
_APPROVER_ROLES = {"admin", "super_admin"}
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_ALIAS_ALPHABET = string.ascii_letters + string.digits
_BULK_CAP = 500


def require_approver(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in _APPROVER_ROLES:
        raise HTTPException(403, "Approver access required (admin/super_admin)")
    return user


# ── Approvals ─────────────────────────────────────────────────────────────
class ApprovalDecisionIn(BaseModel):
    comment: Optional[str] = None


class CommentIn(BaseModel):
    text: str


async def _find_post_or_404(pid: str, tenant_id: str) -> dict:
    d = await db.social_posts.find_one({"id": pid, "tenant_id": tenant_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Post not found")
    return d


async def _get_or_create_approval(post_id: str, tenant_id: str, submitted_by: str) -> dict:
    now = now_iso()
    existing = await db.social_post_approvals.find_one(
        {"post_id": post_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if existing:
        return existing
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "post_id": post_id,
        "submitted_by": submitted_by,
        "submitted_at": now,
        "status": "pending",
        "reviewer": None,
        "decided_at": None,
        "comment": None,
        "comment_thread": [],
    }
    await db.social_post_approvals.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _notify_approvers(tenant_id: str, post_id: str, submitted_by: str):
    try:
        admins = await db.users.find(
            {"tenant_id": tenant_id, "role": {"$in": list(_APPROVER_ROLES)}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        from routers.realtime import bus
        for a in admins:
            await bus.broadcast(a["id"], {
                "type": "social.approval.submitted",
                "payload": {"post_id": post_id, "submitted_by": submitted_by},
            })
    except Exception as e:
        logger.warning(f"approval WS broadcast failed: {e}")


@router.post("/social/posts/{pid}/submit-for-approval")
async def submit_for_approval(pid: str,
                              user: dict = Depends(require_marketing),
                              tenant: dict = Depends(get_current_tenant)):
    post = await _find_post_or_404(pid, tenant["id"])
    if post["status"] in ("publishing", "published"):
        raise HTTPException(400, "Cannot submit a published post")
    now = now_iso()
    await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "pending_approval", "updated_at": now}},
    )
    approval = await _get_or_create_approval(pid, tenant["id"], user["id"])
    await db.social_post_approvals.update_one(
        {"id": approval["id"]},
        {"$set": {"status": "pending", "submitted_by": user["id"],
                  "submitted_at": now, "reviewer": None,
                  "decided_at": None, "comment": None}},
    )
    await _notify_approvers(tenant["id"], pid, user["id"])
    return {"ok": True, "post_id": pid, "status": "pending_approval"}


@router.post("/social/posts/{pid}/approve")
async def approve_post(pid: str, body: ApprovalDecisionIn,
                       user: dict = Depends(require_approver),
                       tenant: dict = Depends(get_current_tenant)):
    post = await _find_post_or_404(pid, tenant["id"])
    if post["status"] != "pending_approval":
        raise HTTPException(400, "Post is not pending approval")
    next_status = _status_for(post.get("scheduled_at"))
    now = now_iso()
    await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": next_status, "updated_at": now}},
    )
    await db.social_post_approvals.update_one(
        {"post_id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "approved", "reviewer": user["id"],
                  "decided_at": now, "comment": body.comment}},
    )
    return {"ok": True, "post_status": next_status}


@router.post("/social/posts/{pid}/reject")
async def reject_post(pid: str, body: ApprovalDecisionIn,
                      user: dict = Depends(require_approver),
                      tenant: dict = Depends(get_current_tenant)):
    if not (body.comment or "").strip():
        raise HTTPException(400, "Rejection requires a comment")
    post = await _find_post_or_404(pid, tenant["id"])
    if post["status"] != "pending_approval":
        raise HTTPException(400, "Post is not pending approval")
    now = now_iso()
    await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "draft", "updated_at": now}},
    )
    await db.social_post_approvals.update_one(
        {"post_id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "rejected", "reviewer": user["id"],
                  "decided_at": now, "comment": body.comment}},
    )
    return {"ok": True, "post_status": "draft"}


@router.post("/social/posts/{pid}/request-changes")
async def request_changes(pid: str, body: ApprovalDecisionIn,
                          user: dict = Depends(require_approver),
                          tenant: dict = Depends(get_current_tenant)):
    if not (body.comment or "").strip():
        raise HTTPException(400, "Changes request requires a comment")
    post = await _find_post_or_404(pid, tenant["id"])
    if post["status"] != "pending_approval":
        raise HTTPException(400, "Post is not pending approval")
    now = now_iso()
    await db.social_posts.update_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "draft", "updated_at": now}},
    )
    await db.social_post_approvals.update_one(
        {"post_id": pid, "tenant_id": tenant["id"]},
        {"$set": {"status": "changes_requested", "reviewer": user["id"],
                  "decided_at": now, "comment": body.comment}},
    )
    return {"ok": True, "post_status": "draft"}


@router.post("/social/posts/{pid}/comment")
async def add_approval_comment(pid: str, body: CommentIn,
                               user: dict = Depends(require_marketing),
                               tenant: dict = Depends(get_current_tenant)):
    if not body.text.strip():
        raise HTTPException(400, "text is required")
    await _find_post_or_404(pid, tenant["id"])
    approval = await _get_or_create_approval(pid, tenant["id"], user["id"])
    entry = {"user_id": user["id"], "at": now_iso(), "text": body.text.strip()}
    await db.social_post_approvals.update_one(
        {"id": approval["id"]},
        {"$push": {"comment_thread": entry}},
    )
    return {"ok": True, "entry": entry}


@router.get("/social/approvals")
async def approval_queue(status: Optional[str] = "pending",
                         user: dict = Depends(require_marketing),
                         tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    rows = await db.social_post_approvals.find(q, {"_id": 0}).sort(
        "submitted_at", -1
    ).to_list(200)
    out = []
    for a in rows:
        p = await db.social_posts.find_one(
            {"id": a["post_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        )
        if p:
            a["post_preview"] = {
                "caption": (p.get("caption") or "")[:200],
                "networks": p.get("networks") or [],
                "scheduled_at": p.get("scheduled_at"),
                "status": p.get("status"),
                "media_ids": p.get("media_ids") or [],
            }
        out.append(a)
    return out


# ── Bulk CSV / JSON post creation ─────────────────────────────────────────
class BulkPostRow(BaseModel):
    caption: str
    networks: List[str]
    scheduled_at: Optional[str] = None
    media_urls: Optional[List[str]] = None
    hashtags: Optional[List[str]] = None
    first_comment: Optional[str] = None


class BulkPostsIn(BaseModel):
    posts: List[BulkPostRow]


def _split_semi(cell: Optional[str]) -> List[str]:
    if not cell:
        return []
    return [x.strip() for x in str(cell).split(";") if x.strip()]


async def _create_bulk_row(row: dict, user: dict, tenant_id: str):
    nets = _split_semi(row.get("networks")) if not isinstance(row.get("networks"), list) else [
        n.strip() for n in row["networks"] if str(n).strip()
    ]
    if not nets:
        raise ValueError("networks required")
    for n in nets:
        if n not in SUPPORTED_NETWORKS:
            raise ValueError(f"Unknown network '{n}'")
    caption = (row.get("caption") or "").strip()
    if not caption:
        raise ValueError("caption required")
    scheduled_at = row.get("scheduled_at") or None
    media_urls = (
        _split_semi(row.get("media_urls"))
        if not isinstance(row.get("media_urls"), list)
        else list(row.get("media_urls") or [])
    )
    hashtags = (
        _split_semi(row.get("hashtags"))
        if not isinstance(row.get("hashtags"), list)
        else list(row.get("hashtags") or [])
    )
    # Convert media_urls → media asset records (persisted) so composer can reuse them.
    media_ids: List[str] = []
    for u in media_urls:
        asset = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "uploaded_by": user["id"],
            "url": u,
            "mime": "image/*",
            "tags": ["bulk"],
            "alt_text": None,
            "folder_id": None,
            "created_at": now_iso(),
        }
        await db.social_media_assets.insert_one(asset)
        media_ids.append(asset["id"])
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "created_by": user["id"],
        "networks": nets,
        "caption": caption,
        "hashtags": hashtags,
        "media_ids": media_ids,
        "scheduled_at": scheduled_at,
        "published_at": None,
        "status": _status_for(scheduled_at),
        "per_network_status": {n: "draft" for n in nets},
        "first_comment": row.get("first_comment") or None,
        "utm": {},
        "network_metadata": {},
        "error": None,
        "created_at": now, "updated_at": now,
    }
    await db.social_posts.insert_one(doc)
    return doc["id"]


@router.post("/social/posts/bulk")
async def bulk_create_posts(
    body: Optional[BulkPostsIn] = None,
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(require_marketing),
    tenant: dict = Depends(get_current_tenant),
):
    """Accepts either a JSON body { posts:[...] } or a multipart CSV upload."""
    rows: List[dict] = []
    if file is not None:
        raw = await file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(400, "CSV must be UTF-8 encoded")
        reader = csv.DictReader(io.StringIO(text))
        for r in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in r.items()})
    elif body and body.posts:
        rows = [p.dict() for p in body.posts]
    else:
        raise HTTPException(400, "Provide a CSV file or a JSON body")

    if len(rows) > _BULK_CAP:
        raise HTTPException(400, f"Bulk upload capped at {_BULK_CAP} rows (got {len(rows)})")

    created: List[str] = []
    errors: List[dict] = []
    for idx, r in enumerate(rows, start=1):
        try:
            pid = await _create_bulk_row(r, user, tenant["id"])
            created.append(pid)
        except Exception as e:
            errors.append({"row": idx, "msg": str(e)})
    return {"created": len(created), "errors": errors, "preview_ids": created[:20]}


# ── UTM builder + presets ─────────────────────────────────────────────────
class UtmBuildIn(BaseModel):
    url: str
    source: Optional[str] = None
    medium: Optional[str] = "social"
    campaign: Optional[str] = None
    term: Optional[str] = None
    content: Optional[str] = None


class UtmPresetIn(BaseModel):
    name: str
    source: Optional[str] = None
    medium: Optional[str] = "social"
    campaign: Optional[str] = None
    term: Optional[str] = None
    content: Optional[str] = None


def _build_utm(u: str, params: Dict[str, Optional[str]]) -> str:
    parsed = urlparse(u)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(400, "Invalid URL")
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in params.items():
        if v:
            q[f"utm_{k}"] = v
    return urlunparse(parsed._replace(query=urlencode(q)))


@router.post("/social/utm/build")
async def utm_build(body: UtmBuildIn,
                    user: dict = Depends(require_marketing),
                    tenant: dict = Depends(get_current_tenant)):
    tagged = _build_utm(body.url, {
        "source": body.source, "medium": body.medium,
        "campaign": body.campaign, "term": body.term, "content": body.content,
    })
    return {"tagged_url": tagged}


@router.get("/social/utm/presets")
async def list_utm_presets(user: dict = Depends(require_marketing),
                           tenant: dict = Depends(get_current_tenant)):
    return await db.utm_presets.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("name", 1).to_list(200)


@router.post("/social/utm/presets")
async def create_utm_preset(body: UtmPresetIn,
                            user: dict = Depends(require_marketing),
                            tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name.strip(),
        "source": body.source, "medium": body.medium,
        "campaign": body.campaign, "term": body.term, "content": body.content,
        "created_by": user["id"],
        "created_at": now_iso(),
    }
    await db.utm_presets.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/social/utm/presets/{pid}")
async def delete_utm_preset(pid: str,
                            user: dict = Depends(require_marketing),
                            tenant: dict = Depends(get_current_tenant)):
    await db.utm_presets.delete_one({"id": pid, "tenant_id": tenant["id"]})
    return {"ok": True}


# ── Short links ───────────────────────────────────────────────────────────
class ShortLinkIn(BaseModel):
    target_url: str
    alias: Optional[str] = None


def _gen_alias(n: int = 6) -> str:
    return "".join(secrets.choice(_ALIAS_ALPHABET) for _ in range(n))


async def _ensure_short_indexes():
    try:
        await db.short_links.create_index("alias", unique=True)
        await db.short_links.create_index([("tenant_id", 1), ("alias", 1)])
        await db.short_link_hits.create_index(
            "ts_dt", expireAfterSeconds=60 * 60 * 24 * 90
        )
    except Exception as e:
        logger.warning(f"short-link index create skipped: {e}")


def _origin_from_env(fallback: str = "") -> str:
    return (APP_PUBLIC_URL or fallback or "").rstrip("/")


def _short_url(alias: str) -> str:
    """Build the externally-reachable short URL.

    Kubernetes ingress only forwards `/api/*` to the backend, so the URL we
    hand users must live under `/api/r/`. Locally (curl to :8001) both
    `/r/{alias}` and `/api/r/{alias}` resolve — see routers.public_social
    which is mounted at both paths in server.py.
    """
    origin = _origin_from_env()
    return f"{origin}/api/r/{alias}" if origin else f"/api/r/{alias}"


@router.post("/social/short-links")
async def create_short_link(body: ShortLinkIn,
                            user: dict = Depends(require_marketing),
                            tenant: dict = Depends(get_current_tenant)):
    await _ensure_short_indexes()
    parsed = urlparse(body.target_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(400, "Invalid target URL")
    alias = (body.alias or "").strip()
    if alias:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", alias):
            raise HTTPException(400, "Alias must be 3-32 chars, alnum/_/- only")
        clash = await db.short_links.find_one({"alias": alias})
        if clash:
            raise HTTPException(409, "Alias already taken")
    else:
        for _ in range(6):
            alias = _gen_alias(6)
            if not await db.short_links.find_one({"alias": alias}):
                break
        else:
            raise HTTPException(500, "Could not generate a unique alias")
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "alias": alias,
        "target_url": body.target_url,
        "created_by": user["id"],
        "clicks_total": 0,
        "created_at": now,
    }
    await db.short_links.insert_one(doc)
    doc.pop("_id", None)
    doc["short_url"] = _short_url(alias)
    return doc


@router.get("/social/short-links")
async def list_short_links(user: dict = Depends(require_marketing),
                           tenant: dict = Depends(get_current_tenant)):
    rows = await db.short_links.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    for r in rows:
        r["short_url"] = _short_url(r["alias"])
    return rows


@router.get("/social/short-links/{sid}/stats")
async def short_link_stats(sid: str,
                            user: dict = Depends(require_marketing),
                            tenant: dict = Depends(get_current_tenant)):
    link = await db.short_links.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not link:
        raise HTTPException(404, "Short link not found")
    hits = await db.short_link_hits.find(
        {"link_id": sid}, {"_id": 0}
    ).sort("ts", -1).to_list(1000)
    series: Dict[str, int] = {}
    referrers: Dict[str, int] = {}
    for h in hits:
        day = (h.get("ts") or "")[:10]
        if day:
            series[day] = series.get(day, 0) + 1
        ref = h.get("referrer") or "direct"
        referrers[ref] = referrers.get(ref, 0) + 1
    top_referrers = sorted(
        [{"referrer": k, "count": v} for k, v in referrers.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]
    click_series = sorted(
        [{"date": k, "count": v} for k, v in series.items()],
        key=lambda x: x["date"],
    )
    origin = _origin_from_env()
    return {
        "id": sid,
        "alias": link["alias"],
        "short_url": _short_url(link["alias"]),
        "target_url": link["target_url"],
        "clicks": link.get("clicks_total", 0),
        "click_series": click_series,
        "top_referrers": top_referrers,
    }


@router.delete("/social/short-links/{sid}")
async def delete_short_link(sid: str,
                             user: dict = Depends(require_marketing),
                             tenant: dict = Depends(get_current_tenant)):
    await db.short_links.delete_one({"id": sid, "tenant_id": tenant["id"]})
    await db.short_link_hits.delete_many({"link_id": sid})
    return {"ok": True}


# ── Media folders ─────────────────────────────────────────────────────────
class FolderIn(BaseModel):
    name: str
    parent_id: Optional[str] = None


@router.post("/social/media/folders")
async def create_folder(body: FolderIn,
                        user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "name": body.name.strip() or "Untitled",
        "parent_id": body.parent_id,
        "created_by": user["id"],
        "created_at": now_iso(),
    }
    await db.social_media_folders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/social/media/folders")
async def list_folders(user: dict = Depends(require_marketing),
                       tenant: dict = Depends(get_current_tenant)):
    return await db.social_media_folders.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("name", 1).to_list(500)


@router.delete("/social/media/folders/{fid}")
async def delete_folder(fid: str,
                        user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    # Cascade: move contained assets back to root (folder_id=None).
    await db.social_media_assets.update_many(
        {"tenant_id": tenant["id"], "folder_id": fid},
        {"$set": {"folder_id": None}},
    )
    await db.social_media_folders.delete_one(
        {"id": fid, "tenant_id": tenant["id"]}
    )
    return {"ok": True}


# ── Media PATCH (alt_text / folder_id / tags) ─────────────────────────────
@router.patch("/social/media/{mid}")
async def patch_media(mid: str, body: MediaPatch,
                      user: dict = Depends(require_marketing),
                      tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if not upd:
        raise HTTPException(400, "No fields to update")
    r = await db.social_media_assets.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": upd},
    )
    if not r.matched_count:
        raise HTTPException(404, "Media not found")
    return await db.social_media_assets.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


# ── Brand Kit ─────────────────────────────────────────────────────────────
class BrandKitIn(BaseModel):
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    logo_url: Optional[str] = None
    font_family: Optional[str] = None
    tagline: Optional[str] = None


_BRAND_KIT_DEFAULTS = {
    "primary_color": "#2563EB",
    "secondary_color": "#0EA5E9",
    "accent_color": "#22C55E",
    "logo_url": None,
    "font_family": None,
    "tagline": None,
}


@router.get("/social/brand-kit")
async def get_brand_kit(user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    doc = await db.brand_kits.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        doc = {"tenant_id": tenant["id"], **_BRAND_KIT_DEFAULTS}
    return doc


@router.put("/social/brand-kit")
async def put_brand_kit(body: BrandKitIn,
                        user: dict = Depends(require_marketing),
                        tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    upd = {k: v for k, v in body.dict(exclude_unset=True).items()}
    upd["updated_by"] = user["id"]
    upd["updated_at"] = now
    await db.brand_kits.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": upd, "$setOnInsert": {"tenant_id": tenant["id"], "created_at": now}},
        upsert=True,
    )
    return await db.brand_kits.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    )


# ── AI Alt-text (vision-enabled) ──────────────────────────────────────────
class AltTextReq(BaseModel):
    media_id: str


@router.post("/social/ai/alt-text")
async def ai_alt_text(body: AltTextReq,
                      user: dict = Depends(require_marketing),
                      tenant: dict = Depends(get_current_tenant)):
    media = await db.social_media_assets.find_one(
        {"id": body.media_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not media:
        raise HTTPException(404, "Media not found")
    url = media.get("url") or ""
    system = (
        "You write short, accessible ALT text for social-media photos posted "
        "by a pool & landscape service company. Describe the visible content in "
        "one sentence (max 140 chars). Avoid marketing fluff. Return STRICT JSON: "
        "{\"alt_text\": \"...\"}."
    )
    prompt = f"Media URL: {url}\nMime: {media.get('mime')}\nDescribe this image for accessibility."
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return {"mocked": True,
                "alt_text": "Photo related to pool or landscape service (set EMERGENT_LLM_KEY for real vision)."}
    raw = None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = (LlmChat(api_key=key, session_id=new_id(), system_message=system)
                .with_model("anthropic", "claude-sonnet-4-5"))
        # Only pass ImageContent when it is an http(s) URL Claude can fetch;
        # data URLs also supported by the SDK.
        try:
            msg = UserMessage(text=prompt, file_contents=[ImageContent(image_url=url)])
        except Exception:
            msg = UserMessage(text=prompt)
        raw = str(await chat.send_message(msg))
    except Exception as e:
        logger.warning(f"alt-text vision AI error: {e}")
        raw = None
    if raw:
        parsed = _parse_ai_json(raw)
        if parsed and parsed.get("alt_text"):
            alt = str(parsed["alt_text"]).strip()[:200]
            await db.social_media_assets.update_one(
                {"id": body.media_id, "tenant_id": tenant["id"]},
                {"$set": {"alt_text": alt}},
            )
            return {"mocked": False, "alt_text": alt}
        # AI answered but not JSON — best-effort fallback.
        alt = raw.strip().strip('"').split("\n")[0][:200]
        await db.social_media_assets.update_one(
            {"id": body.media_id, "tenant_id": tenant["id"]},
            {"$set": {"alt_text": alt}},
        )
        return {"mocked": False, "alt_text": alt}
    return {"mocked": True, "alt_text": "Pool & landscape imagery (AI vision unavailable)."}
