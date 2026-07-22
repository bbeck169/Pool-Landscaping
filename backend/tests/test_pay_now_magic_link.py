"""Feb 2026 · Pay-Now magic-link regression coverage.

The customer-facing invoice email must contain a URL that (a) is on
the PUBLIC ``/pay/invoice/:id`` route and (b) carries a valid magic
JWT that decodes to the correct invoice + tenant. Any other shape
bounces the recipient through the app login page instead of the
Stripe payment sheet — see the customer-reported bug on
2aee9222-4480-40b8-a8f8-38fc25eae676.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]


def _extract_href(html: str) -> str:
    m = re.search(r'href="([^"]+)"', html or "")
    return m.group(1) if m else ""


# ═══════════════════════════ Unit tests ═══════════════════════════════
def test_pay_now_url_is_public_magic_link_and_decodes():
    """Emailer must emit a URL of the form
    ``{APP_PUBLIC_URL}/pay/invoice/<id>?token=<jwt>``. The JWT must
    decode via the same verifier the /full-magic endpoint uses."""
    from emailer import _reminder_html
    from routers.payments_stripe_live import _verify_invoice_magic_token

    inv_id = f"phase-pay-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    inv = {"id": inv_id, "tenant_id": tenant_id,
             "title": "Regression test", "total": 100.0, "amount_paid": 0.0}

    html = _reminder_html(inv, "Regression Buyer")
    href = _extract_href(html)
    assert href, "no href in reminder email"
    assert "/pay/invoice/" in href, f"URL missing /pay/invoice/: {href}"
    # Query must include a valid token.
    parsed = urlparse(href)
    token = parse_qs(parsed.query).get("token", [""])[0]
    assert token, f"no token in query string: {href}"

    payload = _verify_invoice_magic_token(token)
    assert payload["sub"] == "invoice_pay"
    assert payload["invoice_id"] == inv_id
    assert payload["tenant_id"] == tenant_id


def test_pay_now_url_never_uses_authenticated_portal_path():
    """The old broken URL was just APP_PUBLIC_URL or /portal/invoices/…/pay
    — both hit the auth wall. Neither may appear in the reminder
    email body."""
    from emailer import _reminder_html
    inv = {"id": "smoke", "tenant_id": "smoke",
             "title": "Smoke", "total": 1.0, "amount_paid": 0.0}
    html = _reminder_html(inv, "Smoke")
    href = _extract_href(html)
    assert "/portal/invoices/" not in href
    # Base-URL-only pay link redirects to login; reject it.
    assert href.rstrip("/") != (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")


def test_pay_link_builder_empty_when_base_url_missing(monkeypatch):
    from services.pay_link_builder import build_pay_now_url
    monkeypatch.setenv("APP_PUBLIC_URL", "")
    url = build_pay_now_url("inv-x", "tenant-x", base_url="")
    assert url == ""


def test_pay_link_builder_token_expiry_default_30_days():
    from services.pay_link_builder import issue_invoice_magic_token
    from routers.payments_stripe_live import _verify_invoice_magic_token
    import time
    tok = issue_invoice_magic_token("inv-y", "tenant-y")
    payload = _verify_invoice_magic_token(tok)
    delta_seconds = int(payload["exp"]) - int(time.time())
    # Expiry should be ~30 days (allow 60s of drift).
    assert 29 * 86400 - 60 < delta_seconds < 30 * 86400 + 60, delta_seconds


def test_dunning_fallback_uses_public_magic_link():
    """When Stripe PaymentLink is disabled/unavailable the dunning
    scanner previously fell back to ``/portal/invoices/{id}/pay`` — a
    logged-in-only path. Verify the new fallback goes through the
    public magic-link builder instead."""
    from routers.dunning import _payment_link_for

    inv_id = f"phase-pay-dun-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    inv = {"id": inv_id, "tenant_id": tenant_id,
             "title": "Fallback test", "total": 42.0}
    settings = {"stripe_payment_link_enabled": False}
    url = asyncio.get_event_loop().run_until_complete(
        _payment_link_for(inv, settings)
    )
    assert "/pay/invoice/" in url, f"unexpected URL: {url}"
    assert "/portal/invoices/" not in url
    assert "token=" in url
