"""Phase I1.7.e · Fix A · Feb-2026 — Integration-style TestClient
regression suite for ``POST /api/customers/{cid}/send-sms`` under
``MESSAGING_TESTMODE_MOCK=true``.

The chunk 2 tester surfaced a P0 gap: a live curl to
``/api/customers/{cid}/send-sms`` in test-mode returned HTTP 502
even though ``MESSAGING_TESTMODE_MOCK=true`` was set and the mock
short-circuit worked at the adapter level.

Two independent bugs were rolled into that single edge 502:

1. **Endpoint status whitelist too narrow.** ``customers.py`` only
   accepted ``("sent", "queued", "mocked", "suppressed")`` as a
   non-error status. Any guard-block state
   (``dry_run`` / ``suppressed_not_demo`` / ``no_consent``) was
   coerced to ``HTTP 502`` — masking the real reason and looking
   like an infrastructure failure to the tester.

2. **Guard-block ordering** in ``rc_adapter.send``: the pre-flight
   ``is_comm_allowed`` gate fires BEFORE the platform-testmode
   short-circuit. When the target customer is not flagged
   ``is_demo_account=True`` in a non-prod pod, the send returns
   ``provider_status="suppressed_not_demo"`` and the mock envelope
   never runs. This is by design (the guardrails MUST fire in mock
   mode — the whole point of test-mode is to prove nothing bypasses
   the safety net). It just wasn't documented as a smoke-test
   pre-req.

This test suite goes through the FastAPI router end-to-end
(unit-testing the mock function alone was what missed the 502) and
pins the following contracts:

* Test-mode SMS returns HTTP 200 with ``routed_via="platform_testmode_mock"``.
* Guard-block statuses (``suppressed_not_demo`` / ``dry_run`` /
  ``no_consent`` / ``suppressed``) return HTTP 200 with an
  informative envelope — NEVER HTTP 502.
* Cap-exceeded (from the BYO passthrough) surfaces as HTTP 429.
* Actual infrastructure failure (``provider_status="failed"``)
  still surfaces as HTTP 502.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run(coro):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────
# Test client factory — mounts just the customers router with fake
# auth + tenant deps so we exercise the exact endpoint code without
# needing a full server boot.
# ─────────────────────────────────────────────────────────────────────
def _make_client(monkeypatch, *, customer_doc: Dict[str, Any],
                 tenant_id: str = "t-fixA-1",
                 send_result: Dict[str, Any]):
    """Return a ``fastapi.testclient.TestClient`` wired to a minimal
    app that mounts only the customer send-sms surface. The customer
    lookup is stubbed to return ``customer_doc`` and the underlying
    RC SMS adapter is stubbed to return ``send_result``."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import customers as cust_mod
    from services.sms import rc_adapter

    class _StubCollection:
        async def find_one(self, *a, **kw):
            return dict(customer_doc)

        async def insert_one(self, *a, **kw):
            return None

    class _StubDB:
        customers = _StubCollection()
        communications_log = _StubCollection()

    monkeypatch.setattr(cust_mod, "db", _StubDB())

    async def _stub_send(**kwargs):
        return dict(send_result)

    monkeypatch.setattr(rc_adapter, "send", _stub_send)

    async def _fake_admin():
        return {"id": "u-admin", "role": "admin",
                "tenant_id": tenant_id, "email": "admin@x.com"}

    async def _fake_tenant():
        return {"id": tenant_id}

    app = FastAPI()
    app.include_router(cust_mod.router, prefix="/api")
    from utils import require_admin
    from routers.tenants import get_current_tenant
    app.dependency_overrides[require_admin] = _fake_admin
    app.dependency_overrides[get_current_tenant] = _fake_tenant
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────
# 1. Test-mode mock path → HTTP 200 + platform_testmode_mock marker
# ─────────────────────────────────────────────────────────────────────
def test_send_sms_testmode_platform_mock_returns_200(monkeypatch):
    """The mock envelope from ``rc_adapter.send`` (as it would
    return under ``MESSAGING_TESTMODE_MOCK=true``) must surface as
    HTTP 200 with the ``routed_via="platform_testmode_mock"``
    observability marker preserved."""
    customer = {
        "id": "c-1", "tenant_id": "t-fixA-1",
        "phones": [{"number": "+16236285855"}],
        "phone": "+16236285855",
        "is_demo_account": True,
    }
    mock_env = {
        "provider": "mock",
        "provider_status": "sent",
        "provider_response_id": "mock-abc123def456",
        "attempts": 1,
        "error": None,
        "routed_via": "platform_testmode_mock",
        "rc_status": "Queued",
    }
    c = _make_client(monkeypatch, customer_doc=customer,
                       send_result=mock_env)
    r = c.post("/api/customers/c-1/send-sms",
                 json={"to": "+16236285855", "body": "hi"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert j["provider_status"] == "sent"
    assert j["routed_via"] == "platform_testmode_mock"
    assert j["provider_response_id"].startswith("mock-")


def test_send_sms_testmode_tenant_byo_mock_returns_200(monkeypatch):
    """Same contract when the tenant has a BYO SMS provider
    configured: the envelope carries ``routed_via="tenant_byo_testmode_mock"``
    and the endpoint returns HTTP 200."""
    customer = {
        "id": "c-2", "tenant_id": "t-fixA-2",
        "phones": [{"number": "+16236285855"}],
        "phone": "+16236285855",
        "is_demo_account": True,
    }
    byo_mock_env = {
        "status": "sent",
        "provider": "twilio",
        "provider_id": "mock-byo-abc12345",
        "provider_status": "sent",
        "provider_response_id": "mock-byo-abc12345",
        "attempts": 1,
        "error": None,
        "routed_via": "tenant_byo_testmode_mock",
        "raw": {"testmode_mock": True, "tenant_id": "t-fixA-2"},
    }
    c = _make_client(monkeypatch, customer_doc=customer,
                       send_result=byo_mock_env)
    r = c.post("/api/customers/c-2/send-sms",
                 json={"to": "+16236285855", "body": "hi"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provider_status"] == "sent"
    assert j["routed_via"] == "tenant_byo_testmode_mock"
    assert j["provider"] == "twilio"


# ─────────────────────────────────────────────────────────────────────
# 2. Guard-block states → HTTP 200, NEVER 502 (root cause of the
#    original tester finding).
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "guard_status, adapter_provider",
    [
        ("suppressed_not_demo", "ringcentral"),   # is_comm_allowed
        ("dry_run", "ringcentral"),                # guard_outbound preview
        ("no_consent", "ringcentral"),             # K31 consent gate
        ("suppressed", "ringcentral"),             # marketing suppression
    ],
)
def test_send_sms_guard_block_returns_200_not_502(
    monkeypatch, guard_status, adapter_provider,
):
    """Regression guard for the P0 Fix A finding. Every pre-flight
    gate returns a distinct ``provider_status`` OTHER than
    ``"sent"``. Those are business-signalled "guard fired, no live
    send" states — NOT infrastructure failures. Coercing them to a
    502 (as the endpoint did pre-Fix-A) hides the reason from the
    admin UI and looks like a Twilio / RC outage."""
    customer = {
        "id": "c-gb", "tenant_id": "t-fixA-3",
        "phones": [{"number": "+16028874400"}],
        "phone": "+16028874400",
    }
    gate_env = {
        "provider": adapter_provider,
        "provider_status": guard_status,
        "provider_response_id": None,
        "attempts": 0,
        "error": None,
    }
    c = _make_client(monkeypatch, customer_doc=customer,
                       send_result=gate_env)
    r = c.post("/api/customers/c-gb/send-sms",
                 json={"to": "+16028874400", "body": "hi"})
    assert r.status_code == 200, (
        f"guard-block status {guard_status!r} must NOT surface as "
        f"HTTP 502. Response: {r.status_code} {r.text}"
    )
    j = r.json()
    assert j["ok"] is True
    assert j["provider_status"] == guard_status


# ─────────────────────────────────────────────────────────────────────
# 3. Cap-exceeded (from BYO passthrough) → HTTP 429
# ─────────────────────────────────────────────────────────────────────
def test_send_sms_cap_exceeded_returns_429(monkeypatch):
    """When the tenant BYO probe returns a cap-exceeded envelope
    (e.g. Twilio 429 for that tenant's monthly SMS cap), the
    endpoint must translate it into HTTP 429 — NOT 502. This aligns
    with the other transactional cap-exceeded callsites (D2D Zillow
    limiter, comms send-now, checkin rewrite AI cap)."""
    customer = {
        "id": "c-cap", "tenant_id": "t-fixA-4",
        "phones": [{"number": "+16028874400"}],
        "phone": "+16028874400",
        "is_demo_account": True,
    }
    cap_env = {
        "status": "cap_exceeded",
        "provider": "twilio",
        "provider_id": None,
        "provider_status": "cap_exceeded",
        "provider_response_id": None,
        "attempts": 1,
        "error": "monthly cap exceeded",
        "http_status": 429,
        "routed_via": "tenant_byo",
    }
    c = _make_client(monkeypatch, customer_doc=customer,
                       send_result=cap_env)
    r = c.post("/api/customers/c-cap/send-sms",
                 json={"to": "+16028874400", "body": "hi"})
    assert r.status_code == 429, r.text
    assert "cap" in r.json().get("detail", "").lower()


# ─────────────────────────────────────────────────────────────────────
# 4. Real infrastructure failure → HTTP 502 (regression parity)
# ─────────────────────────────────────────────────────────────────────
def test_send_sms_provider_failure_still_returns_502(monkeypatch):
    """Real transport / API errors (``provider_status="failed"``)
    must continue to surface as HTTP 502 so ops paging keeps working.
    This is a regression guard so a future refactor doesn't
    accidentally 200-swallow real infra failures."""
    customer = {
        "id": "c-fail", "tenant_id": "t-fixA-5",
        "phones": [{"number": "+16028874400"}],
        "phone": "+16028874400",
        "is_demo_account": True,
    }
    fail_env = {
        "provider": "ringcentral",
        "provider_status": "failed",
        "provider_response_id": None,
        "attempts": 3,
        "error": "TimeoutError: RC OAuth token endpoint timed out",
        "http_status": 504,
    }
    c = _make_client(monkeypatch, customer_doc=customer,
                       send_result=fail_env)
    r = c.post("/api/customers/c-fail/send-sms",
                 json={"to": "+16028874400", "body": "hi"})
    assert r.status_code == 502, r.text
    assert "TimeoutError" in r.json().get("detail", "")


# ─────────────────────────────────────────────────────────────────────
# 5. .env visibility → the exact flag the running process reads
# ─────────────────────────────────────────────────────────────────────
def test_messaging_testmode_env_is_visible_to_helper():
    """Sanity: whatever ``.env`` says for ``MESSAGING_TESTMODE_MOCK``,
    ``is_messaging_testmode()`` must agree. Complements the more
    specific drift-detection in
    ``test_i17e_testmode_env_visibility.py`` — that suite skips
    when the flag is unset, this one just proves the read-path is
    live for whatever value happens to be in .env at test time."""
    from services.messaging.testmode import is_messaging_testmode
    on_disk = os.environ.get("MESSAGING_TESTMODE_MOCK", "").strip().lower()
    expected = on_disk in ("1", "true", "yes", "on")
    assert bool(is_messaging_testmode()) is expected
