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
            headers={"User-Agent": "AquaTerra-SEO/1.0"},
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
    return {"rows": rows, "offset": offset, "limit": limit, "total": total}


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
    return {"running_audits": running, "timestamp": now_iso()}


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


async def _llm_semantic(target: str, sample: str) -> Dict[str, Any]:
    """Real Claude call for semantic relevance + short critique."""
    if not EMERGENT_LLM_KEY:
        return {"score": 60, "critique": "LLM key not configured (stub).",
                "mocked": True}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY,
                        session_id=new_id(),
                        system_message=(
                          "You are an SEO editor. Score the semantic "
                          "relevance of the content to the target keyword "
                          "(0-100) and give a two-sentence critique. "
                          "Reply as JSON: {\"score\": int, \"critique\": str}."
                        )).with_model("anthropic", "claude-sonnet-4-6"))
        prompt = (f"Target keyword: {target}\n\nContent:\n"
                  f"{sample[:4000]}")
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
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
                              plain[:4000] if plain else html[:4000])

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
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY,
                        session_id=new_id(),
                        system_message=(
                            "You are an SEO content strategist. "
                            "Return strict JSON: {\"outline\": [{\"h2\": str,"
                            " \"points\": [str]}], \"internal_links_suggested\":"
                            " [str], \"faq\": [{\"q\": str, \"a\": str}]}. "
                            "5-6 H2s, 3 points each, 3 FAQ pairs."
                        )).with_model("anthropic", "claude-sonnet-4-6"))
        prompt = (f"Topic: {body.topic}\nTarget keyword: {body.target_keyword}\n"
                  f"Existing content excerpt:\n{(body.existing_html or '')[:2000]}")
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try:
            out = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            out = json.loads(m.group(1)) if m else {}
        out["mocked"] = False
        return out
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
                             grid_size: int, radius_miles: float):
    """Background heatmap worker."""
    started = now_iso()
    await db.seo_rank_heatmaps.update_one(
        {"id": heatmap_id, "tenant_id": tenant_id},
        {"$set": {"status": "running", "started_at": started}},
    )
    try:
        pts = _grid_points(center_lat, center_lng, grid_size, radius_miles)
        # Currently no SERP provider configured — flag mocked=true & synthesize
        # deterministically-random ranks around a plausible mid-teen average
        # so the UI has data to render.
        rng = random.Random(f"{tenant_id}:{keyword}")
        results = []
        for p in pts:
            rank = int(rng.gauss(mu=14, sigma=6))
            rank = max(1, min(40, rank))
            results.append({
                **p,
                "rank": rank,
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
                "mocked": True,
                "mocked_reason": "No SERP provider configured — "
                                 "results are synthesized for UI preview.",
            }},
        )
    except Exception as e:
        logger.exception(f"heatmap failed: {e}")
        await db.seo_rank_heatmaps.update_one(
            {"id": heatmap_id, "tenant_id": tenant_id},
            {"$set": {"status": "failed", "error": str(e),
                      "finished_at": now_iso()}},
        )


@router.post("/seo/rank-heatmaps")
async def start_heatmap(body: RankHeatmapIn, bg: BackgroundTasks,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
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
        "mocked": True,
        "mocked_reason": None,
        "created_at": now_iso(),
    }
    await db.seo_rank_heatmaps.insert_one(dict(doc))
    bg.add_task(_generate_heatmap, doc["id"], tenant["id"],
                body.keyword, body.center_lat, body.center_lng,
                body.grid_size, body.radius_miles)
    return {"heatmap_id": doc["id"], "status": "queued", "mocked": True,
            "reason": "No SERP provider configured — results will be synthesized."}


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
