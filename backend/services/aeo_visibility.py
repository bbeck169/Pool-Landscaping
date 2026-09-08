"""Phase 5b · Feb-2026 — AI Visibility Tracker.

Runs LLM probes ("Best pool service in {city}?") against configured
providers, scores whether the tenant's brand was mentioned, and
persists to ``aeo_visibility_probes``.

LLM fan-out is *injectable* so tests can stub without hitting the
Emergent key. Real calls delegate to
:func:`services.llm_provider._call_emergent_text` when the runner is
invoked with the default probe function.
"""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable, Dict, List, Optional, Tuple

from config import db, logger, EMERGENT_LLM_KEY  # noqa: F401

# ── Config ────────────────────────────────────────────────────────
DEFAULT_QUERY_TEMPLATES = [
    "Best pool service in {city}, {state}",
    "Who should I hire for pool maintenance near {zip}?",
    "Top landscaping companies in {city}",
    "Compare {tenant_name} vs competitors for pool cleaning in {city}",
    "Is {tenant_name} a good pool company?",
]

DEFAULT_PROVIDERS = [
    {"key": "anthropic-claude",  "provider": "anthropic",
     "model": os.environ.get("AEO_MODEL_CLAUDE", "claude-sonnet-4-5")},
    {"key": "openai-gpt",         "provider": "openai",
     "model": os.environ.get("AEO_MODEL_OPENAI", "gpt-4o-mini")},
    {"key": "google-gemini",      "provider": "gemini",
     "model": os.environ.get("AEO_MODEL_GEMINI", "gemini-2.5-flash")},
]

CRON_HOUR_UTC = int(os.environ.get("AEO_VISIBILITY_CRON_HOUR_UTC", "7"))
MONTHLY_COST_CAP_USD = float(os.environ.get("AEO_VISIBILITY_MONTHLY_CAP_USD", "5.0"))
MAX_PROBES_PER_INVOCATION = 15
COST_PER_PROBE_USD = float(os.environ.get("AEO_VISIBILITY_COST_PER_PROBE", "0.02"))
DUPLICATE_HOURS = 20


# ── Rate limit (5 fix-generations per tenant per hour) ────────────
_FIX_WINDOW_SEC = 3600
_FIX_LIMIT = 5
_fix_hits: Dict[str, deque] = defaultdict(deque)


def check_fix_rate_limit(tenant_id: str) -> Optional[int]:
    """Return None if allowed, or Retry-After seconds if rate-limited."""
    now = time.time()
    q = _fix_hits[tenant_id]
    while q and (now - q[0]) > _FIX_WINDOW_SEC:
        q.popleft()
    if len(q) >= _FIX_LIMIT:
        retry = int(_FIX_WINDOW_SEC - (now - q[0]))
        return max(1, retry)
    q.append(now)
    return None


def reset_fix_rate_limit_for_tests() -> None:
    _fix_hits.clear()


# ── Query rendering + scoring ────────────────────────────────────
_WORD_BOUNDARY_CACHE: Dict[str, re.Pattern] = {}


def _mentions(text: str, name: str) -> bool:
    if not name or not text:
        return False
    pat = _WORD_BOUNDARY_CACHE.get(name.lower())
    if pat is None:
        pat = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        _WORD_BOUNDARY_CACHE[name.lower()] = pat
    return bool(pat.search(text))


def render_query(template: str, tenant: Dict[str, Any]) -> str:
    return template.format(
        tenant_name=tenant.get("name") or tenant.get("business_name") or "",
        city=(tenant.get("city") or (tenant.get("address") or {}).get("city")
              if isinstance(tenant.get("address"), dict) else "") or "",
        state=(tenant.get("state") or (tenant.get("address") or {}).get("state")
                if isinstance(tenant.get("address"), dict) else "") or "",
        zip=(tenant.get("zip") or tenant.get("postal_code")
              or (tenant.get("address") or {}).get("postalCode")
                if isinstance(tenant.get("address"), dict) else "") or "",
    ).strip()


def score_answer(answer_text: str, tenant_name: str,
                    tenant_domain: str = "",
                    citations: Optional[List[str]] = None,
                    competitors: Optional[List[str]] = None) -> Tuple[int, Dict[str, Any]]:
    """Score 0..100 per the Phase 5b spec:
        +60 whole-word mention of tenant_name (case-insensitive)
        +20 mention appears in the first paragraph
        +15 at least one citation on tenant_domain
        +5  no competitors mentioned OR tenant appears above them
    """
    citations = citations or []
    competitors = competitors or []
    text = answer_text or ""
    score = 0
    breakdown: Dict[str, Any] = {}
    mentioned = _mentions(text, tenant_name)
    breakdown["brand_mentioned"] = mentioned
    if mentioned:
        score += 60
    # First paragraph
    first_para = text.split("\n\n", 1)[0] if text else ""
    in_first = _mentions(first_para, tenant_name)
    breakdown["mention_in_first_paragraph"] = in_first
    if in_first:
        score += 20
    # Domain citation
    dom_hit = False
    if tenant_domain:
        dom = tenant_domain.lower()
        for u in citations:
            if isinstance(u, str) and dom in u.lower():
                dom_hit = True
                break
    breakdown["has_domain_citation"] = dom_hit
    if dom_hit:
        score += 15
    # Competitor context
    comp_mentioned = [c for c in competitors if _mentions(text, c)]
    breakdown["competitors_mentioned"] = comp_mentioned
    if not comp_mentioned:
        score += 5
    else:
        # +5 if tenant appears before first competitor mention
        tenant_pos = text.lower().find((tenant_name or "").lower()) if tenant_name else -1
        first_comp_pos = min([text.lower().find(c.lower())
                                for c in comp_mentioned
                                if text.lower().find(c.lower()) >= 0]
                               or [-1])
        if tenant_pos >= 0 and (first_comp_pos < 0 or tenant_pos < first_comp_pos):
            score += 5
    return int(min(100, max(0, score))), breakdown


# ── Cost cap ──────────────────────────────────────────────────────

async def month_cost_usd(tenant_id: str) -> float:
    """Sum ``cost_est_usd`` of all probes since start of current UTC month."""
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()
    total = 0.0
    async for row in db.aeo_visibility_probes.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": month_start}},
        {"_id": 0, "cost_est_usd": 1},
    ):
        total += float(row.get("cost_est_usd") or 0.0)
    return round(total, 4)


# ── Probe execution ──────────────────────────────────────────────

# Phase I1.7.e · chunk 2.c · Feb-2026 — Sentinel returned by the
# built-in probe caller when a tenant BYO monthly cap is exceeded.
# :func:`run_probes` short-circuits on this and returns
# ``cap_exceeded=True`` at the top level so the HTTP router can
# raise 429 (and the cron scan can log ``skipped_cap_exceeded``).
_CAP_MARKER_KEY = "__ai_cap_exceeded__"


def _make_llm_call(tenant_id: Optional[str]
                     ) -> Callable[[str, str, str], Awaitable[Dict[str, Any]]]:
    """Build a ``(query, provider, model) -> dict`` caller bound to
    ``tenant_id`` so each probe threads the tenant's BYO provider
    (if configured) into ``call_llm_with_fallback``."""
    async def _call(rendered_query: str, provider: str,
                     model: str) -> Dict[str, Any]:
        from services.llm_provider import call_llm_with_fallback
        system = ("You are a helpful assistant answering local-services "
                  "recommendation questions concisely. When appropriate, cite "
                  "sources with URLs.")
        try:
            r = await call_llm_with_fallback(
                system_prompt=system, user_text=rendered_query,
                provider=provider, model=model,
                tenant_id=tenant_id,
            )
        except Exception as e:  # noqa: BLE001
            return {"error": f"emergent_exception:{e}"}
        if r.get("cap_exceeded"):
            return {"error": "ai_spend_cap_exceeded",
                     _CAP_MARKER_KEY: True}
        if r.get("error"):
            return {"error": r["error"]}
        text = ""
        raw = r.get("raw") or r
        if isinstance(raw, dict):
            text = raw.get("answer") or raw.get("text") or ""
        if not text:
            text = str(r.get("_raw_text", "")) or str(raw)[:2000]
        return {"answer_text": text, "citations": []}
    return _call


async def _default_llm_call(rendered_query: str, provider: str,
                              model: str) -> Dict[str, Any]:
    """Legacy platform-only entrypoint — kept for backwards compat
    with tests that override this symbol. New callers should thread
    ``tenant_id`` via :func:`run_probes`."""
    return await _make_llm_call(None)(rendered_query, provider, model)


async def run_probes(tenant: Dict[str, Any], *,
                       templates: Optional[List[str]] = None,
                       providers: Optional[List[Dict[str, str]]] = None,
                       llm_call: Optional[Callable[[str, str, str], Awaitable[Dict[str, Any]]]] = None,
                       max_probes: int = MAX_PROBES_PER_INVOCATION,
                       tenant_id: Optional[str] = None,
                       ) -> Dict[str, Any]:
    """Run each (template × provider) combination, up to ``max_probes``.

    Returns ``{probes: [...], summary: {total, mentions, avg_score},
    cost_capped, cost_this_month, cost_cap}``.

    Phase I1.7.e · chunk 2.c · Feb-2026 — ``tenant_id`` (defaulting
    to ``tenant['id']``) is threaded into every probe's underlying
    ``call_llm_with_fallback`` call so tenant-BYO provider routing +
    monthly cap enforcement fire per request. On BYO cap-exceeded
    the loop halts, ``cap_exceeded=True`` is set at the top level,
    and any probes already run remain persisted. Transactional
    callers (``POST /aeo/visibility/run-now``) inspect that flag and
    raise HTTP 429; the cron path (``daily_visibility_scan``) logs
    ``skipped_cap_exceeded`` and moves on to the next tenant."""
    resolved_tid = tenant["id"] if isinstance(tenant.get("id"), str) else tenant.get("tenant_id")
    effective_tid = tenant_id or resolved_tid
    if llm_call is None:
        llm_call = _make_llm_call(effective_tid)
    tenant_name = tenant.get("name") or tenant.get("business_name") or ""
    tenant_domain = (tenant.get("url") or tenant.get("website") or "").lower()
    tenant_domain = re.sub(r"^https?://", "", tenant_domain).split("/")[0]

    templates = templates or DEFAULT_QUERY_TEMPLATES
    providers = providers or DEFAULT_PROVIDERS
    started_cost = await month_cost_usd(resolved_tid)
    cost_capped = started_cost >= MONTHLY_COST_CAP_USD
    ai_cap_exceeded = False

    probes_out: List[Dict[str, Any]] = []
    ran = 0
    running_cost = started_cost
    for tpl in templates:
        rendered = render_query(tpl, tenant)
        if not rendered:
            continue
        for prov in providers:
            if ran >= max_probes:
                break
            if running_cost + COST_PER_PROBE_USD > MONTHLY_COST_CAP_USD:
                cost_capped = True
                break
            probe_id = f"probe_{int(time.time()*1000)}_{ran}"
            ran_at = datetime.now(timezone.utc).isoformat()
            try:
                r = await llm_call(rendered, prov["provider"], prov["model"])
            except Exception as e:  # noqa: BLE001
                r = {"error": f"call_exception:{e}"}
            # Phase I1.7.e · chunk 2.c · Feb-2026 — BYO cap hit? Halt
            # the loop and surface at the top level. Any probes
            # already persisted this call stay persisted.
            if r.get(_CAP_MARKER_KEY):
                ai_cap_exceeded = True
                break
            error = r.get("error")
            answer = r.get("answer_text") or ""
            citations = r.get("citations") or []
            comps = tenant.get("competitors") or []
            score, breakdown = score_answer(answer, tenant_name,
                                              tenant_domain=tenant_domain,
                                              citations=citations,
                                              competitors=comps)
            doc = {
                "tenant_id": resolved_tid, "probe_id": probe_id,
                "query_template": tpl, "rendered_query": rendered,
                "llm_provider": prov["key"], "provider_model": prov["model"],
                "ran_at": ran_at,
                "answer_text": (answer or "")[:8000],
                "brand_mentioned": bool(breakdown.get("brand_mentioned")),
                "competitors_mentioned": breakdown.get("competitors_mentioned") or [],
                "citations": citations[:8],
                "score": score,
                "cost_est_usd": COST_PER_PROBE_USD if not error else 0.0,
                "error": error,
            }
            await db.aeo_visibility_probes.insert_one({**doc})
            probes_out.append({
                "probe_id": probe_id, "provider": prov["key"],
                "query": rendered, "brand_mentioned": doc["brand_mentioned"],
                "score": score, "snippet": (answer or "")[:280],
                "error": error,
            })
            ran += 1
            if not error:
                running_cost += COST_PER_PROBE_USD
        if ran >= max_probes or cost_capped or ai_cap_exceeded:
            break

    total = len(probes_out)
    mentions = sum(1 for p in probes_out if p["brand_mentioned"])
    avg = round(sum(p["score"] for p in probes_out) / total, 1) if total else 0.0
    result: Dict[str, Any] = {
        "probes": probes_out,
        "summary": {"total": total, "mentions": mentions, "avg_score": avg},
        "cost_capped": cost_capped,
        "cost_this_month": round(running_cost, 4),
        "cost_cap": MONTHLY_COST_CAP_USD,
    }
    if ai_cap_exceeded:
        result["cap_exceeded"] = True
        result["error"] = "ai_spend_cap_exceeded"
    return result


# ── Dashboard / history ──────────────────────────────────────────

async def dashboard_for_tenant(tenant_id: str) -> Dict[str, Any]:
    """Snapshot: avg score last 30d, top/bottom queries, provider
    breakdown, cost-capped flag."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    scores: List[int] = []
    by_query: Dict[str, List[int]] = defaultdict(list)
    by_prov: Dict[str, List[int]] = defaultdict(list)
    latest_ts: Optional[str] = None
    async for row in db.aeo_visibility_probes.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("ran_at", -1):
        s = int(row.get("score") or 0)
        scores.append(s)
        by_query[row.get("query_template") or "?"].append(s)
        by_prov[row.get("llm_provider") or "?"].append(s)
        latest_ts = latest_ts or row.get("ran_at")

    def _avg(v: List[int]) -> int:
        return int(round(sum(v)/len(v))) if v else 0
    ranked = sorted(
        [{"query": q, "avg_score": _avg(v), "count": len(v)}
          for q, v in by_query.items()],
        key=lambda x: x["avg_score"],
    )
    cost = await month_cost_usd(tenant_id)
    return {
        "avg_score_30d": _avg(scores),
        "probes_30d": len(scores),
        "latest_ran_at": latest_ts,
        "top_queries": list(reversed(ranked))[:3],
        "bottom_queries": ranked[:3],
        "providers": [{"provider": p, "avg_score": _avg(v), "count": len(v)}
                       for p, v in by_prov.items()],
        "cost_this_month": cost,
        "cost_cap": MONTHLY_COST_CAP_USD,
        "cost_capped": cost >= MONTHLY_COST_CAP_USD,
    }


async def history_for_tenant(tenant_id: str, range_key: str = "30d",
                                ) -> Dict[str, Any]:
    days = {"7d": 7, "30d": 30, "90d": 90}.get(range_key, 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    by_day_score: Dict[str, List[int]] = defaultdict(list)
    by_day_mentions: Dict[str, int] = defaultdict(int)
    by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    async for row in db.aeo_visibility_probes.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("ran_at", -1):
        d = (row.get("ran_at") or "")[:10]
        by_day_score[d].append(int(row.get("score") or 0))
        if row.get("brand_mentioned"):
            by_day_mentions[d] += 1
        key = (row.get("llm_provider") or "?",
                row.get("query_template") or "?")
        if key not in by_pair:
            by_pair[key] = {"provider": key[0], "query_template": key[1],
                            "latest_score": int(row.get("score") or 0),
                            "latest_snippet": (row.get("answer_text") or "")[:200],
                            "latest_brand_mentioned": bool(row.get("brand_mentioned")),
                            "count": 1}
        else:
            by_pair[key]["count"] += 1
    series = [{"date": d, "avg_score": int(round(sum(v)/len(v))),
                "mentions": by_day_mentions.get(d, 0)}
               for d, v in sorted(by_day_score.items())]
    return {"range": range_key, "series": series,
            "pairs": list(by_pair.values())}


# ── Cron ─────────────────────────────────────────────────────────

async def daily_visibility_scan() -> Dict[str, Any]:
    """Iterate enabled tenants; skip those with a recent probe.
    Logs an audit row per tenant."""
    dup_cutoff = (datetime.now(timezone.utc)
                    - timedelta(hours=DUPLICATE_HOURS)).isoformat()
    tenants_run = 0
    total_probes = 0
    skipped_cap = 0
    async for t in db.tenants.find({"aeo_visibility_enabled": True},
                                     {"_id": 0}):
        recent = await db.aeo_visibility_probes.find_one(
            {"tenant_id": t.get("id"), "ran_at": {"$gte": dup_cutoff}},
            {"_id": 0, "probe_id": 1})
        if recent:
            continue
        try:
            r = await run_probes(t, tenant_id=t.get("id"))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[aeo_visibility] tenant {t.get('id')} failed: {e}")
            continue
        # Phase I1.7.e · chunk 2.c · Feb-2026 — cron path: log
        # skipped_cap_exceeded and move on. Any probes already
        # persisted this pass still count toward the summary.
        if r.get("cap_exceeded"):
            skipped_cap += 1
            logger.info(
                f"[aeo_visibility] skipped_cap_exceeded tenant={t.get('id')} "
                f"partial_probes={r['summary']['total']}"
            )
        tenants_run += 1
        total_probes += r["summary"]["total"]
        await db.aeo_probe_runs.insert_one({
            "tenant_id": t.get("id"),
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "probes_count": r["summary"]["total"],
            "cost_est_usd_total": r["cost_this_month"],
            "cost_capped": r["cost_capped"],
            "skipped_cap_exceeded": bool(r.get("cap_exceeded")),
        })
    logger.info(f"[aeo_visibility] daily scan tenants={tenants_run} "
                f"probes={total_probes} skipped_cap={skipped_cap}")
    return {"tenants_run": tenants_run, "probes": total_probes,
            "skipped_cap_exceeded": skipped_cap}
