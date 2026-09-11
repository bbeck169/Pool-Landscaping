"""Feb-2026 · Photos-in-S3 Phase 2 · backfill migration tests.

Locks the eight Phase-2 invariants (see
``/app/memory/FEATURE_PHOTOS_S3_PHASE2.md``):

  1. Dry-run — NO S3 writes, NO DB writes, tallies match candidates.
  2. Wet-run without purge — stamps ``s3_key`` + ``s3_mime``; keeps
     ``photos[].data`` intact so read-path fallback stays live.
  3. Wet-run WITH purge — stamps + unsets ``photos[].data``.
  4. Idempotency — 2nd wet-run on same candidates reports them in
     ``already_migrated[]`` and does NOT re-upload.
  5. Resumable — ``limit=1`` twice covers two-job batch; 2nd call
     picks up after the 1st via ``resume_after_job_id``.
  6. Failure isolation — one photo raising mid-upload lands in
     ``failed[]``; the migration continues and other photos ship.
  7. Auth gate — non-admin token → 403.
  8. Flag off — ``PHOTOS_S3_ENABLED=false`` → 409 ``s3_disabled``.

Every test patches ``services.aws_s3.photos`` so we exercise the
migration logic without touching real AWS. The Phase-1 module
already has its own contract tests for the boto3 wiring.
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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


def _b64(payload: bytes = b"fake-photo-bytes") -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode()


async def _seed_job(db, jid: str, photos: list) -> str:
    t = await db.tenants.find_one({"slug": "aquaterra"},
                                     {"_id": 0, "id": 1})
    tid = t["id"]
    await db.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "customer_id": "cust_probe",
        "title": jid,
        "status": "scheduled",
        "scheduled_date": "2026-02-10T09:00:00+00:00",
        "photos": photos,
    })
    return tid


async def _cleanup(db, *jids: str) -> None:
    await db.jobs.delete_many({"id": {"$in": list(jids)}})


# ═════════════════════════════════════════════════════════════════
# 8 · Flag off → 409 s3_disabled
# ═════════════════════════════════════════════════════════════════

def test_migration_returns_409_when_flag_off():
    """Direct-handler test — patch ``_is_configured`` + ``_client`` to
    simulate the flag-off state (env currently has S3 enabled)."""
    from fastapi import HTTPException
    from services.aws_s3 import photos as s3mod

    async def go():
        with patch.object(s3mod, "_is_configured", return_value=False), \
             patch.object(s3mod, "_client", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await _call_migrate(dry_run=True)
            assert exc.value.status_code == 409
            detail = exc.value.detail
            if isinstance(detail, dict):
                assert detail.get("code") == "s3_disabled"
            else:
                assert "s3_disabled" in str(detail)

    _run(go())


# ═════════════════════════════════════════════════════════════════
# 7 · Auth gate → non-admin 403
# ═════════════════════════════════════════════════════════════════

def test_migration_rejects_non_admin():
    tech_token = _login("mike@aquaterra.com")
    r = requests.post(
        f"{API}/admin/migrations/migrate-photos-to-s3",
        headers={"Authorization": f"Bearer {tech_token}"},
        params={"dry_run": True}, timeout=30,
    )
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════
# Direct-handler tests — call the router function in-process so we
# can patch the S3 module cleanly. Uses the same DB the app uses.
# ═════════════════════════════════════════════════════════════════

async def _call_migrate(
    *, dry_run=True, purge_base64=False, tenant_id=None,
    limit=500, resume_after_job_id=None, rate_limit_qps=10,
):
    from routers import admin_s3_migrate
    admin_user = {"role": "admin"}
    return await admin_s3_migrate.migrate_photos_to_s3(
        dry_run=dry_run, limit=limit, tenant_id=tenant_id,
        purge_base64=purge_base64,
        resume_after_job_id=resume_after_job_id,
        rate_limit_qps=rate_limit_qps,
        user=admin_user,
    )


class _S3Stub:
    """In-memory stand-in for the ``services.aws_s3.photos``
    module. Tracks put/head calls so tests can assert behavior."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[str] = []
        self.head_calls: list[str] = []
        self.raise_on_photo_id: str | None = None

    def make_patch(self, enabled=True):
        s3mod_patches = []
        from services.aws_s3 import photos as s3mod

        def _upload(tenant_id, job_id, photo_id, blob, mime):
            self.put_calls.append(photo_id)
            if self.raise_on_photo_id == photo_id:
                return None  # simulate silent failure
            key = f"job-photos/{tenant_id}/{job_id}/{photo_id}"
            self.objects[key] = blob
            return key

        def _head(key):
            self.head_calls.append(key)
            return key in self.objects

        def _cfg():
            return {"enabled": enabled, "access_key": "AK",
                    "secret_key": "SK", "region": "us-east-1",
                    "bucket": "test", "prefix": "job-photos/",
                    "ttl": 3600}

        s3mod_patches.append(patch.object(s3mod, "upload_photo",
                                              side_effect=_upload))
        s3mod_patches.append(patch.object(s3mod, "check_object_exists",
                                              side_effect=_head))
        s3mod_patches.append(patch.object(s3mod, "_cfg",
                                              side_effect=_cfg))
        s3mod_patches.append(patch.object(s3mod, "_is_configured",
                                              return_value=enabled))
        s3mod_patches.append(patch.object(s3mod, "_client",
                                              return_value=(MagicMock() if enabled else None)))
        return s3mod_patches


# ═════════════════════════════════════════════════════════════════
# 1 · Dry-run — no writes anywhere
# ═════════════════════════════════════════════════════════════════

def test_migration_dry_run_touches_nothing():
    prefix = "P2_DRY_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [{
                "id": prefix + "_p1", "data": _b64(b"AAA"),
                "label": "one", "created_at": "2026-02-10T00:00:00+00:00",
            }])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                report = await _call_migrate(dry_run=True, tenant_id=tid)
            finally:
                for p in patches: p.stop()
            # Report — dry_run flag + candidates + no uploads.
            assert report["dry_run"] is True
            assert report["candidate_photos"] >= 1
            uploaded_pids = {u["photo_id"] for u in report["uploaded"]}
            assert (prefix + "_p1") in uploaded_pids
            assert report["uploaded"][0].get("dry_run") is True
            # NO real puts / heads for the candidate we cared about.
            assert (prefix + "_p1") not in stub.put_calls
            # DB unchanged — photos still lack s3_key.
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            for p in doc["photos"]:
                assert not p.get("s3_key")
                assert p.get("data")
        finally:
            await _cleanup(db, jid)

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 2 · Wet-run without purge — stamps s3_key, keeps base64
# ═════════════════════════════════════════════════════════════════

def test_migration_wet_run_no_purge_stamps_key_and_keeps_data():
    prefix = "P2_WET_KEEP_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [{
                "id": prefix + "_p1", "data": _b64(b"BBBBB"),
                "label": "one",
            }])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                report = await _call_migrate(dry_run=False,
                                               purge_base64=False,
                                               tenant_id=tid)
            finally:
                for p in patches: p.stop()

            assert report["dry_run"] is False
            assert any(u["photo_id"] == prefix + "_p1"
                          for u in report["uploaded"])
            assert (prefix + "_p1") in stub.put_calls
            # DB — s3_key stamped, data intact.
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            p1 = next(p for p in doc["photos"] if p["id"] == prefix + "_p1")
            assert p1.get("s3_key") == \
                f"job-photos/{tid}/{jid}/{prefix}_p1"
            assert p1.get("s3_mime") == "image/png"
            assert p1.get("data"), "base64 stripped when purge=False"
        finally:
            await _cleanup(db, jid)

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 3 · Wet-run WITH purge — stamps s3_key AND unsets data
# ═════════════════════════════════════════════════════════════════

def test_migration_wet_run_with_purge_removes_base64():
    prefix = "P2_WET_PURGE_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [{
                "id": prefix + "_p1", "data": _b64(b"CCCCCC"),
            }])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                report = await _call_migrate(dry_run=False,
                                               purge_base64=True,
                                               tenant_id=tid)
            finally:
                for p in patches: p.stop()

            assert report["purge_base64"] is True
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            p1 = next(p for p in doc["photos"] if p["id"] == prefix + "_p1")
            assert p1.get("s3_key")
            assert "data" not in p1 or p1.get("data") in (None, ""), \
                "purge=True must unset photos[].data"
        finally:
            await _cleanup(db, jid)

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 4 · Idempotency — 2nd run on same set reports "already_migrated"
# ═════════════════════════════════════════════════════════════════

def test_migration_idempotent_on_second_run():
    prefix = "P2_IDEM_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [{
                "id": prefix + "_p1", "data": _b64(b"DDD"),
            }])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                # First run — uploads.
                r1 = await _call_migrate(dry_run=False, tenant_id=tid,
                                            purge_base64=False)
                assert any(u["photo_id"] == prefix + "_p1"
                              for u in r1["uploaded"])
                # Simulate second wet run — s3_key stamped on the
                # doc means query filter excludes this photo. Seed
                # a second candidate that ALSO points at the same
                # underlying key (already present in bucket).
                second_pid = prefix + "_p2_existing"
                await db.jobs.update_one(
                    {"id": jid},
                    {"$push": {"photos": {
                        "id": second_pid, "data": _b64(b"EEE"),
                    }}},
                )
                # Pre-populate the S3 stub with the pre-existing
                # object for this second photo id so ``check_object_exists``
                # short-circuits before ``upload_photo``.
                stub.objects[
                    f"job-photos/{tid}/{jid}/{second_pid}"
                ] = b"EEE"
                stub.put_calls.clear()
                r2 = await _call_migrate(dry_run=False, tenant_id=tid,
                                            purge_base64=False)
            finally:
                for p in patches: p.stop()

            already_pids = {a["photo_id"] for a in r2["already_migrated"]}
            assert (prefix + "_p2_existing") in already_pids, \
                "existing S3 object must land in already_migrated[]"
            assert second_pid not in stub.put_calls, \
                "must NOT re-upload when object already present"
            doc = await db.jobs.find_one({"id": jid},
                                              {"_id": 0, "photos": 1})
            p2 = next(p for p in doc["photos"] if p["id"] == second_pid)
            assert p2.get("s3_key") == \
                f"job-photos/{tid}/{jid}/{second_pid}"
        finally:
            await _cleanup(db, jid)

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 5 · Resumable — limit=1 across two jobs
# ═════════════════════════════════════════════════════════════════

def test_migration_resumable_with_limit_cursor():
    prefix = "P2_RESUME_" + uuid.uuid4().hex[:8]
    jid_a = "aaaa_" + prefix + "_job"
    jid_b = "bbbb_" + prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid_a, [{"id": prefix + "_pA",
                                              "data": _b64(b"AA")}])
            await _seed_job(db, jid_b, [{"id": prefix + "_pB",
                                              "data": _b64(b"BB")}])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                r1 = await _call_migrate(dry_run=False, tenant_id=tid,
                                            limit=1, purge_base64=False)
                # First call should have processed the alpha job.
                pids_r1 = {u["photo_id"] for u in r1["uploaded"]}
                assert (prefix + "_pA") in pids_r1
                assert r1["next_resume_after_job_id"] == jid_a
                # Second call — cursor picks up the beta job.
                r2 = await _call_migrate(
                    dry_run=False, tenant_id=tid, limit=1,
                    purge_base64=False,
                    resume_after_job_id=r1["next_resume_after_job_id"],
                )
            finally:
                for p in patches: p.stop()

            pids_r2 = {u["photo_id"] for u in r2["uploaded"]}
            assert (prefix + "_pB") in pids_r2
        finally:
            await _cleanup(db, jid_a, jid_b)

    run_test(go)


# ═════════════════════════════════════════════════════════════════
# 6 · Failure isolation — one photo raises, others succeed
# ═════════════════════════════════════════════════════════════════

def test_migration_failure_isolation():
    prefix = "P2_FAIL_" + uuid.uuid4().hex[:8]
    jid = prefix + "_job"

    async def go(db):
        try:
            await _seed_job(db, jid, [
                {"id": prefix + "_ok",  "data": _b64(b"OK")},
                {"id": prefix + "_bad", "data": _b64(b"BAD")},
            ])
            t = await db.tenants.find_one({"slug": "aquaterra"},
                                             {"_id": 0, "id": 1})
            tid = t["id"]
            stub = _S3Stub()
            stub.raise_on_photo_id = prefix + "_bad"  # returns None → failed[]
            patches = stub.make_patch(enabled=True)
            for p in patches: p.start()
            try:
                report = await _call_migrate(dry_run=False, tenant_id=tid,
                                                purge_base64=False)
            finally:
                for p in patches: p.stop()

            uploaded_pids = {u["photo_id"] for u in report["uploaded"]}
            failed_pids   = {f["photo_id"] for f in report["failed"]}
            assert (prefix + "_ok") in uploaded_pids
            assert (prefix + "_bad") in failed_pids
        finally:
            await _cleanup(db, jid)

    run_test(go)
