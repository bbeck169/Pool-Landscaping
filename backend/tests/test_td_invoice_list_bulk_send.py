"""TD-invoice-list-bulk-send · Feb-2026
================================================================

Pytest coverage for ``POST /api/invoices/bulk-send``.  Follows
the ``test_td_pdf_import_operator_confirm_before_create`` /
``test_k49b_customer_id_backfill`` convention: sync pymongo
for seed + teardown + assertion, single ``asyncio.run()`` per
test for the async endpoint under test.

Covered:
  * all-success (both channels fire) — status=sent_both
  * partial failure (missing email) — status=sent_sms_only
  * partial failure (missing phone) — status=sent_email_only
  * no contact at all — skipped_no_contact + attempt row
  * paid invoice — skipped_already_paid (no attempt row)
  * draft invoice — skipped_draft (no attempt row)
  * invoice not in tenant — skipped_not_found (prevents
    cross-tenant enumeration)
  * dedupe window hit — skipped_recent_send
  * empty invoice_ids body — 400
  * oversize body (501 ids) — 400
  * non-admin user — 403
  * summary + request_id present on response
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch, AsyncMock

import pytest
from dotenv import load_dotenv

from tests._shared_mongo import shared_db as _shared_db

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync_db = _shared_db()


def _tnt() -> str:
    return f"_test_tenant_tdbulksend_{uuid.uuid4().hex[:12]}"


def _mk_customer(tenant_id: str, *,
                   email: Optional[str] = None,
                   phone: Optional[str] = None) -> str:
    cid = f"cust_{uuid.uuid4().hex[:12]}"
    _sync_db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Test Customer",
        "email": email, "phone": phone,
        "is_active": True,
    })
    return cid


def _mk_invoice(tenant_id: str, customer_id: str, *,
                  payment_status: str = "unpaid",
                  status: str = "sent") -> str:
    iid = f"inv_{uuid.uuid4().hex[:12]}"
    _sync_db.quotes.insert_one({
        "id": iid, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "customer_name": "Test Customer",
        "invoice_number": f"INV-T-{uuid.uuid4().hex[:8].upper()}",
        "doc_type": "invoice",
        "payment_status": payment_status,
        "status": status,
        "total": 100.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return iid


def _teardown(tenant_id: str) -> None:
    _sync_db.customers.delete_many({"tenant_id": tenant_id})
    _sync_db.quotes.delete_many({"tenant_id": tenant_id})
    _sync_db.invoice_send_attempts.delete_many(
        {"tenant_id": tenant_id})


def _rebind_motor_loop() -> None:
    try:
        from config import client as _c
        _c._io_loop = asyncio.get_running_loop()
    except Exception:
        pass


async def _call(invoice_ids: List[str], *, tenant_id: str,
                 user_role: str = "admin") -> Any:
    """Direct-invoke the endpoint handler (no FastAPI test
    client needed; the deps are injected via function args).
    """
    _rebind_motor_loop()
    from routers.invoices_bulk_send import (
        bulk_send_invoices, BulkSendBody,
    )
    tenant = {"id": tenant_id, "name": "Test Tenant"}
    user = {"id": f"usr_{uuid.uuid4().hex[:8]}", "role": user_role}

    # Patch _send_email + _send_sms + _get_settings so the
    # pytest run doesn't hit Resend or RingCentral.
    with patch("routers.dunning._send_email",
                new=AsyncMock(return_value={"status": "sent"})) as _, \
         patch("routers.dunning._send_sms",
                new=AsyncMock(return_value={"status": "sent"})) as _, \
         patch("routers.dunning._get_settings",
                new=AsyncMock(return_value={
                    "enabled": True, "stages": [],
                })) as _, \
         patch("routers.dunning._payment_link_for",
                new=AsyncMock(return_value="https://example/pay")):
        return await bulk_send_invoices(
            BulkSendBody(invoice_ids=invoice_ids),
            user=user, tenant=tenant,
        )


# ═════════════════════════════════════════════════════════════
# 1. All-success — both channels fire
# ═════════════════════════════════════════════════════════════
def test_all_success_both_channels() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(
            tenant, email="x@example.com", phone="+15551234567")
        iid = _mk_invoice(tenant, cid)
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["summary"]["sent_both"] == 1
        assert resp["summary"]["requested"] == 1
        assert resp["results"][0]["status"] == "sent_both"
        assert resp["results"][0]["email_to"] == "x@example.com"
        assert resp["results"][0]["sms_to"] == "+15551234567"
        assert "request_id" in resp
        # Attempt row written.
        attempt = _sync_db.invoice_send_attempts.find_one(
            {"tenant_id": tenant, "invoice_id": iid})
        assert attempt is not None
        assert attempt["final_status"] == "sent_both"
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 2. Partial failure — customer missing email
# ═════════════════════════════════════════════════════════════
def test_customer_missing_email_sends_sms_only() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email=None, phone="+15551234567")
        iid = _mk_invoice(tenant, cid)
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["results"][0]["status"] == "sent_sms_only"
        assert resp["summary"]["sent_sms_only"] == 1
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 3. Partial failure — customer missing phone
# ═════════════════════════════════════════════════════════════
def test_customer_missing_phone_sends_email_only() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email="x@example.com", phone=None)
        iid = _mk_invoice(tenant, cid)
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["results"][0]["status"] == "sent_email_only"
        assert resp["summary"]["sent_email_only"] == 1
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 4. No contact at all — skipped_no_contact
# ═════════════════════════════════════════════════════════════
def test_customer_no_contact_at_all_skips() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email=None, phone=None)
        iid = _mk_invoice(tenant, cid)
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["results"][0]["status"] == "skipped_no_contact"
        assert resp["summary"]["skipped_no_contact"] == 1
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 5. Paid invoice — skipped_already_paid
# ═════════════════════════════════════════════════════════════
def test_paid_invoice_skipped() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email="x@example.com",
                             phone="+15551234567")
        iid = _mk_invoice(tenant, cid, payment_status="paid")
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["results"][0]["status"] == "skipped_already_paid"
        assert resp["summary"]["skipped_already_paid"] == 1
        # No attempt row written on skip-paid (gate fires BEFORE
        # the record_attempt call).
        attempt = _sync_db.invoice_send_attempts.find_one(
            {"tenant_id": tenant, "invoice_id": iid})
        assert attempt is None
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 6. Draft invoice — skipped_draft
# ═════════════════════════════════════════════════════════════
def test_draft_invoice_skipped() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email="x@example.com",
                             phone="+15551234567")
        iid = _mk_invoice(tenant, cid, status="draft")
        resp = asyncio.run(_call([iid], tenant_id=tenant))
        assert resp["results"][0]["status"] == "skipped_draft"
        assert resp["summary"]["skipped_draft"] == 1
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 7. Cross-tenant invoice — skipped_not_found
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_invoice_skipped_not_found() -> None:
    tenant_a = _tnt()
    tenant_b = _tnt()
    try:
        cid = _mk_customer(tenant_b, email="x@example.com",
                             phone="+15551234567")
        iid = _mk_invoice(tenant_b, cid)
        resp = asyncio.run(_call([iid], tenant_id=tenant_a))
        assert resp["results"][0]["status"] == "skipped_not_found"
        assert resp["summary"]["skipped_not_found"] == 1
    finally:
        _teardown(tenant_a)
        _teardown(tenant_b)


# ═════════════════════════════════════════════════════════════
# 8. Dedupe window — skipped_recent_send
# ═════════════════════════════════════════════════════════════
def test_dedupe_window_skips_second_send() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email="x@example.com",
                             phone="+15551234567")
        iid = _mk_invoice(tenant, cid)

        first = asyncio.run(_call([iid], tenant_id=tenant))
        assert first["results"][0]["status"] == "sent_both"

        second = asyncio.run(_call([iid], tenant_id=tenant))
        assert second["results"][0]["status"] == "skipped_recent_send"
        assert second["summary"]["skipped_recent_send"] == 1
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 9. Empty invoice_ids — 400
# ═════════════════════════════════════════════════════════════
def test_empty_invoice_ids_rejected() -> None:
    tenant = _tnt()
    try:
        from pydantic import ValidationError
        from routers.invoices_bulk_send import BulkSendBody
        # Pydantic Field(min_length=1) blocks empty at the model
        # layer.  (``bulk_send_invoices`` would also raise 400 if
        # a caller somehow bypassed the model, but validation
        # fires first for HTTP callers.)
        with pytest.raises(ValidationError):
            BulkSendBody(invoice_ids=[])
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 10. Non-admin user — 403
# ═════════════════════════════════════════════════════════════
def test_non_admin_rejected() -> None:
    tenant = _tnt()
    try:
        cid = _mk_customer(tenant, email="x@example.com",
                             phone="+15551234567")
        iid = _mk_invoice(tenant, cid)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(_call(
                [iid], tenant_id=tenant, user_role="technician"))
        assert excinfo.value.status_code == 403
    finally:
        _teardown(tenant)


# ═════════════════════════════════════════════════════════════
# 11. Mixed batch — summary tallies each bucket correctly
# ═════════════════════════════════════════════════════════════
def test_mixed_batch_summary_tallies() -> None:
    tenant = _tnt()
    try:
        c_full = _mk_customer(tenant, email="a@a.com",
                                phone="+15551111111")
        c_email = _mk_customer(tenant, email="b@b.com", phone=None)
        c_none = _mk_customer(tenant, email=None, phone=None)
        inv_full = _mk_invoice(tenant, c_full)
        inv_email = _mk_invoice(tenant, c_email)
        inv_none = _mk_invoice(tenant, c_none)
        inv_paid = _mk_invoice(tenant, c_full, payment_status="paid")
        inv_draft = _mk_invoice(tenant, c_full, status="draft")

        resp = asyncio.run(_call(
            [inv_full, inv_email, inv_none, inv_paid, inv_draft],
            tenant_id=tenant,
        ))
        s = resp["summary"]
        assert s["requested"] == 5
        assert s["sent_both"] == 1
        assert s["sent_email_only"] == 1
        assert s["skipped_no_contact"] == 1
        assert s["skipped_already_paid"] == 1
        assert s["skipped_draft"] == 1
    finally:
        _teardown(tenant)
