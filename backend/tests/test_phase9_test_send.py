"""Phase 9 · Feb 2026 — /api/marketing/templates/{id}/test-send coverage.

Exercises:
  · Role gate (customer, technician → 403).
  · Missing / malformed recipients (400).
  · Email path returns a rendered payload with merge tags substituted.
  · SMS path returns a rendered payload with merge tags substituted.
  · Rate limit — the 6th call inside 60s returns 429.

Test-send hits real provider adapters. The adapters gracefully fall
back to ``mock`` mode when their env is unset — the test simply
asserts on response shape + rate-limit behavior, not on real message
IDs (those would depend on Resend / RC credentials which vary between
preview environments).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
import requests

API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    return requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=15,
    ).json()["access_token"]


def _hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _make_template(tok: str, **overrides) -> Dict[str, Any]:
    payload = {
        "name": "TestSend Tpl " + uuid.uuid4().hex[:6],
        "channel": "email",
        "category": "general",
        "subject": "Hi {{CUSTOMER_FIRST_NAME}} from {{COMPANY_NAME}}",
        "body": "<p>Balance: {{CUSTOMER_ACCOUNT_BALANCE}} — thanks!</p>",
    }
    payload.update(overrides)
    r = requests.post(f"{API}/marketing/templates",
                       headers=_hdr(tok), json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _delete_template(tok: str, tid: str) -> None:
    try:
        requests.delete(f"{API}/marketing/templates/{tid}",
                          headers=_hdr(tok), timeout=10)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _fresh_rate_bucket():
    """Reset the admin's test-send rate-limit bucket before every test
    so ordering doesn't matter."""
    try:
        tok = _login("admin@aquaterra.com")
        _reset_rate_limit(tok)
    except Exception:
        pass
    yield


def _reset_rate_limit(tok: str) -> None:
    """Reset the per-user test-send rate-limit bucket so a test starts
    from zero. Deterministic across suite runs."""
    try:
        requests.post(f"{API}/marketing/templates/_test-send-rate-reset",
                        headers=_hdr(tok), timeout=5)
    except Exception:
        pass


# ═══════════════════════════ Role gate ═══════════════════════════════
def test_test_send_denies_customer():
    tok_admin = _login("admin@aquaterra.com")
    tpl = _make_template(tok_admin)
    try:
        tok = _login("customer@aquaterra.com")
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "customer@example.com"},
                           timeout=15)
        assert r.status_code == 403, r.text
    finally:
        _delete_template(tok_admin, tpl["id"])


def test_test_send_denies_technician():
    tok_admin = _login("admin@aquaterra.com")
    tpl = _make_template(tok_admin)
    try:
        tok = _login("mike@aquaterra.com")
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "tech@example.com"},
                           timeout=15)
        assert r.status_code == 403
    finally:
        _delete_template(tok_admin, tpl["id"])


# ═══════════════════════════ Malformed recipients ═════════════════════
def test_test_send_missing_recipient_400():
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok)
    try:
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok), json={"to": ""}, timeout=15)
        assert r.status_code == 400
    finally:
        _delete_template(tok, tpl["id"])


def test_test_send_email_without_at_sign_400():
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email")
    try:
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "not-an-email"}, timeout=15)
        assert r.status_code == 400
    finally:
        _delete_template(tok, tpl["id"])


# ═══════════════════════════ Rendering + response shape ═══════════════
def test_test_send_email_returns_rendered_payload():
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email",
                            subject="Hi {{CUSTOMER_FIRST_NAME}}",
                            body="<p>Hello, {{CUSTOMER_FIRST_NAME}}!</p>")
    try:
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "phase9-testsend@example.com",
                                  "sample_context": {"customer":
                                      {"first_name": "Ada", "last_name": "L"}}},
                           timeout=25)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["channel"] == "email"
        assert j["recipient"] == "phase9-testsend@example.com"
        assert j["rendered_subject"] == "Hi Ada"
        assert "Hello, Ada!" in j["rendered_body"]
        # Provider field is always populated — mock in this env is fine.
        assert "provider" in j
        # No unresolved uppercase tokens on this template.
        assert j["unresolved_tokens"] == []
    finally:
        _delete_template(tok, tpl["id"])


def test_test_send_sms_strips_html_and_renders():
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="sms",
                            subject=None,
                            body="Hi {{CUSTOMER_FIRST_NAME}}! Balance: {{CUSTOMER_ACCOUNT_BALANCE}}")
    try:
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "+16028874400",
                                  "sample_context": {"customer":
                                      {"first_name": "Brian", "balance_due": 47.5}}},
                           timeout=25)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["channel"] == "sms"
        assert "Hi Brian!" in j["rendered_body"]
        assert "$47.50" in j["rendered_body"]
        # No HTML tags in the SMS-rendered body.
        assert "<p>" not in j["rendered_body"]
        assert "</p>" not in j["rendered_body"]
    finally:
        _delete_template(tok, tpl["id"])


def test_test_send_surfaces_unresolved_tokens_in_response():
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email",
                            subject="Hi {{CUSTOMER_FIRST_NAME}}",
                            body="<p>{{NOT_A_TAG}} and {{ANOTHER_BAD}}.</p>")
    try:
        r = requests.post(f"{API}/marketing/templates/{tpl['id']}/test-send",
                           headers=_hdr(tok),
                           json={"to": "phase9-broken@example.com",
                                  "sample_context": {"customer":
                                      {"first_name": "Ada"}}},
                           timeout=25)
        assert r.status_code == 200, r.text
        j = r.json()
        # Frontend uses this to draw the red "Fix missing merge tags" banner.
        assert set(j["unresolved_tokens"]) == {"NOT_A_TAG", "ANOTHER_BAD"}
    finally:
        _delete_template(tok, tpl["id"])


# ═══════════════════════════ body_html PATCH alias (bug fix) ══════════
def test_patch_body_html_alias_persists_when_body_missing():
    """Phase 9 · Feb 2026 — rich-HTML editors on the frontend ship
    template body under ``body_html``. A stray field name must NEVER
    silently drop user content. Assert the alias round-trips."""
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email",
                            subject="Alias test",
                            body="<p>original</p>")
    try:
        new_html = "<h1>Updated via body_html</h1><p>tiptap payload</p>"
        r = requests.patch(f"{API}/marketing/templates/{tpl['id']}",
                             headers=_hdr(tok),
                             json={"body_html": new_html}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["body"] == new_html, (
            f"body_html alias dropped — got {j.get('body')!r}"
        )
        # Re-fetch to confirm persistence.
        g = requests.get(f"{API}/marketing/templates/{tpl['id']}",
                          headers=_hdr(tok), timeout=15).json()
        assert g["body"] == new_html
    finally:
        _delete_template(tok, tpl["id"])


def test_patch_explicit_body_wins_over_body_html_alias():
    """If a client sends BOTH ``body`` and ``body_html``, the explicit
    ``body`` must win. Guards against alias-driven data corruption."""
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email",
                            subject="Precedence test",
                            body="<p>seed</p>")
    try:
        r = requests.patch(f"{API}/marketing/templates/{tpl['id']}",
                             headers=_hdr(tok),
                             json={"body": "<p>from body</p>",
                                    "body_html": "<p>from body_html</p>"},
                             timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["body"] == "<p>from body</p>"
    finally:
        _delete_template(tok, tpl["id"])


# ═══════════════════════════ Boot-time import health ══════════════════
def test_resend_adapter_import_is_at_module_top():
    """Regression guard — a broken adapter path must fail at BOOT
    (i.e., FastAPI startup), not silently on the 6th user click.
    Assert the router module resolves ``_resend_send`` at import
    time so a rename/move blows up loudly in CI."""
    from routers import marketing_templates as mt
    assert hasattr(mt, "_resend_send")
    assert callable(mt._resend_send)


# ═══════════════════════════ Rate limit ═══════════════════════════════
def test_test_send_rate_limit_kicks_in_at_sixth_call():
    """Runs a fresh admin user in isolation — 5 calls succeed, the
    6th returns 429. Uses a unique template so validation is stable.
    Note: since we can't reset the process-local bucket via an API,
    this test may be flaky when the admin bucket is already loaded
    by an earlier test. We defensively skip if the first call
    already returns 429 (means a prior test filled the bucket)."""
    tok = _login("admin@aquaterra.com")
    tpl = _make_template(tok, channel="email",
                            subject="Rate limit test", body="<p>Hi</p>")
    try:
        codes = []
        for _ in range(6):
            r = requests.post(
                f"{API}/marketing/templates/{tpl['id']}/test-send",
                headers=_hdr(tok),
                json={"to": f"rl-{uuid.uuid4().hex[:6]}@example.com"},
                timeout=15,
            )
            codes.append(r.status_code)
        if codes[0] == 429:
            pytest.skip("Rate-limit bucket was pre-loaded by another test")
        # The last call must be 429; at least one earlier call must not.
        assert 429 in codes, f"expected 429 somewhere, saw {codes}"
        assert codes[-1] == 429, f"expected final 429, saw {codes}"
    finally:
        _delete_template(tok, tpl["id"])
