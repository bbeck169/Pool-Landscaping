"""Feb-2026 · Photos-in-S3 base64-skip contract tests.

Locks the three-way branch on the photo upload write path:

  1. Flag OFF → ``photos[].data`` is retained (unchanged, backward-compat).
  2. Flag ON + all three S3 puts succeed → ``photos[].data`` is DROPPED
     from the persisted doc; ``s3_key`` / ``s3_thumb_key`` /
     ``s3_preview_key`` are stamped instead.
  3. Flag ON + any S3 put fails → ``photos[].data`` is retained as a
     durability fallback, any ``s3_*`` keys that DID succeed are kept
     for observability, and an ``audit_logs`` row with
     ``event="photos.s3_upload_partial_failure"`` is emitted with the
     ``s3_puts_succeeded`` / ``s3_puts_failed`` payload.

Read path is intentionally untested here — Phase-1 already locks the
read-path fallback (``s3_preview_key`` → ``s3_key`` → ``data``).

See /app/memory/FEATURE_PHOTOS_S3_BASE64_SKIP.md.
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test

load_dotenv("/app/backend/.env")


def _tiny_png_data_url() -> str:
    """Return a valid data-URL for a 100x100 red PNG. Small enough
    for fast tests, large enough for Pillow to decode + resize
    into thumb/preview derivatives without complaining."""
    import io as _io
    from PIL import Image as _Image
    img = _Image.new("RGB", (100, 100), color="red")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def _seed_job(db, jid: str, tid: str):
    await db.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": "cust_probe",
        "title": jid,
        "status": "scheduled",
        "scheduled_date": "2026-02-10T09:00:00+00:00",
        "photos": [],
    })


async def _tid(db):
    t = await db.tenants.find_one({"slug": "aquaterra"},
                                     {"_id": 0, "id": 1})
    return t["id"]


async def _admin(db):
    return await db.users.find_one(
        {"email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1, "role": 1, "email": 1, "tenant_id": 1},
    )


def _fake_request():
    r = MagicMock()
    r.headers = {}
    return r


# ═════════════════════════════════════════════════════════════════
# 1 · Flag OFF — regression guard: data is retained, no s3_* keys.
# ═════════════════════════════════════════════════════════════════

def test_upload_flag_off_writes_base64_unchanged(monkeypatch):
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": False, "access_key": "", "secret_key": "",
            "region": "us-east-1", "bucket": "",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _c: False)

    jid = "B64SKIP_OFF_" + uuid.uuid4().hex[:8]

    async def _go(db):
        tid = await _tid(db)
        admin = await _admin(db)
        await _seed_job(db, jid, tid)
        try:
            body = jobs_router.PhotoIn(
                data=_tiny_png_data_url(), label="probe",
            )
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=_fake_request(),
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                          {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            p = photos[0]
            assert p.get("data"), "base64 blob missing on flag-off path"
            assert p.get("s3_key") is None
            assert p.get("s3_thumb_key") is None
            assert p.get("s3_preview_key") is None
            audits = await db.audit_logs.count_documents({
                "tenant_id": tid,
                "event": "photos.s3_upload_partial_failure",
                "payload.photo_id": p["id"],
            })
            assert audits == 0
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 2 · Flag ON + all three S3 puts OK → base64 DROPPED, s3_* stamped.
# ═════════════════════════════════════════════════════════════════

def test_upload_flag_on_success_skips_base64(monkeypatch):
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": True, "access_key": "AK", "secret_key": "SK",
            "region": "us-east-1", "bucket": "test-bucket",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _c: True)
    fake_client = MagicMock()
    # put_object returns a truthy MagicMock — success on all calls.
    monkeypatch.setattr(s3mod, "_client", lambda _c=None: fake_client)

    jid = "B64SKIP_ON_OK_" + uuid.uuid4().hex[:8]

    async def _go(db):
        tid = await _tid(db)
        admin = await _admin(db)
        await _seed_job(db, jid, tid)
        try:
            body = jobs_router.PhotoIn(
                data=_tiny_png_data_url(), label="probe",
            )
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=_fake_request(),
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                          {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            p = photos[0]
            assert not p.get("data"), (
                "base64 blob retained despite all S3 puts OK — "
                "base64-skip contract broken"
            )
            assert p.get("s3_key"), "s3_key missing"
            assert p.get("s3_thumb_key"), "s3_thumb_key missing"
            assert p.get("s3_preview_key"), "s3_preview_key missing"
            assert fake_client.put_object.call_count == 3
            audits = await db.audit_logs.count_documents({
                "tenant_id": tid,
                "event": "photos.s3_upload_partial_failure",
                "payload.photo_id": p["id"],
            })
            assert audits == 0
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.audit_logs.delete_many({"payload.job_id": jid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · Flag ON + preview put FAILS → base64 kept + audit row emitted.
# ═════════════════════════════════════════════════════════════════

def test_upload_flag_on_partial_failure_falls_back_to_base64(monkeypatch):
    from botocore.exceptions import ClientError
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": True, "access_key": "AK", "secret_key": "SK",
            "region": "us-east-1", "bucket": "test-bucket",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _c: True)

    # Simulate: original + thumb succeed, preview fails.
    fake_client = MagicMock()
    call_seq = {"n": 0}

    def _put_object(**kwargs):
        call_seq["n"] += 1
        key = kwargs.get("Key", "")
        if key.endswith("_preview.jpg"):
            raise ClientError(
                {"Error": {"Code": "AccessDenied",
                            "Message": "no s3:PutObject on preview"}},
                "PutObject",
            )
        return MagicMock()

    fake_client.put_object = MagicMock(side_effect=_put_object)
    monkeypatch.setattr(s3mod, "_client", lambda _c=None: fake_client)

    jid = "B64SKIP_ON_PART_" + uuid.uuid4().hex[:8]

    async def _go(db):
        tid = await _tid(db)
        admin = await _admin(db)
        await _seed_job(db, jid, tid)
        try:
            body = jobs_router.PhotoIn(
                data=_tiny_png_data_url(), label="probe",
            )
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=_fake_request(),
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                          {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            p = photos[0]
            assert p.get("data"), (
                "base64 blob dropped despite preview PUT failure — "
                "fallback contract broken"
            )
            assert p.get("s3_key"), "s3_key missing"
            assert p.get("s3_thumb_key"), "s3_thumb_key missing"
            assert p.get("s3_preview_key") is None, (
                "s3_preview_key stamped despite PUT failure"
            )
            audits = await db.audit_logs.find({
                "tenant_id": tid,
                "event": "photos.s3_upload_partial_failure",
                "payload.photo_id": p["id"],
            }).to_list(length=10)
            assert len(audits) == 1, (
                f"expected exactly 1 audit row, got {len(audits)}"
            )
            pl = audits[0].get("payload") or {}
            assert pl.get("job_id") == jid
            assert pl.get("customer_id") == "cust_probe"
            assert "preview" in (pl.get("s3_puts_failed") or [])
            assert "original" in (pl.get("s3_puts_succeeded") or [])
            assert "thumb" in (pl.get("s3_puts_succeeded") or [])
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.audit_logs.delete_many({"payload.job_id": jid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 4 · Flag ON + ALL three puts FAIL → base64 kept, no s3_* keys,
#      audit row lists all three keys in ``s3_puts_failed``.
# ═════════════════════════════════════════════════════════════════

def test_upload_flag_on_total_failure_falls_back_to_base64(monkeypatch):
    from botocore.exceptions import ClientError
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": True, "access_key": "AK", "secret_key": "SK",
            "region": "us-east-1", "bucket": "test-bucket",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _c: True)

    fake_client = MagicMock()

    def _put_object(**kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied",
                        "Message": "bucket policy denies all"}},
            "PutObject",
        )

    fake_client.put_object = MagicMock(side_effect=_put_object)
    monkeypatch.setattr(s3mod, "_client", lambda _c=None: fake_client)

    jid = "B64SKIP_ON_TOTAL_" + uuid.uuid4().hex[:8]

    async def _go(db):
        tid = await _tid(db)
        admin = await _admin(db)
        await _seed_job(db, jid, tid)
        try:
            body = jobs_router.PhotoIn(
                data=_tiny_png_data_url(), label="probe",
            )
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=_fake_request(),
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                          {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            p = photos[0]
            assert p.get("data"), (
                "base64 blob dropped despite ALL S3 puts failing"
            )
            assert p.get("s3_key") is None
            assert p.get("s3_thumb_key") is None
            assert p.get("s3_preview_key") is None
            audits = await db.audit_logs.find({
                "tenant_id": tid,
                "event": "photos.s3_upload_partial_failure",
                "payload.photo_id": p["id"],
            }).to_list(length=10)
            assert len(audits) == 1
            failed = set(audits[0]["payload"].get("s3_puts_failed") or [])
            assert failed == {"original", "thumb", "preview"}, (
                f"expected all three keys in failed, got {failed}"
            )
            assert not (audits[0]["payload"].get("s3_puts_succeeded") or [])
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.audit_logs.delete_many({"payload.job_id": jid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 5 · Flag ON + full success — read path stays healthy even though
#      base64 ``data`` was dropped from the persisted doc. Exercises
#      the DB row directly (read path already has its own Phase-1
#      test coverage; this is a smoke check that the write-path
#      omission doesn't leave a malformed row).
# ═════════════════════════════════════════════════════════════════

def test_upload_flag_on_success_row_shape_still_readable(monkeypatch):
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": True, "access_key": "AK", "secret_key": "SK",
            "region": "us-east-1", "bucket": "test-bucket",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _c: True)
    monkeypatch.setattr(s3mod, "_client", lambda _c=None: MagicMock())

    jid = "B64SKIP_ON_SHAPE_" + uuid.uuid4().hex[:8]

    async def _go(db):
        tid = await _tid(db)
        admin = await _admin(db)
        await _seed_job(db, jid, tid)
        try:
            body = jobs_router.PhotoIn(
                data=_tiny_png_data_url(), label="probe",
            )
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=_fake_request(),
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                          {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            p = photos[0]
            assert p.get("id"), "photo id missing"
            assert p.get("label") == "probe"
            assert p.get("created_at"), "created_at missing"
            assert p.get("s3_key")
            assert p.get("s3_thumb_key")
            assert p.get("s3_preview_key")
            assert p.get("s3_mime") == "image/png"
            assert "data" not in p or not p.get("data")
            from services.jobs_slim_photos import (
                strip_s3_metadata_from_photos,
            )
            probe = {"photos": [dict(p)]}
            strip_s3_metadata_from_photos(probe)
            assert "s3_key" not in probe["photos"][0]
            assert "s3_thumb_key" not in probe["photos"][0]
            assert "s3_preview_key" not in probe["photos"][0]
            assert "s3_mime" not in probe["photos"][0]
        finally:
            await db.jobs.delete_one({"id": jid})
            await db.audit_logs.delete_many({"payload.job_id": jid})

    run_test(_go)
