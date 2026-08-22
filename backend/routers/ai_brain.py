"""Feb-2026 · Item 4 — Master AI knowledge base + Copilot backend.

Adds:

* ``ai_knowledge_base`` collection — admin-curated Markdown chunks
  (company profile, FAQs, policies, custom) that get concatenated
  into the system prompt for every LLM-driven feature.
* ``ai_copilot_log`` collection — one row per Copilot conversation
  turn for audit + billing insight.
* CRUD endpoints (admin only) for the knowledge base.
* ``POST /api/ai/copilot/message`` — read-only chat with tenant-scoped
  server-side tools (list_customers, get_customer, revenue_forecast,
  list_leads, list_jobs, communications_log).

The Copilot NEVER mutates data. Every tool auto-injects
``tenant_id`` from the authenticated admin session so the LLM
cannot query across tenants.

Feb-2026 · P22 — Privacy audit note
-----------------------------------
The Copilot tools (``list_customers``, ``get_customer``,
``communications_log``) are DESIGNED to answer admin queries such as
"find customer Garcia's account" and "when did we last message Jane".
By nature the LLM receives customer names, emails, phones, and
service addresses in the tool-result JSON that is fed back as a
follow-up ``UserMessage``.

This is an **intentional carve-out** from the P21 Privacy Policy
claim that we do not send customer PII to LLM providers. The carve-
out is disclosed in the Privacy Policy (§4 vendor table entry for
"OpenAI / Anthropic (via Emergent LLM Key)").  The claim, restated
precisely, is:

  * Standard operational LLM surfaces (Marina auto-reply, Vizzy
    call prep, Dexter analytics, Churn scoring, Retention drafts,
    Check-in rewrites, Review replies, etc.) do NOT send raw
    customer PII to LLM providers — they use symbolic references
    and redaction.
  * The Admin Copilot is an EXCEPTION: authenticated admin users
    may explicitly request customer data via natural-language
    queries. Per our Emergent LLM Key agreement with Anthropic,
    these requests are subject to a zero-retention policy and are
    not used for model training.

Any future addition of a new tool that returns customer PII must be
disclosed the same way.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()
_ADMIN_ROLES = {"admin", "super_admin"}

_KIND_VALUES = {"company_profile", "faq", "policy", "custom"}


def _require_admin(user: dict):
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


class KnowledgeIn(BaseModel):
    kind: str = Field("custom", pattern="^(company_profile|faq|policy|custom)$")
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)
    is_active: bool = True


class KnowledgePatch(BaseModel):
    kind: Optional[str] = Field(None, pattern="^(company_profile|faq|policy|custom)$")
    title: Optional[str] = None
    content_md: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


# ══════════════════════════════════════════════════════════════
# Knowledge base CRUD
# ══════════════════════════════════════════════════════════════
@router.get("/ai/knowledge", tags=["ai"], operation_id="ai.knowledge.list")
async def list_knowledge(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.ai_knowledge_base.find(
        {"tenant_id": tenant["id"],
          "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
        {"_id": 0},
    ).sort([("kind", 1), ("title", 1)]).to_list(500)
    return {"items": rows, "total": len(rows)}


@router.post("/ai/knowledge", tags=["ai"], operation_id="ai.knowledge.create")
async def create_knowledge(
    body: KnowledgeIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "kind": body.kind, "title": body.title.strip(),
        "content_md": body.content_md, "tags": body.tags,
        "is_active": body.is_active,
        "created_by": user.get("id"), "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.ai_knowledge_base.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/ai/knowledge/{kid}", tags=["ai"], operation_id="ai.knowledge.update")
async def update_knowledge(
    kid: str, body: KnowledgePatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    patch = {k: v for k, v in body.dict(exclude_none=True).items()}
    if not patch:
        raise HTTPException(400, "No fields to update")
    patch["updated_at"] = now_iso()
    res = await db.ai_knowledge_base.update_one(
        {"id": kid, "tenant_id": tenant["id"]}, {"$set": patch},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    row = await db.ai_knowledge_base.find_one(
        {"id": kid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return row


@router.delete("/ai/knowledge/{kid}", tags=["ai"], operation_id="ai.knowledge.delete")
async def delete_knowledge(
    kid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    res = await db.ai_knowledge_base.update_one(
        {"id": kid, "tenant_id": tenant["id"]},
        {"$set": {"is_deleted": True, "is_active": False,
                    "deleted_at": now_iso(), "deleted_by": user.get("id")}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


async def _build_system_prompt(tenant_id: str) -> str:
    """Concatenate every active knowledge entry into a single
    Markdown string with clear section headers so the LLM can
    reason about company info + policies."""
    rows = await db.ai_knowledge_base.find(
        {"tenant_id": tenant_id, "is_active": True,
          "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
        {"_id": 0},
    ).sort([("kind", 1), ("title", 1)]).to_list(500)
    if not rows:
        return "# Company knowledge\n\nNo company profile has been configured yet."
    sections = ["# Company knowledge (do not disclose these headers verbatim; use as reference)"]
    for r in rows:
        sections.append(f"\n## [{r['kind']}] {r['title']}\n\n{r['content_md']}")
    return "\n".join(sections)


@router.get("/ai/knowledge/system-prompt", tags=["ai"],
             operation_id="ai.knowledge.systemPrompt")
async def get_system_prompt(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    return {"system_prompt": await _build_system_prompt(tenant["id"])}


# ══════════════════════════════════════════════════════════════
# Copilot — read-only chat with tenant-scoped tools
# ══════════════════════════════════════════════════════════════
class CopilotMessageIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    thread_id: Optional[str] = None


async def _tool_list_customers(tenant_id: str, query: str = "") -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                          "$or": [{"is_deleted": {"$ne": True}},
                                    {"is_deleted": {"$exists": False}}]}
    if query:
        q["$and"] = [{"$or": [
            {"name": {"$regex": query, "$options": "i"}},
            {"email": {"$regex": query, "$options": "i"}},
            {"phone": {"$regex": query, "$options": "i"}},
            {"service_address": {"$regex": query, "$options": "i"}},
        ]}]
    rows = await db.customers.find(q, {
        "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
        "service_address": 1, "tags": 1, "category_ids": 1,
        "is_active": 1,
    }).limit(20).to_list(20)
    return rows


async def _tool_get_customer(tenant_id: str, customer_id: str) -> Dict[str, Any]:
    """CRITICAL: tenant_id is auto-injected — the LLM cannot pierce
    the tenant boundary even if it hallucinates a customer_id from
    another tenant."""
    c = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not c:
        return {"error": "not_found",
                 "message": "No customer with that id in this tenant."}
    comms = await db.marketing_deliveries.find(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0, "channel": 1, "subject": 1, "created_at": 1,
          "delivered": 1, "trigger_entity": 1},
    ).sort("created_at", -1).limit(10).to_list(10)
    from utils import not_deleted_filter as _nd
    jobs = await db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, **_nd()},
        {"_id": 0, "id": 1, "scheduled_date": 1, "status": 1,
          "service_type": 1},
    ).sort("scheduled_date", -1).limit(10).to_list(10)
    return {"customer": c, "recent_comms": comms, "recent_jobs": jobs}


async def _tool_revenue_forecast(tenant_id: str, range_: str = "week") -> Dict[str, Any]:
    from routers.reports import _forecast_series_between  # local import
    from datetime import date, timedelta
    tz_name = "America/Phoenix"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    today = datetime.now(tz).date()
    if range_ == "today":
        start, end = today, today
    elif range_ == "tomorrow":
        start = today + timedelta(days=1); end = start
    elif range_ == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    else:  # month
        start = today.replace(day=1)
        end = (start.replace(month=start.month + 1) if start.month < 12
                else start.replace(year=start.year + 1, month=1)) - timedelta(days=1)
    series = await _forecast_series_between(start, end)
    return {"range": range_, "date_from": start.isoformat(),
             "date_to": end.isoformat(),
             "total": round(sum(x["amount"] for x in series), 2),
             "series": series}


async def _tool_list_leads(tenant_id: str, status: str = "new",
                            limit: int = 20) -> List[Dict[str, Any]]:
    q = {"tenant_id": tenant_id}
    if status and status != "all":
        q["status"] = status
    return await db.leads.find(
        q, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
             "status": 1, "created_at": 1, "state": 1, "city": 1,
             "rejected_reason": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)


async def _tool_list_jobs(tenant_id: str, day: Optional[str] = None,
                           tech_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if day:
        q["scheduled_date"] = {"$regex": f"^{day}"}
    if tech_id:
        q["technician_id"] = tech_id
    return await db.jobs.find(
        q, {"_id": 0, "id": 1, "customer_id": 1, "technician_id": 1,
             "scheduled_date": 1, "scheduled_start_at": 1, "status": 1,
             "service_type": 1},
    ).sort("scheduled_date", -1).limit(50).to_list(50)


async def _tool_communications_log(tenant_id: str, customer_id: Optional[str] = None,
                                     since: Optional[str] = None,
                                     limit: int = 30) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_id:
        q["customer_id"] = customer_id
    if since:
        q["created_at"] = {"$gte": since}
    return await db.marketing_deliveries.find(
        q, {"_id": 0, "channel": 1, "customer_id": 1, "subject": 1,
             "body": 1, "created_at": 1, "delivered": 1,
             "trigger_entity": 1},
    ).sort("created_at", -1).limit(limit).to_list(limit)


_TOOLS = {
    "list_customers":       ("List customers matching a name/email/phone/address search.",
                              _tool_list_customers, ["query"]),
    "get_customer":         ("Get a customer's full profile plus last 10 comms + last 10 jobs.",
                              _tool_get_customer,   ["customer_id"]),
    "revenue_forecast":     ("Get revenue forecast for a range: today/tomorrow/week/month.",
                              _tool_revenue_forecast, ["range"]),
    "list_leads":           ("List leads by status (new/contacted/qualified/converted/rejected).",
                              _tool_list_leads,     ["status", "limit"]),
    "list_jobs":            ("List scheduled jobs, optionally filtered by day (YYYY-MM-DD) or tech id.",
                              _tool_list_jobs,      ["day", "tech_id"]),
    "communications_log":   ("List recent SMS/email deliveries, optionally filtered by customer.",
                              _tool_communications_log, ["customer_id", "since", "limit"]),
}


def _tool_schema_markdown() -> str:
    lines = ["# TOOLS (read-only — tenant_id auto-injected)"]
    for name, (desc, _, params) in _TOOLS.items():
        lines.append(f"- **{name}**({', '.join(params)}): {desc}")
    lines.append(
        "\nWhen you want to call a tool, respond with a JSON code "
        'fence like:\n```tool\n{"name":"list_customers","args":{"query":"garcia"}}\n```\n'
        "The system will substitute the tool output and continue."
    )
    return "\n".join(lines)


async def _run_tool(tenant_id: str, name: str, args: Dict[str, Any]) -> Any:
    spec = _TOOLS.get(name)
    if not spec:
        return {"error": "unknown_tool", "tool": name}
    _desc, fn, _params = spec
    try:
        # Sanitize args — silently drop unexpected keys + coerce simple types.
        clean = {k: v for k, v in (args or {}).items() if isinstance(k, str)}
        if name == "revenue_forecast":
            return await fn(tenant_id, range_=clean.get("range", "week"))
        # Everything else takes ``tenant_id`` first + kwargs.
        return await fn(tenant_id, **clean)
    except TypeError as exc:
        return {"error": "bad_args", "detail": str(exc)}
    except Exception as exc:
        logger.warning("[copilot] tool %s failed: %s", name, exc)
        return {"error": "tool_failed", "detail": str(exc)}


@router.post("/ai/copilot/message", tags=["ai"], operation_id="ai.copilot.message")
async def copilot_message(
    body: CopilotMessageIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    thread_id = body.thread_id or new_id()

    system_prompt = await _build_system_prompt(tenant["id"])
    system_prompt += "\n\n" + _tool_schema_markdown()

    tool_calls: List[Dict[str, Any]] = []
    reply_text = ""
    tokens_used = 0

    # Import the Emergent LLM client. If unavailable (offline sandbox
    # or key not provisioned) we degrade to a canned response so the
    # UI + audit log flow still work — pytest can mock this path.
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
        emergent_key = os.environ.get("EMERGENT_LLM_KEY") or ""
        if not emergent_key:
            raise RuntimeError("EMERGENT_LLM_KEY not set")
        chat = LlmChat(
            api_key=emergent_key,
            session_id=thread_id,
            system_message=system_prompt,
        ).with_model("anthropic", "claude-sonnet-4-5")
        first = await chat.send_message(UserMessage(text=body.message))
        # Basic tool-call loop — up to 3 rounds. Frontier LLMs almost
        # never need more than 2 in this Copilot's read-only shape.
        cur = first
        for _ in range(3):
            if not isinstance(cur, str):
                cur = str(cur)
            # Look for a ```tool ...``` fence.
            fence_open = cur.find("```tool")
            if fence_open < 0:
                break
            fence_close = cur.find("```", fence_open + 7)
            if fence_close < 0:
                break
            raw = cur[fence_open + 7:fence_close].strip()
            try:
                call = json.loads(raw)
            except Exception:
                break
            tname = str(call.get("name") or "")
            targs = call.get("args") or {}
            result = await _run_tool(tenant["id"], tname, targs)
            tool_calls.append({"name": tname, "args": targs,
                                "result_preview": str(result)[:400]})
            follow = f"Tool `{tname}` returned:\n```json\n{json.dumps(result, default=str)[:4000]}\n```"
            cur = await chat.send_message(UserMessage(text=follow))
        reply_text = str(cur)
    except Exception as exc:
        logger.warning("[copilot] LLM path failed: %s", exc)
        reply_text = ("The Copilot's LLM backend isn't reachable right now. "
                       "Your message was recorded. Try again in a moment.")

    log_row = {
        "id": new_id(), "tenant_id": tenant["id"],
        "user_id": user.get("id"), "thread_id": thread_id,
        "prompt": body.message, "response": reply_text,
        "tool_calls": tool_calls, "tokens_used": tokens_used,
        "created_at": now_iso(),
    }
    await db.ai_copilot_log.insert_one(log_row)
    log_row.pop("_id", None)
    return {"thread_id": thread_id, "reply": reply_text,
             "tool_calls": tool_calls}


# ══════════════════════════════════════════════════════════════
# Feb-2026 · Item 4 bonus — Top admin questions widget.
# Groups ai_copilot_log entries by prompt (case-insensitive) over
# the last N days and returns the most frequently asked questions.
# Powers the AI Brain page dashboard so admins can quickly promote
# common Copilot prompts into their knowledge base.
# ══════════════════════════════════════════════════════════════
@router.get("/ai/copilot/top-questions", tags=["ai"],
             operation_id="ai.copilot.topQuestions")
async def top_questions(
    days: int = 30,
    limit: int = 10,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 10), 50))
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"tenant_id": tenant["id"], "created_at": {"$gte": since},
                     "prompt": {"$exists": True, "$ne": ""}}},
        # Normalize (lowercase + trim) so "How many customers?" and
        # "how many customers?  " group together.
        {"$addFields": {"_norm": {"$toLower": {"$trim": {"input": "$prompt"}}}}},
        {"$group": {
            "_id": "$_norm",
            "count": {"$sum": 1},
            "last_prompt": {"$last": "$prompt"},
            "last_response": {"$last": "$response"},
            "last_asked_at": {"$max": "$created_at"},
        }},
        {"$sort": {"count": -1, "last_asked_at": -1}},
        {"$limit": limit},
    ]
    rows = await db.ai_copilot_log.aggregate(pipeline).to_list(limit)
    return {
        "days": days,
        "total": len(rows),
        "items": [
            {"prompt": r.get("last_prompt") or r.get("_id"),
             "count": int(r.get("count") or 0),
             "last_asked_at": r.get("last_asked_at"),
             "last_response": (r.get("last_response") or "")[:400]}
            for r in rows
        ],
    }



# ══════════════════════════════════════════════════════════════
# Feb-2026 · Phase 20 P2 — Admin toggle for the daily review digest.
# Persists to ``tenants.settings.daily_review_digest_enabled``.
# ══════════════════════════════════════════════════════════════
class DigestToggleIn(BaseModel):
    enabled: bool


@router.get("/ai/settings/daily-review-digest", tags=["ai"],
             operation_id="ai.settings.dailyReviewDigest.get")
async def get_digest_toggle(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    settings = (tenant or {}).get("settings") or {}
    enabled = settings.get("daily_review_digest_enabled")
    # Default is True — the cron opts you IN unless you explicitly
    # opt out.
    return {"enabled": True if enabled is None else bool(enabled)}


@router.patch("/ai/settings/daily-review-digest", tags=["ai"],
               operation_id="ai.settings.dailyReviewDigest.patch")
async def patch_digest_toggle(
    body: DigestToggleIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    await db.tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"settings.daily_review_digest_enabled": bool(body.enabled)}},
    )
    return {"ok": True, "enabled": bool(body.enabled)}


# ═════════════════════════════════════════════════════════════
# Feb-2026 · smart enhancement — Weekly AI Employees Summary tile.
# 5-minute per-tenant in-memory cache; bust via ``?refresh=1``.
# ═════════════════════════════════════════════════════════════
import time as _time
from datetime import timedelta as _td

_WEEKLY_CACHE: dict = {}
_WEEKLY_TTL_S = 300


@router.get("/ai/employees/weekly-summary", tags=["ai"],
             operation_id="ai.employees.weeklySummary")
async def weekly_ai_employees_summary(
    refresh: int = 0,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    tid = tenant["id"]
    ck = f"weekly:{tid}"
    if not refresh:
        cached = _WEEKLY_CACHE.get(ck)
        if cached and (_time.time() - cached["_at"]) < _WEEKLY_TTL_S:
            return cached["payload"]

    now = datetime.now(timezone.utc)
    week_start = now - _td(days=7)
    prev_start = now - _td(days=14)
    prev_end = now - _td(days=7)

    drafts = await db.gbp_post_drafts.count_documents({
        "tenant_id": tid,
        "generated_at": {"$gte": week_start.isoformat()},
    })

    reviews_answered = await db.reviews.count_documents({
        "tenant_id": tid,
        "$or": [
            {"suggested_reply_generated_at": {"$gte": week_start.isoformat()}},
            {"admin_replied_at": {"$gte": week_start.isoformat()}},
        ],
    })

    scan = await db.seo_scans.find_one(
        {"tenant_id": tid}, {"_id": 0, "score": 1},
        sort=[("run_at", -1)],
    )
    seo_score_latest = int((scan or {}).get("score")) if scan else None

    async def _avg(start_iso, end_iso):
        pipe = [
            {"$match": {"tenant_id": tid,
                         "created_at": {"$gte": start_iso, "$lt": end_iso},
                         "star_rating": {"$gte": 1, "$lte": 5}}},
            {"$group": {"_id": None, "count": {"$sum": 1},
                         "avg": {"$avg": "$star_rating"}}},
        ]
        rows = await db.reviews.aggregate(pipe).to_list(1)
        if not rows:
            return 0, 0.0
        return int(rows[0].get("count") or 0), float(rows[0].get("avg") or 0.0)

    this_count, this_avg = await _avg(week_start.isoformat(), now.isoformat())
    _prev_count, prev_avg = await _avg(prev_start.isoformat(), prev_end.isoformat())
    if this_count and _prev_count:
        star_delta = round(this_avg - prev_avg, 2)
    else:
        star_delta = None

    payload = {
        "tenant_id": tid,
        "week_start_at": week_start.isoformat(),
        "week_end_at": now.isoformat(),
        "drafts_generated": int(drafts),
        "reviews_answered": int(reviews_answered),
        "seo_score_latest": seo_score_latest,
        "star_delta": star_delta,
        "total_reviews_last_week": this_count,
        "generated_at": now.isoformat(),
    }
    _WEEKLY_CACHE[ck] = {"_at": _time.time(), "payload": payload}
    return payload
