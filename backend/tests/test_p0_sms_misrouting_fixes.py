"""Feb-2026 · P0 SMS misrouting — pinned tests for the 3 scoped fixes.

Fix 1 — ``process_due_enrolments`` now renders drips against the REAL
customer + tenant docs (via ``render_context``) instead of the
``DEFAULT_SAMPLE_CONTEXT``.  The regression the fix closes: every
``{{customer.first_name}}`` was rendering as the sample ``"Sam"`` and
every ``{{tenant.name}}`` as the sample tenant name — every drip
SMS/email that referenced those tags was leaking developer sample
data to real recipients.

Fix 2a — ``on_event`` guards fan-out with a unique index on
``marketing_event_ledger(tenant_id, customer_id, event_key)``.  Same
event fired twice → the second insert throws ``DuplicateKeyError``,
the fan-out is skipped, zero extra enrolments created.

Fix 2b — ``RingCentralSMSAdapter.send`` uses the ``idempotency_key``
kwarg it previously accepted-and-ignored.  A cached envelope in
``sms_idempotency`` short-circuits the second send with an
``idempotent_replay: True`` flag.

All three tests bind Motor to the pytest loop the same way
``test_marketing_m5c.py`` does (module-scope ``_LOOP``, rebind ``db``
on module import).  Idempotent — safe to run repeatedly.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, Optional

import pytest


# ─── Motor rebinding — copied from test_marketing_m5c.py ─────────────
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.marketing_sequences as _seq
    _seq.db = fresh_db
    import services.marketing.drip_events as _de
    _de.db = fresh_db
    import services.sms.rc_adapter as _rc  # noqa: F401 — module-level ref
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


# ─── Shared helpers ─────────────────────────────────────────────────
async def _tenant_id_of_admin() -> str:
    db = _db()
    u = await db.users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    assert u and u.get("tenant_id"), "admin@aquaterra.com not seeded"
    return u["tenant_id"]


async def _mk_customer(tenant_id: str, first_name: str) -> str:
    db = _db()
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "first_name": first_name, "last_name": "Testcase",
        "name": f"{first_name} Testcase",
        "email": f"{first_name.lower()}.testcase@example.com",
        "phone": "+15555550100",
    })
    return cid


async def _mk_template(
    tenant_id: str, channel: str, body: str,
    subject: str = "", name: str = "P0-tests-tpl",
) -> str:
    db = _db()
    tpl_id = f"test-tpl-{uuid.uuid4().hex[:12]}"
    await db.marketing_templates.insert_one({
        "id": tpl_id, "tenant_id": tenant_id,
        "name": name, "channel": channel,
        "subject": subject, "body": body,
        "active": True, "kind": "custom",
    })
    return tpl_id


async def _mk_sequence(
    tenant_id: str, trigger_type: str, tpl_id: str,
    channel: str = "sms", active: bool = True,
) -> str:
    from utils import new_id, now_iso
    db = _db()
    sid = new_id()
    await db.marketing_sequences.insert_one({
        "id": sid, "tenant_id": tenant_id,
        "name": f"P0-test-seq-{sid[:6]}",
        "trigger_type": trigger_type,
        "trigger_config": {},
        "steps": [{"order": 0, "channel": channel,
                    "template_id": tpl_id,
                    "delay_from": "trigger", "delay_hours": 0}],
        "active": active, "stop_on_reply": True,
        "created_at": now_iso(),
    })
    return sid


async def _drain_teardown(tenant_id: str) -> None:
    """Best-effort cleanup — removes rows created by this file's helpers."""
    db = _db()
    for coll in ("customers", "marketing_templates", "marketing_sequences",
                  "marketing_drip_enrolments", "marketing_deliveries",
                  "marketing_event_ledger", "sms_idempotency"):
        try:
            await db[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [
                     {"id": {"$regex": "^test-"}},
                     {"name": {"$regex": "^P0-tests-tpl|P0-test-seq"}},
                 ]},
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# Fix 1 — real customer + tenant in render context (no more "Hi Sam")
# ═══════════════════════════════════════════════════════════════════════
def test_fix1_drip_render_uses_real_customer_first_name_not_sam():
    async def _go():
        from routers.marketing_sequences import process_due_enrolments
        mine = await _tenant_id_of_admin()
        cid = await _mk_customer(mine, "Kaylan")
        tpl_id = await _mk_template(
            mine, "sms",
            body="Hi {{customer.first_name}}, {{tenant.name}} finished. "
                  "Call {{tenant.phone}}.",
        )
        sid = await _mk_sequence(mine, "service_completed", tpl_id, "sms")

        db = _db()
        # Enrol the real customer directly (bypass on_event so we
        # exercise ONLY the render path here).
        from utils import new_id, now_iso
        enrol_id = new_id()
        past = "2020-01-01T00:00:00+00:00"
        await db.marketing_drip_enrolments.insert_one({
            "id": enrol_id, "tenant_id": mine,
            "sequence_id": sid, "customer_id": cid,
            "trigger_source": "service_completed",
            "enrolled_at": now_iso(), "current_step": 0,
            "next_send_at": past, "status": "active",
            "history": [],
        })

        await process_due_enrolments(tenant_id=mine)

        delivery = await db.marketing_deliveries.find_one(
            {"tenant_id": mine, "enrolment_id": enrol_id},
            {"_id": 0, "body_rendered": 1},
        )
        assert delivery, "process_due_enrolments did not emit a delivery"
        rendered = delivery["body_rendered"]
        # THE regression assertion — "Sam" is the sample first_name
        # in DEFAULT_SAMPLE_CONTEXT.  A real Kaylan-enrolled drip
        # must not leak it.
        assert "Sam" not in rendered, (
            f"Fix 1 regressed: rendered body still contains 'Sam': {rendered!r}"
        )
        assert "Kaylan" in rendered, (
            f"Fix 1 regressed: real customer.first_name missing: {rendered!r}"
        )
        # tenant.name must come from the real tenant, not the
        # sample-context tenant name.
        real_tenant = await db.tenants.find_one(
            {"id": mine}, {"_id": 0, "name": 1, "phone": 1},
        )
        assert real_tenant and real_tenant.get("name"), \
            "admin's tenant has no name — cannot assert render"
        assert real_tenant["name"] in rendered, (
            f"Fix 1 regressed: rendered body should carry real tenant name "
            f"{real_tenant['name']!r} but got: {rendered!r}"
        )
        await _drain_teardown(mine)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Fix 2a — event ledger dedupes same-event fan-out
# ═══════════════════════════════════════════════════════════════════════
def test_fix2a_on_event_dedupes_repeat_correlation_id():
    async def _go():
        from services.marketing.drip_events import on_event
        mine = await _tenant_id_of_admin()
        cid = await _mk_customer(mine, "Kaylan")
        tpl_id = await _mk_template(mine, "sms",
                                       body="Hi {{customer.first_name}}.")
        # Create TWO active sequences on the same trigger — mirrors
        # the prod duplicate vector where a tenant had 2 stacked
        # ``service_completed`` sequences.
        sid_a = await _mk_sequence(mine, "service_completed", tpl_id, "sms")
        sid_b = await _mk_sequence(mine, "service_completed", tpl_id, "sms")

        meta = {"service_report_id": f"test-sr-{uuid.uuid4().hex[:12]}"}
        r1 = await on_event("service_completed", mine, cid, meta=meta)
        r2 = await on_event("service_completed", mine, cid, meta=meta)

        # First call — fans out to both sequences, both enrol.
        assert r1["deduped"] == 0, r1
        assert r1["enrolled"] == 2, r1
        # Second call — same correlation_id → dedupe barrier trips,
        # zero new enrolments, ``deduped=1``.
        assert r2["deduped"] == 1, r2
        assert r2["enrolled"] == 0, r2

        # Ledger row exists once, no more.
        db = _db()
        n = await db.marketing_event_ledger.count_documents({
            "tenant_id": mine, "customer_id": cid,
            "event_key": f"service_completed:{meta['service_report_id']}",
        })
        assert n == 1, f"expected exactly 1 ledger row, got {n}"

        # Total enrolments in the active state for this customer × 2 seqs.
        n_enrol = await db.marketing_drip_enrolments.count_documents({
            "tenant_id": mine, "customer_id": cid,
            "sequence_id": {"$in": [sid_a, sid_b]}, "status": "active",
        })
        assert n_enrol == 2, (
            f"expected exactly 2 enrolments (one per seq, first call only), "
            f"got {n_enrol}"
        )
        await _drain_teardown(mine)

    _run(_go())


def test_fix2a_on_event_different_correlation_ids_still_fan_out():
    """A retry-safe dedupe must NOT dedupe two genuinely different events
    (e.g., two separate service reports for the same customer)."""
    async def _go():
        from services.marketing.drip_events import on_event
        mine = await _tenant_id_of_admin()
        cid = await _mk_customer(mine, "Kaylan")
        tpl_id = await _mk_template(mine, "sms", body="Hi.")
        await _mk_sequence(mine, "service_completed", tpl_id, "sms")

        r1 = await on_event(
            "service_completed", mine, cid,
            meta={"service_report_id": f"test-sr-{uuid.uuid4().hex[:8]}"},
        )
        r2 = await on_event(
            "service_completed", mine, cid,
            meta={"service_report_id": f"test-sr-{uuid.uuid4().hex[:8]}"},
        )
        assert r1["deduped"] == 0 and r1["enrolled"] >= 1, r1
        # Second event has a DIFFERENT correlation → not deduped.
        # (r2["enrolled"] is 0 only because the per-sequence enrol
        # dedup still holds on the active enrolment from r1 — but
        # deduped MUST remain 0.)
        assert r2["deduped"] == 0, r2
        await _drain_teardown(mine)

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Fix 2b — RC adapter idempotency cache
# ═══════════════════════════════════════════════════════════════════════
def test_fix2b_rc_adapter_idempotency_key_cache_hit(monkeypatch):
    async def _go():
        from services.sms import rc_adapter
        from services import comms_env_guard as _guard_mod
        from services.comms import gate as _gate_mod
        mine = await _tenant_id_of_admin()

        # Force the deterministic "mocked" send branch and neutralise
        # the two upstream safety gates so this unit test exercises
        # ONLY the Fix-2b idempotency-cache path.  No real RC is
        # contacted; no real customer receives anything.
        monkeypatch.setattr(rc_adapter._default, "enabled", False, raising=False)
        async def _allow(**kw):
            return True
        monkeypatch.setattr(_gate_mod, "is_comm_allowed", _allow, raising=True)
        # comms_env_guard.guard_outbound is sync + returns a namedtuple.
        class _Verdict:
            blocked = False
            def dry_run_response(self, provider="ringcentral"):
                return {"provider": provider, "provider_status": "dry_run",
                         "provider_response_id": None, "attempts": 0,
                         "error": None}
        monkeypatch.setattr(_guard_mod, "guard_outbound",
                             lambda **kw: _Verdict(), raising=True)

        idem = f"test-idem-{uuid.uuid4().hex[:12]}"
        r1 = await rc_adapter.send(
            to="+15555550199", body="hello", category="transactional",
            tenant_id=mine, customer_id="test-cust-idem",
            idempotency_key=idem,
        )
        r2 = await rc_adapter.send(
            to="+15555550199", body="hello", category="transactional",
            tenant_id=mine, customer_id="test-cust-idem",
            idempotency_key=idem,
        )
        # First send caches an envelope.  Second returns the cached
        # envelope with the replay flag set.
        assert r1.get("provider_status") in {"mocked", "sent", "queued",
                                                 "delivered", "dry_run"}, r1
        assert r2.get("idempotent_replay") is True, r2
        assert r2.get("provider_status") == r1.get("provider_status"), (
            r1, r2,
        )

        db = _db()
        n = await db.sms_idempotency.count_documents({
            "tenant_id": mine, "idempotency_key": idem,
        })
        assert n == 1, f"expected exactly 1 cache row, got {n}"

        # Explicit teardown for this test-only cache row.
        await db.sms_idempotency.delete_many(
            {"tenant_id": mine, "idempotency_key": idem},
        )
        await _drain_teardown(mine)

    _run(_go())


def test_fix2b_rc_adapter_no_idempotency_key_still_works(monkeypatch):
    """No ``idempotency_key`` provided → no cache, no replay flag."""
    async def _go():
        from services.sms import rc_adapter
        from services import comms_env_guard as _guard_mod
        from services.comms import gate as _gate_mod
        mine = await _tenant_id_of_admin()

        monkeypatch.setattr(rc_adapter._default, "enabled", False, raising=False)
        async def _allow(**kw):
            return True
        monkeypatch.setattr(_gate_mod, "is_comm_allowed", _allow, raising=True)
        class _Verdict:
            blocked = False
            def dry_run_response(self, provider="ringcentral"):
                return {"provider": provider, "provider_status": "dry_run",
                         "provider_response_id": None, "attempts": 0,
                         "error": None}
        monkeypatch.setattr(_guard_mod, "guard_outbound",
                             lambda **kw: _Verdict(), raising=True)

        r = await rc_adapter.send(
            to="+15555550199", body="hello", category="transactional",
            tenant_id=mine, customer_id="test-cust-no-idem",
        )
        assert "idempotent_replay" not in r, r
        assert r.get("provider_status") in {"mocked", "sent", "queued",
                                                 "delivered", "dry_run"}, r

    _run(_go())
