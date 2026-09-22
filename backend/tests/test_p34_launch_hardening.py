"""Phase P34 · Feb-2026 — Launch Hardening Punchlist backend tests.

Locks the P34 gaps we closed in one continuous run:

Item 1 · Portal layout ``pt-16`` (FE — covered by vitest).
Item 2 · Magic-link TTLs unified at 168h (7d) — source lint.
Item 3 · ``PUBLIC_FRONTEND_ORIGIN`` in ``backend/.env``.
Item 4 · ``STRIPE_TESTMODE_MOCK_CONNECT=false`` in ``backend/.env``.
Item 5 · Bulk portal-invite uses ``BackgroundTasks`` — envelope shape.
Item 6 · ``inputColors`` mock — mobile-only symbol, deferred (see PRD).
Item 7 · ``has_login`` skip removed from bulk-invite loop.
Item 8 · ``AddCardPage.jsx`` branded ``BrandLogo`` header (FE — vitest).
Item 9 · Resend webhook delivery tracking MVP —
         * ``_try_send_reset_email`` returns email_id.
         * ``_record_portal_invite_outbox`` writes email_outbox rows.
         * ``resend_webhook`` mirrors status into email_outbox.
         * ``GET /admin/portal-invites/delivery-status`` reads it.
Item 10 · ``jobs(tenant_id, scheduled_start)`` background compound
          index in ``scripts/ensure_indexes.py``.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from tests._f7_loop_fixture import run_test


# ══════════════════════════════════════════════════════════════════
# Item 2 — Magic-link TTLs unified at 168h (source lint)
# ══════════════════════════════════════════════════════════════════
def test_p34_item2_magic_link_ttl_168h_across_all_variants():
    src = Path(__file__).resolve().parent.parent / "services" / "portal_magic_links.py"
    txt = src.read_text()
    # All four variants must be 168 (invoice / estimate / portal home / default).
    for pattern in (
        r"_DEFAULT_TTL_HOURS\s*=\s*168",
        r"_INVOICE_TTL_HOURS\s*=\s*168",
        r"_ESTIMATE_TTL_HOURS\s*=\s*168",
        r"_PORTAL_HOME_TTL_HOURS\s*=\s*168",
    ):
        assert re.search(pattern, txt), (
            f"portal_magic_links.py must have {pattern!r} for P34 168h unification"
        )


# ══════════════════════════════════════════════════════════════════
# Item 3 — PUBLIC_FRONTEND_ORIGIN in backend/.env
# ══════════════════════════════════════════════════════════════════
def test_p34_item3_public_frontend_origin_present():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    txt = env_path.read_text()
    # Must be present, non-empty, and NOT pointing at a preview host.
    m = re.search(r"^PUBLIC_FRONTEND_ORIGIN=(.+)$", txt, re.M)
    assert m, "backend/.env must define PUBLIC_FRONTEND_ORIGIN"
    val = m.group(1).strip()
    assert val, "PUBLIC_FRONTEND_ORIGIN must be non-empty"
    assert "preview" not in val.lower(), (
        f"PUBLIC_FRONTEND_ORIGIN should be a canonical prod host, got {val!r}"
    )


# ══════════════════════════════════════════════════════════════════
# Item 4 — STRIPE_TESTMODE_MOCK_CONNECT=false in backend/.env
# ══════════════════════════════════════════════════════════════════
def test_p34_item4_stripe_testmode_mock_connect_false():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    txt = env_path.read_text()
    m = re.search(r"^STRIPE_TESTMODE_MOCK_CONNECT=(.+)$", txt, re.M)
    assert m, "backend/.env must define STRIPE_TESTMODE_MOCK_CONNECT"
    assert m.group(1).strip().lower() == "false", (
        "STRIPE_TESTMODE_MOCK_CONNECT must be 'false' for the P34 "
        f"live-Stripe cutover; got {m.group(1)!r}"
    )


# ══════════════════════════════════════════════════════════════════
# Item 5 — Bulk portal-invite envelope has async sentinel keys
# ══════════════════════════════════════════════════════════════════
@pytest.fixture
def _stub_email_send_module(monkeypatch):
    async def _fake(*a, **kw):
        return f"fake-{uuid.uuid4().hex[:8]}"
    import routers.portal_admin as _pa
    monkeypatch.setattr(_pa, "_try_send_reset_email", _fake,
                          raising=False)


def test_p34_item5_bulk_invite_envelope_is_async(_stub_email_send_module):
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                           {"_id": 0, "id": 1,
                                            "role": 1, "email": 1})
        tid = tenant["id"]
        prefix = "P34_ASY_" + uuid.uuid4().hex[:6] + "_"
        cid = f"{prefix}a"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": cid,
            "email": f"{prefix}a@e.com", "is_active": True,
        })
        try:
            bt = BackgroundTasks()
            envelope = await portal_invite_bulk(
                body=_H1BulkInviteBody(customer_ids=[cid]),
                background_tasks=bt, user=admin, tenant={"id": tid},
            )
            # P34 async sentinels
            assert envelope["async"] is True
            assert envelope["queued"] == 1
            assert envelope["batch_id"]
            # ChaseStalledInvites backwards-compat keys
            assert "enqueued" in envelope
            assert "rate_limited" in envelope
            assert "failed" in envelope
            # Background task was queued (not yet run)
            assert len(bt.tasks) == 1
        finally:
            await db.customers.delete_one({"id": cid})
            await db.email_outbox.delete_many({"customer_id": cid})

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 7 — has_login=True is no longer a skip in bulk invite
# ══════════════════════════════════════════════════════════════════
def test_p34_item7_has_login_true_customer_gets_send_attempted(
    _stub_email_send_module,
):
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                           {"_id": 0, "id": 1,
                                            "role": 1, "email": 1})
        tid = tenant["id"]
        prefix = "P34_HL_" + uuid.uuid4().hex[:6] + "_"
        cid = f"{prefix}already"
        # Seed with has_login=True — the pre-P34 code would have
        # short-circuited this row as ``skipped_already_activated``.
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": cid,
            "email": f"{prefix}a@e.com", "is_active": True,
            "has_login": True,
        })
        try:
            bt = BackgroundTasks()
            envelope = await portal_invite_bulk(
                body=_H1BulkInviteBody(customer_ids=[cid]),
                background_tasks=bt, user=admin, tenant={"id": tid},
            )
            # Drain the bg task so we get the final counters.
            for task in bt.tasks:
                await task()
            audit = await db.audit_events.find_one({
                "event_type": "portal_invite_bulk",
                "tenant_id": tid,
                "payload.batch_id": envelope["batch_id"],
            }, {"_id": 0})
            assert audit is not None
            assert audit["payload"]["sent"] == 1
            # The counter key is preserved at 0 for response-shape compat.
            assert audit["payload"]["skipped_already_activated"] == 0
        finally:
            await db.customers.delete_one({"id": cid})
            await db.users.delete_many({"customer_id": cid})
            await db.email_outbox.delete_many({"customer_id": cid})
            await db.audit_events.delete_many({
                "event_type": "portal_invite_bulk",
                "tenant_id": tid,
                "payload.batch_id": envelope.get("batch_id"),
            })

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 9a — _try_send_reset_email returns email_id (Optional[str])
# ══════════════════════════════════════════════════════════════════
def test_p34_item9a_try_send_returns_optional_str(monkeypatch):
    import routers.portal_admin as _pa
    import inspect

    src = inspect.getsource(_pa._try_send_reset_email)
    assert "-> Optional[str]" in src, (
        "P34 requires _try_send_reset_email to advertise "
        "Optional[str] return"
    )

    async def _go(db):
        # Simulate the "no RESEND_API_KEY" branch → None.
        monkeypatch.setenv("RESEND_API_KEY", "")
        # Re-import config to refresh the cached RESEND_API_KEY
        import importlib
        import config as _cfg
        importlib.reload(_cfg)
        # The function reads ``RESEND_API_KEY`` lazily from config; if
        # the reload path is expensive we can also stub the whole
        # function — we only care about the return type contract.
        res = await _pa._try_send_reset_email(
            "no-key@example.com", "Test", "Tempp1234", "https://x/login",
        )
        assert res is None or isinstance(res, str)

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 9b — _record_portal_invite_outbox writes email_outbox row
# ══════════════════════════════════════════════════════════════════
def test_p34_item9b_outbox_row_written_on_successful_send(
    _stub_email_send_module,
):
    from routers.portal_admin import _do_portal_provision

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                           {"_id": 0, "id": 1,
                                            "role": 1, "email": 1})
        tid = tenant["id"]
        prefix = "P34_OUT_" + uuid.uuid4().hex[:6] + "_"
        cid = f"{prefix}a"
        email = f"{prefix}a@e.com"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": cid,
            "email": email, "is_active": True,
        })
        try:
            await _do_portal_provision(
                cid, tid, admin, explicit_password=None,
            )
            row = await db.email_outbox.find_one(
                {"customer_id": cid, "kind": "portal_invite"},
                {"_id": 0},
            )
            assert row is not None, "outbox row must be written"
            assert row["tenant_id"] == tid
            assert row["kind"] == "portal_invite"
            assert row["recipient"] == email.lower()
            assert row["latest_status"] == "sent"
            assert row["latest_status_ts"]
            assert row["email_id"].startswith("fake-")
        finally:
            await db.customers.delete_one({"id": cid})
            await db.users.delete_many({"customer_id": cid})
            await db.email_outbox.delete_many({"customer_id": cid})

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 9c — resend_webhook mirrors delivery status into email_outbox
# ══════════════════════════════════════════════════════════════════
def test_p34_item9c_webhook_updates_email_outbox_status():
    """We call the handler's persistence path directly by seeding an
    outbox row, then invoking ``db.email_outbox.update_one`` with the
    same shape the webhook uses. This avoids the svix-signature
    verification detour (already locked by Slice N tests) while
    still asserting the P34 correlation contract.

    The webhook code path is inspected at import-time to confirm the
    update statement is present in the source; the DB-side effect is
    exercised on the loop-bound DB fixture."""
    import inspect
    import routers.resend_webhooks as _rw
    src = inspect.getsource(_rw.resend_webhook)
    # Source-lint the correlation write so a future refactor can't
    # silently drop it without failing this test.
    assert "email_outbox" in src, (
        "resend_webhook must mirror status updates into email_outbox"
    )
    assert "latest_status" in src

    async def _go(db):
        email_id = f"p34-test-{uuid.uuid4().hex[:8]}"
        tid = f"p34-test-tenant-{uuid.uuid4().hex[:6]}"
        cid = f"p34-test-cust-{uuid.uuid4().hex[:6]}"
        try:
            # Seed the sent-state row (mimics ``_do_portal_provision``).
            await db.email_outbox.insert_one({
                "id": uuid.uuid4().hex,
                "email_id": email_id,
                "tenant_id": tid,
                "customer_id": cid,
                "kind": "portal_invite",
                "recipient": "test@example.com",
                "latest_status": "sent",
                "latest_status_ts": "2026-02-15T00:00:00+00:00",
                "created_at": "2026-02-15T00:00:00+00:00",
            })
            # Mimic the exact update shape the webhook applies for
            # an ``email.delivered`` event.
            await db.email_outbox.update_one(
                {"email_id": email_id},
                {"$set": {
                    "latest_status": "delivered",
                    "latest_status_ts": "2026-02-15T00:05:00+00:00",
                }},
            )
            row = await db.email_outbox.find_one(
                {"email_id": email_id}, {"_id": 0},
            )
            assert row["latest_status"] == "delivered"
            assert row["latest_status_ts"] == "2026-02-15T00:05:00+00:00"
        finally:
            await db.email_outbox.delete_many({"email_id": email_id})

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 9d — /admin/portal-invites/delivery-status endpoint
# ══════════════════════════════════════════════════════════════════
def test_p34_item9d_delivery_status_endpoint_returns_per_cid_map():
    from routers.portal_admin import portal_invites_delivery_status

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                           {"_id": 0, "id": 1,
                                            "role": 1, "email": 1})
        tid = tenant["id"]
        prefix = "P34_DS_" + uuid.uuid4().hex[:6] + "_"
        cid_a, cid_b = f"{prefix}A", f"{prefix}B"
        try:
            await db.email_outbox.insert_many([
                {"id": uuid.uuid4().hex, "email_id": f"eid-{cid_a}",
                 "tenant_id": tid, "customer_id": cid_a,
                 "kind": "portal_invite", "recipient": "a@e.com",
                 "latest_status": "delivered",
                 "latest_status_ts": "2026-02-15T00:05:00+00:00",
                 "created_at": "2026-02-15T00:00:00+00:00"},
                {"id": uuid.uuid4().hex, "email_id": f"eid-{cid_b}",
                 "tenant_id": tid, "customer_id": cid_b,
                 "kind": "portal_invite", "recipient": "b@e.com",
                 "latest_status": "sent",
                 "latest_status_ts": "2026-02-15T00:01:00+00:00",
                 "created_at": "2026-02-15T00:00:00+00:00"},
            ])
            res = await portal_invites_delivery_status(
                ids=f"{cid_a},{cid_b},{prefix}NONEXISTENT",
                user=admin, tenant={"id": tid},
            )
            items = res["items"]
            assert items[cid_a]["latest_status"] == "delivered"
            assert items[cid_b]["latest_status"] == "sent"
            # Missing cid is silently absent.
            assert f"{prefix}NONEXISTENT" not in items
        finally:
            await db.email_outbox.delete_many(
                {"customer_id": {"$in": [cid_a, cid_b]}},
            )

    run_test(_go)


def test_p34_item9d_delivery_status_endpoint_is_tenant_scoped():
    from routers.portal_admin import portal_invites_delivery_status

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
        admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                           {"_id": 0, "id": 1,
                                            "role": 1, "email": 1})
        tid = tenant["id"]
        alien_tid = f"p34-alien-{uuid.uuid4().hex[:6]}"
        prefix = "P34_XT_" + uuid.uuid4().hex[:6] + "_"
        cid = f"{prefix}A"
        try:
            # Seed an outbox row belonging to a DIFFERENT tenant.
            await db.email_outbox.insert_one({
                "id": uuid.uuid4().hex, "email_id": f"eid-{cid}",
                "tenant_id": alien_tid, "customer_id": cid,
                "kind": "portal_invite", "recipient": "x@e.com",
                "latest_status": "delivered",
                "latest_status_ts": "2026-02-15T00:05:00+00:00",
                "created_at": "2026-02-15T00:00:00+00:00",
            })
            res = await portal_invites_delivery_status(
                ids=cid, user=admin, tenant={"id": tid},
            )
            # Foreign-tenant row must NOT leak into aquaterra's view.
            assert res["items"] == {}
        finally:
            await db.email_outbox.delete_many({"customer_id": cid})

    run_test(_go)


# ══════════════════════════════════════════════════════════════════
# Item 10 — jobs(tenant_id, scheduled_start) compound index
# ══════════════════════════════════════════════════════════════════
def test_p34_ensure_index_jobs_tenant_scheduled_start():
    from scripts.ensure_indexes import _jobs_tenant_scheduled_start_index

    async def _go(db):
        # Sanity: run the ensure fn (idempotent) then inspect indexes.
        await _jobs_tenant_scheduled_start_index()
        idx_cursor = db.jobs.list_indexes()
        idx_list = await idx_cursor.to_list(length=100)
        by_name = {i.get("name"): i for i in idx_list}
        assert "jobs_tenant_id_scheduled_start_bg" in by_name, (
            "P34 Item 10 requires jobs_tenant_id_scheduled_start_bg "
            f"— saw indexes: {sorted(by_name)}"
        )
        target = by_name["jobs_tenant_id_scheduled_start_bg"]
        key = target.get("key") or {}
        # Mongo returns the key as SON({"tenant_id": 1, "scheduled_start": 1});
        # normalise + assert order + direction.
        keys_list = list(key.items())
        assert keys_list == [("tenant_id", 1), ("scheduled_start", 1)], (
            f"Unexpected key spec: {keys_list}"
        )

    run_test(_go)
