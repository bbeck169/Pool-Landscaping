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

# ─── AE2 · Emmie (Email marketing copilot) ────────────────────────────
# Emmie sits on top of Marketing M2 Campaigns. Every draft/variant/
# batch-create action lands in the approval queue and is executed on
# approve. Read-only helpers (analyze, rewrite) skip the queue.
EMMIE_ACTIONS = {
    "emmie.draft_campaign",
    "emmie.suggest_ab_subjects",
    "emmie.analyze_campaign",
    "emmie.suggest_seasonal_ideas",
    "emmie.rewrite_copy",
}
EMMIE_IMMEDIATE_ACTIONS = {
    # Read-only analysis / copy helpers — return the LLM output straight
    # to the assistant turn without landing in ai_employee_actions.
    "emmie.analyze_campaign",
    "emmie.rewrite_copy",
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
    # AE2 · Emmie — approval side-effects. Each action has its own
    # execute path; the underlying M2 campaigns are the source of
    # truth so we never duplicate copy on the ai_employee_actions row.
    elif doc["employee_key"] == "emmie":
        upd = {**upd, **await _emmie_apply_approval(doc, tenant)}
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
    """Route to the employee's action handler. Casey (AE1) + Emmie
    (AE2) are wired here; other employees respond with a friendly
    `not-yet-shipped` note so the UI can still call the endpoint
    without a 500."""
    is_casey_action = action in CASEY_ACTIONS and employee["key"] == "casey"
    is_emmie_action = action in EMMIE_ACTIONS and employee["key"] == "emmie"
    if not (is_casey_action or is_emmie_action):
        assistant_text = (
            f"Action `{action}` isn't wired for {employee['name']} yet. "
            f"Casey + Emmie ship in AE1/AE2. Analytics trio (Buddy, "
            f"Vizzy, Dexter) ships in AE3."
        )
        return assistant_text, None

    # Emmie's read-only helpers skip the heavy debit — they still hit
    # the LLM but produce no queue entry, matching the ship brief.
    charge_heavy = action not in EMMIE_IMMEDIATE_ACTIONS
    if charge_heavy:
        await debit_credits(
            tenant["id"], HEAVY_ACTION_COST,
            feature=f"ai_employees.{action}",
            ref_id=conversation_id, ref_type="ai_employee_conversation",
            reason=action, actor_user_id=user["id"],
        )

    if is_casey_action:
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
    if is_emmie_action:
        if action == "emmie.draft_campaign":
            return await _emmie_draft_campaign(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            )
        if action == "emmie.suggest_ab_subjects":
            return await _emmie_suggest_ab_subjects(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            )
        if action == "emmie.analyze_campaign":
            return await _emmie_analyze_campaign(
                tenant=tenant, user=user, employee=employee,
                params=params, system_prompt=system_prompt,
                user_text=user_text,
            )
        if action == "emmie.suggest_seasonal_ideas":
            return await _emmie_suggest_seasonal_ideas(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            )
        if action == "emmie.rewrite_copy":
            return await _emmie_rewrite_copy(
                tenant=tenant, user=user, employee=employee,
                params=params, system_prompt=system_prompt,
                user_text=user_text,
            )
    return "Unknown action.", None


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



# ─── AE2 · Emmie action handlers ──────────────────────────────────────

async def _campaign_lookup(tenant_id: str, cid: str) -> Optional[Dict[str, Any]]:
    return await db.marketing_campaigns.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0}
    )


def _emmie_extract_section(text: str, header: str) -> str:
    """Very small extractor: pulls the first line after a
    ``## <header>`` or ``<header>:`` marker in the LLM output. Falls
    back to an empty string when the LLM returned free-form text."""
    if not text:
        return ""
    marker_variants = (
        f"## {header}", f"# {header}", f"{header}:",
        f"**{header}**", f"[{header}]",
    )
    lines = text.splitlines()
    for i, line in enumerate(lines):
        low = line.strip().lower()
        for marker in marker_variants:
            m = marker.lower()
            if low.startswith(m):
                # Everything after the marker on this line, else next non-empty line.
                remainder = line.split(":", 1)[-1].strip() if ":" in line else ""
                if remainder and remainder.lower() != low.replace(m, "").strip():
                    return remainder
                # scan forward for next non-empty
                for j in range(i + 1, min(i + 8, len(lines))):
                    nxt = lines[j].strip()
                    if nxt and not nxt.startswith(("#", "-", "*")):
                        return nxt
                    if nxt.startswith(("-", "*")):
                        return nxt.lstrip("-* ").strip()
    return ""


async def _emmie_draft_campaign(*, tenant, user, employee, conversation_id,
                                    params, system_prompt, user_text):
    p = params or {}
    name = (p.get("name") or "Untitled campaign").strip()[:120]
    channel = (p.get("channel") or "email").lower()
    audience_hint = p.get("audience_hint") or ""
    goal = p.get("goal") or user_text
    tone = p.get("tone") or ""

    llm_prompt = (
        f"Draft a marketing campaign named '{name}'.\n"
        f"Channel: {channel} (must include an email if 'email' is in the channel; "
        f"must include an SMS body if 'sms' is in the channel).\n"
        f"Goal: {goal}\n"
        f"Audience: {audience_hint or 'general customer list'}\n"
        f"Tone: {tone or 'per brand brain default'}\n\n"
        "Return sections with these exact headers (Markdown), each on its "
        "own line — Subject:, Preheader:, Email HTML:, SMS Body:. Keep "
        "Subject ≤ 60 chars, Preheader ≤ 90 chars, Email HTML as a short "
        "single-column HTML block, SMS Body ≤ 160 chars (or an empty "
        "line if SMS isn't in the channel)."
    )
    r = await _llm_chat(system_prompt, llm_prompt, history=[])
    text = r["text"]
    subject = _emmie_extract_section(text, "Subject")[:200]
    preheader = _emmie_extract_section(text, "Preheader")[:200]
    email_html = _emmie_extract_section(text, "Email HTML")
    sms_body = _emmie_extract_section(text, "SMS Body")[:320]

    # Create the M2 campaign row eagerly in ``status="draft"`` so the
    # admin can preview it in Marketing → Campaigns even before the
    # AI action is approved. Approve → keeps + surfaces; reject →
    # soft-deletes via ``status="archived"`` so history is preserved.
    now = now_iso()
    campaign = {
        "id": new_id(), "tenant_id": tenant["id"],
        "name": name,
        "subject": subject, "preheader": preheader,
        "from_name": "", "from_email": "", "reply_to": "",
        "channel": channel,
        "content": {"email_html": email_html or text,
                      "email_text": "", "sms_body": sms_body},
        "audience": {"list_ids": [], "segment_ids": [],
                       "exclude_list_ids": [], "exclude_segment_ids": [],
                       "hint": audience_hint},
        "schedule": {"mode": "draft"},
        "ab_test": {"enabled": False},
        "status": "draft",
        "tracking_enabled": True,
        "created_by": user["id"], "created_at": now, "updated_at": now,
        "drafted_by_ai_employee": "emmie",
    }
    await db.marketing_campaigns.insert_one(campaign)
    campaign.pop("_id", None)

    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="emmie",
        conversation_id=conversation_id,
        action="emmie.draft_campaign",
        params={"name": name, "channel": channel,
                  "audience_hint": audience_hint, "goal": goal, "tone": tone},
        draft={"campaign_id": campaign["id"],
                "subject": subject, "preheader": preheader,
                "email_html": email_html, "sms_body": sms_body,
                "raw_llm_output": text},
        title=f"Campaign draft — {name}",
        summary=f"Subject: {subject}"[:200],
    )
    assistant_text = (
        f"Drafted the **{name}** campaign (id `{campaign['id']}`) as a M2 "
        f"draft. Subject → {subject}. Approve the action to keep it, "
        f"reject to archive."
    )
    return assistant_text, action


async def _emmie_suggest_ab_subjects(*, tenant, user, employee, conversation_id,
                                          params, system_prompt, user_text):
    p = params or {}
    cid = p.get("campaign_id")
    if not cid:
        return "Send `campaign_id` in action_params so I know which campaign to draft variants for.", None
    camp = await _campaign_lookup(tenant["id"], cid)
    if not camp:
        return f"Campaign `{cid}` not found in this tenant.", None
    current_subject = camp.get("subject", "")
    goal = user_text or "increase open rate"

    llm_prompt = (
        f"The current subject line is: '{current_subject}'.\n"
        f"Draft THREE subject line variants to A/B test against it. "
        f"Return only the three lines, no numbering, no quotes, one per "
        f"line. Optimize for: {goal}."
    )
    r = await _llm_chat(system_prompt, llm_prompt, history=[])
    lines = [ln.strip().lstrip("-*• ").strip('"').strip("'")
                 for ln in r["text"].splitlines() if ln.strip()]
    variants = [ln[:200] for ln in lines[:3]]
    while len(variants) < 3:
        variants.append(current_subject or "Try the new offer")

    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="emmie",
        conversation_id=conversation_id,
        action="emmie.suggest_ab_subjects",
        params={"campaign_id": cid},
        draft={"campaign_id": cid, "variants": variants},
        title=f"A/B subject variants — {camp.get('name', cid)}",
        summary=" | ".join(variants)[:200],
    )
    assistant_text = (
        "Three subject variants:\n"
        + "\n".join(f"  • {v}" for v in variants)
        + "\n\nApprove to attach them to the campaign's A/B test (50/25/25 default split)."
    )
    return assistant_text, action


async def _emmie_analyze_campaign(*, tenant, user, employee, params,
                                    system_prompt, user_text):
    p = params or {}
    cid = p.get("campaign_id")
    if not cid:
        return "Send `campaign_id` in action_params so I know which campaign to analyze.", None
    camp = await _campaign_lookup(tenant["id"], cid)
    if not camp:
        return f"Campaign `{cid}` not found in this tenant.", None
    from routers.marketing_campaigns import _compute_stats
    try:
        stats = await _compute_stats(tenant["id"], cid)
    except Exception as e:
        logger.warning(f"[ae2] stats compute failed: {e}")
        stats = {}
    llm_prompt = (
        f"Campaign: {camp.get('name', cid)} (channel={camp.get('channel')}, "
        f"status={camp.get('status')}).\nSubject: {camp.get('subject', '')}.\n"
        f"Stats: {stats}\n\n"
        "Write ONE short plain-English performance summary (2-3 sentences) "
        "followed by exactly THREE actionable recommendations. Use a bullet "
        "list for the recommendations. Ground them in the numbers above."
    )
    r = await _llm_chat(system_prompt, llm_prompt, history=[])
    return r["text"], None


async def _emmie_suggest_seasonal_ideas(*, tenant, user, employee,
                                              conversation_id, params,
                                              system_prompt, user_text):
    p = params or {}
    season = (p.get("season") or "current season").strip()
    services = p.get("service_types") or []
    if not isinstance(services, list):
        services = [str(services)]
    services_str = ", ".join(services) if services else "pool + landscape"

    llm_prompt = (
        f"Suggest exactly FIVE marketing campaign ideas for the '{season}' "
        f"season across these service types: {services_str}.\n\n"
        "Format: return five bullet points, each on its own line, each in "
        "the shape 'Name — one-sentence hook'. No numbering."
    )
    r = await _llm_chat(system_prompt, llm_prompt, history=[])
    ideas: List[Dict[str, str]] = []
    for ln in r["text"].splitlines():
        s = ln.strip().lstrip("-*• ").strip()
        if not s or "—" not in s:
            continue
        name, _, hook = s.partition("—")
        ideas.append({"name": name.strip()[:120], "hook": hook.strip()[:280]})
        if len(ideas) >= 5:
            break
    if not ideas:
        return "I couldn't parse any ideas from the model. Try re-running with a different tone param.", None

    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="emmie",
        conversation_id=conversation_id,
        action="emmie.suggest_seasonal_ideas",
        params={"season": season, "service_types": services},
        draft={"ideas": ideas, "season": season, "service_types": services},
        title=f"{season} seasonal ideas ({len(ideas)})",
        summary="; ".join(i["name"] for i in ideas)[:200],
    )
    assistant_text = (
        f"Five {season} ideas:\n"
        + "\n".join(f"  • {i['name']} — {i['hook']}" for i in ideas)
        + "\n\nApprove to spin them up as draft campaigns."
    )
    return assistant_text, action


async def _emmie_rewrite_copy(*, tenant, user, employee, params,
                                 system_prompt, user_text):
    p = params or {}
    text = p.get("text") or user_text
    tone = p.get("tone") or ""
    goal = p.get("goal") or "improve clarity + call to action"
    if not text:
        return "Send `text` in action_params (or in the message) — nothing to rewrite otherwise.", None
    llm_prompt = (
        f"Rewrite the following copy in three different variants. "
        f"Target tone: {tone or 'per brand brain default'}. Goal: {goal}.\n"
        f"Return exactly three variants, each numbered '1.', '2.', '3.', "
        f"each on its own line (or paragraph).\n\n---\n{text}"
    )
    r = await _llm_chat(system_prompt, llm_prompt, history=[])
    return r["text"], None


async def _emmie_apply_approval(action_doc: Dict[str, Any],
                                    tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Emmie approval side-effects. Return dict is merged into the
    ai_employee_actions row (adds executed_at, result, and flips the
    status to executed when the effect landed cleanly)."""
    kind = action_doc.get("action")
    draft = action_doc.get("draft") or {}
    tenant_id = tenant["id"]
    now = now_iso()
    result_common = {"executed_at": now}

    if kind == "emmie.draft_campaign":
        cid = draft.get("campaign_id")
        return {**result_common, "status": "executed",
                "result": {"kind": "emmie_campaign_draft_ready",
                             "campaign_id": cid,
                             "subject": draft.get("subject"),
                             "preheader": draft.get("preheader")}}

    if kind == "emmie.suggest_ab_subjects":
        cid = draft.get("campaign_id")
        variants = draft.get("variants") or []
        if not cid or not variants:
            return {**result_common, "status": "failed",
                     "result": {"kind": "emmie_ab_apply_failed",
                                 "reason": "missing campaign_id or variants"}}
        variant_docs = [
            {"id": new_id(), "subject": v,
              "weight_pct": w, "name": f"Variant {chr(65 + i)}"}
            for i, (v, w) in enumerate(zip(variants, [50, 25, 25]))
        ]
        camp = await db.marketing_campaigns.find_one(
            {"id": cid, "tenant_id": tenant_id}, {"_id": 0, "ab_test": 1},
        )
        existing_ab = (camp or {}).get("ab_test") or {}
        merged_variants = list(existing_ab.get("variants") or [])
        merged_variants.extend(variant_docs)
        await db.marketing_campaigns.update_one(
            {"id": cid, "tenant_id": tenant_id},
            {"$set": {"ab_test": {"enabled": True,
                                        "variants": merged_variants,
                                        "split_field": "subject"},
                       "updated_at": now}},
        )
        return {**result_common, "status": "executed",
                "result": {"kind": "emmie_ab_variants_attached",
                             "campaign_id": cid,
                             "variants": merged_variants}}

    if kind == "emmie.suggest_seasonal_ideas":
        ideas = draft.get("ideas") or []
        if not ideas:
            return {**result_common, "status": "failed",
                     "result": {"kind": "emmie_seasonal_apply_failed",
                                 "reason": "no ideas parsed"}}
        created_ids: List[str] = []
        for idea in ideas:
            doc = {
                "id": new_id(), "tenant_id": tenant_id,
                "name": idea.get("name") or "Seasonal draft",
                "subject": "", "preheader": (idea.get("hook") or "")[:200],
                "from_name": "", "from_email": "", "reply_to": "",
                "channel": "email",
                "content": {"email_html": "", "email_text": idea.get("hook") or "",
                              "sms_body": ""},
                "audience": {"list_ids": [], "segment_ids": [],
                                "exclude_list_ids": [],
                                "exclude_segment_ids": []},
                "schedule": {"mode": "draft"},
                "ab_test": {"enabled": False},
                "status": "draft",
                "tracking_enabled": True,
                "created_by": action_doc.get("requested_by"),
                "created_at": now, "updated_at": now,
                "drafted_by_ai_employee": "emmie",
                "seasonal_seed": draft.get("season"),
            }
            await db.marketing_campaigns.insert_one(doc)
            created_ids.append(doc["id"])
        return {**result_common, "status": "executed",
                "result": {"kind": "emmie_seasonal_drafts_created",
                             "campaign_ids": created_ids,
                             "count": len(created_ids)}}

    return {**result_common, "status": "approved",
             "result": {"kind": "no_side_effect"}}
