"""Phase SEO-C · Feb-2026 — Keyword ideation service.

Two data sources, both free:

* **Google Autocomplete** — the public ``suggestqueries.google.com``
  endpoint returns a JSON array of suggestions for a partial query.
  We hammer it in five flavours (base, questions, comparisons,
  prepositions, alphabetical) then dedupe.

* **Google Trends** via ``pytrends`` — 12-month interest-over-time
  and related queries. This library is notoriously flaky; every
  call is wrapped in ``try/except`` so a Trends failure never
  breaks the ideation flow.

Both are cached in ``keyword_lookups`` for 24 hours to be a good
citizen — Google Autocomplete does not want to be hammered.
"""
from __future__ import annotations

import asyncio
import json
import string
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import db, logger
from utils import new_id, now_iso

_UA = "Mozilla/5.0 (compatible; EmergentKeywordIdeator/1.0)"
_TIMEOUT = 10.0
_CONCURRENCY = 3
_MAX_PER_CATEGORY = 50
_DEFAULT_TTL = 86400  # 24h

_QUESTION_PREFIXES = ["how", "why", "what", "where", "when",
                      "can", "is", "does"]
_COMPARISON_MODS = [" vs ", " or "]
_PREPOSITION_MODS = [" for ", " near ", " with ", " without ", " in "]
_ALPHA = list(string.ascii_lowercase)


# ═══════════════════════ Autocomplete ══════════════════════════════

async def fetch_google_autocomplete(client: httpx.AsyncClient,
                                        query: str,
                                        language: str = "en",
                                        region: str = "US") -> List[str]:
    """Fetch autocomplete suggestions for ``query``. Returns [] on any
    non-2xx / parse error. Never raises."""
    if not query or not query.strip():
        return []
    try:
        r = await client.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": query,
                     "hl": language, "gl": region},
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            if r.status_code in (429, 403):
                logger.info("[keyword_ideator] autocomplete throttled %s",
                            r.status_code)
            return []
        # The response body is a JSON array shaped like:
        #   ["query", ["sug1","sug2",...], [], {…google fields…}]
        # It sometimes ships without a trailing object — parse loosely.
        parsed = json.loads(r.text)
        if not isinstance(parsed, list) or len(parsed) < 2:
            return []
        sugs = parsed[1]
        if not isinstance(sugs, list):
            return []
        return [s for s in sugs if isinstance(s, str)]
    except Exception as e:  # noqa: BLE001
        logger.info("[keyword_ideator] autocomplete failure: %s", e)
        return []


def _dedupe(items: List[str], cap: int = _MAX_PER_CATEGORY) -> List[str]:
    seen: Dict[str, None] = {}
    for it in items:
        k = (it or "").strip().lower()
        if k and k not in seen:
            seen[k] = None
        if len(seen) >= cap:
            break
    return list(seen.keys())


async def run_autocomplete_matrix(
    seed: str, language: str = "en", region: str = "US",
) -> Dict[str, List[str]]:
    """Run the 5-flavour autocomplete sweep concurrently (capped at
    ``_CONCURRENCY`` in-flight requests). Returns the four persisted
    categories."""
    sem = asyncio.Semaphore(_CONCURRENCY)
    seed = (seed or "").strip().lower()

    async with httpx.AsyncClient() as client:

        async def _fetch(q: str) -> List[str]:
            async with sem:
                return await fetch_google_autocomplete(
                    client, q, language, region)

        # Base sweep.
        base_task = _fetch(seed)
        # Question sweep.
        question_tasks = [_fetch(f"{p} {seed}") for p in _QUESTION_PREFIXES]
        # Comparison sweep — "seed vs a", "seed vs b", … "seed or a", …
        comparison_tasks = [_fetch(f"{seed}{mod}{a}")
                             for mod in _COMPARISON_MODS
                             for a in _ALPHA[:5]]  # a-e keeps volume sane
        # Preposition sweep.
        preposition_tasks = [_fetch(f"{seed}{mod}")
                              for mod in _PREPOSITION_MODS]
        # Alphabetical sweep (base + " a" through " z").
        alpha_tasks = [_fetch(f"{seed} {a}") for a in _ALPHA]

        base, q_res, c_res, p_res, a_res = await asyncio.gather(
            base_task,
            asyncio.gather(*question_tasks),
            asyncio.gather(*comparison_tasks),
            asyncio.gather(*preposition_tasks),
            asyncio.gather(*alpha_tasks),
        )

    # Flatten + dedupe per category.
    def _flat(lists: List[List[str]]) -> List[str]:
        out: List[str] = []
        for lst in lists:
            out.extend(lst)
        return out

    all_alpha = base + _flat(a_res)
    return {
        "autocomplete": _dedupe(all_alpha),
        "questions": _dedupe(_flat(q_res)),
        "comparisons": _dedupe(_flat(c_res)),
        "prepositions": _dedupe(_flat(p_res)),
    }


# ═══════════════════════ Trends ════════════════════════════════════

def _fetch_pytrends_sync(seed: str, language: str,
                            region: str) -> Dict[str, Any]:
    """Synchronous pytrends wrapper. All exceptions swallowed —
    returns ``{error: "..."}`` on any failure. Called from a
    threadpool by ``fetch_pytrends`` because pytrends is sync-only."""
    try:
        from pytrends.request import TrendReq
    except Exception as e:  # noqa: BLE001
        return {"error": f"pytrends_import_failed:{e}"}
    try:
        tr = TrendReq(hl=language, tz=0, timeout=(5, 15))
        tr.build_payload([seed], timeframe="today 12-m",
                            geo=region or "")
        iot_df = tr.interest_over_time()
        iot: List[Dict[str, Any]] = []
        if iot_df is not None and not iot_df.empty and seed in iot_df.columns:
            for ts, row in iot_df.iterrows():
                iot.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "value": int(row[seed]) if row[seed] is not None else 0,
                })
        rq = tr.related_queries()
        seed_rq = rq.get(seed, {}) if isinstance(rq, dict) else {}
        top_df = seed_rq.get("top") if isinstance(seed_rq, dict) else None
        rising_df = seed_rq.get("rising") if isinstance(seed_rq, dict) else None
        top = ([r["query"] for _, r in top_df.iterrows()]
               if top_df is not None and not top_df.empty else [])
        rising = ([r["query"] for _, r in rising_df.iterrows()]
                  if rising_df is not None and not rising_df.empty else [])
        return {
            "interest_over_time": iot[:52],
            "related_queries_top": top[:20],
            "related_queries_rising": rising[:20],
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


async def fetch_pytrends(seed: str, language: str = "en",
                            region: str = "US") -> Dict[str, Any]:
    """Async-friendly wrapper — offloads sync pytrends work to the
    default asyncio executor so the event loop keeps spinning."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_pytrends_sync,
                                  seed, language, region),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        return {"error": "pytrends_timeout"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"pytrends_wrapper_error:{e}"}


# ═══════════════════════ Cache + rate limit ════════════════════════

async def _load_cached(tenant_id: str, seed: str, language: str,
                          region: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    row = await db.keyword_lookups.find_one(
        {"tenant_id": tenant_id, "seed_keyword": seed,
          "language": language, "region": region},
        {"_id": 0})
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except Exception:
        return None
    age = (datetime.now(timezone.utc) - fetched).total_seconds()
    if age > ttl_seconds:
        return None
    return row


async def check_rate_limit(user_id: str,
                              limit_per_hour: int = 20) -> None:
    """Raise ``ValueError('rate_limited')`` if the caller has already
    triggered ``limit_per_hour`` fresh lookups in the last 60 minutes.
    Uses ``keyword_search_history`` (one row per POST /ideate) as
    the counter — cheap and DB-backed."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=1)).isoformat()
    count = await db.keyword_search_history.count_documents({
        "user_id": user_id,
        "requested_at": {"$gte": cutoff},
    })
    if count >= limit_per_hour:
        raise ValueError("rate_limited")


# ═══════════════════════ Orchestrator ══════════════════════════════

async def run_ideation(seed: str, language: str, region: str,
                          tenant_id: str, user_id: str,
                          force_refresh: bool = False,
                          ttl_seconds: int = _DEFAULT_TTL) -> Dict[str, Any]:
    """Full ideation pipeline. Returns the persisted lookup row
    (with an added ``cached`` flag). Never raises for autocomplete
    or Trends failures — they degrade to empty lists / error dicts.
    """
    seed = (seed or "").strip().lower()
    if not seed:
        raise ValueError("empty_seed")
    language = (language or "en").strip().lower()
    region = (region or "US").strip().upper()

    if not force_refresh:
        cached = await _load_cached(tenant_id, seed, language,
                                        region, ttl_seconds)
        if cached is not None:
            # Log the history hit too — this is a "search" from the
            # user's PoV even if we didn't hit Google.
            await db.keyword_search_history.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id, "user_id": user_id,
                "seed_keyword": seed,
                "requested_at": now_iso(),
                "lookup_id": cached["id"],
                "cached": True,
            })
            return {**cached, "cached": True}

    # Fresh pull.
    matrix_task = run_autocomplete_matrix(seed, language, region)
    trends_task = fetch_pytrends(seed, language, region)
    matrix, trends = await asyncio.gather(matrix_task, trends_task)

    now_ts = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "requested_by_user_id": user_id,
        "seed_keyword": seed,
        "language": language,
        "region": region,
        "fetched_at": now_ts,
        "autocomplete_suggestions": matrix["autocomplete"],
        "question_suggestions": matrix["questions"],
        "comparison_suggestions": matrix["comparisons"],
        "preposition_suggestions": matrix["prepositions"],
        "trends_summary": trends,
        "cache_ttl_seconds": ttl_seconds,
    }
    # Upsert on unique key (tenant_id, seed_keyword, region, language).
    await db.keyword_lookups.update_one(
        {"tenant_id": tenant_id, "seed_keyword": seed,
          "language": language, "region": region},
        {"$set": doc},
        upsert=True,
    )
    fresh = await db.keyword_lookups.find_one(
        {"tenant_id": tenant_id, "seed_keyword": seed,
          "language": language, "region": region},
        {"_id": 0})
    # History row for the current user.
    await db.keyword_search_history.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id, "user_id": user_id,
        "seed_keyword": seed,
        "requested_at": now_ts,
        "lookup_id": fresh["id"],
        "cached": False,
    })
    return {**fresh, "cached": False}
