"""Feb-2026 · P0 Door hanger email — body composition tests.

Pre-fix the door hanger email body was:

    We stopped by, Brian Beckman.
    Your service was completed on 2026-07-26.
    Notes: —
    (nothing else)

…for every real tech submission, because the composer only read
``job.notes`` / ``job.service_notes`` and never joined
``service_reports`` for the chemistry / chemicals / checklist / photos.

Post-fix the composer uses the same
``services/service_report_view.*`` resolvers the Workstream Service
Log page uses.  These tests exercise the composer end-to-end (via
``TestClient`` on the FastAPI app) with the Resend adapter stubbed
so no live email is sent.
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


async def _mk_customer(tenant_id: str) -> str:
    from utils import new_id, now_iso
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Kaylan Testcase",
        "first_name": "Kaylan", "last_name": "Testcase",
        "email": "kaylan.testcase@example.com",
        "phone": "+15555550100",
    })
    return cid


async def _mk_pool_job(
    tenant_id: str, cid: str, seed_fields: Dict[str, Any] | None = None,
) -> str:
    from utils import new_id, now_iso
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    doc = {
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "customer_name": "Kaylan Testcase",
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
    for coll in ("jobs", "service_reports", "customers", "marketing_deliveries"):
        try:
            await _db()[coll].delete_many(
                {"tenant_id": tenant_id,
                 "$or": [{"id": jid}, {"id": cid}, {"job_id": jid},
                         {"trigger_entity.id": jid}]},
            )
        except Exception:
            pass


def _stub_email_send(monkeypatch) -> Dict[str, Any]:
    """Replace ``services.email.resend_adapter.send`` with a stub that
    records the call args and returns a mock envelope.  Returns the
    dict the test can inspect to see what was sent."""
    from services.email import resend_adapter as _resend
    captured: Dict[str, Any] = {}

    async def _fake_send(**kwargs):
        captured.update(kwargs)
        return {"provider": "mock", "provider_status": "queued",
                "provider_response_id": None, "attempts": 1, "error": None}

    monkeypatch.setattr(_resend, "send", _fake_send, raising=True)
    return captured


async def _call_email_door_hanger(jid: str, tenant_id: str) -> Dict[str, Any]:
    from routers.workstream_service_log import email_door_hanger
    user = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0},
    )
    tenant = await _db().tenants.find_one({"id": tenant_id}, {"_id": 0})
    return await email_door_hanger(jid, user=user, tenant=tenant)


# ═════════════════════════════════════════════════════════════════════
# 1. Full submission — every section renders in the body.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_full_body_contains_every_section(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "photos": [{
                "id": "test-photo-a", "data": "data:image/png;base64,iVBORw==",
                "label": "before", "created_at": "2026-02-20T00:00:00+00:00",
            }],
        })
        # Simulate a tech PATCH → the service_report doc.
        from utils import new_id, now_iso
        await _db().service_reports.insert_one({
            "id": f"test-rep-{uuid.uuid4().hex[:8]}",
            "tenant_id": tid, "job_id": jid, "tech_id": "test-tech",
            "chemical_readings": [
                {"key": "free_chlorine",  "value": 2.5, "unit": "ppm"},
                {"key": "total_chlorine", "value": 3.0, "unit": "ppm"},
                {"key": "ph",             "value": 7.4},
                {"key": "alkalinity",     "value": 80,  "unit": "ppm"},
                {"key": "cyanuric_acid",  "value": 40,  "unit": "ppm"},
            ],
            "chemicals_added": [{"name": "Liquid Chlorine", "quantity": 1.0, "unit": "gallon"}],
            "checklist_items": [
                {"key": "skimmed_pool",     "label": "Skimmed Pool",     "checked": True},
                {"key": "brush_pool",       "label": "Brush Pool",       "checked": True},
                {"key": "tested_chemicals", "label": "Tested Chemicals", "checked": True},
            ],
            "notes": "Pump strainer basket was full. Emptied + rinsed.",
            "submitted_at": now_iso(),
        })

        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r.get("ok") is True, r
            body = captured.get("html") or ""
            # Chemistry — every canonical field + CYA specifically.
            assert "Free Chlorine" in body, body[:300]
            assert "Total Chlorine" in body
            assert "Ph Balance" in body
            assert "Alkalinity" in body
            assert "CYA" in body
            assert "40 ppm" in body or "40.0 ppm" in body, body[:400]
            # Chemicals used.
            assert "Liquid Chlorine" in body
            assert "$8.00" in body, body[:600]
            # Checklist — checked items rendered.
            assert "Skimmed Pool" in body
            assert "Brush Pool" in body
            assert "Tested Chemicals" in body
            # Notes.
            assert "Pump strainer basket was full" in body
            assert "Notes: &mdash;" not in body and "Notes: —" not in body
            # Photos — inline absolute URL.
            assert "test-photo-a" in body
            assert "http" in body  # absolute URL prefix
            assert "/api/public/job-photo/" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 2. Legacy fallback — data on the job doc still renders.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_legacy_readings_on_job_doc_still_render(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "chemical_readings": {
                "free_chlorine": 1.8, "total_chlorine": 2.4,
                "ph": 7.5, "alkalinity": 90, "cyanuric_acid": 45,
            },
            "chemicals_added": [
                {"name": "Muriatic Acid", "quantity": 0.5, "unit": "gallon"},
            ],
            "notes": "Legacy path — inline job.notes.",
        })
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            assert "CYA" in body
            assert "45" in body
            assert "Muriatic Acid" in body
            assert "Legacy path" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 3. Absolute photo URLs — no leading-slash-only paths.
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_photo_urls_are_absolute(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid, seed_fields={
            "photos": [
                {"id": "abs-1", "data": "data:image/png;base64,iVBORw==",
                 "label": "front", "created_at": "2026-02-20T00:00:00+00:00"},
            ],
        })
        # Ensure a base URL is present.  Preview .env has APP_BASE_URL
        # blank so the resolver falls back to the hard-coded prod URL.
        monkeypatch.setenv("PUBLIC_APP_BASE_URL", "https://app.plofv.com")
        captured = _stub_email_send(monkeypatch)
        try:
            await _call_email_door_hanger(jid, tid)
            body = captured.get("html") or ""
            # Assert the src attribute is absolute — the composer must
            # NOT emit ``src="/api/public/job-photo/…"`` (some email
            # clients treat leading slashes as broken links).
            assert 'src="https://app.plofv.com/api/public/job-photo/' in body, body[:800]
        finally:
            await _drain(tid, jid, cid)

    _run(_go())


# ═════════════════════════════════════════════════════════════════════
# 4. No service report at all — email still renders (no crash).
# ═════════════════════════════════════════════════════════════════════
def test_door_hanger_empty_report_renders_gracefully(monkeypatch):
    async def _go():
        tid = await _tenant_id()
        cid = await _mk_customer(tid)
        jid = await _mk_pool_job(tid, cid)  # no report, no readings, no photos
        captured = _stub_email_send(monkeypatch)
        try:
            r = await _call_email_door_hanger(jid, tid)
            assert r["ok"] is True
            body = captured.get("html") or ""
            # Baseline copy still present…
            assert "We stopped by" in body
            assert "Kaylan Testcase" in body
            # …and the empty-notes fallback line still fires.
            assert "Notes: —" in body
        finally:
            await _drain(tid, jid, cid)

    _run(_go())
