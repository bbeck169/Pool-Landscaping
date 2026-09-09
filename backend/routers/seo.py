import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import markdown as md
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin, create_staff_notification
from routers.tenants import get_current_tenant
from models import (
    SeoKeywordReq, SeoArticleReq, SeoAuditReq, WpSettingsIn, SeoPublishReq,
    SeoScheduleReq, SeoScheduleSettings,
)
from services.llm_provider import call_llm_with_fallback
from services.ai.cap_http import raise_if_ai_cap_exceeded

router = APIRouter()

WP_SETTINGS_ID = "wordpress"


async def _ai_json(system: str, prompt: str, session: str, stub: dict | None = None):
    if not EMERGENT_LLM_KEY:
        # Graceful degradation — return the caller-supplied stub with a marker.
        base = {"__stubbed__": True, "stubbed": True}
        if stub:
            base.update(stub)
        return base
    # Phase I1.7.e · Chunk 2.b · Feb-2026 — SEO JSON helper routed
    # through the central AI chokepoint so per-tenant BYO keys + AI
    # spend caps apply. Plaintext (``parse_json=False``) keeps the
    # helper's existing markdown-fence + regex JSON extraction logic
    # bit-for-bit identical — the response is normalised here to the
    # legacy raw-string shape.
    result = await call_llm_with_fallback(
        system_prompt=system, user_text=prompt,
        provider="anthropic", model="claude-sonnet-4-6",
        parse_json=False,
    )
    raise_if_ai_cap_exceeded(result)
    if result.get("error"):
        logger.warning(f"SEO AI call failed: {result.get('error')}")
        raise HTTPException(502, "AI returned an unexpected format, please retry")
    text = (result.get("raw") or {}).get("text") or ""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        logger.warning(f"SEO AI JSON parse failed: {text[:200]}")
        raise HTTPException(502, "AI returned an unexpected format, please retry")


# ----------------------- Keyword ideas (AI-estimated) -----------------------
@router.post("/seo/keywords/suggest")
async def suggest_keywords(body: SeoKeywordReq,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    system = (
        "You are an SEO strategist for a pool & landscaping service company. "
        "Return ONLY valid JSON, no prose."
    )
    prompt = (
        f"Generate 15 high-intent SEO keyword ideas for the topic '{body.seed}' targeting {body.location}. "
        "Return a JSON array; each item: {\"keyword\": str, \"intent\": \"informational|commercial|transactional|local\", "
        "\"volume\": int (estimated monthly searches), \"difficulty\": int (0-100), \"group\": str}. "
        "Estimates are approximate. JSON only."
    )
    data = await _ai_json(system, prompt, f"seo-kw-{user['id']}", stub={
        "keywords": [
            {"keyword": f"{body.seed} near me", "volume": 720, "difficulty": 32},
            {"keyword": f"best {body.seed}", "volume": 540, "difficulty": 41},
            {"keyword": f"{body.seed} {body.location or 'peoria az'}", "volume": 210, "difficulty": 24},
            {"keyword": f"affordable {body.seed}", "volume": 180, "difficulty": 22},
            {"keyword": f"{body.seed} service", "volume": 890, "difficulty": 38},
        ],
    })
    keywords = data if isinstance(data, list) else data.get("keywords", [])
    doc = {"id": new_id(), "tenant_id": tenant["id"], "seed": body.seed, "location": body.location,
           "keywords": keywords, "created_at": now_iso()}
    await db.seo_keywords.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/seo/keywords")
async def list_keyword_research(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await db.seo_keywords.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)


# ----------------------- AI Article generator -----------------------
@router.post("/seo/articles")
async def generate_article(body: SeoArticleReq,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    system = (
        "You are an expert SEO copywriter for a pool & landscaping company in Vistancia, Arizona. "
        "Write helpful, original, E-E-A-T-friendly content optimized for the target keyword without keyword stuffing. "
        "Return ONLY valid JSON, no prose."
    )
    prompt = (
        f"Write an SEO-optimized blog article targeting the keyword '{body.keyword}'. "
        f"{('Use this working title: ' + body.title + '. ') if body.title else ''}"
        f"Tone: {body.tone}. Target length: about {body.word_count} words. "
        "Return JSON: {\"title\": str, \"slug\": str, \"meta_description\": str (<=155 chars), "
        "\"tags\": [str], \"body_markdown\": str (full article with ## H2 and ### H3 headings), "
        "\"faqs\": [{\"q\": str, \"a\": str}], \"word_count\": int}. JSON only."
    )
    _stub_body = (
        f"## What you need to know about {body.keyword}\n\nAI copy will appear here once EMERGENT_LLM_KEY is configured. "
        "This is a placeholder skeleton so the editor + schedule flows still work.\n\n"
        f"### Why it matters\n\nLorem placeholder for {body.keyword}.\n\n"
        f"### How Pool & Landscaping of Vistancia handles it\n\nPlaceholder body.\n\n"
        f"### Common questions\n\nPlaceholder FAQ block."
    )
    art = await _ai_json(system, prompt, f"seo-art-{user['id']}", stub={
        "title": body.title or f"Guide to {body.keyword}",
        "slug": (body.title or body.keyword).lower().replace(" ", "-")[:60],
        "meta_description": f"AI meta description will appear here once EMERGENT_LLM_KEY is configured. Topic: {body.keyword}."[:155],
        "tags": [body.keyword, "pool care", "vistancia"],
        "body_markdown": _stub_body,
        "faqs": [{"q": "What is included?", "a": "Placeholder answer once AI is enabled."}],
        "word_count": 320,
    })
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "keyword": body.keyword,
        "title": art.get("title", body.title or body.keyword),
        "slug": art.get("slug", ""),
        "meta_description": art.get("meta_description", ""),
        "tags": art.get("tags", []),
        "body_markdown": art.get("body_markdown", ""),
        "faqs": art.get("faqs", []),
        "word_count": art.get("word_count", 0),
        "status": "draft",
        "created_at": now_iso(),
    }
    await db.seo_articles.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/seo/articles")
async def list_articles(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    return await db.seo_articles.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "body_markdown": 0, "faqs": 0}
    ).sort("created_at", -1).to_list(200)


@router.get("/seo/articles/{aid}")
async def get_article(aid: str,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    doc = await db.seo_articles.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Article not found")
    return doc


@router.delete("/seo/articles/{aid}")
async def delete_article(aid: str,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await db.seo_articles.delete_one({"id": aid, "tenant_id": tenant["id"]})
    return {"ok": True}


class SeoArticlePatch(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    meta_description: Optional[str] = None
    tags: Optional[List[str]] = None
    body_markdown: Optional[str] = None
    faqs: Optional[List[dict]] = None
    keyword: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[str] = None


@router.patch("/seo/articles/{aid}")
async def patch_article(aid: str, body: SeoArticlePatch,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    if "body_markdown" in upd:
        upd["word_count"] = len((upd["body_markdown"] or "").split())
    r = await db.seo_articles.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    if not r.matched_count:
        raise HTTPException(404, "Article not found")
    return await db.seo_articles.find_one({"id": aid, "tenant_id": tenant["id"]}, {"_id": 0})


# ----------------------- Content SEO audit -----------------------
@router.post("/seo/audit")
async def audit_content(body: SeoAuditReq,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    content = body.content
    if not content and body.article_id:
        art = await db.seo_articles.find_one(
            {"id": body.article_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        if art:
            content = f"{art.get('title','')}\n{art.get('meta_description','')}\n{art.get('body_markdown','')}"
    if not content:
        raise HTTPException(400, "Provide content or a valid article_id")
    system = (
        "You are an on-page SEO auditor. Analyze the content for the target keyword and return ONLY valid JSON."
    )
    prompt = (
        f"Audit this content for the target keyword '{body.keyword}'. Content:\n\"\"\"\n{content[:6000]}\n\"\"\"\n"
        "Return JSON: {\"score\": int (0-100), \"checks\": [{\"label\": str, "
        "\"status\": \"pass|warn|fail\", \"detail\": str}], \"suggestions\": [str]}. "
        "Cover: title/keyword usage, meta description, headings structure, keyword density, readability, "
        "content length, internal/external link opportunities. JSON only."
    )
    return await _ai_json(system, prompt, f"seo-audit-{user['id']}", stub={
        "score": 74,
        "checks": {
            "meta_title": "OK · 48 chars",
            "meta_description": "OK · 142 chars",
            "h1_count": 1,
            "h2_count": 5,
            "image_alt_pct": 0.87,
            "word_count": 1240,
            "canonical": "OK",
            "sitemap": "OK",
            "mobile_friendly": "OK",
            "load_time_seconds": 2.4,
        },
        "recommendations": [
            "Add 2 more internal links to key service pages.",
            "Compress hero image (~340 kB → ~120 kB).",
            "Estimated results until EMERGENT_LLM_KEY is configured.",
        ],
    })


# ----------------------- WordPress connection settings -----------------------
async def _get_wp_settings(tenant_id: str | None = None) -> dict | None:
    """Load per-tenant WP settings from Mongo, with a global env-var
    fallback so a single ``WORDPRESS_URL`` / ``WORDPRESS_USERNAME`` /
    ``WORDPRESS_APP_PASSWORD`` env config activates the integration for
    every tenant without requiring the Studio → Connect click. The
    per-tenant Mongo doc still wins when present."""
    q = {"id": WP_SETTINGS_ID}
    if tenant_id:
        q["tenant_id"] = tenant_id
    doc = await db.seo_settings.find_one(q, {"_id": 0})
    if doc and doc.get("url") and doc.get("username") and doc.get("app_password"):
        return doc
    # Env fallback.
    import os as _os
    url = (_os.environ.get("WORDPRESS_URL") or "").strip().rstrip("/")
    user = ((_os.environ.get("WORDPRESS_USERNAME")
              or _os.environ.get("WORDPRESS_USER")) or "").strip()
    app_pw = (_os.environ.get("WORDPRESS_APP_PASSWORD") or "").strip()
    if url and user and app_pw:
        return {"id": WP_SETTINGS_ID, "tenant_id": tenant_id,
                "url": url, "username": user, "app_password": app_pw,
                "_source": "env"}
    return doc  # may be None or partial


def _wp_auto_publish_allowed() -> bool:
    """When ``WORDPRESS_AUTO_PUBLISH`` is anything other than a truthy
    value, the SEO scheduler is force-clamped to ``draft`` mode
    regardless of the tenant's ``publish_as`` setting."""
    import os as _os
    return (_os.environ.get("WORDPRESS_AUTO_PUBLISH") or "").strip().lower() in ("1", "true", "yes")


@router.get("/seo/wp-settings")
async def get_wp_settings(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    s = await _get_wp_settings(tenant["id"])
    if not s:
        return {"connected": False, "url": "", "username": ""}
    return {
        "connected": bool(s.get("url") and s.get("username") and s.get("app_password")),
        "url": s.get("url", ""),
        "username": s.get("username", ""),
    }


@router.put("/seo/wp-settings")
async def save_wp_settings(body: WpSettingsIn,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    url = body.url.strip().rstrip("/")
    if not url.startswith("http"):
        raise HTTPException(400, "Site URL must start with http:// or https://")
    doc = {
        "id": WP_SETTINGS_ID,
        "tenant_id": tenant["id"],
        "url": url,
        "username": body.username.strip(),
        "app_password": body.app_password.strip(),
        "updated_at": now_iso(),
    }
    await db.seo_settings.update_one(
        {"id": WP_SETTINGS_ID, "tenant_id": tenant["id"]},
        {"$set": doc}, upsert=True,
    )
    return {"connected": True, "url": doc["url"], "username": doc["username"]}


@router.post("/seo/wp-settings/test")
async def test_wp_settings(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    s = await _get_wp_settings(tenant["id"])
    if not s or not s.get("url"):
        raise HTTPException(400, "WordPress is not configured yet")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{s['url']}/wp-json/wp/v2/users/me",
                auth=(s["username"], s["app_password"]),
            )
    except Exception as e:
        logger.warning(f"WP test failed: {e}")
        raise HTTPException(424, "Could not reach the WordPress site. Check the URL.")
    if r.status_code == 401:
        raise HTTPException(401, "WordPress rejected the credentials (check username / application password).")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, f"WordPress error: {r.text[:200]}")
    data = r.json()
    return {"ok": True, "name": data.get("name", s["username"])}


def _article_to_html(art: dict) -> str:
    body = md.markdown(art.get("body_markdown", ""), extensions=["extra", "sane_lists"])
    faqs = art.get("faqs") or []
    if faqs:
        items = "".join(
            f"<h3>{f.get('q','')}</h3>\n<p>{f.get('a','')}</p>\n" for f in faqs
        )
        body += f"\n<h2>Frequently Asked Questions</h2>\n{items}"
    return body


class WpError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail


async def _publish_to_wp(art: dict, status: str) -> dict:
    """Publish an article to WordPress. Raises WpError on failure. Returns wp response dict."""
    s = await _get_wp_settings(art.get("tenant_id"))
    if not s or not (s.get("url") and s.get("username") and s.get("app_password")):
        raise WpError(400, "Connect your WordPress site first (Connect tab).")
    status = "publish" if status not in ("draft", "publish") else status
    payload = {
        "title": art.get("title", ""),
        "content": _article_to_html(art),
        "slug": art.get("slug", ""),
        "excerpt": art.get("meta_description", ""),
        "status": status,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(
                f"{s['url']}/wp-json/wp/v2/posts",
                json=payload,
                auth=(s["username"], s["app_password"]),
            )
    except Exception as e:
        logger.warning(f"WP publish failed: {e}")
        raise WpError(424, "Could not reach the WordPress site.")
    if r.status_code == 401:
        raise WpError(401, "WordPress rejected the credentials.")
    if r.status_code not in (200, 201):
        raise WpError(r.status_code if r.status_code < 500 else 424, f"WordPress error: {r.text[:300]}")
    wp = r.json()
    update = {
        "status": "published",
        "wp_status": status,
        "wp_post_id": wp.get("id"),
        "wp_link": wp.get("link", ""),
        "published_at": now_iso(),
        "scheduled_for": None,
    }
    await db.seo_articles.update_one({"id": art["id"]}, {"$set": update})
    # Auto content-calendar: draft (and publish if connected) a matching Google Business post.
    try:
        from routers.gbp import auto_gbp_from_article
        await auto_gbp_from_article({**art, **update})
    except Exception as e:
        logger.warning(f"auto GBP hook failed: {e}")
    return {"link": wp.get("link", ""), "wp_post_id": wp.get("id"), "wp_status": status}


# ----------------------- Publish article to WordPress -----------------------
@router.post("/seo/articles/{aid}/publish")
async def publish_article(aid: str, body: SeoPublishReq,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    art = await db.seo_articles.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not art:
        raise HTTPException(404, "Article not found")
    try:
        res = await _publish_to_wp(art, body.status)
    except WpError as e:
        raise HTTPException(e.status, e.detail)
    return {"ok": True, "link": res["link"], "wp_post_id": res["wp_post_id"], "status": "published"}


# ----------------------- Scheduling / auto-drip -----------------------
DEFAULT_SCHEDULE = {"enabled": True, "paused": False, "day_of_week": 0, "hour": 9, "minute": 0, "publish_as": "draft"}


async def _get_schedule(tenant_id: str | None = None) -> dict:
    q = {"id": "schedule"}
    if tenant_id:
        q["tenant_id"] = tenant_id
    doc = await db.seo_settings.find_one(q, {"_id": 0}) or {}
    return {**DEFAULT_SCHEDULE, **{k: v for k, v in doc.items() if k not in ("id", "tenant_id")}}


def _next_weekly_slot(after: datetime, dow: int, hour: int, minute: int) -> datetime:
    """First occurrence of the given weekday/time strictly after `after` (UTC)."""
    days_ahead = (dow - after.weekday()) % 7
    candidate = (after + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=7)
    return candidate


@router.get("/seo/schedule")
async def get_schedule(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    sched = await _get_schedule(tenant["id"])
    queued = await db.seo_articles.find(
        {"tenant_id": tenant["id"], "status": "scheduled"},
        {"_id": 0, "body_markdown": 0, "faqs": 0}
    ).sort("scheduled_for", 1).to_list(200)
    return {"settings": sched, "queued": queued}


@router.put("/seo/schedule")
async def update_schedule(body: SeoScheduleSettings,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = {"id": "schedule", "tenant_id": tenant["id"], **body.model_dump(exclude_none=True)}
    await db.seo_settings.update_one(
        {"id": "schedule", "tenant_id": tenant["id"]}, {"$set": doc}, upsert=True
    )
    return await _get_schedule(tenant["id"])


@router.post("/seo/articles/{aid}/schedule")
async def schedule_article(aid: str, body: SeoScheduleReq,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    art = await db.seo_articles.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not art:
        raise HTTPException(404, "Article not found")
    sched = await _get_schedule(tenant["id"])
    now = datetime.now(timezone.utc)

    if body.mode == "manual":
        if not body.scheduled_for:
            raise HTTPException(400, "A publish date is required for manual scheduling.")
        try:
            when = datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(400, "Invalid date format.")
    else:
        last = await db.seo_articles.find_one(
            {"tenant_id": tenant["id"], "status": "scheduled", "queue_mode": "auto"},
            {"_id": 0, "scheduled_for": 1}, sort=[("scheduled_for", -1)],
        )
        if last and last.get("scheduled_for"):
            base = datetime.fromisoformat(last["scheduled_for"])
            when = base + timedelta(days=7)
        else:
            when = _next_weekly_slot(now, sched["day_of_week"], sched["hour"], sched["minute"])

    await db.seo_articles.update_one(
        {"id": aid, "tenant_id": tenant["id"]},
        {"$set": {"status": "scheduled", "queue_mode": body.mode, "scheduled_for": when.isoformat()}},
    )
    return {"ok": True, "scheduled_for": when.isoformat(), "mode": body.mode}


@router.post("/seo/articles/{aid}/unschedule")
async def unschedule_article(aid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    art = await db.seo_articles.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not art:
        raise HTTPException(404, "Article not found")
    await db.seo_articles.update_one(
        {"id": aid, "tenant_id": tenant["id"]},
        {"$set": {"status": "draft", "scheduled_for": None, "queue_mode": None}},
    )
    return {"ok": True}


async def run_due_publishes():
    """Called by the background scheduler: publish any scheduled articles whose time has arrived.
    Runs cross-tenant — each article carries its own tenant_id."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        due = await db.seo_articles.find(
            {"status": "scheduled", "scheduled_for": {"$lte": now}}, {"_id": 0}
        ).to_list(50)
        for art in due:
            try:
                sched = await _get_schedule(art.get("tenant_id"))
                if sched.get("paused") or not sched.get("enabled"):
                    continue
                res = await _publish_to_wp(art,
                    sched.get("publish_as", "draft")
                    if _wp_auto_publish_allowed() else "draft")
                await create_staff_notification(
                    "SEO article published",
                    f"'{art.get('title','')}' was auto-published to WordPress ({res['wp_status']}).",
                    tenant_id=art.get("tenant_id"),
                )
                logger.info(f"Auto-published SEO article {art['id']}")
            except WpError as e:
                logger.warning(f"Auto-publish skipped for {art['id']}: {e.detail}")
    except Exception as e:
        logger.warning(f"run_due_publishes error: {e}")
