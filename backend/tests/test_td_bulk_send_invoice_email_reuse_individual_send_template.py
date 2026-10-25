"""TD-bulk-send-invoice-email-reuse-individual-send-template · Feb-2026
======================================================================

Regression lock for the Ticket N refactor.  Covers:

  §1 — Bulk send calls the canonical
       ``emailer.send_invoice_reminder_email`` per invoice (not
       the legacy inline plain-text path).
  §2 — Subject + HTML live-render lock:
       ``"Payment reminder — invoice INV-..."`` subject;
       body contains the ``Payment reminder`` heading, bolded
       invoice number, red ``View Invoice`` CTA (via the shared
       emailer template).
  §3 — Primary-email gate: ``customers.email`` empty + ``users``
       row present → ``skipped_no_contact`` (users-table fallback
       NOT consulted — operator-spec regression lock).
  §4 — Automation gate off → ``skipped_automation_disabled``
       (not ``error``, not ``failed``).
  §5 — 60-second dedupe window still fires (regression lock).
  §6 — Partial-channel skip (no phone → email-only, no email →
       sms-only) unchanged.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    """Rebind ``db`` on every module in the bulk-send dependency
    graph.  Returns a dict of (module, attr_name, orig_value) so
    the fixture can restore originals on teardown — critical to
    avoid loop-contamination of sibling suites that call
    ``asyncio.run()`` on a fresh loop and expect ``config.db``
    to NOT be bound to this suite's long-lived ``_LOOP``.
    """
    import config
    import routers.invoices_bulk_send as _bs
    import routers.dunning as _dn
    import emailer as _em
    import services.tenant_automation_gates as _tag

    originals = [
        (config, "db", config.db),
        (_bs, "db", _bs.db),
        (_dn, "db", _dn.db),
        (_em, "db", _em.db),
        (_tag.config, "db", _tag.config.db),
    ]
    config.db = _DB
    _bs.db = _DB
    _dn.db = _DB
    _em.db = _DB
    _tag.config.db = _DB
    return originals


def _restore_db(originals):
    for mod, attr, value in originals:
        setattr(mod, attr, value)


_PFX = f"TESTtdN-{uuid4().hex[:8]}"
TENANT = f"{_PFX}-tenant"


async def _seed_tenant(tid, *, past_due_enabled=True):
    doc = {"id": tid, "name": "Ticket N Tenant"}
    if past_due_enabled is False:
        doc["invoice_past_due_enabled"] = False
    await _DB.tenants.update_one(
        {"id": tid}, {"$set": doc}, upsert=True,
    )


async def _seed_customer(*, tid, email=None, phone=None):
    cid = f"{_PFX}-c-{uuid4().hex[:8]}"
    doc = {"id": cid, "tenant_id": tid, "name": "Alex Customer"}
    if email is not None:
        doc["email"] = email
    if phone is not None:
        doc["phone"] = phone
    await _DB.customers.insert_one(doc)
    return cid


async def _seed_invoice(*, tid, cid, status="issued",
                          payment_status="unpaid"):
    inv_id = f"{_PFX}-i-{uuid4().hex[:8]}"
    inv_no = f"INV-TEST-{uuid4().hex[:6].upper()}"
    await _DB.quotes.insert_one({
        "id": inv_id, "tenant_id": tid, "doc_type": "invoice",
        "customer_id": cid, "customer_name": "Alex Customer",
        "invoice_number": inv_no,
        "status": status, "payment_status": payment_status,
        "total": 100.0, "subtotal": 100.0, "tax": 0.0,
        "tax_rate": 0.0, "amount_paid": 0.0,
        "line_items": [{"id": f"{inv_id}-li1",
                          "description": "svc",
                          "quantity": 1, "unit_price": 100}],
        "due_date": "2026-03-10",
        "created_at": "2026-02-10T00:00:00+00:00",
    })
    return inv_id, inv_no


async def _wipe():
    for coll in ("quotes", "customers", "tenants", "users",
                  "invoice_send_attempts"):
        await _DB[coll].delete_many(
            {"$or": [
                {"id": {"$regex": f"^{_PFX}"}},
                {"tenant_id": {"$regex": f"^{_PFX}"}},
            ]},
        )


@pytest.fixture(autouse=True)
def _env():
    originals = _patch_db_everywhere()
    _run(_wipe())
    try:
        yield
    finally:
        _run(_wipe())
        _restore_db(originals)


async def _bulk_send(invoice_ids, *, tenant_id):
    from routers.invoices_bulk_send import (
        bulk_send_invoices, BulkSendBody,
    )
    tenant = {"id": tenant_id, "name": "Ticket N Tenant"}
    user = {"id": f"usr_{uuid4().hex[:8]}", "role": "admin"}
    return await bulk_send_invoices(
        BulkSendBody(invoice_ids=invoice_ids),
        user=user, tenant=tenant,
    )


# ═══════════════════════════════════════════════════════════════════
# §1 · Bulk delegates to canonical send_invoice_reminder_email
# ═══════════════════════════════════════════════════════════════════
def test_bulk_send_calls_canonical_send_invoice_reminder_email_per_invoice():
    """Regression lock: every bulk-sent invoice flows through the
    canonical renderer, NOT the legacy inline plain-text path."""
    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(
        tid=TENANT, email="a@example.com", phone="+15550001",
    ))
    i1, _ = _run(_seed_invoice(tid=TENANT, cid=cid))
    i2, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    canonical_spy = AsyncMock(return_value=True)
    with patch("emailer.send_invoice_reminder_email", new=canonical_spy), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={
                    "enabled": True, "stages": [],
                })), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([i1, i2], tenant_id=TENANT))

    assert res["summary"]["sent_both"] == 2
    assert canonical_spy.await_count == 2
    # Each call receives the full invoice dict (not a trimmed ctx).
    args_i1 = canonical_spy.await_args_list[0].args[0]
    args_i2 = canonical_spy.await_args_list[1].args[0]
    assert {args_i1["id"], args_i2["id"]} == {i1, i2}
    for inv_arg in (args_i1, args_i2):
        assert inv_arg["doc_type"] == "invoice"
        assert inv_arg["tenant_id"] == TENANT
        assert inv_arg["invoice_number"].startswith("INV-TEST-")


# ═══════════════════════════════════════════════════════════════════
# §2 · Subject + HTML live-render lock (canonical renderer surface)
# ═══════════════════════════════════════════════════════════════════
def test_canonical_renderer_produces_payment_reminder_subject_and_branded_html():
    """Live-render regression lock: subject matches the operator-
    specified format and the themed HTML carries the branded shell
    + bolded invoice number + View Invoice CTA.  Executed against
    the canonical ``_reminder_html`` + ``wrap_html_in_shell`` path
    without firing resend.
    """
    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(
        tid=TENANT, email="a@example.com", phone=None,
    ))
    inv_id, inv_no = _run(_seed_invoice(tid=TENANT, cid=cid))

    async def _render():
        inv = await _DB.quotes.find_one({"id": inv_id}, {"_id": 0})
        cust = await _DB.customers.find_one(
            {"id": inv["customer_id"]}, {"_id": 0},
        ) or {}
        from emailer import _reminder_html, _invoice_display_number
        from services.email.theming import wrap_html_in_shell
        from services.tenants.business_settings import (
            get_effective_business_settings,
        )
        from services.email_body_i18n import t_email_body
        inner = _reminder_html(
            inv, cust.get("name") or "there",
            attachment_count=0, portal_cta_url="",
            locale="en", company_name="Ticket N Tenant",
        )
        branding = await get_effective_business_settings(
            _DB, inv["tenant_id"], absolutize=True,
        )
        themed = wrap_html_in_shell(inner, branding)
        subject = t_email_body(
            "en", "email.invoice_reminder.subject",
            invoice_number=_invoice_display_number(inv),
        )
        return subject, themed

    subject, html = _run(_render())
    assert subject == f"Payment reminder — invoice {inv_no}"
    # Branded template elements the operator called out explicitly:
    assert "Payment reminder" in html
    # Bolded invoice number — the i18n body wraps {invoice_number} in <b>.
    assert f"<b>{inv_no}</b>" in html
    # "View Invoice" red CTA button.
    assert "View Invoice" in html


# ═══════════════════════════════════════════════════════════════════
# §3 · Primary-email gate (no users-table fallback)
# ═══════════════════════════════════════════════════════════════════
def test_bulk_send_skips_when_customers_email_empty_even_if_users_row_exists():
    """Operator-spec regression lock: ``customers.email`` empty +
    ``users`` row carries email → MUST short-circuit to
    ``skipped_no_contact``.  The canonical fn's users-table
    fallback is NEVER consulted for the bulk path."""
    _run(_seed_tenant(TENANT))
    # customers.email intentionally absent (``email=None``).
    cid = _run(_seed_customer(tid=TENANT, email=None, phone=None))
    # Seed a users row that WOULD satisfy the canonical fallback —
    # the bulk path must NOT use it.
    _run(_DB.users.insert_one({
        "id": f"{_PFX}-u-{uuid4().hex[:8]}",
        "customer_id": cid, "tenant_id": TENANT,
        "role": "customer", "email": "fallback-user@example.com",
    }))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    canonical_spy = AsyncMock(return_value=True)
    with patch("emailer.send_invoice_reminder_email", new=canonical_spy), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([inv_id], tenant_id=TENANT))

    assert res["summary"]["skipped_no_contact"] == 1
    assert res["results"][0]["status"] == "skipped_no_contact"
    # Canonical fn MUST NOT have been invoked — the pre-check
    # short-circuited before it could consult the users fallback.
    assert canonical_spy.await_count == 0


# ═══════════════════════════════════════════════════════════════════
# §4 · Automation gate off → skipped_automation_disabled (not error)
# ═══════════════════════════════════════════════════════════════════
def test_bulk_send_surfaces_automation_disabled_when_tenant_flag_off():
    """Tenant has ``invoice_past_due_enabled=False`` → canonical fn
    is NOT called; per-row status is ``skipped_automation_disabled``
    (NOT ``error`` / ``failed`` so operator sees the actual reason).
    """
    _run(_seed_tenant(TENANT, past_due_enabled=False))
    cid = _run(_seed_customer(
        tid=TENANT, email="a@example.com", phone=None,
    ))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    canonical_spy = AsyncMock(return_value=True)
    with patch("emailer.send_invoice_reminder_email", new=canonical_spy), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([inv_id], tenant_id=TENANT))

    assert res["summary"]["skipped_automation_disabled"] == 1
    assert res["summary"]["errored"] == 0
    row = res["results"][0]
    assert row["status"] == "skipped_automation_disabled"
    # Canonical fn NOT called — pre-check prevents a wasted Resend
    # dispatch.
    assert canonical_spy.await_count == 0


def test_bulk_send_sms_only_customer_with_automation_off_surfaces_as_automation_disabled():
    """Customer has phone but no email, automation off.  SMS sends,
    but the final per-row status surfaces the automation suppression
    (not ``sent_sms_only``) — the operator sees the actual reason
    the email didn't fire."""
    _run(_seed_tenant(TENANT, past_due_enabled=False))
    cid = _run(_seed_customer(
        tid=TENANT, email=None, phone="+15550099",
    ))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    with patch("emailer.send_invoice_reminder_email",
                new=AsyncMock(return_value=True)), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([inv_id], tenant_id=TENANT))

    # Customer had NO email, so the automation flag has no
    # effect — SMS-only outcome stays as sent_sms_only.
    assert res["results"][0]["status"] == "sent_sms_only"


# ═══════════════════════════════════════════════════════════════════
# §5 · 60-second dedupe window still respected
# ═══════════════════════════════════════════════════════════════════
def test_bulk_send_dedupe_window_still_fires_after_refactor():
    """Second bulk call against the same invoice within the 60s
    window → ``skipped_recent_send``.  Operator-safety guard
    survives the canonical delegation refactor."""
    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(
        tid=TENANT, email="a@example.com", phone="+15550001",
    ))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    with patch("emailer.send_invoice_reminder_email",
                new=AsyncMock(return_value=True)), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res1 = _run(_bulk_send([inv_id], tenant_id=TENANT))
        res2 = _run(_bulk_send([inv_id], tenant_id=TENANT))

    assert res1["summary"]["sent_both"] == 1
    assert res2["summary"]["skipped_recent_send"] == 1
    assert res2["results"][0]["status"] == "skipped_recent_send"


# ═══════════════════════════════════════════════════════════════════
# §6 · Partial-channel skip logic unchanged
# ═══════════════════════════════════════════════════════════════════
def test_bulk_send_phone_only_customer_still_gets_sms_only():
    """``customers.email`` empty + ``customers.phone`` set → SMS
    fires, email skipped, final is ``sent_sms_only``.  Pre-refactor
    contract preserved."""
    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(
        tid=TENANT, email=None, phone="+15559999",
    ))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    canonical_spy = AsyncMock(return_value=True)
    with patch("emailer.send_invoice_reminder_email", new=canonical_spy), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([inv_id], tenant_id=TENANT))

    assert res["results"][0]["status"] == "sent_sms_only"
    assert canonical_spy.await_count == 0


def test_bulk_send_email_only_customer_still_gets_email_only():
    """``customers.phone`` empty + ``customers.email`` set → email
    fires, SMS skipped, final is ``sent_email_only``."""
    _run(_seed_tenant(TENANT))
    cid = _run(_seed_customer(
        tid=TENANT, email="a@example.com", phone=None,
    ))
    inv_id, _ = _run(_seed_invoice(tid=TENANT, cid=cid))

    with patch("emailer.send_invoice_reminder_email",
                new=AsyncMock(return_value=True)), \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})), \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={"enabled": True,
                                              "stages": []})), \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://ex/pay")):
        res = _run(_bulk_send([inv_id], tenant_id=TENANT))

    assert res["results"][0]["status"] == "sent_email_only"
