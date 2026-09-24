"""Task L+P · Commit 5 — JobDetail aggregator SR photos slice.

Locks the ``service_report_photos`` field on the
``GET /api/jobs/{id}/detail`` response
(``backend/routers/workstream_job_detail.py``):

  * Populated via the shared Commit-1 merge (``_media_items``)
    filtered to ``source == "service_report"`` and ``kind ==
    "image"``.
  * Empty list when the job has no SR photos (NOT ``None`` /
    absent).
  * Dedupe policy: id collision with ``jobs.photos`` → SR wins
    (already handled by ``_media_items``).
  * Tenant-scoped: cross-tenant SR photos never leak.
  * Deleted-photo filters honoured on both shapes
    (``deleted_at`` on SR doc + ``is_deleted`` per photo).
  * Access model unchanged: customer → 403; tech → 403 unless
    authorised on the job; admin → full payload.
  * All pre-existing payload keys still present (backward compat
    on every other section).
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "TASKLC5_"

# Payload keys that MUST always be present on the /detail response
# (backward compat guard).  Task L+P Commit 5 adds ONE new key
# (``service_report_photos``); every other key on this set is
# pre-Commit-5.
_LEGACY_PAYLOAD_KEYS = {
    "header", "media", "line_items", "notes",
    "checklist", "forms", "timeline",
}
_TASK_L_PAYLOAD_KEYS = _LEGACY_PAYLOAD_KEYS | {"service_report_photos"}


# ─── Sync fixtures ─────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_jids: List[str] = []
    seeded_report_ids: List[str] = []
    yield seeded_jids, seeded_report_ids
    if seeded_jids:
        dbc.jobs.delete_many({"id": {"$in": seeded_jids}})
        dbc.service_reports.delete_many({"job_id": {"$in": seeded_jids}})
    if seeded_report_ids:
        dbc.service_reports.delete_many({"id": {"$in": seeded_report_ids}})


# ─── Loop + Motor db swap ──────────────────────────────────────────
def _loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    # Swap on BOTH modules: the aggregator (workstream_job_detail)
    # and the merge helper it depends on (workstream_service_log).
    from routers import (
        workstream_job_detail as _wjd,
        workstream_service_log as _wsl,
    )
    _wjd._orig_db_for_test = getattr(_wjd, "_orig_db_for_test", _wjd.db)
    _wsl._orig_db_for_test = getattr(_wsl, "_orig_db_for_test", _wsl.db)
    _wjd.db = adb
    _wsl.db = adb
    return loop, client, adb


def _restore_db(client=None, loop=None):
    from routers import (
        workstream_job_detail as _wjd,
        workstream_service_log as _wsl,
    )
    if hasattr(_wjd, "_orig_db_for_test"):
        _wjd.db = _wjd._orig_db_for_test
    if hasattr(_wsl, "_orig_db_for_test"):
        _wsl.db = _wsl._orig_db_for_test
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    if loop is not None:
        try:
            loop.close()
        except Exception:
            pass


def _run(async_call):
    loop, client, _adb = _loop_and_db()
    try:
        return loop.run_until_complete(async_call)
    finally:
        _restore_db(client, loop)


# ─── Seed helpers ──────────────────────────────────────────────────
def _fresh_id(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job_sync(dbc, tenant_id: str, *,
                    photos: List[dict] = None,
                    status: str = "completed",
                    technician_id: str = None) -> str:
    jid = _fresh_id("JOB")
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "title": "Task L+P C5 seed", "status": status,
        "photos": photos if photos is not None else [],
        "created_at": "2026-02-01T00:00:00Z",
    }
    if technician_id:
        doc["technician_id"] = technician_id
    dbc.jobs.insert_one(doc)
    return jid


def _seed_report_sync(dbc, tenant_id: str, job_id: str, *,
                       photos: List[dict] = None,
                       deleted_at: Any = None) -> str:
    rid = _fresh_id("SR")
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id, "job_id": job_id,
        "public_uuid": uuid.uuid4().hex,
        "photos": photos if photos is not None else [],
    }
    if deleted_at is not None:
        doc["deleted_at"] = deleted_at
    dbc.service_reports.insert_one(doc)
    return rid


def _sr_photo(pid: str, *,
              url: str = None, created_at: str = "2026-02-01T00:05:00Z",
              is_deleted: bool = False) -> dict:
    return {
        "id": pid,
        "url": url or f"/api/public/service/u/photo/{pid}",
        "mime": "image/jpeg", "content_type": "image/jpeg",
        "size_bytes": 1024,
        "uploaded_at": created_at, "created_at": created_at,
        "is_deleted": is_deleted,
    }


def _job_photo(pid: str, *, created_at: str = "2026-02-01T00:07:00Z") -> dict:
    return {
        "id": pid, "data": "data:image/jpeg;base64,AAAA",
        "label": "jobs.photos", "created_at": created_at,
    }


# ═══════════════════════════════════════════════════════════════════
# 1) _build_service_report_photos helper — unit tests
# ═══════════════════════════════════════════════════════════════════
def test_build_sr_photos_populates_from_sr_source(dbc, cleanup):
    """SR has 2 photos → helper returns 2 entries, each tagged
    ``source=service_report`` and ``kind=image``."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("sr-a"), _sr_photo("sr-b"),
    ])
    seeded_report_ids.append(rid)

    from routers.workstream_job_detail import _build_service_report_photos
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    out = _run(_build_service_report_photos(job, tenant_id))
    assert isinstance(out, list)
    ids = {i["id"] for i in out}
    assert ids == {"sr-a", "sr-b"}
    for i in out:
        assert i["source"] == "service_report"
        assert i["kind"] == "image"


def test_build_sr_photos_empty_when_no_sr_row(dbc, cleanup):
    """No SR doc for the job → returns ``[]``, never ``None``."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id,
                          photos=[_job_photo("only-jp")])
    seeded_jids.append(jid)

    from routers.workstream_job_detail import _build_service_report_photos
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    out = _run(_build_service_report_photos(job, tenant_id))
    assert out == []
    assert isinstance(out, list)


def test_build_sr_photos_excludes_legacy_jobs_photos(dbc, cleanup):
    """Legacy ``jobs.photos`` entries never appear in the SR slice
    — those belong to the existing ``media.photos`` grid."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo("legacy-jp-1"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("sr-x"),
    ])
    seeded_report_ids.append(rid)

    from routers.workstream_job_detail import _build_service_report_photos
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    out = _run(_build_service_report_photos(job, tenant_id))
    ids = {i["id"] for i in out}
    assert ids == {"sr-x"}
    assert "legacy-jp-1" not in ids


def test_build_sr_photos_dedupes_id_collision_sr_wins(dbc, cleanup):
    """Same id in both ``jobs.photos`` AND ``service_reports.photos``
    → single entry in the SR slice with ``source=service_report``.
    The jobs.photos entry never reaches this slice (it stays in
    ``media.photos`` on the same response).
    """
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    shared_id = "shared-x"
    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(shared_id),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo(shared_id, url="/api/public/service/u/photo/shared-x"),
    ])
    seeded_report_ids.append(rid)

    from routers.workstream_job_detail import _build_service_report_photos
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    out = _run(_build_service_report_photos(job, tenant_id))
    assert len(out) == 1
    assert out[0]["id"] == shared_id
    assert out[0]["source"] == "service_report"
    assert out[0]["url"] == "/api/public/service/u/photo/shared-x"


def test_build_sr_photos_filters_deleted_shapes(dbc, cleanup):
    """Both tombstone shapes honoured: SR-doc-level ``deleted_at``
    hides all photos on the doc; per-photo ``is_deleted`` hides
    that photo only."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup

    # Case A: SR doc soft-deleted → helper returns [].
    jid_a = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid_a)
    rid_a = _seed_report_sync(
        dbc, tenant_id, jid_a,
        photos=[_sr_photo("in-deleted-sr")],
        deleted_at="2026-02-01T12:00:00Z",
    )
    seeded_report_ids.append(rid_a)

    from routers.workstream_job_detail import _build_service_report_photos
    job_a = dbc.jobs.find_one({"id": jid_a, "tenant_id": tenant_id},
                                {"_id": 0})
    out_a = _run(_build_service_report_photos(job_a, tenant_id))
    assert out_a == []

    # Case B: SR doc live, 2 photos where 1 is soft-deleted → only
    # the live photo returned.
    jid_b = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid_b)
    rid_b = _seed_report_sync(dbc, tenant_id, jid_b, photos=[
        _sr_photo("live-photo"),
        _sr_photo("dead-photo", is_deleted=True),
    ])
    seeded_report_ids.append(rid_b)
    job_b = dbc.jobs.find_one({"id": jid_b, "tenant_id": tenant_id},
                                {"_id": 0})
    out_b = _run(_build_service_report_photos(job_b, tenant_id))
    ids_b = {i["id"] for i in out_b}
    assert ids_b == {"live-photo"}


def test_build_sr_photos_cross_tenant_isolation(dbc, cleanup):
    """Called with tenant A's id + a stale tenant-B job dict →
    tenant B's SR photos MUST NOT surface."""
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    seeded_jids, seeded_report_ids = cleanup

    jid_b = _seed_job_sync(dbc, tenant_b, photos=[])
    seeded_jids.append(jid_b)
    rid_b = _seed_report_sync(dbc, tenant_b, jid_b, photos=[
        _sr_photo("tenant-b-secret"),
    ])
    seeded_report_ids.append(rid_b)

    from routers.workstream_job_detail import _build_service_report_photos
    stale_view = {"id": jid_b, "tenant_id": tenant_b, "photos": []}
    out = _run(_build_service_report_photos(stale_view, tenant_a))
    assert out == []


# ═══════════════════════════════════════════════════════════════════
# 2) Endpoint-level tests — payload contract
# ═══════════════════════════════════════════════════════════════════
def _make_tenant_dep(tenant_id: str):
    return {"id": tenant_id, "name": "test tenant"}


def _admin_user():
    return {"id": _fresh_id("USR"), "role": "admin"}


def _tech_user(tid: str):
    return {"id": tid, "role": "technician", "technician_id": tid}


def test_endpoint_payload_carries_service_report_photos(dbc, cleanup):
    """Admin caller hits ``/api/jobs/{id}/detail`` — response
    includes a ``service_report_photos`` list with expected count.
    All legacy keys preserved."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo("keep-jp"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("sr-1"), _sr_photo("sr-2"),
    ])
    seeded_report_ids.append(rid)

    from routers.workstream_job_detail import get_job_detail
    with patch("services.authz.is_tech_authorized_on_job",
                return_value=True):
        payload = _run(get_job_detail(
            jid, _admin_user(), _make_tenant_dep(tenant_id),
        ))

    # Backward-compat guard: every legacy key still present.
    assert _LEGACY_PAYLOAD_KEYS.issubset(set(payload.keys()))
    # New key surfaces.
    assert "service_report_photos" in payload
    ids = {i["id"] for i in payload["service_report_photos"]}
    assert ids == {"sr-1", "sr-2"}
    # Legacy jobs.photos entry still appears in ``media.photos``.
    media_ids = {i["id"] for i in payload["media"]["photos"]}
    assert "keep-jp" in media_ids
    # And is NOT in the SR slice.
    assert "keep-jp" not in ids


def test_endpoint_service_report_photos_empty_when_no_sr(dbc, cleanup):
    """Job with no SR row → ``service_report_photos == []``."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[_job_photo("only-jp")])
    seeded_jids.append(jid)

    from routers.workstream_job_detail import get_job_detail
    with patch("services.authz.is_tech_authorized_on_job",
                return_value=True):
        payload = _run(get_job_detail(
            jid, _admin_user(), _make_tenant_dep(tenant_id),
        ))
    assert payload["service_report_photos"] == []


def test_endpoint_response_shape_locked(dbc, cleanup):
    """Response top-level key set is EXACTLY the legacy set +
    ``service_report_photos`` — no accidental new keys."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)

    from routers.workstream_job_detail import get_job_detail
    with patch("services.authz.is_tech_authorized_on_job",
                return_value=True):
        payload = _run(get_job_detail(
            jid, _admin_user(), _make_tenant_dep(tenant_id),
        ))
    assert set(payload.keys()) == _TASK_L_PAYLOAD_KEYS


# ═══════════════════════════════════════════════════════════════════
# 3) Access-model regression — customer / tech (auth outcome)
# ═══════════════════════════════════════════════════════════════════
def test_endpoint_customer_role_forbidden(dbc, cleanup):
    """Customer → 403 unchanged.  SR photos slice never crosses
    a 403 boundary."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)

    from routers.workstream_job_detail import get_job_detail
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(get_job_detail(
            jid, {"id": "c", "role": "customer"},
            _make_tenant_dep(tenant_id),
        ))
    assert excinfo.value.status_code == 403


def test_endpoint_tech_unauthorized_forbidden(dbc, cleanup):
    """Unauthorized tech → 403.  Backward compat with the F1
    crew-aware gate."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)

    from routers.workstream_job_detail import get_job_detail
    from fastapi import HTTPException as _HE
    with patch("services.authz.is_tech_authorized_on_job",
                return_value=False):
        with pytest.raises(_HE) as excinfo:
            _run(get_job_detail(
                jid, _tech_user("tech-other"),
                _make_tenant_dep(tenant_id),
            ))
    assert excinfo.value.status_code == 403


def test_endpoint_authorized_tech_receives_sr_photos(dbc, cleanup):
    """Assigned tech → payload includes ``service_report_photos``.
    Access model unchanged; SR photos ride the same 200 path as
    the rest of the payload."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    tid = _fresh_id("TECH")
    jid = _seed_job_sync(dbc, tenant_id, photos=[],
                          technician_id=tid)
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("tech-visible"),
    ])
    seeded_report_ids.append(rid)

    from routers.workstream_job_detail import get_job_detail
    with patch("services.authz.is_tech_authorized_on_job",
                return_value=True):
        payload = _run(get_job_detail(
            jid, _tech_user(tid), _make_tenant_dep(tenant_id),
        ))
    ids = {i["id"] for i in payload["service_report_photos"]}
    assert "tech-visible" in ids
