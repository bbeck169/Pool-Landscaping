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
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso, require_admin
from services.ai_credits import debit_credits, credit_credits

router = APIRouter(tags=["AI Employees"])

# ─── Constants ────────────────────────────────────────────────────────

CHAT_MSG_COST = 1        # credits per chat send
HEAVY_ACTION_COST = 5    # credits per LLM-heavy action (drafts)

DEFAULT_EMPLOYEES: List[Dict[str, Any]] = [
    {"key": "casey",  "name": "Casey",  "role": "Directories",     "avatar_emoji": "📇", "avatar_url": "/avatars/personas/casey.jpg",
     "system_prompt": (
         "You are Casey, the Directories AI Employee for a pool + landscaping CRM. "
         "You help the admin keep their business listings (Google, Yelp, BBB, "
         "Angi, HomeAdvisor, etc.) consistent, drafted, and current. "
         "Every action you suggest — new submission, update, outreach reply — "
         "lands in an approval queue. NEVER claim you have already published. "
         "Ground your drafts in the tenant's NAP profile (business_name, "
         "phone, address, hours, categories) and brand voice."
     )},
    {"key": "emmie",  "name": "Emmie",  "role": "Email marketing", "avatar_emoji": "✉️", "avatar_url": "/avatars/personas/emmie.jpg",
     "system_prompt": (
         "You are Emmie, an email-marketing copilot. Draft campaigns, subject "
         "lines, and A/B variants. Never mark a campaign live yourself — "
         "propose it and let the admin approve. (Ships in slice AE2.)"
     )},
    {"key": "buddy",  "name": "Buddy",  "role": "Growth analytics", "avatar_emoji": "📈", "avatar_url": "/avatars/personas/buddy.jpg",
     "system_prompt": (
         "You are Buddy, a growth analyst. Weekly briefs on pipeline win "
         "rate, InstaQuote conversion, review sentiment, seasonal trends. "
         "(Ships in slice AE3.)"
     )},
    {"key": "vizzy",  "name": "Vizzy",  "role": "Daily brief",      "avatar_emoji": "🗞️", "avatar_url": "/avatars/personas/vizzy.jpg",
     "system_prompt": (
         "You are Vizzy, the admin's morning brief. Jobs today, open "
         "estimates, hot deals, mentions. (Ships in slice AE3.)"
     )},
    {"key": "dexter", "name": "Dexter", "role": "Ad-hoc analytics", "avatar_emoji": "🧮", "avatar_url": "/avatars/personas/dexter.jpg",
     "system_prompt": (
         "You are Dexter, an ad-hoc analytics AI. Answer natural-language "
         "questions with numbers pulled from the CRM. (Ships in AE3.)"
     )},
    {"key": "soshie", "name": "Soshie", "role": "Social media",     "avatar_emoji": "📱", "avatar_url": "/avatars/personas/soshie.jpg",
     "system_prompt": (
         "You are Soshie, a social media drafter for FB/IG/LinkedIn. "
         "Before/after post copy, seasonal ideas. Publishing is "
         "always approve-gated. (Ships in slice AE4.)"
     )},
    {"key": "scouty", "name": "Scouty", "role": "Recruiting",       "avatar_emoji": "🎯", "avatar_url": "/avatars/personas/scouty.jpg",
     "system_prompt": (
         "You are Scouty, a recruiting copilot. Job ad drafts, interview "
         "scheduling. (Ships in slice AE4.)"
     )},
    {"key": "commet", "name": "Commet", "role": "Funnels",          "avatar_emoji": "🚀", "avatar_url": "/avatars/personas/commet.jpg",
     "audience": "admin",
     "system_prompt": (
         "You are Commet, a minimal funnel/landing-page builder. Draft "
         "copy + CTAs, propose sections. (Ships in slice AE4.)"
     )},
    # ─── Feb-2026 · Slice 5 · Customer-facing AI carve-out ─────────
    # These two employees are surfaced ONLY on the customer portal.
    # They are read-only (no action queue), tenant-credit-billed like
    # admin AI, and escalate to the human admin group when they hit
    # anything outside their read-only lookup scope.
    {"key": "skedra", "name": "Skedra", "role": "Scheduling concierge",
     "audience": "customer", "avatar_emoji": "📅", "avatar_url": "/avatars/personas/skedra.jpg",
     "system_prompt": (
         "You are Skedra, a scheduling concierge for a homeowner using "
         "this pool + landscaping company's portal. You have read-only "
         "access to the CALLER CUSTOMER's own scheduling data ONLY — "
         "their upcoming visits, past service history, and the service "
         "types offered at their properties. "
         "Rules you must obey:\n"
         "1. Answer only questions about scheduling — visit dates, "
         "which service is next, what was performed last time, when "
         "the tech is likely to arrive.\n"
         "2. NEVER reveal, invent, or infer data about any other "
         "customer, the tenant's staff, aggregate metrics, or "
         "financial details. If asked, refuse politely.\n"
         "3. NEVER commit to rescheduling, cancelling, or booking a "
         "visit yourself. When the customer asks for a change, reply "
         "with: \"I'll ask our team to reach out about this.\" and "
         "then escalate.\n"
         "4. If the answer isn't in the context payload, say so and "
         "offer to escalate.\n"
         "5. Keep replies short and warm — 1-3 sentences, no jargon."
     )},
    {"key": "billy", "name": "Billy", "role": "Billing concierge",
     "audience": "customer", "avatar_emoji": "💳", "avatar_url": "/avatars/personas/billy.jpg",
     "system_prompt": (
         "You are Billy, a billing concierge for a homeowner using "
         "this pool + landscaping company's portal. You have FULL "
         "read-only access to the CALLER CUSTOMER's complete invoice "
         "history and payment records — every invoice with its line "
         "items and dates, every payment (masked method), aging "
         "buckets, credit history, recurring subscriptions, and total "
         "lifetime spend. Reference specific invoice numbers or dates "
         "when it helps.\n"
         "Rules you must obey:\n"
         "1. Answer detailed questions ONLY about this customer's own "
         "billing — line items on a specific invoice, aging "
         "breakdown (0-30/31-60/61-90/90+), payment history, credits, "
         "next payment due, recurring services, lifetime spend.\n"
         "2. NEVER quote, imply, or invent numbers for any other "
         "customer. NEVER discuss tenant-wide aggregates, other "
         "customers' invoices, admin-only fields, or internal "
         "cost/margin data. If asked about another customer or "
         "aggregates ('who's the biggest customer', 'total revenue'), "
         "politely refuse and redirect to the caller's own account.\n"
         "3. NEVER take a payment, promise a refund, apply a discount, "
         "modify an invoice, or reschedule a service yourself. When "
         "the customer wants any of those actions, reply: \"I'll flag "
         "this to our billing team.\" and then escalate.\n"
         "4. If the context payload doesn't contain the answer, say "
         "so and offer to escalate.\n"
         "5. Keep replies clear — 1-4 sentences, currency formatted "
         "as $X.XX, dates as YYYY-MM-DD."
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

# ─── AE3 · Analytics trio (Buddy · Vizzy · Dexter) ────────────────────
# All three ride on the AE1 wire. Only two of Buddy's actions are
# approve-gated (weekly_growth_brief + pricing_recommendation) so admins
# can mark them "read/actioned" for the audit trail. Everything else
# is read-only — no writes to the DB, only chat 1c debit.
BUDDY_ACTIONS = {
    "buddy.weekly_growth_brief",
    "buddy.pipeline_analysis",
    "buddy.pricing_recommendation",
    "buddy.marketing_weekly_recap",           # Marketing M7
}
VIZZY_ACTIONS = {
    "vizzy.daily_brief",
    "vizzy.prep_call",
    "vizzy.prioritize_today",
    "vizzy.top_performing_sequences",         # Marketing M7
}
DEXTER_ACTIONS = {
    "dexter.ad_hoc_query",
    "dexter.top_customers_report",
    "dexter.chemical_profitability_report",
    "dexter.review_pipeline_health",          # Marketing M7
}
AE3_APPROVE_GATED_ACTIONS = {
    "buddy.weekly_growth_brief",
    "buddy.pricing_recommendation",
}

# ─── AE4 · Soshie / Scouty / Commet ───────────────────────────────────
SOSHIE_ACTIONS = {
    "soshie.draft_post",
    "soshie.schedule_post",
    "soshie.suggest_content_calendar",
    "soshie.analyze_engagement",
    "soshie.hashtag_research",
}
SCOUTY_ACTIONS = {
    "scouty.draft_job_posting",
    "scouty.screen_resume",
    "scouty.suggest_interview_questions",
    "scouty.generate_offer_letter",
    "scouty.pipeline_summary",
}
COMMET_ACTIONS = {
    "commet.draft_funnel_copy",
    "commet.analyze_conversion",
    "commet.suggest_ab_variants",
    "commet.recommend_cta_changes",
    "commet.funnel_stage_report",
}
AE4_APPROVE_GATED_ACTIONS = {
    "soshie.draft_post",
    "soshie.schedule_post",
    "scouty.draft_job_posting",
    "scouty.generate_offer_letter",
    "commet.draft_funnel_copy",
    "commet.suggest_ab_variants",
}


# ─── Models ───────────────────────────────────────────────────────────

class EmployeePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    system_prompt: Optional[str] = Field(None, max_length=4000)
    active: Optional[bool] = None
    avatar_emoji: Optional[str] = Field(None, max_length=8)
    # Task RR/SS Phase 2 follow-on · Feb 2026 — per-persona portrait
    # URL. Nullable string; when unset the frontend falls back to the
    # emoji. Not tenant-branded — every tenant sees the same shared
    # persona portraits committed under
    # ``/app/frontend/public/avatars/personas/{key}.jpg``.
    avatar_url: Optional[str] = Field(None, max_length=1024)
    # Feb-2026 · P24 — guard field. The PATCH endpoint refuses to
    # clear ``avatar_url`` unless the caller explicitly opts in with
    # ``clear_avatar=true``. Without this, a client submitting a
    # partial form that happens to include ``avatar_url: null``
    # would silently wipe the persona portrait. Bug reported on
    # production 2026-02.
    clear_avatar: Optional[bool] = Field(None)
    # Task RR · Feb 2026 — per-persona data read scope.
    # ``customer_scoped`` (default for all seeded personas) restricts
    # tool calls to the caller's OWN customer data. ``tenant_all``
    # lifts the scope and is only intended for admin-audience
    # personas (Billy-admin, Skedra-dispatcher). Only super_admin can
    # flip this via the admin PATCH endpoint — enforced router-side.
    read_access_scope: Optional[str] = Field(
        None, pattern="^(customer_scoped|tenant_all)$",
    )


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
    survive re-seeding. Returns the number of freshly inserted rows.

    Feb-2026 · Slice 5 — every doc now carries an ``audience`` field
    (``"admin"`` or ``"customer"``). Existing rows without the field
    are lazily backfilled to ``"admin"`` since every pre-Slice-5
    employee is admin-only.
    """
    n = 0
    for e in DEFAULT_EMPLOYEES:
        audience = e.get("audience", "admin")
        exists = await db.ai_employees.find_one(
            {"tenant_id": tenant_id, "key": e["key"]},
            {"_id": 0, "id": 1, "audience": 1},
        )
        if exists:
            # Backfill the ``audience`` field on legacy rows.
            if not exists.get("audience"):
                await db.ai_employees.update_one(
                    {"id": exists["id"]},
                    {"$set": {"audience": audience,
                              "updated_at": now_iso()}},
                )
            # Task RR · Feb 2026 — backfill ``read_access_scope``.
            # Default all legacy rows to ``customer_scoped`` (safe).
            # Admin flips to ``tenant_all`` via PATCH.
            if not exists.get("read_access_scope"):
                await db.ai_employees.update_one(
                    {"id": exists["id"]},
                    {"$set": {"read_access_scope": "customer_scoped",
                              "updated_at": now_iso()}},
                )
            continue
        doc = {
            "id": new_id(), "tenant_id": tenant_id, "key": e["key"],
            "name": e["name"], "role": e["role"],
            "avatar_emoji": e["avatar_emoji"],
            "avatar_url": e.get("avatar_url"),
            "system_prompt": e["system_prompt"],
            "audience": audience,
            "read_access_scope": "customer_scoped",
            "active": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.ai_employees.insert_one(doc)
        n += 1
    return n


async def seed_ai_employees_all_tenants() -> Dict[str, int]:
    """Startup migration hook — seeds every tenant once. Also runs the
    one-shot Slice-J2 Billy prompt bump so tenants that were seeded
    before the deeper-billing-access rollout get the new prompt (but
    only when they still have the OLD default — admin-customised
    prompts are respected)."""
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
    # Slice J2 one-shot — bump Billy's prompt to the deeper-access
    # copy for any row still carrying the pre-J2 default text.
    bumped = await _slice_j2_migrate_billy_prompt()
    if bumped:
        logger.info(f"[j2] bumped Billy system prompt on {bumped} tenant(s)")
    return {"tenants": tenants, "inserted": total, "billy_prompt_bumped": bumped}


async def _slice_j2_migrate_billy_prompt() -> int:
    """Rewrite Billy's ``system_prompt`` for tenants that still carry
    the pre-Slice-J2 default. Any admin customisation (system_prompt
    that doesn't start with the pre-J2 sentinel) is left untouched.
    Idempotent."""
    _PRE_J2_SENTINEL = (
        "You are Billy, a billing concierge for a homeowner using "
        "this pool + landscaping company's portal. You have read-only "
        "access to the CALLER CUSTOMER's own billing data ONLY"
    )
    new_prompt = next(
        (e["system_prompt"] for e in DEFAULT_EMPLOYEES if e["key"] == "billy"),
        None,
    )
    if not new_prompt:
        return 0
    res = await db.ai_employees.update_many(
        {
            "key": "billy",
            "system_prompt": {"$regex": f"^{re.escape(_PRE_J2_SENTINEL)}"},
        },
        {"$set": {"system_prompt": new_prompt, "updated_at": now_iso()}},
    )
    return int(getattr(res, "modified_count", 0) or 0)


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


async def _get_employee(tenant_id: str, eid: str,
                          expected_audience: Optional[str] = None) -> Dict[str, Any]:
    emp = await db.ai_employees.find_one(
        {"id": eid, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not emp:
        raise HTTPException(404, "AI employee not found")
    if not emp.get("active", True):
        raise HTTPException(400, "AI employee is disabled")
    # Feb-2026 · Slice 5 — enforce audience boundaries. Admin routes
    # pass ``expected_audience="admin"`` (rejecting Skedra/Billy);
    # customer-portal routes pass ``expected_audience="customer"``
    # (rejecting Casey/Emmie/Buddy/etc). Legacy rows without an
    # ``audience`` field default to ``"admin"``.
    if expected_audience is not None:
        actual = emp.get("audience") or "admin"
        if actual != expected_audience:
            raise HTTPException(403, "AI employee not available in this scope")
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
    # Feb-2026 · Slice 5 — only surface ``audience: "admin"`` rows on
    # the admin Dock. Skedra + Billy are customer-portal-only.
    rows = await db.ai_employees.find(
        {"tenant_id": tenant["id"],
         "$or": [
             {"audience": "admin"},
             {"audience": {"$exists": False}},   # legacy rows default to admin
         ]},
        {"_id": 0},
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
    return await _get_employee(tenant["id"], eid, expected_audience="admin")


@router.patch("/ai-employees/{eid}")
async def patch_employee(eid: str, body: EmployeePatch,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    updates = {k: v for k, v in body.dict(exclude_unset=True).items()}
    # Feb-2026 · P24 — the ``clear_avatar`` flag is a UX signal, not
    # a persisted field. Strip it out and translate it into an
    # explicit avatar_url wipe.
    clear_avatar = bool(updates.pop("clear_avatar", False))
    # P24 guard — never silently null ``avatar_url``. If the client
    # sent ``avatar_url`` but not ``clear_avatar=true``, and the value
    # is None or empty, drop it from the update so we don't wipe an
    # existing portrait. This blocks the "partial form submit ships
    # {avatar_url:null} and wipes the row" class of bugs which the
    # P24 audit found had been happening on prod.
    if "avatar_url" in updates:
        av = updates["avatar_url"]
        if av is None or (isinstance(av, str) and not av.strip()):
            if not clear_avatar:
                updates.pop("avatar_url", None)
                logger.info(
                    "[p24] avatar_url null/empty in PATCH payload without "
                    "clear_avatar=true — silently dropping to preserve "
                    "existing portrait (eid=%s)", eid,
                )
    elif clear_avatar:
        # Caller sent ``clear_avatar=true`` but no ``avatar_url`` key
        # at all — honour the explicit intent.
        updates["avatar_url"] = None
    if not updates:
        return await _get_employee(tenant["id"], eid, expected_audience="admin")
    # Task RR · Feb 2026 — only super_admin can flip a persona to
    # ``tenant_all``. Regular admins can still flip back to
    # ``customer_scoped`` (safe direction), so that path is not
    # gated.
    if (updates.get("read_access_scope") == "tenant_all"
            and user.get("role") != "super_admin"):
        raise HTTPException(
            403, "Only super_admin can grant tenant_all read access",
        )
    updates["updated_at"] = now_iso()
    r = await db.ai_employees.update_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "AI employee not found")
    return await db.ai_employees.find_one(
        {"id": eid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ─── Task RR · Feb 2026 — AI tool call audit trail ───────────────────
@router.get("/admin/ai-personas-scope")
async def list_all_personas_for_scope(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only listing of EVERY persona (both admin + customer
    audiences) with their current ``read_access_scope`` — powers the
    Task RR/SS Phase 2 scope-toggle admin surface.
    """
    await seed_ai_employees_for_tenant(tenant["id"])
    rows = await db.ai_employees.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "key": 1, "name": 1, "role": 1,
          "audience": 1, "read_access_scope": 1, "active": 1,
          "avatar_emoji": 1, "avatar_url": 1},
    ).sort("audience", 1).to_list(50)
    return {"items": rows, "total": len(rows)}


@router.get("/admin/ai-tool-audit")
async def list_ai_tool_audit(
    persona_key: Optional[str] = None,
    tool_name: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only tail of the ``ai_tool_calls`` collection.

    Retention is 90 days (TTL index on ``created_at`` installed by
    the tool dispatcher on first use). Filter by ``persona_key``,
    ``tool_name``, or an ISO ``since`` cutoff. Default 200 rows.
    """
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if persona_key:
        q["persona_key"] = persona_key
    if tool_name:
        q["tool_name"] = tool_name
    if since:
        q["created_at"] = {"$gte": since}
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 200
    rows = await db.ai_tool_calls.find(
        q, {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": rows, "total": len(rows)}


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
    await _get_employee(tenant["id"], eid, expected_audience="admin")
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
    await _get_employee(tenant["id"], eid, expected_audience="admin")
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
    emp = await _get_employee(tenant["id"], eid, expected_audience="admin")
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
    # AE3 · Buddy — the two approve-gated actions
    # (weekly_growth_brief, pricing_recommendation) are read-only
    # briefs. Approval simply audits the admin actioned the brief.
    elif doc["employee_key"] == "buddy":
        upd["status"] = "executed"
        upd["executed_at"] = now_iso()
        upd["result"] = {
            "kind": "buddy_brief_acknowledged",
            "action": doc.get("action"),
            "note": "Recorded for audit trail — no writes performed.",
        }
    # AE4 · Soshie / Scouty / Commet — approval flips to executed
    # with a per-employee ``result.kind``. All AE4 approvals are
    # audit-trail only in this slice; downstream (M6 social sender,
    # HR portal, funnel builder) will consume the draft payload.
    elif doc["employee_key"] in ("soshie", "scouty", "commet"):
        upd["status"] = "executed"
        upd["executed_at"] = now_iso()
        upd["result"] = {
            "kind": f"{doc['employee_key']}_draft_ready",
            "action": doc.get("action"),
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
    """Route to the employee's action handler. Casey (AE1) + Emmie
    (AE2) are wired here; other employees respond with a friendly
    `not-yet-shipped` note so the UI can still call the endpoint
    without a 500."""
    is_casey_action = action in CASEY_ACTIONS and employee["key"] == "casey"
    is_emmie_action = action in EMMIE_ACTIONS and employee["key"] == "emmie"
    is_buddy_action = action in BUDDY_ACTIONS and employee["key"] == "buddy"
    is_vizzy_action = action in VIZZY_ACTIONS and employee["key"] == "vizzy"
    is_dexter_action = action in DEXTER_ACTIONS and employee["key"] == "dexter"
    is_soshie_action = action in SOSHIE_ACTIONS and employee["key"] == "soshie"
    is_scouty_action = action in SCOUTY_ACTIONS and employee["key"] == "scouty"
    is_commet_action = action in COMMET_ACTIONS and employee["key"] == "commet"
    if not (is_casey_action or is_emmie_action or is_buddy_action
              or is_vizzy_action or is_dexter_action
              or is_soshie_action or is_scouty_action or is_commet_action):
        assistant_text = (
            f"Action `{action}` isn't wired for {employee['name']} yet. "
            f"All eight employees (Casey, Emmie, Buddy, Vizzy, Dexter, "
            f"Soshie, Scouty, Commet) are live — check the action key."
        )
        return assistant_text, None

    # Read-only helpers skip the heavy debit. Only approve-gated
    # actions from any slice charge 5c on top of chat 1c.
    charge_heavy = (
        action in AE3_APPROVE_GATED_ACTIONS
        or action in AE4_APPROVE_GATED_ACTIONS
        or (is_casey_action)
        or (is_emmie_action and action not in EMMIE_IMMEDIATE_ACTIONS)
    )
    if charge_heavy:
        await debit_credits(
            tenant["id"], HEAVY_ACTION_COST,
            feature=f"ai_employees.{action}",
            ref_id=conversation_id, ref_type="ai_employee_conversation",
            reason=action, actor_user_id=user["id"],
        )

    async def _run_and_refund_if_no_action(coro):
        """Feb-2026 AE polish — approve-gated handlers can bail out
        early (missing param, validation short-circuit) and return
        ``(assistant_text, None)``. In that case the 5c heavy charge
        we already applied has no matching approval flow — the user
        shouldn't burn credits per validation-failed attempt. Refund
        the heavy portion when the handler produces no pending action
        row. Real drafts still cost the full 6c."""
        text_out, action_out = await coro
        if charge_heavy and action_out is None:
            try:
                await credit_credits(
                    tenant["id"], HEAVY_ACTION_COST,
                    feature=f"ai_employees.{action}",
                    ref_id=conversation_id,
                    ref_type="ai_employee_conversation",
                    reason=f"refund:{action}:no_action_created",
                    actor_user_id=user["id"],
                )
            except Exception as e:
                logger.warning(
                    f"[ae-polish] heavy-refund failed for {action}: {e}"
                )
        return text_out, action_out

    if is_casey_action:
        if action == "casey.draft_directory_submission":
            return await _run_and_refund_if_no_action(_casey_draft_submission(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
        if action == "casey.suggest_directory_updates":
            return await _run_and_refund_if_no_action(_casey_suggest_updates(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
        if action == "casey.draft_outreach_reply":
            return await _run_and_refund_if_no_action(_casey_draft_outreach_reply(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
    if is_emmie_action:
        if action == "emmie.draft_campaign":
            return await _run_and_refund_if_no_action(_emmie_draft_campaign(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
        if action == "emmie.suggest_ab_subjects":
            return await _run_and_refund_if_no_action(_emmie_suggest_ab_subjects(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
        if action == "emmie.analyze_campaign":
            return await _emmie_analyze_campaign(
                tenant=tenant, user=user, employee=employee,
                params=params, system_prompt=system_prompt,
                user_text=user_text,
            )
        if action == "emmie.suggest_seasonal_ideas":
            return await _run_and_refund_if_no_action(_emmie_suggest_seasonal_ideas(
                tenant=tenant, user=user, employee=employee,
                conversation_id=conversation_id, params=params,
                system_prompt=system_prompt, user_text=user_text,
            ))
        if action == "emmie.rewrite_copy":
            return await _emmie_rewrite_copy(
                tenant=tenant, user=user, employee=employee,
                params=params, system_prompt=system_prompt,
                user_text=user_text,
            )
    if is_buddy_action:
        return await _run_and_refund_if_no_action(_buddy_dispatch(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, action=action,
            params=params, system_prompt=system_prompt, user_text=user_text,
        ))
    if is_vizzy_action:
        return await _vizzy_dispatch(
            tenant=tenant, user=user, employee=employee,
            action=action, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if is_dexter_action:
        return await _dexter_dispatch(
            tenant=tenant, user=user, employee=employee,
            action=action, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if is_soshie_action:
        return await _run_and_refund_if_no_action(_soshie_dispatch(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, action=action,
            params=params, system_prompt=system_prompt, user_text=user_text,
        ))
    if is_scouty_action:
        return await _run_and_refund_if_no_action(_scouty_dispatch(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, action=action,
            params=params, system_prompt=system_prompt, user_text=user_text,
        ))
    if is_commet_action:
        return await _run_and_refund_if_no_action(_commet_dispatch(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, action=action,
            params=params, system_prompt=system_prompt, user_text=user_text,
        ))
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


# ─── AE3 · Buddy (Growth Strategist) ──────────────────────────────────

async def _buddy_dispatch(*, tenant, user, employee, conversation_id,
                             action, params, system_prompt, user_text):
    if action == "buddy.weekly_growth_brief":
        return await _buddy_weekly_growth_brief(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "buddy.pipeline_analysis":
        return await _buddy_pipeline_analysis(
            tenant=tenant, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "buddy.pricing_recommendation":
        return await _buddy_pricing_recommendation(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "buddy.marketing_weekly_recap":
        return await _buddy_marketing_weekly_recap(
            tenant=tenant, params=params or {},
        )
    return "Unknown Buddy action.", None


async def _pipeline_stats(tenant_id: str, days: int) -> Dict[str, Any]:
    """Small read-only rollup — Deals pipeline stats. Never writes."""
    since_iso = _iso_days_ago(days)
    stages = {}
    async for s in db.deal_stages.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ):
        stages[s["id"]] = s
    total = 0
    won = 0
    lost = 0
    open_by_stage: Dict[str, int] = {}
    stalled = 0
    all_deals = []
    async for d in db.deals.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ):
        total += 1
        all_deals.append(d)
        status = d.get("status") or (stages.get(d.get("stage_id"), {}) or {}).get("status")
        if status == "won":
            won += 1
        elif status == "lost":
            lost += 1
        else:
            open_by_stage[d.get("stage_id")] = open_by_stage.get(d.get("stage_id"), 0) + 1
            updated = d.get("updated_at") or ""
            if updated and updated < since_iso:
                stalled += 1
    win_rate = round((won / max(1, won + lost)) * 100, 1) if (won + lost) else 0.0
    return {
        "total_deals": total,
        "won": won, "lost": lost,
        "open_by_stage": {(stages.get(k, {}) or {}).get("name", k or "?"): v
                              for k, v in open_by_stage.items()},
        "stalled_over_days": {"days": days, "count": stalled},
        "win_rate_pct": win_rate,
    }


async def _instaquote_conversions(tenant_id: str, days: int) -> Dict[str, Any]:
    since_iso = _iso_days_ago(days)
    total = 0
    converted = 0
    async for s in db.instaquote_submissions.find(
        {"tenant_id": tenant_id, "created_at": {"$gte": since_iso}},
        {"_id": 0, "status": 1, "converted_deal_id": 1},
    ):
        total += 1
        if s.get("converted_deal_id") or s.get("status") in ("converted", "won"):
            converted += 1
    rate = round((converted / max(1, total)) * 100, 1)
    return {"days": days, "total": total, "converted": converted,
             "conversion_pct": rate}


async def _review_sentiment(tenant_id: str, days: int) -> Dict[str, Any]:
    since_iso = _iso_days_ago(days)
    n = 0
    stars_sum = 0
    lo = 0
    async for r in db.reviews.find(
        {"tenant_id": tenant_id, "created_at": {"$gte": since_iso}},
        {"_id": 0, "star_rating": 1},
    ):
        s = int(r.get("star_rating") or 0)
        if s:
            n += 1
            stars_sum += s
            if s <= 3:
                lo += 1
    avg = round(stars_sum / n, 2) if n else 0.0
    return {"days": days, "count": n, "avg_star": avg,
             "low_star_count": lo}


async def _campaign_activity(tenant_id: str, days: int) -> Dict[str, Any]:
    since_iso = _iso_days_ago(days)
    total = 0
    sent = 0
    async for c in db.marketing_campaigns.find(
        {"tenant_id": tenant_id, "updated_at": {"$gte": since_iso}},
        {"_id": 0, "status": 1},
    ):
        total += 1
        if c.get("status") in ("sent", "sending"):
            sent += 1
    return {"days": days, "total_touched": total, "sent_or_sending": sent}


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(0, days))).isoformat()


async def _buddy_weekly_growth_brief(*, tenant, user, employee,
                                          conversation_id, params,
                                          system_prompt, user_text):
    days = int((params or {}).get("days") or 7)
    pipeline = await _pipeline_stats(tenant["id"], days)
    iq = await _instaquote_conversions(tenant["id"], days)
    reviews = await _review_sentiment(tenant["id"], days)
    campaigns = await _campaign_activity(tenant["id"], days)
    # Seasonal indicator — a plain-text hint keyed off calendar month.
    month = datetime.now(timezone.utc).month
    season_map = {1: "Winter maintenance", 2: "Late-winter tune-ups",
                    3: "Spring openings", 4: "Spring openings",
                    5: "Peak swim ramp-up", 6: "Peak swim",
                    7: "Peak swim", 8: "Late-summer service",
                    9: "Fall prep", 10: "Fall closings",
                    11: "Winterization", 12: "Winter maintenance"}
    season = season_map.get(month, "Mixed season")

    prompt = (
        f"Weekly growth brief — window={days}d.\n"
        f"Deals: {pipeline}\n"
        f"InstaQuote: {iq}\n"
        f"Reviews: {reviews}\n"
        f"Campaigns: {campaigns}\n"
        f"Season: {season}\n\n"
        "Write a growth brief (≤ 200 words) with a one-paragraph "
        "narrative followed by exactly 3-5 concrete recommendations "
        "as a bullet list. Ground each recommendation in the numbers "
        "above. Do NOT recommend actions that require writing to the "
        "CRM — I only surface, I never edit."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    brief_text = r["text"]

    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="buddy",
        conversation_id=conversation_id,
        action="buddy.weekly_growth_brief",
        params={"days": days},
        draft={
            "text": brief_text,
            "signals": {
                "deals": pipeline, "instaquote": iq,
                "reviews": reviews, "campaigns": campaigns,
                "season": season,
            },
        },
        title=f"Weekly growth brief — {days}d",
        summary=brief_text[:200],
    )
    return brief_text, action


async def _buddy_pipeline_analysis(*, tenant, params,
                                        system_prompt, user_text):
    days = int((params or {}).get("days") or 14)
    stats = await _pipeline_stats(tenant["id"], days)
    prompt = (
        f"Deals pipeline stats over the last {days}d:\n{stats}\n\n"
        "Write a short analysis (≤ 150 words) — one paragraph narrative "
        "followed by 3 bullet recommendations for unsticking stalled "
        "deals and improving win rate."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _buddy_pricing_recommendation(*, tenant, user, employee,
                                              conversation_id, params,
                                              system_prompt, user_text):
    # Read chemical profitability aggregate (already exposed via the
    # profitability endpoint) but do the query inline so we don't need
    # an HTTP self-call.
    since = _iso_days_ago(90)
    per_type: Dict[str, Dict[str, float]] = {}
    async for row in db.chemicals_added.find(
        {"tenant_id": tenant["id"], "created_at": {"$gte": since}},
        {"_id": 0, "cost_usd": 1, "job_id": 1, "chemical_name": 1},
    ):
        name = row.get("chemical_name") or "unknown"
        entry = per_type.setdefault(name, {"cost_usd": 0.0, "n": 0})
        entry["cost_usd"] += float(row.get("cost_usd") or 0)
        entry["n"] += 1

    prompt = (
        f"Chemical cost rollup over the last 90d:\n{per_type}\n"
        f"Admin note: {user_text}\n\n"
        "Write pricing recommendations (≤ 200 words) as one narrative "
        "paragraph plus a bullet list of concrete adjustments per "
        "service_type. Consider seasonal demand + margin. Do NOT "
        "write to the CRM — I surface only."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="buddy",
        conversation_id=conversation_id,
        action="buddy.pricing_recommendation",
        params={"days": 90},
        draft={"text": text, "cost_rollup": per_type},
        title="Pricing recommendation",
        summary=text[:200],
    )
    return text, action


# ─── AE3 · Vizzy (Executive Assistant) ────────────────────────────────

async def _vizzy_dispatch(*, tenant, user, employee, action, params,
                              system_prompt, user_text):
    if action == "vizzy.daily_brief":
        return await _vizzy_daily_brief(
            tenant=tenant, user=user, system_prompt=system_prompt,
            user_text=user_text,
        )
    if action == "vizzy.prep_call":
        return await _vizzy_prep_call(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "vizzy.prioritize_today":
        return await _vizzy_prioritize_today(
            tenant=tenant, user=user,
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "vizzy.top_performing_sequences":
        return await _vizzy_top_performing_sequences(
            tenant=tenant, params=params or {},
        )
    return "Unknown Vizzy action.", None


async def _vizzy_daily_brief(*, tenant, user, system_prompt, user_text):
    today = datetime.now(timezone.utc).date().isoformat()
    from utils import not_deleted_filter as _nd
    # Jobs today by tech.
    jobs_today = await db.jobs.find(
        {"tenant_id": tenant["id"], "scheduled_date": today, **_nd()},
        {"_id": 0, "id": 1, "technician_id": 1, "technician_name": 1,
          "status": 1},
    ).to_list(500)
    by_tech: Dict[str, int] = {}
    for j in jobs_today:
        by_tech[j.get("technician_name") or "Unassigned"] = \
            by_tech.get(j.get("technician_name") or "Unassigned", 0) + 1

    open_estimates = await db.estimates.count_documents(
        {"tenant_id": tenant["id"], "status": {"$in": ["draft", "sent", "pending"]}},
    )
    # Hot deals — any deal in a stage flagged as "hot" is unreliable;
    # instead surface deals whose stage.status is "open" and were
    # updated in the last 7d.
    since = _iso_days_ago(7)
    hot_deals = await db.deals.count_documents({
        "tenant_id": tenant["id"],
        "updated_at": {"$gte": since},
        "status": {"$nin": ["won", "lost"]},
    })
    # Overdue tasks — customer_tasks with due_date before today.
    overdue_tasks = await db.customer_tasks.count_documents({
        "tenant_id": tenant["id"],
        "status": {"$ne": "completed"},
        "due_date": {"$lt": today, "$ne": None, "$exists": True},
    })
    # Unread mentions — count of unresolved chat mentions targeting user.
    unread_mentions = 0
    try:
        unread_mentions = await db.chat_mentions.count_documents({
            "tenant_id": tenant["id"], "user_id": user["id"],
            "read_at": None,
        })
    except Exception:
        pass

    signals = {
        "jobs_today": len(jobs_today),
        "jobs_by_tech": by_tech,
        "open_estimates": open_estimates,
        "hot_deals_7d": hot_deals,
        "overdue_tasks": overdue_tasks,
        "unread_mentions": unread_mentions,
    }
    prompt = (
        f"Daily brief for {today}:\n{signals}\n\n"
        "Write a punchy morning brief (≤ 120 words). One-line summary, "
        "then a bullet list of the 3 most urgent items with a quick "
        "reason each. Admin note: " + (user_text or "n/a")
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"] + f"\n\n(signals: {signals})", None


async def _vizzy_prep_call(*, tenant, params, system_prompt, user_text):
    cid = (params or {}).get("customer_id")
    if not cid:
        return "Send `customer_id` in action_params so I know whose call to prep.", None
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not cust:
        return f"Customer `{cid}` not found in this tenant.", None
    from utils import not_deleted_filter as _nd_recent
    recent_jobs = await db.jobs.find(
        {"tenant_id": tenant["id"], "customer_id": cid, **_nd_recent()},
        {"_id": 0, "title": 1, "scheduled_date": 1, "status": 1},
    ).sort("scheduled_date", -1).to_list(10)
    open_invoices = await db.quotes.find(
        {"tenant_id": tenant["id"], "customer_id": cid,
          "doc_type": "invoice", "payment_status": {"$ne": "paid"}},
        {"_id": 0, "id": 1, "invoice_number": 1, "total": 1, "amount_paid": 1,
          "due_date": 1},
    ).sort("created_at", -1).to_list(10)
    open_estimates = await db.estimates.find(
        {"tenant_id": tenant["id"], "customer_id": cid,
          "status": {"$in": ["draft", "sent", "pending"]}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "total": 1},
    ).sort("created_at", -1).to_list(10)

    # Feb-2026 · P22 — Privacy policy claim (P21 §4) forbids sending
    # customer names/phones/emails to LLM providers.  We keep the
    # ``customer`` block ONLY for read-only tenant context on the
    # server side; the LLM prompt sees a redacted, symbolic view.
    from services.ai.pii_redactor import redact_pii
    signals = {
        # Symbolic reference — no PII. Real name/email/phone are used
        # AFTER the LLM returns (by the admin UI + downstream comms).
        "customer_ref": f"[CUSTOMER {cid[-6:]}]",
        "is_vip": cust.get("is_vip") or False,
        "notes": redact_pii((cust.get("notes") or "")[:400]),
        "recent_jobs": recent_jobs,
        "open_invoices": open_invoices,
        "open_estimates": open_estimates,
    }
    prompt = (
        "Assemble a call-prep sheet for the admin. Keep it short "
        "(≤ 180 words). Sections: Customer snapshot (refer to them "
        "generically as 'the customer' or by [CUSTOMER …] ref); "
        "Talking points (3 bullets); Outstanding items (list open "
        "invoice #s + amount-owed, open estimates). Data:\n"
        + str(signals)
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _vizzy_prioritize_today(*, tenant, user, system_prompt, user_text):
    today = datetime.now(timezone.utc).date().isoformat()
    tasks = await db.customer_tasks.find(
        {"tenant_id": tenant["id"], "status": {"$ne": "completed"}},
        {"_id": 0, "title": 1, "priority": 1, "due_date": 1, "customer_id": 1},
    ).sort("due_date", 1).to_list(50)
    since = _iso_days_ago(7)
    deals = await db.deals.find(
        {"tenant_id": tenant["id"], "updated_at": {"$gte": since},
          "status": {"$nin": ["won", "lost"]}},
        {"_id": 0, "id": 1, "title": 1, "value_cents": 1},
    ).sort("value_cents", -1).to_list(20)
    prompt = (
        f"Prioritize the admin's day ({today}).\n"
        f"Open tasks: {tasks}\n"
        f"Hot deals: {deals}\n"
        f"Admin note: {user_text}\n\n"
        "Return a ranked list of the 5 most important actions with a "
        "short reason each. Skip anything already completed."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


# ─── AE3 · Dexter (Data Analyst) ──────────────────────────────────────

_DEXTER_COLLECTION_BUDGET = 5


async def _dexter_dispatch(*, tenant, user, employee, action, params,
                                system_prompt, user_text):
    if action == "dexter.ad_hoc_query":
        return await _dexter_ad_hoc_query(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "dexter.top_customers_report":
        return await _dexter_top_customers_report(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "dexter.chemical_profitability_report":
        return await _dexter_chemical_profitability_report(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "dexter.review_pipeline_health":
        return await _dexter_review_pipeline_health(
            tenant=tenant, params=params or {},
        )
    return "Unknown Dexter action.", None


# ─── Marketing Slice M7 · Analytics narratives (read-only) ────────────
# Three light handlers that call the M7 analytics router and render an
# executive brief.  Read-only; no writes, no approve gating (1c chat
# debit only per the standard AE3 wire).

async def _buddy_marketing_weekly_recap(*, tenant, params):
    """Pulls last-7-day overview and renders an executive brief."""
    from routers.marketing_analytics import _compute_overview
    ov = await _compute_overview(tenant["id"], "7d")
    camps = ov["campaigns"]
    seqs = ov["sequences"]
    rr = ov["review_requests"]
    top_seq_line = ", ".join(
        f"{t['name']} ({t['enrolments']})" for t in ov["top_sequences"]
    ) or "none active this week"
    top_camp_line = ", ".join(
        f"{t['name']} ({t['delivered']})" for t in ov["top_campaigns"]
    ) or "no campaigns delivered"
    review_rate = rr.get("review_rate_pct")
    body = (
        "**Marketing recap · last 7 days**\n\n"
        f"• Campaigns: {camps['total_sent']} sent this week "
        f"({camps['active']} still running), "
        f"{camps['delivered']} deliveries, {camps['opened']} opens.\n"
        f"• Sequences: {seqs['total_enrolments']} new enrolments "
        f"({seqs['active']} active · {seqs['completed']} completed · "
        f"{seqs['halted']} halted). "
        f"Avg completion: "
        f"{seqs['avg_completion_hours'] or '—'} hours.\n"
        f"• Reviews: {rr['reviewed']} of {rr['total']} requests converted "
        f"({review_rate if review_rate is not None else '—'}%). "
        f"Avg rating: {rr['avg_rating'] or '—'}.\n"
        f"• Top sequences: {top_seq_line}.\n"
        f"• Top campaigns: {top_camp_line}."
    )
    return body, None


async def _vizzy_top_performing_sequences(*, tenant, params):
    """30-day view of top sequences ranked by enrolment volume."""
    from routers.marketing_analytics import _compute_overview
    ov = await _compute_overview(tenant["id"], "30d")
    rows = ov["top_sequences"]
    if not rows:
        return ("No sequences have collected enrolments in the last 30 days. "
                 "Turn on Sequences from Marketing → Sequences to get started."), None
    lines = ["**Top-performing sequences · last 30 days**", ""]
    for r in rows:
        rate = r.get("completion_rate")
        lines.append(
            f"• **{r['name']}** — {r['enrolments']} enrolments, "
            f"{rate if rate is not None else '—'}% completion rate",
        )
    return "\n".join(lines), None


async def _dexter_review_pipeline_health(*, tenant, params):
    """Call out bottlenecks in the review-request funnel."""
    from routers.marketing_analytics import _compute_overview
    ov = await _compute_overview(tenant["id"], "30d")
    rr = ov["review_requests"]
    total = rr.get("total") or 0
    if total == 0:
        return ("No review requests in the last 30 days. Enable Marketing → "
                 "Review Requests to start collecting."), None
    queued_share = _local_pct(rr["queued"], total)
    sent_share = _local_pct(rr["sent"], total)
    review_share = _local_pct(rr["reviewed"], total)
    expire_share = _local_pct(rr["expired"], total)
    notes = []
    if queued_share and queued_share > 50:
        notes.append(
            f"⚠️ {queued_share}% still queued — check quiet-hour config + "
            f"tick job health.",
        )
    if sent_share and rr["opened"] == 0 and rr["sent"] > 0:
        notes.append(
            "⚠️ Messages are being sent but nobody has opened them yet — "
            "worth verifying deliverability once a live provider is wired.",
        )
    if expire_share and expire_share > 20:
        notes.append(
            f"⚠️ {expire_share}% expired — consider shortening delay_hours "
            f"or lengthening expire_days.",
        )
    if not notes:
        notes.append("✅ Funnel looks healthy — no bottlenecks stand out.")
    body = (
        "**Review request pipeline · last 30 days**\n\n"
        f"• Total: {total}\n"
        f"• Queued: {rr['queued']} · Sent: {rr['sent']} · "
        f"Opened: {rr['opened']} · Reviewed: {rr['reviewed']} · "
        f"Expired: {rr['expired']}\n"
        f"• Review conversion rate: "
        f"{rr.get('review_rate_pct') if rr.get('review_rate_pct') is not None else '—'}%\n"
        f"• Avg rating captured: {rr.get('avg_rating') or '—'}\n\n"
        + "\n".join(notes)
    )
    return body, None


def _local_pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _dexter_too_broad(question: str) -> bool:
    """Guard against queries that would sweep half the CRM. Very
    conservative heuristic — the shipping brief says to return a
    'too broad — refine' hint when a query would need >5 collections
    or unbounded aggregation."""
    if not question:
        return True
    q = question.lower()
    all_word = any(w in q for w in
                       ("everything", "all data", "every collection",
                         "whole database", "entire crm", "list all"))
    unbounded = any(w in q for w in
                        ("history", "since forever", "all time"))
    return all_word and unbounded


async def _dexter_ad_hoc_query(*, tenant, params, system_prompt, user_text):
    question = (params or {}).get("question") or user_text
    if _dexter_too_broad(question):
        return (
            "That's too broad — narrow it down. Try scoping by time "
            "window (e.g. 'last 90 days'), a service type, or a single "
            "collection."
        ), None
    # Snapshot small aggregates the LLM can reason over. We stay under
    # the 5-collection budget on purpose.
    snapshot: Dict[str, Any] = {"question": question}
    customers = await db.customers.count_documents({"tenant_id": tenant["id"]})
    jobs = await db.jobs.count_documents({"tenant_id": tenant["id"]})
    invoices = await db.quotes.count_documents(
        {"tenant_id": tenant["id"], "doc_type": "invoice"}
    )
    deals = await db.deals.count_documents({"tenant_id": tenant["id"]})
    campaigns = await db.marketing_campaigns.count_documents({"tenant_id": tenant["id"]})
    snapshot["counts"] = {"customers": customers, "jobs": jobs,
                             "invoices": invoices, "deals": deals,
                             "campaigns": campaigns}
    # Extra city-level breakdown when the question mentions a city.
    q_lower = question.lower() if question else ""
    if any(city in q_lower for city in
                ("peoria", "phoenix", "scottsdale", "glendale",
                  "chandler", "mesa", "tempe")):
        # City counts.
        cursor = db.customers.aggregate([
            {"$match": {"tenant_id": tenant["id"]}},
            {"$group": {"_id": {"$toLower": "$city"}, "n": {"$sum": 1}}},
            {"$limit": 20},
        ])
        cities = {row["_id"] or "unknown": int(row["n"]) async for row in cursor}
        snapshot["customers_by_city"] = cities
    prompt = (
        f"You are answering the admin's question with numbers pulled "
        f"from a CRM. Respect the following snapshot exactly — do not "
        f"invent unrelated numbers.\n\n{snapshot}\n\n"
        "Answer the question in ≤ 100 words. Start with a numeric "
        "answer when possible (e.g. 'There are 42 customers in "
        "Peoria.'). Follow with 1-2 sentences of interpretation."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _dexter_top_customers_report(*, tenant, params, system_prompt, user_text):
    metric = ((params or {}).get("metric") or "revenue").lower()
    period_days = int((params or {}).get("period_days") or 90)
    since = _iso_days_ago(period_days)
    ranking: List[Dict[str, Any]] = []
    if metric == "revenue":
        cursor = db.quotes.aggregate([
            {"$match": {"tenant_id": tenant["id"], "doc_type": "invoice",
                          "created_at": {"$gte": since}}},
            {"$group": {"_id": "$customer_id",
                          "revenue": {"$sum": "$total"},
                          "invoices": {"$sum": 1}}},
            {"$sort": {"revenue": -1}},
            {"$limit": 20},
        ])
        async for row in cursor:
            ranking.append({"customer_id": row["_id"],
                                "revenue": round(float(row.get("revenue") or 0), 2),
                                "invoices": int(row.get("invoices") or 0)})
    elif metric == "visits":
        cursor = db.jobs.aggregate([
            {"$match": {"tenant_id": tenant["id"],
                          "created_at": {"$gte": since}}},
            {"$group": {"_id": "$customer_id",
                          "visits": {"$sum": 1}}},
            {"$sort": {"visits": -1}},
            {"$limit": 20},
        ])
        async for row in cursor:
            ranking.append({"customer_id": row["_id"],
                                "visits": int(row.get("visits") or 0)})
    elif metric == "chemicals_cost":
        cursor = db.chemicals_added.aggregate([
            {"$match": {"tenant_id": tenant["id"],
                          "created_at": {"$gte": since}}},
            {"$lookup": {"from": "jobs", "localField": "job_id",
                            "foreignField": "id", "as": "job"}},
            {"$unwind": {"path": "$job", "preserveNullAndEmptyArrays": True}},
            {"$group": {"_id": "$job.customer_id",
                          "cost_usd": {"$sum": "$cost_usd"}}},
            {"$sort": {"cost_usd": -1}},
            {"$limit": 20},
        ])
        async for row in cursor:
            ranking.append({"customer_id": row["_id"],
                                "chemicals_cost": round(float(row.get("cost_usd") or 0), 2)})
    else:
        return f"Unknown metric `{metric}`. Try revenue, visits, or chemicals_cost.", None
    # Hydrate customer names.
    # Feb-2026 · P22 — Privacy policy compliance: LLM sees anonymized
    # rows only. Real customer names are re-attached in the response
    # payload AFTER the LLM call (see ``ranking`` return below).
    ids = [r["customer_id"] for r in ranking if r.get("customer_id")]
    names = {}
    async for c in db.customers.find(
        {"id": {"$in": ids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "name": 1},
    ):
        names[c["id"]] = c.get("name")
    # Anonymized ranking for the LLM prompt (no PII).
    anon_ranking = []
    for i, row in enumerate(ranking, start=1):
        anon_ranking.append(
            {**{k: v for k, v in row.items() if k != "customer_id"},
              "customer_ref": f"Customer_{i}"}
        )
    prompt = (
        f"Top {len(anon_ranking)} customers by {metric} over the last "
        f"{period_days}d (identified only by symbolic Customer_N "
        f"reference — do NOT ask for real names):\n"
        f"{anon_ranking}\n\nWrite a 3-sentence summary highlighting "
        f"the top 3 and any notable pattern. Refer to customers by "
        f"their Customer_N reference; the app will substitute real "
        f"names in the display."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    # Attach real names to the ranking we return to the caller —
    # the LLM never saw them.
    for row in ranking:
        row["name"] = names.get(row.get("customer_id"), "?")
    return r["text"] + f"\n\n(ranking: {ranking})", None


async def _dexter_chemical_profitability_report(*, tenant, params,
                                                        system_prompt, user_text):
    days = int((params or {}).get("period_days") or 60)
    since = _iso_days_ago(days)
    per_chem: Dict[str, Dict[str, float]] = {}
    async for row in db.chemicals_added.find(
        {"tenant_id": tenant["id"], "created_at": {"$gte": since}},
        {"_id": 0, "cost_usd": 1, "chemical_name": 1, "billed_amount": 1},
    ):
        name = row.get("chemical_name") or "unknown"
        entry = per_chem.setdefault(name, {"cost": 0.0, "billed": 0.0, "n": 0})
        entry["cost"] += float(row.get("cost_usd") or 0)
        entry["billed"] += float(row.get("billed_amount") or 0)
        entry["n"] += 1
    for entry in per_chem.values():
        margin = entry["billed"] - entry["cost"]
        entry["margin"] = round(margin, 2)
        entry["margin_pct"] = round(
            (margin / entry["billed"] * 100) if entry["billed"] else 0.0, 1
        )
    prompt = (
        f"Chemical profitability over {days}d:\n{per_chem}\n\n"
        "Write a 4-sentence analysis calling out the highest-margin "
        "product, the lowest-margin product, and one recommendation."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"] + f"\n\n(rollup: {per_chem})", None



# ─── AE4 · Soshie (Social media copilot) ──────────────────────────────

async def _soshie_dispatch(*, tenant, user, employee, conversation_id,
                              action, params, system_prompt, user_text):
    # Feb-2026 · Soshie AI-Agent Expansion P1 — SEO Suite grounding.
    # Every Soshie action gets a compact <2 KB snapshot of the
    # tenant's SEO state prepended to the system prompt: latest
    # scan score, top open AEO gaps, rank movers, top mention
    # domains, recent keyword ideations.  Empty on tenants that
    # haven't run a scan yet — degrades cleanly.
    try:
        from services.soshie.seo_context import (
            build_seo_context, format_seo_context_for_prompt,
        )
        seo_ctx = await build_seo_context(tenant["id"])
        seo_block = format_seo_context_for_prompt(seo_ctx)
        if seo_block:
            system_prompt = f"{system_prompt}\n\n{seo_block}"
    except Exception as e:                                        # noqa: BLE001
        logger.warning("[soshie.dispatch] SEO context skipped: %s", e)

    if action == "soshie.draft_post":
        return await _soshie_draft_post(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "soshie.schedule_post":
        return await _soshie_schedule_post(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "soshie.suggest_content_calendar":
        return await _soshie_content_calendar(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "soshie.analyze_engagement":
        return await _soshie_analyze_engagement(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "soshie.hashtag_research":
        return await _soshie_hashtag_research(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    return "Unknown Soshie action.", None


async def _soshie_draft_post(*, tenant, user, employee, conversation_id,
                                params, system_prompt, user_text):
    platform = (params.get("platform") or "instagram").lower()
    topic = params.get("topic") or user_text
    tone = params.get("tone") or ""
    prompt = (
        f"Draft a {platform} post about: {topic}\n"
        f"Tone: {tone or 'per brand brain default'}. "
        f"Keep it authentic to the pool/landscaping brand.\n\n"
        "Return sections with these exact headers on their own lines: "
        "Caption:, Hashtags: (5-10 comma-separated), CTA:. Do not "
        "include placeholders like [BRAND] — expand them into real "
        "copy per the brand brain."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="soshie",
        conversation_id=conversation_id,
        action="soshie.draft_post",
        params={"platform": platform, "topic": topic, "tone": tone},
        draft={"text": text, "platform": platform},
        title=f"Post draft — {platform}",
        summary=text[:200],
    )
    return text, action


async def _soshie_schedule_post(*, tenant, user, employee, conversation_id,
                                    params, system_prompt, user_text):
    platform = (params.get("platform") or "instagram").lower()
    when = params.get("scheduled_at") or ""
    caption = (params.get("caption") or "").strip()
    if not caption:
        return "Send `caption` in action_params so I know what to schedule.", None
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="soshie",
        conversation_id=conversation_id,
        action="soshie.schedule_post",
        params={"platform": platform, "scheduled_at": when,
                  "caption": caption[:400]},
        draft={"platform": platform, "scheduled_at": when,
                "caption": caption},
        title=f"Schedule {platform} post",
        summary=f"{platform} @ {when or 'unspecified'}: {caption[:120]}",
    )
    reply = (
        f"Queued a {platform} post" +
        (f" for {when}" if when else " (no time set)") +
        f". Approve to move it to the outbox.\n\nCaption preview:\n{caption[:400]}"
    )
    return reply, action


async def _soshie_content_calendar(*, tenant, params, system_prompt, user_text):
    days = int(params.get("days") or 14)
    services = params.get("service_types") or ["Pool", "Landscape"]
    prompt = (
        f"Draft a {days}-day social content calendar for a pool + "
        f"landscape business covering {services}. Return a bullet list "
        f"of ideas, one per day, in the shape 'Day N — Platform — "
        f"Hook'. Alternate platforms across Instagram, Facebook, "
        f"LinkedIn. Ground ideas in seasonality + service mix."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _soshie_analyze_engagement(*, tenant, params, system_prompt, user_text):
    days = int(params.get("days") or 30)
    # Best-effort read of any social_posts collection — safe fallback
    # when the collection isn't present yet.
    counts = {"posts": 0, "recent_days": days}
    try:
        since = _iso_days_ago(days)
        counts["posts"] = await db.social_posts.count_documents({
            "tenant_id": tenant["id"], "created_at": {"$gte": since},
        })
    except Exception:
        pass
    prompt = (
        f"Recent social activity snapshot: {counts}\n"
        "Write a short engagement analysis (≤ 120 words) with 3 "
        "actionable recommendations. If activity is zero or low, "
        "recommend a starter cadence."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _soshie_hashtag_research(*, tenant, params, system_prompt, user_text):
    topic = params.get("topic") or user_text or "pool service"
    prompt = (
        f"Give me 15 hashtags for the topic '{topic}' in the pool + "
        "landscape service niche. Mix niche + broad. Return a comma-"
        "separated list, no numbering, no # symbols missing."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


# ─── AE4 · Scouty (Recruiting copilot) ────────────────────────────────

async def _scouty_dispatch(*, tenant, user, employee, conversation_id,
                              action, params, system_prompt, user_text):
    if action == "scouty.draft_job_posting":
        return await _scouty_draft_job_posting(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "scouty.screen_resume":
        return await _scouty_screen_resume(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "scouty.suggest_interview_questions":
        return await _scouty_interview_questions(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "scouty.generate_offer_letter":
        return await _scouty_offer_letter(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "scouty.pipeline_summary":
        return await _scouty_pipeline_summary(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    return "Unknown Scouty action.", None


async def _scouty_draft_job_posting(*, tenant, user, employee,
                                        conversation_id, params,
                                        system_prompt, user_text):
    role = params.get("role") or "Pool Technician"
    location = params.get("location") or "Peoria, AZ"
    pay_range = params.get("pay_range") or ""
    prompt = (
        f"Draft a job posting for a {role} role based in {location}. "
        f"Pay range: {pay_range or 'competitive'}. "
        "Include sections: Overview, Responsibilities (bullet list, "
        "5-7 items), Requirements (bullet list, 4-6 items), Why work "
        "with us (bullet list, 3-4 items), How to apply."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="scouty",
        conversation_id=conversation_id,
        action="scouty.draft_job_posting",
        params={"role": role, "location": location,
                  "pay_range": pay_range},
        draft={"text": text, "role": role, "location": location},
        title=f"Job posting draft — {role}",
        summary=text[:200],
    )
    return text, action


async def _scouty_screen_resume(*, tenant, params, system_prompt, user_text):
    resume = params.get("resume_text") or user_text
    role = params.get("role") or "Pool Technician"
    if not resume or len(resume.strip()) < 40:
        return "Send `resume_text` in action_params (≥ 40 chars).", None
    prompt = (
        f"Screen the following resume against a {role} role for a "
        f"pool + landscape service company. Rate fit 1-10, list top "
        f"3 strengths, top 3 concerns, and a recommended next step.\n\n"
        f"--- Resume ---\n{resume}"
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _scouty_interview_questions(*, tenant, params, system_prompt, user_text):
    role = params.get("role") or "Pool Technician"
    count = int(params.get("count") or 8)
    prompt = (
        f"Draft {count} interview questions for a {role} role. Mix "
        "behavioural, situational, and role-specific technical items. "
        "Return one per line, no numbering. Skip anything that would "
        "raise legal concerns (age, family, disability, etc.)."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _scouty_offer_letter(*, tenant, user, employee, conversation_id,
                                   params, system_prompt, user_text):
    candidate = params.get("candidate_name") or "[Candidate Name]"
    role = params.get("role") or "Pool Technician"
    salary = params.get("salary") or ""
    start_date = params.get("start_date") or "[Start Date]"
    prompt = (
        f"Draft an offer letter for {candidate} for the {role} role. "
        f"Salary: {salary or '[Salary TBD]'}. Start date: {start_date}. "
        "Include: warm opening, role title + reporting structure, "
        "compensation, benefits summary, at-will note, response "
        "deadline (1 week), and a sign-off. Do NOT invent numbers "
        "beyond what's provided."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="scouty",
        conversation_id=conversation_id,
        action="scouty.generate_offer_letter",
        params={"candidate_name": candidate, "role": role,
                  "salary": salary, "start_date": start_date},
        draft={"text": text},
        title=f"Offer letter draft — {candidate}",
        summary=text[:200],
    )
    return text, action


async def _scouty_pipeline_summary(*, tenant, params, system_prompt, user_text):
    # Best-effort — read any candidates collection if present.
    counts = {"applications": 0, "in_review": 0, "hired_30d": 0}
    try:
        counts["applications"] = await db.recruit_applications.count_documents({
            "tenant_id": tenant["id"],
        })
        counts["in_review"] = await db.recruit_applications.count_documents({
            "tenant_id": tenant["id"], "status": "in_review",
        })
        since = _iso_days_ago(30)
        counts["hired_30d"] = await db.recruit_applications.count_documents({
            "tenant_id": tenant["id"], "status": "hired",
            "updated_at": {"$gte": since},
        })
    except Exception:
        pass
    prompt = (
        f"Recruit pipeline snapshot: {counts}\n"
        "Write a short (≤ 100 words) pipeline summary + 3 actionable "
        "next steps for the hiring manager."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


# ─── AE4 · Commet (Funnels copilot) ────────────────────────────────────

async def _commet_dispatch(*, tenant, user, employee, conversation_id,
                              action, params, system_prompt, user_text):
    if action == "commet.draft_funnel_copy":
        return await _commet_draft_funnel_copy(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "commet.analyze_conversion":
        return await _commet_analyze_conversion(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "commet.suggest_ab_variants":
        return await _commet_suggest_ab_variants(
            tenant=tenant, user=user, employee=employee,
            conversation_id=conversation_id, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "commet.recommend_cta_changes":
        return await _commet_recommend_cta_changes(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    if action == "commet.funnel_stage_report":
        return await _commet_funnel_stage_report(
            tenant=tenant, params=params or {},
            system_prompt=system_prompt, user_text=user_text,
        )
    return "Unknown Commet action.", None


async def _commet_draft_funnel_copy(*, tenant, user, employee, conversation_id,
                                          params, system_prompt, user_text):
    goal = params.get("goal") or user_text or "get InstaQuote submissions"
    audience = params.get("audience") or "homeowners with in-ground pools"
    prompt = (
        f"Draft copy for a marketing funnel targeting: {audience}.\n"
        f"Goal: {goal}\n\n"
        "Return the following sections on their own lines: "
        "Headline:, Subheadline:, Body (3-4 short paragraphs), "
        "Primary CTA:, Trust builders (3 bullets)."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    text = r["text"]
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="commet",
        conversation_id=conversation_id,
        action="commet.draft_funnel_copy",
        params={"goal": goal, "audience": audience},
        draft={"text": text},
        title=f"Funnel copy draft — {goal[:40]}",
        summary=text[:200],
    )
    return text, action


async def _commet_analyze_conversion(*, tenant, params, system_prompt, user_text):
    days = int(params.get("days") or 30)
    since = _iso_days_ago(days)
    counts = {"days": days}
    try:
        counts["instaquote_submissions"] = \
            await db.instaquote_submissions.count_documents({
                "tenant_id": tenant["id"], "created_at": {"$gte": since},
            })
    except Exception:
        counts["instaquote_submissions"] = 0
    try:
        counts["deals_created"] = await db.deals.count_documents({
            "tenant_id": tenant["id"], "created_at": {"$gte": since},
        })
    except Exception:
        counts["deals_created"] = 0
    prompt = (
        f"Funnel conversion snapshot over {days}d: {counts}\n"
        "Write a short analysis (≤ 120 words) with 3 concrete "
        "recommendations for lifting conversion."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _commet_suggest_ab_variants(*, tenant, user, employee, conversation_id,
                                          params, system_prompt, user_text):
    element = params.get("element") or "headline"
    current = (params.get("current_copy") or "").strip()
    if not current:
        return "Send `current_copy` in action_params so I know what to A/B against.", None
    prompt = (
        f"Draft THREE A/B variants for the {element}. Return only the "
        f"three variants, one per line, no numbering.\n\n"
        f"--- Current copy ---\n{current}"
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    variants = [ln.strip().lstrip("-*• ").strip('"').strip("'")
                    for ln in r["text"].splitlines() if ln.strip()][:3]
    while len(variants) < 3:
        variants.append(current)
    action = await _create_action(
        tenant_id=tenant["id"], user_id=user["id"],
        employee_id=employee["id"], employee_key="commet",
        conversation_id=conversation_id,
        action="commet.suggest_ab_variants",
        params={"element": element, "current_copy": current[:400]},
        draft={"element": element, "variants": variants,
                "raw_llm_output": r["text"]},
        title=f"A/B {element} variants",
        summary=" | ".join(variants)[:200],
    )
    reply = (
        f"Three {element} variants:\n"
        + "\n".join(f"  • {v}" for v in variants)
        + "\n\nApprove to log them for the funnel builder."
    )
    return reply, action


async def _commet_recommend_cta_changes(*, tenant, params, system_prompt, user_text):
    current = params.get("current_cta") or user_text or "Get a Quote"
    prompt = (
        f"The current CTA is: '{current}'. Suggest 3 stronger CTAs, "
        "each on its own line, no numbering. Optimize for pool + "
        "landscape service booking."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None


async def _commet_funnel_stage_report(*, tenant, params, system_prompt, user_text):
    counts = {}
    try:
        counts["instaquote_pending"] = \
            await db.instaquote_submissions.count_documents({
                "tenant_id": tenant["id"], "status": "pending",
            })
        counts["deals_open"] = await db.deals.count_documents({
            "tenant_id": tenant["id"],
            "status": {"$nin": ["won", "lost"]},
        })
    except Exception:
        pass
    prompt = (
        f"Funnel stage counts: {counts}\n"
        "Write a stage-by-stage report (≤ 100 words). Call out any "
        "stage that looks blocked and suggest one action."
    )
    r = await _llm_chat(system_prompt, prompt, history=[])
    return r["text"], None

