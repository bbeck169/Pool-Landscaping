"""TD-customer-list-bulk-request-card-stripe-setupintent · Feb-2026.

Supersedes test_td_customer_list_bulk_request_card_on_file.py (Ticket I).

Direct-invoke contract tests for the three new endpoints:
  * POST /customers/bulk-request-card-setup-intent  (admin bulk)
  * GET  /card-capture/{token}                      (page bootstrap)
  * POST /card-capture/{token}/confirm              (PM attach)
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
from fastapi import HTTPException

from tests._shared_mongo import shared_db as _shared_db

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
_sync_db = _shared_db()


def _tnt(label: str = "a") -> str:
    return f"_test_tenant_tdcc_{label}_{uuid.uuid4().hex[:10]}"


def _mk_customer(tenant_id: str, *, email: Optional[str] = None,
                   phone: Optional[str] = None) -> str:
    cid = f"cust_{uuid.uuid4().hex[:12]}"
    _sync_db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id, "name": "Test Customer",
        "first_name": "Test", "last_name": "Customer",
        "email": email, "phone": phone, "is_active": True,
    })
    return cid


def _mk_tenant(tid: str) -> None:
    _sync_db.tenants.insert_one({"id": tid, "name": "Test Tenant",
                                  "slug": tid, "active": True})


def _teardown(tenant_ids: List[str]) -> None:
    _sync_db.customers.delete_many({"tenant_id": {"$in": tenant_ids}})
    _sync_db.communications_log.delete_many(
        {"tenant_id": {"$in": tenant_ids}})
    _sync_db.customer_card_capture_tokens.delete_many(
        {"tenant_id": {"$in": tenant_ids}})
    _sync_db.payment_methods.delete_many({"tenant_id": {"$in": tenant_ids}})
    _sync_db.tenants.delete_many({"id": {"$in": tenant_ids}})


def _rebind_motor() -> None:
    try:
        from config import client as _c
        _c._io_loop = asyncio.get_running_loop()
    except Exception:
        pass


_FAKE_SI_RETURN = {"id": "seti_stub",
                    "client_secret": "seti_stub_secret_xyz",
                    "publishable_key": "pk_test_stub"}


async def _bulk(customer_ids: List[str], tenant_id: str,
                 user_role: str = "admin") -> Any:
    _rebind_motor()
    from routers.customers_bulk_card_capture import (
        bulk_request_card_setup_intent, BulkRequestCardSetupBody,
    )
    tenant = {"id": tenant_id, "name": "Test Tenant"}
    user = {"id": f"usr_{uuid.uuid4().hex[:8]}", "role": user_role}

    async def _fake_ensure(tenant_id, customer_id):
        return f"cus_stub_{customer_id[:6]}"

    async def _fake_email(*a, **kw):
        return {"status": "sent", "provider_id": f"em_{uuid.uuid4().hex[:6]}"}

    async def _fake_sms(*a, **kw):
        return {"status": "sent", "provider_id": f"sm_{uuid.uuid4().hex[:6]}"}

    with patch("services.payments.stripe_charge.ensure_stripe_customer",
                new=AsyncMock(side_effect=_fake_ensure)), \
         patch("services.comms_email_adapter.send_email",
                new=AsyncMock(side_effect=_fake_email)), \
         patch("services.sms.rc_adapter.send",
                new=AsyncMock(side_effect=_fake_sms)):
        return await bulk_request_card_setup_intent(
            BulkRequestCardSetupBody(customer_ids=customer_ids),
            user=user, tenant=tenant,
        )


async def _get_ctx(token: str) -> Any:
    _rebind_motor()
    from routers.customers_bulk_card_capture import get_card_capture_context

    async def _fake_si(**kw):
        return _FAKE_SI_RETURN

    with patch("services.payments.stripe_charge.create_setup_intent",
                new=AsyncMock(side_effect=_fake_si)):
        return await get_card_capture_context(token)


async def _confirm(token: str, pm_id: str = "pm_stub_xyz") -> Any:
    _rebind_motor()
    from routers.customers_bulk_card_capture import (
        confirm_card_capture, CardCaptureConfirmBody,
    )

    class _Req:
        client = None
        headers: Dict[str, str] = {}

    return await confirm_card_capture(
        token, CardCaptureConfirmBody(payment_method_id=pm_id), _Req(),
    )


# ─── 403 Preflights ──────────────────────────────────────────────
def test_cross_tenant_customer_id_triggers_403() -> None:
    tnt_a, tnt_b = _tnt("a"), _tnt("b")
    _mk_tenant(tnt_a); _mk_tenant(tnt_b)
    try:
        a = _mk_customer(tnt_a, email="x@td.local")
        b = _mk_customer(tnt_b, email="y@td.local")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_bulk([a, b], tenant_id=tnt_a))
        assert exc.value.status_code == 403
        d = exc.value.detail
        assert d["error"] == "tenant_isolation_breach"
        hits = [e for e in d["errors"] if e.get("customer_id") == b]
        assert hits and hits[0]["reason"] == "foreign_tenant"
    finally:
        _teardown([tnt_a, tnt_b])


def test_orphan_customer_id_triggers_403() -> None:
    tnt = _tnt()
    _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_bulk([a, "orphan-xxxxxxxx"], tenant_id=tnt))
        assert exc.value.status_code == 403
        hits = [e for e in exc.value.detail["errors"]
                 if e.get("customer_id") == "orphan-xxxxxxxx"]
        assert hits and hits[0]["reason"] == "orphan"
    finally:
        _teardown([tnt])


def test_non_admin_rejected() -> None:
    tnt = _tnt()
    _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_bulk([a], tenant_id=tnt, user_role="technician"))
        assert exc.value.status_code == 403
    finally:
        _teardown([tnt])


def test_batch_size_cap_enforced() -> None:
    tnt = _tnt()
    _mk_tenant(tnt)
    try:
        ids = [f"c{i}" for i in range(501)]
        from routers.customers_bulk_card_capture import BulkRequestCardSetupBody
        with pytest.raises(Exception):
            BulkRequestCardSetupBody(customer_ids=ids)
    finally:
        _teardown([tnt])


# ─── Happy path: tokens minted, sends dispatched ─────────────────
def test_bulk_mints_token_per_customer_and_sends_both_channels() -> None:
    tnt = _tnt()
    _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local", phone="+15551112222")
        b = _mk_customer(tnt, email="y@td.local", phone="+15551112223")
        resp = asyncio.run(_bulk([a, b], tenant_id=tnt))
        assert resp["counts"]["email_sent"] == 2
        assert resp["counts"]["sms_sent"] == 2
        toks = list(_sync_db.customer_card_capture_tokens.find(
            {"tenant_id": tnt}))
        assert len(toks) == 2
        assert set(t["customer_id"] for t in toks) == {a, b}
        for t in toks:
            assert t["used_at"] is None
            assert t["token"]
            assert t["expires_at"]
            # Expires ~7 days out.
            exp = datetime.fromisoformat(t["expires_at"])
            created = datetime.fromisoformat(t["created_at"])
            delta = exp - created
            assert timedelta(days=7) - timedelta(seconds=60) <= delta
            assert delta <= timedelta(days=7) + timedelta(seconds=60)
    finally:
        _teardown([tnt])


def test_bulk_handles_email_only_sms_only_and_no_contact() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        e = _mk_customer(tnt, email="e@td.local")
        s = _mk_customer(tnt, phone="+15551110000")
        n = _mk_customer(tnt)
        resp = asyncio.run(_bulk([e, s, n], tenant_id=tnt))
        by = {r["customer_id"]: r for r in resp["results"]}
        assert by[e]["status"] == "sent_email_only"
        assert by[s]["status"] == "sent_sms_only"
        assert by[n]["status"] == "skipped_no_contact"
        # No-contact customer should NOT get a token minted.
        assert _sync_db.customer_card_capture_tokens.count_documents(
            {"customer_id": n}) == 0
    finally:
        _teardown([tnt])


def test_bulk_stripe_create_failure_per_row_degrades() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")

        async def _ensure_fail(tenant_id, customer_id):
            raise RuntimeError("stripe 500")

        async def _fake_email(*a, **k):
            return {"status": "sent", "provider_id": "e"}

        async def _fake_sms(*a, **k):
            return {"status": "sent", "provider_id": "s"}

        async def _run():
            _rebind_motor()
            from routers.customers_bulk_card_capture import (
                bulk_request_card_setup_intent, BulkRequestCardSetupBody,
            )
            with patch("services.payments.stripe_charge.ensure_stripe_customer",
                        new=AsyncMock(side_effect=_ensure_fail)), \
                 patch("services.comms_email_adapter.send_email",
                        new=AsyncMock(side_effect=_fake_email)), \
                 patch("services.sms.rc_adapter.send",
                        new=AsyncMock(side_effect=_fake_sms)):
                return await bulk_request_card_setup_intent(
                    BulkRequestCardSetupBody(customer_ids=[a]),
                    user={"id": "u", "role": "admin"},
                    tenant={"id": tnt, "name": "T"},
                )
        resp = asyncio.run(_run())
        row = resp["results"][0]
        assert row["status"] == "skipped_stripe_customer_create_failed"
        assert "stripe_customer" in row.get("error", "")
    finally:
        _teardown([tnt])


# ─── Capture page: GET, confirm, single-use ─────────────────────
def test_get_capture_context_returns_customer_and_tenant_names() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        asyncio.run(_bulk([a], tenant_id=tnt))
        tok = _sync_db.customer_card_capture_tokens.find_one(
            {"tenant_id": tnt, "customer_id": a})["token"]
        ctx = asyncio.run(_get_ctx(tok))
        assert ctx["customer_first_name"] == "Test"
        assert ctx["tenant_business_name"] == "Test Tenant"
        assert ctx["setup_intent_client_secret"] == "seti_stub_secret_xyz"
        assert ctx["publishable_key"] == "pk_test_stub"
        assert ctx["used"] is False
    finally:
        _teardown([tnt])


def test_confirm_marks_token_used_and_flips_card_on_file() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        asyncio.run(_bulk([a], tenant_id=tnt))
        tok = _sync_db.customer_card_capture_tokens.find_one(
            {"tenant_id": tnt, "customer_id": a})["token"]
        asyncio.run(_get_ctx(tok))   # materialize client_secret
        resp = asyncio.run(_confirm(tok, pm_id="pm_test_zzz"))
        assert resp["ok"] is True
        # Token marked used.
        row = _sync_db.customer_card_capture_tokens.find_one(
            {"token": tok})
        assert row["used_at"]
        # PM mirrored into db.payment_methods.
        pms = list(_sync_db.payment_methods.find(
            {"tenant_id": tnt, "customer_id": a}))
        assert len(pms) == 1
        assert pms[0]["stripe_payment_method_id"] == "pm_test_zzz"
        # Customer row stamped.
        c = _sync_db.customers.find_one({"id": a})
        assert c["stripe_default_payment_method_id"] == "pm_test_zzz"
        assert c["card_on_file_added_at"]
    finally:
        _teardown([tnt])


def test_second_confirm_on_same_token_returns_410() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        asyncio.run(_bulk([a], tenant_id=tnt))
        tok = _sync_db.customer_card_capture_tokens.find_one(
            {"tenant_id": tnt, "customer_id": a})["token"]
        asyncio.run(_get_ctx(tok))
        asyncio.run(_confirm(tok, pm_id="pm_test_1"))
        # Second attempt → 410.
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_confirm(tok, pm_id="pm_test_2"))
        assert exc.value.status_code == 410
        assert exc.value.detail["code"] == "token_already_used"
    finally:
        _teardown([tnt])


def test_expired_token_returns_410() -> None:
    tnt = _tnt(); _mk_tenant(tnt)
    try:
        a = _mk_customer(tnt, email="x@td.local")
        asyncio.run(_bulk([a], tenant_id=tnt))
        tok_doc = _sync_db.customer_card_capture_tokens.find_one(
            {"tenant_id": tnt, "customer_id": a})
        # Clock forward past expiry (7 days + 1 minute).
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        _sync_db.customer_card_capture_tokens.update_one(
            {"token": tok_doc["token"]},
            {"$set": {"expires_at": past.isoformat()}})
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_get_ctx(tok_doc["token"]))
        assert exc.value.status_code == 410
        assert exc.value.detail["code"] == "token_expired"
    finally:
        _teardown([tnt])


def test_unknown_token_returns_404() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_get_ctx("nope-nothing-here-xxxxxxxx"))
    assert exc.value.status_code == 404
