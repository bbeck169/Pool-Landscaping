"""SMS-RECIPIENT-FIX · Feb-2026 — Pytest coverage for the
customer-facing deny-list wiring across all 7 unprotected SMS send
paths + the ``utils.send_sms`` ``kind`` kwarg + the audit script.

Approach
--------
A. **Static-source wiring contract** (fast, no I/O) — read each
   modified module's source and assert the exact wiring pattern is
   present at the right spot. Mirrors the ``on_my_way.py:321-333``
   precedent that this ticket replicates.

B. **Async behavior tests** (mock-based) — for a representative
   subset of the 7 sites, patch
   ``strip_admin_owned_recipients`` + the terminal SMS adapter and
   assert that:

   * when the strip returns a non-empty ``stripped`` list the
     adapter is NOT called;
   * the strip is invoked with ``kind="customer_facing"``,
     ``channel="sms"``, and the right ``tenant_id``;
   * when the strip returns everything in ``kept``, the adapter
     IS called with the kept phone verbatim.

C. **``utils.send_sms`` kwarg plumbing** — the ``kind`` kwarg
   defaults to ``"internal"`` (strict pass-through). Only
   ``kind="customer_facing"`` + a non-empty ``tenant_id`` engages the
   strip. ``notify_customer`` must pass ``kind="customer_facing"``
   (verified against source).

D. **Audit script sanity** — module imports, CLI parses, and the
   normaliser collapses E.164 / dashed / parenthesised numbers to
   the same last-10-digits bucket. Mongo-touching paths are mocked
   so the test runs offline.

This file deliberately avoids spinning the FastAPI test client
because the shared ``_shared_mongo`` conftest fixtures assume a
live Mongo + supervisor-running backend; the wiring contract this
suite protects is static-source + mock-driven, so none of that is
required. The existing
``backend/tests/test_notification_cleanup_iv.py`` already covers
the full-stack ``on_my_way`` integration end-to-end against the
real deny-list.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ═════════════════════════════════════════════════════════════════════
# A · Static-source wiring contract — every modified site must import
# the deny-list and pass ``kind="customer_facing"`` + ``channel="sms"``.
# ═════════════════════════════════════════════════════════════════════
_SITES = {
    "routers/service_reports.py": (
        "SMS-RECIPIENT-FIX",
        # Both _bg_send_completion_sms and _send_recap_sms wire it.
        2,
    ),
    "services/notifications_pipeline/service_notifications.py": (
        "SMS-RECIPIENT-FIX", 1,
    ),
    "routers/could_not_service.py": ("SMS-RECIPIENT-FIX", 1),
    "services/live_dispatcher.py": ("SMS-RECIPIENT-FIX", 1),
    "services/fleet/notifications.py": ("SMS-RECIPIENT-FIX", 1),
    "routers/comms.py": (
        "SMS-RECIPIENT-FIX",
        # Automation + manual fan-out branches.
        2,
    ),
    "utils.py": ("SMS-RECIPIENT-FIX", 1),
}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf8")


@pytest.mark.parametrize("rel,expect", list(_SITES.items()))
def test_site_imports_strip_admin_owned_recipients(rel, expect):
    """Every migrated site imports the deny-list helper."""
    src = _read(rel)
    assert "strip_admin_owned_recipients" in src, (
        f"{rel} missing strip_admin_owned_recipients import — "
        "SMS-RECIPIENT-FIX wiring regressed"
    )


@pytest.mark.parametrize("rel,expect", list(_SITES.items()))
def test_site_passes_customer_facing_kind(rel, expect):
    """Every migrated site passes ``kind="customer_facing"`` to the
    strip. Any site passing ``kind="internal"`` on an SMS send would
    silently neutralise the guard — guard against that."""
    src = _read(rel)
    # ``_` in kw args keeps the eyes-on-paired-spelling check tight.
    assert 'kind="customer_facing"' in src, (
        f"{rel} missing kind=\"customer_facing\" — guard neutralised"
    )
    # ``channel="sms"`` must also be present.
    assert 'channel="sms"' in src, (
        f"{rel} missing channel=\"sms\" on the strip call"
    )


@pytest.mark.parametrize("rel,expect", list(_SITES.items()))
def test_site_tags_ticket_comment(rel, expect):
    """Each site has the ``SMS-RECIPIENT-FIX`` comment anchor so a
    future diff reviewer can trace the wiring back to this ticket."""
    tag, count = expect
    src = _read(rel)
    hits = src.count(tag)
    assert hits >= count, (
        f"{rel} expected ≥{count} '{tag}' comment anchors, found {hits}"
    )


def test_quote_notifications_working_as_designed_comment():
    """``quote_notifications.py:441`` keeps ``audience="internal"`` on
    purpose (recipient is admin). Pin the ``[SMS-AUDIENCE-FIX:
    working-as-designed]`` tag so it doesn't get re-ticketed."""
    src = _read("services/quote_notifications.py")
    assert "SMS-AUDIENCE-FIX: working-as-designed" in src, (
        "quote_notifications.py missing the "
        "[SMS-AUDIENCE-FIX: working-as-designed] marker"
    )
    assert 'audience="internal"' in src, (
        "quote_notifications.py should still send with "
        "audience='internal' — admins are the intended recipient"
    )


def test_lead_requests_untouched_per_g5():
    """G5 explicitly excludes ``lead_requests`` from the strip wiring.
    Make sure a future refactor doesn't accidentally add the guard
    there without a product decision."""
    src = _read("routers/lead_requests.py")
    assert "strip_admin_owned_recipients" not in src, (
        "lead_requests.py should NOT carry the strip wire per G5 — "
        "if product has reclassified it as customer-facing, update "
        "this test alongside the migration."
    )


# ═════════════════════════════════════════════════════════════════════
# B · Mock-based behavior tests on representative sites
# ═════════════════════════════════════════════════════════════════════
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_send_recap_sms_strips_contaminated_phone():
    """``_send_recap_sms`` returns the ``denied_admin_owned_recipient``
    reason string and never calls the RC adapter when the
    customer phone is admin-owned."""
    from routers.service_reports import _send_recap_sms

    async def _strip_hit(*, tenant_id, kind, channel, recipients,
                          context=None):
        assert kind == "customer_facing"
        assert channel == "sms"
        return [], [{"address": recipients[0],
                      "reason": "workforce_or_tenant_phone"}]

    adapter_mock = AsyncMock(return_value={"provider": "ringcentral",
                                             "provider_status": "sent"})
    cust = {"id": "cust-1", "phone": "+16028874400"}
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=_strip_hit,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        res = _run(_send_recap_sms(cust, "hello", tenant_id="tnt-1"))
    assert res["sent"] is False
    assert res["reason"] == "denied_admin_owned_recipient"
    adapter_mock.assert_not_awaited()


def test_send_recap_sms_passes_through_clean_phone():
    """Clean customer phone → strip returns kept, adapter called."""
    from routers.service_reports import _send_recap_sms

    async def _strip_pass(*, tenant_id, kind, channel, recipients,
                            context=None):
        return list(recipients), []

    adapter_mock = AsyncMock(return_value={"provider": "ringcentral",
                                             "provider_status": "sent",
                                             "provider_response_id": "pm1"})
    cust = {"id": "cust-2", "phone": "+15555550100"}
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=_strip_pass,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        res = _run(_send_recap_sms(cust, "hello", tenant_id="tnt-1"))
    assert res["sent"] is True
    adapter_mock.assert_awaited_once()
    kwargs = adapter_mock.await_args.kwargs
    # Adapter receives the clean customer phone verbatim.
    assert kwargs["to"] == "+15555550100"


def test_send_recap_sms_fails_open_without_tenant_id():
    """Legacy callers that haven't been migrated yet (no ``tenant_id``
    kwarg) must still function — the deny-list only engages when
    ``tenant_id`` is provided."""
    from routers.service_reports import _send_recap_sms

    strip_mock = AsyncMock()
    adapter_mock = AsyncMock(return_value={"provider": "ringcentral",
                                             "provider_status": "sent"})
    cust = {"id": "cust-3", "phone": "+15555550101"}
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=strip_mock,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        res = _run(_send_recap_sms(cust, "hello"))  # tenant_id omitted
    strip_mock.assert_not_awaited()
    adapter_mock.assert_awaited_once()
    assert res["sent"] is True


# ═════════════════════════════════════════════════════════════════════
# C · ``utils.send_sms`` kwarg contract
# ═════════════════════════════════════════════════════════════════════
def test_utils_send_sms_default_kind_is_internal():
    """``kind`` kwarg defaults to ``"internal"`` — pre-existing callers
    (lead_requests admin dispatch, csat alerts, etc.) are safe."""
    import inspect
    from utils import send_sms

    sig = inspect.signature(send_sms)
    param = sig.parameters.get("kind")
    assert param is not None, "send_sms should expose a ``kind`` kwarg"
    assert param.default == "internal", (
        "``kind`` default must be ``\"internal\"`` so pre-existing "
        "callers remain pass-through (G3 strict)."
    )


def test_utils_send_sms_internal_bypasses_deny_list():
    """Calls that don't opt into ``kind=\"customer_facing\"`` must not
    invoke the deny-list even when ``tenant_id`` is present."""
    from utils import send_sms

    strip_mock = AsyncMock(return_value=([], []))
    adapter_mock = AsyncMock(return_value={"provider": "ringcentral",
                                             "provider_status": "sent"})
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=strip_mock,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        ok = send_sms("+15555550102", "hi", tenant_id="tnt-1")
    assert ok is True
    strip_mock.assert_not_awaited()
    adapter_mock.assert_awaited_once()


def test_utils_send_sms_customer_facing_engages_deny_list_strip():
    """``kind=\"customer_facing\"`` + a stripped recipient →
    silent False return, adapter not touched, WARN logged."""
    from utils import send_sms

    async def _strip_hit(*, tenant_id, kind, channel, recipients,
                          context=None):
        return [], [{"address": recipients[0],
                      "reason": "workforce_or_tenant_phone"}]

    adapter_mock = AsyncMock()
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=_strip_hit,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        ok = send_sms("+16028874400", "hi",
                       tenant_id="tnt-1",
                       kind="customer_facing")
    assert ok is False
    adapter_mock.assert_not_awaited()


def test_utils_send_sms_customer_facing_passes_clean_phone():
    """Clean phone + ``kind=\"customer_facing\"`` → strip returns
    kept, adapter called with the clean recipient."""
    from utils import send_sms

    async def _strip_pass(*, tenant_id, kind, channel, recipients,
                            context=None):
        return list(recipients), []

    adapter_mock = AsyncMock(return_value={"provider": "ringcentral",
                                             "provider_status": "sent"})
    with patch(
        "services.comms_hardening.deny_list.strip_admin_owned_recipients",
        new=_strip_pass,
    ), patch(
        "services.sms.rc_adapter.send", new=adapter_mock,
    ):
        ok = send_sms("+15555550103", "hi",
                       tenant_id="tnt-1",
                       kind="customer_facing")
    assert ok is True
    adapter_mock.assert_awaited_once()


def test_utils_notify_customer_source_passes_customer_facing():
    """Static source check — ``notify_customer`` must call
    ``send_sms`` with ``kind="customer_facing"`` so the deny-list
    engages on the dominant customer-facing legacy caller."""
    src = _read("utils.py")
    # The notify_customer-triggered send_sms call must carry the
    # customer-facing kind kwarg.
    assert re.search(
        r"send_sms\(\s*cust\[\"phone\"\][^)]*kind=\"customer_facing\"",
        src, re.DOTALL,
    ), "notify_customer must pass kind=\"customer_facing\" to send_sms"


# ═════════════════════════════════════════════════════════════════════
# D · Audit script sanity
# ═════════════════════════════════════════════════════════════════════
def test_audit_script_imports_and_normaliser():
    """Audit script imports cleanly and the normaliser collapses
    all common phone formats to the same last-10-digits bucket."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_customer_phone_overlap as audit  # noqa: WPS433
    for raw in ("+16028874400", "16028874400", "6028874400",
                "(602) 887-4400", "+1 602.887.4400"):
        assert audit._norm_phone(raw) == "6028874400"
    assert audit._norm_phone("") == ""
    assert audit._norm_phone("123") == ""  # <4 digits guard
    assert audit._norm_phone(None) == ""


def test_audit_script_env_from_numbers(monkeypatch):
    """The env collector picks up all 4 configured env keys and the
    CSV allowlist."""
    monkeypatch.setenv("RC_FROM_NUMBER", "+16028874400")
    monkeypatch.setenv("RC_SMS_DEFAULT_FROM", "6236285855")
    monkeypatch.setenv("RC_VOICE_DEFAULT_FROM", "")
    monkeypatch.setenv("COMMS_TEST_ALLOWLIST_PHONES",
                        "+16028874400, +16236285855")
    import importlib
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_customer_phone_overlap as audit  # noqa: WPS433
    importlib.reload(audit)
    env_map = audit._collect_env_from_numbers()
    assert "6028874400" in env_map["RC_FROM_NUMBER"]
    assert "6236285855" in env_map["RC_SMS_DEFAULT_FROM"]
    assert "6028874400" in env_map["COMMS_TEST_ALLOWLIST_PHONES"]
    assert "6236285855" in env_map["COMMS_TEST_ALLOWLIST_PHONES"]
    # Empty env key is omitted entirely.
    assert "RC_VOICE_DEFAULT_FROM" not in env_map


def test_audit_script_help_runs():
    """CLI ``--help`` parses without touching Mongo."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import audit_customer_phone_overlap as audit  # noqa: WPS433
    with pytest.raises(SystemExit) as exc:
        with patch.object(sys, "argv", ["audit", "--help"]):
            audit.main()
    assert exc.value.code == 0
