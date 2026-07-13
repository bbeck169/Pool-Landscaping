"""Google Business Profile (Google My Business) management.

Live Google calls require: (1) OAuth Client ID/Secret saved via the Connect screen,
(2) an approved GBP API project, and (3) a connected account (tokens stored after consent).
Until all three exist, endpoints fail gracefully with actionable messages. The AI drafting
helpers (post-from-article, reply-draft) work today via the Emergent LLM key.
"""
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse

from config import db, logger, EMERGENT_LLM_KEY, APP_PUBLIC_URL
from utils import now_iso, new_id, require_admin
from models import (
    GbpSettingsIn, GbpPostIn, GbpReplyIn, GbpAiPostReq, GbpAiReplyReq, GbpBusinessUpdate,
    GbpAutopost, GbpCalendarEdit,
)
from emergentintegrations.llm.chat import LlmChat, UserMessage

router = APIRouter()

SCOPE = "https://www.googleapis.com/auth/business.manage"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
ACCT_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
V4_API = "https://mybusiness.googleapis.com/v4"

CONFIG_ID = "config"
TOKENS_ID = "tokens"


async def _get_config() -> dict | None:
    return await db.gbp_settings.find_one({"id": CONFIG_ID}, {"_id": 0})


async def _get_tokens() -> dict | None:
    return await db.gbp_settings.find_one({"id": TOKENS_ID}, {"_id": 0})


async def _access_token() -> str:
    """Return a valid access token, refreshing if expired. Raises HTTPException if not connected."""
    cfg = await _get_config()
    if not cfg or not (cfg.get("client_id") and cfg.get("client_secret")):
        raise HTTPException(400, "Add your Google OAuth credentials first (Connect tab).")
    tok = await _get_tokens()
    if not tok or not tok.get("access_token"):
        raise HTTPException(400, "Connect your Google Business Profile first (Connect tab).")
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    # refresh
    if not tok.get("refresh_token"):
        raise HTTPException(400, "Google session expired — please reconnect (Connect tab).")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": tok["refresh_token"],
            "grant_type": "refresh_token",
        })
    if r.status_code >= 400:
        raise HTTPException(400, "Could not refresh Google session — please reconnect.")
    d = r.json()
    new = {
        "id": TOKENS_ID,
        "access_token": d["access_token"],
        "refresh_token": tok["refresh_token"],
        "expires_at": time.time() + d.get("expires_in", 3600),
        "updated_at": now_iso(),
    }
    await db.gbp_settings.update_one({"id": TOKENS_ID}, {"$set": new}, upsert=True)
    return new["access_token"]


async def _google_get(url: str, token: str):
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
    return _handle(r)


def _handle(r: httpx.Response):
    if r.status_code == 403:
        raise HTTPException(424, "Google Business Profile API access is not approved for this project yet (403). Apply for access in Google Cloud, then try again.")
    if r.status_code == 401:
        raise HTTPException(400, "Google authorization failed — please reconnect (Connect tab).")
    if r.status_code >= 400:
        raise HTTPException(424, f"Google API error: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        return {}


# ----------------------- OAuth config + connect flow -----------------------
@router.get("/gbp/settings")
async def gbp_settings(user: dict = Depends(require_admin)):
    cfg = await _get_config() or {}
    tok = await _get_tokens()
    suggested = f"{APP_PUBLIC_URL}/api/gbp/callback" if APP_PUBLIC_URL else ""
    return {
        "configured": bool(cfg.get("client_id") and cfg.get("client_secret")),
        "connected": bool(tok and tok.get("access_token")),
        "client_id": cfg.get("client_id", ""),
        "redirect_uri": cfg.get("redirect_uri", suggested),
        "suggested_redirect_uri": suggested,
    }


@router.put("/gbp/settings")
async def save_gbp_settings(body: GbpSettingsIn, user: dict = Depends(require_admin)):
    doc = {
        "id": CONFIG_ID,
        "client_id": body.client_id.strip(),
        "client_secret": body.client_secret.strip(),
        "redirect_uri": body.redirect_uri.strip().rstrip("/"),
        "updated_at": now_iso(),
    }
    await db.gbp_settings.update_one({"id": CONFIG_ID}, {"$set": doc}, upsert=True)
    return {"configured": True, "client_id": doc["client_id"], "redirect_uri": doc["redirect_uri"]}


@router.get("/gbp/auth-url")
async def gbp_auth_url(user: dict = Depends(require_admin)):
    cfg = await _get_config()
    if not cfg or not (cfg.get("client_id") and cfg.get("redirect_uri")):
        raise HTTPException(400, "Save your Client ID, Secret and Redirect URI first.")
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return {"url": f"{AUTH_URL}?{urlencode(params)}"}


@router.get("/gbp/callback")
async def gbp_callback(code: str = "", error: str = ""):
    """Google redirects here after consent. Public (no auth) — Google calls it."""
    if error or not code:
        return HTMLResponse(f"<html><body style='font-family:sans-serif;padding:40px'><h2>Connection cancelled</h2><p>{error or 'No authorization code returned.'}</p></body></html>")
    cfg = await _get_config()
    if not cfg:
        return HTMLResponse("<html><body><h2>Not configured</h2></body></html>")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": cfg["redirect_uri"],
            "grant_type": "authorization_code",
        })
    if r.status_code >= 400:
        logger.warning(f"GBP token exchange failed: {r.text[:300]}")
        return HTMLResponse(f"<html><body style='font-family:sans-serif;padding:40px'><h2>Connection failed</h2><p>{r.text[:300]}</p></body></html>")
    d = r.json()
    await db.gbp_settings.update_one({"id": TOKENS_ID}, {"$set": {
        "id": TOKENS_ID,
        "access_token": d.get("access_token"),
        "refresh_token": d.get("refresh_token"),
        "expires_at": time.time() + d.get("expires_in", 3600),
        "updated_at": now_iso(),
    }}, upsert=True)
    return HTMLResponse("<html><body style='font-family:sans-serif;padding:40px;text-align:center'><h2>✅ Google Business Profile connected</h2><p>You can close this window and return to the app.</p></body></html>")


@router.post("/gbp/disconnect")
async def gbp_disconnect(user: dict = Depends(require_admin)):
    await db.gbp_settings.delete_one({"id": TOKENS_ID})
    return {"ok": True}


# ----------------------- Locations -----------------------
@router.get("/gbp/locations")
async def gbp_locations(user: dict = Depends(require_admin)):
    token = await _access_token()
    accts = await _google_get(f"{ACCT_API}/accounts", token)
    account = (accts.get("accounts") or [{}])[0].get("name")
    if not account:
        return {"account": None, "locations": []}
    read_mask = "name,title,storefrontAddress,phoneNumbers,websiteUri,regularHours"
    locs = await _google_get(f"{INFO_API}/{account}/locations?readMask={read_mask}&pageSize=100", token)
    return {"account": account, "locations": locs.get("locations", [])}


async def _first_location(token: str) -> str | None:
    accts = await _google_get(f"{ACCT_API}/accounts", token)
    account = (accts.get("accounts") or [{}])[0].get("name")
    if not account:
        return None
    locs = await _google_get(f"{INFO_API}/{account}/locations?readMask=name,title&pageSize=1", token)
    ls = locs.get("locations") or []
    return ls[0]["name"] if ls else None


async def _do_publish_post(token: str, location: str, summary: str, cta_url: str | None, action_type: str = "LEARN_MORE"):
    post: dict = {"languageCode": "en-US", "summary": summary, "topicType": "STANDARD"}
    if cta_url:
        post["callToAction"] = {"actionType": action_type or "LEARN_MORE", "url": cta_url}
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{V4_API}/{location}/localPosts", headers={"Authorization": f"Bearer {token}"}, json=post)
    return _handle(r)


# ----------------------- Local posts -----------------------
@router.post("/gbp/posts")
async def gbp_create_post(body: GbpPostIn, user: dict = Depends(require_admin)):
    token = await _access_token()
    return await _do_publish_post(token, body.location, body.summary, body.cta_url, body.action_type)


@router.get("/gbp/posts")
async def gbp_list_posts(location: str, user: dict = Depends(require_admin)):
    token = await _access_token()
    return await _google_get(f"{V4_API}/{location}/localPosts", token)


# ----------------------- Reviews -----------------------
@router.get("/gbp/reviews")
async def gbp_reviews(location: str, user: dict = Depends(require_admin)):
    token = await _access_token()
    return await _google_get(f"{V4_API}/{location}/reviews", token)


@router.put("/gbp/reviews/reply")
async def gbp_reply(body: GbpReplyIn, user: dict = Depends(require_admin)):
    token = await _access_token()
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.put(f"{V4_API}/{body.review_name}/reply", headers={"Authorization": f"Bearer {token}"}, json={"comment": body.comment})
    return _handle(r)


# ----------------------- Business info -----------------------
@router.patch("/gbp/business")
async def gbp_update_business(body: GbpBusinessUpdate, user: dict = Depends(require_admin)):
    token = await _access_token()
    fields = []
    payload: dict = {}
    if body.phone is not None:
        payload["phoneNumbers"] = {"primaryPhone": body.phone}
        fields.append("phoneNumbers")
    if body.website is not None:
        payload["websiteUri"] = body.website
        fields.append("websiteUri")
    if body.regular_hours is not None:
        payload["regularHours"] = body.regular_hours
        fields.append("regularHours")
    if not fields:
        raise HTTPException(400, "Nothing to update.")
    mask = ",".join(fields)
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.patch(
            f"{INFO_API}/{body.location}?updateMask={mask}",
            headers={"Authorization": f"Bearer {token}"}, json=payload,
        )
    return _handle(r)


# ----------------------- AI drafting (works today) -----------------------
async def _ai_text(system: str, prompt: str, session: str) -> str:
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "AI is not configured")
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session, system_message=system).with_model("anthropic", "claude-sonnet-4-6")
    raw = await chat.send_message(UserMessage(text=prompt))
    return (raw if isinstance(raw, str) else str(raw)).strip()


async def _draft_post_from_article(art: dict, session: str) -> str:
    system = (
        "You write short, engaging Google Business Profile posts for a pool & landscaping company in Vistancia, Arizona. "
        "Keep it under 1400 characters, friendly and local, with 1-2 relevant emojis and a soft call to action. Return only the post text."
    )
    prompt = (
        f"Turn this blog article into a concise Google Business Profile update post.\n"
        f"Title: {art.get('title','')}\nSummary: {art.get('meta_description','')}\n"
        f"Content excerpt: {art.get('body_markdown','')[:1500]}"
    )
    text = await _ai_text(system, prompt, session)
    return text[:1490]


@router.post("/gbp/ai/post-from-article")
async def ai_post_from_article(body: GbpAiPostReq, user: dict = Depends(require_admin)):
    art = await db.seo_articles.find_one({"id": body.article_id}, {"_id": 0})
    if not art:
        raise HTTPException(404, "Article not found")
    text = await _draft_post_from_article(art, f"gbp-post-{user['id']}")
    return {"summary": text, "cta_url": art.get("wp_link", "")}


@router.post("/gbp/ai/reply-draft")
async def ai_reply_draft(body: GbpAiReplyReq, user: dict = Depends(require_admin)):
    system = (
        "You draft professional, warm replies to Google reviews for a pool & landscaping company. "
        "Be gracious, personal, under 700 characters, and never fabricate specifics. Return only the reply text."
    )
    prompt = (
        f"Draft a reply to this {body.rating}-star review from {body.reviewer_name or 'a customer'}:\n"
        f"\"{body.review_text or '(no comment)'}\""
    )
    text = await _ai_text(system, prompt, f"gbp-reply-{user['id']}")
    return {"comment": text[:700]}


# ----------------------- Content calendar / auto-post -----------------------
AUTOPOST_ID = "autopost"


async def _autopost_enabled() -> bool:
    doc = await db.gbp_settings.find_one({"id": AUTOPOST_ID}, {"_id": 0})
    return True if doc is None else bool(doc.get("enabled", True))


@router.get("/gbp/autopost")
async def get_autopost(user: dict = Depends(require_admin)):
    return {"enabled": await _autopost_enabled()}


@router.put("/gbp/autopost")
async def set_autopost(body: GbpAutopost, user: dict = Depends(require_admin)):
    await db.gbp_settings.update_one({"id": AUTOPOST_ID}, {"$set": {"id": AUTOPOST_ID, "enabled": body.enabled}}, upsert=True)
    return {"enabled": body.enabled}


@router.get("/gbp/calendar")
async def gbp_calendar(user: dict = Depends(require_admin)):
    return await db.gbp_posts.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.patch("/gbp/calendar/{pid}")
async def gbp_calendar_edit(pid: str, body: GbpCalendarEdit, user: dict = Depends(require_admin)):
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if patch:
        await db.gbp_posts.update_one({"id": pid}, {"$set": patch})
    doc = await db.gbp_posts.find_one({"id": pid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.delete("/gbp/calendar/{pid}")
async def gbp_calendar_delete(pid: str, user: dict = Depends(require_admin)):
    await db.gbp_posts.delete_one({"id": pid})
    return {"ok": True}


@router.post("/gbp/calendar/{pid}/publish")
async def gbp_calendar_publish(pid: str, user: dict = Depends(require_admin)):
    rec = await db.gbp_posts.find_one({"id": pid}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Not found")
    token = await _access_token()
    loc = await _first_location(token)
    if not loc:
        raise HTTPException(424, "No Google Business location found on this account.")
    res = await _do_publish_post(token, loc, rec["summary"], rec.get("cta_url"))
    await db.gbp_posts.update_one({"id": pid}, {"$set": {
        "status": "published", "google_post_name": res.get("name"), "published_at": now_iso(),
    }})
    return {"ok": True, "google_post_name": res.get("name")}


async def auto_gbp_from_article(article: dict):
    """Best-effort: when an SEO article publishes, AI-draft a GBP post and (if connected) publish it live.
    Otherwise store it as a draft in the content calendar so nothing is lost."""
    try:
        if not await _autopost_enabled():
            return
        # Skip if we already generated one for this article
        if await db.gbp_posts.find_one({"article_id": article.get("id")}):
            return
        summary = await _draft_post_from_article(article, f"gbp-auto-{article.get('id')}")
        rec = {
            "id": new_id(),
            "article_id": article.get("id"),
            "article_title": article.get("title", ""),
            "summary": summary,
            "cta_url": article.get("wp_link", ""),
            "status": "draft",
            "google_post_name": None,
            "created_at": now_iso(),
        }
        # Try to publish immediately if GBP is connected + approved
        try:
            token = await _access_token()
            loc = await _first_location(token)
            if loc:
                res = await _do_publish_post(token, loc, summary, rec["cta_url"])
                rec["status"] = "published"
                rec["google_post_name"] = res.get("name")
                rec["published_at"] = now_iso()
        except HTTPException:
            pass  # not connected / not approved -> keep as draft in calendar
        except Exception as e:
            logger.warning(f"auto GBP publish skipped: {e}")
        await db.gbp_posts.insert_one(rec)
        logger.info(f"Auto GBP post created for article {article.get('id')} (status={rec['status']})")
    except Exception as e:
        logger.warning(f"auto_gbp_from_article error: {e}")



# ─── Phase 8 additions ──────────────────────────────────────────────────────
@router.get("/gbp/status")
async def gbp_status(user: dict = Depends(require_admin)):
    """Lightweight connection-state probe for the UI."""
    cfg = await _get_config()
    tokens = await db.gbp_settings.find_one({"id": TOKENS_ID}, {"_id": 0}) or {}
    has_client = bool(cfg and cfg.get("client_id") and cfg.get("redirect_uri"))
    has_tokens = bool(tokens.get("access_token"))
    return {
        "connected": bool(has_client and has_tokens),
        "credentials_configured": has_client,
        "has_tokens": has_tokens,
        "message": (
            "Not connected — configure OAuth credentials in Business Info first."
            if not has_client else
            "Credentials saved but Google consent not granted yet — click 'Connect'."
            if not has_tokens else
            "Connected to Google Business Profile."
        ),
    }


@router.get("/gbp/oauth/auth-url")
async def gbp_oauth_auth_url(user: dict = Depends(require_admin)):
    """Alias for /gbp/auth-url with friendly 424 when creds absent (for UI)."""
    cfg = await _get_config()
    if not cfg or not (cfg.get("client_id") and cfg.get("redirect_uri")):
        raise HTTPException(424, "GBP not connected — save Client ID, Secret and Redirect URI first.")
    return await gbp_auth_url(user)


@router.post("/gbp/oauth/callback")
async def gbp_oauth_callback_post(code: str = "", error: str = ""):
    """POST alias for the OAuth callback (browser-side)."""
    return await gbp_callback(code=code, error=error)
