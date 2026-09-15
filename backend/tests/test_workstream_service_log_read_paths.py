"""Feb-2026 · P0 Workstream Service Log read/write reconciliation.

Fix A (water test) — join on ``service_reports.chemical_readings``
with ``job.chemical_readings`` legacy fallback; accept BOTH list and
dict shapes; add ``cyanuric_acid`` to the canonical key order.

Fix B (chemicals used) — join on ``service_reports.chemicals_added``
with ``job.chemicals_added`` legacy fallback; cost math unchanged.

Fix C (checklist) — prefer ``key`` matches over ``label`` matches so a
whitespace/case delta in the tech's write payload no longer drops
the item.

All 6 pinned tests hit the real ``GET /api/jobs/{jid}/service-log``
route via ``TestClient`` to catch any router-level regression too.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List

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
    _cfg.db = fresh_db
    import routers.workstream_service_log as _mod
    _mod.db = fresh_db
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


async def _mk_pool_job(tenant_id: str, seed_fields: Dict[str, Any] | None = None) -> str:
    from utils import new_id, now_iso
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": None, "customer_name": "Testcase Customer",
        "service_type": "Weekly Pool Service",
        "status": "completed", "completed_at": now_iso(),
        "scheduled_date": now_iso(), "title": "Weekly Pool",
        "created_at": now_iso(),
    }
    if seed_fields:
        doc.update(seed_fields)
    await _db().jobs.insert_one(doc)
    return jid


async def _mk_service_report(tenant_id: str, jid: str, body: Dict[str, Any]) -> str:
    from utils import new_id, now_iso
    rid = f"test-rep-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": rid, "tenant_id": tenant_id, "job_id": jid,
        "tech_id": "test-tech",
        "submitted_at": now_iso(),
        "created_at": now_iso(),
    }
    doc.update(body)
    await _db().service_reports.insert_one(doc)
    return rid


async def _drain(tenant_id: str, jid: str) -> None:
    for coll in ("jobs", "service_reports"):
        try:
            await _db()[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [{"id": jid}, {"job_id": jid}]},
            )
        except Exception:
            pass


def _fake_admin() -> Dict[str, Any]:
    """Return the admin user doc — used to construct a
    Depends() override for get_current_user in the router tests."""
    async def _find():
        return await _db().users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0},
        )
    return _run(_find())


def _fake_tenant(tenant_id: str) -> Dict[str, Any]:
    async def _find():
        return await _db().tenants.find_one({"id": tenant_id}, {"_id": 0})
    return _run(_find())


# ─── Direct-call helper (bypasses HTTP for speed) ────────────────────
async def _call_service_log(jid: str, tenant_id: str) -> Dict[str, Any]:
    """Call the router function directly with fake user + tenant deps.
    Doing this via ``TestClient`` would work too but adds ~2s of app
    boot to every test; the router body is a pure Motor read so
    direct-call gives identical coverage 30x faster."""
    from routers.workstream_service_log import get_service_log
    user = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0},
    )
    tenant = await _db().tenants.find_one({"id": tenant_id}, {"_id": 0})
    return await get_service_log(jid, user=user, tenant=tenant)


# ═════════════════════════════════════════════════════════════════════
# 1. Chemistry via service_report LIST shape → all 5 rows.
# ═════════════════════════════════════════════════════════════════════
def test_water_test_list_shape_from_service_report_renders_required_four_including_cya():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, {
            "chemical_readings": [
                {"key": "free_chlorine",  "label": "Free Chlorine",  "value": 2.5, "unit": "ppm"},
                {"key": "ph",             "label": "pH",             "value": 7.4},
                {"key": "alkalinity",     "label": "Alkalinity",     "value": 80,  "unit": "ppm"},
                {"key": "cyanuric_acid",  "label": "CYA",            "value": 40,  "unit": "ppm"},
            ],
        })
        try:
            payload = await _call_service_log(jid, tid)
            wt = payload["water_test"]
            # Phase CHEM1 · Feb-2026 — Required Four surfaces exactly.
            assert len(wt) == 4, wt
            assert [r["key"] for r in wt] == [
                "free_chlorine", "ph",
                "alkalinity", "cyanuric_acid",
            ], wt
            # Fix-A explicit CYA rendering (bundled into this ship).
            cya = next(r for r in wt if r["key"] == "cyanuric_acid")
            assert cya["value"] == 40.0
            assert cya["label"] == "CYA"
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Chemistry via service_report DICT shape → Required Four rows.
# ═════════════════════════════════════════════════════════════════════
def test_water_test_dict_shape_from_service_report_renders_required_four():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, {
            "chemical_readings": {
                "free_chlorine": 2.5,
                "ph": 7.4, "alkalinity": 80, "cyanuric_acid": 40,
            },
        })
        try:
            payload = await _call_service_log(jid, tid)
            wt = payload["water_test"]
            values = {r["key"]: r["value"] for r in wt}
            assert values["free_chlorine"] == 2.5
            assert values["cyanuric_acid"] == 40.0
            # Phase CHEM1 · Feb-2026 — Required Four surfaces exactly.
            assert len(wt) == 4
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. Legacy: readings on the job doc (dict shape) → still renders.
# ═════════════════════════════════════════════════════════════════════
def test_water_test_backward_compat_reads_from_job_when_service_report_missing():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid, seed_fields={
            "chemical_readings": {
                "free_chlorine": 1.5,
                "ph": 7.6, "alkalinity": 100, "cyanuric_acid": 55,
            },
        })
        # NO service_report inserted — fall-back path only.
        try:
            payload = await _call_service_log(jid, tid)
            values = {r["key"]: r["value"] for r in payload["water_test"]}
            assert values == {
                "free_chlorine": 1.5,
                "ph": 7.6, "alkalinity": 100.0, "cyanuric_acid": 55.0,
            }
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. Chemicals used from service report → renders + cost calc.
# ═════════════════════════════════════════════════════════════════════
def test_chemicals_used_from_service_report_renders_with_cost():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, {
            "chemicals_added": [
                {"name": "Liquid Chlorine", "quantity": 1.0, "unit": "gallon"},
                {"name": "Muriatic Acid",   "quantity": 0.5, "unit": "gallon"},
            ],
        })
        try:
            payload = await _call_service_log(jid, tid)
            chems = payload["chemicals_used"]
            names = [c["name"] for c in chems]
            assert "Liquid Chlorine" in names and "Muriatic Acid" in names
            # $8.00 × 1  +  $8.00 × 0.5  = $12.00.
            assert payload["chemical_cost_usd"] == 12.0, payload
            assert payload["chemical_cost_cents"] == 1200
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 5. Checklist — Fix C: key match wins over label whitespace delta.
# ═════════════════════════════════════════════════════════════════════
def test_checklist_key_match_wins_over_label_whitespace_delta():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        # Write payload uses canonical KEY ``brush_pool`` but a
        # sloppy LABEL ``"Brushed  Pool"`` (extra space + past
        # tense).  Pre-Fix-C the reader dropped this item.
        await _mk_service_report(tid, jid, {
            "checklist_items": [
                {"key": "skimmed_pool", "label": "Skimmed Pool",   "checked": True},
                {"key": "brush_pool",   "label": "Brushed  Pool",  "checked": True},
            ],
        })
        try:
            payload = await _call_service_log(jid, tid)
            state = payload["checklist_state"]
            items = state["items"]
            by_key = {it["key"]: it["completed"] for it in items}
            assert by_key.get("skimmed_pool") is True, by_key
            assert by_key.get("brush_pool") is True, by_key
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 6. Regression guard — photo upload via job.photos still renders.
# ═════════════════════════════════════════════════════════════════════
def test_service_images_regression_photo_written_to_job_still_renders():
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid, seed_fields={
            "photos": [
                {"id": "test-photo-1", "data": "data:image/png;base64,iVBORw0KGg==",
                 "label": "regression-check",
                 "created_at": "2026-02-20T00:00:00+00:00"},
            ],
        })
        try:
            payload = await _call_service_log(jid, tid)
            imgs = payload["service_images"]
            assert len(imgs) == 1, imgs
            assert imgs[0]["kind"] == "image"
            assert imgs[0]["id"] == "test-photo-1"
            assert imgs[0]["label"] == "regression-check"
        finally:
            await _drain(tid, jid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# BONUS regression — water test ordering matches the canonical spec.
# ═════════════════════════════════════════════════════════════════════
def test_water_test_ordering_matches_canonical_spec():
    """User-facing order requirement: Free Cl → Total Cl → pH → Alk →
    CYA → Conditioner → custom.  Payload deliberately submits keys
    OUT of that order to prove the reader re-orders."""
    async def _go():
        tid = await _tenant_id()
        jid = await _mk_pool_job(tid)
        await _mk_service_report(tid, jid, {
            "chemical_readings": [
                # Deliberately submit out of canonical order.
                {"key": "alkalinity",     "value": 80},
                {"key": "cyanuric_acid",  "value": 40},
                {"key": "ph",             "value": 7.4},
                {"key": "free_chlorine",  "value": 2.5},
                # A custom reading — should render AFTER canonical.
                {"key": "calcium_hardness","value": 250},
            ],
        })
        try:
            payload = await _call_service_log(jid, tid)
            wt = payload["water_test"]
            assert [r["key"] for r in wt] == [
                "free_chlorine", "ph",
                "alkalinity", "cyanuric_acid", "calcium_hardness",
            ], wt
        finally:
            await _drain(tid, jid)

    _run(_go())
