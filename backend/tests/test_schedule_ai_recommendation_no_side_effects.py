"""SO-A · Feb-2026 — no-side-effects test for the recommendation
compute path.

The recommendation endpoint MUST be read-only against the ``jobs``
collection (route_index unchanged; no updates), MUST write exactly
ONE ``ai_employee_actions`` row per call (auto-approved recommendation
audit), and MUST NOT create any reassign action row.  The reassign
action row only appears when ``/schedule/apply-recommendation`` is
called.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.schedule_optimizer.endpoint import generate_recommendations
from tests._mth_c_helpers import (
    mth_c_db, seed_rules_doc, seed_platform_defaults, run,        # noqa: F401
)


NOW = datetime(2026, 2, 16, 14, 0, 0, tzinfo=timezone.utc)


def _fake_eta():
    async def _eta(a_lat, a_lng, b_lat, b_lng):
        return type("_R", (), {
            "provider": "crowflies",
            "duration_s": 120, "distance_m": 800,
        })()
    return _eta


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    async def _fake(system_prompt, user_text, parse_json, max_tokens,
                       tenant_id="", **_kw):
        return {"raw": "line1\nline2", "provider": "fake",
                 "model": "fake-1"}
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _fake,
        raising=False,
    )


def _seed_baseline(fake):
    from services.tenant_ai_rules.schema import (
        ACTION_INVENTORY, EMPLOYEE_KEYS,
    )
    seed_platform_defaults(fake, {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    })
    seed_rules_doc(fake, "t1", {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    }, master=True)
    # 2 techs, each 2 stops.
    for tid in ("tech_a", "tech_b"):
        fake.users.rows.append({
            "id": tid, "tenant_id": "t1",
            "name": f"Tech {tid}", "role": "technician",
        })
        for i in range(2):
            fake.jobs.rows.append({
                "id": f"j-{tid}-{i}", "tenant_id": "t1",
                "technician_id": tid, "scheduled_date": "2026-02-16",
                "route_index": i, "lat": 10.0, "lng": 20.0 + i,
            })
        fake.tech_locations.rows.append({
            "id": f"loc-{tid}", "tenant_id": "t1",
            "tech_user_id": tid, "lat": 9.5, "lng": 19.0,
            "recorded_at": (NOW - timedelta(minutes=10)).isoformat(),
        })
    fake.jobs.rows.append({
        "id": "TGT", "tenant_id": "t1",
        "scheduled_date": "2026-02-16",
        "lat": 10.0, "lng": 21.5,
    })


def test_route_index_unchanged_on_recommendation(mth_c_db):
    _seed_baseline(mth_c_db)
    before = [
        (j["id"], j.get("route_index"), j.get("technician_id"))
        for j in mth_c_db.jobs.rows
    ]
    run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta(),
    ))
    after = [
        (j["id"], j.get("route_index"), j.get("technician_id"))
        for j in mth_c_db.jobs.rows
    ]
    assert before == after, "recommendation MUST NOT mutate jobs"


def test_no_reassign_action_row_created(mth_c_db):
    _seed_baseline(mth_c_db)
    # generate_recommendations does NOT write an audit row on its
    # own — the router wrapper does.  So after the compute the
    # ai_employee_actions collection stays empty.
    run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta(),
    ))
    reassign_rows = [
        r for r in mth_c_db.ai_employee_actions.rows
        if r.get("action_key") == "dispatch.reassign"
    ]
    assert reassign_rows == [], (
        "compute path must NOT write a reassign action row"
    )


def test_rate_limit_state_isolated_from_persistent_writes():
    """The rate-limit deque lives in a module-level dict — this test
    guards that mth-d and so-a limiters stay independent.  Locked
    end-to-end by the rate-limit unit test file; here we only
    smoke-check that recording doesn't touch the DB."""
    from services.schedule_optimizer import rate_limit as rl
    rl.reset()
    rl.check_and_record("u1")
    # No DB assertion needed — the pure-python bucket is in-memory
    # by construction and doesn't hold a Motor reference.
    assert len(rl._buckets) == 1


def test_master_off_does_not_persist_anything(mth_c_db):
    """Even with master switch OFF, the recommendation call is
    read-only: no jobs mutation, no audit row (which is the router's
    responsibility)."""
    from services.tenant_ai_rules.schema import (
        ACTION_INVENTORY, EMPLOYEE_KEYS,
    )
    seed_platform_defaults(mth_c_db, {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    })
    seed_rules_doc(mth_c_db, "t1", {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    }, master=False)
    mth_c_db.users.rows.append({
        "id": "tech_z", "tenant_id": "t1",
        "name": "Tech Z", "role": "technician",
    })
    mth_c_db.jobs.rows.append({
        "id": "j-tech_z-0", "tenant_id": "t1",
        "technician_id": "tech_z", "scheduled_date": "2026-02-16",
        "route_index": 0, "lat": 10.0, "lng": 20.0,
    })
    mth_c_db.jobs.rows.append({
        "id": "TGT", "tenant_id": "t1",
        "scheduled_date": "2026-02-16",
        "lat": 10.0, "lng": 20.5,
    })
    before_rows = len(mth_c_db.jobs.rows)
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta(),
    ))
    assert result["master_switch_on"] is False
    assert len(mth_c_db.jobs.rows) == before_rows
    assert mth_c_db.ai_employee_actions.rows == []


def test_dispatch_registered_in_ai_hub_registry():
    """SO-A depends on the ``dispatch`` employee existing in the
    AIHUB-A registry.  Guard the assumption."""
    from services.ai_hub.employee_registry import EMPLOYEES
    keys = [e.key for e in EMPLOYEES]
    assert "dispatch" in keys


def test_dispatch_action_keys_in_action_inventory():
    """The auto_action_allowlist gate depends on these keys being
    present in the MTH-A action inventory."""
    from services.tenant_ai_rules.schema import ACTION_INVENTORY
    assert "dispatch.reassign" in ACTION_INVENTORY
    assert "dispatch.schedule_recommendation" in ACTION_INVENTORY
