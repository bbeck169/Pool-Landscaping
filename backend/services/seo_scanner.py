"""Phase SEO-A · Feb-2026 — Free on-page SEO scanner.

Pure orchestration + pure parsing helpers. No paid keys. All external
calls go over ``httpx.AsyncClient`` with strict timeouts.

Public entry point: :func:`run_scan(target_url, tenant_id, user_id)`.

Split into small, individually-testable helpers so ``compute_score``,
``parse_on_page``, ``parse_schema_org``, and ``security_headers`` can
each be exercised from unit tests without touching the network.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config import db, logger
from utils import new_id, now_iso

_UA = "EmergentSEOAuditor/1.0 (+https://emergent.dev)"
_TIMEOUT = 15.0
_LINK_TIMEOUT = 5.0
_BROKEN_LINK_CAP = 25
_REDIRECT_CAP = 5
_PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Hostnames/paths that MUST NOT be scanned. We block preview.emergentagent
# domains outright to keep the auditor from accidentally scanning itself
# or any other sibling preview instance.
_BLOCKED_HOSTS_SUFFIX = (
    "localhost", ".local", ".internal",
    "preview.emergentagent.com",
    "emergent.host",
)


# ─── URL validation / SSRF guards ──────────────────────────────────

def normalize_url(url: str) -> str:
    """Return a normalized (scheme, host lowercased, path kept) URL."""
    if not url:
        raise ValueError("empty_url")
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("invalid_url")
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    return f"{parsed.scheme.lower()}://{host}{path}" + (
        f"?{parsed.query}" if parsed.query else "")


def validate_target(url: str) -> None:
    """Reject localhost, private CIDRs, and this app's own preview host.

    Raises :class:`ValueError` with a machine-readable code the router can
    surface as an HTTP 400.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("invalid_host")
    for suf in _BLOCKED_HOSTS_SUFFIX:
        if host == suf or host.endswith(suf):
            raise ValueError("blocked_host")
    try:
        ip = socket.gethostbyname(host)
        ip_obj = ipaddress.ip_address(ip)
        if (ip_obj.is_private or ip_obj.is_loopback
                or ip_obj.is_link_local or ip_obj.is_reserved):
            raise ValueError("private_ip")
    except socket.gaierror as e:
        raise ValueError("dns_error") from e


# ─── Fetch helpers ─────────────────────────────────────────────────

async def fetch_page(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    resp = await client.get(url, headers={"User-Agent": _UA},
                              timeout=_TIMEOUT,
                              follow_redirects=True)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "status": resp.status_code,
        "headers": {k.lower(): v for k, v in resp.headers.items()},
        "html_bytes": resp.content,
        "final_url": str(resp.url),
        "elapsed_ms": elapsed_ms,
    }


# ─── On-page parser ────────────────────────────────────────────────

def _first_meta(soup: BeautifulSoup, name: str) -> Optional[str]:
    """Return first ``<meta>`` value keyed by name or property."""
    m = soup.find("meta", attrs={"name": name})
    if m and m.get("content"):
        return m["content"]
    m = soup.find("meta", attrs={"property": name})
    if m and m.get("content"):
        return m["content"]
    return None


def parse_on_page(html_bytes: bytes, base_url: str) -> Dict[str, Any]:
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_tag = soup.find("title")
    title_val = (title_tag.get_text(strip=True) if title_tag else "") or ""
    title_len = len(title_val)
    title_block: Dict[str, Any] = {
        "present": bool(title_val),
        "length": title_len,
        "value": title_val,
    }
    if not title_val:
        title_block["issue"] = "missing"
    elif title_len > 60:
        title_block["issue"] = f"too_long_{title_len}"
    elif title_len < 10:
        title_block["issue"] = f"too_short_{title_len}"

    # Meta description
    desc = _first_meta(soup, "description") or ""
    desc_len = len(desc)
    desc_block: Dict[str, Any] = {
        "present": bool(desc), "length": desc_len, "value": desc,
    }
    if not desc:
        desc_block["issue"] = "missing"
    elif desc_len < 50:
        desc_block["issue"] = f"too_short_{desc_len}"
    elif desc_len > 160:
        desc_block["issue"] = f"too_long_{desc_len}"

    # H1 / H2
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h1_block: Dict[str, Any] = {"count": len(h1s), "values": h1s[:5]}
    if len(h1s) == 0:
        h1_block["issue"] = "missing"
    elif len(h1s) > 1:
        h1_block["issue"] = f"multiple_{len(h1s)}"
    h2_count = len(soup.find_all("h2"))

    # Canonical
    canonical_tag = soup.find("link", rel=lambda x: x and "canonical" in x)
    canonical_url = canonical_tag.get("href") if canonical_tag else None
    canonical_block: Dict[str, Any] = {
        "present": bool(canonical_url), "url": canonical_url,
    }
    if not canonical_url:
        canonical_block["issue"] = "missing"

    # OG tags
    required_og = ["og:title", "og:description", "og:image"]
    missing_og = [p for p in required_og if not _first_meta(soup, p)]
    og_block: Dict[str, Any] = {
        "present": len(missing_og) == 0,
        "missing": missing_og,
    }
    if missing_og:
        og_block["issue"] = f"missing_{','.join(missing_og)}"

    # Twitter card
    twitter_card = _first_meta(soup, "twitter:card")
    twitter_block: Dict[str, Any] = {"present": bool(twitter_card)}
    if not twitter_card:
        twitter_block["issue"] = "missing"

    # Lang
    html_tag = soup.find("html")
    lang_val = html_tag.get("lang") if html_tag else None
    lang_block = {"present": bool(lang_val), "value": lang_val}

    # Viewport
    viewport = _first_meta(soup, "viewport")
    viewport_block = {"present": bool(viewport), "value": viewport}

    # Robots meta
    robots = _first_meta(soup, "robots") or ""
    robots_block = {
        "value": robots or None,
        "noindex": "noindex" in robots.lower(),
    }

    # Images alt
    imgs = soup.find_all("img")
    missing_alt = sum(1 for i in imgs
                        if not (i.get("alt") or "").strip())

    # Internal links (same-origin only)
    parsed_base = urlparse(base_url)
    base_host = (parsed_base.hostname or "").lower()
    internal_hrefs: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href)
        h = (urlparse(full).hostname or "").lower()
        if h and h == base_host:
            internal_hrefs.append(full)

    # Word count on visible text
    for junk in soup.find_all(["script", "style", "noscript"]):
        junk.decompose()
    text = soup.get_text(separator=" ", strip=True)
    word_count = len(text.split())

    html_size_kb = round(len(html_bytes) / 1024.0, 2)

    return {
        "title": title_block,
        "meta_description": desc_block,
        "h1": h1_block,
        "h2_count": h2_count,
        "canonical": canonical_block,
        "og_tags": og_block,
        "twitter_card": twitter_block,
        "lang_attr": lang_block,
        "viewport": viewport_block,
        "robots_meta": robots_block,
        "images_total": len(imgs),
        "images_missing_alt": missing_alt,
        "internal_link_urls": list(dict.fromkeys(internal_hrefs))[:_BROKEN_LINK_CAP],
        "broken_internal_links": [],
        "html_size_kb": html_size_kb,
        "word_count": word_count,
    }


# ─── schema.org / JSON-LD parser ───────────────────────────────────

def parse_schema_org(html_bytes: bytes) -> Dict[str, Any]:
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("script", attrs={"type": "application/ld+json"})
    types: List[str] = []
    warnings: List[str] = []
    valid_count = 0
    for i, b in enumerate(blocks):
        raw = b.string or b.get_text() or ""
        raw = raw.strip()
        if not raw:
            warnings.append(f"block_{i}_empty")
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            warnings.append(f"block_{i}_parse_error:{e.msg}")
            continue
        valid_count += 1
        for item in (parsed if isinstance(parsed, list) else [parsed]):
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(str(x) for x in t)
    return {
        "blocks_found": len(blocks),
        "types": types,
        "valid": len(blocks) > 0 and valid_count == len(blocks),
        "warnings": warnings,
    }


# ─── Broken link checker ───────────────────────────────────────────

async def check_broken_links(client: httpx.AsyncClient,
                                hrefs: List[str]) -> List[Dict[str, Any]]:
    hrefs = hrefs[:_BROKEN_LINK_CAP]
    if not hrefs:
        return []

    async def _probe(u: str) -> Optional[Dict[str, Any]]:
        try:
            r = await client.head(u, headers={"User-Agent": _UA},
                                     timeout=_LINK_TIMEOUT,
                                     follow_redirects=True)
            if r.status_code == 405 or r.status_code >= 500:
                # Some servers reject HEAD; retry once with GET.
                r = await client.get(u, headers={"User-Agent": _UA},
                                        timeout=_LINK_TIMEOUT,
                                        follow_redirects=True)
            if r.status_code >= 400:
                return {"url": u, "status": r.status_code}
        except Exception as e:  # noqa: BLE001
            return {"url": u, "status": 0, "error": str(e)[:80]}
        return None

    results = await asyncio.gather(*[_probe(u) for u in hrefs])
    return [r for r in results if r is not None]


# ─── PageSpeed Insights ────────────────────────────────────────────

async def fetch_pagespeed(client: httpx.AsyncClient,
                             url: str,
                             strategy: str = "mobile") -> Dict[str, Any]:
    try:
        r = await client.get(_PSI_URL,
                                params={"url": url, "strategy": strategy,
                                          "category": "performance"},
                                timeout=30.0)
        if r.status_code != 200:
            return {"error": f"psi_http_{r.status_code}",
                    "score": None, "lcp_ms": None, "cls": None}
        data = r.json()
        lh = data.get("lighthouseResult", {})
        cats = lh.get("categories", {})
        perf = cats.get("performance", {}) or {}
        score = perf.get("score")
        audits = lh.get("audits", {}) or {}
        lcp = ((audits.get("largest-contentful-paint") or {})
               .get("numericValue"))
        cls = ((audits.get("cumulative-layout-shift") or {})
               .get("numericValue"))
        return {
            "score": int(round(score * 100)) if isinstance(score, (int, float)) else None,
            "lcp_ms": int(lcp) if isinstance(lcp, (int, float)) else None,
            "cls": float(cls) if isinstance(cls, (int, float)) else None,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"psi_exception:{str(e)[:80]}",
                "score": None, "lcp_ms": None, "cls": None}


# ─── robots / sitemap ──────────────────────────────────────────────

async def fetch_robots_and_sitemap(client: httpx.AsyncClient,
                                       base_url: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    async def _fetch(u: str) -> httpx.Response | None:
        try:
            return await client.get(u, headers={"User-Agent": _UA},
                                        timeout=_LINK_TIMEOUT,
                                        follow_redirects=True)
        except Exception:
            return None

    r_robots, r_sitemap = await asyncio.gather(
        _fetch(f"{origin}/robots.txt"),
        _fetch(f"{origin}/sitemap.xml"),
    )

    robots: Dict[str, Any] = {"present": False, "sitemap_ref": False,
                                "disallows_all": False}
    if r_robots is not None and 200 <= r_robots.status_code < 400:
        text = r_robots.text or ""
        robots = {
            "present": True,
            "sitemap_ref": "sitemap:" in text.lower(),
            "disallows_all": bool(
                re.search(r"^\s*User-agent:\s*\*\s*$.*?^\s*Disallow:\s*/\s*$",
                             text, re.IGNORECASE | re.MULTILINE | re.DOTALL)),
        }

    sitemap: Dict[str, Any] = {"present": False, "url_count": None,
                                 "sample_urls": []}
    if r_sitemap is not None and 200 <= r_sitemap.status_code < 400:
        text = r_sitemap.text or ""
        urls = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text)
        sitemap = {
            "present": True,
            "url_count": len(urls),
            "sample_urls": urls[:5],
        }

    return robots, sitemap


# ─── Security headers ──────────────────────────────────────────────

def security_headers(scheme: str, headers: Dict[str, str]) -> Dict[str, Any]:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return {
        "https": scheme.lower() == "https",
        "hsts": "strict-transport-security" in h,
        "x_content_type_options": "x-content-type-options" in h,
        "referrer_policy": "referrer-policy" in h,
        "content_security_policy": "content-security-policy" in h,
    }


# ─── Mobile-friendly heuristic ─────────────────────────────────────

def mobile_friendly_heuristic(html_bytes: bytes,
                                  viewport_present: bool) -> Dict[str, Any]:
    """Google's public MFT endpoint retired its free tier in 2023 —
    we fall back to a heuristic: viewport meta present + no
    deprecated table-layout/frame markup. Reported as a heuristic
    so users don't confuse it with a real Google verdict."""
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    lower = html.lower()
    deprecated_tags = [t for t in ("<frameset", "<applet", "<marquee")
                          if t in lower]
    issues: List[str] = []
    if not viewport_present:
        issues.append("no_viewport_meta")
    for t in deprecated_tags:
        issues.append(f"deprecated_tag:{t.lstrip('<')}")
    return {
        "pass": viewport_present and not deprecated_tags,
        "issues": issues,
        "heuristic": True,
    }


# ─── Score + issue synthesis ───────────────────────────────────────

def compute_score(results: Dict[str, Any]) -> Tuple[int, Dict[str, int]]:
    """Return ``(score_0_to_100, issue_counts)``. See docstring for
    the exact weight table."""
    op = results.get("on_page") or {}
    schema = results.get("schema_org") or {}
    perf = results.get("performance") or {}
    sec = results.get("security") or {}
    robots = results.get("robots_txt") or {}
    sitemap = results.get("sitemap_xml") or {}

    score = 0.0
    critical = 0
    warning = 0
    notice = 0

    # Title (10)
    title = op.get("title") or {}
    if title.get("present") and title.get("length", 0) <= 60:
        score += 10
    else:
        if not title.get("present"):
            critical += 1
        else:
            warning += 1
    # Meta description (10)
    desc = op.get("meta_description") or {}
    if desc.get("present") and 50 <= desc.get("length", 0) <= 160:
        score += 10
    else:
        if not desc.get("present"):
            critical += 1
        else:
            warning += 1
    # H1 (5)
    h1 = op.get("h1") or {}
    if h1.get("count") == 1:
        score += 5
    else:
        if h1.get("count", 0) == 0:
            critical += 1
        else:
            warning += 1
    # Canonical (5)
    if (op.get("canonical") or {}).get("present"):
        score += 5
    else:
        critical += 1
    # OG (5)
    if (op.get("og_tags") or {}).get("present"):
        score += 5
    else:
        warning += 1
    # Viewport (5)
    if (op.get("viewport") or {}).get("present"):
        score += 5
    else:
        notice += 1
    # Image alt coverage (10)
    imgs = int(op.get("images_total") or 0)
    missing = int(op.get("images_missing_alt") or 0)
    if imgs == 0:
        score += 10
    else:
        coverage = max(0.0, 1.0 - (missing / imgs))
        score += 10.0 * coverage
        if missing > 0:
            warning += 1
    # Broken links (10)
    broken = op.get("broken_internal_links") or []
    if not broken:
        score += 10
    else:
        critical += 1
    # schema.org (5)
    types = set(schema.get("types") or [])
    if types & {"LocalBusiness", "Service", "Organization",
                 "ProfessionalService"}:
        score += 5
    else:
        warning += 1
    # HTTPS (5)
    if sec.get("https"):
        score += 5
    else:
        critical += 1
    # PSI mobile (15)
    pm = perf.get("pagespeed_mobile_score")
    if isinstance(pm, int):
        score += 15.0 * (pm / 100.0)
        if pm < 50:
            warning += 1
    # PSI desktop (10)
    pd = perf.get("pagespeed_desktop_score")
    if isinstance(pd, int):
        score += 10.0 * (pd / 100.0)
        if pd < 50:
            notice += 1
    # robots + sitemap (5, both must exist)
    if robots.get("present") and sitemap.get("present"):
        score += 5
    elif robots.get("present") or sitemap.get("present"):
        score += 2.5
        notice += 1
    else:
        notice += 1

    return int(round(min(100, max(0, score)))), {
        "critical": critical,
        "warning": warning,
        "notice": notice,
    }


# ─── Rate limiting (per-user hourly, DB-backed) ───────────────────

async def check_rate_limit(user_id: str, limit_per_hour: int = 5) -> None:
    """Raise ``ValueError('rate_limited')`` if the caller has already
    triggered ``limit_per_hour`` scans in the last 60 minutes.

    Backed by the same ``seo_scans`` collection so the counter survives
    process restarts and works across replicas.
    """
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=1)).isoformat()
    count = await db.seo_scans.count_documents({
        "requested_by_user_id": user_id,
        "requested_at": {"$gte": cutoff},
    })
    if count >= limit_per_hour:
        raise ValueError("rate_limited")


# ─── Orchestrator ─────────────────────────────────────────────────

async def run_scan(target_url: str, tenant_id: str, user_id: str,
                    scan_id: Optional[str] = None) -> Dict[str, Any]:
    """Run a full scan and persist to ``db.seo_scans``. Returns the
    written scan document."""
    scan_id = scan_id or new_id()
    t0 = time.perf_counter()

    # 1. Insert running row first.
    running_doc = {
        "id": scan_id,
        "tenant_id": tenant_id,
        "requested_by_user_id": user_id,
        "requested_at": now_iso(),
        "target_url": target_url,
        "status": "running",
        "results": None,
    }
    await db.seo_scans.insert_one({**running_doc})

    try:
        async with httpx.AsyncClient(max_redirects=_REDIRECT_CAP) as client:
            page = await fetch_page(client, target_url)

            on_page = parse_on_page(page["html_bytes"], target_url)
            schema = parse_schema_org(page["html_bytes"])

            # Concurrent side-fetches.
            broken_task = check_broken_links(client,
                                                on_page["internal_link_urls"])
            psi_mobile_task = fetch_pagespeed(client, target_url, "mobile")
            psi_desktop_task = fetch_pagespeed(client, target_url, "desktop")
            robots_task = fetch_robots_and_sitemap(client, target_url)

            broken, psi_m, psi_d, (robots, sitemap) = await asyncio.gather(
                broken_task, psi_mobile_task, psi_desktop_task, robots_task)

        on_page["broken_internal_links"] = broken
        parsed = urlparse(page["final_url"])
        sec = security_headers(parsed.scheme, page["headers"])
        mobile = mobile_friendly_heuristic(
            page["html_bytes"],
            viewport_present=on_page["viewport"]["present"])

        performance: Dict[str, Any] = {
            "pagespeed_mobile_score": psi_m.get("score"),
            "pagespeed_desktop_score": psi_d.get("score"),
            "lcp_ms": psi_m.get("lcp_ms"),
            "cls": psi_m.get("cls"),
        }
        if psi_m.get("error") or psi_d.get("error"):
            performance["pagespeed_error"] = (
                psi_m.get("error") or psi_d.get("error"))

        results: Dict[str, Any] = {
            "on_page": {k: v for k, v in on_page.items()
                          if k != "internal_link_urls"},
            "schema_org": schema,
            "performance": performance,
            "mobile_friendly": mobile,
            "security": sec,
            "robots_txt": robots,
            "sitemap_xml": sitemap,
        }
        score, issue_count = compute_score(results)
        results["score"] = score
        results["issue_count"] = issue_count

        duration_ms = int((time.perf_counter() - t0) * 1000)
        update = {
            "status": "complete",
            "finished_at": now_iso(),
            "duration_ms": duration_ms,
            "results": results,
        }
        await db.seo_scans.update_one({"id": scan_id}, {"$set": update})
        return {**running_doc, **update}

    except Exception as e:  # noqa: BLE001
        logger.warning(f"[seo_scanner] scan {scan_id} failed: {e}")
        update = {
            "status": "error",
            "finished_at": now_iso(),
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "error_message": str(e)[:400],
        }
        await db.seo_scans.update_one({"id": scan_id}, {"$set": update})
        return {**running_doc, **update}
