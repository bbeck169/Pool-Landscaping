# ruff: noqa: F403,F405
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from models import AIChatIn, AccessUpdate
from services.llm_provider import call_llm_with_fallback
from services.ai.cap_http import raise_if_ai_cap_exceeded

router = APIRouter()


# ----------------------- Admin: AI Employees -----------------------
AI_EMPLOYEES = [
    {"id": "sales", "name": "Sky", "role": "Sales Assistant", "icon": "trending-up",
     "tagline": "Drafts quotes, follow-ups & win-back messages.",
     "system": "You are Sky, a friendly sales assistant for a pool & landscaping company called Pool & Landscaping of Vistancia. Help draft persuasive but concise customer messages, quote follow-ups, and win-back offers. Keep responses under 150 words and action-oriented."},
    {"id": "support", "name": "Marina", "role": "Customer Support", "icon": "chatbubbles",
     "tagline": "Answers customer questions & handles scheduling.",
     "system": "You are Marina, a warm customer support agent for a pool & landscaping company. Answer customer questions clearly, help with scheduling and service explanations. Be empathetic and concise (under 150 words)."},
    {"id": "ops", "name": "Dex", "role": "Operations Advisor", "icon": "construct",
     "tagline": "Optimizes routes, crews & job planning.",
     "system": "You are Dex, an operations advisor for a pool & landscaping company. Give practical advice on dispatching, route optimization, crew scheduling, and job efficiency. Be direct and use bullet points where helpful (under 150 words)."},
    {"id": "marketing", "name": "Nova", "role": "Marketing Strategist", "icon": "megaphone",
     "tagline": "Writes campaigns, review replies & SEO copy.",
     "system": "You are Nova, a marketing strategist for a pool & landscaping company. Write compelling email/SMS campaign copy, review responses, and local-SEO friendly content. Keep it punchy and on-brand (under 150 words)."},
]


@router.get("/ai-employees/{eid}/history")
async def ai_history(eid: str, session_id: str, user: dict = Depends(require_admin)):
    msgs = await db.ai_messages.find(
        {"session_id": session_id, "employee_id": eid}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    return msgs


@router.post("/ai-employees/chat")
async def ai_chat(body: AIChatIn, user: dict = Depends(require_admin)):
    emp = next((e for e in AI_EMPLOYEES if e["id"] == body.employee_id), None)
    if not emp:
        raise HTTPException(404, "AI employee not found")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(503, "AI is not configured")
    session_id = body.session_id or f"{user['id']}-{body.employee_id}"
    # Persist user message
    await db.ai_messages.insert_one({
        "id": new_id(), "session_id": session_id, "employee_id": body.employee_id,
        "role": "user", "text": body.message, "created_at": now_iso(),
    })
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend caps
        # apply. Same session_id + system_message wiring; plaintext
        # (``parse_json=False``) preserves the legacy string return.
        result = await call_llm_with_fallback(
            system_prompt=emp["system"],
            user_text=body.message,
            provider="anthropic", model="claude-sonnet-4-6",
            tenant_id=user.get("tenant_id"),
            parse_json=False,
        )
        raise_if_ai_cap_exceeded(result)
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        reply = (result.get("raw") or {}).get("text") or ""
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"AI chat failed: {e}")
        raise HTTPException(502, "AI request failed")
    reply_text = reply if isinstance(reply, str) else str(reply)
    await db.ai_messages.insert_one({
        "id": new_id(), "session_id": session_id, "employee_id": body.employee_id,
        "role": "assistant", "text": reply_text, "created_at": now_iso(),
    })
    return {"reply": reply_text, "session_id": session_id}


# ----------------------- Admin: Access Settings -----------------------
ACCESS_MODULES = ["jobs", "schedule", "quotes", "customers", "payments", "reports", "dispatch", "marketing"]
DEFAULT_ACCESS = {
    "technician": {"jobs": True, "schedule": True, "quotes": False, "customers": False, "payments": False, "reports": False, "dispatch": False, "marketing": False},
    "customer": {"jobs": True, "schedule": False, "quotes": True, "customers": False, "payments": True, "reports": False, "dispatch": False, "marketing": False},
}


@router.get("/access-settings")
async def get_access_settings(user: dict = Depends(require_admin)):
    stored = await db.access_settings.find_one({"id": "singleton"}, {"_id": 0})
    matrix = stored["matrix"] if stored else DEFAULT_ACCESS
    return {"modules": ACCESS_MODULES, "matrix": matrix}


@router.put("/access-settings")
async def update_access_settings(body: AccessUpdate, user: dict = Depends(require_admin)):
    stored = await db.access_settings.find_one({"id": "singleton"}, {"_id": 0})
    matrix = stored["matrix"] if stored else {r: dict(v) for r, v in DEFAULT_ACCESS.items()}
    if body.role not in matrix:
        matrix[body.role] = {}
    matrix[body.role][body.module] = body.enabled
    await db.access_settings.update_one(
        {"id": "singleton"}, {"$set": {"id": "singleton", "matrix": matrix}}, upsert=True
    )
    return {"modules": ACCESS_MODULES, "matrix": matrix}


