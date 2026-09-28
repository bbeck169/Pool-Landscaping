"""MTH-C · Feb-2026 — prompt injection integration tests.

Locks:
  * For each of the 18 employees, ``build_employee_system_prompt``
    prepends the tone directive from the tenant rules.
  * Tenant A (formal) and tenant B (technical) produce different
    prompts for the same employee.
  * Cache respected — the 2nd call within 30s hits the cache
    instead of re-reading the DB.
  * Falsy ``tenant_id`` short-circuits to the raw employee prompt.
"""
from __future__ import annotations

from services.ai_hub.employee_registry import EMPLOYEES
from services.tenant_ai_rules.prompt_injection import (
    build_employee_system_prompt,
)
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _friendly_rules():
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def _formal_rules():
    return {
        **_friendly_rules(),
        "tone_voice": {"style": "formal", "custom_directive": ""},
    }


def _technical_rules():
    return {
        **_friendly_rules(),
        "tone_voice": {"style": "technical",
                        "custom_directive": "Cite ppm ranges."},
    }


def test_every_employee_gets_tone_directive_prepended(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _formal_rules())
    for spec in EMPLOYEES:
        emp = {"key": spec.key, "system_prompt":
                 f"You are {spec.codename}. Do your job."}
        out = run(build_employee_system_prompt(emp, "t1"))
        assert "Respond with professional" in out, spec.key
        assert emp["system_prompt"] in out, spec.key


def test_tenant_a_formal_vs_tenant_b_technical(mth_c_db):
    seed_rules_doc(mth_c_db, "t_a", _formal_rules())
    seed_rules_doc(mth_c_db, "t_b", _technical_rules())
    emp = {"key": "marco_executive", "system_prompt": "MARCO"}
    a = run(build_employee_system_prompt(emp, "t_a"))
    b = run(build_employee_system_prompt(emp, "t_b"))
    assert a != b
    assert "professional, courteous" in a
    assert "precisely and technically" in b
    assert "Tenant directive: Cite ppm ranges" in b


def test_cache_respected_second_call_uses_cache(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _formal_rules())
    emp = {"key": "nova", "system_prompt": "NOVA"}
    run(build_employee_system_prompt(emp, "t1"))
    # Remove the seeded doc — the cache should still return the
    # first read's result on the second call.
    mth_c_db.tenant_ai_rules.rows.clear()
    second = run(build_employee_system_prompt(emp, "t1"))
    assert "Respond with professional" in second


def test_no_tenant_returns_raw_prompt(mth_c_db):
    emp = {"key": "nova", "system_prompt": "Persona payload."}
    out = run(build_employee_system_prompt(emp, None))
    assert out == "Persona payload."


def test_missing_employee_prompt_returns_directive_only(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _formal_rules())
    out = run(build_employee_system_prompt({"key": "x"}, "t1"))
    # Directive alone — no trailing blank prompt.
    assert out.startswith("— Tone & voice guidance —")


def test_full_18_employee_count_in_registry():
    # Guardrail — the tone-directive test above iterates the same
    # registry the prompt path reads.  If someone ships employee 19
    # this test forces them to look at MTH-C prompt injection.
    assert len(EMPLOYEES) == 18
