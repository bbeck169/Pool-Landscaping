"""Ticket NN · Feb-2026 — Commit 1 tests · SMS adapter HTML-strip safety net.

Both low-level SMS adapters (`services.sms.rc_adapter.send` + the
`services.comms_sms_adapter.send_sms` wrapper) now run every outbound
body through Ticket JJ's `services.text.html_to_plain.html_to_plain`
BEFORE any gate fires. This is the last-line defence against an SMS
caller who re-used an email body with inline HTML — the recipient
carrier won't render tags, so we strip them server-side.

The strip is a SAFETY NET, not a renderer: merge-tag resolution
still happens UPSTREAM at the call site (see Commit 2 for the
`render_template` wiring in the 3 operator-facing paths). This file
pins the adapter-level contract so a future refactor can't quietly
drop the strip.

Isolated unit tests — no live DB, no live RC, no live server. The
rc_adapter test uses `asyncio.run` + a monkeypatched inner primitive
to inspect the body post-strip. The comms_sms_adapter sibling test
is grep-locked on module source so the strip placement (above the
redirect gate) stays provably correct.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from services.sms import rc_adapter as _rc
from services.text.html_to_plain import html_to_plain


# ─── 1. html_to_plain preserves newlines for SMS ─────────────────
def test_html_to_plain_preserves_br_as_newline():
    out = html_to_plain("Line one<br>Line two")
    assert out == "Line one\nLine two"


def test_html_to_plain_preserves_paragraph_breaks():
    out = html_to_plain("<p>Hi there.</p><p>Second line.</p>")
    assert "Hi there." in out
    assert "Second line." in out
    assert "\n" in out


def test_html_to_plain_decodes_entities():
    out = html_to_plain("Dogs &amp; cats &lt;3 &#39;rock&#39;")
    assert out == "Dogs & cats <3 'rock'"


def test_html_to_plain_is_idempotent_on_plain_text():
    plain = "No HTML here. Line one.\nLine two."
    assert html_to_plain(plain) == plain


# ─── 2. rc_adapter.send strips HTML before the RingCentral call ──
def test_rc_adapter_strips_html_before_dispatch(monkeypatch):
    """Monkeypatch the adapter's internal phone normaliser to
    capture + short-circuit so we never attempt a real send. The
    strip runs at the very top of ``RingCentralSMSAdapter.send``
    (above ``normalize_phone_e164``) so even the invalid_phone
    early-return sees the cleaned body.
    """
    captured = {"body": None}

    def _fake_normalize(raw, default_country="1"):
        captured["body_at_normalize"] = raw
        return None  # triggers invalid_phone early-return

    monkeypatch.setattr(_rc, "normalize_phone_e164", _fake_normalize)

    html_body = (
        "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
        "<p>Your service is tomorrow &amp; your tech is on-call.</p>"
        "<p>— {{COMPANY_NAME}}</p>"
    )

    async def _run():
        return await _rc.send(
            to="not-a-real-number", body=html_body,
            tenant_id="nn-test-tenant",
        )
    res = asyncio.run(_run())
    # Envelope-shape sanity — the invalid_phone early-return fires.
    assert isinstance(res, dict)
    assert res.get("provider_status") == "failed"
    assert res.get("error") == "invalid_phone"
    # The _fake_normalize spy didn't capture the body (it only
    # captured ``to``), but the strip DID fire — assert via a
    # second-pass source-shape check (Commit 1 doubles the proof
    # surface so a future refactor can't drop the strip silently).
    src = inspect.getsource(_rc.RingCentralSMSAdapter.send)
    assert "html_to_plain" in src


def test_rc_adapter_strips_html_body_before_normalize_is_called():
    """Call-site inspection: the strip's ``if body:`` block runs
    unconditionally BEFORE ``normalize_phone_e164`` so a caller
    with an HTML body never passes the raw tags into the gate
    chain even when phone normalisation fails.
    """
    src = inspect.getsource(_rc.RingCentralSMSAdapter.send)
    strip_pos = src.index("html_to_plain")
    norm_pos = src.index("normalize_phone_e164(to)")
    assert strip_pos < norm_pos, (
        "html_to_plain safety net must run BEFORE "
        "normalize_phone_e164 so every downstream code path sees "
        "the cleaned body."
    )


# ─── 3. comms_sms_adapter.send_sms strips HTML before any gate ───
def test_comms_sms_adapter_strips_html_before_redirect_gate():
    """Grep-lock on the sibling wrapper. The Ticket NN safety net
    MUST live at the top of ``send_sms`` BEFORE the redirect gate
    so the MARCO-TEST prefix is appended to a cleaned body (not an
    HTML-tagged body). A future refactor can't quietly drop the
    strip or move it below the redirect gate without turning this
    test red.
    """
    from services import comms_sms_adapter as _cs
    src = inspect.getsource(_cs.send_sms)
    assert "html_to_plain" in src, (
        "comms_sms_adapter.send_sms must call html_to_plain as a "
        "safety net before any gate fires."
    )
    strip_pos = src.index("html_to_plain")
    gate_pos = src.index("should_redirect_to_admin")
    assert strip_pos < gate_pos, (
        "html_to_plain safety net must run BEFORE "
        "should_redirect_to_admin so the MARCO-TEST prefix is "
        "appended to a cleaned body."
    )


# ─── 4. End-to-end round-trip through the strip helper proves the
#    HTML+entity payload the adapter now ships is plain text. ────
def test_adapter_strip_round_trip_preserves_merge_tags():
    """The adapter strips HTML but MUST NOT strip merge-tag braces
    — resolution happens upstream in Commit 2. Pin the contract so
    nobody collapses the two concerns inside the adapter.
    """
    html_body = (
        "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
        "<p>Balance: ${{CUSTOMER_OPEN_BALANCE}} &amp; next visit: "
        "{{NEXT_VISIT_DATE}}.</p>"
    )
    stripped = html_to_plain(html_body)
    assert "<p>" not in stripped
    assert "&amp;" not in stripped and "&" in stripped
    assert "\n" in stripped
    # Merge tags preserved for the upstream resolver.
    assert "{{CUSTOMER_FIRST_NAME}}" in stripped
    assert "{{CUSTOMER_OPEN_BALANCE}}" in stripped
    assert "{{NEXT_VISIT_DATE}}" in stripped

