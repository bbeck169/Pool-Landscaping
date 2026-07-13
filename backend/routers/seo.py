import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import markdown as md
from fastapi import APIRouter, HTTPException, Depends

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin, create_staff_notification
from models import (
    SeoKeywordReq, SeoArticleReq, SeoAuditReq, WpSettingsIn, SeoPublishReq,
    SeoScheduleReq, SeoScheduleSettings,
)
from emergentintegrations.llm.chat import LlmChat, UserMessage

router = APIRouter()

WP_SETTINGS_ID = "wordpress"


async def _ai_json(system: str, prompt: str, session: str):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "AI is not configured")
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session, system_message=system).with_model("anthropic", "claude-sonnet-4-6")
    raw = await chat.send_message(UserMessage(text=prompt))
    text = raw if isinstance(raw, str) else str(raw)
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
async def suggest_keywords(body: SeoKeywordReq, user: dict = Depends(require_admin)):
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
    data = await _ai_json(system, prompt, f"seo-kw-{user['id']}")
    keywords = data if isinstance(data, list) else data.get("keywords", [])
    doc = {"id": new_id(), "seed": body.seed, "location": body.location,
           "keywords": keywords, "created_at": now_iso()}
    await db.seo_keywords.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/seo/keywords")
async def list_keyword_research(user: dict = Depends(require_admin)):
    return await db.seo_keywords.find({}, {"_id": 0}).sort("created_at", -1).to_list(50)


# ----------------------- AI Article generator -----------------------
@router.post("/seo/articles")
async def generate_article(body: SeoArticleReq, user: dict = Depends(require_admin)):
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
    art = await _ai_json(system, prompt, f"seo-art-{user['id']}")
    doc = {
        "id": new_id(),
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
async def list_articles(user: dict = Depends(require_admin)):
    return await db.seo_articles.find({}, {"_id": 0, "body_markdown": 0, "faqs": 0}).sort("created_at", -1).to_list(200)


@router.get("/seo/articles/{aid}")
async def get_article(aid: str, user: dict = Depends(require_admin)):
    doc = await db.seo_articles.find_one({"id": aid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Article not found")
    return doc


@router.delete("/seo/articles/{aid}")
async def delete_article(aid: str, user: dict = Depends(require_admin)):
    await db.seo_articles.delete_one({"id": aid})
    return {"ok": True}


# ----------------------- Content SEO audit -----------------------
@router.post("/seo/audit")
async def audit_content(body: SeoAuditReq, user: dict = Depends(require_admin)):
    content = body.content
    if not content and body.article_id:
        art = await db.seo_articles.find_one({"id": body.article_id}, {"_id": 0})
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
    return await _ai_json(system, prompt, f"seo-audit-{user['id']}")


# ----------------------- WordPress connection settings -----------------------
async def _get_wp_settings() -> dict | None:
    return await db.seo_settings.find_one({"id": WP_SETTINGS_ID}, {"_id": 0})


@router.get("/seo/wp-settings")
async def get_wp_settings(user: dict = Depends(require_admin)):
    s = await _get_wp_settings()
    if not s:
        return {"connected": False, "url": "", "username": ""}
    return {
        "connected": bool(s.get("url") and s.get("username") and s.get("app_password")),
        "url": s.get("url", ""),
        "username": s.get("username", ""),
    }


@router.put("/seo/wp-settings")
async def save_wp_settings(body: WpSettingsIn, user: dict = Depends(require_admin)):
    url = body.url.strip().rstrip("/")
    if not url.startswith("http"):
        raise HTTPException(400, "Site URL must start with http:// or https://")
    doc = {
        "id": WP_SETTINGS_ID,
        "url": url,
        "username": body.username.strip(),
        "app_password": body.app_password.strip(),
        "updated_at": now_iso(),
    }
    await db.seo_settings.update_one({"id": WP_SETTINGS_ID}, {"$set": doc}, upsert=True)
    return {"connected": True, "url": doc["url"], "username": doc["username"]}


@router.post("/seo/wp-settings/test")
async def test_wp_settings(user: dict = Depends(require_admin)):
    s = await _get_wp_settings()
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
    s = await _get_wp_settings()
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
async def publish_article(aid: str, body: SeoPublishReq, user: dict = Depends(require_admin)):
    art = await db.seo_articles.find_one({"id": aid}, {"_id": 0})
    if not art:
        raise HTTPException(404, "Article not found")
    try:
        res = await _publish_to_wp(art, body.status)
    except WpError as e:
        raise HTTPException(e.status, e.detail)
    return {"ok": True, "link": res["link"], "wp_post_id": res["wp_post_id"], "status": "published"}


# ----------------------- Scheduling / auto-drip -----------------------
DEFAULT_SCHEDULE = {"enabled": True, "paused": False, "day_of_week": 0, "hour": 9, "minute": 0, "publish_as": "draft"}


async def _get_schedule() -> dict:
    doc = await db.seo_settings.find_one({"id": "schedule"}, {"_id": 0}) or {}
    return {**DEFAULT_SCHEDULE, **{k: v for k, v in doc.items() if k != "id"}}


def _next_weekly_slot(after: datetime, dow: int, hour: int, minute: int) -> datetime:
    """First occurrence of the given weekday/time strictly after `after` (UTC)."""
    days_ahead = (dow - after.weekday()) % 7
    candidate = (after + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=7)
    return candidate


@router.get("/seo/schedule")
async def get_schedule(user: dict = Depends(require_admin)):
    sched = await _get_schedule()
    queued = await db.seo_articles.find(
        {"status": "scheduled"}, {"_id": 0, "body_markdown": 0, "faqs": 0}
    ).sort("scheduled_for", 1).to_list(200)
    return {"settings": sched, "queued": queued}


@router.put("/seo/schedule")
async def update_schedule(body: SeoScheduleSettings, user: dict = Depends(require_admin)):
    doc = {"id": "schedule", **body.model_dump(exclude_none=True)}
    await db.seo_settings.update_one({"id": "schedule"}, {"$set": doc}, upsert=True)
    return await _get_schedule()


@router.post("/seo/articles/{aid}/schedule")
async def schedule_article(aid: str, body: SeoScheduleReq, user: dict = Depends(require_admin)):
    art = await db.seo_articles.find_one({"id": aid}, {"_id": 0})
    if not art:
        raise HTTPException(404, "Article not found")
    sched = await _get_schedule()
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
        # auto weekly drip: one week after the last auto-queued item, else the next weekly slot
        last = await db.seo_articles.find_one(
            {"status": "scheduled", "queue_mode": "auto"},
            {"_id": 0, "scheduled_for": 1}, sort=[("scheduled_for", -1)],
        )
        if last and last.get("scheduled_for"):
            base = datetime.fromisoformat(last["scheduled_for"])
            when = base + timedelta(days=7)
        else:
            when = _next_weekly_slot(now, sched["day_of_week"], sched["hour"], sched["minute"])

    await db.seo_articles.update_one(
        {"id": aid},
        {"$set": {"status": "scheduled", "queue_mode": body.mode, "scheduled_for": when.isoformat()}},
    )
    return {"ok": True, "scheduled_for": when.isoformat(), "mode": body.mode}


@router.post("/seo/articles/{aid}/unschedule")
async def unschedule_article(aid: str, user: dict = Depends(require_admin)):
    art = await db.seo_articles.find_one({"id": aid}, {"_id": 0})
    if not art:
        raise HTTPException(404, "Article not found")
    await db.seo_articles.update_one(
        {"id": aid}, {"$set": {"status": "draft", "scheduled_for": None, "queue_mode": None}}
    )
    return {"ok": True}


async def run_due_publishes():
    """Called by the background scheduler: publish any scheduled articles whose time has arrived."""
    try:
        sched = await _get_schedule()
        if sched.get("paused") or not sched.get("enabled"):
            return
        now = datetime.now(timezone.utc).isoformat()
        due = await db.seo_articles.find(
            {"status": "scheduled", "scheduled_for": {"$lte": now}}, {"_id": 0}
        ).to_list(50)
        for art in due:
            try:
                res = await _publish_to_wp(art, sched.get("publish_as", "draft"))
                await create_staff_notification(
                    "SEO article published",
                    f"'{art.get('title','')}' was auto-published to WordPress ({res['wp_status']}).",
                )
                logger.info(f"Auto-published SEO article {art['id']}")
            except WpError as e:
                logger.warning(f"Auto-publish skipped for {art['id']}: {e.detail}")
                # Leave it scheduled so it retries on the next tick (e.g. WP temporarily unreachable)
    except Exception as e:
        logger.warning(f"run_due_publishes error: {e}")
