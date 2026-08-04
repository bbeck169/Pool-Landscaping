"""Phase 49 · Feb-2026 — Lana admin todos service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def list_todos(db, *, tenant_id: str, user_id: str,
                      include_completed: bool = False) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id, "user_id": user_id}
    if not include_completed:
        q["completed"] = False
    rows = await db.admin_todos.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows


async def create_todo(db, *, tenant_id: str, user_id: str, text: str,
                       due_at: Optional[str] = None) -> Dict[str, Any]:
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "text": text.strip(),
        "due_at": due_at,
        "completed": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.admin_todos.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def update_todo(db, *, tenant_id: str, user_id: str, todo_id: str,
                       patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {k: v for k, v in patch.items() if k in {"text", "due_at", "completed"}}
    if not allowed:
        return None
    allowed["updated_at"] = _now()
    await db.admin_todos.update_one(
        {"id": todo_id, "tenant_id": tenant_id, "user_id": user_id},
        {"$set": allowed},
    )
    return await db.admin_todos.find_one(
        {"id": todo_id, "tenant_id": tenant_id, "user_id": user_id}, {"_id": 0},
    )


async def delete_todo(db, *, tenant_id: str, user_id: str, todo_id: str) -> bool:
    r = await db.admin_todos.delete_one(
        {"id": todo_id, "tenant_id": tenant_id, "user_id": user_id},
    )
    return bool(r.deleted_count)
