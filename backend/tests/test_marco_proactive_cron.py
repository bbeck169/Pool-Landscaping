"""Feb-2026 · MARCO · Sub-phase E — proactive todo reminder tests.

Covers the 8 acceptance-criteria cases from the E brief:
    (a) 10-min-due todo → scanner fires, notification + SSE +
        marco_pinged_at all stamped.
    (b) Second run → no duplicate (idempotency).
    (c) 30-min-due todo → skipped (outside 15-min horizon).
    (d) Already-pinged todo → skipped.
    (e) status="done" todo → skipped.
    (f) Notification insert raises → marco_pinged_at NOT stamped,
        warning logged, next run retries.
    (g) Priority → severity mapping (urgent/high/med/low).
    (h) Timezone formatting — LA user sees LA-formatted time.

Testing style
─────────────
Real Motor DB for the todo scan (matches Sub-phase D router tests)
+ monkeypatched ``routers.realtime.bus`` to capture SSE broadcasts
+ real writes to ``db.notifications`` so we can assert bell rows.
Auto-fixture cleans ``marco_admin_todos``, ``notifications``,
``notification_preferences``, ``tenants``, ``users`` for the
tenants + users this file owns.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# Reference "now" — Wed 2026-02-11 15:00:00 UTC.
_FIXED_NOW = datetime(2026, 2, 11, 15, 0, tzinfo=timezone.utc)

# Owned tenant / user IDs — every row this file inserts carries
# one of these so the cleanup fixture can scope its delete.
_T_A = "mrc-e-A"
_T_B = "mrc-e-B"
_U_A = "mrc-e-user-A"
_U_B = "mrc-e-user-B"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


@pytest.fixture(autouse=True)
def _cleanup():
    """Clean owned rows before + after each test (blocking pymongo
    so we don't fight Motor's loop binding)."""
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    tenants_scope = {"$in": [_T_A, _T_B]}
    users_scope = {"$in": [_U_A, _U_B]}

    def _clean():
        db.marco_admin_todos.delete_many({"tenant_id": tenants_scope})
        db.notifications.delete_many({"tenant_id": tenants_scope})
        db.notification_preferences.delete_many({
            "tenant_id": tenants_scope,
        })
        db.tenants.delete_many({"id": tenants_scope})
        db.users.delete_many({"id": users_scope})

    _clean()
    # Seed one tenant + one user for tenant A on every test.
    # Individual tests can override / add tenant B as needed.
    db.tenants.insert_one({
        "id": _T_A, "name": "MRC-E Tenant A",
        "timezone": "America/New_York",
    })
    db.users.insert_one({
        "id": _U_A, "tenant_id": _T_A,
        "role": "admin",
        "email": "mrc-e-a@example.test",
    })
    yield
    _clean()


@pytest.fixture()
def sse_capture(monkeypatch):
    """Monkeypatch ``routers.realtime.bus.broadcast`` so tests can
    assert SSE payloads without wiring a real EventSource."""
    from routers import realtime

    captured: List[Dict[str, Any]] = []

    async def _fake_broadcast(user_id, message):
        captured.append({"user_id": user_id, "message": message})
        return 1
    monkeypatch.setattr(realtime.bus, "broadcast", _fake_broadcast)
    return captured


def _seed_todo(**overrides) -> Dict[str, Any]:
    """Build + insert a marco_admin_todos row via blocking pymongo.
    All fields default to a plausible 'open todo due in 10 min for
    tenant A / user A' shape."""
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    due_at = overrides.pop(
        "due_at", _iso(_FIXED_NOW + timedelta(minutes=10)),
    )
    doc = {
        "id": overrides.pop("id", f"todo-{len(overrides)}-e2e"),
        "tenant_id": overrides.pop("tenant_id", _T_A),
        "title": overrides.pop("title", "Call the Johnson family"),
        "due_at": due_at,
        "priority": overrides.pop("priority", "med"),
        "notes": overrides.pop("notes", None),
        "status": overrides.pop("status", "open"),
        "created_by": overrides.pop("created_by", _U_A),
        "created_via": overrides.pop("created_via", "marco_voice"),
        "created_at": _iso(_FIXED_NOW - timedelta(minutes=30)),
        "updated_at": _iso(_FIXED_NOW - timedelta(minutes=30)),
        "completed_at": None,
        "marco_pinged_at": overrides.pop("marco_pinged_at", None),
    }
    doc.update(overrides)
    db.marco_admin_todos.insert_one(dict(doc))
    return doc


def _read_todo(todo_id: str) -> Dict[str, Any]:
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    return db.marco_admin_todos.find_one({"id": todo_id}) or {}


def _read_notifications(tenant_id: str) -> List[Dict[str, Any]]:
    import os
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    return list(db.notifications.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ))


# ═══════════════════════════════════════════════════════════════════
# (a) 10-min-due todo — scanner fires everything.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_fires_notification_sse_and_stamps_marco_pinged_at(
    sse_capture,
):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    todo = _seed_todo(
        id="todo-fire-1",
        due_at=_iso(_FIXED_NOW + timedelta(minutes=10)),
        priority="high",
    )

    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 1

    # (i) notification row.
    notifs = _read_notifications(_T_A)
    assert len(notifs) == 1
    n = notifs[0]
    assert n["kind"] == "marco_todo_due"
    assert n["title"] == "MARCO Reminder"
    assert "Call the Johnson family" in n["body"]
    assert n["href"] == "/admin/todos/todo-fire-1"
    assert n["user_id"] == _U_A
    assert n["tenant_id"] == _T_A
    # High-priority todo → severity "warning".
    assert n["priority"] == "warning"
    assert n["source_ref"]["kind"] == "admin_todo"
    assert n["source_ref"]["id"] == "todo-fire-1"

    # (ii) SSE broadcast.
    assert len(sse_capture) == 1
    sse = sse_capture[0]
    assert sse["user_id"] == _U_A
    assert sse["message"]["type"] == "notification"
    assert sse["message"]["payload"]["kind"] == "marco_todo_due"

    # (iii) marco_pinged_at stamped.
    row = _read_todo("todo-fire-1")
    assert row["marco_pinged_at"] is not None


# ═══════════════════════════════════════════════════════════════════
# (b) Idempotency — second run doesn't duplicate.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_second_run_does_not_duplicate(sse_capture):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    _seed_todo(id="todo-idem", due_at=_iso(
        _FIXED_NOW + timedelta(minutes=10),
    ))

    fired_1 = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    fired_2 = _run(fire_due_admin_todos(
        db, now=_FIXED_NOW + timedelta(minutes=1),
    ))

    assert fired_1 == 1
    assert fired_2 == 0
    assert len(_read_notifications(_T_A)) == 1
    assert len(sse_capture) == 1


# ═══════════════════════════════════════════════════════════════════
# (c) 30-min-due todo — outside the 15-min horizon → skipped.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_skips_todo_outside_horizon(sse_capture):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    _seed_todo(id="todo-far", due_at=_iso(
        _FIXED_NOW + timedelta(minutes=30),
    ))

    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 0
    assert _read_notifications(_T_A) == []
    assert sse_capture == []
    assert _read_todo("todo-far")["marco_pinged_at"] is None


# ═══════════════════════════════════════════════════════════════════
# (d) Already-stamped todo → skipped.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_skips_already_stamped_todo(sse_capture):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    _seed_todo(
        id="todo-stamped",
        due_at=_iso(_FIXED_NOW + timedelta(minutes=5)),
        marco_pinged_at=_iso(_FIXED_NOW - timedelta(minutes=1)),
    )

    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 0
    assert _read_notifications(_T_A) == []
    assert sse_capture == []


# ═══════════════════════════════════════════════════════════════════
# (e) status="done" todo → skipped.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_skips_done_todo(sse_capture):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    _seed_todo(
        id="todo-done",
        due_at=_iso(_FIXED_NOW + timedelta(minutes=5)),
        status="done",
    )
    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 0
    assert _read_notifications(_T_A) == []
    assert sse_capture == []
    # Still not stamped — done is a terminal state, not a ping state.
    assert _read_todo("todo-done")["marco_pinged_at"] is None


# ═══════════════════════════════════════════════════════════════════
# (f) Failure injection — emit raises → marco_pinged_at NOT stamped
#     + warning logged + next run retries.
# ═══════════════════════════════════════════════════════════════════
def test_scanner_does_not_stamp_when_emit_fails(monkeypatch, caplog):
    from config import db
    from services import marco_reminder_cron

    _seed_todo(id="todo-fail", due_at=_iso(
        _FIXED_NOW + timedelta(minutes=10),
    ))

    async def _boom(*_a, **_k):
        raise RuntimeError("simulated bell insert crash")
    monkeypatch.setattr(
        marco_reminder_cron, "_emit_marco_reminder", _boom,
    )

    with caplog.at_level(logging.WARNING,
                            logger="marco.reminders.cron"):
        fired_1 = _run(marco_reminder_cron.fire_due_admin_todos(
            db, now=_FIXED_NOW,
        ))

    assert fired_1 == 0
    assert _read_todo("todo-fail")["marco_pinged_at"] is None
    # Warning was logged with todo id.
    assert any(
        "todo-fail" in r.message
        for r in caplog.records
        if r.levelname == "WARNING"
    ), caplog.text

    # Restore + confirm next run retries + succeeds.
    monkeypatch.undo()
    fired_2 = _run(marco_reminder_cron.fire_due_admin_todos(
        db, now=_FIXED_NOW + timedelta(minutes=1),
    ))
    assert fired_2 == 1
    assert _read_todo("todo-fail")["marco_pinged_at"] is not None
    assert len(_read_notifications(_T_A)) == 1


# ═══════════════════════════════════════════════════════════════════
# (g) Priority → severity mapping.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("priority,severity", [
    ("urgent", "urgent"),
    ("high", "warning"),
    ("med", "info"),
    ("low", "info"),
])
def test_priority_maps_to_severity(sse_capture, priority, severity):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    todo_id = f"todo-prio-{priority}"
    _seed_todo(
        id=todo_id,
        due_at=_iso(_FIXED_NOW + timedelta(minutes=5)),
        priority=priority,
    )

    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 1

    notifs = _read_notifications(_T_A)
    assert len(notifs) == 1
    n = notifs[0]
    assert n["priority"] == severity, (
        f"priority={priority} should map to severity={severity}"
        f", got notification priority={n['priority']!r}"
    )
    assert n["source_ref"]["severity"] == severity
    assert n["source_ref"]["priority"] == priority


# ═══════════════════════════════════════════════════════════════════
# (h) Timezone formatting — LA user sees LA time.
# ═══════════════════════════════════════════════════════════════════
def test_notification_body_formats_due_at_in_tenant_timezone(
    sse_capture,
):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    # Rebrand the seeded tenant to America/Los_Angeles.
    import os
    from pymongo import MongoClient
    _client = MongoClient(os.environ["MONGO_URL"])
    _client[os.environ["DB_NAME"]].tenants.update_one(
        {"id": _T_A},
        {"$set": {"timezone": "America/Los_Angeles"}},
    )

    # Due at 2026-02-11 22:00 UTC = 2:00 PM PST.
    due_utc = datetime(2026, 2, 11, 22, 0, tzinfo=timezone.utc)
    _seed_todo(id="todo-la", due_at=_iso(due_utc))

    # "Now" 10 min before due so it's inside the horizon.
    now = due_utc - timedelta(minutes=10)
    fired = _run(fire_due_admin_todos(db, now=now))
    assert fired == 1

    notifs = _read_notifications(_T_A)
    assert len(notifs) == 1
    body = notifs[0]["body"]
    # Should contain LA-local hour (2 PM), NOT UTC hour (10 PM).
    assert "2:00 PM" in body, (
        f"body should carry LA-local time, got: {body!r}"
    )
    # Timezone abbreviation should be PST (or PDT in daylight
    # months — Feb is PST).
    assert "PST" in body, (
        f"body should carry PST tz abbrev, got: {body!r}"
    )


# ═══════════════════════════════════════════════════════════════════
# Bonus — tenant isolation.  A tenant A run should NOT pick up a
# tenant B row and vice-versa (the scanner is tenant-agnostic by
# design; isolation is enforced by user_id routing + tenant_id on
# the notification row).
# ═══════════════════════════════════════════════════════════════════
def test_scanner_writes_notifications_scoped_to_todo_tenant(
    sse_capture,
):
    from config import db
    from services.marco_reminder_cron import fire_due_admin_todos

    # Seed tenant B + a due todo.
    import os
    from pymongo import MongoClient
    _client = MongoClient(os.environ["MONGO_URL"])
    _db = _client[os.environ["DB_NAME"]]
    _db.tenants.insert_one({
        "id": _T_B, "name": "MRC-E Tenant B",
        "timezone": "America/New_York",
    })
    _db.users.insert_one({
        "id": _U_B, "tenant_id": _T_B, "role": "admin",
        "email": "mrc-e-b@example.test",
    })

    _seed_todo(
        id="todo-a", due_at=_iso(_FIXED_NOW + timedelta(minutes=5)),
    )
    _seed_todo(
        id="todo-b", tenant_id=_T_B, created_by=_U_B,
        due_at=_iso(_FIXED_NOW + timedelta(minutes=5)),
    )

    fired = _run(fire_due_admin_todos(db, now=_FIXED_NOW))
    assert fired == 2

    notifs_a = _read_notifications(_T_A)
    notifs_b = _read_notifications(_T_B)
    assert len(notifs_a) == 1
    assert len(notifs_b) == 1
    assert notifs_a[0]["user_id"] == _U_A
    assert notifs_b[0]["user_id"] == _U_B
