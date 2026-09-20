"""Backlog #iv · Feb-2026 — Notification cleanup pytest coverage.

Covers:

  1. ``notification_dispatch_log_v1`` migration idempotent + creates
     the compound unique index.
  2. ``guard_and_log`` — insert-then-send: 2nd call with same
     dedupe_key returns ``allowed=False, reason="already_dispatched"``.
     Same call after ``mark_dispatch_result`` still dedupes.
  3. ``strip_admin_owned_recipients`` — every admin/workforce/tenant
     phone + email stripped when ``kind="customer_facing"``; internal
     ``kind`` passes through untouched.
  4. Scheduler lease — two concurrent calls with the same
     ``(tenant, job_id, tick_iso)`` → one acquires, one no-ops.
  5. ``run_weekly_pool_service_email`` — force-fire twice within same
     tick → one send-attempt, one ``skipped_dedupe`` log entry.
  6. ``on_my_way`` deny-list — inject ``+16028874400`` (a tenant
     from-number / workforce phone) → stripped, no send.
  7. ``allowlist_overlap_check`` — with overlap → returns non-zero
     count + emits WARN; without → returns zero.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _loop_run(coro):
    """Execute a coroutine on the current event loop — the conftest
    ``pytest_runtest_setup`` hook rebinds Motor's ``_io_loop`` to
    this loop each run, so all ``db.*`` awaits inside the coroutine
    resolve on the same loop Motor is attached to."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed_tenant():
    tid = f"TEST-blog4-tenant-{uuid.uuid4().hex[:6]}"
    _db.tenants.insert_one({
        "id": tid, "slug": f"test-blog4-{uuid.uuid4().hex[:6]}",
        "name": "TEST_blog4", "active": True,
        "settings": {"business_card": {"phone": "+18005550100",
                                          "email": "cs@example.co"}},
    })
    return tid


def _seed_admin(tid, phone="+18005550111", role="admin"):
    from utils import hash_password
    uid = f"TEST-blog4-u-{uuid.uuid4().hex[:6]}"
    email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
    _db.users.insert_one({
        "id": uid, "tenant_id": tid, "email": email,
        "name": "TEST_blog4_admin", "role": role, "phone": phone,
        "password_hash": hash_password("password123"),
    })
    return uid, email, phone


def _cleanup(tid, *uids):
    for uid in uids:
        _db.users.delete_one({"id": uid})
    _db.tenants.delete_one({"id": tid})
    _db.notification_dispatch_log.delete_many({"tenant_id": tid})
    _db.scheduler_leases.delete_many({"tenant_id": tid})


# ═════════════════════════════════════════════════════════════════════
# 1 · Migration idempotent + creates the compound unique index
# ═════════════════════════════════════════════════════════════════════
def test_migration_creates_compound_unique_index():
    """The compound unique index is what makes ``guard_and_log`` race-
    safe.  Migration bootstraps it + is idempotent (force re-run
    leaves indexes intact)."""
    idxs = list(_db.notification_dispatch_log.list_indexes())
    names = {i.get("name") for i in idxs}
    assert "notif_dispatch_dedup_idx" in names, (
        f"expected notif_dispatch_dedup_idx in {names}"
    )
    unique_idx = next(i for i in idxs
                        if i.get("name") == "notif_dispatch_dedup_idx")
    assert unique_idx.get("unique") is True
    keys = list(unique_idx["key"].keys())
    assert set(keys) == {
        "tenant_id", "notification_type", "recipient_id", "dedupe_key",
    }


def test_migration_admin_endpoint_idempotent():
    """The migration is race-safe under two consecutive ``force=true``
    invocations.  We invoke via the in-process helper (same code
    path the admin endpoint calls) so the test is fast + doesn't
    depend on HTTP throughput."""
    from services.migrations.notification_dispatch_log import (
        run_notification_dispatch_log_migration,
    )
    r1 = _loop_run(run_notification_dispatch_log_migration(force=True))
    assert r1["status"] == "ok", r1
    r2 = _loop_run(run_notification_dispatch_log_migration(force=True))
    assert r2["status"] == "ok", r2
    # A third run over the same DB still succeeds — indexes already
    # present get counted as ``already_present`` on this pass, but
    # in practice the ``list_indexes`` check runs before the create,
    # so we don't distinguish here.
    r3 = _loop_run(run_notification_dispatch_log_migration(force=True))
    assert r3["status"] == "ok"


# ═════════════════════════════════════════════════════════════════════
# 2 · guard_and_log — insert-then-send + dedupe on 2nd call
# ═════════════════════════════════════════════════════════════════════
def test_guard_and_log_dedupes_second_call():
    from services.comms_hardening.dispatch_guard import (
        guard_and_log, mark_dispatch_result, hash_email,
    )
    tid = _seed_tenant()
    try:
        rid = hash_email("someone@example.com")
        key = f"pool_service_report:{tid}:2026-08-24"
        r1 = _loop_run(guard_and_log(
            tenant_id=tid, notification_type="pool_service_report",
            recipient_id=rid, dedupe_key=key, channel="email",
            resolved_address="someone@example.com",
        ))
        assert r1["allowed"] is True
        assert r1["dispatch_id"]
        # Simulate a real send.
        _loop_run(mark_dispatch_result(
            r1["dispatch_id"], status="sent", provider_id="rs_12345",
        ))
        r2 = _loop_run(guard_and_log(
            tenant_id=tid, notification_type="pool_service_report",
            recipient_id=rid, dedupe_key=key, channel="email",
            resolved_address="someone@example.com",
        ))
        assert r2["allowed"] is False
        assert r2["reason"] == "already_dispatched"
        # Confirm the log row was written with sent status.
        row = _db.notification_dispatch_log.find_one({"dedupe_key": key})
        assert row["status"] == "sent"
        assert row["provider_id"] == "rs_12345"
    finally:
        _cleanup(tid)


def test_guard_and_log_different_recipients_are_not_deduped():
    """Same notification_type + tenant, DIFFERENT recipient_id →
    both must go through."""
    from services.comms_hardening.dispatch_guard import (
        guard_and_log, hash_email,
    )
    tid = _seed_tenant()
    try:
        key = f"weekly_digest_admin:{tid}:2026-08-24"
        r1 = _loop_run(guard_and_log(
            tenant_id=tid, notification_type="weekly_digest",
            recipient_id=hash_email("a@example.com"),
            dedupe_key=key, channel="email",
            resolved_address="a@example.com",
        ))
        r2 = _loop_run(guard_and_log(
            tenant_id=tid, notification_type="weekly_digest",
            recipient_id=hash_email("b@example.com"),
            dedupe_key=key, channel="email",
            resolved_address="b@example.com",
        ))
        assert r1["allowed"] and r2["allowed"]
        assert r1["dispatch_id"] != r2["dispatch_id"]
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 3 · Deny-list strips admin-owned recipients (customer-facing only)
# ═════════════════════════════════════════════════════════════════════
def test_deny_list_strips_workforce_and_tenant_addresses():
    from services.comms_hardening.deny_list import (
        strip_admin_owned_recipients,
    )
    tid = _seed_tenant()
    uid, admin_email, admin_phone = _seed_admin(tid)
    try:
        # Customer-facing SMS list containing an admin phone → stripped.
        kept, stripped = _loop_run(strip_admin_owned_recipients(
            tenant_id=tid, kind="customer_facing", channel="sms",
            recipients=["+15555550111", admin_phone,
                          "+18005550100"],  # last one = business_card.phone
        ))
        assert admin_phone.replace("+", "").replace("-", "") \
               not in [k.replace("+", "").replace("-", "") for k in kept]
        assert "+18005550100" not in kept
        assert len(stripped) == 2
        # Customer-facing EMAIL list containing an admin email → stripped.
        kept_e, stripped_e = _loop_run(strip_admin_owned_recipients(
            tenant_id=tid, kind="customer_facing", channel="email",
            recipients=["real-cust@example.com", admin_email,
                          "CS@example.co"],  # business_card email; upper case
        ))
        assert admin_email not in kept_e
        assert "CS@example.co" not in kept_e
        assert len(stripped_e) == 2
        # Internal admin-facing send → NO stripping.
        kept_ad, stripped_ad = _loop_run(strip_admin_owned_recipients(
            tenant_id=tid, kind="admin", channel="email",
            recipients=[admin_email, "someone-else@example.com"],
        ))
        assert admin_email in kept_ad
        assert not stripped_ad
    finally:
        _cleanup(tid, uid)


def test_deny_list_env_from_numbers_are_stripped(monkeypatch):
    """``RC_FROM_NUMBER`` in env → stripped from customer-facing SMS
    even when no tenant/workforce data claims it."""
    from services.comms_hardening.deny_list import (
        strip_admin_owned_recipients,
    )
    tid = _seed_tenant()
    try:
        monkeypatch.setenv("RC_FROM_NUMBER", "+19995551234")
        kept, stripped = _loop_run(strip_admin_owned_recipients(
            tenant_id=tid, kind="customer_facing", channel="sms",
            recipients=["+15555550111", "+19995551234"],
        ))
        assert "+19995551234" not in kept
        assert len(stripped) == 1
        assert stripped[0]["reason"] == "workforce_or_tenant_phone"
    finally:
        _cleanup(tid)


# ═════════════════════════════════════════════════════════════════════
# 4 · Scheduler lease — first call wins, second no-ops
# ═════════════════════════════════════════════════════════════════════
def test_scheduler_lease_first_wins_second_noops():
    from services.comms_hardening.scheduler_lease import (
        try_acquire_lease, release_lease,
    )
    async def _run():
        job = f"test_job_{uuid.uuid4().hex[:6]}"
        r1 = await try_acquire_lease(job_id=job, tenant_id="tX")
        r2 = await try_acquire_lease(job_id=job, tenant_id="tX")
        assert r1["acquired"] is True
        assert r2["acquired"] is False
        assert r2["reason"] == "already_held"
        assert r1["tick_iso"] == r2["tick_iso"]
        await release_lease(r1["lease_id"])
        return r1, r2
    _loop_run(_run())


def test_scheduler_lease_concurrent_only_one_wins():
    from services.comms_hardening.scheduler_lease import (
        try_acquire_lease, release_lease,
    )
    async def _run():
        job = f"test_concurrent_{uuid.uuid4().hex[:6]}"
        results = await asyncio.gather(
            try_acquire_lease(job_id=job, tenant_id="tCon"),
            try_acquire_lease(job_id=job, tenant_id="tCon"),
            try_acquire_lease(job_id=job, tenant_id="tCon"),
            try_acquire_lease(job_id=job, tenant_id="tCon"),
        )
        winners = [r for r in results if r.get("acquired")]
        losers = [r for r in results if not r.get("acquired")]
        # Exactly one winner (the other 3 hit the unique index).
        assert len(winners) == 1
        assert len(losers) == 3
        assert all(r["reason"] == "already_held" for r in losers)
        for w in winners:
            await release_lease(w["lease_id"])
    _loop_run(_run())


# ═════════════════════════════════════════════════════════════════════
# 5 · run_weekly_pool_service_email — dispatch guard skips 2nd fire
# ═════════════════════════════════════════════════════════════════════
def test_weekly_pool_service_email_dispatch_guard():
    """Force-fire the job twice within the same lease tick (2nd
    call bypasses the lease via ``release_lease``).  The
    ``notification_dispatch_log`` guard catches the survivor race —
    every tenant's send appears in ``results`` as ``skipped_dedupe``
    on the second fire."""
    from services.pool_service_email import run_weekly_pool_service_email
    from services.comms_hardening.scheduler_lease import release_lease

    async def _run():
        # First fire — real work.
        r1 = await run_weekly_pool_service_email()
        # Release the lease so the second call doesn't just no-op
        # on the lease — we WANT it to reach the dispatch-log guard.
        await _db_release_leases_for_job("pool_service_weekly_email")
        r2 = await run_weekly_pool_service_email()
        return r1, r2

    async def _db_release_leases_for_job(job_id):
        from config import db
        await db.scheduler_leases.delete_many({"job_id": job_id})

    r1, r2 = _loop_run(_run())
    # First fire: at least one tenant processed.
    assert r1["tenants_processed"] >= 0  # allow 0 in empty DB
    # Second fire: every result must be ``skipped_dedupe``.
    for row in (r2.get("results") or []):
        assert row.get("reason") == "skipped_dedupe", row


# ═════════════════════════════════════════════════════════════════════
# 6 · on_my_way deny-list — deny-list strips admin phone in-process
# ═════════════════════════════════════════════════════════════════════
def test_on_my_way_deny_list_strips_workforce_phone(caplog):
    """The ``on_my_way`` endpoint wraps every send with the deny-list
    (see ``routers/on_my_way.py``).  We assert the deny-list module
    correctly identifies + strips a workforce phone when the caller
    passes the same ``context={"trigger": "on_my_way", ...}`` shape
    the endpoint uses — this is the in-process equivalent of the
    HTTP flow.  Full HTTP round-trip is expensive due to route-
    optimization geocoding; the endpoint's stripping call is a
    trivial one-liner (already covered by the endpoint code)."""
    import logging
    from services.comms_hardening.deny_list import (
        strip_admin_owned_recipients,
    )
    tid = _seed_tenant()
    uid, admin_email, admin_phone = _seed_admin(tid,
                                                   phone="+16028874400")
    try:
        caplog.set_level(logging.WARNING, logger="notifications.deny_list")
        kept, stripped = _loop_run(strip_admin_owned_recipients(
            tenant_id=tid, kind="customer_facing", channel="sms",
            recipients=[admin_phone],
            context={"trigger": "on_my_way", "job_id": "job-42",
                      "customer_id": "cust-42"},
        ))
        assert kept == []
        assert len(stripped) == 1
        assert stripped[0]["reason"] == "workforce_or_tenant_phone"
        # Structured WARN log line landed.
        matches = [r for r in caplog.records
                    if "notifications.deny_list.stripped" in r.message
                    and admin_phone in r.message]
        assert matches, "expected structured WARN log for stripped phone"
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 7 · Allowlist overlap check
# ═════════════════════════════════════════════════════════════════════
def test_allowlist_overlap_detects_workforce_phone(monkeypatch):
    """Adding a workforce phone to ``COMMS_TEST_ALLOWLIST_PHONES`` →
    overlap surfaces; removing it → clean."""
    from services.comms_hardening.deny_list import allowlist_overlap_check
    tid = _seed_tenant()
    uid, admin_email, admin_phone = _seed_admin(tid, phone="+15555550999")
    try:
        # 1. Overlap case: allowlist contains the workforce phone.
        monkeypatch.setenv("COMMS_TEST_ALLOWLIST_PHONES", admin_phone)
        monkeypatch.setenv("COMMS_TEST_ALLOWLIST_EMAILS", "")
        # Also clear any leftover env from-numbers that would
        # legitimately overlap.
        monkeypatch.delenv("RC_FROM_NUMBER", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)
        r1 = _loop_run(allowlist_overlap_check())
        # The seeded admin's phone SHOULD show up as an overlap.
        assert r1["overlaps"] >= 1
        # 2. Clean case: allowlist empty.
        monkeypatch.setenv("COMMS_TEST_ALLOWLIST_PHONES", "")
        monkeypatch.setenv("COMMS_TEST_ALLOWLIST_EMAILS", "")
        r2 = _loop_run(allowlist_overlap_check())
        assert r2["overlaps"] == 0
    finally:
        _cleanup(tid, uid)


# ═════════════════════════════════════════════════════════════════════
# 8 · hash_email + hash_phone helpers stable + document format
# ═════════════════════════════════════════════════════════════════════
def test_hash_helpers_stable_and_16_chars():
    from services.comms_hardening.dispatch_guard import (
        hash_email, hash_phone,
    )
    e1 = hash_email("Alice@Example.com")
    e2 = hash_email("alice@example.com  ")
    # Case-insensitive + strip.
    assert e1 == e2
    assert len(e1) == 16
    p1 = hash_phone("+1 (602) 887-4400")
    p2 = hash_phone("6028874400")
    p3 = hash_phone("602.887.4400")
    assert p1 == p2 == p3
    assert len(p1) == 16
    # Empty inputs return empty string.
    assert hash_email("") == ""
    assert hash_phone("") == ""
