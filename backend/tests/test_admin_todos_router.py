"""Feb-2026 · MARCO · Sub-phase D — admin_todos router + create_admin_todo
tool integration tests.

Covers:
  1. Router auth guard — technician 403.
  2. Tenant isolation — tenant A cannot see tenant B's todos.
  3. Priority filter + due_before filter.
  4. Soft-delete transitions status to "deleted".
  5. create_admin_todo tool end-to-end — MARCO's conversation
     context flows through, row lands in ``marco_admin_todos``
     with the right tenant_id + created_via + priority.
  6. create_admin_todo → created_via="marco_voice" when
     conversation_context.source_channel == "voice".
  7. create_admin_todo rejects due_at more than 5 min in the past.
  8. Tool loop wiring — dispatch_tool refuses when
     conversation_context is missing (bad_context guard).

Loop / DB hygiene
─────────────────
Router tests use ``httpx.AsyncClient(transport=ASGITransport(app))``
wrapped in an async ``go()`` closure and driven by
``asyncio.get_event_loop().run_until_complete`` — the codebase-
standard pattern for Motor-touching router tests (matches
``test_property_picker.py``, ``test_admin_unlinked_techs.py``).
Motor's futures are bound to the same loop the test drives, so no
cross-loop ``got Future attached to a different loop`` errors.

Tool tests use ``MagicMock`` for the DB (no real Motor traffic).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Router tests — AsyncClient over ASGITransport (see module docstr).
# ═══════════════════════════════════════════════════════════════════
@pytest.fixture()
def app_ctx():
    """Slim FastAPI app with just the admin_todos router + auth
    and tenant deps overridden.  Avoids booting the full CRM app."""
    from routers.admin_todos import router as todos_router
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    state = {
        "user": {"id": "user-1", "role": "admin"},
        "tenant": {"id": "tenant-A"},
    }

    app = FastAPI()
    app.include_router(todos_router)
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[get_current_tenant] = lambda: state["tenant"]

    return SimpleNamespace(app=app, state=state)


def _client(ctx):
    return AsyncClient(
        transport=ASGITransport(app=ctx.app),
        base_url="http://test",
    )


def _clean_marco_todos_sync():
    """Blocking cleanup — the router touches Motor async, but our
    fixtures accumulate in the shared DB across tests."""
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    db.marco_admin_todos.delete_many({
        "tenant_id": {"$in": ["tenant-A", "tenant-B"]},
    })


@pytest.fixture(autouse=True)
def _cleanup_todos():
    _clean_marco_todos_sync()
    yield
    _clean_marco_todos_sync()


# 1) Auth guard — technician forbidden.
def test_technician_forbidden_on_list(app_ctx):
    app_ctx.state["user"] = {"id": "tech-1", "role": "technician"}

    async def go():
        async with _client(app_ctx) as c:
            r = await c.get("/api/admin/todos")
            assert r.status_code == 403
            assert r.json()["detail"] == "admin_only"
    _run(go())


# 2) Tenant isolation — a todo in tenant B is invisible from
# tenant A's list.
def test_tenant_isolation_hides_other_tenant_rows(app_ctx):
    # Seed a row into tenant-B directly via blocking pymongo.
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    db.marco_admin_todos.insert_one({
        "id": "todo-b-1",
        "tenant_id": "tenant-B",
        "title": "Tenant B secret",
        "due_at": "2026-03-01T10:00:00Z",
        "priority": "med",
        "status": "open",
        "created_by": "user-b",
        "created_via": "admin_manual",
        "created_at": "2026-02-11T00:00:00Z",
        "updated_at": "2026-02-11T00:00:00Z",
        "completed_at": None,
        "marco_pinged_at": None,
    })

    async def go():
        async with _client(app_ctx) as c:
            r_create = await c.post("/api/admin/todos", json={
                "title": "Tenant A todo",
                "due_at": "2026-03-01T10:00:00Z",
                "priority": "high",
            })
            assert r_create.status_code == 200, r_create.text
            r_list = await c.get("/api/admin/todos")
            assert r_list.status_code == 200
            body = r_list.json()
            ids = [row["id"] for row in body["items"]]
            assert "todo-b-1" not in ids, (
                "tenant isolation regression — tenant A sees"
                " tenant B's row"
            )
            assert any(
                row["title"] == "Tenant A todo"
                for row in body["items"]
            )
    _run(go())


# 3) Priority filter + due_before filter.
def test_list_filters_by_priority_and_due_before(app_ctx):
    async def go():
        async with _client(app_ctx) as c:
            await c.post("/api/admin/todos", json={
                "title": "high one", "priority": "high",
                "due_at": "2026-02-15T10:00:00Z",
            })
            await c.post("/api/admin/todos", json={
                "title": "urgent one", "priority": "urgent",
                "due_at": "2026-02-13T10:00:00Z",
            })
            await c.post("/api/admin/todos", json={
                "title": "med far one", "priority": "med",
                "due_at": "2026-03-01T10:00:00Z",
            })

            r = await c.get("/api/admin/todos?priority=urgent")
            items = r.json()["items"]
            assert len(items) == 1
            assert items[0]["title"] == "urgent one"

            r = await c.get(
                "/api/admin/todos?due_before=2026-02-20T00:00:00Z",
            )
            items = r.json()["items"]
            titles = sorted(row["title"] for row in items)
            assert titles == ["high one", "urgent one"]
    _run(go())


# 4) Soft-delete transitions to status="deleted".
def test_delete_endpoint_soft_deletes(app_ctx):
    async def go():
        async with _client(app_ctx) as c:
            r = await c.post("/api/admin/todos", json={
                "title": "to be deleted", "priority": "low",
                "due_at": "2026-02-15T10:00:00Z",
            })
            todo_id = r.json()["id"]

            r_del = await c.delete(f"/api/admin/todos/{todo_id}")
            assert r_del.status_code == 200
            assert r_del.json() == {
                "ok": True, "id": todo_id, "status": "deleted",
            }

            r_list = await c.get("/api/admin/todos")
            assert all(
                row["id"] != todo_id
                for row in r_list.json()["items"]
            )

            r_del_list = await c.get(
                "/api/admin/todos?status=deleted",
            )
            assert any(
                row["id"] == todo_id
                for row in r_del_list.json()["items"]
            )
    _run(go())


# ═══════════════════════════════════════════════════════════════════
# create_admin_todo tool integration tests.
# ═══════════════════════════════════════════════════════════════════
class _InsertCapture:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
    async def __call__(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="mock")


# 5) End-to-end tool dispatch: MARCO calls create_admin_todo →
# row lands in marco_admin_todos with the right tenant_id +
# created_via.
def test_tool_dispatch_writes_row_with_tenant_and_created_via(
    monkeypatch,
):
    from services import ai_employee_tools as tools

    inserts = _InsertCapture()

    fake_db = MagicMock()
    fake_db.marco_admin_todos.insert_one = inserts

    import config as _cfg
    original = _cfg.db
    _cfg.db = fake_db
    try:
        monkeypatch.setattr(tools, "_audit",
                              AsyncMock(return_value=None))
        monkeypatch.setattr(tools, "_count_since",
                              AsyncMock(return_value=0))
        monkeypatch.setattr(tools, "_ensure_indexes",
                              AsyncMock(return_value=None))

        marco = {
            "id": "marco-1", "key": "marco_executive",
            "name": "MARCO", "orchestrator": True,
            "read_access_scope": "tenant_all",
        }
        outcome = _run(tools.dispatch_tool(
            tenant_id="tenant-A", persona=marco,
            caller_kind="admin", caller_id="user-1",
            tool_name="create_admin_todo",
            args={
                "title": "Call the Johnson family",
                "due_at": "2026-12-15T20:00:00Z",
                "priority": "high",
                "notes": "3pm EST, use their landline",
            },
            conversation_context={
                "conversation_id": "conv-1",
                "tenant_id": "tenant-A",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
                "source_channel": "chat",
            },
        ))
    finally:
        _cfg.db = original

    assert outcome.get("result", {}).get("ok") is True
    assert len(inserts.docs) == 1
    row = inserts.docs[0]
    assert row["tenant_id"] == "tenant-A"
    assert row["title"] == "Call the Johnson family"
    assert row["priority"] == "high"
    assert row["notes"] == "3pm EST, use their landline"
    assert row["created_by"] == "user-1"
    assert row["status"] == "open"
    assert row["created_via"] == "marco_chat"


# 6) source_channel="voice" → created_via="marco_voice".
def test_tool_source_channel_voice_flips_created_via(monkeypatch):
    from services import ai_employee_tools as tools
    inserts = _InsertCapture()
    fake_db = MagicMock()
    fake_db.marco_admin_todos.insert_one = inserts

    import config as _cfg
    original = _cfg.db
    _cfg.db = fake_db
    try:
        monkeypatch.setattr(tools, "_audit",
                              AsyncMock(return_value=None))
        monkeypatch.setattr(tools, "_count_since",
                              AsyncMock(return_value=0))
        monkeypatch.setattr(tools, "_ensure_indexes",
                              AsyncMock(return_value=None))

        marco = {
            "id": "marco-1", "key": "marco_executive",
            "orchestrator": True,
            "read_access_scope": "tenant_all",
        }
        outcome = _run(tools.dispatch_tool(
            tenant_id="tenant-A", persona=marco,
            caller_kind="admin", caller_id="user-1",
            tool_name="create_admin_todo",
            args={
                "title": "Voice-dictated task",
                "due_at": "2026-12-15T20:00:00Z",
                "priority": "med",
            },
            conversation_context={
                "conversation_id": "conv-1",
                "tenant_id": "tenant-A",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
                "source_channel": "voice",
            },
        ))
    finally:
        _cfg.db = original

    assert outcome.get("result", {}).get("ok") is True
    assert len(inserts.docs) == 1
    assert inserts.docs[0]["created_via"] == "marco_voice"


# 7) Past due_at rejected.
def test_tool_rejects_due_at_more_than_5min_in_past(monkeypatch):
    from services import ai_employee_tools as tools
    from datetime import datetime, timedelta, timezone

    inserts = _InsertCapture()
    fake_db = MagicMock()
    fake_db.marco_admin_todos.insert_one = inserts
    import config as _cfg
    original = _cfg.db
    _cfg.db = fake_db
    try:
        monkeypatch.setattr(tools, "_audit",
                              AsyncMock(return_value=None))
        monkeypatch.setattr(tools, "_count_since",
                              AsyncMock(return_value=0))
        monkeypatch.setattr(tools, "_ensure_indexes",
                              AsyncMock(return_value=None))

        past = (datetime.now(timezone.utc)
                - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

        marco = {
            "id": "marco-1", "key": "marco_executive",
            "orchestrator": True,
            "read_access_scope": "tenant_all",
        }
        outcome = _run(tools.dispatch_tool(
            tenant_id="tenant-A", persona=marco,
            caller_kind="admin", caller_id="user-1",
            tool_name="create_admin_todo",
            args={
                "title": "Past task",
                "due_at": past,
                "priority": "med",
            },
            conversation_context={
                "conversation_id": "conv-1",
                "tenant_id": "tenant-A",
                "invoker_persona": marco,
                "user": {"id": "user-1"},
            },
        ))
    finally:
        _cfg.db = original

    inner = outcome.get("result") or outcome
    assert (inner.get("error") == "due_at_in_past"), inner
    # Row was NOT written.
    assert inserts.docs == []


# 8) Missing conversation_context → bad_context refusal (guard
# from Sub-phase B dispatch_tool extension).
def test_tool_refuses_when_conversation_context_missing(monkeypatch):
    from services import ai_employee_tools as tools

    inserts = _InsertCapture()
    fake_db = MagicMock()
    fake_db.marco_admin_todos.insert_one = inserts
    import config as _cfg
    original = _cfg.db
    _cfg.db = fake_db
    try:
        monkeypatch.setattr(tools, "_audit",
                              AsyncMock(return_value=None))
        monkeypatch.setattr(tools, "_count_since",
                              AsyncMock(return_value=0))
        monkeypatch.setattr(tools, "_ensure_indexes",
                              AsyncMock(return_value=None))

        marco = {"id": "m-1", "key": "marco_executive",
                   "orchestrator": True,
                   "read_access_scope": "tenant_all"}
        outcome = _run(tools.dispatch_tool(
            tenant_id="tenant-A", persona=marco,
            caller_kind="admin", caller_id="user-1",
            tool_name="create_admin_todo",
            args={
                "title": "x", "due_at": "2026-12-15T20:00:00Z",
                "priority": "med",
            },
            # NO conversation_context.
        ))
    finally:
        _cfg.db = original

    assert outcome.get("error") == "bad_context"
    assert inserts.docs == []
