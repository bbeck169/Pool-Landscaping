"""Phase C · Feb-2026 — Reorder Route drag-and-drop backend contract.

The web client now always sends `ordered_job_ids` as a 1..N contiguous
array (position = array index). Legacy mobile / third-party clients
that send arbitrary integer positions are STILL accepted — the
backend derives `route_index` from array order, so the persistence
contract is inherently contiguous.

Locks:
  1. Duplicate ids in payload → 422 (regression).
  2. Empty payload → 400 (regression).
  3. Set mismatch (subset / extra) → 422 (regression).
  4. Happy path — payload matches the day's exact non-terminal set →
     200 with contiguous route_index 0..N-1.
"""
from __future__ import annotations

import asyncio
import uuid

from tests._f7_loop_fixture import run_test


def _seed(db, tenant_id, tech_id, date, statuses):
    ids = [str(uuid.uuid4()) for _ in statuses]
    docs = []
    for jid, status in zip(ids, statuses):
        docs.append({
            "id": jid,
            "tenant_id": tenant_id,
            "tech_user_id": tech_id,
            "scheduled_date": f"{date}T09:00:00Z",
            "status": status,
        })
    return ids, docs


def test_reorder_rejects_duplicate_ids_and_empty_payload():
    from routers import schedule_reorder as sr
    from fastapi import HTTPException
    import pytest as _pt

    async def _go(db):
        tid = "tenant-perfC-" + uuid.uuid4().hex[:6]
        tuid = "tech-" + uuid.uuid4().hex[:6]
        ids, docs = _seed(db, tid, tuid, "2026-02-05",
                           ["scheduled", "scheduled"])
        await db.jobs.insert_many(docs)
        user = {"id": "u", "role": "admin"}
        tenant = {"id": tid}
        try:
            # 1) empty payload
            with _pt.raises(HTTPException) as ei:
                await sr.reorder_jobs(
                    body=sr.ReorderBody(
                        tech_user_id=tuid, date="2026-02-05",
                        ordered_job_ids=[]),
                    user=user, tenant=tenant,
                )
            assert ei.value.status_code == 400

            # 2) duplicate ids
            with _pt.raises(HTTPException) as ei:
                await sr.reorder_jobs(
                    body=sr.ReorderBody(
                        tech_user_id=tuid, date="2026-02-05",
                        ordered_job_ids=[ids[0], ids[0]]),
                    user=user, tenant=tenant,
                )
            assert ei.value.status_code == 422
        finally:
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_reorder_rejects_set_mismatch_and_accepts_full_set():
    from routers import schedule_reorder as sr
    from fastapi import HTTPException
    import pytest as _pt

    async def _go(db):
        tid = "tenant-perfC-" + uuid.uuid4().hex[:6]
        tuid = "tech-" + uuid.uuid4().hex[:6]
        ids, docs = _seed(db, tid, tuid, "2026-02-05",
                           ["scheduled", "scheduled", "scheduled"])
        await db.jobs.insert_many(docs)
        user = {"id": "u", "role": "admin"}
        tenant = {"id": tid}
        try:
            # subset — missing 1 → 422
            with _pt.raises(HTTPException) as ei:
                await sr.reorder_jobs(
                    body=sr.ReorderBody(
                        tech_user_id=tuid, date="2026-02-05",
                        ordered_job_ids=ids[:2]),
                    user=user, tenant=tenant,
                )
            assert ei.value.status_code == 422

            # unknown id → 422 (extra)
            extra = ids + [str(uuid.uuid4())]
            with _pt.raises(HTTPException) as ei:
                await sr.reorder_jobs(
                    body=sr.ReorderBody(
                        tech_user_id=tuid, date="2026-02-05",
                        ordered_job_ids=extra),
                    user=user, tenant=tenant,
                )
            assert ei.value.status_code == 422

            # Happy path — exact set in a different order.
            reordered = [ids[2], ids[0], ids[1]]
            resp = await sr.reorder_jobs(
                body=sr.ReorderBody(
                    tech_user_id=tuid, date="2026-02-05",
                    ordered_job_ids=reordered),
                user=user, tenant=tenant,
            )
            assert resp["ok"] is True
            assert resp["updated"] == 3
            assert resp["expected"] == 3
            # Verify contiguous 0..N-1 route_index.
            got = {}
            async for j in db.jobs.find(
                {"tenant_id": tid}, {"_id": 0, "id": 1, "route_index": 1},
            ):
                got[j["id"]] = j.get("route_index")
            assert got[reordered[0]] == 0
            assert got[reordered[1]] == 1
            assert got[reordered[2]] == 2
            assert sorted(got.values()) == [0, 1, 2]
        finally:
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)


def test_reorder_terminal_jobs_are_excluded_from_expected_set():
    """A completed / canceled / skipped job is NOT part of the day
    set — the client doesn't render an input for it, and the server
    must accept a payload that excludes it."""
    from routers import schedule_reorder as sr

    async def _go(db):
        tid = "tenant-perfC-" + uuid.uuid4().hex[:6]
        tuid = "tech-" + uuid.uuid4().hex[:6]
        ids, docs = _seed(db, tid, tuid, "2026-02-05",
                           ["scheduled", "completed", "scheduled"])
        await db.jobs.insert_many(docs)
        user = {"id": "u", "role": "admin"}
        tenant = {"id": tid}
        try:
            resp = await sr.reorder_jobs(
                body=sr.ReorderBody(
                    tech_user_id=tuid, date="2026-02-05",
                    ordered_job_ids=[ids[2], ids[0]]),
                user=user, tenant=tenant,
            )
            assert resp["ok"] is True
            assert resp["updated"] == 2
        finally:
            await db.jobs.delete_many({"tenant_id": tid})

    run_test(_go)
