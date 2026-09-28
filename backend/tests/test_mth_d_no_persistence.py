"""MTH-D · Feb-2026 — no-persistence contract.

Locks:
  * After 5 preview calls with different overlays, the tenant's
    stored ``tenant_ai_rules`` doc is byte-for-byte unchanged.
  * The cache is not polluted — a fresh
    :func:`resolve_rules_for_tenant` still returns the tenant's
    pre-preview state.
"""
from __future__ import annotations

import copy

from services.tenant_ai_rules.preview import preview_rules
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from tests._mth_c_helpers import mth_c_db, seed_rules_doc, run  # noqa: F401


def _stored_rules():
    return {
        "tone_voice": {"style": "friendly", "custom_directive": ""},
        "employee_enable_disable": {"marco_executive": True},
        "working_hours": {"enabled": False, "timezone": "UTC", "windows": []},
        "auto_action_allowlist": {},
        "escalation_rules": [],
    }


def test_five_previews_do_not_mutate_stored_doc(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _stored_rules(), master=True)
    snapshot = copy.deepcopy(mth_c_db.tenant_ai_rules.rows[0])

    async def _fake_llm(**kw):
        return {"raw": "sample", "provider": "emergent"}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    overlays = [
        ("tone_voice", {"style": "formal", "custom_directive": ""}),
        ("tone_voice", {"style": "technical",
                          "custom_directive": "cite ppm"}),
        ("escalation_rules", [
            {"keyword": "refund", "is_regex": False,
             "target_role": "admin", "sla_minutes": 5,
             "notify_channel": "email"},
        ]),
        ("working_hours", {"enabled": True, "timezone": "UTC",
                             "windows": [
                                 {"day": "mon", "start": "08:00",
                                  "end": "17:00"},
                             ]}),
        ("auto_action_allowlist", {"marco.create_admin_todo": "auto"}),
    ]
    kinds = ["response", "response", "escalation_match",
              "working_hours_status", "auto_action_walkthrough"]
    inputs = [
        {},
        {},
        {"test_messages": ["refund now"]},
        {"probe_datetime": "2026-02-02T18:00:00+00:00"},
        {"employee_key": "marco_executive",
         "action_key": "marco.create_admin_todo"},
    ]
    for (cat, val), kind, inp in zip(overlays, kinds, inputs):
        run(preview_rules(
            tenant_id="t1", category=cat, pending_value=val,
            preview_kind=kind, preview_input=inp,
        ))
    assert mth_c_db.tenant_ai_rules.rows[0] == snapshot


def test_cache_not_polluted_by_overlay(mth_c_db):
    seed_rules_doc(mth_c_db, "t1", _stored_rules(), master=True)
    before = run(resolve_rules_for_tenant("t1"))
    assert before["rules"]["tone_voice"]["style"] == "friendly"

    # Preview with a formal overlay.
    run(preview_rules(
        tenant_id="t1", category="tone_voice",
        pending_value={"style": "formal", "custom_directive": ""},
        preview_kind="working_hours_status",  # cheap kind — no LLM
        preview_input={"probe_datetime": "2026-02-02T18:00:00+00:00"},
    ))
    # Post-preview: cache still returns friendly.
    after = run(resolve_rules_for_tenant("t1"))
    assert after["rules"]["tone_voice"]["style"] == "friendly"
    # Overlay-applied flag is FALSE on the cached read.
    assert after.get("overlay_applied") is False


def test_no_revision_bump_after_previews(mth_c_db, monkeypatch):
    seed_rules_doc(mth_c_db, "t1", _stored_rules(), master=True)
    original_rev = mth_c_db.tenant_ai_rules.rows[0]["revision_number"]

    async def _fake_llm(**kw):
        return {"raw": "ok", "provider": "emergent"}

    monkeypatch.setattr(
        "services.llm_provider.call_llm_with_fallback",
        _fake_llm, raising=True,
    )
    for _ in range(3):
        run(preview_rules(
            tenant_id="t1", category="tone_voice",
            pending_value={"style": "formal", "custom_directive": ""},
            preview_kind="response", preview_input={},
        ))
    assert mth_c_db.tenant_ai_rules.rows[0]["revision_number"] == original_rev
