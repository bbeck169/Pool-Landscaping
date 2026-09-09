"""Phase 7 — AI Marketing Studio.

All AI paths gracefully degrade to a stubbed response with `{stubbed: true, ...}`
when EMERGENT_LLM_KEY is absent so the UI stays functional end-to-end.
"""
import os
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin, get_current_user
from routers.tenants import get_current_tenant

router = APIRouter()

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
STUBBED = not bool(EMERGENT_LLM_KEY)

BRAND_ID = "singleton"
BRAND_DEFAULTS = {
    "business_name": "Pool & Landscaping of Vistancia",
    "description": "Full-service pool and landscape maintenance in North Peoria, AZ.",
    "tone": "Local Expert",
    "target_persona": "Homeowners in Vistancia, Trilogy, and Sun City West with in-ground pools.",
    "service_zips": ["85373", "85375", "85383", "85387"],
    "primary_color": "#0284C7",
    "accent_color": "#16A34A",
    "usps": ["Licensed & insured", "Same-week response", "Transparent pricing"],
    "disallowed_phrases": ["cheapest", "guaranteed clean"],
}

CHANNEL_LIMITS = {"facebook": 500, "instagram": 300, "x": 280, "nextdoor": 800, "gbp": 750}
CHANNEL_HASHTAGS = {"facebook": 3, "instagram": 8, "x": 2, "nextdoor": 0, "gbp": 2}


# ─── models ──────────────────────────────────────────────────────────────────
class BrandIn(BaseModel):
    business_name: Optional[str] = None
    description: Optional[str] = None
    tone: Optional[str] = None
    target_persona: Optional[str] = None
    service_zips: Optional[List[str]] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    usps: Optional[List[str]] = None
    disallowed_phrases: Optional[List[str]] = None


class CampaignIn(BaseModel):
    goal: str
    audience: str = "All customers"
    channels: List[str] = ["email", "sms", "facebook", "instagram"]
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    template_slug: Optional[str] = None


class CampaignUpdate(BaseModel):
    goal: Optional[str] = None
    audience: Optional[str] = None
    channels: Optional[List[str]] = None
    status: Optional[str] = None


class PostGenIn(BaseModel):
    topic: str
    channels: List[str]
    source_url: Optional[str] = None


class VisualIn(BaseModel):
    prompt: str
    style: str = "photo"
    seed: Optional[int] = None


class SchedulingIn(BaseModel):
    channel: str
    slots: List[dict]  # [{day_of_week: "mon", hour: 10, minute: 0}, ...]


class ItemUpdate(BaseModel):
    copy: Optional[str] = None
    hero_image_url: Optional[str] = None
    scheduled_at: Optional[str] = None
    status: Optional[str] = None


class RejectIn(BaseModel):
    reason: Optional[str] = ""


class AgentChatIn(BaseModel):
    message: str
    mentions: List[str] = []


# ─── brand memory ───────────────────────────────────────────────────────────
async def get_brand_memory(tenant_id: str | None = None) -> dict:
    """Fetch this tenant's brand memory (per-tenant singleton).
    Falls back to a global singleton for pre-multi-tenant callers."""
    q = {"id": BRAND_ID}
    if tenant_id:
        q["tenant_id"] = tenant_id
    doc = await db.marketing_brand.find_one(q, {"_id": 0})
    if not doc:
        doc = {"id": BRAND_ID, "tenant_id": tenant_id, **BRAND_DEFAULTS, "updated_at": now_iso()}
        await db.marketing_brand.insert_one(dict(doc))
    return {**BRAND_DEFAULTS, **{k: v for k, v in doc.items() if v is not None and k not in ("id", "tenant_id")}}


@router.get("/marketing/brand")
async def get_brand(admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    return await get_brand_memory(tenant["id"])


@router.put("/marketing/brand")
async def put_brand(body: BrandIn,
                    admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.marketing_brand.update_one(
        {"id": BRAND_ID, "tenant_id": tenant["id"]},
        {"$set": {"id": BRAND_ID, "tenant_id": tenant["id"], **upd}},
        upsert=True,
    )
    return await get_brand_memory()


# ─── AI stub helpers ─────────────────────────────────────────────────────────
def _stub_note() -> str:
    return "AI copy will appear here once EMERGENT_LLM_KEY is configured."


def _stub_variant(channel: str, topic: str, brand: dict) -> dict:
    limit = CHANNEL_LIMITS.get(channel, 500)
    tag_count = CHANNEL_HASHTAGS.get(channel, 0)
    tags = " ".join(["#poolcare", "#peoriaAZ", "#vistancia", "#poollife", "#plofv",
                     "#backyard", "#summer", "#servicematters"][:tag_count])
    base = f"[{brand.get('tone')}] {topic} — {_stub_note()}"
    body = (base + " " + tags).strip()
    return {"channel": channel, "copy": body[:limit], "hashtags": tags,
            "cta": "Book your first visit today.", "character_limit": limit}


async def _ai_variant(channel: str, topic: str, brand: dict, session: Optional[str] = None,
                       tenant_id: Optional[str] = None) -> dict:
    """Real LLM-generated post variant. Falls back to stub if key absent or call fails."""
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return _stub_variant(channel, topic, brand)
    limit = CHANNEL_LIMITS.get(channel, 500)
    tag_count = CHANNEL_HASHTAGS.get(channel, 0)
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.  Plaintext (``parse_json=False``) preserves
        # the local fenced-block JSON extract + truncation logic.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        import json as _json, re as _re
        zips = ", ".join(brand.get("service_zips") or [])
        system = (
            f"You are the {brand.get('tone', 'professional')} marketing voice for a pool & landscaping "
            f"company serving {brand.get('service_area', 'Vistancia, Peoria AZ')} (ZIPs: {zips}). "
            "Write ONLY valid JSON — no prose, no markdown fences."
        )
        prompt = (
            f"Draft a {channel} post about '{topic}'. "
            f"Hard cap: {limit} chars in the 'copy' field. Include exactly {tag_count} on-brand hashtags. "
            "Return JSON: {\"copy\": str, \"hashtags\": str, \"cta\": str}."
        )
        result = await call_llm_with_fallback(
            system_prompt=system, user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-5",
            tenant_id=tenant_id,
            parse_json=False,
        )
        if is_ai_cap_exceeded(result) or result.get("error"):
            return _stub_variant(channel, topic, brand)
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = _re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = _json.loads(text)
        except Exception:
            m = _re.search(r"\{.*\}", text, _re.S)
            data = _json.loads(m.group(0)) if m else {}
        copy = (data.get("copy") or "").strip()
        hashtags = (data.get("hashtags") or "").strip()
        cta = (data.get("cta") or "Book your first visit today.").strip()
        return {"channel": channel, "copy": copy[:limit], "hashtags": hashtags,
                "cta": cta, "character_limit": limit}
    except Exception as e:
        logger.warning(f"marketing _ai_variant fallback ({channel}/{topic}): {e}")
        return _stub_variant(channel, topic, brand)


async def _ai_email(topic: str, goal: str, brand: dict, session: Optional[str] = None,
                     tenant_id: Optional[str] = None) -> dict:
    """LLM-generated email (subject + body). Falls back to stub."""
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return {"subject": f"[{brand.get('tone')}] {goal[:60]}", "copy": _stub_note()}
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        import json as _json, re as _re
        system = (
            f"You are the {brand.get('tone', 'professional')} email marketer for a pool & landscaping "
            f"company. Return ONLY valid JSON."
        )
        prompt = (
            f"Write a marketing email supporting the campaign goal '{goal}' about '{topic}'. "
            "150-220 words in the body. Return JSON: {\"subject\": str (<=60 chars), \"copy\": str}."
        )
        result = await call_llm_with_fallback(
            system_prompt=system, user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-5",
            tenant_id=tenant_id,
            parse_json=False,
        )
        if is_ai_cap_exceeded(result) or result.get("error"):
            return {"subject": f"[{brand.get('tone')}] {goal[:60]}", "copy": _stub_note()}
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = _re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            data = _json.loads(text)
        except Exception:
            m = _re.search(r"\{.*\}", text, _re.S)
            data = _json.loads(m.group(0)) if m else {}
        return {"subject": (data.get("subject") or "")[:80] or f"{goal[:60]}",
                "copy": data.get("copy") or _stub_note()}
    except Exception as e:
        logger.warning(f"marketing _ai_email fallback: {e}")
        return {"subject": f"[{brand.get('tone')}] {goal[:60]}", "copy": _stub_note()}


async def _ai_sms(topic: str, goal: str, brand: dict, session: Optional[str] = None,
                   tenant_id: Optional[str] = None) -> str:
    """LLM-generated SMS (<=160 chars). Falls back to stub."""
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return f"{goal[:80]} — {_stub_note()}"[:160]
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        system = (
            f"You are the {brand.get('tone', 'professional')} SMS copywriter for a pool & landscaping "
            "service. Reply with ONE plaintext SMS message only — no quotes, no preface, no JSON."
        )
        prompt = (
            f"Write ONE SMS (max 155 chars) supporting the goal '{goal}' about '{topic}'. "
            "Include one clear call to action."
        )
        result = await call_llm_with_fallback(
            system_prompt=system, user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-5",
            tenant_id=tenant_id,
            parse_json=False,
        )
        if is_ai_cap_exceeded(result) or result.get("error"):
            return f"{goal[:80]} — {_stub_note()}"[:160]
        text = ((result.get("raw") or {}).get("text") or "").strip().strip('"').strip("'")
        return text[:160] or (f"{goal[:80]} — Book today"[:160])
    except Exception as e:
        logger.warning(f"marketing _ai_sms fallback: {e}")
        return f"{goal[:80]} — {_stub_note()}"[:160]


async def _create_queue_item(row: dict, tenant_id: str | None = None) -> dict:
    row.setdefault("id", new_id())
    row.setdefault("status", "pending_review")
    row.setdefault("created_at", now_iso())
    if tenant_id and "tenant_id" not in row:
        row["tenant_id"] = tenant_id
    await db.marketing_queue.insert_one(row)
    row.pop("_id", None)
    return row


# ─── campaign briefs ────────────────────────────────────────────────────────
@router.get("/marketing/campaigns")
async def list_campaigns(admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await db.marketing_campaigns.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)


@router.post("/marketing/campaigns")
async def create_campaign(body: CampaignIn,
                          admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"], **body.dict(), "status": "draft",
           "created_at": now_iso(), "item_counts": {"pending": 0, "approved": 0}}
    await db.marketing_campaigns.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/marketing/campaigns/{cid}")
async def get_campaign(cid: str,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    c = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not c:
        raise HTTPException(404, "Not found")
    items = await db.marketing_queue.find(
        {"campaign_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    return {**c, "items": items}


@router.patch("/marketing/campaigns/{cid}")
async def patch_campaign(cid: str, body: CampaignUpdate,
                         admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.delete("/marketing/campaigns/{cid}")
async def delete_campaign(cid: str,
                          admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.marketing_campaigns.delete_one({"id": cid, "tenant_id": tenant["id"]})
    await db.marketing_queue.delete_many({"campaign_id": cid, "tenant_id": tenant["id"]})
    return {"ok": True}


@router.post("/marketing/campaigns/{cid}/generate")
async def generate_campaign(cid: str,
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    campaign = await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not campaign:
        raise HTTPException(404, "Not found")
    brand = await get_brand_memory(tenant["id"])
    channels = campaign.get("channels") or ["facebook"]
    goal = campaign.get("goal") or "Boost bookings"
    session = f"campaign-{cid}"
    items_created = []
    stubbed_now = not bool(EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", ""))
    for ch in channels:
        if ch in ("email", "sms"):
            continue
        v = await _ai_variant(ch, goal, brand, session=session, tenant_id=tenant["id"])
        items_created.append(await _create_queue_item({
            "type": "social_post", "channel": ch, "campaign_id": cid,
            "copy": v["copy"], "cta": v["cta"], "hero_image_url": None,
            "hashtags": v.get("hashtags"),
            "character_limit": v["character_limit"],
        }, tenant_id=tenant["id"]))
    if "email" in channels:
        for i in range(2):
            em = await _ai_email(f"{goal} — variant {i+1}", goal, brand, session=session,
                                    tenant_id=tenant["id"])
            items_created.append(await _create_queue_item({
                "type": "email", "channel": "email", "campaign_id": cid,
                "subject": em["subject"], "copy": em["copy"],
            }, tenant_id=tenant["id"]))
    if "sms" in channels:
        for i in range(3):
            sms_copy = await _ai_sms(f"{goal} — variant {i+1}", goal, brand, session=session,
                                          tenant_id=tenant["id"])
            items_created.append(await _create_queue_item({
                "type": "sms", "channel": "sms", "campaign_id": cid,
                "copy": sms_copy,
            }, tenant_id=tenant["id"]))
    if "gbp" in channels or "google" in channels:
        v = await _ai_variant("gbp", goal, brand, session=session, tenant_id=tenant["id"])
        items_created.append(await _create_queue_item({
            "type": "gbp_post", "channel": "gbp", "campaign_id": cid,
            "copy": v["copy"],
        }, tenant_id=tenant["id"]))
    await db.marketing_campaigns.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "generated", "item_counts.pending": len(items_created), "generated_at": now_iso()}},
    )
    return {"stubbed": stubbed_now, "generated": len(items_created), "brand_snapshot": brand,
            "items": items_created}


@router.post("/marketing/campaigns/{cid}/agent-chat")
async def campaign_agent_chat(cid: str, body: AgentChatIn,
                              admin: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    brand = await get_brand_memory(tenant["id"])
    replies = []
    for m in (body.mentions or ["content-writer"]):
        replies.append({
            "persona": m,
            "message": f"@{m}: {_stub_note()} (Tone: {brand['tone']}, ZIPs: {','.join(brand['service_zips'])})",
        })
    doc = {"id": new_id(), "tenant_id": tenant["id"], "campaign_id": cid, "message": body.message,
           "mentions": body.mentions, "replies": replies, "created_at": now_iso()}
    await db.marketing_threads.insert_one(doc)
    doc.pop("_id", None)
    return {"stubbed": STUBBED, **doc}


# ─── posts / variants ────────────────────────────────────────────────────────
@router.post("/marketing/posts/generate")
async def generate_post_variants(body: PostGenIn,
                                 admin: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    brand = await get_brand_memory(tenant["id"])
    session = f"posts-{new_id()[:8]}"
    variants = []
    for ch in body.channels:
        variants.append(await _ai_variant(ch, body.topic, brand, session=session,
                                              tenant_id=tenant["id"]))
    items = []
    for v in variants:
        items.append(await _create_queue_item({
            "type": "social_post", "channel": v["channel"],
            "copy": v["copy"], "cta": v["cta"], "hero_image_url": None,
            "hashtags": v.get("hashtags"),
            "campaign_id": None, "topic": body.topic,
            "character_limit": v["character_limit"],
        }, tenant_id=tenant["id"]))
    stubbed_now = not bool(EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", ""))
    return {"stubbed": stubbed_now, "variants": items}


@router.get("/marketing/posts")
async def list_posts(admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant),
                     status: Optional[str] = None,
                     channel: Optional[str] = None, campaign_id: Optional[str] = None):
    q = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    if channel: q["channel"] = channel
    if campaign_id: q["campaign_id"] = campaign_id
    return await db.marketing_queue.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.patch("/marketing/posts/{pid}")
async def patch_post(pid: str, body: ItemUpdate,
                     admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.marketing_queue.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await db.marketing_queue.find_one({"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})


# ─── visuals ─────────────────────────────────────────────────────────────────
@router.post("/marketing/visuals/generate")
async def generate_visual(body: VisualIn, admin: dict = Depends(require_admin)):
    seed = body.seed or new_id()[:8]
    url = f"https://picsum.photos/seed/{seed}/1200/675"
    return {"stubbed": STUBBED, "url": url, "prompt": body.prompt, "style": body.style}


# ─── approval queue ─────────────────────────────────────────────────────────
@router.get("/marketing/queue")
async def get_queue(admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant),
                    status: Optional[str] = None,
                    channel: Optional[str] = None, campaign_id: Optional[str] = None):
    q = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    if channel: q["channel"] = channel
    if campaign_id: q["campaign_id"] = campaign_id
    return await db.marketing_queue.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/marketing/queue/{item_id}/approve")
async def approve_item(item_id: str,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_queue.update_one(
        {"id": item_id, "tenant_id": tenant["id"]},
        {"$set": {"status": "approved", "approved_at": now_iso()}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Item not found")
    fresh = await db.marketing_queue.find_one({"id": item_id, "tenant_id": tenant["id"]}, {"_id": 0})
    try:
        from routers.realtime import bus
        admins = await db.users.find(
            {"role": "admin", "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
        ).to_list(100)
        for a in admins:
            await bus.broadcast(a["id"], {"type": "approval_change",
                "payload": {"item_id": item_id, "status": "approved"}})
    except Exception:
        pass
    return fresh


@router.post("/marketing/queue/{item_id}/reject")
async def reject_item(item_id: str, body: RejectIn,
                      admin: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_queue.update_one(
        {"id": item_id, "tenant_id": tenant["id"]},
        {"$set": {"status": "rejected", "rejected_at": now_iso(), "reject_reason": body.reason or ""}},
    )
    if not r.matched_count:
        raise HTTPException(404, "Item not found")
    fresh = await db.marketing_queue.find_one({"id": item_id, "tenant_id": tenant["id"]}, {"_id": 0})
    try:
        from routers.realtime import bus
        admins = await db.users.find(
            {"role": "admin", "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
        ).to_list(100)
        for a in admins:
            await bus.broadcast(a["id"], {"type": "approval_change",
                "payload": {"item_id": item_id, "status": "rejected", "reason": body.reason or ""}})
    except Exception:
        pass
    return fresh


@router.post("/marketing/queue/bulk-approve")
async def bulk_approve(ids: List[str],
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    r = await db.marketing_queue.update_many(
        {"id": {"$in": ids}, "tenant_id": tenant["id"]},
        {"$set": {"status": "approved", "approved_at": now_iso()}},
    )
    return {"approved": r.modified_count}


@router.post("/marketing/publish/{item_id}")
async def publish_item(item_id: str,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    item = await db.marketing_queue.find_one(
        {"id": item_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not item:
        raise HTTPException(404, "Not found")
    if item.get("status") not in ("approved", "scheduled"):
        raise HTTPException(400, "Item must be approved before publishing")
    new_status = "published_stubbed" if item.get("channel") != "gbp" else "published"
    await db.marketing_queue.update_one(
        {"id": item_id, "tenant_id": tenant["id"]},
        {"$set": {"status": new_status, "published_at": now_iso()}},
    )
    logger.info(f"marketing_autopost: would publish {item_id} to {item.get('channel')} — stubbed={new_status}")
    return {"ok": True, "status": new_status}


# ─── scheduling slots ────────────────────────────────────────────────────────
@router.get("/marketing/scheduling")
async def get_scheduling(admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    docs = await db.marketing_scheduling.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(50)
    return docs


@router.post("/marketing/scheduling")
async def upsert_scheduling(body: SchedulingIn,
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    await db.marketing_scheduling.update_one(
        {"channel": body.channel, "tenant_id": tenant["id"]},
        {"$set": {"tenant_id": tenant["id"], "channel": body.channel, "slots": body.slots, "updated_at": now_iso()}},
        upsert=True,
    )
    return await db.marketing_scheduling.find_one({"channel": body.channel}, {"_id": 0})


async def run_marketing_autopost():
    """APScheduler job — every 10 minutes."""
    now = datetime.now(timezone.utc).isoformat()
    due = await db.marketing_queue.find(
        {"status": "scheduled", "scheduled_at": {"$lte": now}}, {"_id": 0}
    ).to_list(100)
    fired = 0
    for item in due:
        new_status = "published_stubbed" if item.get("channel") != "gbp" else "published"
        await db.marketing_queue.update_one({"id": item["id"]}, {"$set": {"status": new_status, "published_at": now_iso()}})
        logger.info(f"marketing_autopost tick: published item {item['id']} → {new_status}")
        fired += 1
    if fired:
        logger.info(f"marketing_autopost tick: {fired} item(s) fired.")


# ─── performance ─────────────────────────────────────────────────────────────
@router.get("/marketing/performance")
async def performance(admin: dict = Depends(require_admin)):
    published = await db.marketing_queue.find({"status": {"$in": ["published", "published_stubbed"]}}, {"_id": 0}).to_list(500)
    upcoming = await db.marketing_queue.find({"status": "scheduled"}, {"_id": 0}).to_list(500)
    counts_by_channel = {}
    for p in published:
        counts_by_channel[p.get("channel", "?")] = counts_by_channel.get(p.get("channel", "?"), 0) + 1
    trend = []
    now = datetime.now(timezone.utc).date()
    for i in range(8, 0, -1):
        wk = (now - timedelta(days=i * 7)).isoformat()
        trend.append({"week": wk,
                      "facebook": 3 + (i * 5) % 12,
                      "instagram": 5 + (i * 7) % 15,
                      "gbp": 2 + (i * 3) % 8})
    return {
        "stubbed": True,
        "published_this_month": len(published),
        "upcoming_count": len(upcoming),
        "counts_by_channel": counts_by_channel,
        "best_channel": max(counts_by_channel.items(), key=lambda kv: kv[1])[0] if counts_by_channel else None,
        "avg_engagement": 0.042,  # 4.2% placeholder
        "trend": trend,
        "note": "Mock data — connect FB/IG/Nextdoor/X accounts to see real numbers.",
    }


# ─── review reply drafts ─────────────────────────────────────────────────────
@router.post("/marketing/reviews/{review_id}/draft-reply")
async def draft_reply(review_id: str, admin: dict = Depends(require_admin)):
    brand = await get_brand_memory()
    reply = (f"Thank you so much for your review! We appreciate your business here in "
             f"{','.join(brand['service_zips'])}. {_stub_note()}")
    item = await _create_queue_item({
        "type": "review_reply", "channel": "gbp",
        "review_id": review_id, "copy": reply,
    })
    return {"stubbed": STUBBED, **item}


# ─── AI agents (personas) ────────────────────────────────────────────────────
@router.get("/marketing/agents")
async def list_agents(admin: dict = Depends(require_admin)):
    return [
        {"slug": "content-writer", "name": "Content Writer", "specialty": "Long-form marketing copy"},
        {"slug": "seo-specialist", "name": "SEO Specialist", "specialty": "Keyword strategy + on-page angle"},
        {"slug": "ads-copywriter", "name": "Ads Copywriter", "specialty": "Short punchy conversion copy"},
    ]


# ─── seeded templates ────────────────────────────────────────────────────────
CAMPAIGN_TEMPLATES = [
    {"slug": "end-of-season-deep-clean", "name": "End of Season Deep Clean",
     "goal": "Book deep cleans before winterization.", "tone": "Local Expert",
     "channels": ["email", "sms", "facebook", "instagram", "gbp"]},
    {"slug": "new-customer-welcome", "name": "New Customer Welcome",
     "goal": "Onboard new customers, set expectations.", "tone": "Friendly",
     "channels": ["email", "sms"]},
    {"slug": "off-season-maintenance", "name": "Off-Season Maintenance",
     "goal": "Fill winter/off-season calendar.", "tone": "Professional",
     "channels": ["email", "facebook", "gbp"]},
    {"slug": "referral-push", "name": "Referral Push",
     "goal": "Drive referrals via existing happy customers.", "tone": "Friendly",
     "channels": ["email", "sms", "nextdoor"]},
    {"slug": "waitlist-follow-up", "name": "Waitlist Follow-Up",
     "goal": "Convert waitlisted leads.", "tone": "Local Expert",
     "channels": ["email", "sms"]},
    {"slug": "storm-damage-priority", "name": "Storm Damage Priority Service",
     "goal": "Rapid outreach after storms.", "tone": "Professional",
     "channels": ["email", "sms", "gbp", "facebook", "nextdoor"]},
]

EMAIL_TEMPLATES = [
    {"slug": "welcome-email", "name": "Welcome Email", "subject": "Welcome to Pool & Landscaping",
     "body": "Hi {{name}}, welcome to Pool & Landscaping of Vistancia!"},
    {"slug": "review-request-email", "name": "Review Request", "subject": "How did we do?",
     "body": "Hi {{name}}, we hope you loved your recent service. Would you leave us a review?"},
    {"slug": "invoice-reminder-email", "name": "Invoice Reminder", "subject": "Friendly reminder",
     "body": "Hi {{name}}, this is a friendly reminder about invoice #{{invoice_id}}."},
    {"slug": "service-completed-email", "name": "Service Completed", "subject": "Service report ready",
     "body": "Hi {{name}}, your service report is ready in your portal."},
    {"slug": "quote-follow-up-email", "name": "Quote Follow-Up", "subject": "Any questions on your estimate?",
     "body": "Hi {{name}}, checking in on your estimate. Happy to answer any questions."},
]

SMS_TEMPLATES = [
    {"slug": "review-request-sms", "name": "Review Request SMS",
     "body": "Hi {{name}}, thanks for choosing Pool & Landscaping! Mind leaving us a quick review? {{link}}"},
    {"slug": "invoice-past-due-sms", "name": "Invoice Past Due SMS",
     "body": "Hi {{name}}, invoice #{{invoice_id}} is past due. Pay here: {{link}}"},
    {"slug": "appt-confirmation-sms", "name": "Appointment Confirmation SMS",
     "body": "Reminder: your Pool & Landscaping visit is scheduled for {{date}} at {{time}}."},
]


async def _seed_templates():
    for row in CAMPAIGN_TEMPLATES:
        await db.marketing_campaign_templates.update_one(
            {"slug": row["slug"]}, {"$set": row}, upsert=True)
    for row in EMAIL_TEMPLATES:
        await db.marketing_email_templates.update_one(
            {"slug": row["slug"]}, {"$set": row}, upsert=True)
    for row in SMS_TEMPLATES:
        await db.marketing_sms_templates.update_one(
            {"slug": row["slug"]}, {"$set": row}, upsert=True)


@router.get("/marketing/templates/campaigns")
async def list_campaign_templates(admin: dict = Depends(require_admin)):
    return await db.marketing_campaign_templates.find({}, {"_id": 0}).to_list(100)


@router.get("/marketing/templates/emails")
async def list_email_templates(admin: dict = Depends(require_admin)):
    return await db.marketing_email_templates.find({}, {"_id": 0}).to_list(100)


@router.get("/marketing/templates/sms")
async def list_sms_templates(admin: dict = Depends(require_admin)):
    return await db.marketing_sms_templates.find({}, {"_id": 0}).to_list(100)


# ─── public embeds ───────────────────────────────────────────────────────────
@router.get("/public/checkins")
async def public_checkins():
    checkins = await db.checkins.find({}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"checkins": checkins}


@router.get("/public/company-card")
async def public_company_card():
    brand = await get_brand_memory()
    return {
        "name": brand["business_name"],
        "description": brand["description"],
        "phone": "602-887-4400",
        "email": "hello@plofv.com",
        "service_zips": brand["service_zips"],
        "primary_color": brand["primary_color"],
        "hours": "24/7 dispatch",
    }


@router.get("/embed/portal-widget.js")
async def portal_widget_js():
    js = """
(function(){
  var host = document.currentScript && document.currentScript.getAttribute('data-host') || 'https://poolscape-audit.preview.emergentagent.com';
  var box = document.createElement('div');
  box.style.cssText = 'font-family:system-ui;background:#fff;border:1px solid #E4E4E7;border-radius:16px;padding:16px;max-width:320px;box-shadow:0 2px 8px rgba(0,0,0,0.05)';
  box.innerHTML = '<h3 style="margin:0 0 8px;color:#0284C7">Pool & Landscaping Customer Portal</h3>'
    + '<p style="margin:0 0 12px;font-size:14px;color:#71717A">Sign in to view invoices, estimates, and service history.</p>'
    + '<a href="'+host+'/login" style="display:inline-block;background:#0284C7;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px">Sign in</a>';
  // Phase 21 · Feb 2026 — accept both the new brand id and the legacy
  // one so existing customer embeds keep working during the rebrand.
  var target = document.getElementById('plofv-portal')
    || document.getElementById('aquaterra-portal')
    || document.body;
  target.appendChild(box);
})();
    """.strip()
    return Response(content=js, media_type="application/javascript")


@router.get("/embed/ai-chat-widget.js")
async def ai_widget_js():
    js = """
(function(){
  var box = document.createElement('div');
  box.style.cssText='position:fixed;bottom:20px;right:20px;font-family:system-ui;background:linear-gradient(135deg,#0284C7,#16A34A);color:#fff;padding:14px 18px;border-radius:999px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,0.15);font-weight:700;z-index:9999';
  box.innerText='Chat with Pool & Landscaping';
  box.onclick=function(){alert('AI chat coming soon.');};
  document.body.appendChild(box);
})();
    """.strip()
    return Response(content=js, media_type="application/javascript")
