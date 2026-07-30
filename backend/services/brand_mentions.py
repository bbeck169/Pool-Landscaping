"""Phase 5c · Feb-2026 — Brand mention crawler.

Runs each default (or supplied) query through the configured search
provider, dedupes results into ``brand_mentions`` by
(tenant_id, url), optionally classifies sentiment with a cached
Claude call, enforces a per-tenant monthly cost cap, and returns
`{new_mentions, updated_mentions, total_seen, provider_configured}`.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config import db, logger  # noqa: F401
from services.search_provider import search as _default_search, selected_provider

MONTHLY_COST_CAP_USD = float(os.environ.get("AEO_MENTIONS_MONTHLY_CAP_USD", "3.0"))
CRON_HOUR_UTC = int(os.environ.get("AEO_MENTIONS_CRON_HOUR_UTC", "8"))
DUPLICATE_HOURS = 20
DEFAULT_MAX_RESULTS = 10
SENTIMENT_MIN_LEN = 40
SENTIMENT_CACHE_DAYS = 30


def default_queries(tenant: Dict[str, Any]) -> List[str]:
    name = (tenant.get("name") or tenant.get("business_name") or "").strip()
    addr = tenant.get("address") if isinstance(tenant.get("address"), dict) else {}
    city = (addr.get("city") or tenant.get("city") or "").strip()
    state = (addr.get("state") or tenant.get("state") or "").strip()
    qs = []
    if name:
        qs.append(f'"{name}"')
        qs.append(f'"{name}" reviews')
        if city:
            qs.append(f'"{name}" {city}')
    if city and state:
        qs.append(f"pool service {city} {state}")
        qs.append(f"landscaping {city} {state}")
    return qs


async def month_cost_usd(tenant_id: str) -> float:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    total = 0.0
    async for r in db.brand_mention_runs.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": month_start}},
        {"_id": 0, "cost_est_usd": 1},
    ):
        total += float(r.get("cost_est_usd") or 0.0)
    return round(total, 4)


async def _sentiment(snippet: str, tenant_id: str,
                        llm_call: Optional[Callable[[str], Awaitable[str]]] = None,
                        ) -> Optional[str]:
    """Very light Claude classification. Cached in ``brand_sentiment_cache``
    for 30 days per (tenant_id, snippet_hash)."""
    if not snippet or len(snippet) < SENTIMENT_MIN_LEN:
        return None
    import hashlib
    h = hashlib.sha1((snippet or "").encode("utf-8")).hexdigest()
    cached = await db.brand_sentiment_cache.find_one(
        {"tenant_id": tenant_id, "hash": h}, {"_id": 0})
    if cached:
        exp = cached.get("expires_at") or ""
        if exp > datetime.now(timezone.utc).isoformat():
            return cached.get("sentiment")
    # Live call (or stub in tests).
    if llm_call is None:
        async def llm_call(prompt: str) -> str:  # type: ignore[misc]
            from services.llm_provider import _call_emergent_text
            r = await _call_emergent_text(
                system_prompt=("Classify sentiment of the following web "
                                "search snippet toward the mentioned business "
                                "as exactly one word: positive, neutral, or "
                                "negative. Reply with only that word."),
                user_text=prompt, provider="anthropic",
                model="claude-sonnet-4-5")
            if r.get("error"):
                return "neutral"
            raw = r.get("raw") or r
            if isinstance(raw, dict):
                return str(raw.get("answer") or raw.get("text") or "neutral")
            return str(raw)
    try:
        out = (await llm_call(snippet) or "").strip().lower()
    except Exception:  # noqa: BLE001
        out = ""
    if "positive" in out:
        s = "positive"
    elif "negative" in out:
        s = "negative"
    else:
        s = "neutral"
    exp_iso = (datetime.now(timezone.utc)
                 + timedelta(days=SENTIMENT_CACHE_DAYS)).isoformat()
    await db.brand_sentiment_cache.update_one(
        {"tenant_id": tenant_id, "hash": h},
        {"$set": {"tenant_id": tenant_id, "hash": h,
                    "sentiment": s, "expires_at": exp_iso,
                    "snippet_sample": snippet[:120]}},
        upsert=True,
    )
    return s


async def run_crawl(tenant: Dict[str, Any], *,
                       queries: Optional[List[str]] = None,
                       max_results_per_query: int = DEFAULT_MAX_RESULTS,
                       search_fn: Callable[..., Awaitable[Dict[str, Any]]]
                                    = _default_search,
                       sentiment_fn: Optional[Callable[[str, str], Awaitable[Optional[str]]]] = None,
                       ) -> Dict[str, Any]:
    tenant_id = tenant.get("id") or tenant.get("tenant_id")
    max_results_per_query = min(max(int(max_results_per_query or 10), 1), 20)
    started_cost = await month_cost_usd(tenant_id)
    cost_capped = started_cost >= MONTHLY_COST_CAP_USD
    provider = selected_provider()
    provider_configured = bool(provider)

    own_domain = (tenant.get("url") or "").lower()
    own_domain = re.sub(r"^https?://", "", own_domain).split("/")[0]
    competitor_domains = set(
        d.lower() for d in (tenant.get("competitor_domains") or []) if d)

    new_ct = 0
    upd_ct = 0
    total_seen = 0
    running_cost = started_cost
    now_iso = datetime.now(timezone.utc).isoformat()
    error: Optional[str] = None

    qs = queries or default_queries(tenant)
    for q in qs:
        if not q:
            continue
        if not provider_configured:
            break
        if running_cost + 0.001 > MONTHLY_COST_CAP_USD:
            cost_capped = True
            break
        r = await search_fn(q, max_results=max_results_per_query)
        if r.get("error"):
            error = r.get("error")
        running_cost += float(r.get("cost_est_usd") or 0.0)
        results = r.get("results") or []
        total_seen += len(results)
        for res in results:
            url = res.get("url") or ""
            if not url:
                continue
            dom = (res.get("domain") or "").lower()
            existing = await db.brand_mentions.find_one(
                {"tenant_id": tenant_id, "url": url}, {"_id": 0})
            if existing:
                await db.brand_mentions.update_one(
                    {"tenant_id": tenant_id, "url": url},
                    {"$set": {"last_seen_at": now_iso,
                                "is_competitor_domain": dom in competitor_domains,
                                "is_own_domain": bool(own_domain and dom == own_domain)}},
                )
                upd_ct += 1
                continue
            sentiment: Optional[str] = None
            if sentiment_fn is not None:
                sentiment = await sentiment_fn(res.get("snippet") or "", tenant_id)
            elif res.get("snippet") and len(res["snippet"]) >= SENTIMENT_MIN_LEN:
                sentiment = await _sentiment(res["snippet"], tenant_id)
            doc = {
                "tenant_id": tenant_id,
                "mention_id": f"m_{int(datetime.now().timestamp()*1000)}_{new_ct}",
                "query": q, "provider": provider,
                "url": url, "title": res.get("title") or "",
                "snippet": (res.get("snippet") or "")[:600],
                "domain": dom,
                "sentiment": sentiment,
                "is_competitor_domain": dom in competitor_domains,
                "is_own_domain": bool(own_domain and dom == own_domain),
                "tag": None,
                "discovered_at": now_iso,
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
            }
            try:
                await db.brand_mentions.insert_one(doc)
                new_ct += 1
            except Exception as e:  # noqa: BLE001
                # Unique index race — treat as update.
                await db.brand_mentions.update_one(
                    {"tenant_id": tenant_id, "url": url},
                    {"$set": {"last_seen_at": now_iso}})
                upd_ct += 1
                logger.debug(f"[mentions] dedupe race on {url}: {e}")

    run_doc = {
        "tenant_id": tenant_id, "ran_at": now_iso,
        "queries_run": len([q for q in qs if q]),
        "new_mentions": new_ct, "updated_mentions": upd_ct,
        "provider": provider, "cost_est_usd": round(running_cost - started_cost, 4),
        "cost_capped": cost_capped, "error": error,
    }
    await db.brand_mention_runs.insert_one(run_doc)
    return {"new_mentions": new_ct, "updated_mentions": upd_ct,
            "total_seen": total_seen,
            "provider_configured": provider_configured,
            "provider": provider, "cost_capped": cost_capped,
            "cost_this_month": round(running_cost, 4),
            "cost_cap": MONTHLY_COST_CAP_USD,
            "run_id": run_doc.get("mention_id") or "",
            "error": error}


# ── Dashboard / list ──────────────────────────────────────────────

async def dashboard_for_tenant(tenant_id: str) -> Dict[str, Any]:
    cutoff30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    cutoff7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    total = 0
    new_this_week = 0
    by_sent: Dict[str, int] = defaultdict(int)
    by_domain: Dict[str, int] = defaultdict(int)
    by_day: Dict[str, int] = defaultdict(int)
    async for r in db.brand_mentions.find(
        {"tenant_id": tenant_id,
          "discovered_at": {"$gte": cutoff30}}, {"_id": 0}):
        total += 1
        d = (r.get("discovered_at") or "")[:10]
        by_day[d] += 1
        if r.get("discovered_at", "") >= cutoff7:
            new_this_week += 1
        s = r.get("sentiment") or "unknown"
        by_sent[s] += 1
        by_domain[r.get("domain") or "?"] += 1
    top_domains = sorted(
        [{"domain": d, "count": c} for d, c in by_domain.items()],
        key=lambda x: -x["count"])[:10]
    series = [{"date": d, "count": by_day.get(d, 0)}
               for d in sorted(by_day.keys())]
    cost = await month_cost_usd(tenant_id)
    return {
        "provider_configured": bool(selected_provider()),
        "provider": selected_provider(),
        "total_30d": total,
        "new_this_week": new_this_week,
        "sentiment_breakdown": dict(by_sent),
        "top_domains": top_domains,
        "series_7d": [{"date": d, "count": by_day.get(d, 0)}
                        for d in sorted(by_day.keys())
                        if d >= cutoff7[:10]],
        "series_range": series,
        "cost_this_month": cost,
        "cost_cap": MONTHLY_COST_CAP_USD,
        "cost_capped": cost >= MONTHLY_COST_CAP_USD,
    }


async def list_mentions(tenant_id: str, *, range_key: str = "30d",
                          domain: Optional[str] = None,
                          sentiment: Optional[str] = None,
                          page: int = 1, size: int = 25) -> Dict[str, Any]:
    days = {"7d": 7, "30d": 30, "90d": 90}.get(range_key, 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                          "discovered_at": {"$gte": cutoff}}
    if domain:
        q["domain"] = domain.lower()
    if sentiment:
        q["sentiment"] = sentiment
    total = await db.brand_mentions.count_documents(q)
    items: List[Dict[str, Any]] = []
    cursor = (db.brand_mentions.find(q, {"_id": 0})
              .sort("discovered_at", -1)
              .skip(max(0, (page - 1) * size)).limit(size))
    async for row in cursor:
        items.append(row)
    return {"items": items, "total": total, "page": page, "size": size}


# ── Cron ─────────────────────────────────────────────────────────

async def daily_mentions_scan() -> Dict[str, Any]:
    dup_cutoff = (datetime.now(timezone.utc)
                    - timedelta(hours=DUPLICATE_HOURS)).isoformat()
    ran = 0
    new_total = 0
    if not selected_provider():
        logger.info("[mentions] cron skipped — no provider configured")
        return {"tenants_run": 0, "new_mentions": 0, "reason": "no_provider"}
    async for t in db.tenants.find({"aeo_visibility_enabled": True},
                                     {"_id": 0}):
        recent = await db.brand_mention_runs.find_one(
            {"tenant_id": t.get("id"), "ran_at": {"$gte": dup_cutoff}},
            {"_id": 0})
        if recent:
            continue
        try:
            r = await run_crawl(t)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[mentions] tenant {t.get('id')} failed: {e}")
            continue
        ran += 1
        new_total += r.get("new_mentions") or 0
    logger.info(f"[mentions] daily scan tenants={ran} new={new_total}")
    return {"tenants_run": ran, "new_mentions": new_total}


# ── Competitor retagging ─────────────────────────────────────────

async def set_competitor_domains(tenant_id: str,
                                    domains: List[str]) -> Dict[str, Any]:
    cleaned = sorted({(d or "").lower().strip() for d in domains if (d or "").strip()})
    await db.tenants.update_one({"id": tenant_id},
                                    {"$set": {"competitor_domains": cleaned}})
    # Retroactively tag past mentions.
    if cleaned:
        r_true = await db.brand_mentions.update_many(
            {"tenant_id": tenant_id, "domain": {"$in": cleaned}},
            {"$set": {"is_competitor_domain": True}})
        r_false = await db.brand_mentions.update_many(
            {"tenant_id": tenant_id, "domain": {"$nin": cleaned}},
            {"$set": {"is_competitor_domain": False}})
        return {"domains": cleaned,
                "retagged_true": r_true.modified_count,
                "retagged_false": r_false.modified_count}
    r = await db.brand_mentions.update_many(
        {"tenant_id": tenant_id},
        {"$set": {"is_competitor_domain": False}})
    return {"domains": [], "retagged_true": 0,
            "retagged_false": r.modified_count}
