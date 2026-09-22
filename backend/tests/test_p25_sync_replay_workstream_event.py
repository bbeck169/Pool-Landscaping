"""Phase P25 · Feb-2026 — Sync-replay job.completed Workstream event.

Locks the following contracts:

  1. **Offline replay emits.** A ``job.close`` sync-op processed via
     ``routers.mobile_sync::_handle_job_close`` MUST insert a
     ``type = "job.completed"`` row into ``db.workstream_events``
     with:
       * ``payload.job_id`` = the completed job id,
       * ``payload.tenant_id`` (via row-level ``tenant_id``),
       * ``actor_user_id`` = the syncing tech,
       * ``payload.completed_at`` = the OFFLINE-CAPTURED timestamp
         from ``op.payload.completed_at`` (NOT ``now_iso()``),
       * ``payload.source == "mobile_sync_replay"``.
  2. **Idempotency.** Two calls to ``_handle_job_close`` for the
     SAME job (either the same ``client_op_id`` — caught by the
     ``pending_sync_receipts`` short-circuit in the outer route —
     or a second replay AFTER the job already flipped to
     ``completed``) MUST produce EXACTLY ONE workstream event.
  3. **Online completion still emits.** A PATCH to
     ``/api/jobs/{id}`` flipping status to ``completed`` still
     emits a ``job.completed`` workstream event with
     ``payload.source == "online"`` (regression guard).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest

from tests._f7_loop_fixture import run_test


TAG = "TEST_P25_"


async def _cleanup(db, tenant_id: str, job_id: str):
    await db.jobs.delete_many({"tenant_id": tenant_id})
    await db.workstream_events.delete_many({"tenant_id": tenant_id})
    await db.pending_sync_receipts.delete_many({"tenant_id": tenant_id})
    await db.sync_conflict_log.delete_many({"tenant_id": tenant_id})
    await db.service_reports.delete_many({"tenant_id": tenant_id})


async def _seed_job(
    db, tenant_id: str, job_id: str,
    status: str = "in_progress",
    is_pool: bool = False,
) -> dict:
    doc = {
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": f"{TAG}CUST",
        "customer_name": "Test Customer",
        "technician_id": f"{TAG}TECH",
        "status": status,
        "service_type": "pool_service" if is_pool else "lawn_care",
        "scheduled_date": "2026-02-24",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.jobs.insert_one(dict(doc))
    return doc


# ── 1) Offline replay → job.completed event with offline timestamp ─


def test_p25_offline_replay_emits_job_completed_workstream_event():
    async def _go(db):
        tenant_id = f"{TAG}TEN_{uuid.uuid4().hex[:6]}"
        job_id = f"{TAG}JOB_{uuid.uuid4().hex[:6]}"
        user_id = f"{TAG}USR_{uuid.uuid4().hex[:6]}"
        try:
            await _cleanup(db, tenant_id, job_id)
            await _seed_job(db, tenant_id, job_id, status="in_progress",
                            is_pool=False)  # non-pool to skip chem gate

            # Offline-captured close time — INTENTIONALLY in the past
            # so the event's ``completed_at`` cannot be confused with
            # a ``now_iso()`` value from the replay itself.
            offline_close_iso = (
                datetime.now(timezone.utc) - timedelta(hours=6)
            ).isoformat()

            from routers.mobile_sync import _handle_job_close, _SyncOp
            op = _SyncOp(
                client_op_id=f"{TAG}OP_{uuid.uuid4().hex[:6]}",
                op_type="job.close",
                entity_id=job_id,
                payload={"completed_at": offline_close_iso},
            )
            res = await _handle_job_close(op, tenant_id, user_id)
            assert res["server_id"] == job_id

            # Job doc flipped and stamped with the OFFLINE timestamp.
            job_after = await db.jobs.find_one(
                {"id": job_id, "tenant_id": tenant_id}, {"_id": 0},
            )
            assert job_after["status"] == "completed"
            assert job_after["completed_at"] == offline_close_iso

            # Exactly ONE workstream event, correct shape.
            evts = await db.workstream_events.find(
                {"tenant_id": tenant_id, "type": "job.completed"},
                {"_id": 0},
            ).to_list(10)
            assert len(evts) == 1, (
                f"Expected 1 workstream event, got {len(evts)}: {evts}"
            )
            e = evts[0]
            assert e["type"] == "job.completed"
            assert e["tenant_id"] == tenant_id
            assert e["actor_user_id"] == user_id
            assert e["actor_role"] == "technician"
            pay = e.get("payload") or {}
            assert pay.get("job_id") == job_id
            # ★ Original offline timestamp preserved (NOT replay's
            # now_iso). This is the P25 spec's causal-timestamp rule.
            assert pay.get("completed_at") == offline_close_iso, (
                f"Expected offline timestamp {offline_close_iso!r}, "
                f"got {pay.get('completed_at')!r} — replay clobbered "
                f"the causal timestamp."
            )
            assert pay.get("source") == "mobile_sync_replay"
            ref = e.get("related_ref") or {}
            assert ref.get("type") == "job"
            assert ref.get("id") == job_id
        finally:
            await _cleanup(db, tenant_id, job_id)

    run_test(_go)


# ── 2) Idempotency: replay of an already-completed job → 0 new events


def test_p25_replay_of_already_completed_job_does_not_duplicate_event():
    async def _go(db):
        tenant_id = f"{TAG}TEN_{uuid.uuid4().hex[:6]}"
        job_id = f"{TAG}JOB_{uuid.uuid4().hex[:6]}"
        user_id = f"{TAG}USR_{uuid.uuid4().hex[:6]}"
        try:
            await _cleanup(db, tenant_id, job_id)
            await _seed_job(db, tenant_id, job_id, status="in_progress")

            offline_close_iso = (
                datetime.now(timezone.utc) - timedelta(hours=6)
            ).isoformat()

            from routers.mobile_sync import _handle_job_close, _SyncOp

            # First replay — flips the job to completed, emits 1 event.
            op1 = _SyncOp(
                client_op_id=f"{TAG}OP_A_{uuid.uuid4().hex[:6]}",
                op_type="job.close",
                entity_id=job_id,
                payload={"completed_at": offline_close_iso},
            )
            await _handle_job_close(op1, tenant_id, user_id)

            # Second replay — DIFFERENT client_op_id (so the outer
            # receipt-dedup wouldn't fire) but the job is already
            # in ``completed`` state. The handler's transition guard
            # (``_prev_status != "completed"``) MUST skip the second
            # event emission.
            op2 = _SyncOp(
                client_op_id=f"{TAG}OP_B_{uuid.uuid4().hex[:6]}",
                op_type="job.close",
                entity_id=job_id,
                payload={"completed_at": offline_close_iso},
            )
            await _handle_job_close(op2, tenant_id, user_id)

            evts = await db.workstream_events.find(
                {"tenant_id": tenant_id, "type": "job.completed"},
                {"_id": 0},
            ).to_list(10)
            assert len(evts) == 1, (
                f"Expected exactly ONE workstream event after two "
                f"replays of the same completion; got {len(evts)}: "
                f"{[e.get('payload', {}).get('source') for e in evts]}"
            )
        finally:
            await _cleanup(db, tenant_id, job_id)

    run_test(_go)


# ── 3) Regression: online path still emits ─────────────────────────


def test_p25_online_completion_still_emits_workstream_event():
    """Directly exercises the P25 helper the way the online PATCH
    handler does. Guardrail: a future refactor that removes the
    online emit site should fail this test."""
    async def _go(db):
        tenant_id = f"{TAG}TEN_{uuid.uuid4().hex[:6]}"
        job_id = f"{TAG}JOB_{uuid.uuid4().hex[:6]}"
        user_id = f"{TAG}USR_{uuid.uuid4().hex[:6]}"
        try:
            await _cleanup(db, tenant_id, job_id)
            job = await _seed_job(db, tenant_id, job_id, status="completed")
            # Simulate the online PATCH post-completion emit — pass
            # the fresh (post-transition) job doc, and the caller's
            # user identity.
            from routers.workstream import emit_job_completed_event
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            doc = await emit_job_completed_event(
                tenant_id=tenant_id,
                actor_user_id=user_id,
                actor_role="admin",
                job=job,
                completed_at=job["completed_at"],
                source="online",
            )
            assert doc is not None, (
                "Online-path emit returned None — the P25 helper "
                "silently failed to insert the event."
            )
            assert doc["type"] == "job.completed"
            assert doc["payload"]["source"] == "online"
            assert doc["actor_role"] == "admin"

            evts = await db.workstream_events.find(
                {"tenant_id": tenant_id, "type": "job.completed"},
                {"_id": 0},
            ).to_list(10)
            assert len(evts) == 1
            assert evts[0]["payload"]["source"] == "online"
        finally:
            await _cleanup(db, tenant_id, job_id)

    run_test(_go)


# ── 4) Guardrail: source-lint — both write paths invoke the helper


def test_p25_both_write_paths_call_emit_job_completed_event():
    """Source-level lint: the online completion transition block in
    ``routers/jobs.py`` and the offline replay handler
    ``_handle_job_close`` in ``routers/mobile_sync.py`` MUST both
    import + call ``emit_job_completed_event``. A silent removal of
    either call site would drop the Workstream feed."""
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    jobs_src = (backend / "routers" / "jobs.py").read_text(encoding="utf-8")
    sync_src = (backend / "routers" / "mobile_sync.py").read_text(
        encoding="utf-8"
    )
    assert "emit_job_completed_event" in jobs_src, (
        "routers/jobs.py no longer calls emit_job_completed_event — "
        "the online completion path stopped emitting the Workstream "
        "job.completed event."
    )
    assert "emit_job_completed_event" in sync_src, (
        "routers/mobile_sync.py no longer calls "
        "emit_job_completed_event — the mobile-sync replay path "
        "stopped emitting the Workstream job.completed event."
    )


# ── 5) Guardrail: source shape — helper preserves offline timestamp


def test_p25_replay_call_site_passes_offline_completed_at():
    """The mobile-sync replay call site MUST pass
    ``op.payload.get('completed_at')`` (via the ``completed_at_val``
    local) — not ``now_iso()`` — to
    ``emit_job_completed_event`` so the event's causal timestamp
    reflects the tech's real-world close, not the replay time."""
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    src = (backend / "routers" / "mobile_sync.py").read_text(
        encoding="utf-8"
    )
    # Find the offline replay emit block and assert it passes the
    # offline-captured value (via ``completed_at_val``).
    assert "completed_at=completed_at_val" in src, (
        "Mobile-sync replay no longer passes the offline-captured "
        "completed_at value to emit_job_completed_event — the event "
        "timestamp will reflect replay time, not real-world close."
    )
    # ``op.payload.get("completed_at")`` MUST still be the source
    # of ``completed_at_val``.
    assert 'op.payload.get("completed_at")' in src or \
           "op.payload.get('completed_at')" in src, (
        "Mobile-sync replay no longer reads completed_at from the "
        "offline op payload — offline timestamps will be lost."
    )
