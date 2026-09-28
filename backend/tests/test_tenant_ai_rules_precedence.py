"""MTH-A · Feb-2026 — Rule precedence tests.

Contract for ``services.tenant_ai_rules.resolver.resolve_rules_for_tenant``:

  * When the tenant has no explicit value → platform default wins
    and ``override_map["<field>"] == "platform"``.
  * When the tenant has an explicit value → tenant wins and
    ``override_map["<field>"] == "tenant"``.
  * ``tone_voice`` merges at the sub-field level: a tenant that
    overrides only ``style`` keeps the platform's ``custom_directive``.
  * ``escalation_rules`` is an ATOMIC override (whole-array).
  * ``reset_category`` cleanly restores platform provenance for
    every sub-field.
"""
from __future__ import annotations

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def _actor():
    return {"id": "u1", "email": "a@t1", "name": "Alice"}


def test_all_platform_on_first_read(fake_db):
    resolved = run(resolve_rules_for_tenant("t1"))
    om = resolved["override_map"]
    # Every mapped field starts as "platform".
    assert om["tone_voice.style"] == "platform"
    assert om["tone_voice.custom_directive"] == "platform"
    assert om["working_hours.timezone"] == "platform"
    assert om["working_hours.enabled"] == "platform"
    assert om["escalation_rules"] == "platform"
    # Platform default style is "friendly".
    assert resolved["rules"]["tone_voice"]["style"] == "friendly"


def test_tenant_override_wins_and_flags_map(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor=_actor(), reason="tone-switch-corp-brand",
    ))
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["rules"]["tone_voice"]["style"] == "formal"
    assert (resolved["override_map"]["tone_voice.style"]
             == "tenant")
    assert (resolved["override_map"]["tone_voice.custom_directive"]
             == "tenant")


def test_partial_dict_merge_for_working_hours(fake_db):
    """Tenant overrides only the timezone.  ``enabled`` + ``windows``
    stay platform-provenance."""
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "America/New_York",
         "windows": [
             {"day": "mon", "start": "09:00", "end": "18:00"},
         ]},
        actor=_actor(),
        reason="tenant-wants-nyc-hours-adjustment",
    ))
    # Now RESET everything except timezone by re-saving JUST the
    # timezone. The store today saves the whole category, so we
    # rely on the merger's behaviour when the tenant only stored
    # a subset of keys. Simulate by directly manipulating the doc:
    row = fake_db.tenant_ai_rules.rows[0]
    row["rules"]["working_hours"] = {"timezone": "America/New_York"}
    cache.invalidate_all()

    resolved = run(resolve_rules_for_tenant("t1"))
    wh = resolved["rules"]["working_hours"]
    assert wh["timezone"] == "America/New_York"
    # Windows + enabled came from platform.
    assert wh["enabled"] is True
    assert isinstance(wh["windows"], list) and wh["windows"]
    om = resolved["override_map"]
    assert om["working_hours.timezone"] == "tenant"
    assert om["working_hours.enabled"] == "platform"
    assert om["working_hours.windows"] == "platform"


def test_escalation_rules_are_atomic(fake_db):
    run(store.save_category(
        "t1", "escalation_rules",
        [{"keyword": "chargeback", "is_regex": False,
          "target_role": "super", "sla_minutes": 15,
          "notify_channel": "both"}],
        actor=_actor(),
        reason="add-chargeback-escalation-please",
    ))
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["override_map"]["escalation_rules"] == "tenant"
    assert (resolved["rules"]["escalation_rules"][0]["keyword"]
             == "chargeback")


def test_reset_flips_provenance_back_to_platform(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "technical", "custom_directive": "corp"},
        actor=_actor(),
        reason="switching-tone-to-technical-lang",
    ))
    run(store.reset_category(
        "t1", "tone_voice",
        actor=_actor(),
        reason="rolling-back-tone-change-please",
    ))
    resolved = run(resolve_rules_for_tenant("t1"))
    assert (resolved["override_map"]["tone_voice.style"]
             == "platform")
    assert resolved["rules"]["tone_voice"]["style"] == "friendly"


def test_platform_update_flows_into_new_reads(fake_db):
    """Platform default change → resolved view for tenant reflects
    the new default (only for fields where the tenant has no override)."""
    run(resolve_rules_for_tenant("t1"))                        # warm up
    run(store.save_platform_category(
        category="tone_voice",
        value={"style": "technical", "custom_directive": ""},
        actor=_actor(),
        reason="platform-tone-shift-to-technical",
    ))
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["rules"]["tone_voice"]["style"] == "technical"
    assert (resolved["override_map"]["tone_voice.style"]
             == "platform")


def test_master_switch_flows_through_resolved_view(fake_db):
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["master_ai_send_live_comms"] is False
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="tenant-goes-live-with-ai",
    ))
    resolved = run(resolve_rules_for_tenant("t1"))
    assert resolved["master_ai_send_live_comms"] is True
