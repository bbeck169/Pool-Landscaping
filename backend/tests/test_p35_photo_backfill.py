"""Phase P35 · Feb-2026 — S3 photo fallback + backfill migration tests.

Covers the P35 deliverables:

* Renderer fallback ladder in ``routers/jobs.py::public_job_photo``:
    1. S3 hit (redirect).
    2. S3 miss + base64 present → decoded response.
    3. Both missing → structured 404 with ``code=photo_not_found``.
    4. ``[p35] photo fallback base64`` WARN on the base64 fallback branch.

* Migration script ``scripts/p35_photo_backfill``:
    5-6. Pass A dry-run + execute behaviour.
    7-8. Pass B dry-run + execute behaviour.
    9. Idempotent re-run (zero mutations on the second execute).
    10. Tenant filter scopes the mutation set correctly.

S3 is faked at the ``services.aws_s3.photos`` boundary via a tiny
in-memory dict — every helper the migration + renderer touch is
monkeypatched. This avoids requiring ``moto`` and keeps the tests
fully hermetic. Note: the F7 loop fixture rebinds ``config.db``
for each test, so ``scripts.p35_photo_backfill.db`` is refreshed
per test (see ``_REBOUND_MODULES``).
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


# ─────────────────────────────────────────────────────────────────
# In-memory S3 fake — swapped in for each test via a fixture.
# ─────────────────────────────────────────────────────────────────
class _FakeS3:
    """A minimal, key-addressable byte store with per-op counters."""

    def __init__(self) -> None:
        self.store: Dict[str, tuple[bytes, str]] = {}  # key -> (bytes, mime)
        self.put_calls: list = []
        self.get_calls: list = []
        self.head_calls: list = []
        self.delete_calls: list = []
        self.force_put_fail: bool = False

    def put(self, key: str, blob: bytes, mime: str):
        self.put_calls.append(key)
        if self.force_put_fail:
            return None
        self.store[key] = (blob, mime)
        return key

    def head(self, key: str) -> bool:
        self.head_calls.append(key)
        return key in self.store

    def get(self, key: str):
        self.get_calls.append(key)
        if key not in self.store:
            return None
        return self.store[key][0]

    def delete(self, key: str) -> bool:
        self.delete_calls.append(key)
        return self.store.pop(key, None) is not None


@pytest.fixture
def fake_s3(monkeypatch):
    fake = _FakeS3()

    def _upload_blob_at_key(key, blob, mime):
        return fake.put(key, blob, mime)

    def _read_object(key):
        return fake.get(key)

    def _check_object_exists(key):
        return fake.head(key)

    def _delete_photo(key):
        return fake.delete(key)

    def _generate_signed_url(key, ttl_seconds=None):
        return f"https://fake-s3.example/{key}?sig=fake"

    def _build_key(tenant_id, job_id, photo_id, *, prefix=None):
        p = prefix or "Photos/"
        if not p.endswith("/"):
            p = p + "/"
        return f"{p}{tenant_id}/{job_id}/{photo_id}"

    def _upload_photo(tenant_id, job_id, photo_id, blob, mime):
        key = _build_key(tenant_id, job_id, photo_id)
        return fake.put(key, blob, mime)

    def _cfg():
        return {"prefix": "Photos/", "bucket": "fake-bucket"}

    import services.aws_s3.photos as _s3mod
    monkeypatch.setattr(_s3mod, "upload_blob_at_key",
                          _upload_blob_at_key)
    monkeypatch.setattr(_s3mod, "read_object", _read_object)
    monkeypatch.setattr(_s3mod, "check_object_exists",
                          _check_object_exists)
    monkeypatch.setattr(_s3mod, "delete_photo", _delete_photo)
    monkeypatch.setattr(_s3mod, "generate_signed_url",
                          _generate_signed_url)
    monkeypatch.setattr(_s3mod, "build_key", _build_key)
    monkeypatch.setattr(_s3mod, "upload_photo", _upload_photo)
    monkeypatch.setattr(_s3mod, "_cfg", _cfg)
    return fake


# ─────────────────────────────────────────────────────────────────
# Renderer tests — ``public_job_photo`` fallback ladder
# ─────────────────────────────────────────────────────────────────
_PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
    b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx"
    b"\x9cc\xf8\xcf\xc0P\x0f\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb1"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _mk_data_url(blob: bytes = _PNG_1PX,
                    mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode()}"


async def _seed_job_with_photo(db, *, tid, jid, pid, s3_key=None,
                                  data=None, s3_mime="image/png"):
    doc = {"id": jid, "tenant_id": tid,
            "photos": [{
                "id": pid,
                "s3_key": s3_key,
                "s3_mime": s3_mime,
                "data": data,
            }]}
    await db.jobs.replace_one({"id": jid}, doc, upsert=True)


def test_renderer_s3_hit_returns_bytes(fake_s3):
    from routers.jobs import public_job_photo

    async def _go(db):
        tid = f"p35-{uuid.uuid4().hex[:6]}"
        jid = f"p35job-{uuid.uuid4().hex[:6]}"
        pid = f"p35pho-{uuid.uuid4().hex[:6]}"
        s3_key = f"Photos/{tid}/{jid}/{pid}"
        # Seed the fake S3 store so HEAD returns True.
        fake_s3.store[s3_key] = (_PNG_1PX, "image/png")
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=s3_key, data=None)
        try:
            resp = await public_job_photo(jid, pid)
            # S3 hit → RedirectResponse (302).
            assert resp.status_code == 302
            assert "fake-s3.example" in resp.headers["location"]
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_renderer_s3_miss_falls_back_to_base64(fake_s3):
    from routers.jobs import public_job_photo
    from fastapi.responses import Response

    async def _go(db):
        tid = f"p35-{uuid.uuid4().hex[:6]}"
        jid = f"p35job-{uuid.uuid4().hex[:6]}"
        pid = f"p35pho-{uuid.uuid4().hex[:6]}"
        # s3_key set BUT the fake S3 is empty → HEAD returns False.
        s3_key = f"Photos/{tid}/{jid}/{pid}"
        await _seed_job_with_photo(
            db, tid=tid, jid=jid, pid=pid,
            s3_key=s3_key, data=_mk_data_url(),
        )
        try:
            resp = await public_job_photo(jid, pid)
            # Base64 fallback → Response with decoded PNG bytes.
            assert isinstance(resp, Response)
            assert resp.status_code == 200
            assert resp.media_type == "image/png"
            assert resp.body == _PNG_1PX
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_renderer_no_s3_no_base64_returns_404(fake_s3):
    from routers.jobs import public_job_photo

    async def _go(db):
        tid = f"p35-{uuid.uuid4().hex[:6]}"
        jid = f"p35job-{uuid.uuid4().hex[:6]}"
        pid = f"p35pho-{uuid.uuid4().hex[:6]}"
        # Both empty — neither s3_key nor data.
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=None, data=None)
        try:
            with pytest.raises(HTTPException) as ei:
                await public_job_photo(jid, pid)
            assert ei.value.status_code == 404
            assert isinstance(ei.value.detail, dict)
            assert ei.value.detail.get("code") == "photo_not_found"
            assert ei.value.detail.get("photo_id") == pid
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_renderer_logs_warn_on_base64_fallback(fake_s3, caplog):
    from routers.jobs import public_job_photo

    async def _go(db):
        tid = f"p35-{uuid.uuid4().hex[:6]}"
        jid = f"p35job-{uuid.uuid4().hex[:6]}"
        pid = f"p35pho-{uuid.uuid4().hex[:6]}"
        s3_key = f"Photos/{tid}/{jid}/{pid}"
        await _seed_job_with_photo(
            db, tid=tid, jid=jid, pid=pid,
            s3_key=s3_key, data=_mk_data_url(),
        )
        try:
            with caplog.at_level(logging.WARNING, logger="pool_crm"):
                await public_job_photo(jid, pid)
            joined = " · ".join(r.getMessage() for r in caplog.records)
            assert "[p35] photo fallback base64" in joined
            assert f"photo_id={pid}" in joined
            assert f"job_id={jid}" in joined
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


# ─────────────────────────────────────────────────────────────────
# Migration tests — pass A + pass B behaviour
# ─────────────────────────────────────────────────────────────────
def _make_argv(*, execute=False, which_pass="both",
                  tenant=None, limit=None, batch=100):
    argv = []
    if execute:
        argv.append("--execute")
    argv.extend(["--pass", which_pass, "--batch", str(batch)])
    if tenant:
        argv.extend(["--tenant", tenant])
    if limit is not None:
        argv.extend(["--limit", str(limit)])
    return argv


def test_migration_pass_a_dry_run_no_writes(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        old_key = f"job-photos/{tid}/{jid}/{pid}"
        fake_s3.store[old_key] = (_PNG_1PX, "image/png")
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=old_key,
                                       data=_mk_data_url())
        try:
            await _main_async(_make_argv(
                execute=False, which_pass="a", tenant=tid,
            ))
            # No S3 mutations.
            assert fake_s3.put_calls == []
            assert fake_s3.delete_calls == []
            # DB unchanged.
            row = await db.jobs.find_one({"id": jid}, {"_id": 0})
            assert row["photos"][0]["s3_key"] == old_key
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_pass_a_execute_reprefixes_key(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        old_key = f"job-photos/{tid}/{jid}/{pid}"
        new_key = f"Photos/{tid}/{jid}/{pid}"
        fake_s3.store[old_key] = (_PNG_1PX, "image/png")
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=old_key, s3_mime="image/png",
                                       data=_mk_data_url())
        try:
            await _main_async(_make_argv(
                execute=True, which_pass="a", tenant=tid,
            ))
            # New S3 key present, old S3 key deleted.
            assert new_key in fake_s3.store
            assert old_key not in fake_s3.store
            # DB row flipped.
            row = await db.jobs.find_one({"id": jid}, {"_id": 0})
            assert row["photos"][0]["s3_key"] == new_key
            # ``data`` preserved as safety net.
            assert row["photos"][0]["data"]
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_pass_a_repairs_from_base64_when_old_s3_orphaned(fake_s3):
    """When the old S3 key is dangling (``NoSuchKey``) but the row
    still carries a valid ``data`` URL, Pass A must repair from base64
    into the canonical key rather than skipping the row. This is the
    real-world state we found on prod DB — 6 dangling s3_keys, all
    with valid data URLs."""
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        old_key = f"job-photos/{tid}/{jid}/{pid}"
        new_key = f"Photos/{tid}/{jid}/{pid}"
        # Intentionally DO NOT seed ``fake_s3.store[old_key]`` — the
        # old key is orphaned in S3.
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=old_key, s3_mime="image/png",
                                       data=_mk_data_url())
        try:
            await _main_async(_make_argv(
                execute=True, which_pass="a", tenant=tid,
            ))
            # New S3 key present — payload came from decoding data URL.
            assert new_key in fake_s3.store
            blob, mime = fake_s3.store[new_key]
            assert blob == _PNG_1PX
            assert mime == "image/png"
            # DB row flipped to canonical key.
            row = await db.jobs.find_one({"id": jid}, {"_id": 0})
            assert row["photos"][0]["s3_key"] == new_key
            # ``data`` preserved.
            assert row["photos"][0]["data"]
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_pass_b_dry_run_no_writes(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        # base64-only: has ``data`` but NO ``s3_key``.
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=None, data=_mk_data_url())
        try:
            await _main_async(_make_argv(
                execute=False, which_pass="b", tenant=tid,
            ))
            assert fake_s3.put_calls == []
            row = await db.jobs.find_one({"id": jid}, {"_id": 0})
            # s3_key must remain None (dry-run).
            assert row["photos"][0].get("s3_key") in (None, "")
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_pass_b_execute_uploads_and_updates(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        expected_new_key = f"Photos/{tid}/{jid}/{pid}"
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=None, data=_mk_data_url())
        try:
            await _main_async(_make_argv(
                execute=True, which_pass="b", tenant=tid,
            ))
            # S3 PUT happened at the canonical key.
            assert expected_new_key in fake_s3.store
            # DB stamped with s3_key + s3_mime; data PRESERVED.
            row = await db.jobs.find_one({"id": jid}, {"_id": 0})
            p = row["photos"][0]
            assert p["s3_key"] == expected_new_key
            assert p["s3_mime"] == "image/png"
            assert p["data"], "data field must be preserved per P35 policy"
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_idempotent_second_run_zero_mutations(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid = f"p35tid-{uuid.uuid4().hex[:6]}"
        jid = f"p35jid-{uuid.uuid4().hex[:6]}"
        pid = f"p35pid-{uuid.uuid4().hex[:6]}"
        old_key = f"job-photos/{tid}/{jid}/{pid}"
        fake_s3.store[old_key] = (_PNG_1PX, "image/png")
        await _seed_job_with_photo(db, tid=tid, jid=jid, pid=pid,
                                       s3_key=old_key, s3_mime="image/png",
                                       data=_mk_data_url())
        try:
            # Run 1 — mutates.
            await _main_async(_make_argv(
                execute=True, which_pass="both", tenant=tid,
            ))
            put_calls_after_run1 = list(fake_s3.put_calls)
            delete_calls_after_run1 = list(fake_s3.delete_calls)
            # Run 2 — must be a no-op.
            await _main_async(_make_argv(
                execute=True, which_pass="both", tenant=tid,
            ))
            assert fake_s3.put_calls == put_calls_after_run1, (
                "second run must not issue new PUTs"
            )
            assert fake_s3.delete_calls == delete_calls_after_run1, (
                "second run must not issue new deletes"
            )
        finally:
            await db.jobs.delete_one({"id": jid})

    run_test(_go)


def test_migration_tenant_filter_scopes_correctly(fake_s3):
    from scripts.p35_photo_backfill import _main_async

    async def _go(db):
        tid_a = f"p35A-{uuid.uuid4().hex[:6]}"
        tid_b = f"p35B-{uuid.uuid4().hex[:6]}"
        jid_a = f"p35jidA-{uuid.uuid4().hex[:6]}"
        jid_b = f"p35jidB-{uuid.uuid4().hex[:6]}"
        pid_a = f"p35pidA-{uuid.uuid4().hex[:6]}"
        pid_b = f"p35pidB-{uuid.uuid4().hex[:6]}"
        old_key_a = f"job-photos/{tid_a}/{jid_a}/{pid_a}"
        old_key_b = f"job-photos/{tid_b}/{jid_b}/{pid_b}"
        fake_s3.store[old_key_a] = (_PNG_1PX, "image/png")
        fake_s3.store[old_key_b] = (_PNG_1PX, "image/png")
        await _seed_job_with_photo(db, tid=tid_a, jid=jid_a, pid=pid_a,
                                       s3_key=old_key_a, s3_mime="image/png")
        await _seed_job_with_photo(db, tid=tid_b, jid=jid_b, pid=pid_b,
                                       s3_key=old_key_b, s3_mime="image/png")
        try:
            await _main_async(_make_argv(
                execute=True, which_pass="a", tenant=tid_a,
            ))
            # Tenant A migrated.
            row_a = await db.jobs.find_one({"id": jid_a}, {"_id": 0})
            assert row_a["photos"][0]["s3_key"].startswith("Photos/")
            assert row_a["photos"][0]["s3_key"] == (
                f"Photos/{tid_a}/{jid_a}/{pid_a}"
            )
            # Tenant B untouched.
            row_b = await db.jobs.find_one({"id": jid_b}, {"_id": 0})
            assert row_b["photos"][0]["s3_key"] == old_key_b
        finally:
            await db.jobs.delete_one({"id": jid_a})
            await db.jobs.delete_one({"id": jid_b})

    run_test(_go)
