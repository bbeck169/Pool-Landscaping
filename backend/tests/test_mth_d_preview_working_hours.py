"""MTH-D · Feb-2026 — preview_kind=working_hours_status tests."""
from __future__ import annotations

from services.tenant_ai_rules.preview import preview_rules
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _base_rules():
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {},
        "working_hours": {"enabled": True, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_inside_window_returns_true(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = {
        "enabled": True,
        "timezone": "America/Los_Angeles",
        "windows": [{"day": "mon", "start": "08:00", "end": "17:00"}],
    }
    # 2026-02-02 = Monday.  10:15 PT = 18:15 UTC (PST, UTC-8).
    out = run(preview_rules(
        tenant_id="t1", category="working_hours",
        pending_value=pending,
        preview_kind="working_hours_status",
        preview_input={"probe_datetime": "2026-02-02T18:15:00+00:00"},
    ))
    assert out["output"]["inside_window"] is True
    assert out["output"]["current_window"]["day"] == "mon"
    assert "Inside window" in out["output"]["summary"]


def test_outside_window_computes_next_start(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = {
        "enabled": True,
        "timezone": "America/Los_Angeles",
        "windows": [
            {"day": "mon", "start": "08:00", "end": "17:00"},
            {"day": "tue", "start": "08:00", "end": "17:00"},
        ],
    }
    # 2026-02-02 04:00 UTC = 2026-02-01 20:00 PT (Sunday evening).
    out = run(preview_rules(
        tenant_id="t1", category="working_hours",
        pending_value=pending,
        preview_kind="working_hours_status",
        preview_input={"probe_datetime": "2026-02-02T04:00:00+00:00"},
    ))
    assert out["output"]["inside_window"] is False
    # Next window is Monday 08:00 PT.
    assert "Monday 08:00" in out["output"]["summary"]
    assert out["output"]["next_window_start"] is not None


def test_enabled_false_short_circuits_summary(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    pending = {"enabled": False, "timezone": "UTC", "windows": []}
    out = run(preview_rules(
        tenant_id="t1", category="working_hours",
        pending_value=pending,
        preview_kind="working_hours_status",
        preview_input={"probe_datetime": "2026-02-02T04:00:00+00:00"},
    ))
    assert out["output"]["inside_window"] is False
    assert out["output"]["enabled"] is False
    assert "restriction is OFF" in out["output"]["summary"]


def test_timezone_respected_ny_vs_la(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    # Monday 14:00 UTC = 06:00 PT (Mon) / 09:00 ET (Mon).
    probe = "2026-02-02T14:00:00+00:00"
    la = run(preview_rules(
        tenant_id="t1", category="working_hours",
        pending_value={
            "enabled": True, "timezone": "America/Los_Angeles",
            "windows": [{"day": "mon", "start": "08:00", "end": "17:00"}],
        },
        preview_kind="working_hours_status",
        preview_input={"probe_datetime": probe},
    ))
    ny = run(preview_rules(
        tenant_id="t1", category="working_hours",
        pending_value={
            "enabled": True, "timezone": "America/New_York",
            "windows": [{"day": "mon", "start": "08:00", "end": "17:00"}],
        },
        preview_kind="working_hours_status",
        preview_input={"probe_datetime": probe},
    ))
    assert la["output"]["inside_window"] is False  # 06:00 PT — pre-window
    assert ny["output"]["inside_window"] is True   # 09:00 ET — inside
    assert la["output"]["timezone_used"] == "America/Los_Angeles"
    assert ny["output"]["timezone_used"] == "America/New_York"


def test_invalid_probe_datetime_returns_422_shaped_error(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _base_rules())
    import pytest
    from services.tenant_ai_rules.preview import PreviewError
    with pytest.raises(PreviewError) as excinfo:
        run(preview_rules(
            tenant_id="t1", category="working_hours",
            pending_value={"enabled": True, "timezone": "UTC",
                             "windows": []},
            preview_kind="working_hours_status",
            preview_input={"probe_datetime": "not-a-date"},
        ))
    assert excinfo.value.http_status == 422
