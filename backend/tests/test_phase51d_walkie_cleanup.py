"""Phase 51d · Feb-2026 — Walkie 24h cleanup cron tests.

Exercises the ``services.walkie.cleanup_cron`` sweeps directly
against a live Mongo test-database (no HTTP hop). Isolation
strategy mirrors ``test_phase51c_walkie_push.py`` — a fresh event
loop per test with Motor's ``_io_loop`` swapped in and restored so
we don't fight the Phase 41.1d conftest rebind.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from services.walkie import cleanup_cron


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"  # aquaterra


@pytest.fixture
def sync_db():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        yield mc[be["DB_NAME"]]
    finally:
        mc.close()


def _run(coro):
    from config import client as _motor_client
    prev = getattr(_motor_client, "_io_loop", None)
    loop = asyncio.new_event_loop()
    _motor_client._io_loop = loop
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        _motor_client._io_loop = prev


def _seed(sync_db, live_msg_id: str, orphan_msg_id: str, live_file_id: str, orphan_file_id: str):
    """Insert one live + one orphan of each kind for the cron to
    chew on. Marks everything with a unique tag so we can assert
    only our fixtures got touched."""
    now = datetime.now(timezone.utc)
    tag = f"phase51d_test_{uuid.uuid4().hex[:8]}"
    # One live message (its receipt + file should survive).
    sync_db.walkie_messages.insert_one({
        "id": live_msg_id, "tenant_id": TID, "channel_id": "ch_test",
        "sender_user_id": "u_x", "audio_file_id": live_file_id,
        "duration_ms": 2000, "waveform_peaks": [], "created_at": now,
        "expires_at": now + timedelta(hours=24), "_phase51d_tag": tag,
    })
    # Two receipts — one for the live message, one for a dead id.
    sync_db.walkie_receipts.insert_many([
        {"id": uuid.uuid4().hex, "tenant_id": TID, "message_id": live_msg_id,
         "recipient_user_id": "u_r1", "listened_at": None, "_phase51d_tag": tag},
        {"id": uuid.uuid4().hex, "tenant_id": TID, "message_id": orphan_msg_id,
         "recipient_user_id": "u_r2", "listened_at": None, "_phase51d_tag": tag},
    ])
    # Two walkie_audio files — one referenced, one orphaned.
    sync_db.files.insert_many([
        {"id": live_file_id, "tenant_id": TID, "purpose": "walkie_audio",
         "path": "tenants/x/walkie/live.webm", "content_type": "audio/webm",
         "size": 10, "_phase51d_tag": tag},
        {"id": orphan_file_id, "tenant_id": TID, "purpose": "walkie_audio",
         "path": "tenants/x/walkie/orphan.webm", "content_type": "audio/webm",
         "size": 10, "_phase51d_tag": tag},
    ])
    # Sanity — insert a non-walkie file that must be UNTOUCHED even
    # if its id happens not to be referenced by walkie_messages.
    sync_db.files.insert_one({
        "id": f"unrelated_{uuid.uuid4().hex}",
        "tenant_id": TID, "purpose": "invoice_pdf",
        "path": "tenants/x/invoices/inv.pdf", "content_type": "application/pdf",
        "size": 10, "_phase51d_tag": tag,
    })
    return tag


def _cleanup(sync_db, tag: str):
    """Remove anything we inserted so the DB stays clean between runs."""
    sync_db.walkie_messages.delete_many({"_phase51d_tag": tag})
    sync_db.walkie_receipts.delete_many({"_phase51d_tag": tag})
    sync_db.files.delete_many({"_phase51d_tag": tag})


def test_cleanup_removes_orphan_receipts_and_files(sync_db):
    """The happy path — cron deletes exactly the orphan receipt and
    the orphan walkie_audio file, leaving the live rows intact and
    the unrelated invoice file untouched."""
    live_msg = f"m_live_{uuid.uuid4().hex}"
    orphan_msg = f"m_orphan_{uuid.uuid4().hex}"
    live_file = f"f_live_{uuid.uuid4().hex}"
    orphan_file = f"f_orphan_{uuid.uuid4().hex}"
    tag = _seed(sync_db, live_msg, orphan_msg, live_file, orphan_file)
    try:
        from config import db as motor_db
        result = _run(cleanup_cron.run_walkie_cleanup_once(motor_db))
        # The sweep runs against the WHOLE db, so the counts include
        # any pre-existing orphans across every tenant. What we care
        # about is that OUR orphans are gone and OUR live rows survived.
        assert result["receipts"] >= 1
        assert result["files"] >= 1
        # Orphan receipt gone, live receipt still there.
        remaining_receipts = list(sync_db.walkie_receipts.find({"_phase51d_tag": tag}))
        assert len(remaining_receipts) == 1
        assert remaining_receipts[0]["message_id"] == live_msg
        # Orphan file gone, live file still there.
        remaining_files = list(sync_db.files.find({"_phase51d_tag": tag}))
        remaining_ids = sorted(f["id"] for f in remaining_files)
        # Must still contain the live walkie file AND the unrelated invoice.
        assert live_file in remaining_ids
        assert not any(fid == orphan_file for fid in remaining_ids), "orphan walkie_audio file must be deleted"
        assert any(f.get("purpose") == "invoice_pdf" for f in remaining_files), "unrelated file must survive"
    finally:
        _cleanup(sync_db, tag)


def test_cleanup_is_noop_when_nothing_to_clean(sync_db):
    """Second run in a row must return 0 deletions for our test data
    (idempotency). We can't guarantee cross-tenant zeros because the
    live database may have other orphans — we scope by tag."""
    live_msg = f"m_live_{uuid.uuid4().hex}"
    orphan_msg = f"m_orphan_{uuid.uuid4().hex}"
    live_file = f"f_live_{uuid.uuid4().hex}"
    orphan_file = f"f_orphan_{uuid.uuid4().hex}"
    tag = _seed(sync_db, live_msg, orphan_msg, live_file, orphan_file)
    try:
        from config import db as motor_db
        _run(cleanup_cron.run_walkie_cleanup_once(motor_db))
        # Second pass should NOT touch any of our surviving rows.
        pre_receipts = sync_db.walkie_receipts.count_documents({"_phase51d_tag": tag})
        pre_files = sync_db.files.count_documents({"_phase51d_tag": tag})
        _run(cleanup_cron.run_walkie_cleanup_once(motor_db))
        post_receipts = sync_db.walkie_receipts.count_documents({"_phase51d_tag": tag})
        post_files = sync_db.files.count_documents({"_phase51d_tag": tag})
        assert pre_receipts == post_receipts, "receipts must not churn on a second pass"
        assert pre_files == post_files, "files must not churn on a second pass"
    finally:
        _cleanup(sync_db, tag)


def test_cleanup_never_touches_non_walkie_files(sync_db):
    """Insert an orphan file with a NON-walkie purpose and confirm
    the sweep leaves it alone even though no walkie_messages row
    references it. Locks the purpose filter in place."""
    tag = f"phase51d_purpose_{uuid.uuid4().hex[:8]}"
    unrelated_id = f"unrelated_{uuid.uuid4().hex}"
    sync_db.files.insert_one({
        "id": unrelated_id, "tenant_id": TID, "purpose": "before_after_photo",
        "path": "tenants/x/media/x.jpg", "content_type": "image/jpeg",
        "size": 10, "_phase51d_tag": tag,
    })
    try:
        from config import db as motor_db
        _run(cleanup_cron.run_walkie_cleanup_once(motor_db))
        row = sync_db.files.find_one({"id": unrelated_id})
        assert row is not None, "non-walkie files must survive the sweep"
    finally:
        _cleanup(sync_db, tag)


def test_cleanup_cron_registers_on_provided_scheduler(monkeypatch):
    """The registration helper adds a job called ``walkie.cleanup.tick``
    to whatever ``AsyncIOScheduler`` we hand it — mirroring the Phase 49
    pattern. Verifies no direct scheduler side effect / no new scheduler
    stood up."""
    calls: list[dict] = []

    class FakeScheduler:
        def add_job(self, fn, trigger=None, id=None, replace_existing=None):
            calls.append({"fn": fn, "id": id, "trigger": trigger, "replace_existing": replace_existing})

    cleanup_cron.register_walkie_cleanup_cron(FakeScheduler())
    assert len(calls) == 1
    assert calls[0]["id"] == "walkie.cleanup.tick"
    assert calls[0]["replace_existing"] is True
    # Coroutine function handed to the scheduler directly (same
    # pattern as the Lana reminder cron).
    assert asyncio.iscoroutinefunction(calls[0]["fn"])


def test_cleanup_disabled_by_env_flag(monkeypatch):
    """Setting ``WALKIE_CLEANUP_ENABLED=0`` short-circuits the tick
    (no DB access at all — returns ``skipped``)."""
    monkeypatch.setenv("WALKIE_CLEANUP_ENABLED", "0")
    res = _run(cleanup_cron._tick())
    assert res == {"skipped": True, "reason": "disabled"}


def test_cleanup_register_is_no_op_on_none_scheduler():
    """Defensive — passing ``None`` (e.g. from a startup path where
    the scheduler isn't ready) must not raise."""
    cleanup_cron.register_walkie_cleanup_cron(None)  # no error
