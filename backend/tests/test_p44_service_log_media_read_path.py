"""Phase P44 · Feb-2026 — Service Log media read-path fix.

Locks the two-rung read cascade in
``backend/routers/workstream_service_log.py::_media_items``:

  Rung 1 — ``service_reports`` (primary).  Match ``(tenant_id,
  job_id)``.  Photos + videos on the report carry a pre-computed
  ``url`` field (Phase-27 upload path) and are passed through
  verbatim.  No S3 signing at read time.

  Rung 2 — ``jobs.photos`` / ``jobs.videos`` (legacy fallback).
  Fires when no matching ``service_reports`` doc exists OR when the
  matching doc has empty ``photos`` AND empty ``videos``.  URLs go
  through the P35 renderer at ``/api/public/job-photo/{jid}/{pid}``.

Also asserts:
  * Tenant scoping is enforced on the primary rung (no cross-tenant
    leak — service_reports match on both ``tenant_id`` + ``job_id``).
  * Stored ``url`` is returned verbatim (no re-signing, no concat).
  * ``generate_signed_url`` fallback fires when stored ``url`` is
    absent AND ``s3_key`` is present.
  * Empty state returns ``[]``, never ``None``.
  * Videos serialize alongside photos in a single mixed list.

Test loop convention (mirrors ``test_heatmap_cooldown_cache.py``):
Seeding uses ``pymongo.MongoClient`` (sync — no loop affinity).
The SUT call runs on a fresh ``asyncio`` loop with a Motor client
freshly bound to that loop and monkey-patched into
``routers.workstream_service_log.db`` for the duration of the test.
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

TAG = "P44_"


# ─── Sync fixture — seeding + cleanup only (no async involved) ───────

@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    """Sync pymongo handle for seeding and cleanup.  Avoids Motor's
    module-cached-loop trap that bit the first draft of this suite."""
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Drops every P44_-tagged row this test wrote."""
    seeded_jids: List[str] = []
    seeded_report_ids: List[str] = []
    yield seeded_jids, seeded_report_ids
    if seeded_jids:
        dbc.jobs.delete_many({"id": {"$in": seeded_jids}})
        dbc.service_reports.delete_many({"job_id": {"$in": seeded_jids}})
    if seeded_report_ids:
        dbc.service_reports.delete_many({"id": {"$in": seeded_report_ids}})


# ─── Per-test async loop + patched Motor db handle ───────────────────

def _loop_and_db():
    """Create a fresh asyncio loop AND a Motor client bound to it,
    then swap ``routers.workstream_service_log.db`` to that Motor
    handle so the SUT reads/writes on the same loop.  Returns
    ``(loop, client, adb)``.

    Restore via ``_restore_db()`` in a ``finally``.
    """
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


def _run_media_items(job: Dict[str, Any], tenant_id: str,
                      _extra_setup=None):
    """Common runner: swap in loop-bound Motor db, invoke
    ``_media_items(job, tenant_id)``, tear down.

    ``_extra_setup`` is an optional callable ``(loop) -> ctx`` that
    runs before the SUT call — currently unused, kept for future
    extension (e.g., seeding via Motor rather than pymongo when a
    test needs the writes on the same loop).
    """
    loop, client, _adb = _loop_and_db()
    try:
        from routers.workstream_service_log import _media_items
        return loop.run_until_complete(_media_items(job, tenant_id))
    finally:
        _restore_db(client, loop)


# ─── Seed builders (sync via pymongo) ────────────────────────────────

def _fresh_id(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job_sync(dbc, tenant_id: str, *,
                    photos: List[dict] = None,
                    videos: List[dict] = None) -> str:
    jid = _fresh_id("JOB")
    doc: Dict[str, Any] = {
        "id": jid,
        "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "title": "P44 seed job",
        "status": "completed",
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
        "id": rid,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "tech_id": _fresh_id("TECH"),
        "public_uuid": uuid.uuid4().hex,
        "photos": photos if photos is not None else [],
        "videos": videos if videos is not None else [],
        "created_at": "2026-02-01T00:00:00Z",
    }
    dbc.service_reports.insert_one(doc)
    return rid


def _sr_photo(url: str, *, pid: str = None,
              extra: dict = None) -> dict:
    p = {
        "id": pid or _fresh_id("PID"),
        "storage_path": f"tenants/x/service_report/xyz/{uuid.uuid4().hex}.jpg",
        "url": url,
        "mime": "image/jpeg",
        "content_type": "image/jpeg",
        "size_bytes": 1024,
        "uploaded_at": "2026-02-01T00:05:00Z",
        "is_deleted": False,
    }
    if extra:
        p.update(extra)
    return p


def _sr_video(url: str, *, vid: str = None,
              duration_seconds: float = 12.5) -> dict:
    return {
        "id": vid or _fresh_id("VID"),
        "storage_path": f"tenants/x/service_report/xyz/{uuid.uuid4().hex}.mp4",
        "url": url,
        "mime": "video/mp4",
        "content_type": "video/mp4",
        "size_bytes": 2048,
        "duration_seconds": duration_seconds,
        "uploaded_at": "2026-02-01T00:06:00Z",
        "is_deleted": False,
    }


def _job_photo(pid: str = None, *, label: str = "photo") -> dict:
    return {
        "id": pid or _fresh_id("JP"),
        "data": "data:image/jpeg;base64,AAAA",
        "label": label,
        "created_at": "2026-02-01T00:07:00Z",
    }


# ═══════════════════════════════════════════════════════════════════
# 1) service_reports IS the primary source when present
# ═══════════════════════════════════════════════════════════════════

def test_service_log_reads_photos_from_service_reports_when_present(
    dbc, cleanup,
):
    """When ``service_reports.photos`` has rows AND ``jobs.photos``
    is empty, the read must come from service_reports and use the
    stored ``url`` field verbatim."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    sr_photos = [
        _sr_photo("/api/public/service/uuid1/photo/pid1", pid="pid1"),
        _sr_photo("/api/public/service/uuid1/photo/pid2", pid="pid2"),
    ]
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=sr_photos)
    seeded_report_ids.append(rid)

    # Pass the persisted job dict (photos:[]) — SUT will find the
    # service_report on rung 1 and use it.
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert isinstance(items, list)
    assert len(items) == 2
    urls = [i["url"] for i in items]
    assert "/api/public/service/uuid1/photo/pid1" in urls
    assert "/api/public/service/uuid1/photo/pid2" in urls
    for i in items:
        assert i["kind"] == "image"
        assert i["id"] in ("pid1", "pid2")
        # No re-minting — passed through as-is.
        assert not i["url"].startswith("/api/public/job-photo/")


# ═══════════════════════════════════════════════════════════════════
# 2) Falls back to jobs.photos when no service_report exists at all
# ═══════════════════════════════════════════════════════════════════

def test_service_log_falls_back_to_job_photos_when_no_service_report(
    dbc, cleanup,
):
    """No matching row in ``service_reports`` → fall through to the
    legacy embedded ``jobs.photos`` array."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, _ = cleanup

    job_photos = [_job_photo(pid="jp-a"), _job_photo(pid="jp-b")]
    jid = _seed_job_sync(dbc, tenant_id, photos=job_photos)
    seeded_jids.append(jid)
    # NO service_reports row exists.

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert len(items) == 2
    ids = {i["id"] for i in items}
    assert ids == {"jp-a", "jp-b"}
    for i in items:
        # Legacy fallback uses the P35 renderer URL shape.
        assert i["url"].startswith("/api/public/job-photo/")
        assert i["url"].endswith(f"/{i['id']}")


# ═══════════════════════════════════════════════════════════════════
# 3) Falls back to jobs.photos when service_report has empty photos
# ═══════════════════════════════════════════════════════════════════

def test_service_log_falls_back_to_job_photos_when_service_report_has_empty_photos(
    dbc, cleanup,
):
    """Report row exists but ``photos`` (AND ``videos``) is empty —
    still fall through to jobs.photos so template-bootstrapped
    reports don't blank the media rail."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    job_photos = [_job_photo(pid="jp-fallback")]
    jid = _seed_job_sync(dbc, tenant_id, photos=job_photos)
    seeded_jids.append(jid)
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[], videos=[])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert len(items) == 1
    assert items[0]["id"] == "jp-fallback"
    assert items[0]["url"].startswith("/api/public/job-photo/")


# ═══════════════════════════════════════════════════════════════════
# 4) Stored ``url`` is passed through byte-identical
# ═══════════════════════════════════════════════════════════════════

def test_service_log_uses_stored_url_field_verbatim(dbc, cleanup):
    """When the photo carries an externally-hosted URL string,
    the helper must return the exact string — no re-signing, no
    prefix rewrite."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup
    exact = "https://cdn.example.com/tenant-x/report/abc/photo.jpg"

    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(
        dbc, tenant_id, jid,
        photos=[_sr_photo(exact, pid="urlverbatim")],
    )
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)
    assert len(items) == 1
    assert items[0]["url"] == exact


# ═══════════════════════════════════════════════════════════════════
# 5) Falls back to generate_signed_url when ``url`` is absent
# ═══════════════════════════════════════════════════════════════════

def test_service_log_falls_back_to_generate_signed_url_when_url_missing(
    dbc, cleanup,
):
    """Legacy / partially-migrated rows may have an ``s3_key`` but
    no stored ``url``.  The helper must call
    ``services.aws_s3.photos.generate_signed_url(s3_key)`` for those
    rows — not concatenate an S3 URL manually."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup
    signed_url = "https://s3.us-east-2.amazonaws.com/bucket/key?X-Amz-Sig=abc"

    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    # Photo lacks ``url`` entirely but has ``s3_key``.
    legacy_photo = {
        "id": "legacy-1",
        "s3_key": "tenants/x/service_report/legacy.jpg",
        "s3_mime": "image/jpeg",
        "created_at": "2026-02-01T00:00:00Z",
        "is_deleted": False,
    }
    rid = _seed_report_sync(dbc, tenant_id, jid, photos=[legacy_photo])
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    with patch("services.aws_s3.photos.generate_signed_url",
                return_value=signed_url) as _mock:
        items = _run_media_items(job, tenant_id)
        calls = list(_mock.call_args_list)

    assert len(items) == 1
    assert items[0]["url"] == signed_url
    assert len(calls) == 1
    args, kwargs = calls[0]
    called_with = (args[0] if args else kwargs.get("s3_key")
                    or kwargs.get("key"))
    assert called_with == "tenants/x/service_report/legacy.jpg"


# ═══════════════════════════════════════════════════════════════════
# 6) Tenant scoping — service_reports rung filters by tenant_id
# ═══════════════════════════════════════════════════════════════════

def test_service_log_tenant_scoping(dbc, cleanup):
    """Tenant B owns a service_report + job with photos.  When
    ``_media_items`` is called with tenant A's tenant_id, the
    service_reports rung MUST return no matches (rung 1 is scrubbed
    by ``tenant_id`` in the ``find_one`` filter).

    Cross-tenant leakage on the legacy rung is structurally
    impossible in production because the outer
    ``db.jobs.find_one`` in ``get_service_log`` already scopes by
    tenant_id — a foreign-tenant ``job`` dict can never reach this
    helper via the live endpoint.
    """
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    seeded_jids, seeded_report_ids = cleanup

    # Tenant B owns the data.
    jid_b = _seed_job_sync(dbc, tenant_b, photos=[])
    seeded_jids.append(jid_b)
    rid_b = _seed_report_sync(
        dbc, tenant_b, jid_b,
        photos=[_sr_photo("/api/public/service/tb-uuid/photo/tb-sr",
                            pid="tb-sr")],
    )
    seeded_report_ids.append(rid_b)

    # Pretend tenant A somehow got tenant B's job dict passed in
    # (defense-in-depth check).  The SR-rung MUST reject it via the
    # ``tenant_id`` filter, so ``tb-sr`` never leaks.
    stale_job_view = {"id": jid_b, "tenant_id": tenant_b, "photos": []}
    items = _run_media_items(stale_job_view, tenant_a)

    ids = {i["id"] for i in items}
    assert "tb-sr" not in ids, "service_reports rung leaked cross-tenant"
    # And nothing from rung 2 either — the job dict passed in had
    # empty photos, so the fallback rung is a no-op too.
    assert items == []


# ═══════════════════════════════════════════════════════════════════
# 7) Empty result returns [] never None
# ═══════════════════════════════════════════════════════════════════

def test_service_log_empty_result_returns_empty_list_not_none(
    dbc, cleanup,
):
    """No photos anywhere — must return ``[]``, never ``None`` or
    a raise."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, _ = cleanup

    jid = _seed_job_sync(dbc, tenant_id)  # no photos, no videos
    seeded_jids.append(jid)
    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    assert items == []
    assert items is not None
    assert isinstance(items, list)


# ═══════════════════════════════════════════════════════════════════
# 8) Videos serialize alongside photos
# ═══════════════════════════════════════════════════════════════════

def test_service_log_serializes_videos_alongside_photos(dbc, cleanup):
    """Mixed media on service_reports must all come through in the
    returned list with the correct ``kind`` on each item."""
    tenant_id = _fresh_id("TENANT")
    seeded_jids, seeded_report_ids = cleanup

    jid = _seed_job_sync(dbc, tenant_id, photos=[])
    seeded_jids.append(jid)
    rid = _seed_report_sync(
        dbc, tenant_id, jid,
        photos=[_sr_photo("/api/public/service/uuid-mixed/photo/mixed-p",
                            pid="mixed-p")],
        videos=[_sr_video("/api/public/service/uuid-mixed/video/mixed-v",
                            vid="mixed-v", duration_seconds=8.0)],
    )
    seeded_report_ids.append(rid)

    job = dbc.jobs.find_one({"id": jid, "tenant_id": tenant_id},
                              {"_id": 0})
    items = _run_media_items(job, tenant_id)

    kinds = {i["kind"] for i in items}
    assert kinds == {"image", "video"}
    assert len(items) == 2
    video = next(i for i in items if i["kind"] == "video")
    assert video["url"] == "/api/public/service/uuid-mixed/video/mixed-v"
    assert video["duration_ms"] == 8000
    photo = next(i for i in items if i["kind"] == "image")
    assert photo["url"] == "/api/public/service/uuid-mixed/photo/mixed-p"
