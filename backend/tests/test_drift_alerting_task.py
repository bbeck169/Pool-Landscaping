"""Phase D · Feb-2026 — Drift alerting task tests.

Covers:
  1. clean branch (dangling_refs_total=0) → dispatched=False, reason='clean',
     audit row present, no wire calls.
  2. dirty branch → both channels called, audit row records channels.
  3. same-day dedupe → 2nd force=False call is a no-op with reason
     'already_dispatched_today'.
"""
from __future__ import annotations

import asyncio
import uuid

from tests._f7_loop_fixture import run_test


async def _reset(db, tid):
    await asyncio.gather(
        db.drift_alert_settings.delete_many({"tenant_id": tid}),
        db.audit_events.delete_many(
            {"event_type": "data_integrity_digest", "tenant_id": tid},
        ),
        db.tenants.delete_many({"id": tid}),
    )


def test_drift_alerting_clean_branch_writes_heartbeat_audit():
    from services.drift_alerting import (
        AUDIT_EVENT_TYPE, dispatch_for_tenant,
    )

    async def _go(db):
        tid = "tenant-driftD-" + uuid.uuid4().hex[:6]
        await _reset(db, tid)
        await db.tenants.insert_one(
            {"id": tid, "name": "Test Co", "slug": "test-co"},
        )
        await db.drift_alert_settings.insert_one({
            "tenant_id": tid, "enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/x",
            "email_recipients": ["ops@example.com"],
            "timezone": "America/Phoenix",
        })
        slack_calls, email_calls = [], []
        async def _slack(url, payload):
            slack_calls.append((url, payload)); return {"ok": True, "status": 200}
        async def _email(to, s, h, t):
            email_calls.append(to); return {"ok": True, "status": 200}
        try:
            tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
            # Stub the F3 status to a clean 0-orphan payload so the
            # test is deterministic regardless of preview DB state.
            import routers.data_repair as _dr
            _orig = _dr.data_repair_status
            async def _stub_status(user=None, **kw):
                return {"current_state": {
                    "dangling_refs_total": 0,
                    "dangling_refs_by_class": {"customer": 0,
                                                 "technician": 0,
                                                 "crew": 0},
                    "log_only_mode_active": False,
                    "enforce_mode": True,
                }}
            _dr.data_repair_status = _stub_status
            try:
                res = await dispatch_for_tenant(
                    {"id": tid, **tenant}, force=True,
                    slack_post=_slack, resend_send=_email,
                )
            finally:
                _dr.data_repair_status = _orig
            assert res["dispatched"] is False
            assert res["reason"] == "clean"
            assert res["dangling_refs_total"] == 0
            assert slack_calls == []
            assert email_calls == []
            row = await db.audit_events.find_one(
                {"id": res["audit_event_id"]}, {"_id": 0},
            )
            assert row is not None
            assert row["event_type"] == AUDIT_EVENT_TYPE
            assert row["payload"]["reason"] == "clean"
            assert row["payload"]["dispatched"] is False
        finally:
            await _reset(db, tid)

    run_test(_go)


def test_drift_alerting_dedupes_within_same_local_date():
    from services.drift_alerting import dispatch_for_tenant

    async def _go(db):
        tid = "tenant-driftD-" + uuid.uuid4().hex[:6]
        await _reset(db, tid)
        await db.tenants.insert_one({"id": tid, "name": "Test Co"})
        await db.drift_alert_settings.insert_one({
            "tenant_id": tid, "enabled": True,
            "email_recipients": ["ops@example.com"],
            "timezone": "America/Phoenix",
        })
        # Manually seed a "dispatched today" audit row so the 2nd
        # call (force=False) hits the dedupe branch. We do NOT need
        # a real orphan for this test — the dedupe check runs before
        # F3.
        from datetime import datetime, timezone
        try:
            from zoneinfo import ZoneInfo
            date_str = datetime.now(timezone.utc).astimezone(
                ZoneInfo("America/Phoenix")).strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await db.audit_events.insert_one({
            "id": str(uuid.uuid4()),
            "event_type": "data_integrity_digest",
            "tenant_id": tid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "date": date_str, "dispatched": True,
                "dangling_refs_total": 3,
                "reason": "sent",
                "channels_notified": ["email"],
                "top_collections": [],
            },
        })
        try:
            tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
            res = await dispatch_for_tenant(
                {"id": tid, **tenant}, force=False,
            )
            assert res["skipped"] is True
            assert res["reason"] == "already_dispatched_today"
        finally:
            await _reset(db, tid)

    run_test(_go)


def test_drift_alerting_disabled_short_circuits():
    from services.drift_alerting import dispatch_for_tenant

    async def _go(db):
        tid = "tenant-driftD-" + uuid.uuid4().hex[:6]
        await _reset(db, tid)
        await db.tenants.insert_one({"id": tid, "name": "Test Co"})
        await db.drift_alert_settings.insert_one({
            "tenant_id": tid, "enabled": False,
        })
        try:
            tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
            res = await dispatch_for_tenant(
                {"id": tid, **tenant}, force=True,
            )
            assert res["skipped"] is True
            assert res["reason"] == "disabled"
        finally:
            await _reset(db, tid)

    run_test(_go)


def test_drift_alerting_dirty_branch_calls_both_channels():
    from services.drift_alerting import dispatch_for_tenant

    async def _go(db):
        tid = "tenant-driftD-" + uuid.uuid4().hex[:6]
        await _reset(db, tid)
        await db.tenants.insert_one({"id": tid, "name": "Test Co"})
        await db.drift_alert_settings.insert_one({
            "tenant_id": tid, "enabled": True,
            "slack_webhook_url": "https://hooks.slack.com/x",
            "email_recipients": ["ops@example.com"],
            "timezone": "America/Phoenix",
        })
        slack_calls, email_calls = [], []
        async def _slack(url, payload):
            slack_calls.append((url, payload))
            return {"ok": True, "status": 200}
        async def _email(to, s, h, t):
            email_calls.append((to, s))
            return {"ok": True, "status": 200}

        # Stub F3 status to a NON-zero payload — proves both channels
        # dispatch when drift is detected.
        import routers.data_repair as _dr
        _orig = _dr.data_repair_status
        async def _stub_status(user=None, **kw):
            return {"current_state": {
                "dangling_refs_total": 7,
                "dangling_refs_by_class": {"customer": 5,
                                             "technician": 2,
                                             "crew": 0},
                "log_only_mode_active": False,
                "enforce_mode": True,
            }}
        _dr.data_repair_status = _stub_status
        try:
            tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
            res = await dispatch_for_tenant(
                {"id": tid, **tenant}, force=True,
                slack_post=_slack, resend_send=_email,
            )
            assert res["dispatched"] is True
            assert res["dangling_refs_total"] == 7
            assert set(res["channels_notified"]) == {"slack", "email"}
            assert len(slack_calls) == 1
            assert len(email_calls) == 1
            # Email subject carries the total.
            assert "7 dangling refs" in email_calls[0][1]
            # Top offenders present.
            top_classes = {r["class"] for r in res["top"]}
            assert "customer" in top_classes
            assert "technician" in top_classes
        finally:
            _dr.data_repair_status = _orig
            await _reset(db, tid)

    run_test(_go)
