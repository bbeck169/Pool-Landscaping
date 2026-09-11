"""Feb-2026 · Thumbnails + upload guardrails contract tests.

Locks the invariants shipped alongside Phase 1/2:

  1. Oversize decoded payload → 413 ``photo_too_large``.
  2. Non-image MIME              → 415 ``photo_unsupported_mime``.
  3. Wet upload with S3 ON       → ``s3_thumb_key`` +
     ``s3_preview_key`` stamped in DB; ``s3_key`` too.
  4. Wet upload with S3 OFF      → embedded base64 ``thumb`` +
     ``preview`` stamped in DB.
  5. Slim-photos wire rows carry ``photo_thumb_urls`` but strip
     ``s3_thumb_key`` / ``s3_preview_key`` / ``thumb`` / ``preview``.
  6. ``strip_s3_metadata_from_photos`` removes derivative fields
     from a single job doc (used on ``POST /photos`` +
     ``GET /jobs/{jid}`` responses).
  7. Public read endpoints ``/thumb`` and ``/preview`` return
     302 for S3-stamped photos.
  8. Public read endpoints fall back to embedded base64 when
     no S3 key is stamped.
  9. Phase 2 migration stamps thumb + preview keys alongside
     ``s3_key`` on wet-run.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
import requests
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test

load_dotenv("/app/backend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str = "admin@aquaterra.com",
           pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login()}"}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tiny_png() -> bytes:
    """Generate a valid 32×32 red PNG via Pillow so the derivative
    resampler in ``photos_derivatives`` can actually decode it.
    The 67-byte hard-coded 1×1 PNG we use elsewhere trips on some
    Pillow paths ("broken data stream") — this variant is safe."""
    from PIL import Image
    im = Image.new("RGB", (32, 32), (200, 40, 40))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _b64(payload: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode()


async def _seed_job(db, jid: str, photos: list) -> str:
    t = await db.tenants.find_one({"slug": "aquaterra"},
                                     {"_id": 0, "id": 1})
    tid = t["id"]
    await db.jobs.insert_one({
        "id": jid, "tenant_id": tid, "customer_id": "cust_probe",
        "title": jid, "status": "scheduled",
        "scheduled_date": "2026-02-10T09:00:00+00:00",
        "photos": photos,
    })
    return tid


# ═════════════════════════════════════════════════════════════════
# 1 · Oversize → 413
# ═════════════════════════════════════════════════════════════════

def test_upload_too_large_returns_413(admin_headers):
    prefix = "THUMB_TOOBIG_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [])
            # 8 MB blob of zeroes wrapped as a fake PNG data URL.
            oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (8 * 1024 * 1024)
            r = requests.post(
                f"{API}/jobs/{jid}/photos",
                headers={**admin_headers, "Content-Type": "application/json"},
                json={"data": _b64(oversized, "image/png"), "label": "big"},
                timeout=60,
            )
            assert r.status_code == 413, r.text
            body = r.json()
            detail = body.get("detail") or {}
            assert detail.get("code") == "photo_too_large"
            assert detail.get("actual_bytes", 0) > detail.get("max_bytes", 0)
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 2 · Non-image MIME → 415
# ═════════════════════════════════════════════════════════════════

def test_upload_bad_mime_returns_415(admin_headers):
    prefix = "THUMB_BADMIME_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [])
            r = requests.post(
                f"{API}/jobs/{jid}/photos",
                headers={**admin_headers, "Content-Type": "application/json"},
                json={"data": _b64(b"%PDF-1.4 fakepdfbytes", "application/pdf"),
                       "label": "pdf"},
                timeout=30,
            )
            assert r.status_code == 415, r.text
            detail = r.json().get("detail") or {}
            assert detail.get("code") == "photo_unsupported_mime"
            assert "image/jpeg" in detail.get("allowed", [])
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 3 · Wet upload with S3 ON — derivatives stamped in DB
# ═════════════════════════════════════════════════════════════════

def test_upload_stamps_derivative_keys_when_flag_on(admin_headers):
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    prefix = "THUMB_S3ON_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
            tid = t["id"]
            admin = await db.users.find_one(
                {"email": "admin@aquaterra.com"},
                {"_id": 0, "id": 1, "role": 1, "email": 1, "tenant_id": 1},
            )
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid, "customer_id": "cust",
                "title": jid, "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [],
            })
            fake = MagicMock()
            with patch.object(s3mod, "_client", return_value=fake), \
                 patch.object(s3mod, "_is_configured", return_value=True), \
                 patch.object(s3mod, "_cfg", return_value={
                     "enabled": True, "access_key": "AK", "secret_key": "SK",
                     "region": "us-east-1", "bucket": "test-bucket",
                     "prefix": "job-photos/", "ttl": 3600,
                 }):
                body = jobs_router.PhotoIn(data=_b64(_tiny_png()),
                                             label="probe")
                req = MagicMock(); req.headers = {}
                resp = await jobs_router.add_job_photo(
                    jid=jid, body=body, request=req,
                    user=admin, tenant={"id": tid},
                )
            # Wire response strips all S3 metadata (see slim helper).
            for p in (resp.get("photos") or []):
                assert "s3_key" not in p
                assert "s3_thumb_key" not in p
                assert "s3_preview_key" not in p
                assert "thumb" not in p
                assert "preview" not in p
            # DB doc carries all three keys.
            doc = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1})
            p = doc["photos"][0]
            assert p.get("s3_key")
            assert p.get("s3_thumb_key") == p["s3_key"] + "_thumb.jpg"
            assert p.get("s3_preview_key") == p["s3_key"] + "_preview.jpg"
            # boto3 saw 3 puts — original + thumb + preview.
            assert fake.put_object.call_count >= 3
            put_keys = {c.kwargs["Key"] for c in fake.put_object.call_args_list}
            assert any(k.endswith("_thumb.jpg") for k in put_keys)
            assert any(k.endswith("_preview.jpg") for k in put_keys)
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 4 · Wet upload with S3 OFF — embedded base64 derivatives in DB
# ═════════════════════════════════════════════════════════════════

def test_upload_embeds_base64_derivatives_when_flag_off(admin_headers):
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    prefix = "THUMB_S3OFF_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
            tid = t["id"]
            admin = await db.users.find_one(
                {"email": "admin@aquaterra.com"},
                {"_id": 0, "id": 1, "role": 1, "email": 1, "tenant_id": 1},
            )
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid, "customer_id": "cust",
                "title": jid, "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [],
            })
            # Simulate flag OFF — S3 client is None so ``upload_photo``
            # returns None and the write path falls into the base64
            # derivative branch.
            with patch.object(s3mod, "_client", return_value=None), \
                 patch.object(s3mod, "_is_configured", return_value=False):
                body = jobs_router.PhotoIn(data=_b64(_tiny_png()),
                                             label="probe")
                req = MagicMock(); req.headers = {}
                await jobs_router.add_job_photo(
                    jid=jid, body=body, request=req,
                    user=admin, tenant={"id": tid},
                )
            doc = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1})
            p = doc["photos"][0]
            assert not p.get("s3_key"), "s3_key stamped despite flag off"
            assert isinstance(p.get("thumb"), str) and p["thumb"].startswith(
                "data:image/jpeg;base64,"
            )
            assert isinstance(p.get("preview"), str) and p["preview"].startswith(
                "data:image/jpeg;base64,"
            )
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 5 · slim-photos emits photo_thumb_urls, strips derivative fields
# ═════════════════════════════════════════════════════════════════

def test_slim_photos_emits_thumb_urls_and_strips_deriv_keys():
    from services.jobs_slim_photos import (
        slim_photos_on_rows, strip_s3_metadata_from_photos,
    )
    rows = [{
        "id": "job-42",
        "photos": [{
            "id": "photo-9",
            "data": "data:image/png;base64,MQ==",
            "s3_key": "job-photos/t/job-42/photo-9",
            "s3_thumb_key": "job-photos/t/job-42/photo-9_thumb.jpg",
            "s3_preview_key": "job-photos/t/job-42/photo-9_preview.jpg",
            "thumb": "data:image/jpeg;base64,QQ==",
            "preview": "data:image/jpeg;base64,QQ==",
        }],
    }]
    slim_photos_on_rows(rows, include_photos=True)
    row = rows[0]
    assert row["photo_thumb_urls"] == [
        "/api/public/job-photo/job-42/photo-9/thumb"
    ]
    p = row["photos"][0]
    for stripped in ("s3_key", "s3_thumb_key", "s3_preview_key",
                       "thumb", "preview"):
        assert stripped not in p, f"{stripped} leaked in include_photos wire"
    # Also cover the single-doc strip helper (used on POST + detail).
    doc = {
        "id": "job-42",
        "photos": [{"id": "p", "s3_thumb_key": "k", "s3_preview_key": "k",
                    "thumb": "t", "preview": "v", "data": "d"}],
    }
    strip_s3_metadata_from_photos(doc)
    p = doc["photos"][0]
    for stripped in ("s3_thumb_key", "s3_preview_key", "thumb", "preview"):
        assert stripped not in p


# ═════════════════════════════════════════════════════════════════
# 7 · Public read /thumb & /preview → 302 when S3 keys present
# ═════════════════════════════════════════════════════════════════

def test_public_thumb_and_preview_return_302_when_s3_keys_present():
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod
    from fastapi.responses import RedirectResponse

    prefix = "THUMB_READ_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"
    pid = prefix + "_photo"

    async def go(db):
        try:
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                              {"_id": 0, "id": 1})
            tid = t["id"]
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid, "customer_id": "c",
                "title": jid, "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [{
                    "id": pid, "data": _b64(_tiny_png()),
                    "s3_key":         f"job-photos/{tid}/{jid}/{pid}",
                    "s3_thumb_key":   f"job-photos/{tid}/{jid}/{pid}_thumb.jpg",
                    "s3_preview_key": f"job-photos/{tid}/{jid}/{pid}_preview.jpg",
                    "s3_mime": "image/png", "label": "probe",
                    "created_at": "2026-02-10T00:00:00+00:00",
                }],
            })
            with patch.object(s3mod, "generate_signed_url",
                              return_value="https://s3.example.com/signed"):
                thumb_resp = await jobs_router.public_job_photo_thumb(
                    jid=jid, pid=pid,
                )
                preview_resp = await jobs_router.public_job_photo_preview(
                    jid=jid, pid=pid,
                )
            assert isinstance(thumb_resp, RedirectResponse)
            assert thumb_resp.status_code == 302
            assert thumb_resp.headers["location"] == "https://s3.example.com/signed"
            assert isinstance(preview_resp, RedirectResponse)
            assert preview_resp.status_code == 302
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 8 · Public read /thumb falls back to embedded base64 when no s3
# ═════════════════════════════════════════════════════════════════

def test_public_thumb_returns_base64_body_when_no_s3_key(admin_headers):
    prefix = "THUMB_B64_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"
    pid = prefix + "_photo"
    thumb_blob = b"\xff\xd8\xff\xd9"  # SOI + EOI — minimal JPEG stub

    async def go(db):
        try:
            await _seed_job(db, jid, [{
                "id": pid,
                "data": _b64(_tiny_png()),
                "thumb": "data:image/jpeg;base64,"
                          + base64.b64encode(thumb_blob).decode(),
                "label": "probe",
                "created_at": "2026-02-10T00:00:00+00:00",
            }])
        finally:
            pass
        try:
            r = requests.get(
                f"{API}/public/job-photo/{jid}/{pid}/thumb",
                allow_redirects=False, timeout=30,
            )
            assert r.status_code == 200, r.text
            assert r.headers.get("content-type", "").startswith("image/jpeg")
            assert r.content == thumb_blob
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 9 · Phase 2 migration stamps thumb + preview keys
# ═════════════════════════════════════════════════════════════════

def test_phase2_migration_stamps_derivative_keys():
    from routers import admin_s3_migrate
    from services.aws_s3 import photos as s3mod

    prefix = "THUMB_MIG_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            tid = await _seed_job(db, jid, [{
                "id": prefix + "_p",
                "data": _b64(_tiny_png()),
                "label": "legacy",
                "created_at": "2026-02-10T00:00:00+00:00",
            }])
            stub_objects: dict[str, bytes] = {}
            put_calls: list[str] = []

            def _upload(t, j, p, blob, mime):
                key = f"job-photos/{t}/{j}/{p}"
                stub_objects[key] = blob; put_calls.append(key)
                return key

            def _put_at(key, blob, mime):
                stub_objects[key] = blob; put_calls.append(key)
                return key

            def _head(key):
                return key in stub_objects

            with patch.object(s3mod, "upload_photo", side_effect=_upload), \
                 patch.object(s3mod, "upload_blob_at_key", side_effect=_put_at), \
                 patch.object(s3mod, "check_object_exists", side_effect=_head), \
                 patch.object(s3mod, "_is_configured", return_value=True), \
                 patch.object(s3mod, "_client", return_value=MagicMock()):
                await admin_s3_migrate.migrate_photos_to_s3(
                    dry_run=False, limit=100, tenant_id=tid,
                    purge_base64=False, resume_after_job_id=None,
                    rate_limit_qps=10, user={"role": "admin"},
                )

            doc = await db.jobs.find_one({"id": jid}, {"_id": 0, "photos": 1})
            p = doc["photos"][0]
            assert p.get("s3_key")
            assert p.get("s3_thumb_key") == p["s3_key"] + "_thumb.jpg"
            assert p.get("s3_preview_key") == p["s3_key"] + "_preview.jpg"
            assert any(k.endswith("_thumb.jpg") for k in put_calls)
            assert any(k.endswith("_preview.jpg") for k in put_calls)
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(go)
