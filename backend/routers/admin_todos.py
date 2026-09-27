"""Feb-2026 · MARCO · Sub-phase D — admin_todos CRUD REST surface.

Route prefix: ``/api/admin/todos``.  Fully tenant-scoped.  Distinct
from Lana's Phase 49 ``/api/lana/todos`` surface — different route,
different collection (``marco_admin_todos``), different model.

Auth: admin/super_admin/manager only.  Technicians and customers
get 403.

All rows carry:
  * ``tenant_id`` — enforced on every filter + create + update
  * ``created_by`` — the caller's user id
  * ``created_via`` — one of ``admin_manual`` (this router's POST)
    OR ``marco_voice`` / ``marco_chat`` (via the
    ``create_admin_todo`` tool in the AI Employees tool loop).

Sub-phase E's proactive cron reads from this collection to
dispatch reminder pings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant
from models import (
    AdminTodoIn, AdminTodoPatch, AdminTodoOut,
    MARCO_ADMIN_TODOS_COLLECTION,
)


router = APIRouter(prefix="/api")


_ADMIN_ROLES = {"admin", "super_admin", "manager"}


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "admin_only")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return uuid4().hex[:24]


class AdminTodosListOut(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


# ══════════════════════════════════════════════════════════════════
# GET /api/admin/todos  — list + filter + paginate
# ══════════════════════════════════════════════════════════════════
@router.get("/admin/todos", response_model=AdminTodosListOut)
async def list_admin_todos(
    status: Optional[str] = Query(
        None, pattern="^(open|done|snoozed|deleted)$",
    ),
    priority: Optional[str] = Query(
        None, pattern="^(low|med|high|urgent)$",
    ),
    due_before: Optional[str] = None,   # ISO datetime
    due_after: Optional[str] = None,    # ISO datetime
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    filt: dict = {"tenant_id": tenant["id"]}
    if status:
        filt["status"] = status
    else:
        # Default — hide deleted rows from the list unless the
        # caller explicitly asks for them.
        filt["status"] = {"$ne": "deleted"}
    if priority:
        filt["priority"] = priority
    if due_before or due_after:
        due_range: dict = {}
        if due_before:
            due_range["$lte"] = due_before
        if due_after:
            due_range["$gte"] = due_after
        filt["due_at"] = due_range

    total = await db[MARCO_ADMIN_TODOS_COLLECTION].count_documents(filt)
    cursor = db[MARCO_ADMIN_TODOS_COLLECTION].find(
        filt, {"_id": 0},
    ).sort("due_at", 1).skip((page - 1) * page_size).limit(page_size)
    items = await cursor.to_list(page_size)
    return {"items": items, "total": total,
              "page": page, "page_size": page_size}


# ══════════════════════════════════════════════════════════════════
# GET /api/admin/todos/{id}
# ══════════════════════════════════════════════════════════════════
@router.get("/admin/todos/{todo_id}", response_model=AdminTodoOut)
async def get_admin_todo(
    todo_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    row = await db[MARCO_ADMIN_TODOS_COLLECTION].find_one(
        {"id": todo_id, "tenant_id": tenant["id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "todo_not_found")
    return row


# ══════════════════════════════════════════════════════════════════
# POST /api/admin/todos  — manual admin create
# ══════════════════════════════════════════════════════════════════
@router.post("/admin/todos", response_model=AdminTodoOut)
async def create_admin_todo_row(
    body: AdminTodoIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    now = _now_iso()
    doc = {
        "id": _new_id(),
        "tenant_id": tenant["id"],
        "title": body.title.strip(),
        "due_at": body.due_at,
        "priority": body.priority,
        "notes": body.notes,
        "status": "open",
        "created_by": user["id"],
        "created_via": "admin_manual",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "marco_pinged_at": None,
    }
    await db[MARCO_ADMIN_TODOS_COLLECTION].insert_one(dict(doc))
    return doc


# ══════════════════════════════════════════════════════════════════
# PATCH /api/admin/todos/{id}  — partial update + status transitions
# ══════════════════════════════════════════════════════════════════
@router.patch("/admin/todos/{todo_id}", response_model=AdminTodoOut)
async def patch_admin_todo(
    todo_id: str,
    body: AdminTodoPatch,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(422, "no_fields")
    updates["updated_at"] = _now_iso()
    # ``done`` transition auto-stamps completed_at.  Any other
    # status transition clears it.
    if updates.get("status") == "done":
        updates["completed_at"] = _now_iso()
    elif updates.get("status") in ("open", "snoozed", "deleted"):
        updates["completed_at"] = None

    res = await db[MARCO_ADMIN_TODOS_COLLECTION].find_one_and_update(
        {"id": todo_id, "tenant_id": tenant["id"]},
        {"$set": updates},
        return_document=True,
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(404, "todo_not_found")
    return res


# ══════════════════════════════════════════════════════════════════
# DELETE /api/admin/todos/{id}  — soft delete
#
# Chose SOFT delete (status='deleted') over hard delete so
# Sub-phase E's cron scans + audit trails retain the row.  A
# subsequent hard-delete migration can prune rows older than
# 90 days if operationally needed.
# ══════════════════════════════════════════════════════════════════
@router.delete("/admin/todos/{todo_id}")
async def delete_admin_todo(
    todo_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    res = await db[MARCO_ADMIN_TODOS_COLLECTION].update_one(
        {"id": todo_id, "tenant_id": tenant["id"],
          "status": {"$ne": "deleted"}},
        {"$set": {"status": "deleted",
                  "updated_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "todo_not_found")
    return {"ok": True, "id": todo_id, "status": "deleted"}
