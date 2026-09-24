"""Task L+P · Feb-2026 — Workstream media merge coverage.

Locks the MERGE behavior of
``backend/routers/workstream_service_log.py::_media_items``:

  * Both ``service_reports.photos`` / ``.videos`` AND
    ``jobs.photos`` / ``.videos`` are combined — a photo present
    in EITHER source appears in the result.
  * Dedupe by ``id``: on collision the service_report entry wins
    (freshest metadata + pre-computed url).
  * Sort by ``created_at`` DESC across both sources.  Entries
    lacking a reliable timestamp fall back to insertion order
    (SR first, then legacy).
  * ``source`` field emitted per item (``"service_report"`` |
    ``"job"``) — additive, does not disturb pre-existing shape.
  * Tenant scoping preserved on both rungs (SR match uses
    ``tenant_id`` + ``job_id``; legacy rung reads the caller-
    supplied job dict already loaded under a tenant filter by
    ``get_service_log``).
  * Deleted photos filtered on both sides.

Test loop convention mirrors ``test_p44_service_log_media_read_path.py``:
sync ``pymongo.MongoClient`` for seeding + cleanup, Motor client
on a fresh asyncio loop swapped into ``routers.workstream_service_log.db``
only for the duration of the SUT call.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "TASKL_"


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


# ─── Per-test loop + Motor db swap ─────────────────────────────────
def _loop_and_db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    from routers import workstream_service_log as _wsl
    _wsl._orig_db_for_test = getattr(_wsl, "_orig_db_for_test", _wsl.db)
    _wsl.db = adb
    return loop, client, adb


def _restore_db(client=None, loop=None):
    from routers import workstream_service_log as _wsl
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


def _run_media_items(job: Dict[str, Any], tenant_id: str):
    loop, client, _adb = _loop_and_db()
    try:
        from routers.workstream_service_log import _media_items
        return loop.run_until_complete(_media_items(job, tenant_id))
    finally:
        _restore_db(client, loop)


# ─── Seed helpers ──────────────────────────────────────────────────
def _fresh_id(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job_sync(dbc, tenant_id: str, *,
                    photos: List[dict] = None,
                    videos: List[dict] = None) -> str:
    jid = _fresh_id("JOB")
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "title": "Task L+P seed job", "status": "completed",
        "created_at": "2026-02-01T00:00:00Z",
    }
    if photos is not None:
        doc["photos"] = photos
    if videos is not None:
        doc["videos"] = videos
    dbc.jobs.insert_one(doc)
    return jid


def _seed_report_sync(dbc, tenant_id: str, job_id: str, *,
                       photos: List[dict] = None,
                       videos: List[dict] = None) -> str:
    rid = _fresh_id("SR")
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id, "job_id": job_id,
        "tech_id": _fresh_id("TECH"),
        "public_uuid": uuid.uuid4().hex,
        "photos": photos if photos is not None else [],
        "videos": videos if videos is not None else [],
        "created_at": "2026-02-01T00:00:00Z",
    }
    dbc.service_reports.insert_one(doc)
    return rid


def _sr_photo(url: str, *, pid: str = None,
              created_at: str = "2026-02-01T00:05:00Z",
              is_deleted: bool = False) -> dict:
    return {
        "id": pid or _fresh_id("PID"),
        "storage_path": f"tenants/x/service_report/{uuid.uuid4().hex}.jpg",
        "url": url, "mime": "image/jpeg", "content_type": "image/jpeg",
        "size_bytes": 1024, "uploaded_at": created_at,
        "created_at": created_at, "is_deleted": is_deleted,
    }


def _job_photo(*, pid: str = None, label: str = "photo",
                created_at: str = "2026-02-01T00:07:00Z") -> dict:
    return {
        "id": pid or _fresh_id("JP"),
        "data": "data:image/jpeg;base64,AAAA",
        "label": label, "created_at": created_at,
    }


# ═══════════════════════════════════════════════════════════════════
# 1) Merge — both sources have unique photos → all appear
# ═══════════════════════════════════════════════════════════════════
def test_merge_returns_photos_from_both_sources(dbc, cleanup):
    """When SR has 2 unique photos AND jobs.photos has 2 unique
    photos, the merged list contains all 4."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    job_photos = [
        _job_photo(pid="jp-a", created_at="2026-02-01T00:07:00Z"),
        _job_photo(pid="jp-b", created_at="2026-02-01T00:08:00Z"),
    ]
    jid = _seed_job_sync(dbc, tenant_id, photos=job_photos)
    seeded_jids.append(jid)
    rid = _seed_report_sync(
        dbc, tenant_id, jid,
        photos=[
            _sr_photo("/api/public/service/uuid/photo/sr-a",
                       pid="sr-a", created_at="2026-02-01T00:09:00Z"),
            _sr_photo("/api/public/service/uuid/photo/sr-b",
                       pid="sr-b", created_at="2026-02-01T00:10:00Z"),
        ],
    )
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    ids = {i["id"] for i in items}
    assert ids == {"sr-a", "sr-b", "jp-a", "jp-b"}
    # Every SR item is tagged source=service_report; every job item
    # is tagged source=job.
    by_id = {i["id"]: i for i in items}
    assert by_id["sr-a"]["source"] == "service_report"
    assert by_id["sr-b"]["source"] == "service_report"
    assert by_id["jp-a"]["source"] == "job"
    assert by_id["jp-b"]["source"] == "job"


# ═══════════════════════════════════════════════════════════════════
# 2) Merge — id collision across sources → SR wins, no duplicate
# ═══════════════════════════════════════════════════════════════════
def test_merge_dedupes_by_id_service_report_wins(dbc, cleanup):
    """Same photo id in both sources → single entry in the result,
    taken from the SR side (freshest metadata, pre-computed url)."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    shared_id = "shared-photo-1"
    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid=shared_id, label="legacy-blob"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/uuid/photo/shared-photo-1",
                    pid=shared_id),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert len(items) == 1
    winner = items[0]
    assert winner["id"] == shared_id
    assert winner["source"] == "service_report"
    # SR url wins, NOT the legacy /api/public/job-photo/ shape.
    assert winner["url"] == "/api/public/service/uuid/photo/shared-photo-1"
    assert not winner["url"].startswith("/api/public/job-photo/")


# ═══════════════════════════════════════════════════════════════════
# 3) Only job.photos (no SR row) → returns job photos with source="job"
# ═══════════════════════════════════════════════════════════════════
def test_merge_only_jobs_photos(dbc, cleanup):
    """SR row does not exist for this job → merged result is just
    the jobs.photos side, source-tagged."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, _ = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid="only-jp-a"),
        _job_photo(pid="only-jp-b"),
    ])
    seeded_jids.append(jid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert len(items) == 2
    for i in items:
        assert i["source"] == "job"
        assert i["url"].startswith("/api/public/job-photo/")


# ═══════════════════════════════════════════════════════════════════
# 4) Only SR photos (empty job.photos) → returns SR side, source=SR
# ═══════════════════════════════════════════════════════════════════
def test_merge_only_service_report_photos(dbc, cleanup):
    """jobs.photos is empty; SR has 2 photos → merged result is
    exactly the SR side."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/u/photo/only-sr-a", pid="only-sr-a"),
        _sr_photo("/api/public/service/u/photo/only-sr-b", pid="only-sr-b"),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    ids = {i["id"] for i in items}
    assert ids == {"only-sr-a", "only-sr-b"}
    for i in items:
        assert i["source"] == "service_report"


# ═══════════════════════════════════════════════════════════════════
# 5) Cross-tenant safety — merge does NOT leak SR from other tenant
# ═══════════════════════════════════════════════════════════════════
def test_merge_cross_tenant_isolation(dbc, cleanup):
    """Tenant B owns a job + SR pair with photos.  Merge called with
    tenant A's id (and a stale foreign job dict) must not include
    tenant B's SR photos on the SR rung."""
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    seeded_jids, seeded_report_ids = cleanup

    jid_b = _seed_job_sync(dbc, tenant_b, photos=[])
    seeded_jids.append(jid_b)
    rid_b = _seed_report_sync(dbc, tenant_b, jid_b, photos=[
        _sr_photo("/api/public/service/tb/photo/tb-secret",
                    pid="tb-secret"),
    ])
    seeded_report_ids.append(rid_b)

    # Tenant A caller with a stale foreign-tenant job dict view.
    stale_job = {"id": jid_b, "tenant_id": tenant_b, "photos": []}
    items = _run_media_items(stale_job, tenant_a)

    ids = {i["id"] for i in items}
    assert "tb-secret" not in ids, "SR merge leaked cross-tenant"
    assert items == []


# ═══════════════════════════════════════════════════════════════════
# 6) Deleted photos filtered on the SR side
# ═══════════════════════════════════════════════════════════════════
def test_merge_filters_deleted_service_report_photos(dbc, cleanup):
    """SR photos flagged ``is_deleted=True`` are dropped from the
    merged result; live SR photos + job photos still come through."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid="live-jp"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/u/photo/live-sr", pid="live-sr"),
        _sr_photo("/api/public/service/u/photo/dead-sr", pid="dead-sr",
                    is_deleted=True),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    ids = {i["id"] for i in items}
    assert ids == {"live-sr", "live-jp"}
    assert "dead-sr" not in ids


# ═══════════════════════════════════════════════════════════════════
# 7) Ordering — created_at DESC across both sources
# ═══════════════════════════════════════════════════════════════════
def test_merge_orders_by_created_at_desc_across_sources(dbc, cleanup):
    """When every entry has a ``created_at``, the merged list is
    ordered NEWEST first across both sources — unified timeline."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    # Interleave timestamps deliberately: newest is a JOB photo,
    # middle is an SR photo, oldest is a JOB photo.
    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid="jp-newest",   created_at="2026-02-01T10:00:00Z"),
        _job_photo(pid="jp-oldest",   created_at="2026-02-01T05:00:00Z"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/u/photo/sr-mid",
                    pid="sr-mid",   created_at="2026-02-01T08:00:00Z"),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    ids_in_order = [i["id"] for i in items]
    assert ids_in_order == ["jp-newest", "sr-mid", "jp-oldest"], \
        f"expected newest-first order across sources, got {ids_in_order}"


# ═══════════════════════════════════════════════════════════════════
# 8) Insertion-order fallback for entries without created_at
# ═══════════════════════════════════════════════════════════════════
def test_merge_insertion_order_fallback_for_untimestamped(dbc, cleanup):
    """Entries lacking a ``created_at`` timestamp keep their
    natural insertion order (SR items first, then legacy job
    items) after the timestamped items.  Legacy rows without
    timestamps must not silently reorder relative to each other.
    """
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    # Two legacy job photos WITHOUT created_at.
    jp_a = {"id": "jp-legacy-a", "data": "data:image/jpeg;base64,AAAA",
             "label": "A"}
    jp_b = {"id": "jp-legacy-b", "data": "data:image/jpeg;base64,AAAA",
             "label": "B"}
    jid = _seed_job_sync(dbc, tenant_id, photos=[jp_a, jp_b])
    seeded_jids.append(jid)

    # One SR photo also WITHOUT a stored created_at (legacy row).
    sr_untimestamped = {
        "id": "sr-legacy-1",
        "url": "/api/public/service/u/photo/sr-legacy-1",
        "storage_path": "x", "mime": "image/jpeg",
        "is_deleted": False,
    }
    rid = _seed_report_sync(dbc, tenant_id, jid,
                              photos=[sr_untimestamped])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    # All 3 present; none have created_at, so they preserve
    # insertion order — SR first (rung 1), then jobs in list order.
    ids_in_order = [i["id"] for i in items]
    assert ids_in_order == ["sr-legacy-1", "jp-legacy-a", "jp-legacy-b"]


# ═══════════════════════════════════════════════════════════════════
# 9) Timestamped entries sort FIRST; untimestamped fall to the tail
# ═══════════════════════════════════════════════════════════════════
def test_merge_timestamped_first_then_untimestamped(dbc, cleanup):
    """Given a mix of timestamped + untimestamped items, the
    timestamped ones sort DESC and appear before the
    untimestamped tail (which itself keeps insertion order).
    """
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid="jp-ts",  created_at="2026-02-01T09:00:00Z"),
        # Legacy — no created_at:
        {"id": "jp-nots", "data": "data:image/jpeg;base64,AAAA",
         "label": "legacy"},
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/u/photo/sr-ts",
                    pid="sr-ts", created_at="2026-02-01T11:00:00Z"),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    ids_in_order = [i["id"] for i in items]
    # Timestamped desc first: sr-ts (11:00), jp-ts (09:00);
    # then untimestamped tail: jp-nots.
    assert ids_in_order == ["sr-ts", "jp-ts", "jp-nots"]


# ═══════════════════════════════════════════════════════════════════
# 10) Return shape backward compatibility
# ═══════════════════════════════════════════════════════════════════
def test_merge_preserves_return_shape(dbc, cleanup):
    """Every returned item still exposes the pre-Task-L+P core
    fields: ``id``, ``kind``, ``url``.  The new ``source`` field
    is additive — presence-tested but never replaces anything.
    """
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[
        _job_photo(pid="shape-jp"),
    ])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[
        _sr_photo("/api/public/service/u/photo/shape-sr",
                    pid="shape-sr"),
    ])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert len(items) == 2
    for i in items:
        assert set(["id", "kind", "url", "source"]).issubset(i.keys())
        assert i["kind"] == "image"
        assert i["source"] in ("service_report", "job")
