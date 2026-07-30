"""Phase 5c · Feb-2026 — Search provider adapter for brand-mention
crawling. User API Key integration — no bundled shared keys.

Two providers: Serper.dev (default) and Google Custom Search JSON API
(fallback). If neither key is present, the adapter returns an empty
result set with ``provider_configured=False`` — the endpoint MUST NOT
crash.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

_UA = "EmergentBrandMentions/1.0 (+https://emergent.dev)"
_TIMEOUT = 10.0

# Coarse per-call cost estimate (used only for the tenant monthly cap).
COST_PER_CALL_USD = float(os.environ.get(
    "AEO_MENTIONS_COST_PER_CALL_USD", "0.003"))


def selected_provider() -> Optional[str]:
    if os.environ.get("SERPER_API_KEY"):
        return "serper"
    if os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX"):
        return "google_cse"
    return None


def _domain_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


async def _serper_search(client: httpx.AsyncClient, query: str,
                            max_results: int) -> List[Dict[str, Any]]:
    key = os.environ["SERPER_API_KEY"]
    r = await client.post("https://google.serper.dev/search",
                             headers={"X-API-KEY": key,
                                        "Content-Type": "application/json",
                                        "User-Agent": _UA},
                             json={"q": query, "num": max_results},
                             timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json() or {}
    out: List[Dict[str, Any]] = []
    for item in (data.get("organic") or [])[:max_results]:
        out.append({"url": item.get("link"),
                     "title": item.get("title") or "",
                     "snippet": item.get("snippet") or ""})
    return out


async def _google_cse_search(client: httpx.AsyncClient, query: str,
                                max_results: int) -> List[Dict[str, Any]]:
    key = os.environ["GOOGLE_CSE_API_KEY"]
    cx = os.environ["GOOGLE_CSE_CX"]
    r = await client.get("https://www.googleapis.com/customsearch/v1",
                            params={"key": key, "cx": cx, "q": query,
                                     "num": min(max_results, 10)},
                            headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json() or {}
    out: List[Dict[str, Any]] = []
    for item in (data.get("items") or [])[:max_results]:
        out.append({"url": item.get("link"),
                     "title": item.get("title") or "",
                     "snippet": item.get("snippet") or ""})
    return out


async def search(query: str, max_results: int = 10,
                   client: Optional[httpx.AsyncClient] = None,
                   ) -> Dict[str, Any]:
    """Return {provider, provider_configured, results:[{url,title,snippet,domain}]}."""
    prov = selected_provider()
    if not prov:
        return {"provider": None, "provider_configured": False,
                "results": [], "cost_est_usd": 0.0}
    own = client
    if own is None:
        own = httpx.AsyncClient()
    try:
        if prov == "serper":
            raw = await _serper_search(own, query, max_results)
        else:
            raw = await _google_cse_search(own, query, max_results)
    except Exception as e:  # noqa: BLE001
        raw = []
        return {"provider": prov, "provider_configured": True,
                "results": [], "cost_est_usd": 0.0,
                "error": f"{type(e).__name__}:{str(e)[:120]}"}
    finally:
        if client is None:
            await own.aclose()
    results = [{"url": x["url"], "title": x["title"],
                "snippet": x["snippet"], "domain": _domain_of(x["url"])}
               for x in raw if x.get("url")]
    return {"provider": prov, "provider_configured": True,
            "results": results, "cost_est_usd": COST_PER_CALL_USD}
