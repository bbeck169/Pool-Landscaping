"""Phase P14 · Feb-2026 · Item 3 — auto_visit_email `from_name`.

Asserts the outbound Resend ``from`` header carries the tenant's
company name (RFC 5322 ``Display Name <address>`` shape) instead
of the bare from address.

Uses plain ``asyncio.run(...)`` rather than ``pytest-asyncio`` —
the pod doesn't have the plugin installed and every other async
call site in ``backend/tests/`` uses the sync-wrapping pattern.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    """Wrapper to run an async coroutine in a fresh event loop."""
    return asyncio.get_event_loop().run_until_complete(coro) \
        if not asyncio.new_event_loop().is_closed() \
        else asyncio.run(coro)


def _patchset():
    """Common patch set for the send_visit_summary_email flow."""
    return [
        patch("services.customer_multi_contact.active_email_recipients",
               side_effect=lambda customer, context: ["customer@example.com"]),
        patch("services.customer_multi_contact.log_mute_suppressed",
               new=AsyncMock(return_value=None)),
        patch("services.tenants.business_settings.get_effective_business_settings",
               new=AsyncMock(return_value=None)),
        patch("routers.service_reports._redact_report_for_customer",
               side_effect=lambda x: dict(x)),
        patch("services.auto_visit_email._is_enabled", return_value=True),
    ]


def test_p14_resend_from_header_carries_company_name(monkeypatch):
    """Mock ``resend.Emails.send`` and assert the ``from`` field
    is ``"<tenant.name> <RESEND_FROM>"``."""
    monkeypatch.setenv("RESEND_API_KEY", "test-key-p14")
    monkeypatch.setenv("RESEND_FROM", "onboarding@resend.dev")

    tenant = {
        "id": "p14-tenant",
        "name": "Aquaterra Pool & Landscape",
        "settings": {"auto_visit_email": {"enabled": True}},
    }
    job = {"id": "p14-job", "customer_id": "p14-cust",
           "address": "9 Oak St, Chandler, AZ"}
    sr = {"id": "p14-sr", "job_id": "p14-job",
          "created_at": "2026-02-14T00:00:00+00:00"}

    from services import auto_visit_email as ave
    ave_db_mock = MagicMock()
    ave_db_mock.customers.find_one = AsyncMock(return_value={
        "id": "p14-cust", "email": "customer@example.com",
        "tenant_id": "p14-tenant", "name": "Test Customer",
        "portal_email": "customer@example.com",
    })
    ave_db_mock.outbound_emails.find_one = AsyncMock(return_value=None)
    ave_db_mock.outbound_emails.insert_one = AsyncMock(return_value=None)

    fake_resend = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "resend-mock-id"})
    sys.modules["resend"] = fake_resend

    patches = _patchset() + [patch.object(ave, "db", ave_db_mock)]
    for p in patches:
        p.start()
    try:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                ave.send_visit_summary_email(tenant, job, sr)
            )
        finally:
            loop.close()
    finally:
        for p in reversed(patches):
            p.stop()
        sys.modules.pop("resend", None)

    assert result is not None, "send_visit_summary_email returned None"
    assert fake_resend.Emails.send.called
    from_header = fake_resend.Emails.send.call_args[0][0]["from"]
    assert from_header == "Aquaterra Pool & Landscape <onboarding@resend.dev>", (
        f"unexpected from header: {from_header!r}"
    )


def test_p14_from_header_falls_back_to_default_when_tenant_name_missing(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key-p14")
    monkeypatch.setenv("RESEND_FROM", "onboarding@resend.dev")

    tenant = {
        "id": "p14-tenant-noname",
        "settings": {"auto_visit_email": {"enabled": True}},
    }
    job = {"id": "j", "customer_id": "c", "address": "x"}
    sr = {"id": "s", "job_id": "j",
          "created_at": "2026-02-14T00:00:00+00:00"}

    from services import auto_visit_email as ave
    ave_db_mock = MagicMock()
    ave_db_mock.customers.find_one = AsyncMock(return_value={
        "id": "c", "email": "who@example.com",
        "tenant_id": "p14-tenant-noname",
    })
    ave_db_mock.outbound_emails.find_one = AsyncMock(return_value=None)
    ave_db_mock.outbound_emails.insert_one = AsyncMock(return_value=None)

    fake_resend = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "id-2"})
    sys.modules["resend"] = fake_resend

    patches = _patchset() + [patch.object(ave, "db", ave_db_mock)]
    for p in patches:
        p.start()
    try:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                ave.send_visit_summary_email(tenant, job, sr)
            )
        finally:
            loop.close()
    finally:
        for p in reversed(patches):
            p.stop()
        sys.modules.pop("resend", None)

    from_header = fake_resend.Emails.send.call_args[0][0]["from"]
    assert from_header == "Pool & Landscaping <onboarding@resend.dev>", (
        f"expected module default company; got {from_header!r}"
    )


def test_p14_from_header_strips_header_break_chars(monkeypatch):
    """Adversarial: a tenant name with ``<`` / newline chars can't
    break out into extra headers. Every stripped char keeps the
    display name from spoofing.
    """
    monkeypatch.setenv("RESEND_API_KEY", "test-key-p14")
    monkeypatch.setenv("RESEND_FROM", "onboarding@resend.dev")

    tenant = {
        "id": "adv",
        "name": "Evil<Corp\r\nBCC: bad@example.com,Fake",
        "settings": {"auto_visit_email": {"enabled": True}},
    }
    job = {"id": "j", "customer_id": "c", "address": "x"}
    sr = {"id": "s", "job_id": "j",
          "created_at": "2026-02-14T00:00:00+00:00"}

    from services import auto_visit_email as ave
    ave_db_mock = MagicMock()
    ave_db_mock.customers.find_one = AsyncMock(return_value={
        "id": "c", "email": "who@example.com", "tenant_id": "adv",
    })
    ave_db_mock.outbound_emails.find_one = AsyncMock(return_value=None)
    ave_db_mock.outbound_emails.insert_one = AsyncMock(return_value=None)

    fake_resend = MagicMock()
    fake_resend.Emails.send = MagicMock(return_value={"id": "id-3"})
    sys.modules["resend"] = fake_resend

    patches = _patchset() + [patch.object(ave, "db", ave_db_mock)]
    for p in patches:
        p.start()
    try:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                ave.send_visit_summary_email(tenant, job, sr)
            )
        finally:
            loop.close()
    finally:
        for p in reversed(patches):
            p.stop()
        sys.modules.pop("resend", None)

    from_header = fake_resend.Emails.send.call_args[0][0]["from"]
    # None of these break-chars survived.
    for bad in ("<", ">", ",", ";", '"', "\r", "\n"):
        # The ``<`` and ``>`` framing the address are legitimate — check
        # they only appear as the address wrapper.
        if bad in "<>":
            continue
        assert bad not in from_header, (
            f"header-break char {bad!r} leaked into from: {from_header!r}"
        )
    # And the resulting header still has a valid shape.
    assert from_header.endswith(" <onboarding@resend.dev>")
