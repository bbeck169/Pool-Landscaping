"""Phase 5a · Feb-2026 — AEO (Answer Engine Optimization) auditor
signals. Pure parsing helpers layered on top of the existing SEO
scanner output. No new HTTP dependencies beyond the caller's httpx
client, which is passed in for the llms.txt origin probe.

Public entry points:
    :func:`aeo_signals_from_html`   → dict of sub-signals + score
    :func:`fetch_llms_txt_presence` → dict with present/url/size

All functions are individually unit-testable without touching the
network.
"""
from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from services.seo_scanner import parse_schema_org

_UA = "EmergentAEOAuditor/1.0 (+https://emergent.dev)"
_TIMEOUT = 6.0
_LLMS_MAX_BYTES = 512_000  # 512 KB cap for llms.txt file size read.

# Recommended schema types for pool + landscaping services. Weighted:
# LocalBusiness / Service must be present; FAQPage is highly-desired.
_RECOMMENDED = ("LocalBusiness", "FAQPage", "Service", "Organization",
                 "HowTo", "BreadcrumbList", "Review")
_MUST_HAVE = ("LocalBusiness", "Service", "FAQPage")

# Weighting for overall_aeo_score (must sum to 100).
_WEIGHTS = {
    "schema": 30, "faq": 20, "llms_txt": 15,
    "passages": 15, "entity_clarity": 20,
}


def _schema_signal(html_bytes: bytes) -> Dict[str, Any]:
    parsed = parse_schema_org(html_bytes)
    present = set(parsed.get("types") or [])
    missing = [t for t in _RECOMMENDED if t not in present]
    # 0 if none of the must-have types are present.
    has_must = any(t in present for t in _MUST_HAVE)
    if not has_must:
        score = 0
    else:
        # Base 30 for any must-have, +10 for each recommended present
        # (cap at 100).
        score = 30 + 10 * sum(1 for t in _RECOMMENDED if t in present)
        score = min(100, score)
    return {
        "types_present": sorted(present),
        "types_missing_recommended": missing,
        "score": int(score),
    }


def _faq_signal(html_bytes: bytes) -> Dict[str, Any]:
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")
    # 1) <details>/<summary> pairs.
    details_count = len(soup.find_all("details"))
    # 2) Question-style h2/h3 headings.
    q_prefix = re.compile(r"^\s*(how|what|why|when|where|does|do|is|are|can|should)\b",
                           re.IGNORECASE)
    q_headings = [h for h in soup.find_all(["h2", "h3"])
                   if h.get_text(strip=True)
                   and (q_prefix.match(h.get_text(strip=True))
                         or h.get_text(strip=True).rstrip().endswith("?"))]
    # 3) Explicit FAQPage schema.
    schema = parse_schema_org(html_bytes)
    schema_faq = "FAQPage" in (schema.get("types") or [])
    count = max(details_count, len(q_headings))
    if schema_faq and count == 0:
        count = 1  # schema alone counts as 1
    if count == 0:
        score = 0
    elif count >= 5 or schema_faq:
        score = 100
    else:
        score = 40 + 15 * count  # 55, 70, 85 for 1..3
    return {"count": count, "schema_faq": schema_faq,
            "detail_pairs": details_count,
            "question_headings": len(q_headings),
            "score": int(min(100, score))}


async def fetch_llms_txt_presence(client: httpx.AsyncClient,
                                     base_url: str) -> Dict[str, Any]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    checked = f"{origin}/llms.txt"
    present = False
    size = 0
    try:
        r = await client.get(checked, headers={"User-Agent": _UA},
                                timeout=_TIMEOUT, follow_redirects=True)
        if 200 <= r.status_code < 300:
            body = r.content or b""
            # Guard against JS SPA fallbacks that serve index.html at every
            # unknown route. Require a plain-text mime OR a body that looks
            # like it starts with "# " (Markdown-ish llms.txt spec).
            ct = (r.headers.get("content-type") or "").lower()
            looks_like_llms = (
                ct.startswith("text/plain")
                or ct.startswith("text/markdown")
                or body[:2] == b"# "
            )
            if looks_like_llms:
                present = True
                size = min(len(body), _LLMS_MAX_BYTES)
    except Exception:
        pass
    score = 100 if present else 0
    return {"present": present, "url_checked": checked, "size_bytes": size,
            "score": score}


def _passage_signal(html_bytes: bytes) -> Dict[str, Any]:
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup.find_all(["script", "style", "noscript", "nav",
                                  "header", "footer"]):
        junk.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if p]
    if not paras:
        return {"total": 0, "median_words": 0, "over_90_words": 0,
                "score": 0}
    lens = [len(p.split()) for p in paras]
    med = int(statistics.median(lens))
    over = sum(1 for n in lens if n > 90)
    # Score: 100 when median <= 45, 0 when median >= 150. Linear in-between.
    if med <= 45:
        score = 100
    elif med >= 150:
        score = 0
    else:
        score = int(round(100 * (150 - med) / (150 - 45)))
    # Penalize when > half the paragraphs are over 90.
    if over > len(paras) / 2:
        score = max(0, score - 25)
    return {"total": len(paras), "median_words": med,
            "over_90_words": over, "score": int(score)}


def _entity_clarity_signal(html_bytes: bytes,
                             business_name: str = "") -> Dict[str, Any]:
    html = html_bytes.decode("utf-8", errors="replace") if html_bytes else ""
    soup = BeautifulSoup(html, "html.parser")
    # Meta description length.
    m = soup.find("meta", attrs={"name": "description"})
    if not m:
        m = soup.find("meta", attrs={"property": "og:description"})
    desc = (m.get("content") if m else "") or ""
    desc_len = len(desc)
    # H1 presence + optional business-name check.
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
    has_h1 = bool(h1s)
    h1_has_biz = bool(business_name) and any(
        business_name.lower() in (t or "").lower() for t in h1s)
    # sameAs count from any JSON-LD block.
    schema = parse_schema_org(html_bytes)
    same_as: List[str] = []
    for block in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            import json as _json
            raw = block.string or block.get_text() or ""
            data = _json.loads(raw.strip())
            for item in (data if isinstance(data, list) else [data]):
                if isinstance(item, dict) and item.get("sameAs"):
                    s = item["sameAs"]
                    same_as.extend(s if isinstance(s, list) else [s])
        except Exception:
            continue
    same_as_count = len(same_as)

    # Score composition:
    #   +40 for meta description length in [150, 160]
    #   +20 for description length in [80, 149] (short but exists)
    #   +25 for has_h1 (+10 more if business name appears in it)
    #   +25 for same_as_count >= 2  (or +12 for 1)
    score = 0
    if 150 <= desc_len <= 160:
        score += 40
    elif 80 <= desc_len <= 149:
        score += 20
    if has_h1:
        score += 25
        if h1_has_biz:
            score += 10
    if same_as_count >= 2:
        score += 25
    elif same_as_count == 1:
        score += 12
    # Presence of schema.types at all is worth a small bump.
    if schema.get("types"):
        score += 0  # already counted in schema signal
    score = min(100, score)
    return {"has_h1": has_h1, "meta_description_len": desc_len,
            "same_as_count": same_as_count,
            "h1_has_business_name": h1_has_biz,
            "score": int(score)}


def _weighted_overall(signals: Dict[str, Dict[str, Any]]) -> int:
    total = 0.0
    for k, w in _WEIGHTS.items():
        total += (signals.get(k, {}).get("score", 0)) * (w / 100.0)
    return int(round(total))


def aeo_signals_from_html(html_bytes: bytes, base_url: str = "",
                            business_name: str = "",
                            llms_txt: Dict[str, Any] | None = None,
                            ) -> Dict[str, Any]:
    """Compute all AEO sub-signals. ``llms_txt`` should already be
    fetched by the async caller (see :func:`fetch_llms_txt_presence`)."""
    schema = _schema_signal(html_bytes)
    faq = _faq_signal(html_bytes)
    passages = _passage_signal(html_bytes)
    ent = _entity_clarity_signal(html_bytes, business_name)
    llms = llms_txt or {"present": False, "url_checked": None,
                          "size_bytes": 0, "score": 0}
    signals = {"schema": schema, "faq": faq, "llms_txt": llms,
               "passages": passages, "entity_clarity": ent}
    overall = _weighted_overall(signals)
    return {**signals, "overall_aeo_score": overall}


async def compute_aeo_signals(client: httpx.AsyncClient,
                                html_bytes: bytes, base_url: str,
                                business_name: str = "") -> Dict[str, Any]:
    """Async wrapper that also probes llms.txt at the target origin."""
    llms = await fetch_llms_txt_presence(client, base_url)
    return aeo_signals_from_html(html_bytes, base_url, business_name, llms)
