"""Feb-2026 · Part B · Door-hanger auto-send on job completion.

Contract under test
===================
* Fires on ``previous_status != "completed"`` → ``new_status == "completed"``.
* Exactly ONE ``marketing_event_ledger`` row + ONE
  ``marketing_deliveries`` row per job.
* Silently skips when: no email, ``customer.unsubscribed``,
  ``customer.do_not_contact``, or a matching ``subscribers`` row has
  ``status="unsubscribed"``.  Skip cases still stamp the ledger
  ``sent`` so we do NOT retry on subsequent completions.
* Manual ``POST /api/jobs/{jid}/email-door-hanger`` bypasses the
  auto-send ledger key.
* Never raises out of the completion write path — a Resend outage
  MUST NOT cause the completion API to 500.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict

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
    import routers.workstream_service_log as _mod
    _mod.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _mk_customer(tenant_id: str, *, email: str | None = "kaylan@example.com",
                       extra: Dict[str, Any] | None = None) -> str:
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": cid, "tenant_id": tenant_id,
        "name": "Kaylan Testcase",
        "first_name": "Kaylan", "last_name": "Testcase",
        "email": email,
        "phone": "+15555550100",
    }
    if extra:
        doc.update(extra)
    await _db().customers.insert_one(doc)
    return cid


async def _mk_job(tenant_id: str, cid: str, *, status: str = "pending") -> str:
    from utils import now_iso
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "customer_name": "Kaylan Testcase",
        "service_type": "Weekly Pool Service",
        "status": status, "scheduled_date": now_iso(),
        "title": "Weekly Pool", "created_at": now_iso(),
    })
    return jid


async def _drain(tenant_id: str, jid: str, cid: str) -> None:
    for coll in ("jobs", "service_reports", "customers",
                 "marketing_deliveries", "marketing_event_ledger",
                 "subscribers"):
        try:
            await _db()[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [{"id": jid}, {"id": cid}, {"job_id": jid},
                         {"customer_id": cid},
                         {"trigger_entity.id": jid},
                         {"correlation_id": jid}]},
            )
        except Exception:
            pass


def _stub_email_send(monkeypatch) -> Dict[str, Any]:
    """Replace ``services.email.resend_adapter.send`` with a stub that
    records the LAST call's kwargs and returns a mock envelope."""
    from services.email import resend_adapter as _resend
    captured: Dict[str, Any] = {"call_count": 0, "last": None}

    async def _fake_send(**kwargs):
        captured["call_count"] += 1
        captured["last"] = kwargs
        return {"provider": "mock", "provider_status": "mocked",
                "provider_response_id": None, "attempts": 1, "error": None}

    monkeypatch.setattr(_resend, "send", _fake_send, raising=True)
    return captured


async def _ledger_count(tenant_id: str, jid: str) -> int:
    return await _db().marketing_event_ledger.count_documents({
        "tenant_id": tenant_id, "event_key": f"door_hanger_auto:{jid}",
    })


async def _delivery_count(tenant_id: str, jid: str, *,
                          actor: str | None = None,
                          status: str | None = None) -> int:
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "trigger_entity.kind": "job_door_hanger",
        "trigger_entity.id": jid,
    }
    if actor is not None:
        q["actor"] = actor
    if status is not None:
        q["provider_status"] = status
    return await _db().marketing_deliveries.count_documents(q)


# ═════════════════════════════════════════════════════════════════════
# 1. Happy path — first pending→completed fires exactly once.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_fires_exactly_once_on_first_completion(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            # Simulate the completion write path — flip status THEN
            # invoke the helper the same way the routers do.
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r = await maybe_auto_send_door_hanger(jid, tid)
            assert r["status"] == "sent", r

            assert await _ledger_count(tid, jid) == 1
            assert await _delivery_count(tid, jid, actor="auto") == 1
            # The Resend adapter got called exactly once with the
            # customer's email.
            assert captured["call_count"] == 1
            assert captured["last"]["to"] == "kaylan@example.com"
            assert captured["last"]["category"] == "transactional"
            # Confirm the shared builder ran (Part-A copy sanity).
            assert "your visit has been completed" in captured["last"]["html"]
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Idempotency — a second completion fires ZERO extra emails.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_is_idempotent_across_repeat_completions(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r1 = await maybe_auto_send_door_hanger(jid, tid)
            r2 = await maybe_auto_send_door_hanger(jid, tid)
            assert r1["status"] == "sent"
            assert r2["status"] == "skipped"
            assert r2["reason"] == "already_sent"

            assert await _ledger_count(tid, jid) == 1
            assert await _delivery_count(tid, jid, actor="auto") == 1
            assert captured["call_count"] == 1
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. could_not_service → NO auto-send.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_skips_could_not_service(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            # A tech marks the job could_not_service (NOT completed).
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "could_not_service"}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r = await maybe_auto_send_door_hanger(jid, tid)
            assert r["status"] == "skipped"
            assert r["reason"] == "status_not_completed"
            assert await _ledger_count(tid, jid) == 0
            assert await _delivery_count(tid, jid) == 0
            assert captured["call_count"] == 0
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. Customer with NO email → ledger sent, delivery=skipped, no send.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_no_email_records_skip_and_marks_ledger(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid, email=None)
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r = await maybe_auto_send_door_hanger(jid, tid)
            assert r["status"] == "skipped"
            assert r["reason"] == "no_email"
            # Ledger row exists — we must NOT retry.
            assert await _ledger_count(tid, jid) == 1
            # A delivery row was written with the skip reason.
            assert await _delivery_count(
                tid, jid, actor="auto", status="skipped") == 1
            # Resend was never called.
            assert captured["call_count"] == 0
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5a. customer.unsubscribed=True → skip.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_skips_when_customer_unsubscribed(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid, extra={"unsubscribed": True})
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r = await maybe_auto_send_door_hanger(jid, tid)
            assert r["status"] == "skipped"
            assert r["reason"] == "customer_unsubscribed"
            assert await _ledger_count(tid, jid) == 1
            assert await _delivery_count(
                tid, jid, actor="auto", status="skipped") == 1
            assert captured["call_count"] == 0
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5b. customer.do_not_contact=True → skip.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_skips_when_customer_do_not_contact(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid, extra={"do_not_contact": True})
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import maybe_auto_send_door_hanger
            r = await maybe_auto_send_door_hanger(jid, tid)
            assert r["status"] == "skipped"
            assert r["reason"] == "customer_do_not_contact"
            assert await _ledger_count(tid, jid) == 1
            assert await _delivery_count(
                tid, jid, actor="auto", status="skipped") == 1
            assert captured["call_count"] == 0
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 6. Manual endpoint after auto-send → still delivers.
# ═════════════════════════════════════════════════════════════════════
def test_manual_endpoint_is_not_blocked_by_auto_ledger(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_job(tid, cid, status="pending")
        captured = _stub_email_send(monkeypatch)
        try:
            from utils import now_iso
            await _db().jobs.update_one(
                {"id": jid, "tenant_id": tid},
                {"$set": {"status": "completed", "completed_at": now_iso()}},
            )
            from routers.workstream_service_log import (
                maybe_auto_send_door_hanger, email_door_hanger,
            )
            r_auto = await maybe_auto_send_door_hanger(jid, tid)
            assert r_auto["status"] == "sent"

            # Manual send AFTER auto → NOT blocked by the auto ledger.
            user = await _db().users.find_one(
                {"email": "admin@aquaterra.com"}, {"_id": 0},
            )
            tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0})
            r_manual = await email_door_hanger(jid, user=user, tenant=tenant)
            assert r_manual.get("ok") is True, r_manual

            # Ledger still shows ONE auto row; deliveries shows one
            # auto + one manual row.
            assert await _ledger_count(tid, jid) == 1
            assert await _delivery_count(tid, jid, actor="auto") == 1
            assert await _delivery_count(tid, jid, actor="manual") == 1
            assert captured["call_count"] == 2
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 7. Helper crash MUST NOT bubble up → schedule wrapper never raises.
# ═════════════════════════════════════════════════════════════════════
def test_auto_send_helper_never_raises_on_internal_error(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_job(tid, cid, status="completed")
        try:
            # Sabotage the internal builder so it raises — the outer
            # ``maybe_auto_send_door_hanger`` MUST swallow it.
            import routers.workstream_service_log as _mod

            async def _boom(**kwargs):  # noqa: ANN001, ANN201
                raise RuntimeError("simulated builder crash")

            monkeypatch.setattr(_mod, "_compose_and_send_door_hanger", _boom)

            r = await _mod.maybe_auto_send_door_hanger(jid, tid)
            # Either "error" (build phase crashed) or "sent"/"skipped" —
            # the contract is only that it does NOT raise.
            assert isinstance(r, dict)
            assert "status" in r
            assert r["status"] in {"error", "skipped", "sent"}
        finally:
            await _drain(tid, jid, cid)

    _run(_go())
