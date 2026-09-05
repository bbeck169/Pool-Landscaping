"""Feb 2026 · Shared builder for customer-facing "Pay Now" URLs.

Extracted from ``routers/payments_stripe_live.py::_issue_invoice_magic_token``
so email senders (``emailer.py``, ``routers/dunning.py``, drip campaigns)
can produce a public magic-link URL without importing FastAPI router
internals.

The resulting URL is public-safe: no session cookie needed. It points
at ``{APP_PUBLIC_URL}/pay/invoice/{invoice_id}?token=<jwt>`` where the
JWT carries ``sub=invoice_pay``, ``invoice_id``, ``tenant_id`` and a
30-day expiry. The frontend route ``/pay/invoice/:id`` is registered
OUTSIDE ``<AppLayout>`` (see ``frontend/src/App.js``) so opening this
link in an incognito browser lands directly on the Stripe payment
sheet — no login redirect.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from config import JWT_ALGO, JWT_SECRET, logger


def issue_invoice_magic_token(invoice_id: str, tenant_id: str,
                                days: int = 30) -> str:
    """Mint a 30-day magic-link JWT for a single invoice.

    Kept identical to ``payments_stripe_live._issue_invoice_magic_token``
    so tokens minted here verify cleanly via ``_verify_invoice_magic_token``.
    """
    payload = {
        "sub": "invoice_pay",
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=days),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def build_pay_now_url(invoice_id: str, tenant_id: str,
                        base_url: Optional[str] = None,
                        days: int = 30,
                        src: Optional[str] = None) -> str:
    """Return the full public Pay Now URL for a given invoice.

    Falls back to ``os.environ['APP_PUBLIC_URL']`` when ``base_url`` is
    omitted. Never raises — if the base URL is unset we log a warning
    and return an empty string; callers should treat that as "no pay
    link available" and omit the CTA rather than emailing a broken
    relative URL.

    Phase K47 · Feb-2026 — the optional ``src`` parameter is appended
    to the URL query string (``&src=email|sms|link``) so the public
    magic-link viewer can stamp the correct source on the resulting
    ``invoice_views`` record. Any value passed through here is
    trusted — the receiving endpoint normalises against a fixed
    whitelist before storage.
    """
    base = (base_url or os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")
    if not base:
        logger.warning(
            "[pay_link] APP_PUBLIC_URL not set — Pay Now URL will be empty for "
            f"invoice={invoice_id}"
        )
        return ""
    token = issue_invoice_magic_token(invoice_id, tenant_id, days=days)
    url = f"{base}/pay/invoice/{invoice_id}?token={token}"
    if src:
        url = f"{url}&src={src}"
    return url
