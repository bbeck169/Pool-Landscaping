"""Phase F5-reset · Feb-2026 — F5 sentinel reset endpoint.

Direct-coroutine invocation via the shared F7 loop fixture so the
test stays sub-1s and doesn't share the HTTP-timeout flakiness of
the shared preview backend.

Covers:
  1. Happy path — sentinel present → deleted, previous_state
     returned, audit_events row written.
  2. Idempotency — a second call after the first still returns 200,
     deleted_count=0, previous_state=None; another audit row still
     appended (so ops can trace attempted resets).
  3. Role gate — non-super_admin (admin) is 403'd by the shared
     ``require_super_admin`` dep.
"""
from __future__ import annotations

import asyncio

from tests._f7_loop_fixture import run_test


def _seed_sentinel_doc(actor_id: str = "test-actor") -> dict:
    return {
        "key": "f5_leads_backfill_v1",
        "completed_at": "2026-02-01T12:00:00+00:00",
        "summary": {
            "candidates_total": 3,
            "changed": 2,
            "skipped": 1,
        },
    }


def _cleanup(db):
    return asyncio.gather(
        db.migration_status.delete_many({"key": "f5_leads_backfill_v1"}),
        db.audit_events.delete_many({"event_type": "f5_sentinel_reset"}),
    )


def test_f5_reset_deletes_sentinel_and_writes_audit_event():
    """Happy path — sentinel present → deleted + audit row logged."""
    from routers import data_repair as dr

    async def _go(db):
        await _cleanup(db)
        seed = _seed_sentinel_doc()
        await db.migration_status.insert_one(seed)
        try:
            out = await dr.reset_f5_leads_backfill_sentinel(
                user={"id": "user-super", "role": "super_admin",
                      "tenant_id": "tenant-a"},
            )
            assert out["ok"] is True
            assert out["sentinel_key"] == "f5_leads_backfill_v1"
            assert out["deleted_count"] == 1
            assert out["previous_state"] is not None
            assert out["previous_state"]["key"] == "f5_leads_backfill_v1"
            assert out["previous_state"]["summary"]["changed"] == 2
            assert out["audit_event_id"]

            # Sentinel actually gone from Mongo.
            still = await db.migration_status.find_one(
                {"key": "f5_leads_backfill_v1"}, {"_id": 0},
            )
            assert still is None

            # Audit row is present with the expected shape.
            audit = await db.audit_events.find_one(
                {"id": out["audit_event_id"]}, {"_id": 0},
            )
            assert audit is not None
            assert audit["event_type"] == "f5_sentinel_reset"
            assert audit["actor_user_id"] == "user-super"
            assert audit["tenant_id"] == "tenant-a"
            assert audit["sentinel_key"] == "f5_leads_backfill_v1"
            assert audit["deleted_count"] == 1
            assert audit["previous_state"]["key"] == "f5_leads_backfill_v1"
            assert audit.get("timestamp")
        finally:
            await _cleanup(db)

    run_test(_go)


def test_f5_reset_is_idempotent_when_sentinel_absent():
    """Second call after sentinel gone → 200, deleted_count=0,
    previous_state=None. Still writes an audit row so attempted
    resets are traceable."""
    from routers import data_repair as dr

    async def _go(db):
        await _cleanup(db)
        try:
            # First call — no sentinel to start with.
            out = await dr.reset_f5_leads_backfill_sentinel(
                user={"id": "user-super", "role": "super_admin",
                      "tenant_id": "tenant-a"},
            )
            assert out["ok"] is True
            assert out["deleted_count"] == 0
            assert out["previous_state"] is None

            # Second call — same shape.
            out2 = await dr.reset_f5_leads_backfill_sentinel(
                user={"id": "user-super", "role": "super_admin",
                      "tenant_id": "tenant-a"},
            )
            assert out2["ok"] is True
            assert out2["deleted_count"] == 0
            assert out2["previous_state"] is None
            assert out2["audit_event_id"] != out["audit_event_id"]

            # Both audit events are present.
            audits = await db.audit_events.find(
                {"event_type": "f5_sentinel_reset"}, {"_id": 0},
            ).to_list(10)
            assert len(audits) >= 2
        finally:
            await _cleanup(db)

    run_test(_go)


def test_f5_reset_role_gate_enforced_via_require_super_admin():
    """A non-super_admin passed through the dep must raise 403.
    ``require_super_admin`` is a plain sync function taking ``user``
    as a kwarg — mirroring how the F9 status test locks its gate."""
    from fastapi import HTTPException
    from utils import require_super_admin

    async def _go():
        import pytest as _pytest
        with _pytest.raises(HTTPException) as ei:
            require_super_admin(user={"role": "admin"})
        assert ei.value.status_code == 403

    asyncio.new_event_loop().run_until_complete(_go())
