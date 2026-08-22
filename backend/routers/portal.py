from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from datetime import datetime, timedelta

from config import db, logger, EMERGENT_LLM_KEY
from utils import now_iso, new_id, get_current_user, require_admin, notify_customer, create_staff_notification
from routers.tenants import get_current_tenant
from models import MessageIn, DocumentIn, BookIn
from emergentintegrations.llm.chat import LlmChat, UserMessage

router = APIRouter()

AI_SUPPORT_NAME = "Marina (AI)"
SCHED_KEYWORDS = ["schedule", "book", "appointment", "come out", "reschedul", "availab",
                  "when can", "visit", "slot", "next week", "stop by", "service call", "clean", "time"]


def _wants_scheduling(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in SCHED_KEYWORDS)


def _require_customer(user: dict):
    if user.get("role") != "customer" or not user.get("customer_id"):
        raise HTTPException(403, "Customers only")
    return user["customer_id"]


async def _suggest_slots():
    """Return up to 3 upcoming weekday appointment windows with the lightest schedule."""
    slots = []
    d = datetime.utcnow()
    checked = 0
    while len(slots) < 3 and checked < 14:
        d += timedelta(days=1)
        checked += 1
        if d.weekday() >= 5:  # skip weekends
            continue
        cnt = await db.jobs.count_documents({"scheduled_date": {"$regex": f"^{d.date().isoformat()}"}})
        window = "morning (8am–12pm)" if cnt % 2 == 0 else "afternoon (1pm–5pm)"
        slots.append({"date": d.date().isoformat(), "window": window, "label": f"{d.strftime('%A %b %d')} — {window}"})
    return slots


async def generate_ai_reply(cid: str, incoming: str):
    """Marina (AI) auto-reply. Returns (text, slots) where slots is set for scheduling intents."""
    if not EMERGENT_LLM_KEY:
        return None, None
    try:
        cust = await db.customers.find_one({"id": cid}, {"_id": 0}) or {}
        unpaid = await db.quotes.find(
            {"customer_id": cid, "doc_type": "invoice", "payment_status": "unpaid"}, {"_id": 0}
        ).to_list(100)
        balance = round(sum(q.get("total", 0.0) for q in unpaid), 2)
        inv_summary = "; ".join(f"{q.get('title', 'Invoice')} (${q.get('total', 0):.2f})" for q in unpaid) or "none"
        slots = await _suggest_slots()
        slot_labels = "; ".join(s["label"] for s in slots)
        history = await db.messages.find({"customer_id": cid}, {"_id": 0}).sort("created_at", 1).to_list(12)
        convo = "\n".join(
            f"{'Customer' if m.get('sender') == 'customer' else 'You'}: {m.get('text','')}" for m in history[-10:]
        )
        system = (
            f"You are Marina, a warm, professional customer support agent for Pool & Landscaping of Vistancia. "
            # Feb-2026 · P22 — Do NOT interpolate the customer's real
            # name into the LLM prompt; the customer's own message
            # arrives via ``user_text`` and the reply flows back into
            # the portal thread where the name is already visible.
            f"You are messaging with a valued customer.\n"
            f"BILLING: Their current outstanding balance is ${balance:.2f} across {len(unpaid)} unpaid invoice(s): {inv_summary}. "
            f"Answer billing questions using ONLY this info; to pay, tell them to open the Invoices section. Never invent charges.\n"
            f"SCHEDULING: If they want to book or reschedule service, offer these open windows and ask them to tap one to request it: "
            f"{slot_labels or 'ask them for a preferred day and we will confirm'}. "
            f"Tell them our team will confirm the final time.\n"
            f"Answer general pool/landscaping questions too. Be concise (under 120 words), friendly. "
            f"If something needs a human, say a team member will follow up shortly."
        )
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"portal-{cid}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-6")
        user_text = (
            f"Recent conversation for context:\n{convo}\n\n"
            f"LATEST CUSTOMER MESSAGE: \"{incoming}\"\n\n"
            f"Answer THIS latest message directly and specifically. If it is about billing or what they owe, "
            f"lead with the billing details. Only bring up appointment times if they are asking about scheduling."
        )
        reply = await chat.send_message(UserMessage(text=user_text))
        text = reply if isinstance(reply, str) else str(reply)
        return text, (slots if _wants_scheduling(incoming) else None)
    except Exception as e:
        logger.warning(f"AI auto-reply failed: {e}")
        return None, None


# ----------------------- Customer messages -----------------------
@router.get("/me/messages")
async def my_messages(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    msgs = await db.messages.find(
        {"customer_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(1000)
    await db.messages.update_many(
        {"customer_id": cid, "tenant_id": tenant["id"], "read_by_customer": False},
        {"$set": {"read_by_customer": True}},
    )
    return msgs


@router.post("/me/messages")
async def send_my_message(body: MessageIn,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cid, "sender": "customer",
        "sender_name": user.get("name", "Customer"), "text": body.text,
        "read_by_customer": True, "read_by_staff": False, "created_at": now_iso(),
    }
    await db.messages.insert_one(doc)
    doc.pop("_id", None)

    try:
        from routers.realtime import bus
        admins = await db.users.find(
            {"role": "admin", "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
        ).to_list(100)
        for a in admins:
            await bus.broadcast(a["id"], {
                "type": "new_message",
                "payload": {"customer_id": cid, "text": (body.text or "")[:200], "sender": "customer"},
            })
    except Exception:
        pass

    ai_doc = None
    cust = await db.customers.find_one({"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}) or {}
    if not cust.get("ai_paused"):
        ai_text, slots = await generate_ai_reply(cid, body.text)
        if ai_text:
            ai_doc = {
                "id": new_id(), "tenant_id": tenant["id"],
                "customer_id": cid, "sender": "business",
                "sender_name": AI_SUPPORT_NAME, "text": ai_text, "ai": True,
                "read_by_customer": True, "read_by_staff": True, "created_at": now_iso(),
            }
            if slots:
                ai_doc["slots"] = slots
            await db.messages.insert_one(ai_doc)
            ai_doc.pop("_id", None)
    return {"message": doc, "ai_reply": ai_doc}


@router.post("/me/book")
async def book_slot(body: BookIn,
                    user: dict = Depends(get_current_user),
                    tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    cust = await db.customers.find_one({"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}) or {}
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "title": "Service Request", "service_type": "Pool Cleaning",
        "customer_id": cid, "customer_name": cust.get("name", "Customer"),
        "address": cust.get("address", ""), "status": "requested",
        "scheduled_date": body.date, "price": 0, "photos": [],
        "notes": f"Requested via chat: {body.label}", "created_at": now_iso(),
    }
    await db.jobs.insert_one(job)
    msg = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cid, "sender": "business",
        "sender_name": AI_SUPPORT_NAME, "ai": True,
        "text": f"✅ Great! I've requested {body.label}. Our team will confirm your appointment shortly.",
        "read_by_customer": True, "read_by_staff": False, "created_at": now_iso(),
    }
    await db.messages.insert_one(msg)
    msg.pop("_id", None)
    await db.messages.update_many(
        {"customer_id": cid, "tenant_id": tenant["id"], "slots": {"$exists": True}},
        {"$unset": {"slots": ""}},
    )
    await create_staff_notification(
        "New booking request",
        f"{cust.get('name', 'A customer')} requested {body.label}",
        tenant_id=tenant["id"],
    )
    return {"message": msg}


# ----------------------- Admin communications -----------------------
@router.get("/communications")
async def list_threads(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    msgs = await db.messages.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(5000)
    threads: dict = {}
    for m in msgs:
        cid = m.get("customer_id")
        if cid not in threads:
            threads[cid] = {
                "customer_id": cid, "customer_name": "", "last_text": m["text"],
                "last_at": m["created_at"], "unread": 0,
            }
        if m.get("sender") == "customer" and not m.get("read_by_staff"):
            threads[cid]["unread"] += 1
    for cid, t in threads.items():
        cust = await db.customers.find_one({"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
        t["customer_name"] = cust.get("name", "Customer") if cust else "Customer"
    return sorted(threads.values(), key=lambda x: x["last_at"], reverse=True)


@router.get("/communications/{cid}")
async def get_thread(cid: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    msgs = await db.messages.find(
        {"customer_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(1000)
    await db.messages.update_many(
        {"customer_id": cid, "tenant_id": tenant["id"], "read_by_staff": False},
        {"$set": {"read_by_staff": True}},
    )
    cust = await db.customers.find_one({"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    return {
        "customer_name": cust.get("name", "Customer") if cust else "Customer",
        "ai_paused": bool(cust.get("ai_paused")) if cust else False,
        "messages": msgs,
    }


@router.post("/communications/{cid}/ai-toggle")
async def toggle_ai(cid: str,
                    paused: bool = Query(...),
                    user: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    await db.customers.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": {"ai_paused": paused}}
    )
    return {"ai_paused": paused}


@router.post("/communications/{cid}/reply")
async def reply_thread(cid: str, body: MessageIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cid, "sender": "business",
        "sender_name": user.get("name", "Support"), "text": body.text,
        "read_by_customer": False, "read_by_staff": True, "created_at": now_iso(),
    }
    await db.messages.insert_one(doc)
    doc.pop("_id", None)
    await notify_customer(cid, "New message", body.text)
    return doc


# ----------------------- Documents -----------------------
@router.get("/me/documents")
async def my_documents(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    cid = _require_customer(user)
    return await db.documents.find(
        {"customer_id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.get("/documents")
async def list_documents(customer_id: str = Query(...),
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    return await db.documents.find(
        {"customer_id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)


@router.post("/documents")
async def upload_document(body: DocumentIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    cust = await db.customers.find_one({"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Customer not found")
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": body.customer_id, "name": body.name,
        "type": body.type, "data": body.data, "uploaded_by": user.get("name", "Admin"),
        "created_at": now_iso(),
    }
    await db.documents.insert_one(doc)
    doc.pop("_id", None)
    await notify_customer(body.customer_id, "New document", f"'{body.name}' was shared with you.")
    return doc


@router.delete("/documents/{did}")
async def delete_document(did: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.documents.delete_one({"id": did, "tenant_id": tenant["id"]})
    return {"ok": True}
