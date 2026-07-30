"""Phase 6 · Feb-2026 — Reputation response drafts.

Claude-drafted public replies to negative brand mentions from
Phase 5c. Platform-aware prompt, tone knob, 24h dedup per
(mention_id, tone), 10/hr/tenant rate limit (sliding window),
soft-delete via ``status="discarded"``.
"""
from __future__ import annotations

import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config import db, logger  # noqa: F401

DEFAULT_TONES = ("empathetic", "professional", "apologetic", "assertive")
DEFAULT_MODEL = os.environ.get("AEO_DRAFT_MODEL", "claude-sonnet-4-5")
COST_PER_DRAFT_USD = float(os.environ.get("AEO_DRAFT_COST_PER_CALL_USD", "0.005"))

# Platform detection — map by domain (optionally with URL substring).
_PLATFORM_MAP = [
    ("yelp.com",       "yelp"),
    ("nextdoor.com",   "nextdoor"),
    ("reddit.com",     "reddit"),
    ("facebook.com",   "facebook"),
    ("bbb.org",        "bbb"),
]

# Length hint per platform (chars).
LENGTH_HINTS = {
    "yelp":            750,
    "google_reviews":  600,
    "nextdoor":        500,
    "reddit":          400,
    "facebook":        500,
    "bbb":             700,
    "generic":         500,
}

# ── Rate limit — 10 drafts / hour / tenant ────────────────────────
_WINDOW = 3600
_LIMIT = 10
_hits: Dict[str, deque] = defaultdict(deque)


def check_rate_limit(tenant_id: str) -> Optional[int]:
    now = time.time()
    q = _hits[tenant_id]
    while q and now - q[0] > _WINDOW:
        q.popleft()
    if len(q) >= _LIMIT:
        return max(1, int(_WINDOW - (now - q[0])))
    q.append(now)
    return None


def reset_rate_limit_for_tests() -> None:
    _hits.clear()


def detect_platform(domain: str, url: str = "") -> str:
    dom = (domain or "").lower()
    for needle, plat in _PLATFORM_MAP:
        if needle in dom:
            return plat
    if "google.com" in dom and "/maps/" in (url or ""):
        return "google_reviews"
    return "generic"


def _build_prompt(*, tenant: Dict[str, Any], mention: Dict[str, Any],
                    platform: str, tone: str,
                    examples: Optional[List[Dict[str, Any]]] = None
                    ) -> Dict[str, str]:
    name = tenant.get("name") or tenant.get("business_name") or "Your business"
    city = ""
    if isinstance(tenant.get("address"), dict):
        city = tenant["address"].get("city") or ""
    city = city or tenant.get("city") or ""
    phone = tenant.get("phone") or ""
    email = tenant.get("email") or ""
    length = LENGTH_HINTS.get(platform, LENGTH_HINTS["generic"])
    snippet = (mention.get("snippet") or "")[:1200]

    system = (
        "You draft short, professional, empathetic replies from the "
        "business owner to public negative reviews or comments about "
        "their business. Never argue, never blame the reviewer. "
        "Acknowledge the concern, offer a specific next step (contact "
        "number or email from the tenant profile), and thank them. "
        "Match the platform's expected tone."
    )
    # Phase 10 · sub-item D — few-shot conditioning from the tenant's
    # own posted-reply library. `examples` is a list of template dicts.
    if examples:
        try:
            from services.response_library import render_examples_for_prompt
            system += render_examples_for_prompt(examples)
        except Exception:
            pass
    constraints = (
        "\nHard constraints:\n"
        "- Do NOT include the customer's name unless it appears in the snippet.\n"
        "- Do NOT make refund promises.\n"
        "- Do NOT badmouth competitors.\n"
        "- Do NOT include emoji.\n"
        "- Return PLAIN TEXT only (no markdown wrappers, no quotes)."
    )
    user = (
        f"Business: {name} — a pool & landscaping company"
        f"{' in ' + city if city else ''}.\n"
        f"Platform: {platform}. Max length: {length} characters.\n"
        f"Requested tone: {tone}.\n"
        f"Contact on file — phone: {phone or '(not provided)'} · "
        f"email: {email or '(not provided)'}.\n\n"
        f"Public snippet to respond to:\n\"\"\"\n{snippet}\n\"\"\""
        f"{constraints}"
    )
    return {"system": system, "user": user, "max_chars": length}


async def _default_llm_call(system: str, user: str) -> Dict[str, Any]:
    from services.llm_provider import _call_emergent_text
    r = await _call_emergent_text(
        system_prompt=system, user_text=user,
        provider="anthropic", model=DEFAULT_MODEL,
    )
    if r.get("error"):
        return {"error": r["error"]}
    raw = r.get("raw") or r
    text = ""
    if isinstance(raw, dict):
        text = raw.get("answer") or raw.get("text") or ""
    if not text:
        text = str(r.get("_raw_text", "")) or str(raw)[:2000]
    return {"text": text.strip(), "tokens_used": r.get("tokens_used", 0)}


async def _find_cached_draft(tenant_id: str, mention_id: str,
                                tone: str) -> Optional[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.mention_response_drafts.find_one(
        {"tenant_id": tenant_id, "mention_id": mention_id, "tone": tone,
          "status": {"$ne": "discarded"},
          "drafted_at": {"$gte": cutoff}},
        {"_id": 0}, sort=[("drafted_at", -1)])


async def create_or_get_draft(*, tenant: Dict[str, Any],
                                 mention: Dict[str, Any],
                                 tone: str = "empathetic",
                                 regenerate: bool = False,
                                 user_id: str = "",
                                 llm_call: Callable[[str, str], Awaitable[Dict[str, Any]]]
                                              = _default_llm_call,
                                 ) -> Dict[str, Any]:
    tenant_id = tenant.get("id") or tenant.get("tenant_id")
    if tone not in DEFAULT_TONES:
        tone = "empathetic"

    if not regenerate:
        cached = await _find_cached_draft(tenant_id, mention["mention_id"], tone)
        if cached:
            return {"cached": True, **cached}

    platform = detect_platform(mention.get("domain") or "",
                                 mention.get("url") or "")
    # Phase 10 · sub-item D — pull up to 3 in-context examples from the
    # tenant's own template library.
    examples: List[Dict[str, Any]] = []
    try:
        from services.response_library import top_templates_for
        examples = await top_templates_for(tenant_id=tenant_id,
                                              platform=platform, tone=tone,
                                              limit=3)
    except Exception:
        examples = []
    prompt = _build_prompt(tenant=tenant, mention=mention,
                             platform=platform, tone=tone,
                             examples=examples)
    r = await llm_call(prompt["system"], prompt["user"])
    if r.get("error"):
        return {"error": r["error"]}
    text = (r.get("text") or "").strip()
    if not text:
        return {"error": "empty_response"}

    now = datetime.now(timezone.utc).isoformat()
    draft = {
        "tenant_id": tenant_id,
        "draft_id": f"drft_{uuid.uuid4().hex[:16]}",
        "mention_id": mention["mention_id"],
        "platform": platform,
        "draft_text": text,
        "tone": tone,
        "drafted_at": now,
        "drafted_by": user_id or "",
        "model_used": DEFAULT_MODEL,
        "tokens_used": int(r.get("tokens_used") or 0),
        "cost_est_usd": COST_PER_DRAFT_USD,
        "status": "draft",
        "status_updated_at": now,
        "max_chars": prompt["max_chars"],
    }
    await db.mention_response_drafts.insert_one({**draft})
    # Mirror on the mention doc.
    await db.brand_mentions.update_one(
        {"tenant_id": tenant_id, "mention_id": mention["mention_id"]},
        {"$set": {"has_response_draft": True,
                    "latest_draft_status": "draft"}})
    return {"cached": False, **draft}


async def list_drafts(tenant_id: str, mention_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    async for d in db.mention_response_drafts.find(
        {"tenant_id": tenant_id, "mention_id": mention_id},
        {"_id": 0},
    ).sort("drafted_at", -1):
        out.append(d)
    return out


async def update_draft(*, tenant_id: str, draft_id: str,
                          edited_text: Optional[str] = None,
                          status: Optional[str] = None,
                          user_id: str = "") -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    setter: Dict[str, Any] = {}
    if edited_text is not None:
        setter["edited_text"] = edited_text[:8000]
        setter["edited_at"] = now
        setter["edited_by"] = user_id or ""
    if status is not None:
        if status not in ("draft", "copied", "posted", "discarded"):
            return {"error": "invalid_status"}
        setter["status"] = status
        setter["status_updated_at"] = now
        setter["status_updated_by"] = user_id or ""
    if not setter:
        return {"error": "no_updates"}
    doc = await db.mention_response_drafts.find_one_and_update(
        {"tenant_id": tenant_id, "draft_id": draft_id},
        {"$set": setter},
        return_document=True,
        projection={"_id": 0},
    )
    if not doc:
        return {"error": "not_found"}
    if status:
        await db.brand_mentions.update_one(
            {"tenant_id": tenant_id, "mention_id": doc["mention_id"]},
            {"$set": {"latest_draft_status": status}})
        # Phase 10 · sub-item D — auto-capture posted drafts into the
        # response-library. Failures never bubble.
        if status == "posted":
            try:
                from services.response_library import capture_template_from_draft
                await capture_template_from_draft(tenant_id=tenant_id, draft=doc)
            except Exception:
                pass
    return doc


async def pending_draft_count(tenant_id: str) -> int:
    return await db.mention_response_drafts.count_documents(
        {"tenant_id": tenant_id, "status": {"$in": ["draft", "copied"]}})
