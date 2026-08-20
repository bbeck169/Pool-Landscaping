"""Feb-2026 · P0 Tech-name resolution — 4-rung cascade tests.

The ``resolve_technician_names`` helper in
``services.service_report_view`` tolerates the tech-ID fragmentation
where ``job.technician_id`` is stored inconsistently across ~7 write
paths (some paths write ``technicians.id``, others write ``users.id``).
Each of the 5 tests below locks in one cascade rung + the orphan case.
"""
from __future__ import annotations
import asyncio, os, uuid
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
    d = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = d
    import routers.workstream_service_log as _mod; _mod.db = d
    import routers.workstream as _ws; _ws.db = d
    import routers.jobs as _jobs; _jobs.db = d
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _tenant_id():
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _mk_user(tid, name, role="technician"):
    uid = f"test-user-{uuid.uuid4().hex[:12]}"
    await _db().users.insert_one({
        "id": uid, "tenant_id": tid, "role": role,
        "name": name, "email": f"{uid}@example.com",
    })
    return uid


async def _mk_tech(tid, name, user_id=None):
    tech_id = f"test-tech-{uuid.uuid4().hex[:12]}"
    await _db().technicians.insert_one({
        "id": tech_id, "tenant_id": tid, "name": name,
        "user_id": user_id, "department": "pool",
    })
    return tech_id


async def _cleanup(tid):
    for coll in ("users", "technicians"):
        await _db()[coll].delete_many(
            {"tenant_id": tid, "id": {"$regex": "^test-"}})


# ═════════════ Rung 1 — technicians.id ═════════════
def test_rung1_resolves_via_technicians_id():
    async def _go():
        from services.service_report_view import resolve_technician_names
        tid = await _tenant_id()
        t_id = await _mk_tech(tid, "Mike Rivera")
        try:
            m = await resolve_technician_names(_db(), tid, [t_id])
            assert m == {t_id: "Mike Rivera"}, m
        finally:
            await _cleanup(tid)
    _run(_go())


# ═════════════ Rung 2 — technicians.user_id back-ref ═════════════
def test_rung2_resolves_via_technicians_user_id_backref():
    async def _go():
        from services.service_report_view import resolve_technician_names
        tid = await _tenant_id()
        uid = await _mk_user(tid, "Ethan Smith")
        _t_id = await _mk_tech(tid, "Ethan Smith", user_id=uid)
        try:
            m = await resolve_technician_names(_db(), tid, [uid])
            assert m.get(uid) == "Ethan Smith", m
        finally:
            await _cleanup(tid)
    _run(_go())


# ═════════════ Rung 3 — users.id direct ═════════════
def test_rung3_resolves_via_users_id_when_no_technician_row():
    async def _go():
        from services.service_report_view import resolve_technician_names
        tid = await _tenant_id()
        # user exists as tech, but NO technicians row — mimic the
        # prod state for Ethan Smith before a tech doc was created.
        uid = await _mk_user(tid, "Ethan Smith")
        try:
            m = await resolve_technician_names(_db(), tid, [uid])
            assert m.get(uid) == "Ethan Smith", m
        finally:
            await _cleanup(tid)
    _run(_go())


# ═════════════ Rung 4 — first_name + last_name synth ═════════════
def test_rung4_resolves_via_first_last_when_name_field_missing():
    async def _go():
        from services.service_report_view import resolve_technician_names
        tid = await _tenant_id()
        uid = f"test-user-{uuid.uuid4().hex[:12]}"
        await _db().users.insert_one({
            "id": uid, "tenant_id": tid, "role": "technician",
            "first_name": "Ethan", "last_name": "Smith",
        })
        try:
            m = await resolve_technician_names(_db(), tid, [uid])
            assert m.get(uid) == "Ethan Smith", m
        finally:
            await _cleanup(tid)
    _run(_go())


# ═════════════ Orphan — id resolves nowhere ═════════════
def test_orphan_id_returns_empty_map_entry():
    async def _go():
        from services.service_report_view import resolve_technician_names
        tid = await _tenant_id()
        orphan = f"orphan-{uuid.uuid4().hex[:12]}"
        m = await resolve_technician_names(_db(), tid, [orphan])
        assert orphan not in m, m
    _run(_go())


# ═════════════ Pool Service Report body — end-to-end ═════════════
def test_pool_service_report_renders_tech_name_via_user_id_shape():
    async def _go():
        from routers.jobs import compute_pool_service
        tid = await _tenant_id()
        uid = await _mk_user(tid, "Ethan Smith")
        # Seed 3 completed pool jobs assigned via users.id shape,
        # in the current week window (compute_pool_service reads
        # ``scheduled_date`` range).
        from datetime import date, timedelta
        d0 = date.today() - timedelta(days=1)
        seeded_ids = []
        for i in range(3):
            jid = f"test-job-{uuid.uuid4().hex[:12]}"
            seeded_ids.append(jid)
            await _db().jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": None, "customer_name": f"C{i}",
                "service_type": "Weekly Pool Service",
                "status": "completed",
                "technician_id": uid,  # users.id shape (the bug)
                "scheduled_date": d0.isoformat(),
            })
        try:
            r = await compute_pool_service(tid, d0.isoformat(),
                (d0 + timedelta(days=1)).isoformat())
            rows = r.get("rows") or []
            ethan = [row for row in rows
                       if row.get("technician_name") == "Ethan Smith"]
            assert ethan, f"Expected Ethan Smith row, got: {rows}"
            assert ethan[0]["completed"] == 3, ethan
            unknowns = [row for row in rows
                        if row.get("technician_name") == "Unknown"]
            assert not unknowns, f"Expected 0 Unknown rows, got: {unknowns}"
        finally:
            await _db().jobs.delete_many({"id": {"$in": seeded_ids}})
            await _cleanup(tid)
    _run(_go())
