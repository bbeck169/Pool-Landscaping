"""Phase D · Feb-2026 — Drift alerts settings + test-fire RBAC.

Direct handler invocation via the F7 loop fixture.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from tests._f7_loop_fixture import run_test


async def _cleanup(db, tid):
    await asyncio.gather(
        db.drift_alert_settings.delete_many({"tenant_id": tid}),
        db.audit_events.delete_many(
            {"event_type": "data_integrity_digest", "tenant_id": tid},
        ),
        db.tenants.delete_many({"id": tid}),
    )


def test_drift_alerts_settings_get_put_round_trip():
    from routers.drift_alerts import (
        DriftAlertSettingsPatch, get_drift_alert_settings,
        put_drift_alert_settings,
    )

    async def _go(db):
        tid = "tenant-drift-rt-" + uuid.uuid4().hex[:6]
        await _cleanup(db, tid)
        user = {"id": "u", "role": "admin", "tenant_id": tid}
        try:
            r1 = await get_drift_alert_settings(user=user)
            assert r1["tenant_id"] == tid
            assert r1["enabled"] is True  # default
            assert r1["email_recipients"] == []
            assert r1["slack_webhook_url_masked"] == ""

            r2 = await put_drift_alert_settings(
                body=DriftAlertSettingsPatch(
                    enabled=True,
                    slack_webhook_url="https://hooks.slack.com/foo/bar",
                    email_recipients=["ops@example.com"],
                    timezone="America/Phoenix",
                ),
                user=user,
            )
            assert "slack_webhook_url" not in r2  # masked-only output
            assert r2["slack_webhook_url_masked"].startswith("…")
            assert "ops@example.com" in r2["email_recipients"]

            # Round-trip: GET again returns the persisted values.
            r3 = await get_drift_alert_settings(user=user)
            assert r3["email_recipients"] == ["ops@example.com"]
            assert r3["timezone"] == "America/Phoenix"
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_drift_alerts_rbac_tech_403_super_admin_can_fire():
    from fastapi import HTTPException
    from utils import require_admin, require_super_admin

    async def _go(_db):
        with pytest.raises(HTTPException) as ei:
            require_admin(user={"role": "technician"})
        assert ei.value.status_code == 403
        # admin passes require_admin
        assert require_admin(user={"role": "admin"})["role"] == "admin"
        # super_admin passes require_super_admin
        assert require_super_admin(
            user={"role": "super_admin"})["role"] == "super_admin"
        # admin FAILS super_admin
        with pytest.raises(HTTPException) as ei:
            require_super_admin(user={"role": "admin"})
        assert ei.value.status_code == 403

    async def _wrap(db):
        await _go(db)

    run_test(_wrap)
