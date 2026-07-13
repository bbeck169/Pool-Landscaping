"""Phase 7 — Sequence Automations engine.

APScheduler cron `sequences_tick` fires every 15 minutes, walks all active
enrollments, and advances any step whose `next_action_at <= now`.
"""
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()


class SequenceStep(BaseModel):
    delay_days: int = 0
    action_type: str  # email | sms | task | ai_reply
    template_slug: Optional[str] = None
    notes: Optional[str] = ""


class SequenceIn(BaseModel):
    name: str
    trigger: str  # customer_created | job_completed | invoice_created | invoice_overdue_30 | quote_sent | quote_approved | manual
    steps: List[SequenceStep] = []
    active: bool = True


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    trigger: Optional[str] = None
    steps: Optional[List[SequenceStep]] = None
    active: Optional[bool] = None


# ─── seed ───────────────────────────────────────────────────────────────────
SEEDED_SEQUENCES = [
    {"slug": "welcome-sequence", "name": "Welcome Sequence", "trigger": "customer_created",
     "steps": [
         {"delay_days": 0, "action_type": "email", "template_slug": "welcome-email", "notes": "Welcome email"},
         {"delay_days": 3, "action_type": "sms", "template_slug": None, "notes": "Any questions?"},
         {"delay_days": 7, "action_type": "email", "template_slug": None, "notes": "Service reminder"},
     ]},
    {"slug": "review-request", "name": "Review Request", "trigger": "job_completed",
     "steps": [
         {"delay_days": 1, "action_type": "email", "template_slug": "review-request-email"},
         {"delay_days": 7, "action_type": "sms", "template_slug": "review-request-sms", "notes": "Reminder if no review"},
     ]},
    {"slug": "overdue-invoice-sequence", "name": "Overdue Invoice Sequence",
     "trigger": "invoice_overdue_30",
     "steps": [
         {"delay_days": 0, "action_type": "email", "template_slug": "invoice-reminder-email"},
         {"delay_days": 15, "action_type": "sms", "template_slug": "invoice-past-due-sms", "notes": "AI-drafted reminder"},
         {"delay_days": 30, "action_type": "escalation_task", "notes": "Escalate to admin — create a high-priority task"},
     ]},
]


async def ensure_sequences_seeded():
    """Global startup: seed cross-tenant defaults (no tenant_id).
    Per-tenant sequences will be seeded lazily on first list_sequences call."""
    for seq in SEEDED_SEQUENCES:
        existing = await db.sequences.find_one({"slug": seq["slug"], "tenant_id": {"$in": [None, ""]}}, {"_id": 0})
        if not existing:
            doc = {"id": new_id(), "tenant_id": None, **seq, "active": True, "created_at": now_iso()}
            await db.sequences.insert_one(doc)
            logger.info(f"Seeded global sequence '{seq['slug']}'")
        else:
            await db.sequences.update_one(
                {"slug": seq["slug"], "tenant_id": {"$in": [None, ""]}},
                {"$set": {"steps": seq["steps"], "trigger": seq["trigger"]}},
            )


async def _ensure_tenant_sequences(tenant_id: str):
    """Ensure a tenant has its own copy of the seeded sequences on first access."""
    if await db.sequences.count_documents({"tenant_id": tenant_id}) == 0:
        for seq in SEEDED_SEQUENCES:
            await db.sequences.insert_one({
                "id": new_id(), "tenant_id": tenant_id, **seq,
                "active": True, "created_at": now_iso(),
            })


# ─── CRUD ──────────────────────────────────────────────────────────────────
@router.get("/sequences")
async def list_sequences(admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    await _ensure_tenant_sequences(tenant["id"])
    rows = await db.sequences.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    for r in rows:
        r["enrolled_count"] = await db.sequence_enrollments.count_documents(
            {"sequence_id": r["id"], "tenant_id": tenant["id"],
             "status": {"$in": ["active", "paused"]}})
        r["steps_count"] = len(r.get("steps", []))
    return rows


@router.post("/sequences")
async def create_sequence(body: SequenceIn,
                          admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    doc = {"id": new_id(), "tenant_id": tenant["id"], "slug": None,
           **body.dict(), "created_at": now_iso()}
    await db.sequences.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/sequences/{sid}")
async def get_sequence(sid: str,
                       admin: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = await db.sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Not found")
    return doc


@router.patch("/sequences/{sid}")
async def patch_sequence(sid: str, body: SequenceUpdate,
                         admin: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    upd["updated_at"] = now_iso()
    await db.sequences.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": upd}
    )
    return await db.sequences.find_one({"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})


@router.delete("/sequences/{sid}")
async def delete_sequence(sid: str,
                          admin: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    await db.sequences.delete_one({"id": sid, "tenant_id": tenant["id"]})
    return {"ok": True}


# ─── enrollment ─────────────────────────────────────────────────────────────
@router.post("/sequences/{sid}/enroll")
async def enroll(sid: str, customer_id: str,
                 admin: dict = Depends(require_admin),
                 tenant: dict = Depends(get_current_tenant)):
    seq = await db.sequences.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not seq:
        raise HTTPException(404, "Sequence not found")
    if not (seq.get("steps") or []):
        raise HTTPException(400, "Sequence has no steps")
    first_delay = int((seq["steps"][0] or {}).get("delay_days") or 0)
    next_at = (datetime.now(timezone.utc) + timedelta(days=first_delay)).isoformat()
    doc = {
        "id": new_id(), "tenant_id": tenant["id"],
        "sequence_id": sid, "customer_id": customer_id,
        "status": "active", "current_step": 0,
        "next_action_at": next_at, "started_at": now_iso(), "log": [],
    }
    await db.sequence_enrollments.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/sequences/{sid}/enrollments")
async def list_enrollments(sid: str,
                           admin: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    return await db.sequence_enrollments.find(
        {"sequence_id": sid, "tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("started_at", -1).to_list(500)


@router.post("/sequences/{sid}/pause")
async def pause_seq(sid: str,
                    admin: dict = Depends(require_admin),
                    tenant: dict = Depends(get_current_tenant)):
    await db.sequences.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": {"active": False}}
    )
    return {"ok": True}


@router.post("/sequences/{sid}/resume")
async def resume_seq(sid: str,
                     admin: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    await db.sequences.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": {"active": True}}
    )
    return {"ok": True}


@router.post("/sequences/{sid}/unenroll/{customer_id}")
async def unenroll(sid: str, customer_id: str,
                   admin: dict = Depends(require_admin),
                   tenant: dict = Depends(get_current_tenant)):
    r = await db.sequence_enrollments.update_many(
        {"sequence_id": sid, "customer_id": customer_id,
         "tenant_id": tenant["id"], "status": {"$in": ["active", "paused"]}},
        {"$set": {"status": "unenrolled", "ended_at": now_iso()}},
    )
    return {"unenrolled": r.modified_count}


# ─── ticker ─────────────────────────────────────────────────────────────────
async def run_sequences_tick():
    """APScheduler job — every 15 minutes. Advances any due enrollment."""
    now = datetime.now(timezone.utc)
    due = await db.sequence_enrollments.find(
        {"status": "active", "next_action_at": {"$lte": now.isoformat()}}, {"_id": 0}
    ).to_list(500)
    fired = 0
    for e in due:
        seq = await db.sequences.find_one({"id": e["sequence_id"]}, {"_id": 0})
        if not seq or not seq.get("active"):
            continue
        steps = seq.get("steps") or []
        current = int(e.get("current_step", 0))
        if current >= len(steps):
            await db.sequence_enrollments.update_one(
                {"id": e["id"]}, {"$set": {"status": "completed", "ended_at": now_iso()}})
            continue
        step = steps[current]
        log_entry = {"step": current, "action_type": step.get("action_type"),
                     "fired_at": now_iso(), "notes": step.get("notes")}
        # Stubbed side effect — real implementation would send email/SMS/task
        logger.info(f"sequences_tick: enrollment {e['id']} step {current} fired ({step.get('action_type')})")
        # NEW — auto-create an admin task when this step is an escalation.
        if step.get("action_type") == "escalation_task":
            try:
                cust = await db.customers.find_one({"id": e.get("customer_id")}, {"_id": 0}) or {}
                inv = await db.quotes.find_one({"id": e.get("trigger_invoice_id")}, {"_id": 0}) or {}
                admin_user = await db.users.find_one({"role": "admin", "active": {"$ne": False}}, {"_id": 0}) or {}
                due_iso = (inv.get("due_date") or "")[:10]
                days_past = 30
                if due_iso:
                    try:
                        days_past = (datetime.now(timezone.utc).date() - datetime.fromisoformat(due_iso).date()).days
                    except Exception:
                        pass
                task = {
                    "id": new_id(),
                    "title": f"Overdue invoice — customer {cust.get('name', '(unknown)')}",
                    "description": (
                        f"Auto-escalated from Overdue Invoice Sequence — invoice "
                        f"{inv.get('id', '?')[:8]} (${inv.get('total', 0)}) is {days_past} days past due. "
                        "Attempted email + SMS reminders, no response."
                    ),
                    "priority": "high",
                    "assigned_to": admin_user.get("id"),
                    "status": "open",
                    "source": "sequence-escalation",
                    "related_ref": {"type": "customer", "id": e.get("customer_id"),
                                    "invoice_id": e.get("trigger_invoice_id")},
                    "created_at": now_iso(),
                }
                await db.tasks.insert_one(task)
                if admin_user.get("id"):
                    await db.notifications.insert_one({
                        "id": new_id(), "user_id": admin_user["id"],
                        "title": f"New task: Overdue invoice — {cust.get('name', 'customer')}",
                        "body": "Auto-escalated from sequence. Click to open the task.",
                        "ref": {"type": "task", "id": task["id"]},
                        "read": False, "created_at": now_iso(),
                    })
                log_entry["task_id"] = task["id"]
                logger.info(f"sequences_tick: escalation task {task['id']} created for customer {e.get('customer_id')}")
            except Exception as ex:
                logger.warning(f"escalation task creation failed: {ex}")
        next_step = current + 1
        upd = {"$push": {"log": log_entry}, "$set": {}}
        if next_step >= len(steps):
            upd["$set"]["status"] = "completed"
            upd["$set"]["ended_at"] = now_iso()
        else:
            delay = int((steps[next_step] or {}).get("delay_days") or 0)
            upd["$set"]["current_step"] = next_step
            upd["$set"]["next_action_at"] = (now + timedelta(days=delay)).isoformat()
        await db.sequence_enrollments.update_one({"id": e["id"]}, upd)
        fired += 1
    if fired:
        logger.info(f"sequences_tick: {fired} enrollment(s) advanced.")
