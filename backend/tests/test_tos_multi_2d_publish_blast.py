"""Feb-2026 · Slice 2D — Publish notification blast tests."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.tos_multi as _mod
    _mod.db = fresh_db
    # Ensure the ledger unique index exists so the idempotency guard
    # actually blocks a duplicate ``tos_update:{doc_id}`` insert.
    _LOOP.run_until_complete(
        __import__("services.tos_service", fromlist=["ensure_indexes"])
        .ensure_indexes(fresh_db),
    )
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _tid() -> str:
    return f"TEST_tos2d_{uuid.uuid4().hex[:10]}"


async def _drain(tid: str):
    for coll in ("tos_documents", "customers", "marketing_deliveries",
                  "marketing_event_ledger", "tenants"):
        await _db()[coll].delete_many({"tenant_id": tid})


async def _seed_tenant(tid: str):
    await _db().tenants.insert_one({
        "id": tid, "name": "Test Tenant", "phone": "555-0100",
        "brand_color": "#1f2937",
    })


async def _mk_customer(
    tid: str, *, service_type: str = "", email: str = "c@t.com",
    unsubscribed: bool = False, dnc: bool = False,
) -> str:
    from utils import new_id
    cid = new_id()
    doc = {"id": cid, "tenant_id": tid, "name": "T C", "first_name": "T",
             "email": email, "service_type": service_type}
    if unsubscribed:
        doc["unsubscribed"] = True
    if dnc:
        doc["do_not_contact"] = True
    await _db().customers.insert_one(doc)
    return cid


async def _mk_doc(tid: str, service_type: str, version: int = 1) -> str:
    from utils import new_id, now_iso
    did = new_id()
    await _db().tos_documents.insert_one({
        "id": did, "tenant_id": tid, "service_type": service_type,
        "version": version, "status": "published", "title": "T",
        "content_html": "<p>t</p>", "content_json": None,
        "effective_date": "2026-02-15",
        "created_at": now_iso(), "created_by": "test",
        "published_at": now_iso(), "published_by": "test",
        "superseded_at": None,
    })
    return did


def _stub_resend(monkeypatch, *, raise_it: bool = False):
    calls: List[Dict[str, Any]] = []

    async def _send(*, to, subject, html, sender=None, **kw):
        calls.append({"to": to, "subject": subject, "html": html})
        if raise_it:
            raise RuntimeError("resend outage")
        return {"id": f"re_{uuid.uuid4().hex[:12]}"}

    from services.email import resend_adapter
    monkeypatch.setattr(resend_adapter, "send", _send)
    return calls


async def _run_blast(tid: str, did: str):
    from routers.tos_multi import _run_publish_blast
    doc = await _db().tos_documents.find_one({"id": did}, {"_id": 0})
    tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0})
    await _run_publish_blast(document=doc, tenant=tenant)


# ── 1. Pool publish emails only pool customers ──────────────────────
def test_pool_publish_emails_active_pool_customers(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        c_pool = await _mk_customer(tid, service_type="Weekly Pool Service",
                                        email="pool@x.com")
        c_ls = await _mk_customer(tid, service_type="Landscape Maintenance",
                                      email="ls@x.com")
        did = await _mk_doc(tid, "pool", version=2)
        calls = _stub_resend(monkeypatch)
        try:
            await _run_blast(tid, did)
            recipients = sorted(c["to"] for c in calls)
            assert recipients == ["pool@x.com"], recipients
            rows = await _db().marketing_deliveries.find(
                {"tenant_id": tid}, {"_id": 0},
            ).to_list(50)
            statuses = {r["customer_id"]: r["status"] for r in rows}
            assert statuses.get(c_pool) == "sent"
            assert c_ls not in statuses  # not queried at all
        finally:
            await _drain(tid)
    _run(_go())


# ── 2. Cross-service isolation ──────────────────────────────────────
def test_landscaping_customer_not_emailed_on_pool_publish(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        await _mk_customer(tid, service_type="Lawn Mowing", email="ls@x.com")
        did = await _mk_doc(tid, "pool", version=1)
        calls = _stub_resend(monkeypatch)
        try:
            await _run_blast(tid, did)
            assert calls == []
            rows = await _db().marketing_deliveries.count_documents(
                {"tenant_id": tid},
            )
            assert rows == 0
        finally:
            await _drain(tid)
    _run(_go())


# ── 3. Skip rules ───────────────────────────────────────────────────
def test_skip_rules_logged_with_reason(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        c_none = await _mk_customer(tid, service_type="Pool", email="")
        c_unsub = await _mk_customer(tid, service_type="Pool",
                                        email="u@x.com", unsubscribed=True)
        c_dnc = await _mk_customer(tid, service_type="Pool",
                                      email="d@x.com", dnc=True)
        did = await _mk_doc(tid, "pool", version=1)
        calls = _stub_resend(monkeypatch)
        try:
            await _run_blast(tid, did)
            assert calls == []  # no email sends
            rows = await _db().marketing_deliveries.find(
                {"tenant_id": tid}, {"_id": 0},
            ).to_list(50)
            by_cid = {r["customer_id"]: r for r in rows}
            assert by_cid[c_none]["status"] == "skipped"
            assert by_cid[c_none]["skip_reason"] == "no_email"
            assert by_cid[c_unsub]["skip_reason"] == "unsubscribed"
            assert by_cid[c_dnc]["skip_reason"] == "do_not_contact"
        finally:
            await _drain(tid)
    _run(_go())


# ── 4. Re-publish blocked by ledger key ─────────────────────────────
def test_second_blast_blocked_by_ledger_key(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        await _mk_customer(tid, service_type="Pool", email="p@x.com")
        did = await _mk_doc(tid, "pool", version=1)
        calls = _stub_resend(monkeypatch)
        try:
            await _run_blast(tid, did)
            await _run_blast(tid, did)  # second run
            # Only ONE send, only ONE ledger row.
            assert len(calls) == 1
            n_ledger = await _db().marketing_event_ledger.count_documents(
                {"tenant_id": tid, "event_key": f"tos_update:{did}"},
            )
            assert n_ledger == 1
        finally:
            await _drain(tid)
    _run(_go())


# ── 5. Resend failure — publish stays 200; row marked failed ────────
def test_resend_failure_writes_failed_delivery(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        cid = await _mk_customer(tid, service_type="Pool", email="p@x.com")
        did = await _mk_doc(tid, "pool", version=1)
        _stub_resend(monkeypatch, raise_it=True)
        try:
            # _run_publish_blast MUST NOT raise even when the adapter
            # blows up — the publish endpoint depends on this.
            await _run_blast(tid, did)
            row = await _db().marketing_deliveries.find_one(
                {"tenant_id": tid, "customer_id": cid}, {"_id": 0},
            )
            assert row["status"] == "failed"
            assert row["provider_status"] == "failed"
            assert "resend outage" in (row.get("skip_reason") or "")
        finally:
            await _drain(tid)
    _run(_go())


# ── 6. Cross-scope replay guards ────────────────────────────────────
def test_portal_home_token_rejected_by_all_other_verifiers():
    from services.portal_magic_links import (
        mint_portal_home_token, mint_job_view_token,
        mint_invoice_pay_token, mint_estimate_view_token,
        verify_portal_home_token, verify_job_view_token,
        verify_invoice_pay_token, verify_estimate_view_token,
    )
    from fastapi import HTTPException
    ph = mint_portal_home_token("c1", "t1")
    for other_verify in (verify_job_view_token,
                          verify_invoice_pay_token,
                          verify_estimate_view_token):
        with pytest.raises(HTTPException) as exc:
            other_verify(ph)
        assert exc.value.status_code == 401
        assert exc.value.detail == "token_wrong_scope"
    # Other tokens must also be rejected by verify_portal_home_token.
    for other in (
        mint_job_view_token("c1", "j1", "t1"),
        mint_invoice_pay_token("c1", "i1", "t1"),
        mint_estimate_view_token("c1", "e1", "t1"),
    ):
        with pytest.raises(HTTPException) as exc:
            verify_portal_home_token(other)
        assert exc.value.status_code == 401
        assert exc.value.detail == "token_wrong_scope"


# ── 7. Auto-login route accepts portal_home → /portal/home ──────────
def test_auto_login_route_accepts_portal_home_and_redirects_home():
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        cid = await _mk_customer(tid, service_type="Pool", email="p@x.com")
        from utils import new_id
        await _db().users.insert_one({
            "id": new_id(), "tenant_id": tid, "customer_id": cid,
            "role": "customer", "email": "p@x.com",
        })
        try:
            from services.portal_magic_links import mint_portal_home_token
            from routers.portal_auto_login import portal_auto_login

            class _R:
                headers = {}
                client = type("C", (), {"host": "127.0.0.1"})()

            tok = mint_portal_home_token(cid, tid)
            resp = await portal_auto_login(_R(), t=tok, redirect=None)
            assert resp.status_code == 200
            body = resp.body.decode("utf-8")
            assert "/portal/home" in body
            assert "localStorage.setItem('token'," in body
        finally:
            await _db().users.delete_many({"tenant_id": tid})
            await _drain(tid)
    _run(_go())


# ── 8. Sequential pool + landscaping publish emails a dual-service customer twice ──
def test_dual_service_customer_gets_both_emails(monkeypatch):
    async def _go():
        tid = _tid()
        await _seed_tenant(tid)
        cid = await _mk_customer(
            tid, service_type="Pool", email="dual@x.com",
        )
        # Give this customer BOTH services via the explicit list.
        await _db().customers.update_one(
            {"id": cid}, {"$set": {"service_types": ["pool", "landscaping"]}},
        )
        pool_id = await _mk_doc(tid, "pool", version=1)
        ls_id = await _mk_doc(tid, "landscaping", version=1)
        calls = _stub_resend(monkeypatch)
        try:
            await _run_blast(tid, pool_id)
            await _run_blast(tid, ls_id)
            assert len(calls) == 2
            recipients = [c["to"] for c in calls]
            assert recipients == ["dual@x.com", "dual@x.com"]
            # Two distinct ledger rows.
            n = await _db().marketing_event_ledger.count_documents(
                {"tenant_id": tid,
                 "event_key": {"$in": [
                     f"tos_update:{pool_id}", f"tos_update:{ls_id}"]}},
            )
            assert n == 2
        finally:
            await _drain(tid)
    _run(_go())
