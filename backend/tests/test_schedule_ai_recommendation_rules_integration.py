"""SO-A · Feb-2026 — Rules integration tests.

Locks:
  * Dispatch employee disabled → suggestions still return, but
    ``plain_english_source`` is a template fallback.
  * Allowlist ``dispatch.reassign=auto`` → ``apply_mode=one_click``.
  * Allowlist ``dispatch.reassign=admin_approval`` → queued.
  * Working-hours OFF → tech excluded.
  * Master switch OFF → ``plain_english_source =
    template_fallback_master_off``.
  * Tone_voice ``formal`` vs ``friendly`` produces DIFFERENT prompt
    shape (verified via monkeypatched LLM adapter).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

from services.schedule_optimizer.endpoint import generate_recommendations
from services.schedule_optimizer import persona as _persona_mod

from tests._mth_c_helpers import (
    mth_c_db, seed_rules_doc, seed_platform_defaults, run,        # noqa: F401
)


NOW = datetime(2026, 2, 16, 14, 0, 0, tzinfo=timezone.utc)   # Mon 14:00Z


def _fake_eta_stub():
    async def _eta(a_lat, a_lng, b_lat, b_lng):
        d = abs(a_lat - b_lat) + abs(a_lng - b_lng)
        return type("_R", (), {
            "provider": "crowflies",
            "duration_s": int(d * 60), "distance_m": int(d * 20),
        })()
    return _eta


def _seed_default_platform(fake):
    """Seed platform defaults with dispatch employee enabled + all
    allowlist entries at admin_approval (safety-first)."""
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


def _seed_tenant(fake, tenant_id: str, **overrides):
    from services.tenant_ai_rules.schema import (
        ACTION_INVENTORY, EMPLOYEE_KEYS,
    )
    base = {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    }
    for k, v in overrides.items():
        base[k] = v
    seed_rules_doc(fake, tenant_id, base, master=True)


def _seed_tech_and_jobs(fake, tenant_id: str, tech_id: str,
                          n_stops: int = 2) -> None:
    fake.users.rows.append({
        "id": tech_id, "tenant_id": tenant_id,
        "name": f"Tech {tech_id}", "role": "technician",
    })
    for i in range(n_stops):
        fake.jobs.rows.append({
            "id": f"j-{tech_id}-{i}",
            "tenant_id": tenant_id,
            "technician_id": tech_id,
            "scheduled_date": "2026-02-16",
            "route_index": i,
            "lat": 10.0, "lng": 20.0 + i,
        })
    # Fresh GPS ping.
    fake.tech_locations.rows.append({
        "id": f"loc-{tech_id}",
        "tenant_id": tenant_id, "tech_user_id": tech_id,
        "lat": 9.5, "lng": 19.0,
        "recorded_at": (NOW - timedelta(minutes=15)).isoformat(),
    })


def _seed_target_job(fake, tenant_id: str, job_id: str = "TGT") -> None:
    fake.jobs.rows.append({
        "id": job_id, "tenant_id": tenant_id,
        "scheduled_date": "2026-02-16",
        "lat": 10.0, "lng": 21.5,
    })


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    """Monkey-patch the LLM caller to a deterministic echo so the
    tests aren't network-bound.  We RECORD calls so tone-shape tests
    can assert on the system prompt."""
    recorded: List[Dict[str, Any]] = []

    async def _fake(system_prompt: str, user_text: str,
                       parse_json: bool, max_tokens: int,
                       tenant_id: str = "", **_kw):
        recorded.append({
            "system_prompt": system_prompt,
            "user_text": user_text,
            "tenant_id": tenant_id,
        })
        # Return one line per tech in user_text.
        lines = [ln for ln in user_text.splitlines() if ln.strip()]
        return {
            "raw": "\n".join(
                f"{ln.split('Tech: ')[-1].split(' ·')[0]}: LLM-line #{i}"
                for i, ln in enumerate(lines)
            ),
            "provider": "fake", "model": "fake-1",
        }
    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback", _fake,
        raising=False,
    )
    yield recorded


def test_dispatch_disabled_falls_back_to_template(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    _seed_tenant(mth_c_db, "t1", employee_enable_disable={"dispatch": False})
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    assert result["plain_english_source"] == "template_fallback_disabled"
    assert result["dispatch_employee_enabled"] is False
    # Suggestions still present.
    assert len(result["suggestions"]) == 1
    # Deterministic template shape.
    assert "adds " in result["suggestions"][0]["plain_english"]
    # LLM stub was NOT invoked.
    assert _stub_llm == []


def test_allowlist_auto_produces_one_click(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    _seed_tenant(mth_c_db, "t1", auto_action_allowlist={
        "dispatch.reassign": "auto",
    })
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    assert result["apply_mode"] == "one_click"


def test_allowlist_admin_approval_produces_queued(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    _seed_tenant(mth_c_db, "t1", auto_action_allowlist={
        "dispatch.reassign": "admin_approval",
    })
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    assert result["apply_mode"] == "queued_for_approval"


def test_working_hours_excludes_tech_outside_window(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    # Mon 14:00Z UTC — outside a "Mon 09-10 UTC" window.
    _seed_tenant(mth_c_db, "t1", working_hours={
        "enabled": True, "timezone": "UTC",
        "windows": [{"day": "mon", "start": "09:00", "end": "10:00"}],
    })
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    assert result["suggestions"] == []
    reasons = [u["reason"] for u in result["unavailable_technicians"]]
    assert "outside_working_hours" in reasons


def test_tone_voice_formal_vs_friendly_alters_prompt(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    _seed_tenant(mth_c_db, "t1", tone_voice={
        "style": "formal", "custom_directive": "",
    })
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    prompts_formal = [c["system_prompt"] for c in _stub_llm]

    # Same setup, friendly tone.
    _stub_llm.clear()
    mth_c_db.reset()
    _seed_default_platform(mth_c_db)
    _seed_tenant(mth_c_db, "t2", tone_voice={
        "style": "friendly", "custom_directive": "",
    })
    _seed_tech_and_jobs(mth_c_db, "t2", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t2")
    run(generate_recommendations(
        tenant_id="t2", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    prompts_friendly = [c["system_prompt"] for c in _stub_llm]

    assert prompts_formal and prompts_friendly
    assert prompts_formal[0] != prompts_friendly[0]


def test_master_switch_off_forces_template_master_off(mth_c_db, _stub_llm):
    _seed_default_platform(mth_c_db)
    from tests._mth_c_helpers import seed_rules_doc
    from services.tenant_ai_rules.schema import (
        ACTION_INVENTORY, EMPLOYEE_KEYS,
    )
    seed_rules_doc(mth_c_db, "t1", {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {k: True for k in EMPLOYEE_KEYS},
        "working_hours": {"enabled": False, "timezone": "UTC",
                           "windows": []},
        "auto_action_allowlist":
            {a: "admin_approval" for a in ACTION_INVENTORY},
        "escalation_rules": [],
    }, master=False)
    _seed_tech_and_jobs(mth_c_db, "t1", "tech_alpha", n_stops=2)
    _seed_target_job(mth_c_db, "t1")
    result = run(generate_recommendations(
        tenant_id="t1", job_id="TGT", target_date="2026-02-16",
        eligible_technician_ids=None, max_suggestions=3,
        now_utc=NOW, eta_fn=_fake_eta_stub(),
    ))
    assert result["master_switch_on"] is False
    assert result["plain_english_source"] == "template_fallback_master_off"
    assert result["apply_mode"] == "queued_for_approval"
