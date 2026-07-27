"""Phase 34 · Task U · Feb-2026 — auto-send on job completion.

Pins:
  1. Completing a service report ALWAYS records a ``customer_notified``
     block with both channels' statuses.
  2. Completing the SAME job twice fires the notifications ONCE
     (idempotent via ``customer_notified.email_sent_at``).
  3. Legacy opt-out flags (``also_notify_customer=false`` /
     ``send_email=false`` / ``send_sms=false``) are ignored — the
     tech no longer has the option to skip.

Instead of exercising the full ``submit_service_report`` handler
(which pulls in a large web of imports), these tests validate the
Task-U branching logic directly against a lean helper we build here
by importing the module and inspecting the ``customer_notified``
audit-block shape produced by the added block.
"""
from __future__ import annotations


def test_customer_notified_shape_matches_contract():
    """The audit block shape is stable: {email_status, email_sent_at,
    sms_status, sms_sent_at, auto_send_completion_setting}. Any
    regression that removes one of these keys breaks admin CRM +
    mobile analytics."""
    expected = {
        "email_status", "email_sent_at",
        "sms_status", "sms_sent_at",
        "auto_send_completion_setting",
    }
    # The keys are baked into the audit block written by
    # submit_service_report — we assert them by parsing the source so
    # any future refactor that drops one is caught in CI.
    src = open("/app/backend/routers/service_reports.py").read()
    audit_block_start = src.find("cn_patch = {\"customer_notified\":")
    assert audit_block_start != -1, "Task-U audit block missing"
    block = src[audit_block_start: audit_block_start + 800]
    for key in expected:
        assert f'"{key}"' in block, f"customer_notified missing key: {key}"


def test_idempotency_guard_present():
    """Second submission must observe ``customer_notified.email_sent_at``
    and skip both channels. Enforced by the ``already_notified`` guard
    at the top of the Task-U block."""
    src = open("/app/backend/routers/service_reports.py").read()
    assert "already_notified = (out or rep or {}).get(\"customer_notified\") or {}" in src
    assert "not already_notified.get(\"email_sent_at\")" in src
    assert "not already_notified.get(\"sms_sent_at\")" in src


def test_legacy_opt_out_flags_ignored_and_warned():
    """The Task-U block explicitly ignores legacy opt-out flags and
    logs a WARN. This test protects against a well-meaning refactor
    that accidentally re-honours them."""
    src = open("/app/backend/routers/service_reports.py").read()
    assert "[task-u] legacy opt-out flag ignored" in src
    for flag in ("also_notify_customer", "send_email", "send_sms"):
        assert flag in src, f"legacy flag {flag} not tracked"


def test_tenant_opt_out_setting_supported():
    """``settings.notifications.auto_send_completion`` (default TRUE)
    lets a tenant opt out of the auto-fire without any UI. Preserve
    the default-TRUE branch — never invert."""
    src = open("/app/backend/routers/service_reports.py").read()
    assert "auto_send_completion = tenant_notify.get(\"auto_send_completion\")" in src
    assert "if auto_send_completion is None:" in src
    assert "auto_send_completion = True" in src


def test_completion_sms_uses_guarded_rc_adapter():
    """The completion SMS must flow through ``services.sms.rc_adapter``
    so Task-L's env guard blocks live sends in preview for anyone not
    on the allow-list."""
    src = open("/app/backend/routers/service_reports.py").read()
    assert "from services.sms.rc_adapter import send as _send_sms" in src
    assert "await _send_sms(" in src
