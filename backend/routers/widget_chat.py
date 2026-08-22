"""Feb-2026 · Slice G1 — Public AI Website Chat Widget backend.

External embed for a homeowner-facing chatbot that can answer basic
FAQ / services / pricing questions and opportunistically capture a
lead into ``leads`` when the visitor drops an email/phone or asks to
schedule.

Every endpoint here is called from the widget JS bundle running on
a tenant's OWN marketing site — authenticated via
:func:`routers.widget_config.require_widget_auth` (public widget key
+ Origin allowlist).

Design notes
------------
* No token / cookie: the widget passes its ``X-Widget-Key`` on every
  request. The stateless *conversation_id* is what stitches a chat
  session together. The conversation carries a ``tenant_id`` so cross-
  tenant reads are refused even if a conversation_id leaks.
* Anonymous mode: no ``customer_id`` — the LLM system prompt is a
  slimmer anonymous variant of Skedra's prompt with two extra rules:
  never invent tenant data, and weave in a natural ask for name + a
  contact method within 1-2 turns.
* Lead capture: opportunistic. When email OR phone is detected in a
  user turn, we upsert a ``leads`` doc (``source="chat_widget"``) and
  link its id onto the conversation. When booking-intent is detected
  AND a contact has been captured, we fan out an admin bell so the
  human team can pick it up.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger, EMERGENT_LLM_KEY
from utils import new_id, now_iso
from routers.widget_config import require_widget_auth
from routers.ai_employees import _llm_chat  # reuse the emergent LLM helper

router = APIRouter(tags=["Widget Chat"])

# ─── Constants ────────────────────────────────────────────────────────

MAX_MSG_LEN = 2000
HISTORY_WINDOW = 20

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Phone regex tightened (GH-Fix): require at least 10 digits with real
# phone punctuation. We strip emails from the text BEFORE running the
# phone match so timestamp-heavy email local parts (e.g.
# "widget-test-1707422400@example.com") don't get mis-detected as
# phone numbers.
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
)
# Rough name extractor: "my name is X" or "I'm X" — best-effort only.
_NAME_RE = re.compile(
    r"\b(?:my name is|i am|i'm|this is)\s+([A-Z][A-Za-z'\-]{1,30}(?:\s+[A-Z][A-Za-z'\-]{1,30}){0,2})",
    re.IGNORECASE,
)

_BOOKING_KEYWORDS = re.compile(
    r"\b(book|schedul(?:e|ing)|appointment|estimate|quote|reserv"
    r"|come\s+out|visit|inspect|service\s+call|when\s+can\s+you)\w*\b",
    re.IGNORECASE,
)

# Anonymous system prompt. Kept small so the tenant's tone (via a
# future ``tenant.chat_widget_greeting`` / brand brain slot) can layer
# on top later.
ANON_SYSTEM_PROMPT = (
    "You are the friendly AI concierge on the public website of a "
    "pool + landscaping company. You are speaking to an ANONYMOUS "
    "website visitor — you do NOT know their name, email, or address, "
    "and you have no access to any customer records.\n\n"
    "Behavioural rules:\n"
    "1. Answer the visitor's first question directly and helpfully. "
    "Cover general topics: services offered (pool cleaning, chemical "
    "balancing, landscape maintenance, one-off cleanups, etc.), rough "
    "seasonal expectations, what a visit involves. If you don't know a "
    "specific number (exact pricing, availability slots), say so and "
    "offer to have the team follow up.\n"
    "2. Within the next 1-2 replies, weave in a natural ask for the "
    "visitor's name and either email or phone — for example, "
    "'What's the best way to reach you if we want to send more info?'. "
    "DO NOT gate your first reply on getting contact info first — give "
    "value up-front.\n"
    "3. If the visitor is clearly asking to book, schedule, or get an "
    "estimate, and they have NOT yet shared a name + contact, kindly "
    "say you need those two things before you can pass it to the team. "
    "Never invent an appointment or promise a specific time.\n"
    "4. Never claim to see the visitor's account, invoice, or address. "
    "Never reveal any customer's info — you have none.\n"
    "5. Keep replies short (1-4 sentences) and warm."
)


# ─── Models ───────────────────────────────────────────────────────────

class ConvStart(BaseModel):
    page_url: Optional[str] = Field(None, max_length=500)
    referrer: Optional[str] = Field(None, max_length=500)


class WidgetMsgIn(BaseModel):
    # GH-Fix: ``conversation_id`` in the body is OPTIONAL now — the
    # path param is authoritative. Kept for backwards compat with the
    # old widget JS bundle that may still send it.
    conversation_id: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=MAX_MSG_LEN)


# ─── Helpers ──────────────────────────────────────────────────────────

def _extract_contact(text: str) -> Dict[str, Optional[str]]:
    """Return the first email/phone/name we can pull out of ``text``.
    All fields optional. Names are best-effort — the LLM system prompt
    reminds it to ask, so a missed extraction here still gets picked
    up on the next turn.

    GH-Fix: emails are stripped from the message BEFORE the phone regex
    runs so ``widget-test-1707422400@example.com`` doesn't extract
    ``1707422400`` as a phone number.
    """
    raw = text or ""
    email_m = _EMAIL_RE.search(raw)
    # Strip any email addresses from the text before phone matching to
    # avoid false-positives on numeric email local parts.
    text_no_email = _EMAIL_RE.sub(" ", raw)
    phone_m = _PHONE_RE.search(text_no_email)
    name_m = _NAME_RE.search(raw)
    return {
        "email": email_m.group(0).strip() if email_m else None,
        "phone": phone_m.group(0).strip() if phone_m else None,
        "name": name_m.group(1).strip() if name_m else None,
    }


def _looks_booking(text: str) -> bool:
    return bool(_BOOKING_KEYWORDS.search(text or ""))


async def _get_conversation(cid: str, tenant_id: str) -> Dict[str, Any]:
    doc = await db.widget_chat_conversations.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Conversation not found")
    return doc


async def _upsert_lead(conv: Dict[str, Any], tenant_id: str, *,
                        contact: Dict[str, Optional[str]],
                        first_user_text: str,
                        page_url: Optional[str]) -> Optional[str]:
    """Idempotently create-or-update the lead linked to this
    conversation. Returns the lead id (existing or new); ``None`` when
    the conversation has captured no contact yet — leads without at
    least an email or a phone would be noise in the admin inbox."""
    email = contact.get("email") or conv.get("visitor_email")
    phone = contact.get("phone") or conv.get("visitor_phone")
    name = contact.get("name") or conv.get("visitor_name")

    if not (email or phone):
        return None

    # Existing lead already linked?
    if conv.get("lead_id"):
        upd: Dict[str, Any] = {}
        if email and not conv.get("visitor_email"):
            upd["email"] = email
        if phone and not conv.get("visitor_phone"):
            upd["phone"] = phone
        if name:
            upd["name"] = name
        if upd:
            await db.leads.update_one(
                {"id": conv["lead_id"], "tenant_id": tenant_id},
                {"$set": upd},
            )
        return conv["lead_id"]

    # Try match by contact within tenant to avoid duplicates.
    existing = None
    if email:
        existing = await db.leads.find_one(
            {"tenant_id": tenant_id, "email": email}, {"_id": 0, "id": 1}
        )
    if not existing and phone:
        existing = await db.leads.find_one(
            {"tenant_id": tenant_id, "phone": phone}, {"_id": 0, "id": 1}
        )
    if existing:
        return existing["id"]

    lead_id = new_id()
    lead_doc = {
        "id": lead_id,
        "tenant_id": tenant_id,
        "name": name or "Website visitor",
        "email": email or "",
        "phone": phone or "",
        "source": "chat_widget",
        "status": "new",
        "notes": (first_user_text or "")[:500],
        "meta": {"page_url": page_url,
                 "widget_conversation_id": conv.get("id")},
        "created_at": now_iso(),
    }
    await db.leads.insert_one(lead_doc)
    # Feb-2026 · P18 — mark last created lead so the caller
    # endpoint can fan out to tenant-configured SMS+email recipients.
    _upsert_lead._last_created = {                              # type: ignore[attr-defined]
        "lead": lead_doc, "tenant_id": tenant_id,
    }
    return lead_id


async def _fire_admin_bell(tenant_id: str, *, title: str, body: str,
                              lead_id: Optional[str],
                              conversation_id: str) -> None:
    """Best-effort admin bell fan-out. Never raises."""
    try:
        from services.notifications import enqueue_for_tenant_admins
        await enqueue_for_tenant_admins(
            tenant_id,
            kind="widget_chat_lead",
            title=title,
            body=body,
            source_ref={
                "kind": "widget_chat",
                "conversation_id": conversation_id,
                "lead_id": lead_id,
            },
            href=(f"/leads/{lead_id}" if lead_id else "/leads"),
            priority="normal",
        )
    except Exception as exc:  # pragma: no cover — logged only
        logger.warning("[g1] admin bell fan-out failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════
@router.post("/widget/chat/conversations", status_code=201)
async def start_widget_conversation(
    body: ConvStart = ConvStart(),
    request: Request = None,  # noqa: ARG001 — kept for symmetry
    tenant: Dict[str, Any] = Depends(require_widget_auth),
):
    """Start a new anonymous chat session."""
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "page_url": body.page_url,
        "referrer": body.referrer,
        "visitor_name": None,
        "visitor_email": None,
        "visitor_phone": None,
        "lead_id": None,
        "escalated": False,
        "message_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.widget_chat_conversations.insert_one(doc)
    doc.pop("_id", None)
    # GH-Fix: expose both ``id`` (legacy) and ``conversation_id``
    # (canonical going forward) so the frontend can move to the new
    # name without waiting on a widget bundle rebuild.
    return {
        "id": doc["id"],
        "conversation_id": doc["id"],
        "tenant_id": doc["tenant_id"],
    }


@router.get("/widget/chat/conversations/{cid}")
async def get_widget_conversation(
    cid: str,
    tenant: Dict[str, Any] = Depends(require_widget_auth),
):
    conv = await _get_conversation(cid, tenant["id"])
    msgs = await db.widget_chat_messages.find(
        {"tenant_id": tenant["id"], "conversation_id": cid},
        {"_id": 0, "id": 1, "role": 1, "text": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(200)
    return {"conversation": conv, "messages": msgs}


@router.post("/widget/chat/conversations/{cid}/messages",
              status_code=201)
async def post_widget_message(
    cid: str,
    body: WidgetMsgIn,
    background_tasks: BackgroundTasks,
    tenant: Dict[str, Any] = Depends(require_widget_auth),
):
    """Send a visitor turn + get the assistant reply.

    Also opportunistically extracts contact info from the visitor's
    message, creates/updates a ``leads`` doc, and fires an admin bell
    on booking-intent-with-contact-captured events.
    """
    # Body sanity — cid in URL must match cid in payload.
    if body.conversation_id and body.conversation_id != cid:
        raise HTTPException(400, "conversation_id mismatch")

    conv = await _get_conversation(cid, tenant["id"])

    # 1) Persist the visitor turn.
    user_msg = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "conversation_id": cid,
        "role": "user",
        "text": body.text,
        "created_at": now_iso(),
    }
    await db.widget_chat_messages.insert_one(user_msg)

    # 2) Extract contact + booking intent.
    contact = _extract_contact(body.text)
    booking_intent = _looks_booking(body.text)

    # 3) Update conversation contact fields (only when we found new info).
    conv_updates: Dict[str, Any] = {"updated_at": now_iso()}
    if contact.get("email") and not conv.get("visitor_email"):
        conv_updates["visitor_email"] = contact["email"]
    if contact.get("phone") and not conv.get("visitor_phone"):
        conv_updates["visitor_phone"] = contact["phone"]
    if contact.get("name") and not conv.get("visitor_name"):
        conv_updates["visitor_name"] = contact["name"]

    # 4) Lead upsert (only if visitor has provided at least one contact).
    lead_id = conv.get("lead_id")
    new_lead_created = False
    if any([contact.get("email"), contact.get("phone")]):
        lead_id = await _upsert_lead(
            conv, tenant["id"], contact=contact,
            first_user_text=body.text,
            page_url=conv.get("page_url"),
        )
        if lead_id and lead_id != conv.get("lead_id"):
            new_lead_created = True
            conv_updates["lead_id"] = lead_id
            # Feb-2026 · P18 — dispatch tenant-configured SMS+email
            # lead alerts on brand-new widget-chat leads.  Deferred
            # via BackgroundTasks; no-op when recipient lists empty.
            _created = getattr(_upsert_lead, "_last_created", None)
            if _created and _created.get("lead", {}).get("id") == lead_id:
                try:
                    from services.lead_notifications import send_lead_alert_notifications
                    send_lead_alert_notifications(
                        lead=_created["lead"], tenant=tenant,
                        background_tasks=background_tasks,
                    )
                except Exception as _e:  # noqa: BLE001
                    logger.warning(f"[p18] widget-chat alert failed: {_e}")
                _upsert_lead._last_created = None                       # type: ignore[attr-defined]

    # 5) Build the LLM system prompt with a live capture-state hint so
    #    the model knows whether it still needs to ask for contact info.
    have_email = bool(conv_updates.get("visitor_email") or conv.get("visitor_email"))
    have_phone = bool(conv_updates.get("visitor_phone") or conv.get("visitor_phone"))
    have_name = bool(conv_updates.get("visitor_name") or conv.get("visitor_name"))

    capture_status = (
        f"[capture_state] name={'yes' if have_name else 'no'}, "
        f"email={'yes' if have_email else 'no'}, "
        f"phone={'yes' if have_phone else 'no'}, "
        f"booking_intent_detected={'yes' if booking_intent else 'no'}."
    )
    system_prompt = ANON_SYSTEM_PROMPT + "\n\n" + capture_status

    # 6) Fetch history for LLM context (before we inserted the current
    #    user turn again — we already inserted it, so read latest).
    history = await db.widget_chat_messages.find(
        {"tenant_id": tenant["id"], "conversation_id": cid},
        {"_id": 0, "role": 1, "text": 1},
    ).sort("created_at", 1).to_list(HISTORY_WINDOW)

    r = await _llm_chat(system_prompt, body.text, history[:-1])
    assistant_text = r["text"]
    provider = r.get("provider", "stub")

    # 7) Persist assistant turn.
    assistant_msg = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "conversation_id": cid,
        "role": "assistant",
        "text": assistant_text,
        "provider": provider,
        "created_at": now_iso(),
    }
    await db.widget_chat_messages.insert_one(assistant_msg)

    # 8) Escalation to admin bell:
    #    - booking intent detected AND we have a captured contact
    #    - OR a brand new lead was created (first contact drop)
    escalated = False
    if new_lead_created or (booking_intent and (have_email or have_phone) and lead_id):
        conv_updates["escalated"] = True
        escalated = True
        who = conv_updates.get("visitor_name") or conv.get("visitor_name") or "Website visitor"
        contact_str = (
            conv_updates.get("visitor_email") or conv.get("visitor_email")
            or conv_updates.get("visitor_phone") or conv.get("visitor_phone")
            or "no contact yet"
        )
        await _fire_admin_bell(
            tenant["id"],
            title=(f"Chat widget lead — {who}"
                     if new_lead_created else
                     f"Chat widget booking request — {who}"),
            body=f"{contact_str} · {body.text[:180]}",
            lead_id=lead_id,
            conversation_id=cid,
        )

        # Phase-3 · SMS escalation to configured recipients.  Tenant
        # settings ``sms_escalation_recipients`` drives fan-out; when
        # absent falls back to the tenant primary admin phone.  When
        # neither is populated we log and no-op — no send attempts.
        try:
            tenant_row = await db.tenants.find_one(
                {"id": tenant["id"]}, {"_id": 0},
            ) or {}
            recips: list = list(tenant_row.get("sms_escalation_recipients") or [])
            if not recips:
                # Fallback: first admin user's phone.
                admin_row = await db.users.find_one(
                    {"tenant_id": tenant["id"],
                     "role": {"$in": ["admin", "super_admin"]},
                     "phone": {"$exists": True, "$ne": ""}},
                    {"_id": 0, "phone": 1},
                )
                if admin_row and admin_row.get("phone"):
                    recips = [admin_row["phone"]]
            if not recips:
                logger.warning(
                    "[widget-chat] escalation for tenant=%s but no sms_"
                    "escalation_recipients configured — SMS not sent.",
                    tenant["id"],
                )
            else:
                from services.sms.rc_adapter import send as _sms_send
                sms_body = (
                    f"{tenant_row.get('name') or 'Widget'} chat lead "
                    f"({cid[:8]}): {who} · {contact_str} — "
                    f"{body.text[:120]}"
                )
                for r in recips[:5]:  # hard cap fan-out
                    try:
                        await _sms_send(
                            to=r, body=sms_body,
                            category="transactional",
                            tenant_id=tenant["id"],
                            idempotency_key=f"chat-esc:{cid}",
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.warning("[widget-chat] esc SMS %s: %s", r, exc)
        except Exception as exc:  # pragma: no cover
            logger.warning("[widget-chat] escalation wiring crashed: %s", exc)

    # 9) Persist conversation updates + bump counter.
    await db.widget_chat_conversations.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": conv_updates, "$inc": {"message_count": 2}},
    )

    user_msg.pop("_id", None)
    assistant_msg.pop("_id", None)
    return {
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "lead_id": lead_id,
        "escalated": escalated,
        "booking_intent": booking_intent,
    }
