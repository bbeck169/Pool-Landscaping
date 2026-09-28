"""MTH-A · Feb-2026 — Combined ``resolve_ai_send_gate`` matrix.

Locks the fail-first evaluation order across all three layers:

    1. Master switch off → False, "master_switch_off"
    2. Per-employee disabled → False, "employee_disabled"
    3. Outside working hours → False, "outside_working_hours"
    4. All layers permissive → True, "ok"

Plus:

    * ``stamp_agent_context_with_gate`` returns AGENT when the gate
      is False even if the employee is authorized.
    * ``stamp_agent_context_with_gate`` preserves the base decision
      when the gate is True.
    * A gate-lookup exception (e.g. DB blip) falls back to the sync
      ``stamp_agent_context`` decision.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.ai_hub.context_stamping import (
    stamp_agent_context, stamp_agent_context_with_gate,
)
from services.comms_env_guard import CommsContext
from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.gate import resolve_ai_send_gate
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def _actor():
    return {"id": "u", "email": "a@t1"}


def _mon_10(tz="America/Los_Angeles"):
    return datetime(2026, 2, 16, 10, 0, tzinfo=ZoneInfo(tz))


def _sun_3(tz="America/Los_Angeles"):
    return datetime(2026, 2, 15, 3, 0, tzinfo=ZoneInfo(tz))


# ─── resolve_ai_send_gate — the layer matrix ─────────────────────

def test_all_off_master_switch_wins(fake_db):
    """Master OFF trumps every other permissive layer."""
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=_mon_10(),
    ))
    assert allowed is False
    assert reason == "master_switch_off"


def test_master_on_but_employee_disabled(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    # Disable marco for this tenant.
    from services.tenant_ai_rules.schema import EMPLOYEE_KEYS
    payload = {k: True for k in EMPLOYEE_KEYS}
    payload["marco_executive"] = False
    run(store.save_category(
        "t1", "employee_enable_disable", payload,
        actor=_actor(),
        reason="marco-off-for-t1-per-req",
    ))
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=_mon_10(),
    ))
    assert allowed is False
    assert reason == "employee_disabled"


def test_master_on_but_outside_hours(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "America/Los_Angeles",
         "windows": [
             {"day": "mon", "start": "08:00", "end": "17:00"},
         ]},
        actor=_actor(),
        reason="tenant-monday-hours-only",
    ))
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=_sun_3(),
    ))
    assert allowed is False
    assert reason == "outside_working_hours"


def test_all_permissive_returns_ok(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "marco_executive", now=_mon_10(),
    ))
    assert allowed is True
    assert reason == "ok"


def test_employee_key_none_skips_employee_layer(fake_db):
    """Callers that don't have an employee context can still probe
    the master + working-hours layers via ``employee_key=None``."""
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    allowed, reason = run(resolve_ai_send_gate(
        "t1", None, now=_mon_10(),
    ))
    assert allowed is True
    assert reason == "ok"


def test_unknown_employee_key_fails_safe(fake_db):
    """Missing / unregistered employee → gate refuses.  Prevents an
    unknown persona from slipping through the enable-disable map."""
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    allowed, reason = run(resolve_ai_send_gate(
        "t1", "bogus_employee_key", now=_mon_10(),
    ))
    assert allowed is False
    assert reason == "employee_disabled"


# ─── stamp_agent_context_with_gate ───────────────────────────────

def _authorized_employee():
    return {"id": "e1", "key": "marco_executive",
            "authorized_for_public_use": True}


def _unauthorized_employee():
    return {"id": "e2", "key": "marco_executive",
            "authorized_for_public_use": False}


def test_gate_off_forces_agent_even_for_authorized(fake_db):
    # Master OFF → gate blocks.
    ctx = run(stamp_agent_context_with_gate(
        tenant_id="t1", employee=_authorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx == CommsContext.AGENT


def test_gate_on_preserves_authorized_context(fake_db):
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    # Working hours default (LA Mon-Fri 08:00-17:00) — assume "now"
    # is inside the window for the test box's local time. To keep
    # this test deterministic across CI clocks, flip to a wide-open
    # window covering the full week.
    run(store.save_category(
        "t1", "working_hours",
        {"enabled": True, "timezone": "UTC",
         "windows": [
             {"day": d, "start": "00:00", "end": "23:59"}
             for d in ("mon", "tue", "wed", "thu", "fri",
                        "sat", "sun")
         ]},
        actor=_actor(),
        reason="always-on-window-for-test-run",
    ))
    ctx = run(stamp_agent_context_with_gate(
        tenant_id="t1", employee=_authorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx == CommsContext.SYSTEM


def test_gate_wrapper_falls_back_to_agent_for_unauthorized(fake_db):
    """Even with master ON + everything permissive, an unauthorized
    employee still gets AGENT (base rule from AIHUB-A)."""
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-comms",
    ))
    ctx = run(stamp_agent_context_with_gate(
        tenant_id="t1", employee=_unauthorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx == CommsContext.AGENT


def test_gate_wrapper_handles_lookup_exception(monkeypatch,
                                                  fake_db):
    """A gate DB blip must NOT crash the send — fall back to the
    sync ``stamp_agent_context`` decision."""
    from services.ai_hub import context_stamping

    async def _boom(*_a, **_kw):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "services.tenant_ai_rules.gate.resolve_ai_send_gate",
        _boom,
    )
    ctx = run(context_stamping.stamp_agent_context_with_gate(
        tenant_id="t1", employee=_authorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    # Falls back to base (authorized → SYSTEM).
    assert ctx == CommsContext.SYSTEM


def test_gate_wrapper_no_tenant_falls_back_to_base(fake_db):
    """No tenant scope → wrapper mirrors the sync decision."""
    ctx = run(stamp_agent_context_with_gate(
        tenant_id="", employee=_authorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx == CommsContext.SYSTEM
    ctx_bad = run(stamp_agent_context_with_gate(
        tenant_id="", employee=_unauthorized_employee(),
        requested_context=CommsContext.SYSTEM,
    ))
    assert ctx_bad == CommsContext.AGENT


def test_sync_stamp_unaffected_by_new_wrapper():
    """Regression: the pre-existing ``stamp_agent_context`` sync
    function keeps its contract from AIHUB-A."""
    assert stamp_agent_context(
        employee=None, requested_context=CommsContext.SYSTEM,
    ) == CommsContext.AGENT
    assert stamp_agent_context(
        employee={"authorized_for_public_use": True, "key": "x"},
        requested_context=CommsContext.SYSTEM,
    ) == CommsContext.SYSTEM
    assert stamp_agent_context(
        employee={"authorized_for_public_use": False, "key": "x"},
        requested_context=CommsContext.SYSTEM,
    ) == CommsContext.AGENT
