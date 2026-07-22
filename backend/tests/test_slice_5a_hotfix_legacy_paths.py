"""Phase 5A hot-fix · Feb 2026 — legacy Stripe/RingCentral consolidation.

Guardrails
==========
1. **No direct SDK instantiation outside the shipped adapters.** Any
   ``twilio.rest.Client(`` or ``stripe.PaymentIntent.create`` call
   outside the shipped adapters + Phase 4B routers is a regression.
   Phase 7B (Feb 2026) fully removed Twilio; any lingering
   ``import twilio`` is now a regression too.
2. **The invoice Pay Now button routes through Phase 4B.** Hitting
   ``POST /api/payments/create-payment-intent`` for the seeded Brian
   Beckman invoice must NEVER return ``{reason: "stripe_error"}`` — it
   must return either a 200 client_secret (LIVE keys accepted by
   Stripe), a 400 "not payable" (draft invoice), or a 502
   AuthenticationError body from the Phase 4B endpoint. Anything else
   means the legacy path re-emerged.
3. **Invoice-SMS uses the shipped adapter.** Hitting
   ``POST /api/invoices/{iid}/send-sms`` must funnel through
   ``services/sms/rc_adapter.send`` (RingCentral). The
   ``sms-not-configured`` sentinel is only allowed when the adapter is
   in mock mode; never when RC env is populated.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import requests

API = "http://localhost:8001/api"
BACKEND_ROOT = Path("/app/backend")


# ─── Grep-based guardrail #1 — no direct SDK instantiation outside allow-list
_ADAPTER_ALLOW_LIST = {
    "services/sms/rc_adapter.py",            # Phase 7B — RingCentral SMS adapter
    "routers/payments_stripe_live.py",       # Phase 4B PaymentIntent + refund
    "routers/stripe_webhooks_live.py",       # Phase 4B webhook handler
    # Legacy admin surfaces still need direct SDK access — grandfathered:
    "routers/stripe_admin.py",               # /api/stripe/health, /webhook (Phase 53)
    "routers/stripe_payments.py",            # /api/stripe/payments admin reconciliation
    "routers/customer_portal.py",            # ACH SetupIntent + Financial Connections
    "routers/dunning.py",                    # Stripe PaymentLink for reminder emails
    "services/stripe_client.py",             # module-level SDK loader
}


def _grep_direct_sdk_calls() -> list[tuple[str, int, str]]:
    """Returns list of (relative_path, line_no, matched_text) where a
    forbidden direct SDK call is found."""
    findings: list[tuple[str, int, str]] = []
    patterns = [
        # Twilio direct client construction
        re.compile(r"^\s*from\s+twilio\.rest\s+import\s+Client"),
        re.compile(r"\btwilio\.rest\.Client\s*\("),
        # Stripe raw SDK writes (creates)
        re.compile(r"\bstripe\.PaymentIntent\.create\s*\("),
        re.compile(r"\bstripe\.Refund\.create\s*\("),
        re.compile(r"\bstripe\.checkout\.Session\.create\s*\("),
    ]
    for path in BACKEND_ROOT.rglob("*.py"):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel.startswith("tests/") or rel.startswith("__pycache__/") or "__pycache__" in rel:
            continue
        if rel in _ADAPTER_ALLOW_LIST:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in patterns:
                if pat.search(line):
                    findings.append((rel, lineno, line.strip()))
    return findings


def test_no_direct_sdk_calls_outside_adapters():
    findings = _grep_direct_sdk_calls()
    assert not findings, (
        "Direct Twilio/Stripe SDK calls detected outside the shipped adapters. "
        "Route through services/sms/rc_adapter.send or "
        "routers/payments_stripe_live.py:\n" +
        "\n".join(f"  {p}:{n} → {t}" for p, n, t in findings)
    )


def test_twilio_package_fully_removed():
    """Phase 7B — nothing anywhere in the codebase may import twilio."""
    r = subprocess.run(
        ["grep", "-rn", "--include=*.py",
          "-e", "^import twilio", "-e", "^from twilio",
          str(BACKEND_ROOT)],
        capture_output=True, text=True,
    )
    # Filter out any leftover comments / doctest strings just in case.
    real = [
        line for line in (r.stdout or "").splitlines()
        if "__pycache__" not in line and "/tests/" not in line
    ]
    assert not real, "twilio imports still present:\n" + "\n".join(real)


# ─── Guardrail #2 — Pay Now never returns "stripe_error"
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}",
             "Content-Type": "application/json"}


def _brian_invoice_id() -> str | None:
    """Fetch the Brian Beckman due 2026-07-22 invoice id if it exists."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    async def _q():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "aquaterra")]
        row = await db.quotes.find_one(
            {"customer_name": {"$regex": "Beckman", "$options": "i"},
             "doc_type": "invoice",
             "due_date": {"$regex": "2026-07-22"}},
            {"_id": 0, "id": 1},
        )
        return (row or {}).get("id")
    return asyncio.new_event_loop().run_until_complete(_q())


def test_pay_now_endpoint_never_returns_stripe_error():
    """Phase 5A regression guard — the endpoint that Pay Now now calls
    must never return ``{reason: "stripe_error"}`` regardless of the
    live-Stripe-key state. If the key auth-fails we get a 502 with a
    ``Stripe could not …`` detail; if the invoice isn't payable we
    get a 400 detail; if payable + keys valid we get 200 with
    ``client_secret``. All three are acceptable — ``stripe_error``
    (the legacy Phase-53 mocked-fallback string) never is."""
    inv_id = _brian_invoice_id()
    if not inv_id:
        pytest.skip("Brian Beckman seed invoice absent in this environment")
    tok = _login("admin@aquaterra.com")
    r = requests.post(f"{API}/payments/create-payment-intent",
                        headers=_hdr(tok),
                        json={"invoice_id": inv_id, "source": "authenticated"},
                        timeout=25)
    text = r.text.lower()
    # HARD gate — the legacy Phase-53 sentinel is forbidden here.
    assert "stripe_error" not in text, r.text
    assert "\"mocked\"" not in text, r.text
    # Soft gate — status code must be one of the sane paths.
    assert r.status_code in (200, 400, 502), r.text


# ─── Guardrail #3 — Invoice-SMS routes through the RC adapter
def test_invoice_send_sms_does_not_false_report_not_configured():
    """Phase 7B regression guard: with RC env populated the invoice
    SMS endpoint must NOT return an ``sms-not-configured`` sentinel —
    the shipped RC adapter is now the only SMS path."""
    if not (os.environ.get("RC_CLIENT_ID") and os.environ.get("RC_JWT")
            and os.environ.get("RC_SMS_DEFAULT_FROM")):
        pytest.skip("RC adapter intentionally in mock mode in this env")

    inv_id = _brian_invoice_id()
    if not inv_id:
        pytest.skip("Brian Beckman seed invoice absent")
    tok = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/invoices/{inv_id}/send-sms",
        headers=_hdr(tok),
        json={"to": "+15005550006", "message": "phase7b probe"},
        timeout=25,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # False-negative sentinels must be gone. Real send may fail with
    # a downstream RC error (invalid destination etc.); that's fine —
    # we're only guarding against the "adapter not wired" sentinel.
    assert body.get("reason") not in (
        "twilio-not-configured", "sms-not-configured",
    ), body
