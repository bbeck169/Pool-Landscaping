"""Phase 13 · W2 · Session-collection compound-index migration."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from pathlib import Path

from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import create_session_indexes as _script  # noqa: E402


def _run(coro):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    return _LOOP.run_until_complete(coro)


def _has_index(coll: str, name: str) -> bool:
    return any(i["name"] == name for i in _sync[coll].list_indexes())


# ── 1. Dry-run does not mutate ────────────────────────────────────
def test_dry_run_does_not_create_indexes():
    coll_name = f"p13_dry_{uuid.uuid4().hex[:6]}"
    _sync[coll_name].insert_one(
        {"tenant_id": "t1", "created_at": "2026-08-01T00:00:00+00:00"})
    _script.SPECS.append((coll_name, "created_at", ()))
    try:
        stats = _run(_script.run(dry_run=True))
        assert stats["created"] == 0
        assert not _has_index(coll_name, "tenant_created_at_desc")
    finally:
        _script.SPECS.pop()
        _sync[coll_name].drop()


# ── 2. Real run creates, second is a no-op ────────────────────────
def test_real_run_creates_and_second_run_is_noop():
    coll_name = f"p13_real_{uuid.uuid4().hex[:6]}"
    _sync[coll_name].insert_one(
        {"tenant_id": "t1", "created_at": "2026-08-01T00:00:00+00:00"})
    _script.SPECS.append((coll_name, "created_at", ()))
    try:
        s1 = _run(_script.run(dry_run=False))
        assert _has_index(coll_name, "tenant_created_at_desc"), s1
        s2 = _run(_script.run(dry_run=False))
        # In the second run, our added collection must fall into
        # already_exists (not created).
        assert s2["created"] == 0
        # (Other pre-existing collections are also already_exists — we
        # can't easily assert the exact count, but 0 new creates is the
        # meaningful signal.)
    finally:
        _script.SPECS.pop()
        _sync[coll_name].drop()


# ── 3. Field-substitution: primary missing → picks fallback ───────
def test_picks_fallback_when_primary_field_missing():
    coll_name = f"p13_fall_{uuid.uuid4().hex[:6]}"
    _sync[coll_name].insert_one(
        {"tenant_id": "t1", "created_at": "2026-08-01T00:00:00+00:00"})
    _script.SPECS.append((coll_name, "nonexistent_ts", ("created_at",)))
    try:
        stats = _run(_script.run(dry_run=False))
        assert stats["substituted_field"] >= 1
        assert _has_index(coll_name, "tenant_created_at_desc")
    finally:
        _script.SPECS.pop()
        _sync[coll_name].drop()


# ── 4. Empty-collection case: skipped without crashing ────────────
def test_empty_collection_skipped_cleanly():
    coll_name = f"p13_empty_{uuid.uuid4().hex[:6]}"
    # Do NOT create the collection.
    _script.SPECS.append((coll_name, "created_at", ()))
    try:
        stats = _run(_script.run(dry_run=False))
        assert stats["skipped_empty_collection"] >= 1
    finally:
        _script.SPECS.pop()


# ── 5. Subprocess dry-run smoke — exits 0 and prints summary ──────
def test_script_dry_run_exits_zero():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.create_session_indexes", "--dry-run"],
        capture_output=True, text=True, timeout=60,
        cwd=str(Path(__file__).resolve().parents[1]))
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN SUMMARY" in r.stdout


# ── 6. Boot hook: does not raise ──────────────────────────────────
def test_ensure_on_boot_never_raises():
    _run(_script.ensure_on_boot())
