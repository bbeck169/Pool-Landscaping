"""Phase 27.2 · Content Refresh Engine.

Scans blog URLs → scores via existing SEO scorer → Claude rewrites the
lowest-ranking pages. Live Claude, no silent mocks.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _fetch_sitemap_urls_sync_ok(root: str, sitemap_url: Optional[str]) -> List[str]:
    """Non-async placeholder — never called directly; kept for parity."""
    return []


async def _extract_urls(base: str, sitemap_url: Optional[str]) -> List[str]:
    urls: List[str] = []
    async with httpx.AsyncClient(timeout=15,
                                     follow_redirects=True) as c:
        target = sitemap_url or f"{base.rstrip('/')}/sitemap.xml"
        try:
            r = await c.get(target)
            if r.status_code == 200 and "<url" in r.text:
                for m in re.finditer(r"<loc>([^<]+)</loc>", r.text):
                    u = m.group(1).strip()
                    if "/blog" in u or "/post" in u or "/article" in u:
                        urls.append(u)
        except Exception as ex:
            logger.warning(f"Sitemap fetch failed: {ex}")
        # Fallback: parse blog index HTML for anchor tags.
        if not urls and base:
            try:
                r = await c.get(base)
                if r.status_code == 200:
                    host = urlparse(base).netloc
                    for m in re.finditer(
                        r'href=[\"\']([^\"\']+)[\"\']', r.text):
                        u = m.group(1)
                        if u.startswith("/"):
                            u = f"{urlparse(base).scheme}://{host}{u}"
                        if host in u and any(k in u for k in
                                                 ("/blog", "/post",
                                                    "/article")):
                            urls.append(u)
            except Exception as ex:
                logger.warning(f"Blog index fetch failed: {ex}")
    seen, uniq = set(), []
    for u in urls:
        if u not in seen: seen.add(u); uniq.append(u)
    return uniq[:20]


def _score_page(html: str, url: str) -> Dict[str, Any]:
    """Simple content quality scorer — mirrors phase 17A intent without
    re-importing (avoids coupling). Returns 0-100."""
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()

    title_m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_m.group(1).strip() if title_m else ""
    meta_m = re.search(
        r'<meta[^>]+name=[\"\']description[\"\'][^>]+content=[\"\']([^\"\']*)[\"\']',
        html, re.I)
    meta = meta_m.group(1).strip() if meta_m else ""
    h1_count = len(re.findall(r"<h1", html, re.I))
    h2_count = len(re.findall(r"<h2", html, re.I))
    word_count = len(plain.split())
    img_count = len(re.findall(r"<img", html, re.I))
    imgs_alt = len(re.findall(
        r'<img[^>]+alt=[\"\'][^\"\']+[\"\']', html, re.I))

    breakdown = {
        "title_present": bool(title),
        "title_length_ok": 30 <= len(title) <= 65,
        "meta_present": bool(meta),
        "meta_length_ok": 70 <= len(meta) <= 165,
        "h1_exactly_one": h1_count == 1,
        "h2_present": h2_count >= 1,
        "word_count": word_count,
        "word_count_ok": word_count >= 400,
        "img_count": img_count,
        "img_alt_ratio": (imgs_alt / img_count) if img_count else 1.0,
    }
    score = 0
    score += 10 if breakdown["title_present"] else 0
    score += 10 if breakdown["title_length_ok"] else 0
    score += 10 if breakdown["meta_present"] else 0
    score += 10 if breakdown["meta_length_ok"] else 0
    score += 15 if breakdown["h1_exactly_one"] else 0
    score += 10 if breakdown["h2_present"] else 0
    score += 20 if breakdown["word_count_ok"] else \
              int(min(20, word_count / 20))
    score += int(10 * breakdown["img_alt_ratio"])
    score = max(0, min(100, score))
    return {"score": score, "breakdown": breakdown,
             "title": title, "meta": meta,
             "word_count": word_count}


class ScanIn(BaseModel):
    sitemap_url: Optional[str] = None
    blog_root_url: Optional[str] = None


@router.post("/seo/content-refresh/scan")
async def content_scan(body: ScanIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    if not (body.sitemap_url or body.blog_root_url):
        raise HTTPException(422,
            "Provide sitemap_url or blog_root_url")
    base = body.blog_root_url or ""
    urls = await _extract_urls(base, body.sitemap_url)
    if not urls:
        raise HTTPException(404,
            "No blog URLs discovered — check sitemap or blog root")
    scored: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        for u in urls:
            try:
                r = await c.get(u)
                if r.status_code != 200:
                    continue
                s = _score_page(r.text, u)
                scored.append({
                    "url": u,
                    "url_hash": _url_hash(u),
                    "score": s["score"],
                    "breakdown": s["breakdown"],
                    "title": s["title"],
                    "meta": s["meta"],
                    "word_count": s["word_count"],
                    "priority": 100 - s["score"],
                })
            except Exception as ex:
                logger.warning(f"Fetch failed for {u}: {ex}")
    scored.sort(key=lambda x: x["score"])
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "sitemap_url": body.sitemap_url,
        "blog_root_url": body.blog_root_url,
        "urls_scored": scored,
        "scanned_at": now_iso(),
        "status": "complete",
    }
    await db.content_refresh_scans.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/seo/content-refresh/scans/{sid}")
async def content_scan_detail(sid: str,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    doc = await db.content_refresh_scans.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc: raise HTTPException(404, "Scan not found")
    return doc


class RewriteIn(BaseModel):
    target_keyword: Optional[str] = None
    tone: Optional[str] = "professional"


_REWRITE_SYSTEM = (
    "You are a senior SEO editor for a pool + landscaping company. "
    "Given the source HTML below, produce an SEO-improved rewrite. "
    "Return STRICT JSON only:\n"
    "{\n"
    '  "title": <str, 50-60 chars>,\n'
    '  "meta_description": <str, 140-160 chars>,\n'
    '  "rewritten_html": <full HTML including <h1>, 2+ <h2>, 400+ words, '
    'well-structured paragraphs, semantic keyword density>,\n'
    '  "diff_summary": <str, human-readable summary of what changed>,\n'
    '  "target_keyword_used": <str>,\n'
    '  "mocked": false\n'
    "}"
)


@router.post("/seo/content-refresh/rewrite/{sid}/{url_hash}")
async def content_rewrite(sid: str, url_hash: str,
                                body: RewriteIn = RewriteIn(),
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    scan = await db.content_refresh_scans.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not scan: raise HTTPException(404, "Scan not found")
    entry = next((e for e in scan["urls_scored"]
                    if e["url_hash"] == url_hash), None)
    if not entry: raise HTTPException(404, "URL not in this scan")

    # Fetch source HTML.
    try:
        async with httpx.AsyncClient(timeout=15,
                                          follow_redirects=True) as c:
            r = await c.get(entry["url"])
        source_html = r.text
    except Exception as ex:
        raise HTTPException(424, f"Could not fetch source: {ex}")

    if not EMERGENT_LLM_KEY:
        result = {"mocked": True,
                    "reason": "EMERGENT_LLM_KEY not configured"}
    else:
        try:
            # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
            # central AI chokepoint so per-tenant BYO keys + AI spend
            # caps apply. Plaintext (``parse_json=False``) preserves
            # the local fenced-block JSON extract logic bit-for-bit.
            from services.llm_provider import call_llm_with_fallback
            from services.ai.cap_http import is_ai_cap_exceeded
            prompt = (
                f"Target keyword: {body.target_keyword or entry['title']}\n"
                f"Tone: {body.tone or 'professional'}\n"
                f"Source URL: {entry['url']}\n"
                f"Source title: {entry['title']}\n"
                f"Source meta: {entry['meta']}\n"
                f"Source score: {entry['score']}/100\n\n"
                f"Source HTML (truncated to 8000 chars):\n"
                f"{source_html[:8000]}"
            )
            llm_result = await call_llm_with_fallback(
                system_prompt=_REWRITE_SYSTEM, user_text=prompt,
                provider="anthropic", model="claude-sonnet-4-6",
                tenant_id=tenant["id"],
                parse_json=False,
            )
            if is_ai_cap_exceeded(llm_result):
                result = {"mocked": True, "reason": "ai_spend_cap_exceeded"}
            elif llm_result.get("error"):
                result = {"mocked": True,
                            "reason": f"llm error: {llm_result.get('error')}"}
            else:
                text = ((llm_result.get("raw") or {}).get("text") or "").strip()
                if text.startswith("```"):
                    text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "",
                                     text).strip()
                try: data = json.loads(text)
                except Exception:
                    m = re.search(r"(\{.*\})", text, re.S)
                    data = json.loads(m.group(1)) if m else {}
                rewritten = data.get("rewritten_html", "")
                re_score = _score_page(
                    f"<html><head><title>{data.get('title','')}</title>"
                    f"<meta name='description' content='{data.get('meta_description','')}'>"
                    f"</head><body>{rewritten}</body></html>",
                    entry["url"])
                result = {
                    "mocked": False,
                    "title": data.get("title"),
                    "meta_description": data.get("meta_description"),
                    "rewritten_html": rewritten,
                    "rewritten_score": re_score["score"],
                    "diff_summary": data.get("diff_summary", ""),
                    "target_keyword_used":
                        data.get("target_keyword_used") or body.target_keyword,
                }
        except Exception as e:
            logger.warning(f"Rewrite LLM failed: {e}")
            result = {"mocked": True, "reason": f"llm error: {e}"}

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "scan_id": sid,
        "source_url": entry["url"],
        "url_hash": url_hash,
        "source_score": entry["score"],
        "rewritten_score": result.get("rewritten_score"),
        "title": result.get("title"),
        "meta_description": result.get("meta_description"),
        "rewritten_html": result.get("rewritten_html"),
        "diff_summary": result.get("diff_summary"),
        "target_keyword": body.target_keyword,
        "tone": body.tone,
        "status": "draft",
        "mocked": result.get("mocked", False),
        "reason": result.get("reason"),
        "created_by": user["id"],
        "created_at": now_iso(),
    }
    await db.content_refresh_rewrites.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/seo/content-refresh/rewrites")
async def list_rewrites(status: Optional[str] = None,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status: q["status"] = status
    rows = await db.content_refresh_rewrites.find(
        q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/seo/content-refresh/rewrites/{rid}/publish-copy")
async def rewrite_publish_copy(rid: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    doc = await db.content_refresh_rewrites.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc: raise HTTPException(404, "Rewrite not found")
    await db.content_refresh_rewrites.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"status": "copied", "copied_at": now_iso()}},
    )
    return {"html": doc.get("rewritten_html"),
             "title": doc.get("title"),
             "meta_description": doc.get("meta_description")}


@router.post("/seo/content-refresh/rewrites/{rid}/mark-published")
async def rewrite_mark_published(rid: str,
                                        user: dict = Depends(require_admin),
                                        tenant: dict = Depends(get_current_tenant)):
    r = await db.content_refresh_rewrites.update_one(
        {"id": rid, "tenant_id": tenant["id"]},
        {"$set": {"status": "published", "published_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Rewrite not found")
    return await db.content_refresh_rewrites.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})
