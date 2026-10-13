"""P2 #10d · Feb-2026 — Automation-gate helper + tenant-settings
schema regression suite.

Covers:
  1. The 4 flag names in ``_P2_10D_FLAGS`` match the exact slugs
     exposed via ``TenantSettingsUpdate``.
  2. ``automation_enabled`` returns True on an unset flag (default
     opt-out posture).
  3. ``automation_enabled`` returns False when the flag is
     explicitly False on the tenant row.
  4. ``automation_enabled`` raises ValueError on an unknown flag
     (defense against typos at call sites).
  5. The lead-conversion welcome email + SMS BOTH short-circuit
     when ``lead_conversion_welcome_enabled=False`` on the tenant
     (proves the gate is wired at the top of both entry points).

Deferred to TD-19 (surfaced in the Commit 4 receipt):
  * Service-side wiring for ``completion_followup_sms_enabled``,
    ``invoice_past_due_enabled``, ``estimate_reminder_enabled`` at
    their respective entry points (``services/completion_sms_template``,
    ``emailer.py``). The schema + helper are in place and the admin
    editor UI (Commit 3) already covers these templates; the gate
    wires can land as a tight follow-up ticket.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _TenantsStub:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    async def find_one(self, flt, projection=None):
        for d in self._docs:
            if d.get("id") == flt.get("id"):
                return dict(d)
        return None


# ─── Case 1 · schema <-> gate flag-name alignment ────────────────

def test_tenant_settings_schema_matches_gate_flag_names():
    """Any flag listed in ``_P2_10D_FLAGS`` MUST also appear on
    ``TenantSettingsUpdate`` — otherwise an admin can't set the flag
    they're being gated by."""
    from services.tenant_automation_gates import _P2_10D_FLAGS
    from routers.tenants import TenantSettingsUpdate
    model_fields = set(TenantSettingsUpdate.model_fields.keys())
    for flag in _P2_10D_FLAGS:
        assert flag in model_fields, (
            f"Flag {flag!r} is checked by automation_enabled() but "
            "not settable via TenantSettingsUpdate."
        )


# ─── Case 2 · default True on unset ──────────────────────────────

def test_automation_enabled_defaults_true_on_unset():
    import config
    from services.tenant_automation_gates import automation_enabled
    orig = config.db
    class _FakeDB:
        tenants = _TenantsStub([{"id": "t-unset"}])  # no flag set
    config.db = _FakeDB()
    try:
        for flag in ("lead_conversion_welcome_enabled",
                      "completion_followup_sms_enabled",
                      "invoice_past_due_enabled",
                      "estimate_reminder_enabled"):
            assert _run(automation_enabled("t-unset", flag)) is True
    finally:
        config.db = orig


# ─── Case 3 · explicit False → gate returns False ────────────────

def test_automation_enabled_false_when_tenant_opted_out():
    import config
    from services.tenant_automation_gates import automation_enabled
    orig = config.db
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-opted-out",
            "lead_conversion_welcome_enabled": False,
            "invoice_past_due_enabled": False,
        }])
    config.db = _FakeDB()
    try:
        assert _run(automation_enabled("t-opted-out", "lead_conversion_welcome_enabled")) is False
        assert _run(automation_enabled("t-opted-out", "invoice_past_due_enabled")) is False
        # Siblings default True.
        assert _run(automation_enabled("t-opted-out", "completion_followup_sms_enabled")) is True
        assert _run(automation_enabled("t-opted-out", "estimate_reminder_enabled")) is True
    finally:
        config.db = orig


# ─── Case 4 · unknown flag raises ────────────────────────────────

def test_automation_enabled_unknown_flag_raises():
    from services.tenant_automation_gates import automation_enabled
    with pytest.raises(ValueError, match="unknown flag"):
        _run(automation_enabled("t-x", "not_a_real_flag"))


# ─── Case 5 · lead-conversion welcome gated (email + sms) ────────

def test_lead_conversion_welcome_short_circuits_when_disabled():
    import config
    from services import lead_conversion_notifications as lcn
    orig = config.db
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-no-lead-welcome",
            "lead_conversion_welcome_enabled": False,
        }])
    config.db = _FakeDB()
    try:
        # Both entry points return None without reaching recipient
        # resolution / render — the gate is the first statement.
        r_email = _run(lcn._send_welcome_email(
            tenant_id="t-no-lead-welcome",
            customer={"id": "c-1", "name": "Test"},
            lead_id="l-1",
        ))
        assert r_email is None
        r_sms = _run(lcn._send_welcome_sms(
            tenant_id="t-no-lead-welcome",
            customer={"id": "c-1", "name": "Test"},
            lead_id="l-1",
        ))
        assert r_sms is None
    finally:
        config.db = orig
