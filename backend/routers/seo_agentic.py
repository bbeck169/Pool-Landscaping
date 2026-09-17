"""Phase 17A · Agentic SEO Suite — Foundation Layer.

Ships three modules:
 - 17A.1 · Site Auditor (crawl + score)
 - 17A.2 · Content Scoring + AI outline suggestions
 - 17A.3 · Local-SEO Rank Heatmap (geo grid)

All endpoints are `require_admin` gated — tech + customer roles get 403.
Long-running work (auditor, heatmap) runs off-thread via FastAPI
`BackgroundTasks`; the endpoint returns immediately with the job id.
"""
import asyncio
import json
import math
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 17A.1 · Site Auditor
# ═══════════════════════════════════════════════════════════════════════

class AuditIn(BaseModel):
    url: str
    depth: int = Field(3, ge=1, le=6)
    max_pages: int = Field(50, ge=1, le=200)


# Weight rubric (per-issue severity multiplier).
_SEVERITY_WEIGHTS = {"critical": 3.0, "warning": 1.5, "info": 0.5}

# Issue → sub-score bucket for the tri-score rollup.
_ISSUE_BUCKET = {
    "TITLE_MISSING": ("on_page", "critical"),
    "TITLE_TOO_SHORT": ("on_page", "warning"),
    "TITLE_TOO_LONG": ("on_page", "warning"),
    "META_MISSING": ("on_page", "warning"),
    "META_TOO_SHORT": ("on_page", "info"),
    "META_TOO_LONG": ("on_page", "info"),
    "H1_MISSING": ("on_page", "critical"),
    "H1_MULTIPLE": ("on_page", "warning"),
    "CANONICAL_MISSING": ("technical", "warning"),
    "THIN_CONTENT": ("on_page", "warning"),
    "ALT_LOW_COVERAGE": ("on_page", "warning"),
    "BROKEN_INTERNAL": ("technical", "critical"),
    "BROKEN_EXTERNAL": ("technical", "warning"),
    "DUPLICATE_TITLE": ("on_page", "warning"),
    "DUPLICATE_META": ("on_page", "info"),
    "REDIRECT_CHAIN": ("technical", "warning"),
    "MIXED_CONTENT": ("technical", "critical"),
    "OG_MISSING": ("on_page", "info"),
    "JSONLD_MISSING": ("technical", "info"),
    "SLOW_LCP": ("ux", "warning"),
    "SITEMAP_MISSING": ("technical", "warning"),
    "ROBOTS_MISSING": ("technical", "info"),
}


def _normalize(url: str, base: str) -> str:
    u = urljoin(base, url).split("#", 1)[0]
    return u.rstrip("/")


async def _fetch(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    t0 = time.time()
    try:
        r = await client.get(url, follow_redirects=True, timeout=20.0)
        dt = int((time.time() - t0) * 1000)
        return {
            "url": str(r.url), "status_code": r.status_code,
            "response_time_ms": dt, "history_len": len(r.history),
            "text": r.text if "html" in (r.headers.get("content-type") or "").lower() else "",
            "content_type": r.headers.get("content-type", ""),
        }
    except Exception as e:
        return {"url": url, "status_code": 0, "response_time_ms": 0,
                "history_len": 0, "text": "", "error": str(e)}


def _check_page(page: Dict[str, Any], base_host: str) -> Dict[str, Any]:
    """Return per-page audit record with issues."""
    issues: List[Dict[str, Any]] = []
    text = page.get("text") or ""
    soup = BeautifulSoup(text, "html.parser") if text else None

    # 1. Title
    title = ""
    if soup and soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        issues.append({"code": "TITLE_MISSING", "severity": "critical",
                       "hint": "Add a <title> tag."})
    else:
        if len(title) < 30:
            issues.append({"code": "TITLE_TOO_SHORT", "severity": "warning",
                           "hint": f"Title is {len(title)} chars (target 30-60)."})
        if len(title) > 60:
            issues.append({"code": "TITLE_TOO_LONG", "severity": "warning",
                           "hint": f"Title is {len(title)} chars (target 30-60)."})

    # 2. Meta description
    meta_desc = ""
    if soup:
        m = soup.find("meta", attrs={"name": "description"})
        if m:
            meta_desc = (m.get("content") or "").strip()
    if not meta_desc:
        issues.append({"code": "META_MISSING", "severity": "warning",
                       "hint": "Add <meta name=\"description\">."})
    else:
        if len(meta_desc) < 120:
            issues.append({"code": "META_TOO_SHORT", "severity": "info",
                           "hint": f"Meta desc {len(meta_desc)} chars (target 120-155)."})
        if len(meta_desc) > 155:
            issues.append({"code": "META_TOO_LONG", "severity": "info",
                           "hint": f"Meta desc {len(meta_desc)} chars (target 120-155)."})

    # 3. H1
    h1_count = 0
    if soup:
        h1_count = len(soup.find_all("h1"))
    if h1_count == 0:
        issues.append({"code": "H1_MISSING", "severity": "critical",
                       "hint": "Add exactly one <h1>."})
    elif h1_count > 1:
        issues.append({"code": "H1_MULTIPLE", "severity": "warning",
                       "hint": f"{h1_count} <h1>s — use only one."})

    # 4. Canonical
    canonical = ""
    if soup:
        c = soup.find("link", rel="canonical")
        if c:
            canonical = c.get("href") or ""
    if not canonical:
        issues.append({"code": "CANONICAL_MISSING", "severity": "warning",
                       "hint": "Add a <link rel=\"canonical\">."})

    # 5. Word count / thin content
    word_count = 0
    if soup:
        body_text = soup.get_text(separator=" ", strip=True)
        word_count = len(re.findall(r"\w+", body_text))
    if word_count and word_count < 300:
        issues.append({"code": "THIN_CONTENT", "severity": "warning",
                       "hint": f"Only {word_count} words — target 300+."})

    # 6. Alt coverage
    alt_pct = 100
    if soup:
        imgs = soup.find_all("img")
        if imgs:
            with_alt = sum(1 for i in imgs if (i.get("alt") or "").strip())
            alt_pct = round(100 * with_alt / len(imgs))
    if alt_pct < 90:
        issues.append({"code": "ALT_LOW_COVERAGE", "severity": "warning",
                       "hint": f"Only {alt_pct}% of <img> tags have alt text."})

    # 7. Redirect chain
    if page.get("history_len", 0) > 2:
        issues.append({"code": "REDIRECT_CHAIN", "severity": "warning",
                       "hint": f"{page['history_len']} redirects — collapse the chain."})

    # 8. Mixed content
    if soup and str(page.get("url", "")).startswith("https://"):
        for tag_attr in [("img", "src"), ("script", "src"),
                         ("link", "href"), ("iframe", "src")]:
            for el in soup.find_all(tag_attr[0]):
                href = el.get(tag_attr[1]) or ""
                if href.startswith("http://"):
                    issues.append({"code": "MIXED_CONTENT", "severity": "critical",
                                   "hint": f"http:// resource on HTTPS page: {href[:80]}"})
                    break
            else:
                continue
            break

    # 9. OG tags
    if soup:
        og = soup.find("meta", attrs={"property": "og:title"})
        if not og:
            issues.append({"code": "OG_MISSING", "severity": "info",
                           "hint": "Add Open Graph meta tags."})

    # 10. JSON-LD
    if soup:
        ldjson = soup.find("script", attrs={"type": "application/ld+json"})
        if not ldjson:
            issues.append({"code": "JSONLD_MISSING", "severity": "info",
                           "hint": "Add JSON-LD schema markup."})

    # 11. Slow LCP proxy (response time > 3s)
    if page.get("response_time_ms", 0) > 3000:
        issues.append({"code": "SLOW_LCP", "severity": "warning",
                       "hint": f"Response took {page['response_time_ms']}ms."})

    return {
        "url": page.get("url"),
        "status_code": page.get("status_code", 0),
        "response_time_ms": page.get("response_time_ms", 0),
        "title": title,
        "meta_description": meta_desc,
        "h1_count": h1_count,
        "canonical": canonical,
        "word_count": word_count,
        "alt_coverage_pct": alt_pct,
        "issues": issues,
    }


def _score_audit(page_records: List[Dict[str, Any]], has_sitemap: bool,
                 has_robots: bool) -> Dict[str, Any]:
    """Turn per-page issues + site-wide facts into 3 subscores + overall."""
    penalty = {"technical": 0.0, "on_page": 0.0, "ux": 0.0}
    for rec in page_records:
        for iss in rec.get("issues") or []:
            bucket, sev = _ISSUE_BUCKET.get(iss["code"], ("on_page", "info"))
            penalty[bucket] += _SEVERITY_WEIGHTS.get(sev, 0.5)

    if not has_sitemap:
        penalty["technical"] += _SEVERITY_WEIGHTS["warning"]
    if not has_robots:
        penalty["technical"] += _SEVERITY_WEIGHTS["info"]

    npages = max(1, len(page_records))
    # Normalize to 0-100.
    scores = {}
    for k, p in penalty.items():
        # Higher penalty per page → lower score.
        per_page = p / npages
        # 5 penalty units per page = 0 score; 0 = 100.
        s = max(0.0, 100.0 - per_page * 20.0)
        scores[k] = round(s)
    scores["overall"] = round(
        (scores["technical"] * 0.35 + scores["on_page"] * 0.4 + scores["ux"] * 0.25)
    )
    return scores


async def _run_audit(audit_id: str, tenant_id: str, url: str,
                     depth: int, max_pages: int):
    """Background worker — crawls the site + records the results."""
    started = now_iso()
    await db.seo_audits.update_one(
        {"id": audit_id, "tenant_id": tenant_id},
        {"$set": {"status": "running", "started_at": started}},
    )
    try:
        base = url.rstrip("/")
        base_host = urlparse(base).netloc

        # robots.txt
        has_robots = False
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{urlparse(base).scheme}://{base_host}/robots.txt",
                               timeout=10.0)
                has_robots = r.status_code == 200
        except Exception:
            pass

        # sitemap.xml
        has_sitemap = False
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{urlparse(base).scheme}://{base_host}/sitemap.xml",
                               timeout=10.0)
                has_sitemap = r.status_code == 200
        except Exception:
            pass

        seen: Set[str] = set()
        queue: List[tuple[str, int]] = [(base, 0)]
        seen.add(base)
        results: List[Dict[str, Any]] = []
        titles_seen: Dict[str, str] = {}
        metas_seen: Dict[str, str] = {}

        sem = asyncio.Semaphore(5)

        async with httpx.AsyncClient(
            headers={"User-Agent": "Pool & Landscaping-SEO/1.0"},
            timeout=20.0,
        ) as client:
            while queue and len(results) < max_pages:
                # Check cancellation.
                audit_doc = await db.seo_audits.find_one(
                    {"id": audit_id, "tenant_id": tenant_id},
                    {"_id": 0, "status": 1},
                )
                if audit_doc and audit_doc.get("status") == "cancelled":
                    return

                # Pull up to 5 URLs from the queue for concurrent fetch.
                batch = []
                while queue and len(batch) < 5 and len(results) + len(batch) < max_pages:
                    batch.append(queue.pop(0))

                async def _one(u: str, d: int):
                    async with sem:
                        page = await _fetch(client, u)
                    rec = _check_page(page, base_host)
                    # Track dup title/meta.
                    if rec["title"]:
                        if rec["title"] in titles_seen and titles_seen[rec["title"]] != u:
                            rec["issues"].append({
                                "code": "DUPLICATE_TITLE", "severity": "warning",
                                "hint": f"Duplicate of {titles_seen[rec['title']]}",
                            })
                        titles_seen.setdefault(rec["title"], u)
                    if rec["meta_description"]:
                        if rec["meta_description"] in metas_seen and metas_seen[rec["meta_description"]] != u:
                            rec["issues"].append({
                                "code": "DUPLICATE_META", "severity": "info",
                                "hint": f"Duplicate of {metas_seen[rec['meta_description']]}",
                            })
                        metas_seen.setdefault(rec["meta_description"], u)

                    # Enqueue same-host links.
                    if page.get("text") and d < depth:
                        soup = BeautifulSoup(page["text"], "html.parser")
                        for a in soup.find_all("a", href=True):
                            nx = _normalize(a["href"], u)
                            if nx and urlparse(nx).netloc == base_host and nx not in seen:
                                seen.add(nx)
                                queue.append((nx, d + 1))
                    return rec

                rec_batch = await asyncio.gather(*[_one(u, d) for u, d in batch])
                for rec in rec_batch:
                    rec["audit_id"] = audit_id
                    rec["tenant_id"] = tenant_id
                    rec["id"] = new_id()
                    results.append(rec)

        # Persist per-page records.
        if results:
            await db.seo_audit_pages.insert_many([{**r} for r in results])

        # Score.
        scores = _score_audit(results, has_sitemap, has_robots)
        summary = {
            "pages_crawled": len(results),
            "issues_total": sum(len(r.get("issues") or []) for r in results),
            "scores": scores,
            "has_sitemap": has_sitemap,
            "has_robots": has_robots,
        }
        await db.seo_audits.update_one(
            {"id": audit_id, "tenant_id": tenant_id},
            {"$set": {"status": "done", "finished_at": now_iso(),
                      "summary": summary}},
        )
    except Exception as e:
        logger.exception(f"SEO audit failed: {e}")
        await db.seo_audits.update_one(
            {"id": audit_id, "tenant_id": tenant_id},
            {"$set": {"status": "failed", "finished_at": now_iso(),
                      "error": str(e)}},
        )


@router.post("/seo/audits")
async def start_audit(body: AuditIn, bg: BackgroundTasks,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    audit = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "initiated_by": user["id"],
        "url": body.url,
        "depth": body.depth,
        "max_pages": body.max_pages,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "error": None,
        "created_at": now_iso(),
    }
    await db.seo_audits.insert_one(dict(audit))
    bg.add_task(_run_audit, audit["id"], tenant["id"],
                body.url, body.depth, body.max_pages)
    audit.pop("_id", None)
    return {"audit_id": audit["id"], "status": "queued"}


@router.get("/seo/audits")
async def list_audits(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    return await db.seo_audits.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.get("/seo/audits/{aid}")
async def get_audit(aid: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    a = await db.seo_audits.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not a:
        raise HTTPException(404, "Audit not found")
    return a


@router.get("/seo/audits/{aid}/pages")
async def get_audit_pages(aid: str,
                          limit: int = Query(50, ge=1, le=500),
                          offset: int = Query(0, ge=0),
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q = {"audit_id": aid, "tenant_id": tenant["id"]}
    rows = await db.seo_audit_pages.find(q, {"_id": 0}).skip(offset).limit(limit).to_list(limit)
    total = await db.seo_audit_pages.count_documents(q)
    # 17B polish · standard REST shape: return `items` + total (kept `rows` alias for one release).
    return {"items": rows, "total": total, "offset": offset, "limit": limit,
            "rows": rows}


@router.post("/seo/audits/{aid}/cancel")
async def cancel_audit(aid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.seo_audits.update_one(
        {"id": aid, "tenant_id": tenant["id"],
         "status": {"$in": ["queued", "running"]}},
        {"$set": {"status": "cancelled", "finished_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Audit not found or not cancelable")
    return {"ok": True}


@router.post("/seo/audits/{aid}/rerun")
async def rerun_audit(aid: str, bg: BackgroundTasks,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    a = await db.seo_audits.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not a: raise HTTPException(404, "Audit not found")
    new = {
        **{k: a[k] for k in ("url", "depth", "max_pages")},
        "id": new_id(),
        "tenant_id": tenant["id"],
        "initiated_by": user["id"],
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "summary": None,
        "error": None,
        "created_at": now_iso(),
    }
    await db.seo_audits.insert_one(dict(new))
    bg.add_task(_run_audit, new["id"], tenant["id"],
                a["url"], a["depth"], a["max_pages"])
    return {"audit_id": new["id"], "status": "queued"}


@router.get("/seo/ping")
async def seo_ping(user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    running = await db.seo_audits.count_documents(
        {"tenant_id": tenant["id"], "status": {"$in": ["queued", "running"]}}
    )
    return {
        "ok": True,
        "running_audits": running,
        "timestamp": now_iso(),
        "crawler_available": True,
        "llm_available": bool(EMERGENT_LLM_KEY),
        "serp_provider_available": False,
        "mocked_domains": ["rank_heatmap"],
    }


# ═══════════════════════════════════════════════════════════════════════
# 17A.2 · Content Scoring
# ═══════════════════════════════════════════════════════════════════════

class ContentScoreIn(BaseModel):
    url: Optional[str] = None
    html: Optional[str] = None
    target_keyword: str
    secondary_keywords: Optional[List[str]] = None


class ContentSuggestionsIn(BaseModel):
    topic: str
    target_keyword: str
    existing_html: Optional[str] = None


def _flesch_reading_ease(text: str) -> float:
    """Basic Flesch reading ease (higher = easier)."""
    sentences = max(1, len(re.split(r"[.!?]+", text.strip())))
    words_list = re.findall(r"[A-Za-z][A-Za-z']*", text)
    words = max(1, len(words_list))
    # Approx syllable count: count vowel groups.
    syllables = 0
    for w in words_list:
        syllables += max(1, len(re.findall(r"[aeiouyAEIOUY]+", w)))
    score = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
    return round(max(0.0, min(100.0, score)), 1)


async def _llm_semantic(target: str, sample: str,
                          tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Real Claude call for semantic relevance + short critique."""
    if not EMERGENT_LLM_KEY:
        return {"score": 60, "critique": "LLM key not configured (stub).",
                "mocked": True}
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        prompt = (f"Target keyword: {target}\n\nContent:\n"
                  f"{sample[:4000]}")
        result = await call_llm_with_fallback(
            system_prompt=(
              "You are an SEO editor. Score the semantic "
              "relevance of the content to the target keyword "
              "(0-100) and give a two-sentence critique. "
              "Reply as JSON: {\"score\": int, \"critique\": str}."
            ),
            user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=tenant_id,
            parse_json=False,
        )
        if is_ai_cap_exceeded(result):
            return {"score": 60,
                     "critique": "ai_spend_cap_exceeded (stub).",
                     "mocked": True}
        if result.get("error"):
            raise RuntimeError(str(result.get("error")))
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            out = json.loads(text)
            return {"score": int(out.get("score", 60)),
                    "critique": str(out.get("critique", ""))[:400],
                    "mocked": False}
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            if m:
                out = json.loads(m.group(1))
                return {"score": int(out.get("score", 60)),
                        "critique": str(out.get("critique", ""))[:400],
                        "mocked": False}
            return {"score": 60, "critique": text[:200], "mocked": False}
    except Exception as e:
        logger.warning(f"LLM semantic relevance failed: {e}")
        return {"score": 60, "critique": f"LLM error: {e}", "mocked": True}


@router.post("/seo/content-score")
async def content_score(body: ContentScoreIn,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    if not body.url and not body.html:
        raise HTTPException(400, "Provide either url or html")
    html = body.html or ""
    if body.url and not html:
        try:
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(body.url, follow_redirects=True)
                html = r.text
        except Exception as e:
            raise HTTPException(400, f"Fetch failed: {e}")

    soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup("", "html.parser")
    plain = soup.get_text(separator=" ", strip=True)
    words = re.findall(r"[A-Za-z][A-Za-z']*", plain)
    word_count = len(words)
    target = body.target_keyword.lower().strip()
    lowered_plain = plain.lower()

    # Readability.
    readability = _flesch_reading_ease(plain) if plain else 0.0

    # Keyword density.
    kw_count = lowered_plain.count(target) if target else 0
    kw_density = round(100 * kw_count / max(1, word_count), 2) if target else 0

    # Heading structure.
    h1 = soup.find_all("h1")
    h2 = soup.find_all("h2")
    h3 = soup.find_all("h3")
    heading_ok = (len(h1) == 1 and target in " ".join(t.get_text().lower()
                                                       for t in h1))
    heading_score = 100 if heading_ok else (60 if len(h1) == 1 else 30)

    # Meta.
    title_tag = (soup.title.string or "").strip() if soup.title else ""
    meta_tag = ""
    m = soup.find("meta", attrs={"name": "description"})
    if m: meta_tag = (m.get("content") or "").strip()
    meta_score = 100
    if not title_tag or target not in title_tag.lower(): meta_score -= 40
    if not meta_tag or target not in meta_tag.lower():   meta_score -= 40
    meta_score = max(0, meta_score)

    # Internal links.
    links = soup.find_all("a", href=True)
    internal = [a for a in links if a["href"].startswith("/")
                                   or a["href"].startswith("#")]
    link_score = 100 if len(internal) >= 2 else (60 if len(internal) == 1 else 20)

    # Image alt coverage.
    imgs = soup.find_all("img")
    if imgs:
        with_alt = sum(1 for i in imgs if (i.get("alt") or "").strip())
        alt_pct = round(100 * with_alt / len(imgs))
    else:
        alt_pct = 100

    # Word count.
    if word_count >= 500:    length_score = 100
    elif word_count >= 300:  length_score = 70
    elif word_count >= 150:  length_score = 40
    else:                    length_score = 15

    # Density score.
    if 0.5 <= kw_density <= 2.0:    density_score = 100
    elif kw_density > 0 and kw_density < 3.0: density_score = 70
    elif kw_density >= 3.0:         density_score = 30   # keyword stuffing
    else:                           density_score = 20

    # LLM semantic.
    llm = await _llm_semantic(body.target_keyword,
                              plain[:4000] if plain else html[:4000],
                              tenant_id=tenant["id"])

    breakdown = {
        "readability":         min(100, int(readability)),
        "keyword_density":     density_score,
        "heading_structure":   heading_score,
        "meta":                meta_score,
        "internal_links":      link_score,
        "image_alt":           alt_pct,
        "content_length":      length_score,
        "semantic_relevance":  int(llm.get("score", 60)),
    }
    score = round(sum(breakdown.values()) / len(breakdown))

    recs: List[str] = []
    if breakdown["readability"] < 60:
        recs.append("Simplify sentence structure — target Flesch score 60+.")
    if kw_density == 0:
        recs.append(f"Include the target keyword \"{body.target_keyword}\" at least once in the body.")
    if kw_density > 3.0:
        recs.append("Reduce keyword density — currently overused (looks like stuffing).")
    if len(h1) != 1:
        recs.append("Use exactly one <h1> that includes the target keyword.")
    if word_count < 500:
        recs.append(f"Expand content to 500+ words (currently {word_count}).")
    if not internal or len(internal) < 2:
        recs.append("Add at least 2 internal links to related pages.")
    if imgs and alt_pct < 90:
        recs.append(f"Fill in missing alt text on images ({alt_pct}% coverage today).")
    if llm.get("critique"):
        recs.append(f"AI review: {llm['critique']}")

    return {
        "score": score,
        "breakdown": breakdown,
        "recommendations": recs,
        "mocked": bool(llm.get("mocked")),
        "target_keyword": body.target_keyword,
        "word_count": word_count,
        "kw_density_pct": kw_density,
    }


@router.post("/seo/content-suggestions")
async def content_suggestions(body: ContentSuggestionsIn,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    if not EMERGENT_LLM_KEY:
        return {
            "outline": [
                {"h2": f"What is {body.target_keyword}?"},
                {"h2": f"Benefits of {body.target_keyword}"},
                {"h2": "How to get started"},
            ],
            "internal_links_suggested": [],
            "faq": [],
            "mocked": True,
        }
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        prompt = (f"Topic: {body.topic}\nTarget keyword: {body.target_keyword}\n"
                  f"Existing content excerpt:\n{(body.existing_html or '')[:2000]}")
        result = await call_llm_with_fallback(
            system_prompt=(
                "You are an SEO content strategist. "
                "Return strict JSON: {\"outline\": [{\"h2\": str,"
                " \"points\": [str]}], \"internal_links_suggested\":"
                " [str], \"faq\": [{\"q\": str, \"a\": str}]}. "
                "5-6 H2s, 3 points each, 3 FAQ pairs."
            ),
            user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=tenant["id"],
            parse_json=False,
        )
        if is_ai_cap_exceeded(result):
            raise HTTPException(429, "ai_spend_cap_exceeded")
        if result.get("error"):
            raise RuntimeError(str(result.get("error")))
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            out = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            out = json.loads(m.group(1)) if m else {}
        out["mocked"] = False
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"content-suggestions LLM failed: {e}")
        raise HTTPException(502, f"AI failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 17A.3 · Rank Heatmap
# ═══════════════════════════════════════════════════════════════════════

class RankHeatmapIn(BaseModel):
    keyword: str
    center_lat: float
    center_lng: float
    grid_size: int = Field(5, ge=2, le=9)
    radius_miles: float = Field(5.0, gt=0.0, le=25.0)


def _grid_points(center_lat: float, center_lng: float,
                 grid_size: int, radius_miles: float) -> List[Dict[str, float]]:
    """Generate an equally-spaced lat/lng grid over the radius square."""
    # 1 mile ~= 1/69 lat degree. Longitude scales with cos(lat).
    lat_deg = radius_miles / 69.0
    lng_deg = radius_miles / (69.0 * max(0.1, math.cos(math.radians(center_lat))))
    step = 2.0 / max(1, grid_size - 1)
    out: List[Dict[str, float]] = []
    for i in range(grid_size):
        for j in range(grid_size):
            dy = -1.0 + i * step
            dx = -1.0 + j * step
            out.append({
                "lat": round(center_lat + dy * lat_deg, 6),
                "lng": round(center_lng + dx * lng_deg, 6),
            })
    return out


async def _generate_heatmap(heatmap_id: str, tenant_id: str,
                             keyword: str,
                             center_lat: float, center_lng: float,
                             grid_size: int, radius_miles: float,
                             *, bypass_cache: bool = False):
    """Background heatmap worker.

    Feb-2026 · Rank Heatmap DataForSEO wire-up:
      1. Consult ``heatmap_run_cache`` (6h TTL) for a live result.
      2. On MISS: pull tenant's target domain, generate the grid,
         fire one ``dfs.serp_google_organic_live`` call per point in
         parallel (soft cap 100 points), parse ``rank_position``,
         degrade per-point on error, bump the tenant cost counter,
         cache the result if any point returned real data.
      3. On HIT: return the cached grid unchanged with
         ``served_from_cache=True`` + ``cached_at`` stamps.
      4. If DataForSEO credentials are unset → single flat mocked
         payload with ``mocked_reason="dataforseo_not_configured"``.

    The function signature is preserved except for a new keyword-only
    ``bypass_cache`` flag so ops can force a fresh run.
    """
    started = now_iso()
    await db.seo_rank_heatmaps.update_one(
        {"id": heatmap_id, "tenant_id": tenant_id},
        {"$set": {"status": "running", "started_at": started}},
    )
    try:
        # ── Soft-cap grid size to guard against credit blowout ────
        pts = _grid_points(center_lat, center_lng, grid_size, radius_miles)
        _POINT_CAP = 100
        truncated = False
        if len(pts) > _POINT_CAP:
            logger.warning(
                "[heatmap] tenant=%s keyword=%r grid_size=%d yields "
                "%d points, exceeding the soft cap of %d — "
                "truncating.", tenant_id, keyword, grid_size,
                len(pts), _POINT_CAP,
            )
            pts = pts[:_POINT_CAP]
            truncated = True

        # ── Cache probe ────────────────────────────────────────────
        cache_key = _heatmap_cache_key(
            tenant_id, keyword, center_lat, center_lng,
            radius_miles, grid_size,
        )
        if not bypass_cache:
            cached = await db.heatmap_run_cache.find_one({"key": cache_key},
                                                             {"_id": 0})
            if cached:
                logger.info(
                    "[heatmap] cache HIT tenant=%s keyword=%r key=%s",
                    tenant_id, keyword, cache_key,
                )
                await db.seo_rank_heatmaps.update_one(
                    {"id": heatmap_id, "tenant_id": tenant_id},
                    {"$set": {
                        "status": "done", "finished_at": now_iso(),
                        "points": cached["points"],
                        "avg_rank": cached.get("avg_rank"),
                        "top_position_count": cached.get("top_position_count"),
                        "mocked": cached.get("mocked", False),
                        "mocked_reason": cached.get("mocked_reason"),
                        "served_from_cache": True,
                        "cached_at": cached.get("cached_at"),
                    }},
                )
                return

        # ── DFS credential gate ────────────────────────────────────
        if _dfs.get_credentials_or_none() is None:
            logger.info(
                "[heatmap] DataForSEO not configured — degrading to "
                "mocked payload for tenant=%s keyword=%r",
                tenant_id, keyword,
            )
            await _write_mocked_heatmap(
                heatmap_id, tenant_id, keyword, pts,
                reason="dataforseo_not_configured",
            )
            return

        # ── Pull target domain (tenant business card) ─────────────
        target_domain = await _tenant_target_domain(tenant_id)

        # ── Fire one SERP call per grid point in parallel ─────────
        tasks = [
            _dfs.serp_google_organic_live(keyword, p["lat"], p["lng"])
            for p in pts
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # ── Assemble per-point results, degrade on error ──────────
        results: List[Dict[str, Any]] = []
        real_call_count = 0
        for pt, resp in zip(pts, responses):
            row = _resolve_heatmap_point(pt, resp, target_domain, keyword)
            if not row.get("mocked"):
                real_call_count += 1
            results.append(row)

        real_ranks = [r["rank"] for r in results
                        if not r.get("mocked") and isinstance(r.get("rank"), int)]
        avg = round(sum(real_ranks) / len(real_ranks), 1) if real_ranks else None
        top10 = sum(1 for r in results
                     if isinstance(r.get("rank"), int) and r["rank"] <= 10
                     and not r.get("mocked"))
        top_level_mocked = real_call_count == 0

        # ── Cost telemetry (only count real API calls) ────────────
        if real_call_count:
            await db.tenants.update_one(
                {"id": tenant_id},
                {"$inc": {"metrics.dataforseo_heatmap_calls": real_call_count}},
            )
        logger.info(
            "[heatmap] tenant=%s keyword=%r real_calls=%d/%d truncated=%s "
            "target_domain=%r avg_rank=%s top10=%d",
            tenant_id, keyword, real_call_count, len(pts), truncated,
            target_domain, avg, top10,
        )

        finished = now_iso()
        payload = {
            "status": "done", "finished_at": finished,
            "points": results, "avg_rank": avg,
            "top_position_count": top10,
            "mocked": top_level_mocked,
            "mocked_reason": (
                "All grid points degraded to synthetic ranks — see "
                "per-point ``error`` fields for the DFS reason."
                if top_level_mocked else None
            ),
            "served_from_cache": False,
        }
        await db.seo_rank_heatmaps.update_one(
            {"id": heatmap_id, "tenant_id": tenant_id},
            {"$set": payload},
        )

        # ── Cache write (skip if all points degraded) ─────────────
        if top_level_mocked:
            logger.warning(
                "[heatmap] tenant=%s keyword=%r all points degraded — "
                "skipping cache write so a re-run can pick up recovered "
                "DFS availability sooner than 6h.",
                tenant_id, keyword,
            )
        else:
            await _write_heatmap_cache(
                cache_key, results, avg, top10, finished,
            )
            logger.info(
                "[heatmap] cache WRITE tenant=%s keyword=%r key=%s "
                "expires_in=6h", tenant_id, keyword, cache_key,
            )
    except Exception as e:
        logger.exception(f"heatmap failed: {e}")
        await db.seo_rank_heatmaps.update_one(
            {"id": heatmap_id, "tenant_id": tenant_id},
            {"$set": {"status": "failed", "error": str(e),
                      "finished_at": now_iso()}},
        )


# ─────────────────────────────────────────────────────────────────
# Heatmap DFS helpers (Feb-2026)
# ─────────────────────────────────────────────────────────────────
from services import dataforseo_client as _dfs  # noqa: E402
from datetime import timedelta as _timedelta    # noqa: E402


def _heatmap_cache_key(tenant_id: str, keyword: str,
                        center_lat: float, center_lng: float,
                        radius_miles: float, grid_size: int) -> str:
    """4dp lat/lng rounding (~11m precision) so micro-jitter can't
    bypass the cache. Keyword is trim-lowercased."""
    kw = (keyword or "").strip().lower()
    return (
        f"{tenant_id}|{kw}|{round(center_lat, 4):.4f}|"
        f"{round(center_lng, 4):.4f}|{radius_miles}|{grid_size}"
    )


async def _tenant_target_domain(tenant_id: str) -> Optional[str]:
    """Same pull path as rank_tracker._tenant_center_and_domain —
    kept local to avoid a cross-router import cycle."""
    t = await db.tenants.find_one({"id": tenant_id},
                                     {"_id": 0, "settings.business_card": 1})
    card = ((t or {}).get("settings") or {}).get("business_card") or {}
    website = (card.get("website_url") or "").strip()
    if not website:
        return None
    try:
        netloc = urlparse(website).netloc or website
        return netloc.lower().replace("www.", "").strip("/") or None
    except Exception:
        return None


def _resolve_heatmap_point(pt: Dict[str, float], resp: Any,
                            target_domain: Optional[str],
                            keyword: str) -> Dict[str, Any]:
    """Turn a ``dfs.serp_google_organic_live`` tuple (or Exception)
    into a single grid-point row. Degrades to a per-point mocked
    result on any error — the whole heatmap never fails just because
    one SERP call flinched."""
    if isinstance(resp, Exception):
        status, body, err = 0, None, f"exception: {resp}"
    else:
        status, body, err = resp
    if err:
        # Fall back to a synthetic rank for THIS point only, so the
        # UI has data to render. Deterministic seed = same keyword
        # + coord → same mock rank across re-runs.
        rng = random.Random(f"{keyword}:{pt['lat']}:{pt['lng']}")  # nosec B311
        rank = max(1, min(40, int(rng.gauss(mu=14, sigma=6))))
        return {**pt, "rank": rank, "mocked": True, "error": err,
                 "api_status": status, "top_10_urls": []}
    # Real DFS response — pull our tenant's domain rank + the top-N
    # urls so the UI can show competitors above us.
    detailed = _dfs.parse_serp_ranks_detailed(
        body, [target_domain] if target_domain else [],
    )
    match = (detailed.get(target_domain) if target_domain else None) or {}
    rank_val: Optional[int] = match.get("rank") if isinstance(match, dict) else None
    # Also collect the top-10 SERP URLs from the response for the UI.
    top10_urls: List[str] = []
    tasks_arr = (body or {}).get("tasks") or []
    if tasks_arr:
        first_result = (tasks_arr[0].get("result") or [{}])[0]
        for item in (first_result.get("items") or [])[:10]:
            url = item.get("url")
            if url:
                top10_urls.append(url)
    return {
        **pt,
        "rank": rank_val if isinstance(rank_val, int) else None,
        "mocked": False,
        "top_10_urls": top10_urls,
        "url_found": match.get("url") if isinstance(match, dict) else None,
    }


async def _write_mocked_heatmap(heatmap_id: str, tenant_id: str,
                                  keyword: str, pts: List[Dict[str, float]],
                                  *, reason: str) -> None:
    """Preserves the pre-wire-up mocked shape verbatim so existing
    frontend consumers continue to render."""
    rng = random.Random(f"{tenant_id}:{keyword}")  # nosec B311
    results = []
    for p in pts:
        rank = max(1, min(40, int(rng.gauss(mu=14, sigma=6))))
        results.append({
            **p, "rank": rank, "mocked": True,
            "top_10_urls": [
                f"https://example-{i}.com/{keyword.replace(' ', '-')}"
                for i in range(1, min(11, rank) + 1)
            ][:10],
        })
    avg = round(sum(r["rank"] for r in results) / len(results), 1)
    top10 = sum(1 for r in results if r["rank"] <= 10)
    await db.seo_rank_heatmaps.update_one(
        {"id": heatmap_id, "tenant_id": tenant_id},
        {"$set": {
            "status": "done", "finished_at": now_iso(),
            "points": results, "avg_rank": avg,
            "top_position_count": top10,
            "mocked": True, "mocked_reason": reason,
            "served_from_cache": False,
        }},
    )


async def _write_heatmap_cache(cache_key: str,
                                 points: List[Dict[str, Any]],
                                 avg_rank: Optional[float],
                                 top_position_count: int,
                                 cached_at: str) -> None:
    """Upsert. TTL index on ``expires_at`` is created on module import
    (see ``_ensure_heatmap_cache_index`` below)."""
    now = datetime.now(timezone.utc)
    await db.heatmap_run_cache.update_one(
        {"key": cache_key},
        {"$set": {
            "key": cache_key,
            "points": points,
            "avg_rank": avg_rank,
            "top_position_count": top_position_count,
            "mocked": False,
            "cached_at": cached_at,
            "expires_at": now + _timedelta(hours=6),
        }},
        upsert=True,
    )


async def _ensure_heatmap_cache_index() -> None:
    """Idempotent TTL index setup. Called from server startup."""
    try:
        await db.heatmap_run_cache.create_index(
            "expires_at", expireAfterSeconds=0,
            name="heatmap_run_cache_ttl",
        )
        await db.heatmap_run_cache.create_index(
            "key", unique=True, name="heatmap_run_cache_key_unique",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[heatmap] cache index setup skipped: {exc}")


@router.post("/seo/rank-heatmaps")
async def start_heatmap(body: RankHeatmapIn, bg: BackgroundTasks,
                         bypass_cache: bool = Query(False,
                             description="Force a re-run past the 6h cooldown. "
                                             "Admin route already gates access."),
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    dfs_configured = _dfs.get_credentials_or_none() is not None
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "initiated_by": user["id"],
        "keyword": body.keyword,
        "center": {"lat": body.center_lat, "lng": body.center_lng},
        "grid_size": body.grid_size,
        "radius_miles": body.radius_miles,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "points": [],
        "avg_rank": None,
        "top_position_count": 0,
        # Feb-2026 · reflect the actual DFS config state so callers
        # can hint the user immediately rather than wait for the
        # background job to finish and re-render.
        "mocked": not dfs_configured,
        "mocked_reason": None if dfs_configured else "dataforseo_not_configured",
        "created_at": now_iso(),
    }
    await db.seo_rank_heatmaps.insert_one(dict(doc))
    bg.add_task(_generate_heatmap, doc["id"], tenant["id"],
                body.keyword, body.center_lat, body.center_lng,
                body.grid_size, body.radius_miles,
                bypass_cache=bypass_cache)
    reason = None
    if not dfs_configured:
        reason = "DataForSEO not configured — results will be synthesized."
    return {"heatmap_id": doc["id"], "status": "queued",
             "mocked": not dfs_configured, "reason": reason}


@router.get("/seo/rank-heatmaps")
async def list_heatmaps(user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await db.seo_rank_heatmaps.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.get("/seo/rank-heatmaps/{hid}")
async def get_heatmap(hid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    d = await db.seo_rank_heatmaps.find_one(
        {"id": hid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not d: raise HTTPException(404, "Heatmap not found")
    return d


# ═══════════════════════════════════════════════════════════════════════
# 17B.1 · Topical Map
# ═══════════════════════════════════════════════════════════════════════

class TopicalMapIn(BaseModel):
    seed_keyword: str
    business_context: Optional[str] = None
    depth: int = Field(2, ge=1, le=3)


class GenerateContentIn(BaseModel):
    node_id: str


async def _generate_tree(seed: str, ctx: str) -> Dict[str, Any]:
    """Ask Claude for a hierarchical topic tree. Returns nodes+edges or a stub."""
    if not EMERGENT_LLM_KEY:
        return {"estimated": True, "mocked": True,
                "nodes": [{"id": "root", "title": seed, "intent": "informational",
                           "estimated_search_volume": 1000,
                           "suggested_url_slug": seed.lower().replace(" ", "-"),
                           "parent": None, "level": 0}],
                "edges": []}
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        prompt = f"Seed keyword: {seed}\nBusiness context: {ctx or 'general'}"
        result = await call_llm_with_fallback(
            system_prompt=(
                "You are an SEO strategist. Given a seed keyword, "
                "produce a topical map as strict JSON:\n"
                "{\"nodes\":[{\"id\":str,\"title\":str,"
                "\"intent\":\"informational|commercial|navigational|transactional\","
                "\"estimated_search_volume\":int,\"suggested_url_slug\":str,"
                "\"parent\":str|null,\"level\":int (0=pillar,1=cluster,2=support)}],"
                "\"edges\":[{\"from\":str,\"to\":str}]}. "
                "1 pillar (level 0), 5-8 clusters (level 1), "
                "3-5 supports per cluster (level 2). "
                "Volumes are ROUGH estimates."
            ),
            user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-6",
            parse_json=False,
        )
        if is_ai_cap_exceeded(result):
            return {"estimated": True, "mocked": True,
                     "nodes": [], "edges": [],
                     "error": "ai_spend_cap_exceeded"}
        if result.get("error"):
            raise RuntimeError(str(result.get("error")))
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            tree = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            tree = json.loads(m.group(1)) if m else {"nodes": [], "edges": []}
        tree["estimated"] = True
        tree["mocked"] = False
        return tree
    except Exception as e:
        logger.warning(f"topical-map LLM failed: {e}")
        return {"estimated": True, "mocked": True,
                "nodes": [], "edges": [], "error": str(e)}


@router.post("/seo/topical-maps")
async def create_topical_map(body: TopicalMapIn,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    tree = await _generate_tree(body.seed_keyword, body.business_context or "")
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "seed_keyword": body.seed_keyword,
        "business_context": body.business_context or "",
        "depth": body.depth,
        "tree": {"nodes": tree.get("nodes", []),
                 "edges": tree.get("edges", [])},
        "estimated": True,
        "mocked": bool(tree.get("mocked")),
        "status": "done" if tree.get("nodes") else "failed",
        "error": tree.get("error"),
        "created_at": now_iso(),
    }
    await db.seo_topical_maps.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"map_id": doc["id"], "status": doc["status"],
            "mocked": doc["mocked"], "node_count": len(tree.get("nodes", []))}


@router.get("/seo/topical-maps")
async def list_topical_maps(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    return await db.seo_topical_maps.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.get("/seo/topical-maps/{mid}")
async def get_topical_map(mid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    d = await db.seo_topical_maps.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not d: raise HTTPException(404, "Map not found")
    return d


@router.post("/seo/topical-maps/{mid}/generate-content")
async def generate_node_content(mid: str, body: GenerateContentIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    d = await db.seo_topical_maps.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not d: raise HTTPException(404, "Map not found")
    node = next((n for n in d["tree"].get("nodes", []) if n["id"] == body.node_id), None)
    if not node: raise HTTPException(404, "Node not found in map")
    if not EMERGENT_LLM_KEY:
        return {"mocked": True, "outline": [], "first_draft_html": ""}
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        prompt = (f"Node: {node['title']}\nIntent: {node.get('intent')}\n"
                  f"Pillar keyword: {d['seed_keyword']}")
        result = await call_llm_with_fallback(
            system_prompt=(
                "SEO editor. Given a topic node, return strict JSON "
                "{\"outline\":[{\"h2\":str,\"points\":[str]}],"
                "\"first_draft_html\":str}. 5 H2s, 3 points each, "
                "~500 word HTML draft."
            ),
            user_text=prompt,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=tenant["id"],
            parse_json=False,
        )
        if is_ai_cap_exceeded(result):
            raise HTTPException(429, "ai_spend_cap_exceeded")
        if result.get("error"):
            raise RuntimeError(str(result.get("error")))
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            out = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            out = json.loads(m.group(1)) if m else {}
        out["mocked"] = False
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"AI failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 17B.2 · LLM Visibility Tracker
# ═══════════════════════════════════════════════════════════════════════

class LlmQueryIn(BaseModel):
    query_text: str
    expected_brand: str
    category: Optional[str] = None


class LlmScanIn(BaseModel):
    query_ids: Optional[List[str]] = None


def _configured_engines() -> List[str]:
    """Only list LLM providers we actually have keys for."""
    engines: List[str] = []
    if EMERGENT_LLM_KEY: engines.append("claude")
    # Adapter stubs — will populate once user provides these:
    # if os.environ.get("OPENAI_API_KEY"):      engines.append("openai")
    # if os.environ.get("GEMINI_API_KEY"):      engines.append("gemini")
    # if os.environ.get("PERPLEXITY_API_KEY"):  engines.append("perplexity")
    return engines


@router.post("/seo/llm-visibility/queries")
async def add_tracked_query(body: LlmQueryIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "query_text": body.query_text,
        "expected_brand": body.expected_brand,
        "category": body.category or "general",
        "created_at": now_iso(),
    }
    await db.seo_llm_tracked_queries.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/seo/llm-visibility/queries")
async def list_tracked_queries(user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    return await db.seo_llm_tracked_queries.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)


@router.delete("/seo/llm-visibility/queries/{qid}")
async def delete_tracked_query(qid: str,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    r = await db.seo_llm_tracked_queries.delete_one(
        {"id": qid, "tenant_id": tenant["id"]}
    )
    if r.deleted_count == 0: raise HTTPException(404, "Not found")
    return {"ok": True}


async def _run_query_on_claude(query_text: str, expected_brand: str) -> Dict[str, Any]:
    """Ask Claude the raw query, then a second pass to extract brand mention."""
    if not EMERGENT_LLM_KEY:
        return {"mocked": True, "reason": "no LLM key",
                "raw_response": "", "brand_mentioned": False,
                "position": None, "competitors": [],
                "quote": "", "sentiment": "unknown"}
    # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
    # central AI chokepoint so per-tenant BYO keys + AI spend
    # caps apply. Two-hop (answer + analyze) preserved verbatim.
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import is_ai_cap_exceeded
    # Step 1: raw answer
    r1 = await call_llm_with_fallback(
        system_prompt="You are a helpful assistant. Answer briefly.",
        user_text=query_text,
        provider="anthropic", model="claude-sonnet-4-6",
        parse_json=False,
    )
    if is_ai_cap_exceeded(r1) or r1.get("error"):
        return {"mocked": True,
                "reason": r1.get("error") or "ai_spend_cap_exceeded",
                "raw_response": "", "brand_mentioned": False,
                "position": None, "competitors": [],
                "quote": "", "sentiment": "unknown"}
    raw_text = (r1.get("raw") or {}).get("text") or ""

    # Step 2: analysis
    prompt = (f"Target brand: {expected_brand}\n\nResponse to analyze:\n{raw_text}")
    r2 = await call_llm_with_fallback(
        system_prompt=(
            "Analyze if the target brand appears in the response. "
            "Return strict JSON: {\"brand_mentioned\":bool,"
            "\"position\":int|null (1-based rank in list, else null),"
            "\"competitors\":[str],\"quote\":str,"
            "\"sentiment\":\"positive|neutral|negative\"}."
        ),
        user_text=prompt,
        provider="anthropic", model="claude-sonnet-4-6",
        parse_json=False,
    )
    analysis_text = ((r2.get("raw") or {}).get("text") or "").strip()
    if analysis_text.startswith("```"):
        analysis_text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", analysis_text).strip()
    try:
        parsed = json.loads(analysis_text)
    except Exception:
        m = re.search(r"(\{.*\})", analysis_text, re.S)
        parsed = json.loads(m.group(1)) if m else {}

    return {"mocked": False, "raw_response": raw_text[:4000],
            "brand_mentioned": bool(parsed.get("brand_mentioned")),
            "position": parsed.get("position"),
            "competitors": parsed.get("competitors") or [],
            "quote": (parsed.get("quote") or "")[:300],
            "sentiment": parsed.get("sentiment") or "neutral"}


@router.post("/seo/llm-visibility/scan")
async def scan_llm_visibility(body: LlmScanIn,
                               user: dict = Depends(require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    q_filter: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if body.query_ids: q_filter["id"] = {"$in": body.query_ids}
    queries = await db.seo_llm_tracked_queries.find(
        q_filter, {"_id": 0}
    ).to_list(200)
    if not queries: return {"scan_id": None, "results": [],
                             "engines_configured": _configured_engines(),
                             "engines_scanned": _configured_engines(),
                             "competitors": [],
                             "competitors_mentioned": []}
    scan_id = new_id()
    results = []
    engines = _configured_engines()
    for q in queries:
        for engine in engines:
            if engine != "claude": continue  # only claude wired today
            r = await _run_query_on_claude(q["query_text"], q["expected_brand"])
            competitors = r.get("competitors") or []
            doc = {
                "id": new_id(), "tenant_id": tenant["id"], "scan_id": scan_id,
                "query_id": q["id"], "engine": engine,
                "brand_mentioned": r["brand_mentioned"],
                "position": r.get("position"),
                "competitors": competitors,
                "competitors_mentioned": competitors,  # deprecated alias
                "quote": r.get("quote"), "sentiment": r.get("sentiment"),
                "raw_response": r["raw_response"],
                "mocked": r.get("mocked", False),
                "scanned_at": now_iso(),
            }
            await db.seo_llm_scans.insert_one(dict(doc))
            doc.pop("_id", None)
            results.append(doc)
    # Scan-level aggregate of competitors across all results
    scan_comp_counts: Dict[str, int] = {}
    for res in results:
        for c in res.get("competitors") or []:
            scan_comp_counts[c] = scan_comp_counts.get(c, 0) + 1
    scan_competitors = [{"name": n, "mentions": c}
                          for n, c in sorted(scan_comp_counts.items(),
                                              key=lambda x: -x[1])]
    return {"scan_id": scan_id, "results": results,
            "engines_configured": engines,
            "engines_scanned": engines,  # deprecated alias
            "competitors": scan_competitors,
            "competitors_mentioned": scan_competitors,  # deprecated alias
            "engines_pending": [e for e in ("openai", "gemini", "perplexity")
                                 if e not in engines]}


@router.get("/seo/llm-visibility/scans/{scan_id}")
async def get_scan(scan_id: str,
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    rows = await db.seo_llm_scans.find(
        {"scan_id": scan_id, "tenant_id": tenant["id"]}, {"_id": 0}
    ).to_list(500)
    # Backfill deprecated alias for any docs stored before the polish.
    for r in rows:
        if "competitors_mentioned" not in r:
            r["competitors_mentioned"] = r.get("competitors") or []
    return rows


@router.get("/seo/llm-visibility/dashboard")
async def llm_dashboard(range: str = Query("30d"),
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    days = int(range.rstrip("d")) if range.endswith("d") else 30
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    scans = await db.seo_llm_scans.find(
        {"tenant_id": tenant["id"], "scanned_at": {"$gte": cutoff}},
        {"_id": 0},
    ).to_list(5000)
    total = len(scans)
    mentioned = sum(1 for s in scans if s.get("brand_mentioned"))
    positions = [s["position"] for s in scans
                 if isinstance(s.get("position"), (int, float))]
    avg_pos = round(sum(positions) / max(1, len(positions)), 2) if positions else None
    comp_counts: Dict[str, int] = {}
    for s in scans:
        for c in s.get("competitors") or []:
            comp_counts[c] = comp_counts.get(c, 0) + 1
    top_competitors = sorted(comp_counts.items(), key=lambda x: -x[1])[:10]
    top_competitors_list = [{"name": n, "mentions": c}
                              for n, c in top_competitors]
    # Trend by day
    trend: Dict[str, Dict[str, int]] = {}
    for s in scans:
        day = (s.get("scanned_at") or "")[:10]
        if not day: continue
        trend.setdefault(day, {"total": 0, "mentioned": 0})
        trend[day]["total"] += 1
        if s.get("brand_mentioned"): trend[day]["mentioned"] += 1
    trend_series = [
        {"date": d, "mention_rate":
            round(100 * v["mentioned"] / max(1, v["total"]), 1),
         "total": v["total"]}
        for d, v in sorted(trend.items())
    ]
    mention_rate = round(100 * mentioned / max(1, total), 1)
    engines = _configured_engines()
    return {
        "range": range,
        "total_scans": total,
        # Canonical keys
        "mention_rate_pct": mention_rate,
        "competitors": top_competitors_list,
        "engines_configured": engines,
        # Deprecated aliases (kept for one release)
        "mentions_rate_pct": mention_rate,
        "competitors_mentioned": top_competitors_list,
        "engines_scanned": engines,
        "top_competitors": top_competitors_list,
        "avg_position": avg_pos,
        "trend": trend_series,
    }


# ═══════════════════════════════════════════════════════════════════════
# 17B.3 · Atlas Agent (tool-calling)
# ═══════════════════════════════════════════════════════════════════════

class AtlasChatIn(BaseModel):
    message: str
    conversation_id: Optional[str] = None


_ATLAS_SYSTEM = (
    "You are Atlas, an SEO operations agent. You have these tools:\n"
    " - run_site_audit(url)\n"
    " - score_content(html_or_url, keyword)\n"
    " - generate_topical_map(keyword, business_context?)\n"
    " - generate_rank_heatmap(keyword, lat, lng)\n"
    " - scan_llm_visibility(query_ids?)\n"
    " - list_audits() / list_topical_maps()\n"
    " - get_audit_summary(audit_id)\n"
    "\n"
    "When a user's message clearly maps to a tool, respond with STRICT JSON:\n"
    "{\"tool\":\"<name>\",\"args\":{...},\"assistant\":\"<one-line explanation>\"}\n"
    "Otherwise respond with STRICT JSON:\n"
    "{\"tool\":null,\"assistant\":\"<free-form answer>\"}\n"
    "Never wrap responses in prose, always emit JSON only."
)


async def _atlas_route(message: str, tenant_id: str, user: dict) -> Dict[str, Any]:
    """Ask Claude to pick a tool + args. Then invoke the tool and return
    a rich payload for the FE to render."""
    if not EMERGENT_LLM_KEY:
        return {"assistant": "LLM key not configured.", "tool_calls": [],
                "mocked": True}
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        result = await call_llm_with_fallback(
            system_prompt=_ATLAS_SYSTEM, user_text=message,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=tenant_id,
            parse_json=False,
        )
        if is_ai_cap_exceeded(result):
            return {"assistant": "ai_spend_cap_exceeded — please retry after tenant cap reset.",
                     "tool_calls": [], "mocked": True}
        if result.get("error"):
            raise RuntimeError(str(result.get("error")))
        text = ((result.get("raw") or {}).get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            plan = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            plan = json.loads(m.group(1)) if m else {"tool": None,
                                                     "assistant": text[:400]}
    except Exception as e:
        return {"assistant": f"AI error: {e}", "tool_calls": [], "mocked": False}

    assistant_msg = plan.get("assistant") or ""
    tool_name = plan.get("tool")
    tool_calls = []

    if tool_name and isinstance(tool_name, str):
        args = plan.get("args") or {}
        call = {"name": tool_name, "args": args, "status": "ok", "result": None}
        try:
            if tool_name == "run_site_audit":
                url = args.get("url") or "https://example.com"
                aid = new_id()
                doc = {"id": aid, "tenant_id": tenant_id,
                       "initiated_by": user["id"], "url": url,
                       "depth": 2, "max_pages": 20, "status": "queued",
                       "started_at": None, "finished_at": None,
                       "summary": None, "error": None,
                       "created_at": now_iso()}
                await db.seo_audits.insert_one(dict(doc))
                asyncio.create_task(_run_audit(aid, tenant_id, url, 2, 20))
                call["result"] = {"audit_id": aid, "status": "queued"}
            elif tool_name == "list_audits":
                rows = await db.seo_audits.find(
                    {"tenant_id": tenant_id}, {"_id": 0, "id": 1, "url": 1,
                                                "status": 1, "summary": 1}
                ).sort("created_at", -1).limit(10).to_list(10)
                call["result"] = {"audits": rows}
            elif tool_name == "get_audit_summary":
                aid = args.get("audit_id")
                a = await db.seo_audits.find_one(
                    {"id": aid, "tenant_id": tenant_id}, {"_id": 0}
                )
                call["result"] = a or {"error": "not found"}
            elif tool_name == "generate_topical_map":
                seed = args.get("keyword") or args.get("seed") or ""
                tree = await _generate_tree(seed, args.get("business_context") or "")
                doc = {"id": new_id(), "tenant_id": tenant_id,
                       "created_by": user["id"], "seed_keyword": seed,
                       "business_context": args.get("business_context") or "",
                       "depth": 2, "tree": {"nodes": tree.get("nodes", []),
                                             "edges": tree.get("edges", [])},
                       "estimated": True, "mocked": bool(tree.get("mocked")),
                       "status": "done", "created_at": now_iso()}
                await db.seo_topical_maps.insert_one(dict(doc))
                call["result"] = {"map_id": doc["id"],
                                   "node_count": len(tree.get("nodes", []))}
            elif tool_name == "list_topical_maps":
                rows = await db.seo_topical_maps.find(
                    {"tenant_id": tenant_id},
                    {"_id": 0, "id": 1, "seed_keyword": 1, "created_at": 1}
                ).sort("created_at", -1).limit(10).to_list(10)
                call["result"] = {"maps": rows}
            elif tool_name == "score_content":
                target = args.get("keyword") or args.get("target_keyword") or ""
                url = args.get("url") or args.get("html_or_url") or ""
                html = args.get("html") or ""
                # tiny inline runner
                if url and not html:
                    async with httpx.AsyncClient(timeout=10.0) as c:
                        r = await c.get(url, follow_redirects=True)
                        html = r.text
                soup = BeautifulSoup(html or "", "html.parser")
                plain = soup.get_text(separator=" ", strip=True)
                word_count = len(re.findall(r"[A-Za-z][A-Za-z']*", plain))
                readability = _flesch_reading_ease(plain) if plain else 0.0
                call["result"] = {"score_stub": round(readability),
                                   "word_count": word_count,
                                   "note": "Use /seo/content-score for the full breakdown."}
            elif tool_name == "generate_rank_heatmap":
                kw = args.get("keyword", "")
                lat = float(args.get("lat", 0.0))
                lng = float(args.get("lng", 0.0))
                hid = new_id()
                doc = {"id": hid, "tenant_id": tenant_id,
                       "initiated_by": user["id"], "keyword": kw,
                       "center": {"lat": lat, "lng": lng},
                       "grid_size": 5, "radius_miles": 5.0,
                       "status": "queued", "started_at": None, "finished_at": None,
                       "points": [], "avg_rank": None, "top_position_count": 0,
                       "mocked": True, "mocked_reason": None,
                       "created_at": now_iso()}
                await db.seo_rank_heatmaps.insert_one(dict(doc))
                asyncio.create_task(_generate_heatmap(hid, tenant_id, kw,
                                                       lat, lng, 5, 5.0))
                call["result"] = {"heatmap_id": hid, "status": "queued",
                                   "mocked": True}
            elif tool_name == "scan_llm_visibility":
                # Small default scan (no bulk here).
                qs = await db.seo_llm_tracked_queries.find(
                    {"tenant_id": tenant_id}, {"_id": 0}
                ).to_list(5)
                call["result"] = {"tracked_queries_count": len(qs),
                                   "engines_configured": _configured_engines()}
            else:
                call["status"] = "unknown_tool"
                call["result"] = {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            call["status"] = "error"
            call["result"] = {"error": str(e)}
        tool_calls.append(call)

    return {"assistant": assistant_msg, "tool_calls": tool_calls, "mocked": False}


@router.post("/seo/atlas/chat")
async def atlas_chat(body: AtlasChatIn,
                      user: dict = Depends(require_admin),
                      tenant: dict = Depends(get_current_tenant)):
    conv_id = body.conversation_id or new_id()
    conv = await db.seo_atlas_conversations.find_one(
        {"id": conv_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not conv:
        conv = {"id": conv_id, "tenant_id": tenant["id"],
                "user_id": user["id"], "messages": [],
                "created_at": now_iso(), "last_message_at": now_iso()}
        await db.seo_atlas_conversations.insert_one(dict(conv))

    result = await _atlas_route(body.message, tenant["id"], user)
    now = now_iso()
    user_msg = {"role": "user", "content": body.message, "at": now}
    assistant_msg = {"role": "assistant",
                     "content": result["assistant"],
                     "tool_calls": result.get("tool_calls") or [],
                     "at": now}
    await db.seo_atlas_conversations.update_one(
        {"id": conv_id, "tenant_id": tenant["id"]},
        {"$push": {"messages": {"$each": [user_msg, assistant_msg]}},
         "$set": {"last_message_at": now}},
    )
    return {"conversation_id": conv_id,
            "assistant": assistant_msg,
            "mocked": bool(result.get("mocked"))}


@router.get("/seo/atlas/conversations")
async def list_conversations(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    return await db.seo_atlas_conversations.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "messages": 0}
    ).sort("last_message_at", -1).to_list(100)


@router.get("/seo/atlas/conversations/{cid}")
async def get_conversation(cid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    c = await db.seo_atlas_conversations.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not c: raise HTTPException(404, "Conversation not found")
    return c
