"""Phase DOOR-HANGER · Feb 2026 — DB-template load path.

Locks the contract that ``_build_door_hanger_email`` prefers the
row in ``marketing_templates`` (keyed by
``code="door_hanger_job_completed"``) over the hardcoded fallback
body.  Assertions:

1. When a row is seeded, the rendered subject + body come from the
   DB row — the unique sentinel strings survive into the composed
   email.
2. Tenant-specific rows win over the global default (``tenant_id
   is None``) — the ``sort=[("tenant_id", -1)]`` cascade lands the
   tenant's edited row.
3. ``{{JOB_PHOTOS}}`` inside the DB body is resolved by the
   catalog resolver — a job with photos surfaces the gallery
   inside the tenant-authored surrounding copy.
4. Pre-rendered section-injection tags (``{{DOOR_HANGER_HERO_HTML}}``,
   ``{{DOOR_HANGER_FOOTER_HTML}}``) are substituted from the
   ctx-injections the builder stashes before render.
5. Defense-in-depth: deleting every row (and having zero global
   default) still produces a non-empty body — the hardcoded
   fallback path fires with a WARN log.
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
    import routers.workstream_service_log as _mod
    # Snapshot originals so we can restore them on teardown — the
    # seed-migration test that follows this module in the same
    # pytest invocation uses ``asyncio.get_event_loop()`` and
    # expects ``config.db`` to be bound to a live loop.  Leaking
    # our ``_LOOP``-bound client past module teardown would trip
    # "future belongs to a different loop" once pytest advances
    # to a new module.
    _orig_cfg_db = _cfg.db
    _orig_mod_db = _mod.db
    _cfg.db = fresh_db
    _mod.db = fresh_db
    try:
        yield
    finally:
        _cfg.db = _orig_cfg_db
        _mod.db = _orig_mod_db
        try:
            fresh.close()
        except Exception:
            pass


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


async def _mk_customer(tenant_id: str) -> str:
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Kaylan DBTemplate", "first_name": "Kaylan",
        "last_name": "DBTemplate",
        "email": "kaylan.dbtpl@example.com",
        "phone": "+15555550100",
    })
    return cid


async def _mk_property(tenant_id: str, cid: str) -> str:
    pid = f"test-prop-{uuid.uuid4().hex[:12]}"
    await _db().properties.insert_one({
        "id": pid, "tenant_id": tenant_id, "customer_id": cid,
        "label": "Home", "address": {
            "line1": "42 DB Template Way",
            "city": "Peoria", "state": "AZ", "zip": "85383",
        },
    })
    return pid


async def _mk_pool_job(
    tenant_id: str, cid: str, seed_fields: Dict[str, Any] | None = None,
) -> str:
    from utils import now_iso
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "customer_name": "Kaylan DBTemplate",
        "service_type": "Weekly Pool Service",
        "status": "completed", "completed_at": now_iso(),
        "scheduled_date": now_iso(),
        "title": "Weekly Pool", "created_at": now_iso(),
    }
    if seed_fields:
        doc.update(seed_fields)
    await _db().jobs.insert_one(doc)
    return jid


async def _drain(tenant_id: str, jid: str, cid: str) -> None:
    for coll in ("jobs", "service_reports", "customers", "properties"):
        try:
            await _db()[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [{"id": jid}, {"id": cid}, {"job_id": jid},
                         {"customer_id": cid}]},
            )
        except Exception:
            pass


async def _wipe_door_hanger_rows() -> None:
    """Clear every ``door_hanger_job_completed`` template row so
    each test starts from a known state."""
    await _db().marketing_templates.delete_many(
        {"code": "door_hanger_job_completed"},
    )


async def _build(jid: str, tid: str, cid: str) -> Dict[str, Any]:
    from routers.workstream_service_log import _build_door_hanger_email
    job = await _db().jobs.find_one({"id": jid, "tenant_id": tid}, {"_id": 0})
    tenant = await _db().tenants.find_one({"id": tid}, {"_id": 0})
    cust = await _db().customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0})
    return await _build_door_hanger_email(
        job=job, tenant=tenant, cust=cust or {}, cid=cid,
    )


# ═════════════════════════════════════════════════════════════════════
# 1. Global default row (tenant_id=None) is picked up.
# ═════════════════════════════════════════════════════════════════════
def test_global_default_row_wins_over_hardcoded_fallback():
    async def _go():
        await _wipe_door_hanger_rows()
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        pid = await _mk_property(tid, cid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "property_id": pid, "title": "DB Template Pool",
        })
        from utils import new_id, now_iso
        # Sentinel is a string that the hardcoded fallback body
        # CANNOT emit — proves the DB path fired.
        sentinel = f"DB-TEMPLATE-SENTINEL-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "door_hanger_job_completed",
            "tenant_id": None,
            "name": "Door Hanger — Job Completed",
            "category": "service_completed", "channel": "email",
            "kind": "transactional",
            "subject": "Subject-{{COMPANY_NAME}}",
            "body": (
                f"<html><body>{sentinel}"
                "<!--HERO-->{{DOOR_HANGER_HERO_HTML}}"
                "<!--FOOTER-->{{DOOR_HANGER_FOOTER_HTML}}"
                "</body></html>"
            ),
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        try:
            composed = await _build(jid, tid, cid)
            body = composed["html"]
            subject = composed["subject"]
            assert sentinel in body, (
                "DB-template body did not surface — the builder must "
                "prefer marketing_templates over the hardcoded fallback"
            )
            # Section-injection tags were resolved to the pre-rendered
            # HTML the builder stashes on ctx.
            assert "We appreciate your business" in body, (
                "DOOR_HANGER_FOOTER_HTML did not resolve — footer block "
                "should have been slotted into the DB template body"
            )
            # Subject came from the DB row too (rendered with COMPANY_NAME).
            assert subject.startswith("Subject-"), subject
            assert "Subject-{{COMPANY_NAME}}" != subject, (
                "subject was not rendered through render_template"
            )
        finally:
            await _wipe_door_hanger_rows()
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Tenant-specific row wins over the global default.
# ═════════════════════════════════════════════════════════════════════
def test_tenant_specific_row_wins_over_global_default():
    async def _go():
        await _wipe_door_hanger_rows()
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import new_id, now_iso
        global_sentinel = f"GLOBAL-{uuid.uuid4().hex[:8]}"
        tenant_sentinel = f"TENANT-{uuid.uuid4().hex[:8]}"
        # Seed BOTH rows.  The tenant-specific row must win.
        await _db().marketing_templates.insert_many([
            {"id": new_id(),
             "code": "door_hanger_job_completed",
             "tenant_id": None,
             "subject": "Global Subject", "body": f"<p>{global_sentinel}</p>",
             "category": "service_completed", "channel": "email",
             "kind": "transactional",
             "is_system": True, "is_default": True, "editable": True,
             "created_at": now_iso(), "updated_at": now_iso()},
            {"id": new_id(),
             "code": "door_hanger_job_completed",
             "tenant_id": tid,
             "subject": "Tenant Subject", "body": f"<p>{tenant_sentinel}</p>",
             "category": "service_completed", "channel": "email",
             "kind": "transactional",
             "is_system": False, "is_default": False, "editable": True,
             "created_at": now_iso(), "updated_at": now_iso()},
        ])
        try:
            composed = await _build(jid, tid, cid)
            body = composed["html"]
            assert tenant_sentinel in body, (
                "tenant-specific row must win over the global default — "
                "the sort=[('tenant_id', -1)] cascade should surface "
                "the tenant row when both exist"
            )
            assert global_sentinel not in body
            assert composed["subject"] == "Tenant Subject"
        finally:
            await _wipe_door_hanger_rows()
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. {{JOB_PHOTOS}} inside the DB body renders the gallery.
# ═════════════════════════════════════════════════════════════════════
def test_job_photos_tag_inside_db_body_renders_gallery():
    async def _go():
        await _wipe_door_hanger_rows()
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        pid = await _mk_property(tid, cid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "property_id": pid,
            "photos": [{
                "id": "dbtpl-photo-a",
                "data": "data:image/png;base64,iVBORw==",
                "label": "before",
                "created_at": "2026-02-20T00:00:00+00:00",
            }],
        })
        from utils import new_id, now_iso
        sentinel = f"WRAP-{uuid.uuid4().hex[:8]}"
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "door_hanger_job_completed",
            "tenant_id": None,
            "subject": "Subj", "body": (
                f"<div>{sentinel}-START</div>"
                "{{JOB_PHOTOS}}"
                f"<div>{sentinel}-END</div>"
            ),
            "category": "service_completed", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        try:
            composed = await _build(jid, tid, cid)
            body = composed["html"]
            # DB sentinel present (proves template path).
            assert f"{sentinel}-START" in body
            assert f"{sentinel}-END" in body
            # {{JOB_PHOTOS}} substituted with the gallery.
            assert "{{JOB_PHOTOS}}" not in body
            assert "Service Photos" in body
            assert "dbtpl-photo-a" in body
            # Gallery sits between the two DB sentinels.
            start = body.index(f"{sentinel}-START")
            end = body.index(f"{sentinel}-END")
            gallery = body.index("Service Photos")
            assert start < gallery < end, (start, gallery, end)
        finally:
            await _wipe_door_hanger_rows()
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. Defense-in-depth: no row at all → hardcoded fallback fires.
# ═════════════════════════════════════════════════════════════════════
def test_hardcoded_fallback_still_produces_valid_body_when_row_absent():
    async def _go():
        await _wipe_door_hanger_rows()
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        pid = await _mk_property(tid, cid)
        jid = await _mk_pool_job(tid, cid, seed_fields={"property_id": pid})
        try:
            composed = await _build(jid, tid, cid)
            body = composed["html"]
            # Non-empty + carries the hardcoded copy.
            assert isinstance(body, str) and len(body) > 500, (
                f"fallback body must be non-empty, got len={len(body)}"
            )
            # Baseline copy the hardcoded fallback emits directly.
            assert "your visit has been completed" in body
            assert "We appreciate your business" in body
            # Subject follows the hardcoded ``Job Completed - {company}``
            # convention.
            assert composed["subject"].startswith("Job Completed - ")
            # A sentinel from the DB test above MUST NOT appear —
            # confirms this is the fallback path.
            assert "DB-TEMPLATE-SENTINEL" not in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5. Malformed DB body → builder logs + falls back gracefully.
# ═════════════════════════════════════════════════════════════════════
def test_empty_db_body_falls_back_to_hardcoded():
    """A template row with an empty body should not blank-out the
    outbound email.  The builder falls back to the hardcoded body
    (the ``if tpl and tpl.get('body'):`` guard covers this)."""
    async def _go():
        await _wipe_door_hanger_rows()
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)
        from utils import new_id, now_iso
        await _db().marketing_templates.insert_one({
            "id": new_id(),
            "code": "door_hanger_job_completed",
            "tenant_id": None,
            "subject": "Subj", "body": "",   # empty body — must fall back
            "category": "service_completed", "channel": "email",
            "kind": "transactional",
            "is_system": True, "is_default": True, "editable": True,
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        try:
            composed = await _build(jid, tid, cid)
            body = composed["html"]
            assert len(body) > 500
            assert "your visit has been completed" in body
            assert "We appreciate your business" in body
        finally:
            await _wipe_door_hanger_rows()
            await _drain(tid, jid, cid)

    _run(_go())
