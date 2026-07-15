"""Phase 27.1 · Customer Churn Analyzer.

Live Claude scoring (no silent mocks). One doc per customer in
`customer_churn_scores`, upsert on rescore. Weekly APScheduler cron.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger, EMERGENT_LLM_KEY
from utils import get_current_user, new_id, now_iso, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

_MODEL_VERSION = "churn.v1.claude-sonnet-4-6"

_SYSTEM = (
    "You are a customer-success analyst for a pool + landscaping company. "
    "Assess churn risk on a 0-100 scale given the signals below. "
    "Return STRICT JSON only, no prose, matching exactly:\n"
    "{\n"
    '  "risk_score": <int 0-100>,\n'
    '  "tier": "low" | "medium" | "high" | "critical",\n'
    '  "top_signals": [<str>, ... max 5],\n'
    '  "recommended_actions": [<str>, ... max 3],\n'
    '  "mocked": false\n'
    "}\n"
    "Thresholds: 0-29 low · 30-54 medium · 55-79 high · 80-100 critical."
)


def _tier_from_score(s: int) -> str:
    if s < 30: return "low"
    if s < 55: return "medium"
    if s < 80: return "high"
    return "critical"


async def _signal_bundle(tenant_id: str, customer_id: str) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    csat = await db.csat_responses.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "created_at": {"$gte": since}}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    completed = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "status": "completed",
          "$or": [{"scheduled_date": {"$gte": since[:10]}},
                    {"created_at": {"$gte": since}}]})
    cancelled = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "status": "cancelled"})
    chats = await db.portal_chats.find(
        {"tenant_id": tenant_id, "customer_id": customer_id,
          "created_at": {"$gte": since}},
        {"_id": 0, "message": 1, "created_at": 1, "sender_role": 1},
    ).sort("created_at", -1).limit(30).to_list(30)
    complaints = [c for c in chats
                     if any(k in (c.get("message") or "").lower()
                              for k in ("complaint", "unhappy",
                                          "cancel", "refund", "terrible",
                                          "awful"))]
    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0}) or {}
    nps_avg = None
    if csat:
        scores = [x.get("score") for x in csat if x.get("score") is not None]
        if scores: nps_avg = round(sum(scores) / len(scores), 1)
    return {
        "customer_name": customer.get("name"),
        "tenure_days": (
            (datetime.now(timezone.utc)
              - datetime.fromisoformat(customer.get("created_at",
                    datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00"))).days
            if customer.get("created_at") else None),
        "nps_responses_90d": len(csat),
        "nps_avg_90d": nps_avg,
        "last_nps_score": (csat[0].get("score") if csat else None),
        "last_nps_at": (csat[0].get("created_at") if csat else None),
        "completed_jobs_90d": completed,
        "cancelled_jobs_lifetime": cancelled,
        "chat_messages_90d": len(chats),
        "complaint_keywords_90d": len(complaints),
        "tags": customer.get("tags") or [],
    }


async def _call_claude(signals: Dict[str, Any]) -> Dict[str, Any]:
    if not EMERGENT_LLM_KEY:
        return {"mocked": True,
                 "reason": "EMERGENT_LLM_KEY not configured",
                 "risk_score": 50, "tier": "medium",
                 "top_signals": [], "recommended_actions": []}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return {"mocked": True, "reason": f"llm import failed: {e}",
                 "risk_score": 50, "tier": "medium",
                 "top_signals": [], "recommended_actions": []}
    prompt = ("Signal bundle (last 90 days unless noted):\n"
                + json.dumps(signals, indent=2, default=str))
    try:
        chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=new_id(),
                         system_message=_SYSTEM)
                .with_model("anthropic", "claude-sonnet-4-6"))
        raw = await chat.send_message(UserMessage(text=prompt))
        text = raw if isinstance(raw, str) else str(raw)
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
        try: data = json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\})", text, re.S)
            data = json.loads(m.group(1)) if m else {}
        score = max(0, min(100, int(data.get("risk_score", 50))))
        return {
            "mocked": False,
            "risk_score": score,
            "tier": data.get("tier") or _tier_from_score(score),
            "top_signals": (data.get("top_signals") or [])[:5],
            "recommended_actions":
                (data.get("recommended_actions") or [])[:3],
        }
    except Exception as e:
        logger.warning(f"Churn LLM failed: {e}")
        return {"mocked": True, "reason": f"llm error: {e}",
                 "risk_score": 50, "tier": "medium",
                 "top_signals": [], "recommended_actions": []}


async def _analyze_and_store(tenant_id: str, customer_id: str) -> Dict[str, Any]:
    signals = await _signal_bundle(tenant_id, customer_id)
    scored = await _call_claude(signals)
    doc = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "risk_score": scored["risk_score"],
        "tier": scored["tier"],
        "top_signals": scored["top_signals"],
        "recommended_actions": scored["recommended_actions"],
        "signals_snapshot": signals,
        "mocked": scored.get("mocked", False),
        "reason": scored.get("reason"),
        "analyzed_at": now_iso(),
        "model_version": _MODEL_VERSION,
    }
    await db.customer_churn_scores.update_one(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"$set": doc, "$setOnInsert": {"id": new_id(),
                                             "created_at": now_iso()}},
        upsert=True,
    )
    out = await db.customer_churn_scores.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id},
        {"_id": 0})
    return out


@router.post("/churn/analyze/{customer_id}")
async def churn_analyze(customer_id: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    return await _analyze_and_store(tenant["id"], customer_id)


@router.post("/churn/analyze-all")
async def churn_analyze_all(user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    cids = await db.customers.find(
        {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1}).to_list(2000)
    scored = 0; at_risk = 0; critical = 0; mocked_any = False
    for c in cids:
        try:
            result = await _analyze_and_store(tenant["id"], c["id"])
            scored += 1
            if result["risk_score"] >= 55: at_risk += 1
            if result["tier"] == "critical": critical += 1
            if result.get("mocked"): mocked_any = True
        except Exception as ex:
            logger.warning(f"Churn scoring failed for {c['id']}: {ex}")
    return {"scored": scored, "at_risk_count": at_risk,
             "critical_count": critical,
             "mocked": mocked_any}


@router.get("/churn/scores")
async def churn_list(tier: Optional[str] = None,
                          min: int = Query(0, ge=0, le=100),
                          max: int = Query(100, ge=0, le=100),
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"],
                            "risk_score": {"$gte": min, "$lte": max}}
    if tier: q["tier"] = tier
    rows = await db.customer_churn_scores.find(
        q, {"_id": 0}).sort("risk_score", -1).to_list(2000)
    # Join customer name for convenience.
    cids = [r["customer_id"] for r in rows]
    custs = await db.customers.find(
        {"id": {"$in": cids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    ).to_list(2000)
    by_id = {c["id"]: c for c in custs}
    for r in rows:
        c = by_id.get(r["customer_id"]) or {}
        r["customer_name"] = c.get("name")
        r["customer_email"] = c.get("email")
    return {"items": rows, "total": len(rows),
             "counts_by_tier": {
                 "low":     sum(1 for r in rows if r["tier"] == "low"),
                 "medium":  sum(1 for r in rows if r["tier"] == "medium"),
                 "high":    sum(1 for r in rows if r["tier"] == "high"),
                 "critical":sum(1 for r in rows if r["tier"] == "critical"),
             }}


@router.get("/churn/customer/{customer_id}")
async def churn_customer_detail(customer_id: str,
                                     user: dict = Depends(require_admin),
                                     tenant: dict = Depends(get_current_tenant)):
    doc = await db.customer_churn_scores.find_one(
        {"tenant_id": tenant["id"], "customer_id": customer_id},
        {"_id": 0})
    if not doc:
        raise HTTPException(404, "No score yet — run analyze first")
    return doc


async def scheduled_churn_scan_all():
    """Weekly cron entry — refreshes scores for every tenant."""
    tenants = await db.tenants.find({}, {"_id": 0, "id": 1}).to_list(500)
    for t in tenants:
        try:
            cids = await db.customers.find(
                {"tenant_id": t["id"]}, {"_id": 0, "id": 1}).to_list(2000)
            for c in cids:
                await _analyze_and_store(t["id"], c["id"])
        except Exception as ex:
            logger.warning(f"Churn cron failed for {t['id']}: {ex}")
