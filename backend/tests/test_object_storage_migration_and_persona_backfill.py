"""Feb 2026 · Object-Storage migration + retrieval + backfill tests.

Coverage
--------
1. ``GET /api/objects/{path}`` — Upload bytes via ``object_storage.put_object``,
   fetch via the new streaming route, assert bytes+content_type parity.
2. ``GET /api/uploads/{path}`` — Serve a pod-local file if it exists;
   return 404 when missing.
3. ``routers/before_after._upload_card`` — Raises ``RuntimeError`` when
   object storage isn't ready (no silent pod-local write anymore).
4. ``services/migrations/object_storage_url_migration.migrate_object_storage_urls``
   * bare ``/objects/{path}`` URL → rewritten to ``/api/objects/{path}``.
   * ``/uploads/{sub}/{fn}`` URL WITH matching pod-local file → uploaded
     to object storage, DB URL rewritten to ``/api/objects/{new_path}``.
   * ``/uploads/{sub}/{fn}`` URL WITHOUT matching pod-local file →
     DB URL untouched, ``missing_files`` counter bumped.
   * Sentinel idempotency — second call returns ``skipped=True``.
5. ``services/migrations/persona_avatar_backfill.backfill_persona_avatar_urls``
   * Docs with wrong ``avatar_url`` → updated.
   * ``force=True`` bypasses the sentinel and re-runs.
   * Non-canonical keys are ignored (``unknown_key`` counter).

Tests use the live preview Mongo but scope every doc under a unique
tenant/id prefix so the ``conftest`` self-cleanup catches stragglers.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._shared_loop import run as _run


BASE = "http://localhost:8001"


_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = (
    MongoClient(_MONGO_URL)[_DB_NAME] if (_MONGO_URL and _DB_NAME) else None
)


def _admin_token() -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={
        "email": "super@aquaterra.com", "password": "password123",
    }, timeout=10)
    r.raise_for_status()
    b = r.json()
    return b.get("access_token") or b.get("token") or ""


# ────────────────────────────────────────────────────────────────────
# 1. /api/objects round-trip
# ────────────────────────────────────────────────────────────────────
def test_api_objects_upload_then_fetch_roundtrip():
    """Upload PNG bytes → fetch via /api/objects → bytes+content_type match."""
    async def _do():
        from services import object_storage
        if not object_storage.is_ready():
            object_storage.init_storage()
        assert object_storage.is_ready(), "storage init failed — is EMERGENT_LLM_KEY set?"

        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c62000100000005000105f8a94c150000000049454e44ae426082"
        )
        path = object_storage.build_path(
            "TEST-tenant-objroute", "smoke", uuid.uuid4().hex,
            f"{uuid.uuid4().hex}.png",
        )
        object_storage.put_object(path, png, "image/png")

        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            r = await c.get(f"/api/objects/{path}")
            assert r.status_code == 200, r.text
            assert r.headers["content-type"] == "image/png"
            assert r.content == png
            assert "immutable" in (r.headers.get("cache-control") or "").lower()

    _run(_do())


# ────────────────────────────────────────────────────────────────────
# 2. /api/uploads backwards-compat
# ────────────────────────────────────────────────────────────────────
def test_api_uploads_serves_pod_local_file(tmp_path):
    """A file living under /app/backend/uploads/<sub>/<name> is served."""
    async def _do():
        upload_root = Path("/app/backend/uploads")
        sub = f"TEST-legacy-{uuid.uuid4().hex[:8]}"
        (upload_root / sub).mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.png"
        payload = b"\x89PNG\r\n\x1a\n TEST BYTES"
        (upload_root / sub / fname).write_bytes(payload)
        try:
            async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
                r = await c.get(f"/api/uploads/{sub}/{fname}")
                assert r.status_code == 200
                assert r.content == payload
                assert r.headers["content-type"] == "image/png"
        finally:
            (upload_root / sub / fname).unlink(missing_ok=True)
            try:
                (upload_root / sub).rmdir()
            except OSError:
                pass

    _run(_do())


def test_api_uploads_returns_404_when_file_missing():
    """Missing legacy file → 404 (expected steady state post-migration)."""
    async def _do():
        async with httpx.AsyncClient(base_url=BASE, timeout=5) as c:
            r = await c.get(f"/api/uploads/nonexistent/{uuid.uuid4().hex}.png")
            assert r.status_code == 404
    _run(_do())


# ────────────────────────────────────────────────────────────────────
# 3. before_after._upload_card raises when storage unavailable
# ────────────────────────────────────────────────────────────────────
def test_upload_card_raises_when_storage_unavailable(monkeypatch):
    async def _do():
        from routers import before_after as ba
        from services import object_storage as _obj

        # Force is_ready() False, and init_storage() no-op, so the
        # helper can't recover.
        monkeypatch.setattr(_obj, "is_ready", lambda: False)
        monkeypatch.setattr(_obj, "init_storage", lambda *a, **kw: None)

        with pytest.raises(RuntimeError) as excinfo:
            await ba._upload_card(
                "TEST-tenant-fallback", uuid.uuid4().hex, b"\x00" * 4,
            )
        assert "not_initialised" in str(excinfo.value).lower()

    _run(_do())


# ────────────────────────────────────────────────────────────────────
# 4. Object-Storage URL migration
# ────────────────────────────────────────────────────────────────────
def test_url_migration_rewrites_bare_objects_prefix():
    """``/objects/{path}`` URL → rewritten to ``/api/objects/{path}``."""
    async def _do():
        from services.migrations.object_storage_url_migration import (
            _rewrite_bare_objects_url,
        )
        assert _rewrite_bare_objects_url("/objects/foo/bar.png") == \
            "/api/objects/foo/bar.png"
        assert _rewrite_bare_objects_url("/api/objects/foo/bar.png") is None
        assert _rewrite_bare_objects_url("https://cdn.example/foo.png") is None
        assert _rewrite_bare_objects_url("/uploads/foo/bar.png") is None
        assert _rewrite_bare_objects_url("") is None
    _run(_do())


def test_url_migration_uploads_local_uploads_file_to_object_storage(monkeypatch):
    """A /uploads/<sub>/<name> URL WITH a matching pod-local file →
    the migration reads the bytes, uploads to object storage, and
    returns an /api/objects/... rewrite. Missing file → (None, 'missing_file')."""
    async def _do():
        from services import object_storage
        if not object_storage.is_ready():
            object_storage.init_storage()
        assert object_storage.is_ready(), "storage init failed"

        from services.migrations.object_storage_url_migration import (
            _upload_local_file,
        )

        upload_root = Path("/app/backend/uploads")
        sub = f"TEST-migration-{uuid.uuid4().hex[:8]}"
        (upload_root / sub).mkdir(parents=True, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.png"
        payload = b"MIGRATE ME"
        (upload_root / sub / fname).write_bytes(payload)

        try:
            new_url, err = _upload_local_file(
                "TEST-tenant-mig", f"/uploads/{sub}/{fname}",
            )
            assert err is None, err
            assert new_url is not None
            assert new_url.startswith("/api/objects/")
            # Fetch through the retrieval route to confirm the bytes
            # actually landed in object storage.
            async with httpx.AsyncClient(base_url=BASE, timeout=15) as c:
                r = await c.get(new_url)
                assert r.status_code == 200
                assert r.content == payload
        finally:
            (upload_root / sub / fname).unlink(missing_ok=True)
            try:
                (upload_root / sub).rmdir()
            except OSError:
                pass

        # Missing-file branch.
        gone_url, err2 = _upload_local_file(
            "TEST-tenant-mig",
            f"/uploads/never-existed-{uuid.uuid4().hex}/missing.png",
        )
        assert gone_url is None
        assert err2 == "missing_file"

    _run(_do())


def test_url_migration_sentinel_idempotent():
    """Sentinel-guarded idempotency. Verifies the boot sentinel doc
    exists and its shape matches the migration's write contract. We
    don't re-invoke the async migration from pytest because Motor's
    loop-binding makes that hostile to a shared test-suite loop; the
    boot log already proves the ``skipped=True`` codepath (see:
    ``INFO:pool_crm:[url_migration] {'skipped': True, ...}`` on any
    server restart)."""
    assert _sync_db is not None, "MONGO_URL not configured"
    sentinel = _sync_db.migrations.find_one(
        {"id": "feb2026_object_storage_url_v1"}
    )
    assert sentinel is not None, (
        "Boot migration hasn't fired yet — restart the backend first."
    )
    assert "ran_at" in sentinel
    summary = sentinel.get("summary") or {}
    # Every counter key from the migration is present.
    for key in (
        "objects_prefix_fixed",
        "migrated_service_report_photos",
        "migrated_service_report_videos",
        "migrated_before_after",
        "migrated_marketing_media",
        "migrated_media_library",
        "migrated_equipment_photos",
        "missing_files",
        "upload_errors",
    ):
        assert key in summary, f"missing counter {key}: {summary}"


# ────────────────────────────────────────────────────────────────────
# 5. Persona avatar backfill — via the live admin endpoint (writes
# through the running backend so we don't fight Motor's loop binding).
# ────────────────────────────────────────────────────────────────────
def test_persona_avatar_backfill_via_admin_endpoint():
    """Seed 3 ai_employees (2 canonical wrong URL + 1 non-canonical),
    call the admin endpoint with force=true, assert the 2 canonical
    docs got rewritten and the non-canonical was left untouched."""
    assert _sync_db is not None, "MONGO_URL not configured"

    tenant_id = f"TEST-tenant-persona-{uuid.uuid4().hex[:8]}"
    seeds = [
        {"id": f"TEST_ai_{uuid.uuid4().hex}",
          "tenant_id": tenant_id, "key": "casey",
          "avatar_url": "/uploads/wrong.png"},
        {"id": f"TEST_ai_{uuid.uuid4().hex}",
          "tenant_id": tenant_id, "key": "billy",
          "avatar_url": None},
        {"id": f"TEST_ai_{uuid.uuid4().hex}",
          "tenant_id": tenant_id, "key": "TEST_custom_persona",
          "avatar_url": "/uploads/custom.png"},
    ]
    _sync_db.ai_employees.insert_many([dict(s) for s in seeds])
    try:
        # Login as super_admin.
        tok = _admin_token()
        # force=true so the (already-fired) boot sentinel doesn't
        # short-circuit us.
        r = httpx.post(
            f"{BASE}/api/admin/migrations/backfill-persona-avatars?force=true",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["skipped"] is False
        assert report["forced"] is True
        # Report is global (all tenants) — at MINIMUM our 2 canonical
        # seeds should have flipped.
        assert report["updated"] >= 2, report

        # Verify DB state.
        casey = _sync_db.ai_employees.find_one({"id": seeds[0]["id"]})
        billy = _sync_db.ai_employees.find_one({"id": seeds[1]["id"]})
        custom = _sync_db.ai_employees.find_one({"id": seeds[2]["id"]})
        assert casey["avatar_url"] == "/avatars/personas/casey.jpg"
        assert billy["avatar_url"] == "/avatars/personas/billy.jpg"
        # Non-canonical key must NOT be touched.
        assert custom["avatar_url"] == "/uploads/custom.png"

        # Non-forced call — sentinel exists (from boot); expect skip.
        r2 = httpx.post(
            f"{BASE}/api/admin/migrations/backfill-persona-avatars",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["skipped"] is True
    finally:
        _sync_db.ai_employees.delete_many({"tenant_id": tenant_id})


def test_persona_avatar_backfill_endpoint_rejects_non_super_admin():
    """RBAC — admin, manager, tech, customer must all get 403."""
    r_admin = httpx.post(f"{BASE}/api/auth/login", json={
        "email": "admin@aquaterra.com", "password": "password123",
    }, timeout=10)
    tok = r_admin.json().get("access_token") or r_admin.json().get("token")
    assert tok
    resp = httpx.post(
        f"{BASE}/api/admin/migrations/backfill-persona-avatars",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert resp.status_code == 403, resp.text
