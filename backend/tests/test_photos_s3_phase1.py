"""Feb-2026 · Photos-in-S3 Phase 1 · contract tests.

Locks the seven Phase-1 invariants:

  1. ``upload_photo`` calls ``put_object`` with the canonical key
     format ``{PREFIX}{tenant_id}/{job_id}/{photo_id}``, SSE-S3,
     correct ContentType.
  2. Photo upload dual-writes — ``photos[].s3_key`` is stamped
     ONLY when the flag is on and boto3 succeeds. Post-Feb-2026
     base64-skip: on flag-on + all-three S3 puts OK the base64
     ``photos[].data`` blob is DROPPED; on flag-on + any S3 put
     failed the base64 is retained as a durability fallback.
  3. Public read endpoint returns a 302 to the presigned URL when
     ``s3_key`` is present AND the flag is on. Falls back to the
     base64 payload otherwise.
  4. Photo delete calls ``delete_object`` on the stored ``s3_key``
     when present + flag on. NEVER crashes when either is missing.
  5. Admin health endpoint reports the config state honestly.
  6. Graceful failure — every S3 helper returns a fallback value
     (``None`` / ``False``) when boto3 raises; the app never 500s.
  7. ``s3_key`` NEVER leaks over the wire (upload response, detail
     response, include_photos=true list all strip it).
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

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


async def _db():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]], client


async def _tid(db):
    t = await db.tenants.find_one({"slug": "aquaterra"},
                                     {"_id": 0, "id": 1})
    return t["id"]


# ═════════════════════════════════════════════════════════════════
# 1 · S3 module — key format + SSE + ContentType wiring
# ═════════════════════════════════════════════════════════════════

def test_upload_photo_puts_object_with_correct_key_sse_and_content_type(
    monkeypatch,
):
    monkeypatch.setenv("PHOTOS_S3_ENABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SECRET_TEST")
    monkeypatch.setenv("AWS_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("AWS_S3_PREFIX", "job-photos/")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    fake_client = MagicMock()
    with patch("boto3.client", return_value=fake_client):
        from services.aws_s3 import photos as s3mod
        key = s3mod.upload_photo(
            tenant_id="tenantA", job_id="jobB", photo_id="photoC",
            blob=b"hello world", mime="image/png",
        )

    assert key == "job-photos/tenantA/jobB/photoC"
    fake_client.put_object.assert_called_once()
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "test-bucket"
    assert kwargs["Key"] == "job-photos/tenantA/jobB/photoC"
    assert kwargs["Body"] == b"hello world"
    assert kwargs["ContentType"] == "image/png"
    assert kwargs["ServerSideEncryption"] == "AES256"


def test_key_builder_rejects_path_traversal(monkeypatch):
    monkeypatch.setenv("PHOTOS_S3_ENABLED", "true")
    from services.aws_s3.photos import build_key
    with pytest.raises(ValueError):
        build_key("../etc/passwd", "jid", "pid")
    with pytest.raises(ValueError):
        build_key("tid", "jid", "../../../secret")


# ═════════════════════════════════════════════════════════════════
# 2 · Dual-write behavior — DB blob stays; s3_key stamped when flag on
# ═════════════════════════════════════════════════════════════════

def test_upload_stamps_s3_key_when_flag_on(admin_headers, monkeypatch):
    """Direct-handler test with the shared loop fixture. Patches
    the in-process ``boto3.client`` factory so the dual-write side
    (``s3_key`` on the DB doc) is verifiable."""
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    prefix = "TEST_S3_ON_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                                {"_id": 0, "id": 1})
        tid = tenant["id"]
        admin = await db.users.find_one(
            {"email": "admin@aquaterra.com"},
            {"_id": 0, "id": 1, "role": 1, "email": 1, "tenant_id": 1},
        )
        try:
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": "cust_probe",
                "title": prefix,
                "status": "scheduled",
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
                body = jobs_router.PhotoIn(
                    data="data:image/png;base64," +
                          base64.b64encode(b"fake").decode(),
                    label="probe",
                )
                fake_request = MagicMock()
                fake_request.headers = {}
                resp = await jobs_router.add_job_photo(
                    jid=jid, body=body, request=fake_request,
                    user=admin, tenant={"id": tid},
                )
            # Wire response has no s3_key (strip runs on serialization).
            for p in (resp.get("photos") or []):
                assert "s3_key" not in p
                assert "s3_mime" not in p
            # DB doc DOES carry s3_key (dual-write happened).
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            # Feb-2026 · base64-skip: the ``data`` field's presence
            # depends on whether the payload was Pillow-decodable
            # (i.e., whether derivatives could be generated). This
            # test uses a stub payload (``b"fake"``) that Pillow
            # rejects, so the base64 fallback fires. The base64-skip
            # contract itself is locked by
            # ``tests/test_photos_s3_base64_skip.py``. This test's
            # invariant is just that ``s3_key`` + ``s3_mime`` are
            # stamped when the flag is on and boto3 succeeds.
            assert photos[0].get("s3_key") == \
                f"job-photos/{tid}/{jid}/{photos[0]['id']}"
            assert photos[0].get("s3_mime") == "image/png"
            fake.put_object.assert_called_once()
            kwargs = fake.put_object.call_args.kwargs
            assert kwargs["Bucket"] == "test-bucket"
            assert kwargs["ServerSideEncryption"] == "AES256"
            assert kwargs["ContentType"] == "image/png"
            assert kwargs["Key"].startswith(f"job-photos/{tid}/{jid}/")
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_upload_does_NOT_stamp_s3_key_when_flag_off(admin_headers, monkeypatch):
    """Flag OFF — upload must skip the S3 side entirely; DB blob is
    stamped as always.

    Hardened Feb-2026 to be independent of the process's ambient
    ``PHOTOS_S3_ENABLED`` value: uses direct in-process handler
    invocation + ``monkeypatch.setattr`` on
    ``services.aws_s3.photos._cfg`` and ``_is_configured`` so the
    flag state is scoped to this test only (auto-restored at
    teardown by the ``monkeypatch`` fixture). Matches the sibling
    ``test_upload_stamps_s3_key_when_flag_on`` topology.
    """
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod

    prefix = "TEST_S3_OFF_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    # Force the flag off for the duration of this test regardless
    # of the .env / process-env state. ``monkeypatch`` restores at
    # teardown so we don't leak state into sibling tests.
    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": False, "access_key": "", "secret_key": "",
            "region": "us-east-1", "bucket": "",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _cfg: False)

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                                {"_id": 0, "id": 1})
        tid = tenant["id"]
        admin = await db.users.find_one(
            {"email": "admin@aquaterra.com"},
            {"_id": 0, "id": 1, "role": 1, "email": 1, "tenant_id": 1},
        )
        try:
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": "cust_probe",
                "title": prefix,
                "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [],
            })
            body = jobs_router.PhotoIn(
                data="data:image/png;base64," +
                      base64.b64encode(b"fake").decode(),
                label="probe",
            )
            fake_request = MagicMock()
            fake_request.headers = {}
            await jobs_router.add_job_photo(
                jid=jid, body=body, request=fake_request,
                user=admin, tenant={"id": tid},
            )
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            photos = doc.get("photos") or []
            assert len(photos) == 1
            assert photos[0].get("data"), "DB blob missing"
            assert photos[0].get("s3_key") is None, (
                "s3_key stamped despite flag off"
            )
            assert photos[0].get("s3_mime") is None
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════
# 3 · Read path — 302 to presigned URL when s3_key + flag on
# ═════════════════════════════════════════════════════════════════

def test_public_read_returns_302_when_s3_key_present(admin_headers):
    """Direct-handler test with the shared loop fixture: patch
    ``generate_signed_url`` in-process and call ``public_job_photo``
    directly. Asserts a RedirectResponse is returned when ``s3_key``
    is present on the doc."""
    from routers import jobs as jobs_router
    from services.aws_s3 import photos as s3mod
    from fastapi.responses import RedirectResponse

    prefix = "TEST_S3_READ_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"
    pid = prefix + "_photo"

    async def _go(db):
        tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                                {"_id": 0, "id": 1})
        tid = tenant["id"]
        try:
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": "cust_probe",
                "title": prefix,
                "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [{
                    "id": pid,
                    "data": "data:image/png;base64," +
                             base64.b64encode(b"fake").decode(),
                    "s3_key": f"job-photos/{tid}/{jid}/{pid}",
                    "s3_mime": "image/png",
                    "label": "probe",
                    "created_at": "2026-02-10T09:00:00+00:00",
                }],
            })
            with patch.object(s3mod, "generate_signed_url",
                              return_value="https://s3.example.com/presigned"):
                resp = await jobs_router.public_job_photo(jid=jid, pid=pid)
            assert isinstance(resp, RedirectResponse), (
                f"expected RedirectResponse, got {type(resp).__name__}"
            )
            assert resp.status_code == 302
            assert resp.headers["location"] == "https://s3.example.com/presigned"
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_public_read_falls_back_to_base64_when_no_s3_key():
    prefix = "TEST_S3_FALLBACK_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"
    pid = prefix + "_photo"
    blob = b"fake"

    async def _seed():
        db, client = await _db()
        try:
            tid = await _tid(db)
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": "cust_probe",
                "title": prefix,
                "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [{
                    "id": pid,
                    "data": "data:image/png;base64," + base64.b64encode(blob).decode(),
                    "label": "probe",
                    "created_at": "2026-02-10T09:00:00+00:00",
                }],
            })
        finally:
            client.close()

    _run(_seed())
    try:
        r = requests.get(f"{API}/public/job-photo/{jid}/{pid}",
                            allow_redirects=False, timeout=30)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.content == blob
    finally:
        async def _clean():
            db, client = await _db()
            try:
                await db.jobs.delete_one({"id": jid})
            finally:
                client.close()
        _run(_clean())


# ═════════════════════════════════════════════════════════════════
# 5 · Admin health endpoint — reports config honestly
# ═════════════════════════════════════════════════════════════════

def test_admin_s3_health_reports_disabled_by_default(admin_headers, monkeypatch):
    """Flag OFF — health endpoint reports the disabled envelope.

    Hardened Feb-2026 to be independent of ambient
    ``PHOTOS_S3_ENABLED`` / AWS_* env state: calls
    ``services.aws_s3.photos.health_check`` directly (same helper
    the router invokes) with ``_cfg`` monkeypatched to the
    disabled-by-default envelope. ``monkeypatch`` restores at
    teardown. Auth/authorization at the HTTP boundary is covered by
    the sibling ``test_admin_s3_health_rejects_non_admin`` test.
    """
    from services.aws_s3 import photos as s3mod

    monkeypatch.setattr(
        s3mod, "_cfg",
        lambda: {
            "enabled": False, "access_key": "", "secret_key": "",
            "region": "us-east-1", "bucket": "",
            "prefix": "job-photos/", "ttl": 3600,
        },
    )
    monkeypatch.setattr(s3mod, "_is_configured", lambda _cfg: False)

    body = s3mod.health_check()
    assert body["status"] == "disabled"
    assert body["enabled"] is False
    assert body["bucket_set"] is False
    assert body["region"] == "us-east-1"
    assert body["prefix"] == "job-photos/"
    assert body["signed_ttl"] == 3600
    assert body["self_test"] is None


def test_admin_s3_health_rejects_non_admin():
    tech_token = _login("mike@aquaterra.com")
    r = requests.get(f"{API}/admin/s3/health",
                       headers={"Authorization": f"Bearer {tech_token}"},
                       timeout=30)
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════
# 6 · Graceful failure — S3 raising must not 5xx the app
# ═════════════════════════════════════════════════════════════════

def test_s3_module_swallows_boto3_exceptions(monkeypatch):
    """put_object / delete_object / head_object exceptions must
    return fallback values, never propagate."""
    monkeypatch.setenv("PHOTOS_S3_ENABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AK")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "SK")
    monkeypatch.setenv("AWS_S3_BUCKET", "b")
    fake = MagicMock()
    fake.put_object.side_effect = RuntimeError("boom")
    fake.delete_object.side_effect = RuntimeError("boom")
    fake.head_object.side_effect = RuntimeError("boom")
    fake.generate_presigned_url.side_effect = RuntimeError("boom")
    with patch("boto3.client", return_value=fake):
        from services.aws_s3 import photos as s3mod
        assert s3mod.upload_photo("t", "j", "p", b"x", "image/png") is None
        assert s3mod.delete_photo("some/key") is False
        assert s3mod.check_object_exists("some/key") is False
        assert s3mod.generate_signed_url("some/key") is None


# ═════════════════════════════════════════════════════════════════
# 7 · s3_key stripped from every wire path (detail + include_photos)
# ═════════════════════════════════════════════════════════════════

def test_strip_s3_metadata_from_photos_removes_s3_keys():
    from services.jobs_slim_photos import (
        strip_s3_metadata_from_photos, slim_photos_on_rows,
    )
    doc = {
        "id": "j1",
        "photos": [
            {"id": "p1", "data": "d1", "s3_key": "k1", "s3_mime": "m1"},
            {"id": "p2", "data": "d2"},
        ],
    }
    strip_s3_metadata_from_photos(doc)
    for p in doc["photos"]:
        assert "s3_key" not in p
        assert "s3_mime" not in p
    # slim_photos_on_rows(include_photos=True) also strips.
    rows = [
        {"id": "j1",
         "photos": [{"id": "p1", "data": "d1", "s3_key": "kX"}]},
    ]
    slim_photos_on_rows(rows, include_photos=True)
    for p in rows[0]["photos"]:
        assert "s3_key" not in p


def test_detail_endpoint_strips_s3_key_from_wire(admin_headers):
    prefix = "TEST_S3_DETAIL_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"
    pid = prefix + "_photo"

    async def _seed():
        db, client = await _db()
        try:
            tid = await _tid(db)
            await db.jobs.insert_one({
                "id": jid, "tenant_id": tid,
                "customer_id": "cust_probe",
                "title": prefix,
                "status": "scheduled",
                "scheduled_date": "2026-02-10T09:00:00+00:00",
                "photos": [{
                    "id": pid,
                    "data": "data:image/png;base64,MQ==",
                    "s3_key": f"job-photos/{tid}/{jid}/{pid}",
                    "s3_mime": "image/png",
                    "label": "probe",
                    "created_at": "2026-02-10T09:00:00+00:00",
                }],
            })
        finally:
            client.close()

    _run(_seed())
    try:
        r = requests.get(f"{API}/jobs/{jid}",
                            headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        photos = doc.get("photos") or []
        assert len(photos) == 1
        assert photos[0].get("data")  # full data still ships (detail contract)
        assert "s3_key" not in photos[0], "s3_key leaked on detail response"
        assert "s3_mime" not in photos[0]
    finally:
        async def _clean():
            db, client = await _db()
            try:
                await db.jobs.delete_one({"id": jid})
            finally:
                client.close()
        _run(_clean())
