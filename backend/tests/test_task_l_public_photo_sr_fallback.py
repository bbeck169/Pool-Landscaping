"""Task L+P · Commit 3 — public /job-photo SR fallback + slim widen.

Locks the endpoint fallback behavior for
``backend/routers/jobs.py`` (``/api/public/job-photo/{jid}/{pid}``
+ ``/thumb`` + ``/preview``) AND the widened slim shape in
``backend/services/jobs_slim_photos.py``:

  * All 3 public photo routes fall back to
    ``service_reports.photos`` when ``jobs.photos`` doesn't
    contain the pid.
  * SR-photo serving cascade: derivative key redirect →
    storage_path bytes → s3_key redirect → inline base64 → 404.
  * SR fallback is tenant-scoped by the job doc's ``tenant_id``
    (magic-token auth model preserved).
  * ``slim_photos_on_rows`` unions ``_sr_photo_ids`` scratch key
    into ``photo_ids[]`` / ``photo_thumb_urls[]`` and drops the
    scratch key before returning.
  * ``enrich_docs_with_sr_photo_ids`` issues exactly ONE
    ``db.service_reports.find`` per page of docs (batched via
    ``$in`` on ``job_id``), filters tombstones on both the SR-doc
    (``deleted_at``) and per-photo (``is_deleted``) layers.
"""
from __future__ import annotations

import asyncio
import base64
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "TASKLC3_"

# Tiny 1x1 red PNG as base64 — used for legacy inline SR photos.
_PNG_1x1 = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001"
        "0806000000001f15c4890000000d49444154789c6300ff00"
        "01010001cb00e2fa000000004945" "4e44ae426082"
    )
).decode()


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
    from routers import jobs as _jobs_mod
    _jobs_mod._orig_db_for_test = getattr(_jobs_mod, "_orig_db_for_test",
                                            _jobs_mod.db)
    _jobs_mod.db = adb
    return loop, client, adb


def _restore_db(client=None, loop=None):
    from routers import jobs as _jobs_mod
    if hasattr(_jobs_mod, "_orig_db_for_test"):
        _jobs_mod.db = _jobs_mod._orig_db_for_test
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


def _seed_job_sync(dbc, tenant_id: str, *, photos: List[dict] = None) -> str:
    jid = _fresh_id("JOB")
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "status": "completed",
        "photos": photos if photos is not None else [],
    }
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


def _inline_job_photo(pid: str) -> dict:
    """Legacy inline-data job photo — served via the base64 branch."""
    return {
        "id": pid,
        "data": f"data:image/png;base64,{_PNG_1x1}",
        "label": "jobs.photos legacy inline",
        "created_at": "2026-02-01T00:00:00Z",
    }


def _inline_sr_photo(pid: str, *, is_deleted: bool = False,
                      storage_path: str = None) -> dict:
    """SR photo with inline ``data:`` fallback for base64 branch
    (only fires when object_storage is unavailable)."""
    p: Dict[str, Any] = {
        "id": pid,
        "url": f"/api/public/service/some-uuid/photo/{pid}",
        "data": f"data:image/png;base64,{_PNG_1x1}",
        "mime": "image/png",
        "content_type": "image/png",
        "size_bytes": 128,
        "uploaded_at": "2026-02-01T00:05:00Z",
        "is_deleted": is_deleted,
    }
    if storage_path:
        p["storage_path"] = storage_path
    return p


# ═══════════════════════════════════════════════════════════════════
# 1) BASE route (/api/public/job-photo/{jid}/{pid})
# ═══════════════════════════════════════════════════════════════════

def test_base_route_serves_from_jobs_photos_when_present(dbc, cleanup):
    """Regression — photo in jobs.photos still serves as before."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[_inline_job_photo("jp-1")])
    seeded_jids.append(jid)
    from routers.jobs import public_job_photo
    resp = _run(public_job_photo(jid, "jp-1"))
    assert resp.media_type in ("image/png", "image/jpeg")
    assert resp.status_code == 200


def test_base_route_falls_back_to_sr_photo(dbc, cleanup):
    """New — photo present ONLY in service_reports.photos serves via
    the SR fallback cascade (inline data branch under test)."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid,
                              photos=[_inline_sr_photo("sr-only-1")])
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo
    resp = _run(public_job_photo(jid, "sr-only-1"))
    assert resp.status_code == 200
    assert resp.media_type in ("image/png", "image/jpeg")


def test_base_route_404_when_neither_source_has_photo(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    from routers.jobs import public_job_photo
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(public_job_photo(jid, "does-not-exist"))
    assert excinfo.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 2) THUMB route (/api/public/job-photo/{jid}/{pid}/thumb)
# ═══════════════════════════════════════════════════════════════════

def test_thumb_route_serves_from_jobs_photos_when_present(dbc, cleanup):
    """Regression — thumb route on legacy jobs.photos row still
    serves (falls back to original when no s3_thumb_key)."""
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[_inline_job_photo("jp-t")])
    seeded_jids.append(jid)
    from routers.jobs import public_job_photo_thumb
    resp = _run(public_job_photo_thumb(jid, "jp-t"))
    assert resp.status_code == 200


def test_thumb_route_falls_back_to_sr_photo_inline(dbc, cleanup):
    """SR photo with no s3_thumb_key falls through to full-size
    inline base64 branch — <img src> still renders."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid,
                              photos=[_inline_sr_photo("sr-thumb-1")])
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo_thumb
    resp = _run(public_job_photo_thumb(jid, "sr-thumb-1"))
    assert resp.status_code == 200


def test_thumb_route_sr_photo_with_s3_thumb_key_redirects(dbc, cleanup):
    """When the SR photo carries ``s3_thumb_key``, the thumb route
    redirects (302) to the presigned URL — not the full-size."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    sr_p = _inline_sr_photo("sr-thumb-s3")
    sr_p["s3_thumb_key"] = "tenants/x/service_report/thumb.jpg"
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[sr_p])
    seeded_report_ids.append(rid)

    signed = "https://s3.us-east-2.amazonaws.com/bucket/thumb?sig=xyz"
    with patch("services.aws_s3.photos.generate_signed_url",
                return_value=signed):
        from routers.jobs import public_job_photo_thumb
        resp = _run(public_job_photo_thumb(jid, "sr-thumb-s3"))
    assert resp.status_code == 302
    assert resp.headers["location"] == signed


def test_thumb_route_404_when_neither_source_has_photo(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, _ = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    from routers.jobs import public_job_photo_thumb
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(public_job_photo_thumb(jid, "no-such-pid"))
    assert excinfo.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 3) PREVIEW route (/api/public/job-photo/{jid}/{pid}/preview)
# ═══════════════════════════════════════════════════════════════════

def test_preview_route_falls_back_to_sr_photo(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid,
                              photos=[_inline_sr_photo("sr-preview-1")])
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo_preview
    resp = _run(public_job_photo_preview(jid, "sr-preview-1"))
    assert resp.status_code == 200


def test_preview_route_sr_photo_with_s3_preview_key_redirects(dbc, cleanup):
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    sr_p = _inline_sr_photo("sr-preview-s3")
    sr_p["s3_preview_key"] = "tenants/x/service_report/preview.jpg"
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[sr_p])
    seeded_report_ids.append(rid)

    signed = "https://s3.us-east-2.amazonaws.com/bucket/preview?sig=xyz"
    with patch("services.aws_s3.photos.generate_signed_url",
                return_value=signed):
        from routers.jobs import public_job_photo_preview
        resp = _run(public_job_photo_preview(jid, "sr-preview-s3"))
    assert resp.status_code == 302
    assert resp.headers["location"] == signed


# ═══════════════════════════════════════════════════════════════════
# 4) SR fallback tenant safety
# ═══════════════════════════════════════════════════════════════════

def test_sr_fallback_isolated_by_tenant(dbc, cleanup):
    """Tenant B owns a job+SR pair with a photo.  Tenant A creates a
    separate job with the SAME jid string — but its own tenant_id.
    The base route lookup uses ``jid`` alone (no tenant on the job
    find), but the SR fallback filters by the resolved
    ``tenant_id`` from the found job doc. Two independent tenants
    can't collide on jid+pid because ``jobs.id`` is globally
    unique in this deployment.  This test asserts the SR filter
    honours the job's tenant_id: an SR photo written under a
    different tenant_id (but same jid) is NOT served.
    """
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    seeded_jids, seeded_report_ids = cleanup

    # Tenant A owns the job (jobs.photos empty).
    jid = _seed_job_sync(dbc, tenant_a, photos=[])
    seeded_jids.append(jid)
    # Foreign-tenant SR row with matching jid but wrong tenant_id —
    # tenant B mis-wrote (defense-in-depth check on the SR filter).
    rid = _seed_report_sync(dbc, tenant_b, jid,
                              photos=[_inline_sr_photo("cross-tenant-pid")])
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(public_job_photo(jid, "cross-tenant-pid"))
    assert excinfo.value.status_code == 404


def test_sr_fallback_filters_soft_deleted_sr_doc(dbc, cleanup):
    """SR doc with ``deleted_at`` set is skipped by the fallback."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(
        dbc, tenant_id, jid,
        photos=[_inline_sr_photo("in-deleted-sr")],
        deleted_at="2026-02-01T12:00:00Z",
    )
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(public_job_photo(jid, "in-deleted-sr"))
    assert excinfo.value.status_code == 404


def test_sr_fallback_filters_per_photo_is_deleted(dbc, cleanup):
    """Photo with ``is_deleted=True`` inside the SR is skipped even
    when the SR doc itself is live."""
    tenant_id = _fresh_id("T")
    seeded_jids, seeded_report_ids = cleanup
    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(
        dbc, tenant_id, jid,
        photos=[_inline_sr_photo("dead-photo", is_deleted=True)],
    )
    seeded_report_ids.append(rid)

    from routers.jobs import public_job_photo
    from fastapi import HTTPException as _HE
    with pytest.raises(_HE) as excinfo:
        _run(public_job_photo(jid, "dead-photo"))
    assert excinfo.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# 5) slim_photos_on_rows widening
# ═══════════════════════════════════════════════════════════════════

def test_slim_photos_merges_sr_photo_ids():
    """Row with 2 jobs.photos + 1 SR photo (pre-stamped via
    ``_sr_photo_ids``) → photo_count=3, photo_ids has all 3, no
    duplicates, thumb URLs point to the extended endpoint."""
    from services.jobs_slim_photos import slim_photos_on_rows
    row = {
        "id": "job-a",
        "photos": [
            {"id": "jp-1", "data": "X"},
            {"id": "jp-2", "data": "Y"},
        ],
        "_sr_photo_ids": ["sr-1"],
    }
    out = slim_photos_on_rows([row], include_photos=False)
    r = out[0]
    assert r["photo_count"] == 3
    # SR ids come first (SR wins on any id-collision; here no
    # collision, so the merge preserves SR-first, legacy-second).
    assert r["photo_ids"] == ["sr-1", "jp-1", "jp-2"]
    assert r["photo_thumb_urls"] == [
        "/api/public/job-photo/job-a/sr-1/thumb",
        "/api/public/job-photo/job-a/jp-1/thumb",
        "/api/public/job-photo/job-a/jp-2/thumb",
    ]
    # Scratch key is dropped so it never leaks over the wire.
    assert "_sr_photo_ids" not in r


def test_slim_photos_dedupes_when_sr_and_jobs_share_id():
    """Same id in both sources → single entry, SR-source preserved
    (dedup is by id string, and SR is prepended first)."""
    from services.jobs_slim_photos import slim_photos_on_rows
    row = {
        "id": "job-b",
        "photos": [{"id": "shared-id", "data": "X"}],
        "_sr_photo_ids": ["shared-id"],
    }
    out = slim_photos_on_rows([row], include_photos=False)
    r = out[0]
    assert r["photo_count"] == 1
    assert r["photo_ids"] == ["shared-id"]


def test_slim_photos_no_scratch_key_backward_compatible():
    """Row without ``_sr_photo_ids`` behaves exactly as pre-Task-L+P
    — photo_count/photo_ids/photo_thumb_urls from photos[] only."""
    from services.jobs_slim_photos import slim_photos_on_rows
    row = {
        "id": "job-c",
        "photos": [{"id": "jp-a", "data": "X"}, {"id": "jp-b", "data": "Y"}],
    }
    out = slim_photos_on_rows([row], include_photos=False)
    r = out[0]
    assert r["photo_count"] == 2
    assert r["photo_ids"] == ["jp-a", "jp-b"]
    assert r["photo_thumb_urls"] == [
        "/api/public/job-photo/job-c/jp-a/thumb",
        "/api/public/job-photo/job-c/jp-b/thumb",
    ]


def test_slim_photos_only_sr_no_jobs_photos():
    """Row with 5 SR photos + 0 jobs.photos → all 5 in photo_ids,
    photo_count=5, every thumb URL points to the extended endpoint.
    """
    from services.jobs_slim_photos import slim_photos_on_rows
    row = {
        "id": "job-d",
        "photos": [],
        "_sr_photo_ids": [f"sr-{i}" for i in range(5)],
    }
    out = slim_photos_on_rows([row], include_photos=False)
    r = out[0]
    assert r["photo_count"] == 5
    assert r["photo_ids"] == [f"sr-{i}" for i in range(5)]
    assert all(u.startswith("/api/public/job-photo/job-d/sr-")
                  and u.endswith("/thumb") for u in r["photo_thumb_urls"])


# ═══════════════════════════════════════════════════════════════════
# 6) enrich_docs_with_sr_photo_ids — batched fetch call count
# ═══════════════════════════════════════════════════════════════════

class _AsyncCursor:
    """Minimal async iterator wrapper over a sync list — mimics
    Motor cursor's ``async for`` protocol."""
    def __init__(self, items: List[Dict[str, Any]]):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def test_enrich_issues_exactly_one_find_call():
    """N-job page → exactly ONE db.service_reports.find call."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photo_ids

    docs = [{"id": f"j-{i}"} for i in range(50)]
    tenant_id = "t-1"

    mock_srs = [
        {"job_id": "j-3", "photos": [{"id": "sr-p1"}]},
        {"job_id": "j-7", "photos": [{"id": "sr-p2"}, {"id": "sr-p3"}]},
    ]
    find_calls = []
    def _fake_find(query, projection):
        find_calls.append((query, projection))
        return _AsyncCursor(mock_srs)

    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photo_ids(mock_db, docs, tenant_id)
    asyncio.get_event_loop().run_until_complete(_go()) \
        if False else asyncio.new_event_loop().run_until_complete(_go())

    # ONE call — no per-row fan-out.
    assert len(find_calls) == 1
    q, proj = find_calls[0]
    assert q["tenant_id"] == tenant_id
    assert set(q["job_id"]["$in"]) == {f"j-{i}" for i in range(50)}
    # Tombstone filter present on the SR doc.
    assert q["deleted_at"] == {"$in": [None, ""]}
    # Projection is tight.
    assert proj == {
        "_id": 0, "job_id": 1,
        "photos.id": 1, "photos.is_deleted": 1,
    }
    # Scratch key present on every row.
    for d in docs:
        assert "_sr_photo_ids" in d
    # Rows that matched pick up their SR ids; others empty.
    assert next(d for d in docs if d["id"] == "j-3")["_sr_photo_ids"] == ["sr-p1"]
    assert next(d for d in docs if d["id"] == "j-7")["_sr_photo_ids"] == ["sr-p2", "sr-p3"]
    assert next(d for d in docs if d["id"] == "j-0")["_sr_photo_ids"] == []


def test_enrich_skips_when_no_job_ids():
    """Empty ``docs`` → zero SR find calls (no wasted round-trip)."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photo_ids
    find_calls = []
    def _fake_find(query, projection):
        find_calls.append((query, projection))
        return _AsyncCursor([])
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photo_ids(mock_db, [], "t-1")
    asyncio.new_event_loop().run_until_complete(_go())
    assert find_calls == []


def test_enrich_filters_per_photo_is_deleted():
    """SR photo with ``is_deleted=True`` inside a live SR is
    dropped from ``_sr_photo_ids``."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photo_ids
    docs = [{"id": "j-1"}]
    mock_srs = [
        {"job_id": "j-1", "photos": [
            {"id": "live", "is_deleted": False},
            {"id": "dead", "is_deleted": True},
        ]},
    ]
    def _fake_find(query, projection):
        return _AsyncCursor(mock_srs)
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photo_ids(mock_db, docs, "t-1")
    asyncio.new_event_loop().run_until_complete(_go())
    assert docs[0]["_sr_photo_ids"] == ["live"]


def test_enrich_end_to_end_with_slim_photos_on_rows():
    """The batched enrich + slim helper wired together produce the
    same final shape a live caller would see: photo_ids merged,
    scratch key stripped, thumb URLs computed."""
    from services.jobs_slim_photos import (
        enrich_docs_with_sr_photo_ids, slim_photos_on_rows,
    )
    docs = [{
        "id": "j-live",
        "photos": [{"id": "jp-a", "data": "X"}],
    }]
    mock_srs = [
        {"job_id": "j-live", "photos": [{"id": "sr-a", "is_deleted": False}]},
    ]
    def _fake_find(query, projection):
        return _AsyncCursor(mock_srs)
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photo_ids(mock_db, docs, "t-1")
        slim_photos_on_rows(docs, include_photos=False)
    asyncio.new_event_loop().run_until_complete(_go())

    r = docs[0]
    assert r["photo_count"] == 2
    assert r["photo_ids"] == ["sr-a", "jp-a"]
    assert r["photo_thumb_urls"] == [
        "/api/public/job-photo/j-live/sr-a/thumb",
        "/api/public/job-photo/j-live/jp-a/thumb",
    ]
    assert "_sr_photo_ids" not in r
    # ``photos`` was dropped by the slim step (include_photos=False).
    assert "photos" not in r
