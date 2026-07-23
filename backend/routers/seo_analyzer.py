"""Feb-2026 · Phase 20 · P3 — Website SEO analyzer.

Fetches an admin-supplied URL (defaulting to
``tenant.business_card.website_url``), parses HTML with BeautifulSoup
and reports an on-page SEO scorecard. No 3rd party SEO service —
purely server-side page inspection.

Score = 100 with weighted deductions per miss. All checks include a
``fix_hint`` string so the UI can render an actionable "how to fix"
section.

Persisted scans (last N=30) → ``seo_scans`` collection for trend
charts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter(tags=["SEO"])

USER_AGENT = "AquaTerraPlatform-SEOAudit/1.0 (+https://aquaterra.com/bot)"
FETCH_TIMEOUT_S = 12.0


class AnalyzeIn(BaseModel):
    url: Optional[str] = None  # falls back to tenant business_card.website_url


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


def _read_website_url(tenant: Dict[str, Any]) -> str:
    settings = tenant.get("settings") or {}
    card = settings.get("business_card") or {}
    return (card.get("website_url") or tenant.get("website_url") or "").strip()


async def _fetch(url: str) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    scheme = parsed.scheme
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT_S, follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        try:
            r = await client.get(url)
        except httpx.HTTPError as e:
            raise HTTPException(400, f"Failed to fetch {url}: {e}")
    final_url = str(r.url)
    return {
        "start_url": url,
        "final_url": final_url,
        "status_code": r.status_code,
        "html": r.text if r.status_code == 200 else "",
        "https_enforced": urlparse(final_url).scheme == "https",
        "scheme": scheme,
    }


def _analyze_html(html: str, base_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    checks: List[Dict[str, Any]] = []

    # ── Title ──
    title = (soup.title.string if soup.title else "") or ""
    title = title.strip()
    if not title:
        checks.append({"key": "title_tag", "ok": False, "weight": 12,
                        "fix_hint": "Add a <title> tag inside <head>. Aim for 50–60 chars including your company name and top service."})
    elif not 20 <= len(title) <= 70:
        checks.append({"key": "title_tag", "ok": False, "weight": 6,
                        "fix_hint": f"Current title is {len(title)} chars. Google truncates around 60 — rewrite in the 20–70 char window."})
    else:
        checks.append({"key": "title_tag", "ok": True, "weight": 0})

    # ── Meta description ──
    meta_desc_el = soup.find("meta", attrs={"name": "description"})
    meta_desc = (meta_desc_el.get("content") if meta_desc_el else "") or ""
    meta_desc = meta_desc.strip()
    if not meta_desc:
        checks.append({"key": "meta_description", "ok": False, "weight": 10,
                        "fix_hint": "Add <meta name=\"description\"> in <head>. 150–160 chars, describe the offer + service area."})
    elif not 80 <= len(meta_desc) <= 170:
        checks.append({"key": "meta_description", "ok": False, "weight": 5,
                        "fix_hint": f"Description is {len(meta_desc)} chars. Sweet spot is 120–160."})
    else:
        checks.append({"key": "meta_description", "ok": True, "weight": 0})

    # ── H1 ──
    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    if len(h1s) == 0:
        checks.append({"key": "h1", "ok": False, "weight": 8,
                        "fix_hint": "Page has no <h1>. Add one clear headline that describes what the page is about."})
    elif len(h1s) > 1:
        checks.append({"key": "h1", "ok": False, "weight": 4,
                        "fix_hint": f"Found {len(h1s)} <h1> tags. Use exactly one primary heading."})
    else:
        checks.append({"key": "h1", "ok": True, "weight": 0})

    # ── Canonical ──
    canonical = soup.find("link", rel="canonical")
    checks.append({
        "key": "canonical_url_present",
        "ok": bool(canonical and canonical.get("href")),
        "weight": 0 if canonical and canonical.get("href") else 3,
        "fix_hint": "Add <link rel=\"canonical\" href=\"...\"> to prevent duplicate-content dilution.",
    })

    # ── JSON-LD LocalBusiness / Organization ──
    ld_kinds: List[str] = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (s.string or s.get_text() or "").strip()
        if not raw:
            continue
        # cheap type detection — regex over the raw JSON blob.
        for m in re.findall(r'"@type"\s*:\s*"([^"]+)"', raw):
            ld_kinds.append(m)
    has_local = any(k in {"LocalBusiness", "Organization", "ProfessionalService"} for k in ld_kinds)
    checks.append({
        "key": "schema_local_business",
        "ok": has_local, "weight": 0 if has_local else 8,
        "detail": ld_kinds,
        "fix_hint": "Add JSON-LD LocalBusiness schema. Include name, address, phone, and openingHours so Google can build the knowledge panel.",
    })

    # ── Open Graph ──
    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_desc = soup.find("meta", attrs={"property": "og:description"})
    og_img = soup.find("meta", attrs={"property": "og:image"})
    ogp_ok = bool(og_title and og_desc and og_img)
    checks.append({
        "key": "open_graph",
        "ok": ogp_ok, "weight": 0 if ogp_ok else 4,
        "detail": {"og:title": bool(og_title), "og:description": bool(og_desc),
                     "og:image": bool(og_img)},
        "fix_hint": "Add og:title, og:description, og:image meta tags so social shares render a rich preview.",
    })

    # ── Image alts ──
    imgs = soup.find_all("img")
    missing_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    checks.append({
        "key": "image_alt",
        "ok": missing_alt == 0,
        "weight": 0 if missing_alt == 0 else min(6, missing_alt),
        "detail": {"images": len(imgs), "missing_alt": missing_alt},
        "fix_hint": f"{missing_alt} image(s) missing alt text. Add descriptive alt for screen readers + Google Images.",
    })

    # ── Word count ──
    text = soup.get_text(" ", strip=True)
    word_count = len(re.findall(r"\w+", text))
    if word_count < 300:
        checks.append({"key": "word_count", "ok": False, "weight": 6,
                        "fix_hint": f"Only {word_count} words. Aim for 500+ on core service pages so Google has ranking signal."})
    else:
        checks.append({"key": "word_count", "ok": True, "weight": 0})

    # ── Internal links ──
    parsed_base = urlparse(base_url)
    internal_links = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        u = urljoin(base_url, href)
        if urlparse(u).netloc == parsed_base.netloc:
            internal_links += 1
    if internal_links < 5:
        checks.append({"key": "internal_links", "ok": False, "weight": 3,
                        "fix_hint": f"Only {internal_links} internal links. Add navigation + contextual links to help Google discover related pages."})
    else:
        checks.append({"key": "internal_links", "ok": True, "weight": 0})

    # ── Mobile viewport ──
    vp = soup.find("meta", attrs={"name": "viewport"})
    checks.append({
        "key": "mobile_viewport",
        "ok": bool(vp), "weight": 0 if vp else 6,
        "fix_hint": "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"> so the page is mobile-usable.",
    })

    # ── Aggregate ──
    total_deduction = sum(int(c.get("weight", 0)) for c in checks if not c.get("ok"))
    score = max(0, 100 - total_deduction)

    # Prioritise fixes by weight desc.
    fixes = sorted(
        [c for c in checks if not c.get("ok")],
        key=lambda c: c.get("weight", 0), reverse=True,
    )

    return {
        "score": score,
        "title": title,
        "meta_description": meta_desc,
        "h1s": h1s,
        "word_count": word_count,
        "internal_link_count": internal_links,
        "image_count": len(imgs),
        "image_alt_missing_count": missing_alt,
        "schema_types": ld_kinds,
        "checks": checks,
        "fixes": fixes,
    }


@router.post("/seo/analyze", operation_id="seo.analyze")
async def analyze(
    body: AnalyzeIn,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_admin(user)
    url = (body.url or "").strip() or _read_website_url(tenant)
    if not url:
        raise HTTPException(400, "No URL configured. Set business_card.website_url or pass ``url``.")
    fetched = await _fetch(url)
    result = {
        "url": fetched["final_url"],
        "start_url": fetched["start_url"],
        "status_code": fetched["status_code"],
        "https_enforced": fetched["https_enforced"],
    }
    if fetched["status_code"] != 200:
        result["error"] = f"Non-200 response: {fetched['status_code']}"
        result["score"] = 0
        result["checks"] = []
        result["fixes"] = []
    else:
        result.update(_analyze_html(fetched["html"], fetched["final_url"]))
        # HTTPS check as a downstream deduction.
        if not fetched["https_enforced"]:
            result["score"] = max(0, int(result.get("score") or 0) - 8)
            result.setdefault("checks", []).append({
                "key": "https", "ok": False, "weight": 8,
                "fix_hint": "Serve the site over HTTPS. Get a free cert via Let's Encrypt or your CDN.",
            })

    scan_doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "url": result["url"],
        "score": int(result.get("score") or 0),
        "run_by_user_id": user.get("id"),
        "run_at": now_iso(),
        "result": {k: v for k, v in result.items() if k != "html"},
    }
    try:
        await db.seo_scans.insert_one(scan_doc)
        # Trim history — keep last 30 per tenant.
        cursor = db.seo_scans.find({"tenant_id": tenant["id"]}, {"_id": 1}).sort("run_at", -1)
        rows = await cursor.to_list(500)
        if len(rows) > 30:
            stale = [r["_id"] for r in rows[30:]]
            await db.seo_scans.delete_many({"_id": {"$in": stale}})
    except Exception as e:
        logger.warning(f"[seo] failed to persist scan: {e}")

    return {**result, "scan_id": scan_doc["id"], "run_at": scan_doc["run_at"]}


@router.get("/seo/scans", operation_id="seo.list")
async def list_scans(
    limit: int = 30,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.seo_scans.find(
        {"tenant_id": tenant["id"]}, {"_id": 0},
    ).sort("run_at", -1).to_list(max(1, min(int(limit or 30), 100)))
    return {"scans": rows, "total": len(rows)}
