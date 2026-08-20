"""Feb-2026 · 24-hour post-completion edit window — end-to-end tests.

15 cases covering all gates + side-effect suppression + rollback +
mobile-sync parity.  Uses the same loop-binding fixture pattern as
``test_chemistry_required_readings_gate.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


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
    for mod in ("routers.jobs", "routers.mobile_sync",
                 "routers.workstream_service_log",
                 "routers.service_reports"):
        __import__(mod)
        import sys
        sys.modules[mod].db = fresh_db
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


async def _mk_completed_pool_job(
    tid: str, *,
    completed_hours_ago: float = 1.0,
    tech_id: str = "ew-tech",
) -> str:
    from utils import now_iso
    jid = f"ew-job-{uuid.uuid4().hex[:10]}"
    completed_at = _iso(datetime.now(timezone.utc)
                         - timedelta(hours=completed_hours_ago))
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": "cust-ew", "customer_name": "Edit Window Cust",
        "service_type": "Weekly Pool Service",
        "technician_id": tech_id,
        "title": "Weekly Pool",
        "status": "completed",
        "completed_at": completed_at,
        "scheduled_date": completed_at,
        "created_at": now_iso(),
        "chemical_readings": [
            {"key": "free_chlorine",  "value": 2.5},
            {"key": "total_chlorine", "value": 3.0},
            {"key": "ph",             "value": 7.4},
            {"key": "alkalinity",     "value": 80},
            {"key": "cyanuric_acid",  "value": 40},
        ],
    })
    return jid


def _mk_tech_user(tid: str, *, tech_id: str = "ew-tech") -> Dict[str, Any]:
    return {"id": f"u-{tech_id}", "role": "technician",
            "technician_id": tech_id, "tenant_id": tid,
            "email": "ew-tech@example.com", "name": "EW Tech"}


async def _admin_user(tid: str) -> Dict[str, Any]:
    return await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0},
    )


async def _drain(tid: str) -> None:
    for coll in ("jobs", "job_edits", "service_reports",
                 "marketing_deliveries", "marketing_event_ledger",
                 "notifications", "messages"):
        await _db()[coll].delete_many({"tenant_id": tid,
                                        "$or": [
                                            {"id": {"$regex": "^ew-"}},
                                            {"job_id": {"$regex": "^ew-"}},
                                            {"customer_id": "cust-ew"},
                                            {"trigger_entity.id": {"$regex": "^ew-"}},
                                            {"correlation_id": {"$regex": "^ew-"}},
                                        ]})


def _patch(**kw) -> Any:
    """Build a JobEditPatch — kwargs map straight to the pydantic body."""
    from routers.jobs import JobEditPatch
    return JobEditPatch(**kw)


async def _tenant_dep(tid: str) -> Dict[str, Any]:
    doc = await _db().tenants.find_one({"id": tid}, {"_id": 0})
    return doc or {"id": tid}


# ═════════════════════════════════════════════════════════════════════
# 1. Edit within window as assigned technician → 200 + audit doc.
# ═════════════════════════════════════════════════════════════════════
def test_edit_within_window_as_technician_writes_audit_row():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window, list_job_edits
            user = _mk_tech_user(tid)
            tenant = await _tenant_dep(tid)
            body = _patch(
                chemical_readings=[
                    {"key": "free_chlorine",  "value": 2.8},   # was 2.5
                    {"key": "total_chlorine", "value": 3.0},
                    {"key": "ph",             "value": 7.4},
                    {"key": "alkalinity",     "value": 80},
                    {"key": "cyanuric_acid",  "value": 40},
                ],
                edit_reason="Corrected Free Cl reading",
            )
            r = await patch_job_edit_window(jid, body, user=user, tenant=tenant)
            assert r["id"] == jid
            hist = await list_job_edits(jid, user=user, tenant=tenant)
            assert hist["count"] == 1
            edit = hist["edits"][0]
            assert edit["edited_by_role"] == "technician"
            assert edit["source"] == "web"
            assert "chemical_readings" in edit["changes"]
            assert edit["reason"] == "Corrected Free Cl reading"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Edit within window as admin → 200 + role recorded.
# ═════════════════════════════════════════════════════════════════════
def test_edit_within_window_as_admin_records_admin_role():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            admin = await _admin_user(tid)
            tenant = await _tenant_dep(tid)
            body = _patch(notes="Admin correction — pump ran quieter today.")
            await patch_job_edit_window(jid, body, user=admin, tenant=tenant)
            edit = await _db().job_edits.find_one(
                {"tenant_id": tid, "job_id": jid}, {"_id": 0},
            )
            assert edit["edited_by_role"] == "admin"
            assert "notes" in edit["changes"]
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. Edit outside window → 403 edit_window_expired.
# ═════════════════════════════════════════════════════════════════════
def test_edit_outside_window_raises_403():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid, completed_hours_ago=25.0)
        try:
            from routers.jobs import patch_job_edit_window
            body = _patch(notes="too late")
            tenant = await _tenant_dep(tid)
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, body, user=_mk_tech_user(tid), tenant=tenant,
                )
            assert ei.value.status_code == 403
            d = ei.value.detail
            assert d["detail"] == "edit_window_expired"
            assert d["edit_window_hours"] == 24
            assert d["hours_since_completion"] >= 24
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. Edit on non-completed job → 400 job_not_completed.
# ═════════════════════════════════════════════════════════════════════
def test_edit_on_non_completed_job_raises_400():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        # Flip status back to pending.
        await _db().jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$set": {"status": "pending"}, "$unset": {"completed_at": ""}},
        )
        try:
            from routers.jobs import patch_job_edit_window
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, _patch(notes="x"),
                    user=_mk_tech_user(tid),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 400
            assert ei.value.detail["detail"] == "job_not_completed"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5. Soft-deleted job — technician sees 404, super_admin sees 409.
# ═════════════════════════════════════════════════════════════════════
def test_soft_deleted_job_masked_for_tech_visible_for_super_admin():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        from utils import now_iso
        await _db().jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$set": {"deleted_at": now_iso()}},
        )
        try:
            from routers.jobs import patch_job_edit_window
            tenant = await _tenant_dep(tid)
            with pytest.raises(HTTPException) as ei_tech:
                await patch_job_edit_window(
                    jid, _patch(notes="x"),
                    user=_mk_tech_user(tid), tenant=tenant,
                )
            assert ei_tech.value.status_code == 404

            super_admin = {"id": "u-sup", "role": "super_admin",
                           "tenant_id": tid}
            with pytest.raises(HTTPException) as ei_sa:
                await patch_job_edit_window(
                    jid, _patch(notes="x"),
                    user=super_admin, tenant=tenant,
                )
            assert ei_sa.value.status_code == 409
            assert ei_sa.value.detail["detail"] == "job_soft_deleted"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 6. Edit that violates chemistry gate → 422 + no audit doc.
# ═════════════════════════════════════════════════════════════════════
def test_edit_violating_chemistry_gate_writes_no_audit_row():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            body = _patch(chemical_readings=[
                {"key": "free_chlorine",  "value": 2.5},
                {"key": "total_chlorine", "value": 3.0},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 80},
                # CYA blanked out — gate must block.
                {"key": "cyanuric_acid",  "value": ""},
            ])
            with pytest.raises(HTTPException) as ei:
                await patch_job_edit_window(
                    jid, body, user=_mk_tech_user(tid),
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 422
            d = ei.value.detail
            assert d["detail"] == "chemistry_core_readings_missing"
            assert d["missing_fields"] == ["cya"]
            assert d["missing_labels"] == ["CYA"]
            n = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid},
            )
            assert n == 0
            # Job unchanged.
            after = await _db().jobs.find_one({"id": jid}, {"_id": 0})
            assert any(r["value"] == 40
                        for r in after["chemical_readings"]
                        if r["key"] == "cyanuric_acid")
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 7. Editing an immutable field → 400 immutable_field.
# ═════════════════════════════════════════════════════════════════════
def test_edit_immutable_field_raises_400():
    """The pydantic model rejects unknown keys — but the guard also
    runs on raw dict fields via ``assert_immutable_fields_untouched``.
    Exercised by calling the guard directly with an evil payload."""
    async def _go():
        from services.edit_window import assert_immutable_fields_untouched
        with pytest.raises(HTTPException) as ei:
            assert_immutable_fields_untouched({"customer_id": "attacker-cid"})
        assert ei.value.status_code == 400
        assert ei.value.detail["detail"] == "immutable_field"
        assert ei.value.detail["field"] == "customer_id"

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 8. Edit MUST NOT create a duplicate door_hanger_auto ledger row.
# ═════════════════════════════════════════════════════════════════════
def test_edit_does_not_duplicate_door_hanger_ledger():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        # Seed one ledger row to represent the original completion.
        from utils import now_iso, new_id
        await _db().marketing_event_ledger.insert_one({
            "id": new_id(), "tenant_id": tid,
            "customer_id": "cust-ew",
            "event_key": f"door_hanger_auto:{jid}",
            "trigger_type": "door_hanger_auto",
            "correlation_id": jid,
            "processed_at": now_iso(),
        })
        try:
            from routers.jobs import patch_job_edit_window
            before_count = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid, "event_key": f"door_hanger_auto:{jid}",
            })
            assert before_count == 1
            await patch_job_edit_window(
                jid, _patch(notes="Corrected notes"),
                user=_mk_tech_user(tid), tenant=await _tenant_dep(tid),
            )
            after_count = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid, "event_key": f"door_hanger_auto:{jid}",
            })
            assert after_count == 1, (
                "PATCH edit path must NOT re-fire the door-hanger "
                "auto-send side effect"
            )
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 8b. Edit MUST NOT re-fire the elevated_followup_shown ledger (new
# side effect introduced with the Slice 5 door-hanger redesign).
# ═════════════════════════════════════════════════════════════════════
def test_edit_does_not_duplicate_elevated_followup_ledger():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        # Seed one ledger row to represent the original CTA render.
        from utils import now_iso, new_id
        await _db().marketing_event_ledger.insert_one({
            "id": new_id(), "tenant_id": tid,
            "customer_id": "cust-ew",
            "event_key": f"elevated_followup_shown:{jid}",
            "trigger_type": "elevated_followup_shown",
            "correlation_id": jid,
            "processed_at": now_iso(),
            "meta": {"job_id": jid},
        })
        try:
            from routers.jobs import patch_job_edit_window
            before_count = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid,
                "event_key": f"elevated_followup_shown:{jid}",
            })
            assert before_count == 1
            # Edit the chemistry — even if the new state STILL has
            # 2+ elevated readings, the PATCH path must not fire the
            # composer that writes the ledger row. Belt-and-suspenders:
            # the compound-unique index also blocks a duplicate.
            await patch_job_edit_window(
                jid, _patch(chemical_readings=[
                    {"key": "free_chlorine",  "value": 12.0},
                    {"key": "total_chlorine", "value": 12.0},
                    {"key": "ph",             "value": 8.6},
                    {"key": "alkalinity",     "value": 200},
                    {"key": "cyanuric_acid",  "value": 40},
                ]),
                user=_mk_tech_user(tid), tenant=await _tenant_dep(tid),
            )
            after_count = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid,
                "event_key": f"elevated_followup_shown:{jid}",
            })
            assert after_count == 1, (
                "PATCH edit path must NOT re-fire the "
                "elevated_followup_shown ledger side effect"
            )
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 8c. Edit path never emits ANY ledger row on any trigger_type — the
# separated code path guarantees NO composer / send / drip is invoked.
# ═════════════════════════════════════════════════════════════════════
def test_edit_writes_no_new_ledger_rows_for_any_trigger_type():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            before = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid, "correlation_id": jid,
            })
            await patch_job_edit_window(
                jid, _patch(notes="Additional notes on the visit."),
                user=_mk_tech_user(tid), tenant=await _tenant_dep(tid),
            )
            after = await _db().marketing_event_ledger.count_documents({
                "tenant_id": tid, "correlation_id": jid,
            })
            assert after == before, (
                f"PATCH edit path emitted {after - before} new "
                f"ledger row(s); should emit 0"
            )
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 9. No new marketing_deliveries rows written on an edit.
# ═════════════════════════════════════════════════════════════════════
def test_edit_writes_no_new_marketing_deliveries():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            before = await _db().marketing_deliveries.count_documents({
                "tenant_id": tid, "trigger_entity.id": jid,
            })
            await patch_job_edit_window(
                jid, _patch(notes="tweak"),
                user=_mk_tech_user(tid), tenant=await _tenant_dep(tid),
            )
            after = await _db().marketing_deliveries.count_documents({
                "tenant_id": tid, "trigger_entity.id": jid,
            })
            assert after == before
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 10. GET /edits — 3 rows returned in desc order.
# ═════════════════════════════════════════════════════════════════════
def test_list_edits_returns_history_in_desc_order():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window, list_job_edits
            user = _mk_tech_user(tid)
            tenant = await _tenant_dep(tid)
            for note in ("first", "second", "third"):
                await patch_job_edit_window(
                    jid, _patch(notes=note), user=user, tenant=tenant,
                )
                await asyncio.sleep(0.01)
            r = await list_job_edits(jid, user=user, tenant=tenant)
            assert r["count"] == 3
            reasons = [e["changes"]["notes"]["after"] for e in r["edits"]]
            assert reasons == ["third", "second", "first"]
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 11. Technician cannot read edits on someone else's job.
# ═════════════════════════════════════════════════════════════════════
def test_technician_cannot_read_edits_on_other_techs_job():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid, tech_id="ew-tech-A")
        try:
            from routers.jobs import list_job_edits
            intruder = _mk_tech_user(tid, tech_id="ew-tech-B")
            with pytest.raises(HTTPException) as ei:
                await list_job_edits(
                    jid, user=intruder,
                    tenant=await _tenant_dep(tid),
                )
            assert ei.value.status_code == 403
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 12. Cross-tenant read → 404 (existence masked).
# ═════════════════════════════════════════════════════════════════════
def test_cross_tenant_edit_history_read_is_404():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import list_job_edits
            other_tenant = {"id": f"TEST_other_{uuid.uuid4().hex[:6]}"}
            admin = {"id": "u-other-admin", "role": "admin",
                     "tenant_id": other_tenant["id"]}
            with pytest.raises(HTTPException) as ei:
                await list_job_edits(jid, user=admin, tenant=other_tenant)
            assert ei.value.status_code == 404
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 13. Audit-doc-write failure → job doc NOT mutated, error bubbles.
# ═════════════════════════════════════════════════════════════════════
def test_audit_write_failure_blocks_job_mutation(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            import routers.jobs as _m

            class _FakeColl:
                async def insert_one(self, *a, **kw):
                    raise RuntimeError("simulated audit insert failure")

            _orig = _m.db.job_edits
            _m.db.job_edits = _FakeColl()
            try:
                with pytest.raises(Exception):
                    await patch_job_edit_window(
                        jid, _patch(notes="attempted"),
                        user=_mk_tech_user(tid),
                        tenant=await _tenant_dep(tid),
                    )
            finally:
                _m.db.job_edits = _orig
            job = await _db().jobs.find_one({"id": jid}, {"_id": 0, "notes": 1})
            assert (job.get("notes") or "") != "attempted"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 14. Job-doc mutation failure AFTER audit → audit doc rolled back.
# ═════════════════════════════════════════════════════════════════════
def test_job_mutation_failure_rolls_back_audit_row(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_completed_pool_job(tid)
        try:
            from routers.jobs import patch_job_edit_window
            import routers.jobs as _m

            # Motor returns a fresh AsyncIOMotorCollection on every
            # ``_m.db.jobs`` access, so assigning
            # ``_m.db.jobs.update_one`` never sticks (the instance is
            # thrown away by the next lookup). Wrap the whole jobs
            # collection in a proxy attached to ``_m.db.jobs`` — the
            # attribute lands in ``_m.db.__dict__`` and shadows the
            # dynamic Motor lookup for the duration of the test.
            _orig_jobs = _m.db.jobs

            class _FailingJobs:
                def __init__(self, real):
                    self._real = real

                def __getattr__(self, name):
                    return getattr(self._real, name)

                async def update_one(self, *a, **kw):
                    raise RuntimeError("simulated jobs.update_one failure")

            _m.db.jobs = _FailingJobs(_orig_jobs)
            try:
                with pytest.raises(Exception):
                    await patch_job_edit_window(
                        jid, _patch(notes="rollback-test"),
                        user=_mk_tech_user(tid),
                        tenant=await _tenant_dep(tid),
                    )
            finally:
                # Delete the shadow attribute so Motor's __getattr__
                # kicks in again for subsequent tests.
                try:
                    del _m.db.jobs
                except AttributeError:  # pragma: no cover
                    _m.db.jobs = _orig_jobs
            n = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid},
            )
            assert n == 0, "audit row must be deleted on mutation failure"
        finally:
            await _drain(tid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 15. Mobile offline replay — success inside window, 403 outside.
# ═════════════════════════════════════════════════════════════════════
def test_mobile_offline_replay_edit_inside_and_outside_window():
    async def _go():
        tid = await _tenant_id()
        # (a) Inside window.
        jid_ok = await _mk_completed_pool_job(tid)
        # (b) Outside window.
        jid_late = await _mk_completed_pool_job(
            tid, completed_hours_ago=48.0,
        )
        try:
            from routers.mobile_sync import _handle_job_edit, _SyncOp
            from utils import now_iso
            op_ok = _SyncOp(
                client_op_id=uuid.uuid4().hex, op_type="job.edit",
                entity_id=jid_ok,
                payload={"notes": "offline replay ok",
                          "edit_reason": "typo"},
                client_ts=now_iso(),
            )
            r = await _handle_job_edit(op_ok, tid, "u-mobile")
            assert r["server_id"] == jid_ok
            hist = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid_ok},
            )
            assert hist == 1

            op_late = _SyncOp(
                client_op_id=uuid.uuid4().hex, op_type="job.edit",
                entity_id=jid_late,
                payload={"notes": "too late"},
                client_ts=now_iso(),
            )
            with pytest.raises(HTTPException) as ei:
                await _handle_job_edit(op_late, tid, "u-mobile")
            assert ei.value.status_code == 403
            assert ei.value.detail["detail"] == "edit_window_expired"
            no_hist = await _db().job_edits.count_documents(
                {"tenant_id": tid, "job_id": jid_late},
            )
            assert no_hist == 0
        finally:
            await _drain(tid)

    _run(_go())
