"""Phase 9 — AI Employees, AI Chat, Tasks, Notifications, Permissions,
RingCentral call tracking, and sequences tick manual trigger."""
import os
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin, get_current_user

router = APIRouter()

STUBBED = not bool(os.environ.get("EMERGENT_LLM_KEY", ""))

# ─── seed AI Employees ─────────────────────────────────────────────────────
SEEDED_EMPLOYEES = [
    {"slug": "ava", "name": "Ava", "role": "customer_service", "avatar": "🙂",
     "system_prompt": "You are Ava, a friendly customer service AI for a pool & landscaping company.",
     "guardrails": ["Never quote a firm price", "Escalate refunds to a human"], "enabled": True, "memory_scope": "per-customer"},
    {"slug": "max", "name": "Max", "role": "sales", "avatar": "💼",
     "system_prompt": "You are Max, a consultative sales AI.",
     "guardrails": ["Never discount below 10%"], "enabled": True, "memory_scope": "per-customer"},
    {"slug": "riley", "name": "Riley", "role": "scheduling", "avatar": "📅",
     "system_prompt": "You are Riley, a scheduling assistant.",
     "guardrails": ["Never double-book a tech"], "enabled": True, "memory_scope": "global"},
    {"slug": "sam", "name": "Sam", "role": "billing", "avatar": "🧾",
     "system_prompt": "You are Sam, a billing assistant.",
     "guardrails": ["Never share other customers' balances"], "enabled": True, "memory_scope": "per-customer"},
    {"slug": "nora", "name": "Nora", "role": "content_writer", "avatar": "✍️",
     "system_prompt": "You are Nora, a long-form marketing content writer.",
     "guardrails": ["Never use banned phrases"], "enabled": True, "memory_scope": "campaign"},
    {"slug": "content-writer", "name": "Content Writer", "role": "content_writer", "avatar": "📝",
     "system_prompt": "Long-form marketing copy specialist.", "guardrails": [], "enabled": True, "memory_scope": "campaign"},
    {"slug": "seo-specialist", "name": "SEO Specialist", "role": "seo_specialist", "avatar": "🔎",
     "system_prompt": "SEO strategist focused on keyword + on-page angle.", "guardrails": [], "enabled": True, "memory_scope": "campaign"},
    {"slug": "ads-copywriter", "name": "Ads Copywriter", "role": "ads_copywriter", "avatar": "🎯",
     "system_prompt": "Short punchy conversion copy expert.", "guardrails": [], "enabled": True, "memory_scope": "campaign"},
]


async def ensure_ai_employees_seeded():
    for emp in SEEDED_EMPLOYEES:
        existing = await db.ai_employees.find_one({"slug": emp["slug"]}, {"_id": 0})
        if not existing:
            doc = {"id": new_id(), **emp, "created_at": now_iso()}
            await db.ai_employees.insert_one(doc)
    logger.info(f"AI Employees seeded ({len(SEEDED_EMPLOYEES)} personas).")


# ─── AI Employees CRUD ─────────────────────────────────────────────────────
class EmployeeIn(BaseModel):
    name: str
    role: str
    avatar: Optional[str] = "🤖"
    system_prompt: Optional[str] = ""
    guardrails: Optional[List[str]] = []
    enabled: Optional[bool] = True
    memory_scope: Optional[str] = "global"


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    avatar: Optional[str] = None
    system_prompt: Optional[str] = None
    guardrails: Optional[List[str]] = None
    enabled: Optional[bool] = None
    memory_scope: Optional[str] = None


class ChatIn(BaseModel):
    message: str
    thread_id: Optional[str] = None


@router.get("/ai-ops/employees")
async def list_employees(admin: dict = Depends(require_admin)):
    return await db.ai_employees.find({}, {"_id": 0}).sort("name", 1).to_list(200)


@router.post("/ai-ops/employees")
async def create_employee(body: EmployeeIn, admin: dict = Depends(require_admin)):
    doc = {"id": new_id(), "slug": body.name.lower().replace(" ", "-"),
           **body.dict(), "created_at": now_iso()}
    await db.ai_employees.insert_one(doc); doc.pop("_id", None); return doc


@router.get("/ai-ops/employees/{eid}")
async def get_employee(eid: str, admin: dict = Depends(require_admin)):
    d = await db.ai_employees.find_one({"$or": [{"id": eid}, {"slug": eid}]}, {"_id": 0})
    if not d: raise HTTPException(404, "Not found")
    return d


@router.patch("/ai-ops/employees/{eid}")
async def patch_employee(eid: str, body: EmployeeUpdate, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.ai_employees.update_one({"id": eid}, {"$set": upd})
    return await db.ai_employees.find_one({"id": eid}, {"_id": 0})


@router.delete("/ai-ops/employees/{eid}")
async def delete_employee(eid: str, admin: dict = Depends(require_admin)):
    await db.ai_employees.delete_one({"id": eid}); return {"ok": True}


@router.post("/ai-ops/employees/{eid}/chat")
async def chat_with_employee(eid: str, body: ChatIn, admin: dict = Depends(require_admin)):
    emp = await db.ai_employees.find_one({"$or": [{"id": eid}, {"slug": eid}]}, {"_id": 0})
    if not emp: raise HTTPException(404, "Not found")
    thread_id = body.thread_id or new_id()
    stub_response = (
        f"[{emp['name']} · {emp['role']}] Placeholder response — real AI activates once "
        "EMERGENT_LLM_KEY is configured. Guardrails: "
        + (", ".join(emp.get("guardrails") or []) or "none")
    )
    turn = {"id": new_id(), "employee_id": emp["id"], "user_id": admin["id"],
            "thread_id": thread_id, "role": "user", "content": body.message, "created_at": now_iso()}
    reply = {"id": new_id(), "employee_id": emp["id"], "user_id": admin["id"],
             "thread_id": thread_id, "role": "assistant", "content": stub_response, "created_at": now_iso()}
    await db.ai_chat_turns.insert_many([turn, reply])
    return {"response": stub_response, "thread_id": thread_id, "stubbed": STUBBED}


@router.get("/ai-ops/employees/{eid}/memory")
async def get_memory(eid: str, admin: dict = Depends(require_admin)):
    return await db.ai_employee_memory.find({"employee_id": eid}, {"_id": 0}).to_list(500)


@router.delete("/ai-ops/employees/{eid}/memory/{fact_id}")
async def del_memory(eid: str, fact_id: str, admin: dict = Depends(require_admin)):
    await db.ai_employee_memory.delete_one({"id": fact_id, "employee_id": eid})
    return {"ok": True}


# ─── Tasks ─────────────────────────────────────────────────────────────────
class TaskIn(BaseModel):
    title: str
    description: Optional[str] = ""
    due_date: Optional[str] = None
    priority: str = "med"
    assigned_to: Optional[str] = None
    related_ref: Optional[dict] = None
    source: str = "manual"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    status: Optional[str] = None


@router.get("/tasks")
async def list_tasks(admin: dict = Depends(require_admin), status: Optional[str] = None,
                     assigned_to: Optional[str] = None, source: Optional[str] = None):
    q = {}
    if status: q["status"] = status
    if assigned_to: q["assigned_to"] = assigned_to
    if source: q["source"] = source
    return await db.tasks.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/tasks")
async def create_task(body: TaskIn, admin: dict = Depends(require_admin)):
    doc = {"id": new_id(), **body.dict(), "status": "open",
           "created_at": now_iso(), "created_by": admin["id"]}
    await db.tasks.insert_one(doc); doc.pop("_id", None); return doc


@router.get("/tasks/{tid}")
async def get_task(tid: str, admin: dict = Depends(require_admin)):
    d = await db.tasks.find_one({"id": tid}, {"_id": 0})
    if not d: raise HTTPException(404, "Not found")
    return d


@router.patch("/tasks/{tid}")
async def patch_task(tid: str, body: TaskUpdate, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.tasks.update_one({"id": tid}, {"$set": upd})
    return await db.tasks.find_one({"id": tid}, {"_id": 0})


@router.delete("/tasks/{tid}")
async def del_task(tid: str, admin: dict = Depends(require_admin)):
    await db.tasks.delete_one({"id": tid}); return {"ok": True}


@router.post("/tasks/{tid}/complete")
async def complete_task(tid: str, admin: dict = Depends(require_admin)):
    await db.tasks.update_one({"id": tid}, {"$set": {"status": "done", "completed_at": now_iso()}})
    return await db.tasks.find_one({"id": tid}, {"_id": 0})


# ─── Notifications ─────────────────────────────────────────────────────────
@router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    return await db.notifications.find(
        {"user_id": {"$in": [user["id"], "*"]}}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)


@router.post("/notifications/{nid}/read")
async def mark_read(nid: str, user: dict = Depends(get_current_user)):
    await db.notifications.update_one({"id": nid}, {"$set": {"read": True, "read_at": now_iso()}})
    return {"ok": True}


@router.post("/notifications/read-all")
async def read_all(user: dict = Depends(get_current_user)):
    r = await db.notifications.update_many(
        {"user_id": {"$in": [user["id"], "*"]}, "read": {"$ne": True}},
        {"$set": {"read": True, "read_at": now_iso()}},
    )
    return {"marked": r.modified_count}


async def create_notification(user_id: str, title: str, body: str, ref: dict | None = None):
    doc = {"id": new_id(), "user_id": user_id, "title": title, "body": body,
           "ref": ref or {}, "read": False, "created_at": now_iso()}
    await db.notifications.insert_one(doc)
    return doc


# ─── Permissions matrix ────────────────────────────────────────────────────
DEFAULT_PERMISSIONS = {
    "admin": {g: "write" for g in
              ["Customers", "Jobs", "Invoices", "Payments", "Reports", "Marketing", "SEO", "GBP", "D2D", "Settings"]},
    "technician": {"Jobs": "write", "Customers": "read"},
    "customer": {},
    "marketer": {"Marketing": "write", "SEO": "write", "GBP": "write"},
    "sales": {"Customers": "write", "Jobs": "read"},
}


@router.get("/permissions")
async def get_permissions(admin: dict = Depends(require_admin)):
    doc = await db.settings.find_one({"id": "permissions_matrix"}, {"_id": 0})
    return doc.get("matrix", DEFAULT_PERMISSIONS) if doc else DEFAULT_PERMISSIONS


@router.put("/permissions")
async def put_permissions(matrix: dict, admin: dict = Depends(require_admin)):
    await db.settings.update_one({"id": "permissions_matrix"},
                                 {"$set": {"id": "permissions_matrix", "matrix": matrix, "updated_at": now_iso()}},
                                 upsert=True)
    return matrix


# ─── RingCentral ───────────────────────────────────────────────────────────
class RingIn(BaseModel):
    webhook_url: Optional[str] = None
    api_key: Optional[str] = None
    account_id: Optional[str] = None


@router.get("/settings/ringcentral")
async def get_ring(admin: dict = Depends(require_admin)):
    doc = await db.settings.find_one({"id": "ringcentral"}, {"_id": 0}) or {}
    return {"webhook_url": doc.get("webhook_url"), "account_id": doc.get("account_id"),
            "configured": bool(doc.get("api_key"))}


@router.put("/settings/ringcentral")
async def put_ring(body: RingIn, admin: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    await db.settings.update_one({"id": "ringcentral"},
                                 {"$set": {"id": "ringcentral", **upd, "updated_at": now_iso()}},
                                 upsert=True)
    return await get_ring(admin)


@router.get("/call-logs")
async def list_call_logs(admin: dict = Depends(require_admin)):
    return await db.call_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/ringcentral/webhook")
async def ringcentral_webhook(request: Request):
    """Public — RingCentral posts here. Signature check skipped when unconfigured."""
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    from_number = (body.get("from") or {}).get("phoneNumber") or body.get("from_number") or ""
    to_number = (body.get("to") or {}).get("phoneNumber") or body.get("to_number") or ""
    duration = body.get("duration") or 0
    recording_url = (body.get("recording") or {}).get("contentUri") or body.get("recording_url")
    # Match customer by phone
    match = None
    if from_number:
        match = await db.customers.find_one({"phones": from_number}, {"_id": 0}) or \
                await db.customers.find_one({"phones": {"$regex": from_number[-7:]}}, {"_id": 0})
    log = {
        "id": new_id(), "from_number": from_number, "to_number": to_number,
        "duration": duration, "recording_url": recording_url,
        "customer_id": (match or {}).get("id"),
        "customer_name": (match or {}).get("name"),
        "created_at": now_iso(), "raw": body,
    }
    await db.call_logs.insert_one(log)
    # Create a lead if unknown
    if not match and from_number:
        await db.leads.insert_one({
            "id": new_id(), "source": "ringcentral-inbound",
            "phone": from_number, "name": f"Unknown caller {from_number[-4:]}",
            "created_at": now_iso(), "status": "new",
        })
    log.pop("_id", None); return {"ok": True, "log_id": log["id"]}


# ─── Manual sequences tick trigger ─────────────────────────────────────────
@router.post("/sequences/tick/run")
async def manual_tick(admin: dict = Depends(require_admin)):
    from routers.sequences import run_sequences_tick
    await run_sequences_tick()
    return {"ok": True}
