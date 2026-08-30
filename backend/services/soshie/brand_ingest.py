"""Soshie · Brand-brain website ingest · Feb-2026.

Shallow crawl of the tenant's own website (home + up to 12
internal pages), distills bullets into ``brand_brain.talking_points``.
Append-only, admin-editable, dedup-safe.

Reuses ``services.seo_scanner.fetch_page`` for the fetch step so
SSRF guards + timeout + user-agent stay consistent with the SEO
Suite. No new HTTP dependencies here beyond ``httpx.AsyncClient``.

Two public entry points:

* :func:`ingest_website` — orchestrator. Fetches, parses, stores,
  merges into brand_brain. Returns a summary dict for the API.
* :func:`preview_website` — dry-run for the frontend "Preview
  before commit" button (Phase 9 stretch).

Persistence:
    * ``db.brand_brain_ingested_pages`` — one row per URL crawled.
      Fields: id, tenant_id, url, title, h1, h2s[], h3s[], cta_texts[],
      about_paragraphs[], ingested_at.
    * ``db.brand_brain.talking_points`` — merged with dedup. NEVER
      overwritten; admins can delete individual bullets via the
      existing ``PATCH /ai-employees/brand-brain`` endpoint.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urldefrag, urlparse

import httpx
from bs4 import BeautifulSoup

from config import db, logger
from utils import new_id, now_iso
from services.seo_scanner import fetch_page, normalize_url

# Crawl caps — small so a single ingest can't run away.
_MAX_INTERNAL_PAGES = 12
_MAX_PAGES_TOTAL = 13  # home + 12
_CTA_KEYWORDS = (
    "get a quote", "get quote", "book now", "call now", "call us",
    "contact us", "request", "schedule", "get started", "learn more",
    "estimate", "consultation", "free quote", "book service",
)
# H-tag length cap so a giant hero doesn't blow the budget.
_HEADING_MAX = 120
# How many bullets we distill per page — hard cap so a large site
# doesn't 10x the brand_brain size.
_BULLETS_PER_PAGE = 3
# Total bullets contributed per ingest, across all pages.
_BULLETS_PER_INGEST = 15


def _internal_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Return unique in-domain links from the page."""
    base = urlparse(base_url)
    out: List[str] = []
    seen: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:",
                                          "javascript:", "#")):
            continue
        absu = urljoin(base_url, href)
        absu, _ = urldefrag(absu)
        parsed = urlparse(absu)
        if parsed.netloc != base.netloc:
            continue
        # Skip common asset paths.
        if any(parsed.path.lower().endswith(ext)
                for ext in (".pdf", ".jpg", ".png", ".webp",
                             ".mp4", ".zip")):
            continue
        if absu in seen:
            continue
        seen.add(absu)
        out.append(absu)
    return out


def _text(el) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def parse_page(html_bytes: bytes, url: str) -> Dict[str, Any]:
    """Pure parser — extracts brand-relevant fields from the HTML
    of a single page. Isolated so unit tests can drive it with a
    fixture blob without touching the network."""
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")

    title = _text(soup.find("title"))[:200]
    h1 = _text(soup.find("h1"))[:_HEADING_MAX]
    h2s = [_text(t)[:_HEADING_MAX] for t in soup.find_all("h2")][:10]
    h3s = [_text(t)[:_HEADING_MAX] for t in soup.find_all("h3")][:10]
    # Distinct de-dup — case-insensitive.
    h2s = _uniq_ci([s for s in h2s if s])
    h3s = _uniq_ci([s for s in h3s if s])

    # About-paragraph heuristic — first non-trivial <p> under the
    # first h2/h3 that mentions "about" or "who we are", falling
    # back to the first 2 paragraphs > 40 chars.
    about: List[str] = []
    section_hits: List[str] = []
    for hdr in soup.find_all(["h1", "h2", "h3"]):
        htxt = _text(hdr).lower()
        if any(k in htxt for k in
                ("about", "who we are", "our story", "why us",
                 "our mission", "our team")):
            sib = hdr.find_next_sibling("p")
            if sib:
                p = _text(sib)
                if len(p) > 40:
                    section_hits.append(p[:400])
    about = _uniq_ci(section_hits)[:2]
    if not about:
        # Fallback — first 2 substantial paragraphs.
        for p in soup.find_all("p"):
            txt = _text(p)
            if len(txt) > 60 and len(about) < 2:
                about.append(txt[:400])
    about = _uniq_ci(about)

    # CTAs — text of buttons + anchors whose text matches a CTA
    # keyword. Deduped, capped.
    ctas: List[str] = []
    for el in soup.find_all(["a", "button"]):
        t = _text(el)
        if not t or len(t) > 60:
            continue
        low = t.lower()
        if any(k in low for k in _CTA_KEYWORDS):
            ctas.append(t)
    ctas = _uniq_ci(ctas)[:8]

    # Service list — anchors under a nav whose text is 2-4 words,
    # non-generic. Rough heuristic — we don't need every service,
    # just the top 5-8 the site emphasizes.
    services: List[str] = []
    for nav in soup.find_all(["nav", "ul"]):
        for a in nav.find_all("a"):
            t = _text(a)
            w = t.split()
            if 2 <= len(w) <= 4 and 3 <= len(t) <= 40 \
                    and not any(k in t.lower() for k in
                                 ("home", "contact", "about",
                                  "blog", "menu")):
                services.append(t)
    services = _uniq_ci(services)[:8]

    return {
        "title": title, "h1": h1, "h2s": h2s, "h3s": h3s,
        "about_paragraphs": about, "cta_texts": ctas,
        "service_hints": services,
    }


def _uniq_ci(items: List[str]) -> List[str]:
    """Case-insensitive dedup that preserves first-seen ordering."""
    seen: Set[str] = set()
    out: List[str] = []
    for s in items:
        k = s.lower().strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(s.strip())
    return out


def distill_bullets(pages: List[Dict[str, Any]]) -> List[str]:
    """Convert per-page parse output into brand-brain talking-point
    bullets. Deterministic — same input produces same output."""
    bullets: List[str] = []
    # 1. Service hints from the home page (page[0]) — highest value.
    if pages:
        for svc in (pages[0].get("service_hints") or [])[:5]:
            bullets.append(f"We offer: {svc}")
    # 2. About paragraphs from any page.
    for p in pages:
        for para in (p.get("about_paragraphs") or [])[:1]:
            # Distill: keep first sentence only.
            sent = re.split(r"(?<=[.!?])\s+", para)[0]
            if len(sent) > 30:
                bullets.append(f"About: {sent}")
    # 3. Distinct CTA phrases — reveals how the brand asks for
    # business.
    cta_seen: Set[str] = set()
    for p in pages:
        for cta in (p.get("cta_texts") or [])[:2]:
            k = cta.lower()
            if k not in cta_seen:
                cta_seen.add(k)
                bullets.append(f"CTA style: '{cta}'")
    # 4. Top h2 headings — reveals content pillars.
    h2_seen: Set[str] = set()
    for p in pages[:3]:  # only home + first 2 internals
        for h in (p.get("h2s") or [])[:_BULLETS_PER_PAGE]:
            k = h.lower()
            if k in h2_seen or len(h) < 10:
                continue
            h2_seen.add(k)
            bullets.append(f"Section: {h}")
    return _uniq_ci(bullets)[:_BULLETS_PER_INGEST]


async def _merge_into_brand_brain(tenant_id: str,
                                     new_bullets: List[str]) -> Dict[str, Any]:
    """Append-only merge into ``brand_brain.talking_points``.
    Never removes existing points. Case-insensitive dedup against
    what's already there. Returns diff stats."""
    row = await db.brand_brain.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "talking_points": 1})
    existing = list(row.get("talking_points") or []) if row else []
    existing_ci = {s.lower().strip() for s in existing}
    added: List[str] = []
    for b in new_bullets:
        k = b.lower().strip()
        if k and k not in existing_ci:
            added.append(b)
            existing_ci.add(k)
    if not added:
        return {"added": 0, "existing": len(existing)}
    merged = existing + added
    await db.brand_brain.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"talking_points": merged, "updated_at": now_iso()}},
        upsert=True,
    )
    return {"added": len(added), "existing": len(existing)}


async def ingest_website(tenant_id: str, website_url: str,
                             *, user_id: Optional[str] = None,
                             max_pages: int = _MAX_PAGES_TOTAL) -> Dict[str, Any]:
    """Crawl + parse + persist + brand-brain merge.

    Returns summary::
        {"pages_fetched": N, "bullets_added": N, "urls": [...]}
    """
    root = normalize_url(website_url)
    max_pages = min(max_pages, _MAX_PAGES_TOTAL)
    pages: List[Dict[str, Any]] = []
    visited: Set[str] = set()

    async with httpx.AsyncClient() as client:
        try:
            first = await fetch_page(client, root)
        except Exception as e:                                    # noqa: BLE001
            logger.warning("[brand_ingest] home fetch failed %s: %s",
                              root, e)
            return {"pages_fetched": 0, "bullets_added": 0,
                     "urls": [], "error": str(e)[:200]}
        visited.add(root)
        pages.append({"url": root, **parse_page(first["html_bytes"], root)})

        # Discover internal links from the home page only — keeps
        # the crawl shallow and predictable.
        soup = BeautifulSoup(
            first["html_bytes"].decode("utf-8", errors="replace"),
            "html.parser",
        )
        internal = _internal_links(soup, root)

        for url in internal:
            if len(pages) >= max_pages:
                break
            if url in visited:
                continue
            try:
                p = await fetch_page(client, url)
            except Exception as e:                                # noqa: BLE001
                logger.info("[brand_ingest] page skip %s: %s", url, e)
                continue
            visited.add(url)
            pages.append({"url": url, **parse_page(p["html_bytes"], url)})

    # Persist per-page ingested rows.
    ingested_at = now_iso()
    for p in pages:
        row = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "url": p["url"],
            "title": p.get("title"),
            "h1": p.get("h1"),
            "h2s": p.get("h2s") or [],
            "h3s": p.get("h3s") or [],
            "about_paragraphs": p.get("about_paragraphs") or [],
            "cta_texts": p.get("cta_texts") or [],
            "service_hints": p.get("service_hints") or [],
            "ingested_at": ingested_at,
            "ingested_by_user_id": user_id,
        }
        try:
            await db.brand_brain_ingested_pages.insert_one(row)
        except Exception as e:                                    # noqa: BLE001
            logger.info(
                "[brand_ingest] ingested_pages insert failed %s: %s",
                p["url"], e)

    # Distill + merge.
    bullets = distill_bullets(pages)
    merge = await _merge_into_brand_brain(tenant_id, bullets)
    return {
        "pages_fetched": len(pages),
        "bullets_added": merge["added"],
        "urls": [p["url"] for p in pages],
        "at": ingested_at,
    }


async def preview_website(website_url: str,
                              max_pages: int = _MAX_PAGES_TOTAL) -> Dict[str, Any]:
    """Dry-run version of ``ingest_website`` — returns the distilled
    bullets without persisting anything. Used by the frontend
    "Preview before commit" affordance."""
    root = normalize_url(website_url)
    max_pages = min(max_pages, _MAX_PAGES_TOTAL)
    pages: List[Dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        try:
            first = await fetch_page(client, root)
        except Exception as e:                                    # noqa: BLE001
            return {"pages_fetched": 0, "bullets": [],
                     "error": str(e)[:200]}
        pages.append({"url": root, **parse_page(first["html_bytes"], root)})
        soup = BeautifulSoup(
            first["html_bytes"].decode("utf-8", errors="replace"),
            "html.parser",
        )
        for url in _internal_links(soup, root):
            if len(pages) >= max_pages:
                break
            try:
                p = await fetch_page(client, url)
            except Exception:
                continue
            pages.append({"url": url, **parse_page(p["html_bytes"], url)})
    return {
        "pages_fetched": len(pages),
        "bullets": distill_bullets(pages),
        "urls": [p["url"] for p in pages],
    }
