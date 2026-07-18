"""Phase 4 · Batch B / Deliverable 6 — Company Handbook + Onboarding v2.

Distinct from the pre-existing `onboarding.py` (admin one-time wizard) and
`employee_onboarding.py` (HR checklist templates + assignments) — this
router ships the Batch B spec:

  * `db.company_handbook_sections` — CRUD + tenant-custom overrides
  * `db.onboarding_tasks`          — role-scoped task catalogue
  * `db.onboarding_progress`       — per-user completion + evidence

Route prefixes:
  * `/api/handbook/*`
  * `/api/onboarding/*` — but only sub-paths that don't collide with
    the two existing routers:
      GET   /onboarding/tasks
      POST  /onboarding/tasks
      PATCH /onboarding/tasks/{code}
      GET   /onboarding/user-progress?user_id=...
      POST  /onboarding/user-progress/mark-complete
      GET   /onboarding/dashboard

Auto-complete hooks live at the bottom of the file and are invoked by
the templates router when an instance is finalized.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant


router = APIRouter()


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


# ─── Handbook Sections ─────────────────────────────────────────────

class SectionIn(BaseModel):
    code: str
    title: str
    order: int = 0
    markdown_body: str
    is_system: bool = False


class SectionPatch(BaseModel):
    title: Optional[str] = None
    order: Optional[int] = None
    markdown_body: Optional[str] = None


async def _load_sections_for(tenant_id: str) -> List[Dict[str, Any]]:
    """System sections + tenant-custom sections. Tenant custom
    overrides same-code system sections."""
    rows_system = await db.company_handbook_sections.find(
        {"is_system": True}, {"_id": 0}).sort("order", 1).to_list(500)
    rows_tenant = await db.company_handbook_sections.find(
        {"tenant_id": tenant_id, "is_system": False}, {"_id": 0}).sort("order", 1).to_list(500)
    by_code = {r["code"]: r for r in rows_system}
    for r in rows_tenant:
        by_code[r["code"]] = r  # override
    out = list(by_code.values())
    out.sort(key=lambda r: (r.get("order", 0), r.get("title") or ""))
    return out


@router.get("/handbook/sections")
async def list_sections(user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    return {"rows": await _load_sections_for(tenant["id"])}


@router.get("/handbook/sections/{code}")
async def get_section(code: str, user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    # Prefer tenant override
    for r in await _load_sections_for(tenant["id"]):
        if r["code"] == code:
            return r
    raise HTTPException(404, "Section not found")


@router.post("/handbook/sections")
async def create_section(body: SectionIn,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # Tenant-custom only (system content is only seeded, never created via API)
    doc = body.dict()
    doc["is_system"] = False
    doc["tenant_id"] = tenant["id"]
    doc["id"] = str(uuid.uuid4())
    doc["version"] = 1
    doc["updated_at"] = now_iso()
    doc["updated_by"] = user.get("email") or user.get("name") or user.get("id")
    # Enforce unique (tenant_id, code)
    existing = await db.company_handbook_sections.find_one(
        {"tenant_id": tenant["id"], "code": body.code, "is_system": False})
    if existing:
        raise HTTPException(409, "A tenant-custom section with that code already exists")
    await db.company_handbook_sections.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/handbook/sections/{code}")
async def update_section(code: str, patch: SectionPatch,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # Only tenant-custom sections may be edited.
    existing = await db.company_handbook_sections.find_one(
        {"tenant_id": tenant["id"], "code": code, "is_system": False})
    if not existing:
        # If a system section with this code exists, block explicitly
        sys_exists = await db.company_handbook_sections.find_one({"code": code, "is_system": True})
        if sys_exists:
            raise HTTPException(400, "System sections are read-only. Duplicate to a tenant-custom copy first.")
        raise HTTPException(404, "Section not found")
    updates = {k: v for k, v in patch.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No updates provided")
    updates["updated_at"] = now_iso()
    updates["updated_by"] = user.get("email") or user.get("name") or user.get("id")
    updates["version"] = int(existing.get("version") or 1) + 1
    await db.company_handbook_sections.update_one(
        {"id": existing["id"]}, {"$set": updates})
    updated = await db.company_handbook_sections.find_one({"id": existing["id"]}, {"_id": 0})
    return updated


@router.delete("/handbook/sections/{code}")
async def delete_section(code: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # System sections are permanent.
    sys_exists = await db.company_handbook_sections.find_one({"code": code, "is_system": True})
    if sys_exists:
        raise HTTPException(400, "System sections cannot be deleted")
    r = await db.company_handbook_sections.delete_one(
        {"tenant_id": tenant["id"], "code": code, "is_system": False})
    if r.deleted_count == 0:
        raise HTTPException(404, "Section not found")
    return {"ok": True}


# ─── Onboarding Tasks ───────────────────────────────────────────────

class TaskIn(BaseModel):
    code: str
    title: str
    description: Optional[str] = None
    required_role: Optional[str] = None  # None means all roles
    order: int = 0
    kind: str  # 'read_handbook_section' | 'training_module' | 'form_signature' | 'video_watch' | 'checklist'
    related_ref: Optional[str] = None


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_role: Optional[str] = None
    order: Optional[int] = None
    kind: Optional[str] = None
    related_ref: Optional[str] = None


async def _load_tasks_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    rows_system = await db.onboarding_tasks.find(
        {"is_system": True}, {"_id": 0}).to_list(500)
    rows_tenant = await db.onboarding_tasks.find(
        {"tenant_id": tenant_id, "is_system": False}, {"_id": 0}).to_list(500)
    by_code = {r["code"]: r for r in rows_system}
    for r in rows_tenant:
        by_code[r["code"]] = r
    tasks = list(by_code.values())
    tasks.sort(key=lambda r: (r.get("order", 0), r.get("title") or ""))
    return tasks


def _task_visible_for_role(task: dict, role: str) -> bool:
    req = task.get("required_role")
    if not req:
        return True
    return role == req


@router.get("/onboarding/tasks")
async def list_tasks(user: dict = Depends(get_current_user),
                      tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    tasks = await _load_tasks_for_tenant(tenant["id"])
    # Admin/super_admin see all tasks; non-admins see only their role tasks
    if role in ("admin", "super_admin"):
        return {"rows": tasks}
    return {"rows": [t for t in tasks if _task_visible_for_role(t, role)]}


@router.post("/onboarding/tasks")
async def create_task(body: TaskIn,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    doc = body.dict()
    doc["is_system"] = False
    doc["tenant_id"] = tenant["id"]
    doc["id"] = str(uuid.uuid4())
    doc["updated_at"] = now_iso()
    existing = await db.onboarding_tasks.find_one(
        {"tenant_id": tenant["id"], "code": body.code, "is_system": False})
    if existing:
        raise HTTPException(409, "A tenant-custom task with that code already exists")
    await db.onboarding_tasks.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/onboarding/tasks/{code}")
async def update_task(code: str, patch: TaskPatch,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    existing = await db.onboarding_tasks.find_one(
        {"tenant_id": tenant["id"], "code": code, "is_system": False})
    if not existing:
        sys_exists = await db.onboarding_tasks.find_one({"code": code, "is_system": True})
        if sys_exists:
            raise HTTPException(400, "System tasks are read-only. Duplicate to a tenant-custom copy first.")
        raise HTTPException(404, "Task not found")
    updates = {k: v for k, v in patch.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No updates provided")
    updates["updated_at"] = now_iso()
    await db.onboarding_tasks.update_one({"id": existing["id"]}, {"$set": updates})
    return await db.onboarding_tasks.find_one({"id": existing["id"]}, {"_id": 0})


# ─── Onboarding Progress ────────────────────────────────────────────

class MarkCompleteIn(BaseModel):
    task_code: str
    evidence: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None  # admin-only override


async def _get_or_create_progress(tenant_id: str, user_id: str, task_code: str) -> Dict[str, Any]:
    row = await db.onboarding_progress.find_one(
        {"tenant_id": tenant_id, "user_id": user_id, "task_code": task_code}, {"_id": 0})
    if row:
        return row
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "task_code": task_code,
        "status": "pending",
        "updated_at": now_iso(),
    }
    await db.onboarding_progress.insert_one(doc)
    return doc


@router.get("/onboarding/user-progress")
async def user_progress(user_id: str = Query("me"),
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    target_id = user["id"] if user_id in ("me", "", None) else user_id
    # Non-admins can only query self
    if target_id != user["id"] and role not in ("admin", "super_admin"):
        raise HTTPException(403, "Not allowed to query another user's progress")
    # Ensure target belongs to this tenant if querying someone else
    if target_id != user["id"]:
        u = await db.users.find_one({"id": target_id, "tenant_id": tenant["id"]}, {"_id": 0, "id": 1})
        if not u:
            raise HTTPException(404, "User not found in this tenant")
    rows = await db.onboarding_progress.find(
        {"tenant_id": tenant["id"], "user_id": target_id}, {"_id": 0}).to_list(500)
    tasks = await _load_tasks_for_tenant(tenant["id"])
    # Non-admin gets role-filtered task list
    target_role = role if target_id == user["id"] else None
    if target_role and target_role not in ("admin", "super_admin"):
        tasks = [t for t in tasks if _task_visible_for_role(t, target_role)]
    by_code = {r["task_code"]: r for r in rows}
    merged = []
    for t in tasks:
        p = by_code.get(t["code"]) or {"status": "pending"}
        merged.append({
            **t,
            "progress": {
                "status": p.get("status", "pending"),
                "completed_at": p.get("completed_at"),
                "evidence": p.get("evidence"),
            },
        })
    complete = sum(1 for m in merged if m["progress"]["status"] == "complete")
    return {
        "user_id": target_id,
        "total": len(merged),
        "complete": complete,
        "pct": (complete / len(merged) * 100.0) if merged else 100.0,
        "rows": merged,
    }


@router.post("/onboarding/user-progress/mark-complete")
async def mark_complete(body: MarkCompleteIn,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    target_id = body.user_id or user["id"]
    if target_id != user["id"] and role not in ("admin", "super_admin"):
        raise HTTPException(403, "Not allowed to complete tasks on behalf of another user")
    # Validate task exists
    tasks = await _load_tasks_for_tenant(tenant["id"])
    if not any(t["code"] == body.task_code for t in tasks):
        raise HTTPException(404, "Task not found")
    row = await _get_or_create_progress(tenant["id"], target_id, body.task_code)
    now = now_iso()
    await db.onboarding_progress.update_one(
        {"id": row["id"]},
        {"$set": {
            "status": "complete",
            "completed_at": now,
            "evidence": body.evidence,
            "updated_at": now,
        }})
    return await db.onboarding_progress.find_one({"id": row["id"]}, {"_id": 0})


@router.get("/onboarding/dashboard")
async def dashboard(user: dict = Depends(_require_admin),
                     tenant: dict = Depends(get_current_tenant),
                     role: Optional[str] = Query(None)):
    """Admin summary: onboarding completion per user in tenant."""
    # Pull users in tenant (optionally role-filtered)
    q = {"tenant_id": tenant["id"]}
    if role:
        q["role"] = role
    users = await db.users.find(q, {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1}).to_list(1000)
    tasks = await _load_tasks_for_tenant(tenant["id"])
    rows = []
    for u in users:
        # Role-filter the task set for this user
        their_role = u.get("role") or ""
        their_tasks = tasks if their_role in ("admin", "super_admin") else [
            t for t in tasks if _task_visible_for_role(t, their_role)]
        codes = [t["code"] for t in their_tasks]
        prog = await db.onboarding_progress.find(
            {"tenant_id": tenant["id"], "user_id": u["id"], "task_code": {"$in": codes}},
            {"_id": 0, "task_code": 1, "status": 1}).to_list(500)
        complete = sum(1 for p in prog if p.get("status") == "complete")
        rows.append({
            "user_id": u["id"],
            "name": u.get("name") or u.get("email"),
            "email": u.get("email"),
            "role": their_role,
            "total": len(codes),
            "complete": complete,
            "pct": (complete / len(codes) * 100.0) if codes else 100.0,
        })
    rows.sort(key=lambda r: r["pct"])
    return {
        "rows": rows,
        "total_users": len(rows),
        "avg_pct": (sum(r["pct"] for r in rows) / len(rows)) if rows else 0.0,
    }


# ─── Auto-complete hook (called by templates_library) ────────────
async def auto_complete_for_template_finalized(tenant_id: str, user_id: str,
                                                 template_code: str) -> None:
    """Called by templates_library when an instance is finalized.
    Auto-marks any onboarding task with `kind='form_signature'` and
    `related_ref == template_code` as complete for this user."""
    try:
        tasks = await _load_tasks_for_tenant(tenant_id)
        for t in tasks:
            if t.get("kind") == "form_signature" and t.get("related_ref") == template_code:
                row = await _get_or_create_progress(tenant_id, user_id, t["code"])
                await db.onboarding_progress.update_one(
                    {"id": row["id"]},
                    {"$set": {"status": "complete", "completed_at": now_iso(),
                              "evidence": {"source": "template_finalized",
                                            "template_code": template_code},
                              "updated_at": now_iso()}})
    except Exception:
        pass


async def ensure_indexes():
    try:
        await db.company_handbook_sections.create_index([("tenant_id", 1), ("code", 1)])
        await db.company_handbook_sections.create_index("code")
        await db.onboarding_tasks.create_index([("tenant_id", 1), ("code", 1)])
        await db.onboarding_tasks.create_index("code")
        await db.onboarding_progress.create_index([("tenant_id", 1), ("user_id", 1), ("task_code", 1)])
    except Exception:
        pass
