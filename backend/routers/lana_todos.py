"""Phase 49 · Feb-2026 — Lana todos + reminders REST surface."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils import get_current_user
from routers.tenants import get_current_tenant
from services.lana import todos as todos_svc
from services.lana import reminders as reminders_svc


router = APIRouter(prefix="/api")


class TodoIn(BaseModel):
    text: str
    due_at: Optional[str] = None


class TodoPatch(BaseModel):
    text: Optional[str] = None
    due_at: Optional[str] = None
    completed: Optional[bool] = None


class ReminderIn(BaseModel):
    text: str
    remind_at: str
    phone: Optional[str] = None


_ADMIN_ROLES = {"admin", "super_admin", "manager"}


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "admin_only")


# ── Todos ─────────────────────────────────────────────────────────────
@router.get("/lana/todos")
async def list_todos(include_completed: bool = False,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    from server import db
    rows = await todos_svc.list_todos(
        db, tenant_id=tenant["id"], user_id=user["id"],
        include_completed=include_completed,
    )
    return {"items": rows}


@router.post("/lana/todos")
async def create_todo(body: TodoIn,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    if not (body.text or "").strip():
        raise HTTPException(422, "text required")
    from server import db
    return await todos_svc.create_todo(
        db, tenant_id=tenant["id"], user_id=user["id"],
        text=body.text, due_at=body.due_at,
    )


@router.patch("/lana/todos/{todo_id}")
async def update_todo(todo_id: str, body: TodoPatch,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    from server import db
    row = await todos_svc.update_todo(
        db, tenant_id=tenant["id"], user_id=user["id"], todo_id=todo_id,
        patch=body.model_dump(exclude_none=True),
    )
    if not row:
        raise HTTPException(404, "todo_not_found")
    return row


@router.delete("/lana/todos/{todo_id}")
async def delete_todo(todo_id: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    from server import db
    ok = await todos_svc.delete_todo(
        db, tenant_id=tenant["id"], user_id=user["id"], todo_id=todo_id,
    )
    if not ok:
        raise HTTPException(404, "todo_not_found")
    return {"ok": True}


# ── Reminders ─────────────────────────────────────────────────────────
@router.get("/lana/reminders")
async def list_reminders(only_upcoming: bool = True,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    from server import db
    rows = await reminders_svc.list_reminders(
        db, tenant_id=tenant["id"], user_id=user["id"],
        only_upcoming=only_upcoming,
    )
    return {"items": rows}


@router.post("/lana/reminders")
async def create_reminder(body: ReminderIn,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    _require_admin(user)
    if not (body.text or "").strip():
        raise HTTPException(422, "text required")
    from server import db
    return await reminders_svc.create_reminder(
        db, tenant_id=tenant["id"], user_id=user["id"],
        text=body.text, remind_at=body.remind_at, phone=body.phone,
    )
