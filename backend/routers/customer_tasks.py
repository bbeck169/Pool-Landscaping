"""Customer Tasks — Feb-2026 Customer Detail Page Additions ship.

Minimal task/to-do model bound to a customer. Fires the ``task_assigned``
unified notification kind whenever a task is created with (or reassigned
to) a specific user_id.

Collection: ``customer_tasks``. Fields:
    id, tenant_id, customer_id, title, description,
    due_at (ISO string, optional),
    assigned_user_id (optional),
    status: "open" | "done" | "cancelled",
    priority: "low" | "normal" | "high",
    created_by_user_id, created_at,
    completed_at (nullable)

Endpoints (all under /api):
    GET  /customer-tasks?customer_id=&status=&assigned_user_id=
    POST /customer-tasks
    PATCH /customer-tasks/{tid}
    POST /customer-tasks/{tid}/complete
    DELETE /customer-tasks/{tid}
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

router = APIRouter(tags=["Customer Tasks"])

_ALLOWED_STATUS = {"open", "done", "cancelled"}
_ALLOWED_PRIORITY = {"low", "normal", "high"}


class TaskIn(BaseModel):
    customer_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ""
    due_at: Optional[str] = None
    assigned_user_id: Optional[str] = None
    priority: Optional[str] = "normal"


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_at: Optional[str] = None
    assigned_user_id: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


def _clean(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return d
    d.pop("_id", None)
    return d


async def _notify_assignee(*, tenant_id: str, task: dict,
                            actor: dict, prev_assignee: Optional[str] = None) -> None:
    """Fire ``task_assigned`` when a task is created/updated with an
    assignee, only if the assignee changed (or was set for the first
    time). Never blocks — swallow all errors."""
    try:
        assignee = task.get("assigned_user_id")
        if not assignee or assignee == actor.get("id"):
            return  # no assignee OR user assigned to themselves — no ping
        if prev_assignee == assignee:
            return  # no change
        from services.notifications import emit as notify_emit
        customer = await db.customers.find_one(
            {"id": task.get("customer_id"), "tenant_id": tenant_id},
            {"_id": 0, "name": 1, "id": 1},
        )
        cname = (customer or {}).get("name") or "customer"
        actor_name = actor.get("name") or actor.get("email") or "Someone"
        await notify_emit(
            [assignee],
            kind="task_assigned",
            title=f"Task assigned: {task.get('title', '')[:80]}",
            body=f"{actor_name} assigned you a task for {cname}",
            href=f"/customers/{task.get('customer_id')}?tab=tasks",
            tenant_id=tenant_id,
            audience="internal",
            source_ref={"kind": "customer_task", "id": task["id"]},
            customer_id=task.get("customer_id"),
        )
    except Exception as e:
        logger.warning(f"[customer_tasks] notify assignee failed: {e}")


@router.get("/customer-tasks")
async def list_tasks(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if status:
        if status not in _ALLOWED_STATUS:
            raise HTTPException(400, f"status must be one of {sorted(_ALLOWED_STATUS)}")
        q["status"] = status
    if assigned_user_id:
        q["assigned_user_id"] = assigned_user_id
    docs = await db.customer_tasks.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@router.post("/customer-tasks", status_code=201)
async def create_task(body: TaskIn,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not allowed")
    priority = body.priority or "normal"
    if priority not in _ALLOWED_PRIORITY:
        raise HTTPException(400, f"priority must be one of {sorted(_ALLOWED_PRIORITY)}")
    if not await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1}
    ):
        raise HTTPException(404, "Customer not found")
    task = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "due_at": body.due_at,
        "assigned_user_id": body.assigned_user_id,
        "priority": priority,
        "status": "open",
        "created_by_user_id": user["id"],
        "created_at": now_iso(),
        "completed_at": None,
    }
    await db.customer_tasks.insert_one(task)
    _clean(task)
    await _notify_assignee(tenant_id=tenant["id"], task=task, actor=user, prev_assignee=None)
    return task


@router.patch("/customer-tasks/{tid}")
async def patch_task(tid: str, body: TaskPatch,
                      user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not allowed")
    existing = await db.customer_tasks.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(404, "Task not found")
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if "status" in updates and updates["status"] not in _ALLOWED_STATUS:
        raise HTTPException(400, f"status must be one of {sorted(_ALLOWED_STATUS)}")
    if "priority" in updates and updates["priority"] not in _ALLOWED_PRIORITY:
        raise HTTPException(400, f"priority must be one of {sorted(_ALLOWED_PRIORITY)}")
    if updates.get("status") == "done" and not existing.get("completed_at"):
        updates["completed_at"] = now_iso()
    if updates.get("status") == "open":
        updates["completed_at"] = None
    prev_assignee = existing.get("assigned_user_id")
    await db.customer_tasks.update_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"$set": updates}
    )
    doc = _clean(await db.customer_tasks.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
    ))
    if doc:
        await _notify_assignee(
            tenant_id=tenant["id"], task=doc, actor=user, prev_assignee=prev_assignee,
        )
    return doc


@router.post("/customer-tasks/{tid}/complete")
async def complete_task(tid: str,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin", "technician"):
        raise HTTPException(403, "Not allowed")
    r = await db.customer_tasks.update_one(
        {"id": tid, "tenant_id": tenant["id"]},
        {"$set": {"status": "done", "completed_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Task not found")
    return _clean(await db.customer_tasks.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0}
    ))


@router.delete("/customer-tasks/{tid}", status_code=204)
async def delete_task(tid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Not allowed")
    await db.customer_tasks.delete_one({"id": tid, "tenant_id": tenant["id"]})
    return None
