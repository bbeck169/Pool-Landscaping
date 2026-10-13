"""SMS-ALLOWLIST-FIX · Feb-2026 — regression guard against the
``allow_off_allowlist`` kwarg being re-added to the quote-
notifications SMS send path.

Background (critical context — the receipt documents this at
length):

* ``quote_notifications._dispatch_notifications`` historically
  passed ``allow_off_allowlist=True`` to BOTH the ``_send_email``
  and ``_send_sms`` calls.  For email the kwarg is legitimate —
  ``services.email.resend_adapter.send`` accepts it as a
  Phase-K30 gate-bypass flag.
* For SMS the kwarg was mis-copied from the email pattern.  The
  SMS adapter at ``services.sms.rc_adapter.RcSmsAdapter.send``
  does NOT accept it; passing the kwarg raised a ``TypeError``
  that the surrounding ``try/except Exception`` silently
  swallowed and logged as ``status="failed"``.  Net effect:
  **no quote-notification SMS ever reached a recipient**.
* The fix removes the kwarg from the SMS call site only.  This
  ENABLES SMS sending for the first time — a behaviour change,
  not an allowlist-bypass correction.

Two guards here, both targeting ``quote_notifications.py``:

1. Source-text guard — the file source MUST NOT contain the
   literal ``allow_off_allowlist`` anywhere inside the SMS
   call-site slice (so a copy/paste regression lands this test
   loudly, not silently).
2. Behavioural guard — a mocked ``_send_sms`` captures every
   kwarg the dispatcher passes and the test asserts
   ``"allow_off_allowlist"`` is absent.  The EMAIL mock in the
   same test asserts the kwarg IS still passed on the email
   call (regression check for the sibling branch).
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import services.quote_notifications as qn


def _run(coro):
    """Mirrors the ``_run`` wrapper used by sibling async tests
    (see ``test_phase39_visit_recap.py``, ``test_auto_visit_email_
    address.py``).  The codebase does not use pytest-asyncio;
    coroutines are driven via a locally-scoped event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════
# Guard 1 — source-text invariant
# ═════════════════════════════════════════════════════════════════
def _sms_call_slice() -> str:
    """Return the source-text slice that spans the ``_send_sms``
    call site inside ``_dispatch_notifications`` so the guard only
    checks the SMS branch (the sibling EMAIL branch still legally
    passes the kwarg)."""
    src = Path(qn.__file__).read_text()
    # The dispatcher body carries exactly ONE ``_send_sms(`` call;
    # grab from that opening paren through the matching ``)`` on
    # the line that still carries ``or {}``.
    m = re.search(r"resp = await _send_sms\((.*?)\) or \{\}", src, re.DOTALL)
    assert m, "Expected a single _send_sms call inside quote_notifications"
    return m.group(1)


def test_sms_call_site_source_does_not_pass_allow_off_allowlist():
    slice_src = _sms_call_slice()
    # Hard assertion — must not reappear via a copy/paste.
    assert "allow_off_allowlist" not in slice_src, (
        "SMS-ALLOWLIST-FIX regression: the quote-notifications SMS "
        "call site must NOT pass allow_off_allowlist (RcSmsAdapter."
        "send does not accept the kwarg; it raises TypeError which "
        "the surrounding try/except silently swallows → no SMS is "
        "ever sent).  See SMS-ALLOWLIST-FIX receipt."
    )


def test_email_call_site_source_still_passes_allow_off_allowlist():
    """The sibling EMAIL branch legitimately passes
    ``allow_off_allowlist=True`` (Phase-K30 gate bypass).  The fix
    must not have swept away the email kwarg by accident."""
    src = Path(qn.__file__).read_text()
    m = re.search(r"resp = await _send_email\((.*?)\) or \{\}", src, re.DOTALL)
    assert m, "Expected a single _send_email call inside quote_notifications"
    assert "allow_off_allowlist=True" in m.group(1), (
        "SMS-ALLOWLIST-FIX side-effect regression: the EMAIL "
        "branch's allow_off_allowlist=True kwarg must stay intact "
        "(email adapter supports it; only the SMS adapter did not)."
    )


# ═════════════════════════════════════════════════════════════════
# Guard 2 — behavioural (mocked call captures kwargs)
# ═════════════════════════════════════════════════════════════════
def test_sms_dispatch_never_passes_allow_off_allowlist_kwarg():
    """Drive ``notify_quote_decision`` end-to-end against mocked
    email + SMS adapters and inspect every kwarg captured on the
    SMS mock.  ``allow_off_allowlist`` must be absent from every
    call; the email mock may legitimately carry it."""
    captured_sms_kwargs: list[dict] = []
    captured_email_kwargs: list[dict] = []

    async def _fake_send_sms(**kwargs):
        captured_sms_kwargs.append(kwargs)
        return {"status": "sent", "provider_id": "fake-sms-1"}

    async def _fake_send_email(**kwargs):
        captured_email_kwargs.append(kwargs)
        return {"status": "sent", "provider_id": "fake-email-1"}

    # Patch the dispatcher's downstream collaborators:
    #   * SMS/email adapters at the import source (dispatcher
    #     does a lazy ``from services.sms.rc_adapter import send
    #     as _send_sms`` at function scope — line ~371).
    #   * ``resolve_recipients`` so the test doesn't need a
    #     tenant row.
    #   * Rate-limiter + logger — side-effect free in a unit test.
    #   * ``render_email`` + ``render_sms`` + the branding wrap —
    #     short-circuit the body-composition layer so this test
    #     only exercises the adapter-call shape.
    tenant = {"id": "tenant-1",
              "lead_notification_recipients": [
                  {"email": "ops@example.com", "phone": "+15555550123"},
              ]}
    doc = {"id": "quote-1", "doc_type": "quote",
           "customer_name": "Jamie", "total": 123}

    with patch("services.sms.rc_adapter.send",
                new=AsyncMock(side_effect=_fake_send_sms)), \
         patch("services.email.resend_adapter.send",
                new=AsyncMock(side_effect=_fake_send_email)), \
         patch("services.quote_notifications._is_rate_limited",
                new=AsyncMock(return_value=False)), \
         patch("services.quote_notifications._log_send",
                new=AsyncMock(return_value=None)), \
         patch("services.quote_notifications.render_email",
                new=AsyncMock(return_value=(
                    "Your quote is ready",
                    "<p>hi</p>",
                    "hi",
                ))), \
         patch("services.quote_notifications.render_sms",
                new=AsyncMock(return_value="Hi — your quote is ready.")), \
         patch("services.email.theming.wrap_html_in_shell",
                return_value="<p>hi</p>"), \
         patch("services.tenants.business_settings.get_effective_business_settings",
                new=AsyncMock(return_value={})):
        result = _run(qn.notify_quote_decision(
            tenant=tenant, doc=doc, event="quote_accepted",
        ))

    # Behavioural assertions.
    assert captured_sms_kwargs, (
        "SMS adapter was never called — the dispatcher skipped the "
        "SMS branch (rate limit? empty recipients?). The behavioural "
        "guard needs an SMS call to introspect."
    )
    for call in captured_sms_kwargs:
        assert "allow_off_allowlist" not in call, (
            f"SMS adapter call carried a forbidden allow_off_allowlist "
            f"kwarg: {call!r}.  See SMS-ALLOWLIST-FIX receipt."
        )
    # The dispatch's own result dict reports success for the SMS
    # path post-fix (previously 'failed' due to the TypeError).
    assert result["sms"]["sent"] == 1, (
        f"Expected the SMS branch to report sent=1 after removing "
        f"the crashing kwarg; got {result['sms']!r}."
    )
    assert result["sms"]["failed"] == 0

    # Sibling-branch regression — the EMAIL mock must still receive
    # allow_off_allowlist=True (fix only touched the SMS call).
    assert captured_email_kwargs, "Email adapter was never called"
    assert any(c.get("allow_off_allowlist") is True
               for c in captured_email_kwargs), (
        "EMAIL branch no longer passes allow_off_allowlist=True; "
        "the fix was supposed to touch SMS only."
    )
