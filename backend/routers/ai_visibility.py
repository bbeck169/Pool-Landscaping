"""Feb-2026 · Phase 24 — AI Search Visibility Tracker.

Tracks which prompts your brand shows up on across AI-answer engines
(Perplexity / Claude / Gemini / Google's DataForSEO AI Overviews).

Providers gracefully degrade when their API key is missing:
* CLAUDE   — always available (EMERGENT_LLM_KEY)
* DFS AIO  — always available (existing DATAFORSEO_* creds)
* PERPLEXITY — needs PERPLEXITY_API_KEY, otherwise 'provider_disabled'
* GEMINI   — needs GEMINI_API_KEY, otherwise 'provider_disabled'

Frontend + weekly-digest email + vitest deferred to next session.
"""
from __future__ import annotations

import os, re, math
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id
from services import dataforseo_client as dfs

router = APIRouter(tags=["AI Visibility"])
MAX_PROMPTS_PER_TENANT = 20
REFRESH_COOLDOWN_HOURS = 6
DAILY_COST_CAP_USD = 5.0

SEED_PROMPTS = [
    "best pool cleaning company peoria az",
    "salt cell replacement services peoria arizona",
    "pool tile repair vistancia",
    "landscaping companies peoria az",
    "sprinkler repair vistancia",
    "artificial turf installers peoria az",
    "pool equipment repair near me peoria",
]


# ──────────────────────────────────────────────────────────────────────
# Provider clients
# ──────────────────────────────────────────────────────────────────────
async def _claude_query(prompt: str) -> Dict[str, Any]:
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return {"error": "provider_disabled",
                 "reason": "EMERGENT_LLM_KEY not configured"}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = (LlmChat(api_key=key, session_id=f"aiv-{new_id()[:8]}",
                          system_message="You are a helpful assistant that answers "
                                          "local business questions with specific "
                                          "company names and links when possible.")
                .with_model("anthropic", "claude-sonnet-4-5-20250929"))
        resp = await chat.send_message(UserMessage(text=prompt))
        text = getattr(resp, "text", str(resp))
        return {"response_text": text, "sources": [], "raw": {"provider": "claude"},
                 "api_cost_usd": 0.005}
    except Exception as e:
        logger.warning(f"[aiv.claude] failed: {e}")
        return {"error": "provider_error", "reason": str(e)[:200]}


async def _perplexity_query(prompt: str) -> Dict[str, Any]:
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        return {"error": "provider_disabled",
                 "reason": "PERPLEXITY_API_KEY not configured"}
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {key}",
                          "Content-Type": "application/json"},
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if r.status_code != 200:
            return {"error": "provider_error",
                     "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
        body = r.json() or {}
        choice = (body.get("choices") or [{}])[0]
        text = ((choice.get("message") or {}).get("content") or "")
        cites = body.get("citations") or []
        return {"response_text": text, "sources": cites,
                 "raw": {"provider": "perplexity", "id": body.get("id")},
                 "api_cost_usd": 0.005}
    except Exception as e:
        logger.warning(f"[aiv.perplexity] failed: {e}")
        return {"error": "provider_error", "reason": str(e)[:200]}


async def _gemini_query(prompt: str) -> Dict[str, Any]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"error": "provider_disabled",
                 "reason": "GEMINI_API_KEY not configured"}
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
        if r.status_code != 200:
            return {"error": "provider_error",
                     "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
        body = r.json() or {}
        cands = body.get("candidates") or []
        text = ""
        if cands:
            parts = ((cands[0].get("content") or {}).get("parts") or [])
            text = " ".join(p.get("text", "") for p in parts)
        return {"response_text": text, "sources": [],
                 "raw": {"provider": "gemini"},
                 "api_cost_usd": 0.001}
    except Exception as e:
        logger.warning(f"[aiv.gemini] failed: {e}")
        return {"error": "provider_error", "reason": str(e)[:200]}


async def _dfs_aio_query(prompt: str, lat: float = 33.77, lng: float = -112.26) -> Dict[str, Any]:
    """DataForSEO AI Overviews live endpoint.

    We reuse the existing DFS auth path.  If DFS is unavailable this
    surfaces the same graceful errors that Rank Tracker does
    (`no_credentials`, `auth_failed`, `account_unverified`).
    """
    creds = dfs._creds()
    if not creds:
        return {"error": "provider_disabled",
                 "reason": "DATAFORSEO_LOGIN/PASSWORD not configured"}
    import base64, json as _json
    login, pw = creds
    b64 = base64.b64encode(f"{login}:{pw}".encode()).decode()
    task = [{
        "keyword": prompt,
        "language_code": "en",
        "location_coordinate": f"{lat:.6f},{lng:.6f},10",
        "device": "desktop",
    }]
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(
                "https://api.dataforseo.com/v3/serp/google/ai_summary/live/advanced",
                headers={"Authorization": f"Basic {b64}",
                          "Content-Type": "application/json"},
                json=task,
            )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        api_sc = body.get("status_code")
        if api_sc == 40104:
            return {"error": "account_unverified",
                     "reason": "DataForSEO account not verified"}
        if api_sc == 40100:
            return {"error": "auth_failed", "reason": "DataForSEO auth failed"}
        if api_sc not in (20000, 20100):
            return {"error": "provider_error",
                     "reason": f"api_status_code={api_sc}"}
        tasks = body.get("tasks") or []
        result = (tasks[0].get("result") if tasks else None) or []
        items = (result[0].get("items") if result else None) or []
        # AI Overview payload can be structured differently — collect text.
        text = ""
        sources: List[str] = []
        for item in items:
            if item.get("type") in ("ai_overview", "ai_overview_expanded"):
                markdown = item.get("markdown") or ""
                text += markdown + "\n"
                for ref in (item.get("references") or []):
                    if ref.get("url"): sources.append(ref["url"])
        return {"response_text": text.strip(), "sources": sources,
                 "raw": {"provider": "dataforseo_aio"},
                 "api_cost_usd": 0.02}
    except Exception as e:
        logger.warning(f"[aiv.dfs_aio] failed: {e}")
        return {"error": "provider_error", "reason": str(e)[:200]}


PROVIDERS = {
    "claude": _claude_query,
    "perplexity": _perplexity_query,
    "gemini": _gemini_query,
    "dataforseo_aio": _dfs_aio_query,
}


# ──────────────────────────────────────────────────────────────────────
# Mention detection
# ──────────────────────────────────────────────────────────────────────
def _domain_of(url: str) -> str:
    if not url: return ""
    try:
        n = urlparse(url).netloc or url
        return n.lower().replace("www.", "").strip("/")
    except Exception:
        return ""


def _brand_terms(business_card: Dict[str, Any],
                   settings: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for k in ("company_name",):
        v = (business_card.get(k) or "").strip()
        if v: terms.append(v)
    domain = _domain_of(business_card.get("website_url") or "")
    if domain: terms.append(domain)
    aliases = (settings.get("ai_visibility") or {}).get("brand_aliases") or []
    for a in aliases:
        if isinstance(a, str) and a.strip(): terms.append(a.strip())
    # Dedupe case-insensitive.
    seen: set = set()
    out: List[str] = []
    for t in terms:
        k = t.lower()
        if k and k not in seen:
            seen.add(k); out.append(t)
    return out


def detect_mention(text: str, brand_terms: List[str]) -> Dict[str, Any]:
    """Case-insensitive substring match. Captures the surrounding
    sentence (± ~120 chars) for the first hit."""
    if not text: return {"found": False, "context": None, "matched_term": None}
    lo = text.lower()
    for term in brand_terms:
        idx = lo.find(term.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(text), idx + len(term) + 60)
            return {"found": True, "matched_term": term,
                     "context": text[start:end].strip()}
    return {"found": False, "context": None, "matched_term": None}


def detect_competitors(text: str, competitors: List[str]) -> List[str]:
    if not text or not competitors: return []
    lo = text.lower()
    out: List[str] = []
    for c in competitors:
        if isinstance(c, str) and c.strip() and c.lower() in lo:
            out.append(c)
    return out


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _admin_or_403(user: dict):
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _tenant_context(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id},
                                     {"_id": 0, "settings": 1})
    settings = (t or {}).get("settings") or {}
    return {
        "business_card": settings.get("business_card") or {},
        "settings": settings,
    }


async def _daily_cost_estimate(tenant_id: str) -> float:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    total = 0.0
    async for r in db.ai_prompt_runs.find(
        {"tenant_id": tenant_id, "ran_at": {"$gte": since}},
        {"_id": 0, "api_cost_usd": 1},
    ):
        total += float(r.get("api_cost_usd") or 0)
    return round(total, 4)


# ──────────────────────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────────────────────
class PromptIn(BaseModel):
    prompt_text: str = Field(..., min_length=3, max_length=250)
    priority: Optional[int] = 5
    tags: Optional[List[str]] = None


@router.get("/ai-visibility/prompts", operation_id="aiVisibility.prompts.list")
async def list_prompts(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    rows = await db.ai_prompts.find({"tenant_id": tid, "is_active": {"$ne": False}},
                                       {"_id": 0}).to_list(MAX_PROMPTS_PER_TENANT + 5)
    rows.sort(key=lambda r: (-(r.get("priority") or 5), r.get("added_at") or ""))
    return {"total": len(rows), "prompts": rows}


@router.post("/ai-visibility/prompts", operation_id="aiVisibility.prompts.add")
async def add_prompt(body: PromptIn,
                       user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    n = await db.ai_prompts.count_documents({"tenant_id": tid,
                                                "is_active": {"$ne": False}})
    if n >= MAX_PROMPTS_PER_TENANT:
        raise HTTPException(400, f"Prompt cap ({MAX_PROMPTS_PER_TENANT}) reached")
    txt = body.prompt_text.strip()
    if await db.ai_prompts.find_one({"tenant_id": tid,
                                        "prompt_text_lc": txt.lower(),
                                        "is_active": {"$ne": False}}):
        raise HTTPException(409, "Prompt already tracked")
    doc = {
        "id": new_id(), "tenant_id": tid,
        "prompt_text": txt, "prompt_text_lc": txt.lower(),
        "priority": int(body.priority or 5),
        "tags": body.tags or [],
        "is_active": True,
        "added_at": now_iso(),
        "added_by_user_id": user.get("id"),
        "last_run_at": None,
    }
    await db.ai_prompts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/ai-visibility/prompts/{pid}", operation_id="aiVisibility.prompts.delete")
async def delete_prompt(pid: str,
                          user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    r = await db.ai_prompts.update_one(
        {"id": pid, "tenant_id": tid},
        {"$set": {"is_active": False, "deleted_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Unknown prompt")
    return {"ok": True}


# ──────────────────────────────────────────────────────────────────────
# Run-now (all 4 providers)
# ──────────────────────────────────────────────────────────────────────
@router.post("/ai-visibility/prompts/{pid}/run-now",
              operation_id="aiVisibility.runNow")
async def run_now(pid: str,
                    user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    prompt = await db.ai_prompts.find_one({"id": pid, "tenant_id": tid,
                                              "is_active": True}, {"_id": 0})
    if not prompt:
        raise HTTPException(404, "Unknown prompt")

    # Cooldown 6h
    last = prompt.get("last_run_at")
    if last:
        try:
            t = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - t < timedelta(hours=REFRESH_COOLDOWN_HOURS):
                remaining = REFRESH_COOLDOWN_HOURS - int(
                    (datetime.now(timezone.utc) - t).total_seconds() // 3600)
                raise HTTPException(429, f"Cooldown — retry in ~{max(1, remaining)}h")
        except HTTPException: raise
        except Exception: pass

    # Cost cap
    est = await _daily_cost_estimate(tid)
    if est > DAILY_COST_CAP_USD:
        raise HTTPException(429,
            f"Daily cost cap ${DAILY_COST_CAP_USD} reached (est ${est}) — try again tomorrow")

    ctx = await _tenant_context(tid)
    brand_terms = _brand_terms(ctx["business_card"], ctx["settings"])
    competitors = ((ctx["settings"].get("ai_visibility") or {}).get("competitor_names") or [])

    import asyncio as _aio
    provider_names = list(PROVIDERS.keys())
    responses = await _aio.gather(
        *[PROVIDERS[p](prompt["prompt_text"]) for p in provider_names],
        return_exceptions=True,
    )
    now = now_iso()
    results: List[Dict[str, Any]] = []
    for name, res in zip(provider_names, responses):
        if isinstance(res, Exception):
            res = {"error": "exception", "reason": str(res)[:200]}
        row = {
            "id": new_id(), "tenant_id": tid, "prompt_id": pid,
            "provider": name, "ran_at": now,
            "response_text": res.get("response_text") or "",
            "sources": res.get("sources") or [],
            "api_cost_usd": res.get("api_cost_usd"),
            "error": res.get("error"),
            "error_reason": res.get("reason"),
        }
        det = detect_mention(row["response_text"], brand_terms)
        row["brand_mention_found"] = det["found"]
        row["brand_mention_context"] = det["context"]
        row["brand_mention_matched_term"] = det["matched_term"]
        row["competitors_detected"] = detect_competitors(row["response_text"], competitors)
        await db.ai_prompt_runs.insert_one(row)
        row.pop("_id", None)
        results.append(row)

    await db.ai_prompts.update_one(
        {"id": pid}, {"$set": {"last_run_at": now}},
    )
    return {"prompt_id": pid, "ran_at": now, "results": results}


# ──────────────────────────────────────────────────────────────────────
# Latest + History + Settings
# ──────────────────────────────────────────────────────────────────────
@router.get("/ai-visibility/latest", operation_id="aiVisibility.latest")
async def latest(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    prompts = await db.ai_prompts.find({"tenant_id": tid,
                                           "is_active": {"$ne": False}},
                                          {"_id": 0}).to_list(50)
    by_prompt: Dict[str, Dict[str, Any]] = {}
    total_mentions = 0
    total_runs = 0
    per_provider: Dict[str, Dict[str, int]] = {p: {"runs": 0, "mentions": 0} for p in PROVIDERS}
    for p in prompts:
        # Latest run per (prompt, provider).
        entry: Dict[str, Any] = {"prompt": p, "providers": {}}
        for pname in PROVIDERS:
            r = await db.ai_prompt_runs.find_one(
                {"tenant_id": tid, "prompt_id": p["id"], "provider": pname},
                {"_id": 0}, sort=[("ran_at", -1)],
            )
            if r:
                entry["providers"][pname] = r
                total_runs += 1
                per_provider[pname]["runs"] += 1
                if r.get("brand_mention_found"):
                    total_mentions += 1
                    per_provider[pname]["mentions"] += 1
            else:
                entry["providers"][pname] = None
        by_prompt[p["id"]] = entry
    mention_rate = round(total_mentions / total_runs * 100, 1) if total_runs else 0.0
    return {
        "total_prompts": len(prompts),
        "total_runs": total_runs,
        "total_mentions": total_mentions,
        "mention_rate_pct": mention_rate,
        "per_provider": per_provider,
        "by_prompt": by_prompt,
    }


@router.get("/ai-visibility/history", operation_id="aiVisibility.history")
async def history(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    snaps = await db.ai_visibility_snapshots.find(
        {"tenant_id": tid}, {"_id": 0},
    ).sort("week_start_at", -1).to_list(12)
    snaps.reverse()
    return {"total": len(snaps), "snapshots": snaps}


class SettingsBody(BaseModel):
    brand_aliases: Optional[List[str]] = None
    competitor_names: Optional[List[str]] = None
    weekly_ai_visibility_digest_enabled: Optional[bool] = None


@router.get("/ai-visibility/settings", operation_id="aiVisibility.settings.get")
async def get_settings(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    t = await db.tenants.find_one({"id": tid},
                                     {"_id": 0, "settings": 1})
    s = (t or {}).get("settings") or {}
    aiv = s.get("ai_visibility") or {}
    return {
        "brand_aliases": aiv.get("brand_aliases") or [],
        "competitor_names": aiv.get("competitor_names") or [],
        "weekly_ai_visibility_digest_enabled":
            s.get("weekly_ai_visibility_digest_enabled", True),
        "provider_status": provider_status(),
        "daily_cost_estimate_usd": await _daily_cost_estimate(tid),
        "daily_cost_cap_usd": DAILY_COST_CAP_USD,
    }


@router.patch("/ai-visibility/settings", operation_id="aiVisibility.settings.patch")
async def patch_settings(body: SettingsBody,
                           user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    updates: Dict[str, Any] = {}
    if body.brand_aliases is not None:
        updates["settings.ai_visibility.brand_aliases"] = [
            s.strip() for s in body.brand_aliases if isinstance(s, str) and s.strip()
        ]
    if body.competitor_names is not None:
        aliases = [s.strip() for s in body.competitor_names if isinstance(s, str) and s.strip()]
        if len(aliases) > 15:
            raise HTTPException(422, "Competitor cap is 15")
        updates["settings.ai_visibility.competitor_names"] = aliases
    if body.weekly_ai_visibility_digest_enabled is not None:
        updates["settings.weekly_ai_visibility_digest_enabled"] = \
            bool(body.weekly_ai_visibility_digest_enabled)
    if updates:
        await db.tenants.update_one({"id": tid}, {"$set": updates})
    return await get_settings(user)


def provider_status() -> Dict[str, Dict[str, Any]]:
    return {
        "claude":         {"enabled": bool(os.environ.get("EMERGENT_LLM_KEY"))},
        "perplexity":     {"enabled": bool(os.environ.get("PERPLEXITY_API_KEY"))},
        "gemini":         {"enabled": bool(os.environ.get("GEMINI_API_KEY"))},
        "dataforseo_aio": {"enabled": bool(dfs._creds())},
    }


# ──────────────────────────────────────────────────────────────────────
# Boot seed + weekly cron (feature-flagged off)
# ──────────────────────────────────────────────────────────────────────
async def run_ai_visibility_seed() -> Dict[str, int]:
    """Idempotent seed — for every tenant with zero AI prompts, insert
    the 7 default prompts. Never overwrites existing prompts."""
    seeded = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        if not tid: continue
        n = await db.ai_prompts.count_documents({"tenant_id": tid})
        if n > 0: continue
        for i, p in enumerate(SEED_PROMPTS):
            await db.ai_prompts.insert_one({
                "id": new_id(), "tenant_id": tid,
                "prompt_text": p, "prompt_text_lc": p.lower(),
                "priority": 10 - i,
                "tags": ["seeded"], "is_active": True,
                "added_at": now_iso(), "added_by_user_id": None,
                "last_run_at": None,
            })
        seeded += 1
    return {"tenants_seeded": seeded}


async def run_weekly_ai_visibility_tracker() -> Dict[str, int]:
    """Weekly cron — MANUAL-only until AI_VISIBILITY_CRON_ENABLED=true."""
    if os.environ.get("AI_VISIBILITY_CRON_ENABLED", "false").lower() != "true":
        logger.info("[aiv-cron] skipped (AI_VISIBILITY_CRON_ENABLED != true)")
        return {"skipped": 1, "prompts_run": 0}
    return {"skipped": 0, "prompts_run": 0}  # cron body deferred
