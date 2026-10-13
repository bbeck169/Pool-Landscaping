"""P2 #10e · Feb-2026 — Automation-gate service-wire sweep.

Closes TD-19 by proving the 3 remaining P2 #10d service entry
points now short-circuit when their tenant flag is False:
  * ``services.completion_sms_template.should_send_completion_followup_sms``
    (consumed by ``routers/service_reports.py::_bg_send_completion_sms``)
  * ``backend.emailer.send_invoice_reminder_email``
  * ``backend.emailer.send_estimate_reminder_email``

Each entry point also fires normally (reaches the next hard
dependency) when the flag is True / unset, proving the gate is a
pre-check only.  The default-True / unset-is-opt-in posture is
already exercised in ``test_p2_10d_automation_toggles.py``.

Shape conventions match the P2 #10d sibling suite:
  * ``_TenantsStub.find_one`` honours the ``{id}`` filter.
  * Each case restores ``config.db`` in a ``finally`` so pytest
    collection order is irrelevant.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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


# ─── should_send_completion_followup_sms ─────────────────────────

def test_should_send_completion_followup_sms_returns_false_when_disabled():
    """``completion_followup_sms_enabled=False`` → helper returns
    False.  ``routers/service_reports.py::_bg_send_completion_sms``
    uses this to short-circuit before any DB / deny-list / RC send
    work."""
    import config
    from services.completion_sms_template import (
        should_send_completion_followup_sms,
    )
    orig = config.db
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-sms-off",
            "completion_followup_sms_enabled": False,
        }])
    config.db = _FakeDB()
    try:
        assert _run(
            should_send_completion_followup_sms("t-sms-off"),
        ) is False
    finally:
        config.db = orig


def test_should_send_completion_followup_sms_defaults_true_on_unset():
    """Flag unset on tenant row → helper returns True (opt-out
    posture).  Also True when the tenant doc is entirely absent."""
    import config
    from services.completion_sms_template import (
        should_send_completion_followup_sms,
    )
    orig = config.db
    class _FakeDBUnset:
        tenants = _TenantsStub([{"id": "t-unset"}])
    class _FakeDBAbsent:
        tenants = _TenantsStub([])
    config.db = _FakeDBUnset()
    try:
        assert _run(
            should_send_completion_followup_sms("t-unset"),
        ) is True
    finally:
        config.db = orig
    config.db = _FakeDBAbsent()
    try:
        assert _run(
            should_send_completion_followup_sms("t-absent"),
        ) is True
    finally:
        config.db = orig


# ─── send_invoice_reminder_email ─────────────────────────────────

def test_send_invoice_reminder_email_skips_when_disabled():
    """``invoice_past_due_enabled=False`` → function returns False
    before touching ``emailer.db`` (no customer lookup, no Resend
    call).  The pre-send gate is the first substantive statement
    after the doc_type guard."""
    import config
    import emailer
    orig_db = config.db
    orig_emailer_db = emailer.db
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-inv-off",
            "invoice_past_due_enabled": False,
        }])
    config.db = _FakeDB()
    # If the gate fails to short-circuit, the next line in the
    # function accesses emailer.db.customers.find_one; sentinel
    # MagicMock would be touched. We assert it was NOT touched.
    sentinel_db = MagicMock()
    sentinel_db.customers.find_one = AsyncMock(
        side_effect=AssertionError(
            "gate failed to short-circuit — db.customers.find_one called"
        ),
    )
    emailer.db = sentinel_db
    try:
        res = _run(emailer.send_invoice_reminder_email({
            "id": "inv-1",
            "tenant_id": "t-inv-off",
            "doc_type": "invoice",
            "customer_id": "c-1",
        }))
        assert res is False
        sentinel_db.customers.find_one.assert_not_called()
    finally:
        config.db = orig_db
        emailer.db = orig_emailer_db


def test_send_invoice_reminder_email_proceeds_when_flag_true():
    """``invoice_past_due_enabled=True`` (or unset default True) →
    function proceeds past the gate.  We stub RESEND_API_KEY so
    the function reaches the customer lookup, then prove
    ``db.customers.find_one`` is called with the right filter."""
    import config
    import emailer
    orig_db = config.db
    orig_emailer_db = emailer.db
    orig_api_key = emailer.RESEND_API_KEY
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-inv-on",
            "invoice_past_due_enabled": True,
        }])
    config.db = _FakeDB()
    sentinel_db = MagicMock()
    # Returning {} for customer → missing email → function returns
    # False, but AFTER reaching the customer lookup.  Proves the
    # gate did NOT short-circuit at the top.
    sentinel_db.customers.find_one = AsyncMock(return_value={})
    sentinel_db.users.find_one = AsyncMock(return_value=None)
    emailer.db = sentinel_db
    emailer.RESEND_API_KEY = "re_test_key_present"
    try:
        res = _run(emailer.send_invoice_reminder_email({
            "id": "inv-2",
            "tenant_id": "t-inv-on",
            "doc_type": "invoice",
            "customer_id": "c-2",
        }))
        # The function bails out later (no email on customer) but
        # ONLY after moving past the gate — which is what we're
        # proving here.
        assert res is False
        sentinel_db.customers.find_one.assert_called_once()
    finally:
        config.db = orig_db
        emailer.db = orig_emailer_db
        emailer.RESEND_API_KEY = orig_api_key


# ─── send_estimate_reminder_email ────────────────────────────────

def test_send_estimate_reminder_email_skips_when_disabled():
    """``estimate_reminder_enabled=False`` → function returns False
    before touching ``emailer.db``.  Sibling of the invoice-reminder
    case above."""
    import config
    import emailer
    orig_db = config.db
    orig_emailer_db = emailer.db
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-est-off",
            "estimate_reminder_enabled": False,
        }])
    config.db = _FakeDB()
    sentinel_db = MagicMock()
    sentinel_db.customers.find_one = AsyncMock(
        side_effect=AssertionError(
            "gate failed to short-circuit — db.customers.find_one called"
        ),
    )
    emailer.db = sentinel_db
    try:
        res = _run(emailer.send_estimate_reminder_email(
            {
                "id": "est-1",
                "tenant_id": "t-est-off",
                "doc_type": "estimate",
                "customer_id": "c-1",
            },
            tenant={"id": "t-est-off"},
            review_url="https://example.com/review",
        ))
        assert res is False
        sentinel_db.customers.find_one.assert_not_called()
    finally:
        config.db = orig_db
        emailer.db = orig_emailer_db


def test_send_estimate_reminder_email_proceeds_when_flag_true():
    """``estimate_reminder_enabled=True`` (or unset default True) →
    function proceeds past the gate."""
    import config
    import emailer
    orig_db = config.db
    orig_emailer_db = emailer.db
    orig_api_key = emailer.RESEND_API_KEY
    class _FakeDB:
        tenants = _TenantsStub([{
            "id": "t-est-on",
            # unset flag → default True
        }])
    config.db = _FakeDB()
    sentinel_db = MagicMock()
    sentinel_db.customers.find_one = AsyncMock(return_value={})
    sentinel_db.users.find_one = AsyncMock(return_value=None)
    emailer.db = sentinel_db
    emailer.RESEND_API_KEY = "re_test_key_present"
    try:
        res = _run(emailer.send_estimate_reminder_email(
            {
                "id": "est-2",
                "tenant_id": "t-est-on",
                "doc_type": "estimate",
                "customer_id": "c-2",
            },
            tenant={"id": "t-est-on"},
            review_url="https://example.com/review",
        ))
        assert res is False
        sentinel_db.customers.find_one.assert_called_once()
    finally:
        config.db = orig_db
        emailer.db = orig_emailer_db
        emailer.RESEND_API_KEY = orig_api_key
