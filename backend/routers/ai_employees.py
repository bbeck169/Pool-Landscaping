"""AE1 · AI Employees foundation + Casey (Feb-2026 ship).

Ships the shared substrate every AI employee slice will build on:

* ``ai_employees`` — per-tenant roster of 8 default employees.
  Idempotently seeded on tenant boot; admins can rename, tweak the
  system prompt, or disable each one.
* ``ai_employee_conversations`` — persistent chat threads (one thread
  per employee per user, with optional named threads for topical work).
* ``ai_employee_messages`` — role=`user` / `assistant` / `system` turn
  log. Assistant messages carry the debited credit amount + provider
  tokens on ``meta``.
* ``ai_employee_actions`` — queue of destructive/external actions that
  the employee proposes. Every action lands in ``status="pending"``
  and requires an admin ``approve`` before it executes. Non-destructive
  drafts (text-only) never enter this queue.
* ``brand_brain`` — a single per-tenant shared context blob that every
  employee's system prompt reads before responding. One row per tenant.

Casey (Directories AI) ships as the reference implementation here:
casey.draft_directory_submission, casey.suggest_directory_updates,
casey.draft_outreach_reply. Every Casey action is approve-gated.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin
from services.ai_credits import debit_credits

router = APIRouter(tags=["AI Employees"])

# ─── Constants ────────────────────────────────────────────────────────

CHAT_MSG_COST = 1        # credits per chat send
HEAVY_ACTION_COST = 5    # credits per LLM-heavy action (drafts)

DEFAULT_EMPLOYEES: List[Dict[str, Any]] = [
    {"key": "casey",  "name": "Casey",  "role": "Directories",     "avatar_emoji": "📇",
     "system_prompt": (
         "You are Casey, the Directories AI Employee for a pool + landscaping CRM. "
         "You help the admin keep their business listings (Google, Yelp, BBB, "
         "Angi, HomeAdvisor, etc.) consistent, drafted, and current. "
         "Every action you suggest — new submission, update, outreach reply — "
         "lands in an approval queue. NEVER claim you have already published. "
         "Ground your drafts in the tenant's NAP profile (business_name, "
         "phone, address, hours, categories) and brand voice."
     )},
    {"key": "emmie",  "name": "Emmie",  "role": "Email marketing", "avatar_emoji": "✉️",
     "system_prompt": (
         "You are Emmie, an email-marketing copilot. Draft campaigns, subject "
         "lines, and A/B variants. Never mark a campaign live yourself — "
         "propose it and let the admin approve. (Ships in slice AE2.)"
     )},
    {"key": "buddy",  "name": "Buddy",  "role": "Growth analytics", "avatar_emoji": "📈",
     "system_prompt": (
         "You are Buddy, a growth analyst. Weekly briefs on pipeline win "
         "rate, InstaQuote conversion, review sentiment, seasonal trends. "
         "(Ships in slice AE3.)"
     )},
    {"key": "vizzy",  "name": "Vizzy",  "role": "Daily brief",      "avatar_emoji": "🗞️",
     "system_prompt": (
         "You are Vizzy, the admin's morning brief. Jobs today, open "
         "estimates, hot deals, mentions. (Ships in slice AE3.)"
     )},
    {"key": "dexter", "name": "Dexter", "role": "Ad-hoc analytics", "avatar_emoji": "🧮",
     "system_prompt": (
         "You are Dexter, an ad-hoc analytics AI. Answer natural-language "
         "questions with numbers pulled from the CRM. (Ships in AE3.)"
     )},
    {"key": "soshie", "name": "Soshie", "role": "Social media",     "avatar_emoji": "📱",
     "system_prompt": (
         "You are Soshie, a social media drafter for FB/IG/LinkedIn. "
         "Before/after post copy, seasonal ideas. Publishing is "
         "always approve-gated. (Ships in slice AE4.)"
     )},
    {"key": "scouty", "name": "Scouty", "role": "Recruiting",       "avatar_emoji": "🎯",
     "system_prompt": (
         "You are Scouty, a recruiting copilot. Job ad drafts, interview "
         "scheduling. (Ships in slice AE4.)"
     )},
    {"key": "commet", "name": "Commet", "role": "Funnels",          "avatar_emoji": "🚀",
     "system_prompt": (
         "You are Commet, a minimal funnel/landing-page builder. Draft "
         "copy + CTAs, propose sections. (Ships in slice AE4.)"
     )},
]

CASEY_ACTIONS = {
    "casey.draft_directory_submission",
    "casey.suggest_directory_updates",
    "casey.draft_outreach_reply",
}


# ─── Models ───────────────────────────────────────────────────────────

class EmployeePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    system_prompt: Optional[str] = Field(None, max_length=4000)
    active: Optional[bool] = None
    avatar_emoji: Optional[str] = Field(None, max_length=8)


class BrandBrainPatch(BaseModel):
    tone: Optional[str] = Field(None, max_length=200)
    audience: Optional[str] = Field(None, max_length=500)
    do_say: Optional[List[str]] = None
    dont_say: Optional[List[str]] = None
    talking_points: Optional[List[str]] = None
    notes: Optional[str] = Field(None, max_length=4000)
    # Feb-2026 AE1 T1 fix — unify with Marketing Autopilot. Short
    # reference paragraph that pins voice / style; folded into every
    # employee's system prompt so autopilot copy + AI employees speak
    # in the same voice.
    brand_voice_snippet: Optional[str] = Field(None, max_length=2000)


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=120)


class MessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    # Optional structured action request. When present, the router
    # routes it to the employee's action handler instead of a plain
    # chat round-trip. The handler MUST produce a draft that lands
    # in the ai_employee_actions queue awaiting approval.
    action: Optional[str] = None
    action_params: Optional[Dict[str, Any]] = None


class ActionDecision(BaseModel):
    note: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────

def _strip(doc: Optional[dict]) -> Optional[dict]:
    if doc:
        doc.pop("_id", None)
    return doc


async def seed_ai_employees_for_tenant(tenant_id: str) -> int:
    """Idempotent per-tenant seed. Never overwrites an existing row —
    admins can rename/customize each employee freely and their edits
    survive re-seeding. Returns the number of freshly inserted rows."""
    n = 0
    for e in DEFAULT_EMPLOYEES:
        exists = await db.ai_employees.find_one(
            {"tenant_id": tenant_id, "key": e["key"]}, {"_id": 0, "id": 1},
        )
        if exists:
            continue
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "key": e["key"],
            "name": e["name"], "role": e["role"],
            "avatar_emoji": e["avatar_emoji"],
            "system_prompt": e["system_prompt"],
            "active": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.ai_employees.insert_one(doc)
        n += 1
    return n


async def seed_ai_employees_all_tenants() -> Dict[str, int]:
    """Startup migration hook — seeds every tenant once."""
    total = 0
    tenants = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        n = await seed_ai_employees_for_tenant(t["id"])
        total += n
        tenants += 1
    if total:
        logger.info(
            f"[ae1] seeded {total} employee row(s) across {tenants} tenant(s)"
        )
    return {"tenants": tenants, "inserted": total}


async def _get_brand_brain(tenant_id: str) -> Dict[str, Any]:
    doc = await db.brand_brain.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        doc = {
            "id": new_id(), "tenant_id": tenant_id,
            "tone": "", "audience": "",
            "do_say": [], "dont_say": [], "talking_points": [],
            "notes": "",
            "brand_voice_snippet": "",
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.brand_brain.insert_one(doc)
        doc.pop("_id", None)
    else:
        # Backfill the field on rows created before the AE1 T1 fix.
        doc.setdefault("brand_voice_snippet", "")
    return doc


def _brand_brain_summary(bb: Dict[str, Any]) -> str:
    parts: List[str] = []
    if bb.get("tone"):
        parts.append(f"Brand voice: {bb['tone']}")
    if bb.get("audience"):
        parts.append(f"Audience: {bb['audience']}")
    if bb.get("brand_voice_snippet"):
        parts.append(
            "Voice reference (mirror this style closely): "
            f"{bb['brand_voice_snippet']}"
        )
    if bb.get("do_say"):
        parts.append("DO SAY: " + "; ".join(bb["do_say"]))
    if bb.get("dont_say"):
        parts.append("DON'T SAY: " + "; ".join(bb["dont_say"]))
    if bb.get("talking_points"):
        parts.append("Key points: " + "; ".join(bb["talking_points"]))
    if bb.get("notes"):
        parts.append(f"Notes: {bb['notes']}")
    return "\n".join(parts) if parts else "(no brand brain content yet)"


async def _get_employee(tenant_id: str, eid: str) -> Dict[str, Any]:
    emp = await db.ai_employees.find_one(
        {"id": eid, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not emp:
        raise HTTPException(404, "AI employee not found")
    if not emp.get("active", True):
        raise HTTPException(400, "AI employee is disabled")
    return emp


async def _llm_chat(system_prompt: str, user_text: str,
                     history: List[Dict[str, str]]) -> Dict[str, Any]:
    """Single LLM round-trip via the Emergent key. Returns
    ``{"text": <reply>, "provider": "emergent" | "stub"}``. When no
    key is configured, returns a deterministic stub so tests and
    dev pods still work."""
    key = EMERGENT_LLM_KEY
    if not key:
        return {"text": f"[stub] {user_text[:200]}", "provider": "stub"}
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        return {"text": f"[stub-import-failed] {e}", "provider": "stub"}
    try:
        chat = (LlmChat(api_key=key, session_id=new_id(),
                          system_message=system_prompt)
                .with_model("anthropic", "claude-sonnet-4-5"))
        # Fold recent history into the user prompt so the LLM has
        # context without a per-turn re-send.
        preamble = ""
        for h in history[-6:]:
            role = h.get("role", "user")
            preamble += f"\n[{role}] {h.get('text', '')}"
        msg = UserMessage(text=(preamble + f"\n[user] {user_text}").strip())
        resp = await asyncio.wait_for(chat.send_message(msg), timeout=30)
        return {"text": str(resp).strip(), "provider": "emergent"}
    except Exception as e:
        logger.warning(f"[ae1] llm chat failed: {e}")
        return {"text": f"[stub-error] {e}", "provider": "stub"}


# ─── Employee CRUD ────────────────────────────────────────────────────

@router.get("/ai-employees")
async def list_employees(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # Lazy seed for pods provisioned before AE1 shipped.
    await seed_ai_employees_for_tenant(tenant["id"])
    rows = await db.ai_employees.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(50)
    return rows


@router.get("/ai-employees/actions")
async def list_actions(status: Optional[str] = None,
                        employee_key: Optional[str] = None,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if employee_key:
        q["employee_key"] = employee_key
    rows = await db.ai_employee_actions.find(
        q, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return rows


@router.get("/ai-employees/{eid}")
async def get_employee(eid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    return await _get_employee(tenant["id"], eid)


@router.patch("/ai-employees/{eid}")
async def patch_employee(eid: str, body: EmployeePatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    if not updates:
        return await _get_employee(tenant["id"], eid)
    updates["updated_at"] = now_iso()
    r = await db.ai_employees.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "AI employee not found")
    return await db.ai_employees.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ─── Brand Brain ─────────────────────────────────────────────────────

@router.get("/brand-brain")
async def get_brand_brain(user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    return await _get_brand_brain(tenant["id"])


@router.patch("/brand-brain")
async def patch_brand_brain(body: BrandBrainPatch,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    await _get_brand_brain(tenant["id"])  # ensures a row exists
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    updates["updated_at"] = now_iso()
    await db.brand_brain.update_one(
        {"tenant_id": tenant["id"]}, {"$set": updates},
    )
    return await _get_brand_brain(tenant["id"])


# ─── Conversations + Messages ────────────────────────────────────────

@router.get("/ai-employees/{eid}/conversations")
async def list_conversations(eid: str,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    await _get_employee(tenant["id"], eid)
    rows = await db.ai_employee_conversations.find(
        {"tenant_id": tenant["id"], "employee_id": eid,
          "user_id": user["id"]},
        {"_id": 0},
    ).sort("updated_at", -1).to_list(50)
    return rows


@router.post("/ai-employees/{eid}/conversations", status_code=201)
async def create_conversation(eid: str, body: ConversationCreate,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    await _get_employee(tenant["id"], eid)
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "employee_id": eid, "user_id": user["id"],
        "title": body.title or "New conversation",
        "message_count": 0,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.ai_employee_conversations.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _load_conversation(tenant_id: str, eid: str, cid: str,
                              user_id: str) -> Dict[str, Any]:
    conv = await db.ai_employee_conversations.find_one(
        {"id": cid, "tenant_id": tenant_id, "employee_id": eid,
          "user_id": user_id}, {"_id": 0},
    )
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/ai-employees/{eid}/conversations/{cid}/messages")
async def list_messages(eid: str, cid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await _load_conversation(tenant["id"], eid, cid, user["id"])
    rows = await db.ai_employee_messages.find(
        {"tenant_id": tenant["id"], "conversation_id": cid},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    return rows


@router.post("/ai-employees/{eid}/conversations/{cid}/messages",
              status_code=201)
async def send_message(eid: str, cid: str, body: MessageIn,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Send a user turn + get the assistant response. When ``action``
    is set, routes to the employee's action handler which produces a
    pending-approval action row (in addition to the plain assistant
    reply). Chat sends debit ``CHAT_MSG_COST``; action drafts debit
    ``HEAVY_ACTION_COST`` on top."""
    emp = await _get_employee(tenant["id"], eid)
    conv = await _load_conversation(tenant["id"], eid, cid, user["id"])

    # 1) Persist the user turn.
    user_msg = {
        "id": new_id(), "tenant_id": tenant["id"],
        "conversation_id": cid, "employee_id": eid,
        "role": "user", "text": body.text,
        "created_at": now_iso(),
    }
    await db.ai_employee_messages.insert_one(user_msg)

    # 2) Debit the chat send.
    await debit_credits(
        tenant["id"], CHAT_MSG_COST,
        feature="ai_employees.chat",
        ref_id=cid, ref_type="ai_employee_conversation",
        reason=f"ai_employees.{emp['key']}.chat",
        actor_user_id=user["id"],
    )

    # 3) Build the system prompt (employee + brand brain).
    bb = await _get_brand_brain(tenant["id"])
    system_prompt = (
        f"{emp['system_prompt']}\n\n"
        f"— Shared brand brain —\n{_brand_brain_summary(bb)}"
    )

    # 4) Route: action handler OR plain chat.
    action_doc: Optional[Dict[str, Any]] = None
    if body.action:
        assistant_text, action_doc = await _dispatch_action(
            tenant=tenant, user=user, employee=emp,
            conversation_id=cid,
            action=body.action, params=body.action_params or {},
            system_prompt=system_prompt, user_text=body.text,
        )
    else:
        history = await db.ai_employee_messages.find(
            {"tenant_id": tenant["id"], "conversation_id": cid},
            {"_id": 0, "role": 1, "text": 1},
        ).sort("created_at", 1).to_list(20)
        r = await _llm_chat(system_prompt, body.text, history)
        assistant_text = r["text"]

    # 5) Persist the assistant turn.
    assistant_msg = {
        "id": new_id(), "tenant_id": tenant["id"],
        "conversation_id": cid, "employee_id": eid,
        "role": "assistant", "text": assistant_text,
        "action_id": (action_doc or {}).get("id"),
        "created_at": now_iso(),
    }
    await db.ai_employee_messages.insert_one(assistant_msg)

    # 6) Bump conversation counters.
    await db.ai_employee_conversations.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"updated_at": now_iso()},
          "$inc": {"message_count": 2}},
    )

    return {
        "user_message": _strip(user_msg),
        "assistant_message": _strip(assistant_msg),
        "action": action_doc,
    }


# ─── Actions queue ────────────────────────────────────────────────────

async def _create_action(*, tenant_id: str, user_id: str, employee_id: str,
                           employee_key: str, conversation_id: Optional[str],
                           action: str, params: Dict[str, Any],
                           draft: Dict[str, Any],
                           title: str, summary: str) -> Dict[str, Any]:
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "employee_key": employee_key,
        "conversation_id": conversation_id,
        "action": action,
        "params": params,
        "draft": draft,          # human-readable text or structured data
        "title": title,
        "summary": summary,
        "status": "pending",     # pending | approved | rejected | executed | failed
        "requested_by": user_id,
        "decided_by": None,
        "decision_note": None,
        "executed_at": None,
        "result": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.ai_employee_actions.insert_one(doc)
    return _strip(doc)


@router.get("/ai-employees/actions/{aid}")
async def get_action(aid: str, user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.ai_employee_actions.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Action not found")
    return doc


@router.post("/ai-employees/actions/{aid}/approve")
async def approve_action(aid: str, body: Optional[ActionDecision] = None,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    """Approve a pending action + optionally execute it. Casey drafts
    are text-only so approval simply flips the status; no external
    call is made from within AE1. Future employees (Emmie/Soshie) will
    execute here."""
    doc = await db.ai_employee_actions.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Action not found")
    if doc["status"] != "pending":
        raise HTTPException(400, f"Action is already {doc['status']}")
    upd = {
        "status": "approved",
        "decided_by": user["id"],
        "decision_note": (body.note if body else None),
        "updated_at": now_iso(),
    }
    # Casey drafts are execute-on-approve (text drops into the doc's
    # ``executed_result`` so downstream UI can copy it). No external
    # calls, no credit hit — the draft LLM run already charged.
    if doc["employee_key"] == "casey":
        upd["status"] = "executed"
        upd["executed_at"] = now_iso()
        upd["result"] = {
            "kind": "casey_draft_ready",
            "draft": doc.get("draft"),
        }
    await db.ai_employee_actions.update_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"$set": upd},
    )
    return await db.ai_employee_actions.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


@router.post("/ai-employees/actions/{aid}/reject")
async def reject_action(aid: str, body: Optional[ActionDecision] = None,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = await db.ai_employee_actions.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Action not found")
    if doc["status"] != "pending":
        raise HTTPException(400, f"Action is already {doc['status']}")
    await db.ai_employee_actions.update_one(
        {"id": aid, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "rejected",
            "decided_by": user["id"],
            "decision_note": (body.note if body else None),
            "updated_at": now_iso(),
        }},
    )
    return await db.ai_employee_actions.find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0}
    )


# ─── Casey action dispatch ────────────────────────────────────────────

async def _dispatch_action(*, tenant: dict, user: dict, employee: dict,
                             conversation_id: str,
                             action: str, params: Dict[str, Any],
                             system_prompt: str,
                             user_text: str) -> tuple:
    """Route to the employee's action handler. Only Casey ships in AE1;
    other keys respond with a friendly `not-yet-shipped` note so the
    UI can still call the endpoint without a 500."""
    if action not in CASEY_ACTIONS or employee["key"] != "casey":
        assistant_text = (
            f"Action `{action}` isn't wired for {employee['name']} yet. "
            f"Casey is the only employee with action handlers in this "
            f"slice (AE1)."
        )
        return assistant_text, None

    # Debit heavy-action cost up front (soft — never blocks).
    await debit_credits(
        tenant["id"], HEAVY_ACTION_COST,
        feature=f"ai_employees.{action}",
        ref_id=conversation_id, ref_type="ai_employee_conversation",
        reason=action, actor_user_id=user["id"],
    )

    if action == "casey.draft_directory_submission":
        return await _casey_draft_submission(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "casey.suggest_directory_updates":
        return await _casey_suggest_updates(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "casey.draft_outreach_reply":
        return await _casey_draft_outreach_reply(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    return "Unknown Casey action.", None


async def _fetch_nap(tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db.directory_nap_profile.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}
    )


async def _casey_draft_submission(*, tenant, user, employee,
                                     conversation_id, params,
                                     system_prompt, user_text):
    directory_slug = (params or {}).get("directory_slug") or "generic"
    directory_name = (params or {}).get("directory_name") or directory_slug
    nap = await _fetch_nap(tenant["id"])
    nap_summary = _nap_summary_lines(nap)
    prompt = (
        f"The admin needs a directory submission drafted for "
        f"'{directory_name}' (slug={directory_slug}).\n\n"
        f"— Business NAP —\n{nap_summary}\n\n"
        f"— Admin note —\n{user_text}\n\n"
        f"Return a short business description (≤ 500 chars), a bullet "
        f"list of services, and the exact NAP block to paste. Format "
        f"as plain text with clear section headers."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    draft_text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="casey",
        conversation_id=conversation_id,
        action="casey.draft_directory_submission",
        params={"directory_slug": directory_slug,
                  "directory_name": directory_name},
        draft={"text": draft_text},
        title=f"Draft submission — {directory_name}",
        summary=draft_text[:200],
    )
    assistant_text = (
        f"Drafted a submission for **{directory_name}**. Review the "
        f"attached draft and hit Approve to mark it ready to paste. "
        f"(Nothing has been published.)\n\n---\n{draft_text}"
    )
    return assistant_text, action


async def _casey_suggest_updates(*, tenant, user, employee,
                                    conversation_id, params,
                                    system_prompt, user_text):
    nap = await _fetch_nap(tenant["id"])
    if not nap:
        return (
            "There's no NAP profile on file yet — set the business "
            "name, phone, and address in Directories → NAP Profile "
            "first, then ask me again."
        ), None
    # Fetch the most recent submissions so we can suggest updates on
    # the ones that look stale relative to the current NAP hash.
    recent = await db.directory_submissions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(30)
    current_hash = nap.get("nap_hash") or ""
    stale = [s for s in recent
                 if (s.get("nap_hash_at_submission") or "") != current_hash
                     and s.get("status") in ("live", "verified", "submitted")]
    if not stale:
        return (
            f"All {len(recent)} recent submissions match the current "
            f"NAP hash. Nothing to update right now."
        ), None
    lines = [
        f"- {s.get('directory_name') or s.get('directory_slug', '?')} "
        f"(status: {s.get('status')})"
        for s in stale[:10]
    ]
    draft_text = (
        "These submissions look stale versus the current NAP:\n"
        + "\n".join(lines)
        + "\n\nRecommendation: re-submit the ones flagged 'live' first, "
        + "then work through the others in status order."
    )
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="casey",
        conversation_id=conversation_id,
        action="casey.suggest_directory_updates",
        params={},
        draft={"text": draft_text, "stale_submission_ids": [s["id"] for s in stale]},
        title=f"{len(stale)} directories drift from NAP",
        summary=draft_text[:200],
    )
    return draft_text, action


async def _casey_draft_outreach_reply(*, tenant, user, employee,
                                          conversation_id, params,
                                          system_prompt, user_text):
    incoming = (params or {}).get("incoming_text") or user_text
    nap = await _fetch_nap(tenant["id"])
    nap_summary = _nap_summary_lines(nap)
    prompt = (
        "A directory (or aggregator) sent us this outreach email. "
        "Draft a polite reply from the admin.\n\n"
        f"— Business NAP —\n{nap_summary}\n\n"
        f"— Incoming outreach —\n{incoming}\n\n"
        "Keep the reply concise (≤ 180 words). Confirm any correct NAP "
        "details, politely decline paid placements unless explicitly "
        "requested, and offer a single follow-up point of contact."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    draft_text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="casey",
        conversation_id=conversation_id,
        action="casey.draft_outreach_reply",
        params={"incoming_text": incoming},
        draft={"text": draft_text},
        title="Outreach reply draft",
        summary=draft_text[:200],
    )
    return draft_text, action


def _nap_summary_lines(nap: Optional[Dict[str, Any]]) -> str:
    if not nap:
        return "(no NAP profile on file)"
    addr = nap.get("address") or {}
    lines = [
        f"Name: {nap.get('business_name', '')}",
        f"Phone: {nap.get('phone_e164') or nap.get('phone', '')}",
        f"Address: {addr.get('line1', '')}, {addr.get('city', '')}, "
        f"{addr.get('state', '')} {addr.get('postal_code', '')}",
        f"Website: {nap.get('website', '')}",
        f"Categories: {', '.join(nap.get('business_categories', []))}",
    ]
    return "\n".join(lines)
