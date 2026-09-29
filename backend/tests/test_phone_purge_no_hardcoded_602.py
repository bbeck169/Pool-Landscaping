"""Phase PHONE-PURGE · Feb-2026 — hardcoded phone-fallback guard.

Locks the intent of the phase: FOUR files must NOT carry the
plofv-internal number as a hardcoded fallback in any format the
downstream SMS / display code paths can consume.

Files under guard (do NOT expand this list without a matching
PHONE-PURGE follow-up phase — every entry here was cleaned up in
the PHONE-PURGE commit and MUST remain clean):

* ``services/leads_side_effects.py`` — internal lead-alert SMS.
* ``routers/customer_portal.py``     — portal service-request SMS.
* ``routers/workstream_service_log.py`` — door-hanger email footer.
* ``routers/tos_multi.py``           — TOS blast email footer.

The guard scans for every canonical rendering of the number:

* ``602-887-4400``
* ``602.887.4400``
* ``6028874400``          (also matches the ``+1`` E.164 form
                           since ``+16028874400`` contains it)
* ``(602) 887-4400``
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_SCOPE_FILES = [
    "services/leads_side_effects.py",
    "routers/customer_portal.py",
    "routers/workstream_service_log.py",
    "routers/tos_multi.py",
]

_BACKEND_ROOT = Path("/app/backend")

_FORBIDDEN_PATTERNS = [
    "602-887-4400",
    "602.887.4400",
    "6028874400",           # covers ``+16028874400`` as a substring
    "(602) 887-4400",
]


@pytest.mark.parametrize("relpath", _SCOPE_FILES)
def test_no_hardcoded_602_number(relpath: str):
    """Every canonical rendering of the plofv-internal number must
    be absent from the file's source (comments included)."""
    src = (_BACKEND_ROOT / relpath).read_text(encoding="utf-8")
    hits = {p: src.count(p) for p in _FORBIDDEN_PATTERNS if p in src}
    assert not hits, (
        f"{relpath} still contains hardcoded plofv-internal phone "
        f"literals: {hits}"
    )


def test_default_internal_sms_constant_removed():
    """``_DEFAULT_INTERNAL_SMS`` used to hold the hardcoded fallback
    in ``services/leads_side_effects.py``. PHONE-PURGE removed it —
    it must not exist as a module-level name anymore."""
    from services import leads_side_effects as mod
    assert not hasattr(mod, "_DEFAULT_INTERNAL_SMS"), (
        "_DEFAULT_INTERNAL_SMS constant still exists in "
        "services.leads_side_effects — Phase PHONE-PURGE requires "
        "the module to source the SMS recipient from tenant "
        "settings only."
    )


def test_service_request_sms_fallback_constant_removed():
    """``_SERVICE_REQUEST_SMS_FALLBACK`` used to hold the hardcoded
    fallback in ``routers/customer_portal.py``. PHONE-PURGE removed
    it — it must not exist as a module-level name anymore."""
    from routers import customer_portal as mod
    assert not hasattr(mod, "_SERVICE_REQUEST_SMS_FALLBACK"), (
        "_SERVICE_REQUEST_SMS_FALLBACK constant still exists in "
        "routers.customer_portal — Phase PHONE-PURGE requires the "
        "resolver to return \"\" when the tenant has no configured "
        "SMS recipient."
    )


def test_resolve_service_request_sms_returns_empty_when_unset():
    """``_resolve_service_request_sms(tenant)`` must return ``""``
    when the tenant has no ``settings.notifications.service_request_sms``
    configured — the PHONE-PURGE contract that lets the send path
    short-circuit rather than dial a stale internal number."""
    from routers.customer_portal import _resolve_service_request_sms
    # Empty tenant → empty result.
    assert _resolve_service_request_sms({}) == ""
    # Tenant with a settings tree but no service_request_sms → empty.
    assert _resolve_service_request_sms(
        {"settings": {"notifications": {}}},
    ) == ""
    # Tenant WITH a configured number → verbatim passthrough.
    assert _resolve_service_request_sms(
        {"settings": {"notifications": {
            "service_request_sms": "+15555550100"}}},
    ) == "+15555550100"


def test_leads_side_effects_tenant_config_returns_empty_sms_when_unset():
    """Same contract on ``services.leads_side_effects._tenant_config``
    — the SMS branch must see an empty string when the tenant has no
    ``internal_lead_notifications.sms`` configured so it can short-
    circuit rather than fall back to a hardcoded plofv number."""
    from services.leads_side_effects import _tenant_config
    from unittest.mock import AsyncMock, patch
    import asyncio

    async def _run(tenant_doc):
        with patch("services.leads_side_effects.db") as _db:
            _db.tenants = AsyncMock()
            _db.tenants.find_one = AsyncMock(return_value=tenant_doc)
            return await _tenant_config("t-1")

    # No ``internal_lead_notifications`` at all → empty SMS.
    cfg = asyncio.get_event_loop().run_until_complete(_run({}))
    assert cfg["sms"] == ""

    # Empty ``internal_lead_notifications`` → empty SMS.
    cfg = asyncio.get_event_loop().run_until_complete(
        _run({"internal_lead_notifications": {}}),
    )
    assert cfg["sms"] == ""

    # Explicit ``sms`` → verbatim passthrough.
    cfg = asyncio.get_event_loop().run_until_complete(
        _run({"internal_lead_notifications":
              {"sms": "+15555550100"}}),
    )
    assert cfg["sms"] == "+15555550100"


def test_forbidden_pattern_strings_are_absent_via_regex():
    """Belt + braces: run a regex over the four files that also
    catches the ``+16028874400`` E.164 form (the ``6028874400``
    substring check above catches it, but this regex is explicit
    about the plus-sign form so a future maintainer sees the
    intent when they read the guard file)."""
    e164 = re.compile(r"\+16028874400")
    for relpath in _SCOPE_FILES:
        src = (_BACKEND_ROOT / relpath).read_text(encoding="utf-8")
        assert not e164.search(src), (
            f"{relpath} still contains the E.164 form ``+16028874400``"
        )
