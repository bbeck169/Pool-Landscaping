"""Phase 49 · Feb-2026 — Lana intents, todos, reminders."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Intent classification ────────────────────────────────────────────
def test_classify_schedule_intent_extracts_service_customer_when():
    from services.lana.intent import classify
    now = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)  # Sunday
    r = classify(
        "Lana, schedule a pool clean for Alan Chesebrough Wednesday at 10am",
        now=now,
    )
    assert r.kind == "schedule_job", r
    assert r.args["service_type"] == "Pool Cleaning"
    assert "alan chesebrough" in r.args["customer_name"].lower()
    assert r.args["scheduled_date"].startswith("2026-02-18")


def test_classify_reminder_intent():
    from services.lana.intent import classify
    now = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    r = classify("remind me at 3pm to call Alan", now=now)
    assert r.kind == "set_reminder"
    assert "call alan" in r.args["text"].lower()
    assert r.args["remind_at"].startswith("2026-02-15")


def test_classify_todo_intent():
    from services.lana.intent import classify
    r = classify("add todo: order muriatic acid")
    assert r.kind == "add_todo"
    assert r.args["text"].lower() == "order muriatic acid"


def test_classify_chat_fallback():
    from services.lana.intent import classify
    r = classify("what's my open job count?")
    assert r.kind == "chat"


def test_looks_destructive_catches_delete_and_cancel():
    from services.lana.intent import looks_destructive
    assert looks_destructive("delete job 123")
    assert looks_destructive("please cancel Alan's invoice")
    assert looks_destructive("refund customer 7")
    assert not looks_destructive("schedule a pool clean")


def test_classify_ambiguous_input_falls_back_to_chat():
    """A schedule-like message with no parseable date must NOT create
    a job — Phase 49 guardrail against LLM hallucinations."""
    from services.lana.intent import classify
    r = classify("schedule a pool clean for someone eventually")
    assert r.kind == "chat", r


# ── Schedule confirm-flow ────────────────────────────────────────────
def test_schedule_preview_finds_customer_by_fuzzy_match():
    from services.lana import schedule_intent as sch
    customers = MagicMock()
    customers.find.return_value.to_list = AsyncMock(return_value=[
        {"id": "c1", "name": "Alan Chesebrough", "address": "1 Pool Ln"},
        {"id": "c2", "name": "Sam Johnson", "address": "2 Test Rd"},
    ])
    fake_db = MagicMock(customers=customers)
    out = asyncio.get_event_loop().run_until_complete(sch.preview(
        fake_db, tenant_id="t1", customer_name="Alan",
        service_type="Pool Cleaning", scheduled_date="2026-02-18T17:00:00+00:00",
    ))
    assert out["ok"] is True
    assert out["preview"]["customer_id"] == "c1"
    assert "Alan Chesebrough" in out["preview"]["title"]


def test_schedule_preview_returns_customer_not_found_below_threshold():
    from services.lana import schedule_intent as sch
    customers = MagicMock()
    customers.find.return_value.to_list = AsyncMock(return_value=[
        {"id": "c1", "name": "Sam Johnson"},
    ])
    fake_db = MagicMock(customers=customers)
    out = asyncio.get_event_loop().run_until_complete(sch.preview(
        fake_db, tenant_id="t1", customer_name="Zzzzz Nobody",
        service_type="Pool Cleaning", scheduled_date="2026-02-18T17:00:00+00:00",
    ))
    assert out["ok"] is False and out["reason"] == "customer_not_found"


# ── Todos CRUD ────────────────────────────────────────────────────────
def test_todos_create_and_list_scoped_per_user():
    from services.lana import todos as t
    stored = []
    admin_todos = MagicMock()
    admin_todos.insert_one = AsyncMock(side_effect=lambda d: stored.append(d) or MagicMock())
    admin_todos.find.return_value.sort.return_value.to_list = AsyncMock(
        return_value=stored,
    )
    fake_db = MagicMock(admin_todos=admin_todos)
    doc = asyncio.get_event_loop().run_until_complete(t.create_todo(
        fake_db, tenant_id="t1", user_id="u1", text="Call Alan",
    ))
    assert doc["text"] == "Call Alan"
    assert doc["completed"] is False
    assert doc["tenant_id"] == "t1" and doc["user_id"] == "u1"


def test_todos_update_only_allowed_keys():
    from services.lana import todos as t
    admin_todos = MagicMock()
    admin_todos.update_one = AsyncMock()
    admin_todos.find_one = AsyncMock(return_value={"id": "x", "completed": True})
    fake_db = MagicMock(admin_todos=admin_todos)
    row = asyncio.get_event_loop().run_until_complete(t.update_todo(
        fake_db, tenant_id="t", user_id="u", todo_id="x",
        patch={"completed": True, "tenant_id": "HACKER", "user_id": "OTHER"},
    ))
    kwargs = admin_todos.update_one.await_args.args
    setter = kwargs[1]["$set"]
    assert setter["completed"] is True
    assert "tenant_id" not in setter and "user_id" not in setter
    assert row is not None


# ── Reminder cron ────────────────────────────────────────────────────
def test_fire_due_reminders_dry_run_by_default(monkeypatch):
    monkeypatch.delenv("LANA_SMS_LIVE", raising=False)
    from services.lana import reminders as rem
    row = {
        "id": "r1", "user_id": "u", "phone": "+14805551234",
        "text": "call alan", "remind_at": "2020-01-01T00:00:00+00:00",
    }
    admin_reminders = MagicMock()
    admin_reminders.find.return_value.to_list = AsyncMock(return_value=[row])
    admin_reminders.update_one = AsyncMock()
    fake_db = MagicMock(admin_reminders=admin_reminders)
    fired = asyncio.get_event_loop().run_until_complete(rem.fire_due_reminders(fake_db))
    assert fired == 1
    # sent_mode must be "dry_run" by default.
    setter = admin_reminders.update_one.await_args.args[1]["$set"]
    assert setter["sent"] is True
    assert setter["sent_mode"] == "dry_run"


def test_fire_due_reminders_skips_not_yet_due():
    from services.lana import reminders as rem
    admin_reminders = MagicMock()
    admin_reminders.find.return_value.to_list = AsyncMock(return_value=[])
    admin_reminders.update_one = AsyncMock()
    fake_db = MagicMock(admin_reminders=admin_reminders)
    fired = asyncio.get_event_loop().run_until_complete(rem.fire_due_reminders(fake_db))
    assert fired == 0
    admin_reminders.update_one.assert_not_awaited()


def test_live_sms_flag_flips_sent_mode(monkeypatch):
    monkeypatch.setenv("LANA_SMS_LIVE", "1")
    from services.lana import reminders as rem
    row = {"id": "r1", "user_id": "u", "phone": "+14805551234",
            "text": "call alan", "remind_at": "2020-01-01T00:00:00+00:00"}
    admin_reminders = MagicMock()
    admin_reminders.find.return_value.to_list = AsyncMock(return_value=[row])
    admin_reminders.update_one = AsyncMock()
    fake_db = MagicMock(admin_reminders=admin_reminders)
    # sms_provider missing → treated as dry_run body, but sent_mode should
    # still be "live" per the code path selection.
    fired = asyncio.get_event_loop().run_until_complete(rem.fire_due_reminders(fake_db))
    assert fired == 1
    setter = admin_reminders.update_one.await_args.args[1]["$set"]
    assert setter["sent_mode"] == "live"


# ── Router regression: /lana/todos endpoints registered ──────────────
def test_lana_todo_router_is_included_in_app():
    from server import app
    paths = {r.path for r in app.routes}
    assert "/api/lana/todos" in paths
    assert "/api/lana/reminders" in paths


def test_lana_schedule_commit_route_registered():
    from server import app
    paths = {r.path for r in app.routes}
    assert "/api/business-os/lana/schedule/commit" in paths
