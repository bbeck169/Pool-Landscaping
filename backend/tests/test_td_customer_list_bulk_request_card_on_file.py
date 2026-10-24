"""TD-customer-list-bulk-request-card-on-file · Feb-2026.

Backend contract tests for Ticket I's
``POST /api/customers/bulk-request-card``.

Scope (per operator-approved contract):
  * Preflight 403 on cross-tenant customer_id (``foreign_tenant``).
  * Preflight 403 on orphan customer_id (``orphan``).
  * Preflight 403 on cross-tenant template_id (``foreign_tenant``).
  * Role gate: non-admin → 403.
  * Empty customer_ids → 422 (pydantic min_length=1).
  * Per-row dispatch tallies: all-success, email-only, SMS-only,
    no-contact, mixed batch.
  * ``communications_log`` writes carry ``tenant_id`` + the
    ``customer_bulk_request_card`` trigger kind on both channels.

Uses the direct-invoke pattern from
``test_td_invoice_list_bulk_send`` (sync pymongo seed +
``asyncio.run`` on the handler + ``unittest.mock.patch`` around
the adapters) so tests don't hit Resend / RingCentral.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch, AsyncMock

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

from tests._shared_mongo import shared_db as _shared_db

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_sync_db = _shared_db()


def _tnt(label: str = "a") -> str:
    return f"_test_tenant_tdrcf_{label}_{uuid.uuid4().hex[:10]}"


def _mk_customer(tenant_id: str, *,
                   email: Optional[str] = None,
                   phone: Optional[str] = None) -> str:
    cid = f"cust_{uuid.uuid4().hex[:12]}"
    _sync_db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Test Customer",
        "first_name": "Test", "last_name": "Customer",
        "email": email, "phone": phone,
        "is_active": True,
    })
    return cid


def _mk_template(tenant_id: str, channel: str, *,
                   code: Optional[str] = None,
                   body: str = "Hi {{CUSTOMER_FIRST_NAME}}, please add a card.") -> str:
    tid = f"tpl_{uuid.uuid4().hex[:12]}"
    _sync_db.marketing_templates.insert_one({
        "id": tid, "tenant_id": tenant_id,
        "channel": channel, "name": f"Test {channel} template",
        "code": code,
        "subject": "Please add a card on file" if channel == "email" else None,
        "body": body, "active": True, "system": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return tid


def _teardown(tenant_ids: List[str]) -> None:
    _sync_db.customers.delete_many({"tenant_id": {"$in": tenant_ids}})
    _sync_db.marketing_templates.delete_many({"tenant_id": {"$in": tenant_ids}})
    _sync_db.communications_log.delete_many({"tenant_id": {"$in": tenant_ids}})


def _rebind_motor_loop() -> None:
    try:
        from config import client as _c
        _c._io_loop = asyncio.get_running_loop()
    except Exception:
        pass


async def _call(*, customer_ids: List[str], tenant_id: str,
                 email_template_id: Optional[str] = None,
                 sms_template_id: Optional[str] = None,
                 user_role: str = "admin") -> Any:
    """Direct-invoke the endpoint handler.  Adapters stubbed so the
    pytest run doesn't hit Resend or RingCentral.
    """
    _rebind_motor_loop()
    from routers.customers_bulk_request_card import (
        bulk_request_card_on_file, BulkRequestCardBody,
    )
    tenant = {"id": tenant_id, "name": "Test Tenant"}
    user = {"id": f"usr_{uuid.uuid4().hex[:8]}", "role": user_role}

    async def _fake_email(tenant_id, to, *, subject, html,
                          attachments=None, context=None):
        return {"status": "sent",
                "provider_id": f"stub-{uuid.uuid4().hex[:6]}"}

    async def _fake_sms(*args, **kwargs):
        return {"status": "sent",
                "provider_id": f"stub-{uuid.uuid4().hex[:6]}"}

    with patch("services.comms_email_adapter.send_email",
                new=AsyncMock(side_effect=_fake_email)), \
         patch("services.sms.rc_adapter.send",
                new=AsyncMock(side_effect=_fake_sms)):
        return await bulk_request_card_on_file(
            BulkRequestCardBody(
                customer_ids=customer_ids,
                email_template_id=email_template_id,
                sms_template_id=sms_template_id,
            ),
            user=user, tenant=tenant,
        )


# ═════════════════════════════════════════════════════════════
# 403 Preflights
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_customer_id_triggers_preflight_403() -> None:
    tnt_a, tnt_b = _tnt("a"), _tnt("b")
    try:
        cid_a = _mk_customer(tnt_a, email="x@td.local")
        cid_b = _mk_customer(tnt_b, email="y@td.local")
        tpl_a_email = _mk_template(tnt_a, "email")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_call(
                customer_ids=[cid_a, cid_b],
                tenant_id=tnt_a,
                email_template_id=tpl_a_email,
            ))
        assert exc.value.status_code == 403
        detail = exc.value.detail
        assert detail["error"] == "tenant_isolation_breach"
        hits = [e for e in detail["errors"]
                 if e.get("customer_id") == cid_b]
        assert hits and hits[0]["reason"] == "foreign_tenant"
        assert hits[0]["tenant_id"] == tnt_b
    finally:
        _teardown([tnt_a, tnt_b])


def test_orphan_customer_id_triggers_preflight_403() -> None:
    tnt = _tnt()
    try:
        cid_real = _mk_customer(tnt, email="x@td.local")
        cid_orphan = f"orphan_{uuid.uuid4().hex[:12]}"
        tpl = _mk_template(tnt, "email")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_call(
                customer_ids=[cid_real, cid_orphan],
                tenant_id=tnt, email_template_id=tpl,
            ))
        assert exc.value.status_code == 403
        detail = exc.value.detail
        hits = [e for e in detail["errors"]
                 if e.get("customer_id") == cid_orphan]
        assert hits and hits[0]["reason"] == "orphan"
    finally:
        _teardown([tnt])


def test_cross_tenant_template_id_triggers_preflight_403() -> None:
    tnt_a, tnt_b = _tnt("a"), _tnt("b")
    try:
        cid_a = _mk_customer(tnt_a, email="x@td.local")
        tpl_b_email = _mk_template(tnt_b, "email")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_call(
                customer_ids=[cid_a], tenant_id=tnt_a,
                email_template_id=tpl_b_email,
            ))
        assert exc.value.status_code == 403
        detail = exc.value.detail
        hits = [e for e in detail["errors"]
                 if e.get("template_id") == tpl_b_email]
        assert hits and hits[0]["reason"] == "foreign_tenant"
    finally:
        _teardown([tnt_a, tnt_b])


def test_orphan_template_id_triggers_preflight_403() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email="x@td.local")
        orphan_tpl = f"tpl_orphan_{uuid.uuid4().hex[:10]}"
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_call(
                customer_ids=[cid], tenant_id=tnt,
                email_template_id=orphan_tpl,
            ))
        assert exc.value.status_code == 403
        detail = exc.value.detail
        hits = [e for e in detail["errors"]
                 if e.get("template_id") == orphan_tpl]
        assert hits and hits[0]["reason"] == "orphan"
    finally:
        _teardown([tnt])


# ═════════════════════════════════════════════════════════════
# Role gate
# ═════════════════════════════════════════════════════════════
def test_non_admin_role_returns_403() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email="x@td.local")
        tpl = _mk_template(tnt, "email")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_call(
                customer_ids=[cid], tenant_id=tnt,
                email_template_id=tpl, user_role="technician",
            ))
        assert exc.value.status_code == 403
    finally:
        _teardown([tnt])


def test_empty_customer_ids_rejected_by_pydantic() -> None:
    from routers.customers_bulk_request_card import BulkRequestCardBody
    with pytest.raises(Exception):
        BulkRequestCardBody(customer_ids=[])


# ═════════════════════════════════════════════════════════════
# Per-row dispatch tallies
# ═════════════════════════════════════════════════════════════
def test_all_success_batch_logs_both_channels() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email="x@td.local", phone="+15551234567")
        tpl_e = _mk_template(tnt, "email")
        tpl_s = _mk_template(tnt, "sms",
                             body="{{TENANT_NAME}}: please add a card.")
        resp = asyncio.run(_call(
            customer_ids=[cid], tenant_id=tnt,
            email_template_id=tpl_e, sms_template_id=tpl_s,
        ))
        assert resp["counts"]["email_sent"] == 1
        assert resp["counts"]["sms_sent"] == 1
        row = resp["results"][0]
        assert row["status"] == "sent_both"
        assert row["email_status"] == "sent"
        assert row["sms_status"] == "sent"
        # communications_log carries tenant_id + the trigger kind.
        logs = list(_sync_db.communications_log.find(
            {"tenant_id": tnt, "customer_id": cid,
             "trigger_entity.kind": "customer_bulk_request_card"}))
        assert len(logs) == 2
        assert sorted(l["channel"] for l in logs) == ["email", "sms"]
        for l in logs:
            assert l["tenant_id"] == tnt
            assert l["direction"] == "outbound"
    finally:
        _teardown([tnt])


def test_email_only_customer_sends_email_only() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email="x@td.local", phone=None)
        tpl_e = _mk_template(tnt, "email")
        tpl_s = _mk_template(tnt, "sms")
        resp = asyncio.run(_call(
            customer_ids=[cid], tenant_id=tnt,
            email_template_id=tpl_e, sms_template_id=tpl_s,
        ))
        assert resp["results"][0]["status"] == "sent_email_only"
        assert resp["results"][0]["email_status"] == "sent"
        assert resp["results"][0]["sms_status"] == "skipped"
    finally:
        _teardown([tnt])


def test_sms_only_customer_sends_sms_only() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email=None, phone="+15551234567")
        tpl_e = _mk_template(tnt, "email")
        tpl_s = _mk_template(tnt, "sms")
        resp = asyncio.run(_call(
            customer_ids=[cid], tenant_id=tnt,
            email_template_id=tpl_e, sms_template_id=tpl_s,
        ))
        assert resp["results"][0]["status"] == "sent_sms_only"
        assert resp["results"][0]["email_status"] == "skipped"
        assert resp["results"][0]["sms_status"] == "sent"
    finally:
        _teardown([tnt])


def test_no_contact_customer_marked_skipped() -> None:
    tnt = _tnt()
    try:
        cid = _mk_customer(tnt, email=None, phone=None)
        tpl_e = _mk_template(tnt, "email")
        tpl_s = _mk_template(tnt, "sms")
        resp = asyncio.run(_call(
            customer_ids=[cid], tenant_id=tnt,
            email_template_id=tpl_e, sms_template_id=tpl_s,
        ))
        assert resp["results"][0]["status"] == "skipped_no_contact"
        assert resp["counts"]["skipped"] == 1
    finally:
        _teardown([tnt])


def test_mixed_batch_per_row_tallies() -> None:
    tnt = _tnt()
    try:
        c_full  = _mk_customer(tnt, email="full@td.local",  phone="+15551110001")
        c_email = _mk_customer(tnt, email="email@td.local", phone=None)
        c_sms   = _mk_customer(tnt, email=None,             phone="+15551110002")
        c_blank = _mk_customer(tnt, email=None,             phone=None)
        tpl_e = _mk_template(tnt, "email")
        tpl_s = _mk_template(tnt, "sms")
        resp = asyncio.run(_call(
            customer_ids=[c_full, c_email, c_sms, c_blank],
            tenant_id=tnt,
            email_template_id=tpl_e, sms_template_id=tpl_s,
        ))
        by_cid = {r["customer_id"]: r for r in resp["results"]}
        assert by_cid[c_full]["status"]  == "sent_both"
        assert by_cid[c_email]["status"] == "sent_email_only"
        assert by_cid[c_sms]["status"]   == "sent_sms_only"
        assert by_cid[c_blank]["status"] == "skipped_no_contact"
        # Rollups.
        assert resp["counts"]["email_sent"] == 2
        assert resp["counts"]["sms_sent"]   == 2
        assert resp["counts"]["skipped"]    == 1
        assert resp["counts"]["error"]      == 0
    finally:
        _teardown([tnt])
