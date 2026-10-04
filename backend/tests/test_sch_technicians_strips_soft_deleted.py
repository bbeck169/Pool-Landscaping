"""SCH Phase II · Feb-2026 — regression lock on ``GET /api/technicians``
soft-delete gate on arm A (the ``db.technicians`` row find).

Three assertions, each isolated under a disposable test tenant_id so
production (aquaterra) stays pristine:

  a. Soft-deleted tech (``deleted_at`` set) is stripped from the
     response — len == 1 and the single row is the active tech.
     Locks the ``deleted_at: None`` arm of the new $or filter.
  b. Tech doc with NO ``deleted_at`` field at all (not even null)
     still appears in the response — len == 1 and that tech is
     present. Locks the ``$exists: False`` arm of the $or filter.
  c. Dangling FK on ``db.jobs.technician_id`` (points at a tech id
     that doesn't exist in ``db.technicians`` for the tenant) does
     NOT crash ``list_technicians`` — it returns 200 (list) and
     the handler's bulk ``db.jobs.aggregate`` counters degrade
     silently. Locks regression on the "~70 dangling historical
     jobs under hard-deleted techs" scenario the Phase II purge
     will create.

Harness: direct function-call via ``_f7_loop_fixture.run_test``
(matches ``test_p23_technician_soft_delete.py``). Each test seeds
and tears down under a unique tenant_id so there's no cross-test
pollution and no risk of leaking into aquaterra.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tests._f7_loop_fixture import run_test


TAG = "TEST_SCH_STRIP_"


def _tid() -> str:
    return f"{TAG}T_{uuid.uuid4().hex[:12]}"


def _admin(tenant_id: str) -> dict:
    return {"id": "sch-admin", "role": "admin",
            "tenant_id": tenant_id, "email": "admin@sch.test"}


async def _cleanup(db, tenant_id: str) -> None:
    for coll in ("technicians", "users", "jobs"):
        await getattr(db, coll).delete_many({"tenant_id": tenant_id})


async def _seed_tech(db, tenant_id, *, tech_id=None, deleted_at=None,
                     include_deleted_at_field=True, name_suffix=""):
    _tech_id = tech_id or f"{TAG}TECH_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": _tech_id, "tenant_id": tenant_id,
        "name": f"SCH-STRIP-{name_suffix or _tech_id[-4:]}",
        "department": "pool_tech",
        "email": f"{_tech_id[-6:]}@sch.test",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if include_deleted_at_field:
        doc["deleted_at"] = deleted_at   # None or an ISO ts string
    await db.technicians.insert_one(doc)
    return _tech_id


def _call_list(tenant_id):
    """Direct call to ``list_technicians`` — no HTTP, no server."""
    from routers.technicians import list_technicians
    return list_technicians(user=_admin(tenant_id),
                            tenant={"id": tenant_id})


# ── (a) Soft-deleted tech is stripped ────────────────────────────────
def test_sch_phase2_soft_deleted_tech_is_stripped_from_list_technicians():
    async def _go(db):
        tenant_id = _tid()
        await _cleanup(db, tenant_id)
        try:
            active_id = await _seed_tech(
                db, tenant_id, deleted_at=None, name_suffix="ACTIVE")
            await _seed_tech(
                db, tenant_id,
                deleted_at=datetime.now(timezone.utc).isoformat(),
                name_suffix="DELETED")

            docs = await _call_list(tenant_id)
            # Exactly 1 — the deleted tech is dropped; no users exist
            # in this disposable tenant so arm B contributes zero.
            assert isinstance(docs, list), f"expected list, got {type(docs)}"
            assert len(docs) == 1, f"expected 1 doc, got {len(docs)}: {docs}"
            assert docs[0].get("id") == active_id, \
                f"wrong tech returned: {docs[0]}"
        finally:
            await _cleanup(db, tenant_id)
    run_test(_go)


# ── (b) Tech with no ``deleted_at`` field is still active ────────────
def test_sch_phase2_tech_without_deleted_at_field_is_treated_active():
    async def _go(db):
        tenant_id = _tid()
        await _cleanup(db, tenant_id)
        try:
            # Insert with include_deleted_at_field=False so the key
            # literally doesn't exist on the doc.
            tech_id = await _seed_tech(
                db, tenant_id,
                include_deleted_at_field=False,
                name_suffix="NOFIELD")

            raw = await db.technicians.find_one({"id": tech_id}, {"_id": 0})
            assert "deleted_at" not in raw, (
                f"seed sanity: deleted_at should be absent, got {raw}")

            docs = await _call_list(tenant_id)
            ids = [d.get("id") for d in docs]
            assert tech_id in ids, (
                f"tech without deleted_at field was dropped: {ids}")
        finally:
            await _cleanup(db, tenant_id)
    run_test(_go)


# ── (c) Dangling FK does not crash list_technicians ──────────────────
def test_sch_phase2_dangling_fk_in_jobs_does_not_crash_list_technicians():
    async def _go(db):
        tenant_id = _tid()
        await _cleanup(db, tenant_id)
        try:
            active_id = await _seed_tech(
                db, tenant_id, deleted_at=None, name_suffix="ACTIVE")
            # Seed a job whose technician_id points at NOTHING.
            dangling_id = f"{TAG}DANGLING_{uuid.uuid4().hex[:8]}"
            await db.jobs.insert_one({
                "id": f"{TAG}JOB_{uuid.uuid4().hex[:8]}",
                "tenant_id": tenant_id,
                "technician_id": dangling_id,
                "status": "pending",
                "customer_id": "sch-stale-cust",
                "scheduled_date": "2026-06-01",
            })
            docs = await _call_list(tenant_id)
            assert isinstance(docs, list), (
                f"handler blew up or returned non-list: {type(docs)}")
            ids = [d.get("id") for d in docs]
            assert active_id in ids, (
                f"active tech missing after dangling-fk seed: {ids}")
            # The dangling id must not materialize as a synthesized tech.
            assert dangling_id not in ids, (
                f"dangling-fk id leaked into response: {ids}")
        finally:
            await _cleanup(db, tenant_id)
    run_test(_go)
