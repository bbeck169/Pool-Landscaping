"""
Feb-2026 · P0 — Estimate-vs-Invoice reminder routing regression suite.

Guards against the prod bug where clicking "Send reminder" on an
Estimate detail page fired the invoice payment-reminder template
against the customer ("This is a friendly reminder that invoice
Estimate has an outstanding balance of $27,273.00 …").

Scenarios covered:
  1. Reminder on an ``estimate`` / ``quote`` doc → estimate template
     path (``send_estimate_reminder_email`` called, invoice email
     NEVER called), audit event = ``estimate_reminder_sent`` /
     ``quote_reminder_sent``, response payload carries
     ``doc_type`` + ``review_url_minted``.
  2. Reminder on an ``invoice`` doc → payment-reminder path,
     ``send_invoice_reminder_email`` called, audit event =
     ``invoice_reminder_sent``.
  3. ``send_invoice_reminder_email`` REFUSES (returns False) if the
     caller sneaks a quote/estimate doc past the router — depth-in-
     defence guard so a future caller can't regress the copy.
  4. ``request-payment-link`` on a quote/estimate id returns a
     documented 4xx (rejected via ``find_invoice_dual`` doc_type
     filter — no Stripe session created).
  5. ``_invoice_display_number`` never falls back to ``title``
     (the exact regression that produced the "invoice Estimate has
     an outstanding balance" prod copy).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException


_MARK = "P0-est-inv-reminder"


# Feb-2026 · Test isolation — bind an owned motor client to a
# dedicated event loop so this suite can run inside the same
# pytest session as ``test_portal_auto_login_route.py`` (which
# also rebinds ``config.db``). The loop + client are created
# inside a session-scoped fixture (NOT at module import) so pytest
# collection doesn't leak a half-initialised loop across other
# suites.
_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro):
    assert _LOOP is not None, "session fixture not initialised"
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    global _LOOP
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.quotes as _q_mod
    _q_mod.db = fresh_db
    import routers.lumino_link_request as _ll_mod
    _ll_mod.db = fresh_db
    import emailer as _e_mod
    _e_mod.db = fresh_db
    yield
    _LOOP.close()
    _LOOP = None


def _db():
    """Late-bound access to ``config.db`` — after the ``_bind_db``
    fixture ran we don't want a module-load-time snapshot."""
    import config as _cfg
    return _cfg.db


# ── Fixtures ─────────────────────────────────────────────────────
@pytest.fixture()
def seeded():
    """Insert one tenant + one customer + one estimate + one invoice
    row. Cleaned up after each test so parallel test runs don't
    stomp each other."""
    tenant_id = f"{_MARK}-tenant"
    customer_id = f"{_MARK}-cust"
    estimate_id = f"{_MARK}-est"
    quote_id = f"{_MARK}-quote"
    invoice_id = f"{_MARK}-inv"

    _run(_db().tenants.insert_one({
        "id": tenant_id, "slug": _MARK, "company_name": "Test Aqua Co",
    }))
    _run(_db().customers.insert_one({
        "id": customer_id, "tenant_id": tenant_id,
        "name": "Valarie Lira", "email": "valarie@example.com",
        "is_active": True, "is_muted": False,
    }))
    _run(_db().quotes.insert_one({
        "id": estimate_id, "tenant_id": tenant_id,
        "customer_id": customer_id, "customer_name": "Valarie Lira",
        "doc_type": "estimate", "status": "sent",
        # The regression trap — title used to be the doc-type label.
        "title": "Estimate",
        "invoice_number": "EST-1042",
        "total": 27273.0, "amount_paid": 0.0,
        "created_at": "2026-02-01T00:00:00+00:00",
    }))
    _run(_db().quotes.insert_one({
        "id": quote_id, "tenant_id": tenant_id,
        "customer_id": customer_id, "customer_name": "Valarie Lira",
        "doc_type": "quote", "status": "sent",
        "title": "Quote",
        "invoice_number": "QTE-77",
        "total": 500.0, "amount_paid": 0.0,
        "created_at": "2026-02-01T00:00:00+00:00",
    }))
    _run(_db().quotes.insert_one({
        "id": invoice_id, "tenant_id": tenant_id,
        "customer_id": customer_id, "customer_name": "Valarie Lira",
        "doc_type": "invoice", "status": "sent",
        "title": "Invoice",
        "invoice_number": "INV-999",
        "total": 1250.75, "amount_paid": 0.0,
        "payment_status": "unpaid",
        "created_at": "2026-02-01T00:00:00+00:00",
    }))
    yield {
        "tenant_id": tenant_id, "customer_id": customer_id,
        "estimate_id": estimate_id, "quote_id": quote_id,
        "invoice_id": invoice_id,
    }
    _run(_db().tenants.delete_many({"id": tenant_id}))
    _run(_db().customers.delete_many({"id": customer_id}))
    _run(_db().quotes.delete_many({"id": {"$in": [
        estimate_id, quote_id, invoice_id,
    ]}}))
    _run(_db().audit_events.delete_many({
        "$or": [
            {"payload.estimate_id": estimate_id},
            {"payload.quote_id": quote_id},
            {"payload.invoice_id": invoice_id},
        ],
    }))


# ── 1. Estimate reminder path ────────────────────────────────────
def test_estimate_reminder_uses_estimate_template(seeded, monkeypatch):
    """The router MUST call ``send_estimate_reminder_email`` for an
    ``estimate`` doc_type and MUST NOT touch the invoice email
    helper.  Audit event fires with the estimate scope name and a
    ``review_url`` was minted for the "Review Estimate" CTA."""
    from routers import quotes as router
    est_email = AsyncMock(return_value=True)
    inv_email = AsyncMock(return_value=True)
    notify_cust = AsyncMock(return_value=None)
    monkeypatch.setattr(router, "send_estimate_reminder_email", est_email)
    monkeypatch.setattr(router, "send_invoice_reminder_email", inv_email)
    monkeypatch.setattr(router, "notify_customer", notify_cust)

    tenant = {"id": seeded["tenant_id"], "company_name": "Test Aqua Co"}
    user = {"id": "admin-1", "role": "super_admin"}
    result = _run(router.send_reminder(
        seeded["estimate_id"], user=user, tenant=tenant,
    ))

    assert result["ok"] is True
    assert result["doc_type"] == "estimate"
    assert result["review_url_minted"] is True
    assert inv_email.await_count == 0, (
        "invoice-reminder helper MUST NOT fire on an estimate — this is "
        "the exact prod-shape regression this test guards against"
    )
    assert est_email.await_count == 1
    # Verify the review URL substring points at the customer-facing
    # magic-link viewer (``/e/estimate?token=…``), NOT the portal.
    call_args = est_email.await_args
    review_url = call_args.args[2] if len(call_args.args) >= 3 else \
        call_args.kwargs.get("review_url")
    assert "/e/estimate?token=" in review_url

    # SMS body must NOT reference outstanding balance / due.
    sms_body = notify_cust.await_args.args[2]
    assert "outstanding balance" not in sms_body.lower()
    assert "due" not in sms_body.lower()
    assert "review" in sms_body.lower() or "awaiting" in sms_body.lower()

    # Audit event tagged with the estimate scope.
    audit = _run(_db().audit_events.find_one({
        "event_type": "estimate_reminder_sent",
        "tenant_id": seeded["tenant_id"],
    }, {"_id": 0}))
    assert audit is not None, "audit event missing"
    assert audit["payload"]["estimate_id"] == seeded["estimate_id"]


def test_quote_reminder_uses_estimate_template(seeded, monkeypatch):
    """Same path as estimate, but doc_type=quote.  Audit event
    should use the ``quote_`` scope name."""
    from routers import quotes as router
    est_email = AsyncMock(return_value=False)
    inv_email = AsyncMock(return_value=True)
    monkeypatch.setattr(router, "send_estimate_reminder_email", est_email)
    monkeypatch.setattr(router, "send_invoice_reminder_email", inv_email)
    monkeypatch.setattr(router, "notify_customer", AsyncMock())

    result = _run(router.send_reminder(
        seeded["quote_id"],
        user={"id": "u", "role": "super_admin"},
        tenant={"id": seeded["tenant_id"]},
    ))
    assert result["doc_type"] == "quote"
    assert inv_email.await_count == 0
    audit = _run(_db().audit_events.find_one({
        "event_type": "quote_reminder_sent",
        "tenant_id": seeded["tenant_id"],
    }, {"_id": 0}))
    assert audit is not None
    assert audit["payload"]["quote_id"] == seeded["quote_id"]


# ── 2. Invoice reminder path ─────────────────────────────────────
def test_invoice_reminder_uses_payment_template(seeded, monkeypatch):
    """Invoice branch must call the invoice-email helper, NOT the
    estimate one.  Audit event and response contract preserved."""
    from routers import quotes as router
    est_email = AsyncMock(return_value=True)
    inv_email = AsyncMock(return_value=True)
    monkeypatch.setattr(router, "send_estimate_reminder_email", est_email)
    monkeypatch.setattr(router, "send_invoice_reminder_email", inv_email)
    monkeypatch.setattr(router, "notify_customer", AsyncMock())

    result = _run(router.send_reminder(
        seeded["invoice_id"],
        user={"id": "u", "role": "super_admin"},
        tenant={"id": seeded["tenant_id"]},
    ))
    assert result["ok"] is True
    assert "doc_type" not in result, (
        "invoice branch preserves the legacy response shape"
    )
    assert est_email.await_count == 0
    assert inv_email.await_count == 1

    audit = _run(_db().audit_events.find_one({
        "event_type": "invoice_reminder_sent",
        "tenant_id": seeded["tenant_id"],
    }, {"_id": 0}))
    assert audit is not None
    assert audit["payload"]["invoice_id"] == seeded["invoice_id"]


# ── 3. Emailer refusal guard ─────────────────────────────────────
def test_send_invoice_reminder_refuses_non_invoice_doc_types(monkeypatch):
    """Defense-in-depth: even if a future caller bypasses the router
    guard and hands ``send_invoice_reminder_email`` an estimate doc,
    the helper MUST return False (and log a warning) — never send
    the "outstanding balance" email against a doc that has no
    outstanding balance."""
    from emailer import send_invoice_reminder_email
    fake_doc = {
        "id": "some-id", "doc_type": "estimate",
        "customer_id": "c", "tenant_id": "t",
        "total": 100.0, "amount_paid": 0.0,
    }
    result = _run(send_invoice_reminder_email(fake_doc))
    assert result is False


def test_send_estimate_reminder_refuses_invoice_doc_types(monkeypatch):
    """Symmetric guard — the estimate helper refuses invoice docs."""
    from emailer import send_estimate_reminder_email
    fake_doc = {
        "id": "some-id", "doc_type": "invoice",
        "customer_id": "c", "tenant_id": "t",
        "total": 100.0,
    }
    result = _run(send_estimate_reminder_email(
        fake_doc, {"id": "t"}, "https://x/e/estimate?token=abc",
    ))
    assert result is False


# ── 4. Payment-link endpoint doc_type refusal ────────────────────
def test_request_payment_link_refuses_quote_estimate(seeded):
    """``POST /invoices/{id}/request-payment-link`` MUST refuse an
    estimate / quote id.  The dual-collection lookup already filters
    by ``doc_type=invoice`` so an estimate resolves as
    ``invoice_not_found`` (404); either behaviour is acceptable so
    long as no Stripe session is created and the response is a
    4xx with a clear error body."""
    from routers import lumino_link_request as router
    async def _do():
        try:
            await router.request_payment_link(
                invoice_id=seeded["estimate_id"],
                body=None,
                user={"id": "u", "role": "super_admin"},
            )
            pytest.fail("expected HTTPException")
        except HTTPException as exc:
            assert 400 <= exc.status_code < 500
            # Either the explicit doc_type guard fires ("not_an_invoice")
            # or the underlying lookup returns 404 "invoice_not_found".
            detail = str(exc.detail).lower()
            assert (
                "not_an_invoice" in detail
                or "invoice_not_found" in detail
            )
    _run(_do())


# ── 5. Display-number regression guard ───────────────────────────
def test_display_number_never_falls_back_to_title():
    """The prod bug root-caused to ``inv.get('title','')`` returning
    the string ``"Estimate"``.  The helper MUST prefer
    ``invoice_number`` → ``doc_number`` → ``#<id[:8]>``, and NEVER
    hydrate from ``title`` even when both other fields are empty."""
    from emailer import _invoice_display_number
    # Preferred order.
    assert _invoice_display_number({
        "invoice_number": "INV-1", "doc_number": "IGN", "title": "Invoice",
    }) == "INV-1"
    assert _invoice_display_number({
        "doc_number": "DOC-9", "title": "Invoice",
    }) == "DOC-9"
    # Falls back to id short-form, NOT title.
    got = _invoice_display_number({
        "id": "abcdef1234-uuid", "title": "Estimate",
    })
    assert got == "#abcdef12"
    assert got != "Estimate"


# ── 6. Portal auto-login legacy fallback ─────────────────────────
def test_portal_auto_login_expired_invoice_bounces_to_public_pay():
    """Feb-2026 · P0 Pay-link routing fix — an expired
    ``portal_invoice_pay`` token MUST redirect to
    ``/pay/invoice/{id}?msg=link_expired`` (public pay page) rather
    than ``/portal/login?reason=link_expired`` (auth wall).  Uses a
    manually-crafted expired JWT so we don't have to wait for a
    real one to age out."""
    import jwt
    from datetime import timedelta
    from config import JWT_ALGO, JWT_SECRET
    payload = {
        "sub": "portal_invoice_pay",
        "customer_id": "c",
        "invoice_id": "inv-42",
        "tenant_id": "t",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    tok = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

    from routers.portal_auto_login import _peek_scope_and_id
    scope, rid = _peek_scope_and_id(tok)
    assert scope == "invoice"
    assert rid == "inv-42"

    # And a legacy ``invoice_pay`` (pay-link builder) token peeks
    # the same way, so a 30-day pay-link that a customer clicks
    # after the invoice was voided also lands on the public page.
    payload_legacy = {
        "sub": "invoice_pay",
        "invoice_id": "inv-77",
        "tenant_id": "t",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    legacy = jwt.encode(payload_legacy, JWT_SECRET, algorithm=JWT_ALGO)
    scope2, rid2 = _peek_scope_and_id(legacy)
    assert scope2 == "invoice"
    assert rid2 == "inv-77"

    # Tampered token peeks as empty — falls through to
    # ``_expired_response`` (legacy behaviour) instead of the
    # public pay redirect.
    scope3, rid3 = _peek_scope_and_id("not.a.real.jwt")
    assert scope3 == "" and rid3 == ""
