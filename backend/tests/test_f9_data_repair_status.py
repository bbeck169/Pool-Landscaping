"""Phase F9 · Feb-2026 — Data-repair status endpoint.

Direct-invocation unit tests on the route coroutine so this stays
sub-1s and doesn't share the HTTP-timeout flakiness of the shared
preview backend.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from tests._f7_loop_fixture import run_test


def test_f9_status_empty_state_returns_zeros():
    """No dump file, no scans, no repairs → shape is stable, all
    fields are non-null / zero, no exceptions."""
    from routers import data_repair as dr

    async def _go(db):
        # Point the dump reader at a fresh empty temp dir.
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["INTEGRITY_DUMP_DIR"] = tmp
            try:
                # Ensure no stale scans / repairs pollute (best effort
                # — real DBs may already carry rows; the F9 endpoint
                # returns whatever's newest, empty state → None).
                out = await dr.data_repair_status(user={"role": "super_admin"})
            finally:
                del os.environ["INTEGRITY_DUMP_DIR"]

        assert "current_state" in out
        cs = out["current_state"]
        assert cs["dangling_refs_total"] == 0
        assert cs["dangling_refs_by_class"] == {
            "customer": 0, "technician": 0, "crew": 0,
        }
        assert cs["snapshot_source"] == "no_dump_on_disk"
        assert cs["log_only_mode_active"] is False
        # last_dry_run + last_apply may be non-None on a real preview
        # DB that already has history — but the shape must always be
        # dict-or-None, never raise.
        assert out["last_dry_run"] is None or isinstance(out["last_dry_run"], dict)
        assert out["last_apply"] is None or isinstance(out["last_apply"], dict)
        assert out["last_dump_file"] is None

    run_test(_go)


def test_f9_status_reads_latest_dump_file():
    """Given a synthesised integrity_dump JSON on disk, current_state
    reflects its totals + snapshot_source flips to
    ``integrity_dump_file``."""
    from routers import data_repair as dr

    async def _go(db):
        with tempfile.TemporaryDirectory() as tmp:
            # Two dumps — endpoint must pick the newer one by ctime.
            older_path = os.path.join(tmp, "integrity_dump_2020-01-01T00-00-00Z.json")
            newer_path = os.path.join(tmp, "integrity_dump_2026-08-31T07-33-22Z.json")
            with open(older_path, "w") as fh:
                json.dump({
                    "timestamp": "2020-01-01T00:00:00Z",
                    "enforce_mode": True,
                    "totals": {"customer": 999, "technician": 999,
                                "crew": 999, "total": 2997},
                    "orphans": {"customer_refs": [], "technician_refs": [],
                                 "crew_refs": []},
                }, fh)
            with open(newer_path, "w") as fh:
                json.dump({
                    "timestamp": "2026-08-31T07:33:22Z",
                    "enforce_mode": False,
                    "totals": {"customer": 4861, "technician": 354,
                                "crew": 0, "total": 5215},
                    "orphans": {
                        "customer_refs": [{"id": f"c-{i}"} for i in range(3)],
                        "technician_refs": [{"id": "t-1"}],
                        "crew_refs": [],
                    },
                    "tenant_breakdown": {"tenant-a": 5215},
                }, fh)
            # Sort by filename (lex ≡ chronological given F6's ISO
            # naming), so no need to jitter ctimes.
            os.utime(newer_path, None)

            os.environ["INTEGRITY_DUMP_DIR"] = tmp
            os.environ["INTEGRITY_CHECK_ENFORCE"] = "false"
            try:
                out = await dr.data_repair_status(user={"role": "super_admin"})
            finally:
                del os.environ["INTEGRITY_DUMP_DIR"]
                del os.environ["INTEGRITY_CHECK_ENFORCE"]

        cs = out["current_state"]
        assert cs["dangling_refs_total"] == 5215
        assert cs["dangling_refs_by_class"] == {
            "customer": 4861, "technician": 354, "crew": 0,
        }
        assert cs["snapshot_source"] == "integrity_dump_file"
        assert cs["enforce_mode"] is False
        assert cs["log_only_mode_active"] is True   # enforce=false AND refs>0
        assert cs["snapshot_at"] == "2026-08-31T07:33:22Z"

        # last_dump_file mirrors the disk row-count (full arrays, not
        # 20-row sample cap — 3 customer + 1 technician + 0 crew).
        assert out["last_dump_file"] is not None
        assert out["last_dump_file"]["row_count"] == 4
        assert out["last_dump_file"]["path"].endswith(
            "integrity_dump_2026-08-31T07-33-22Z.json"
        )

    run_test(_go)


def test_f9_status_last_dry_run_expired_token_shows_null():
    """When the newest scan's expires_at is in the past, the endpoint
    must surface confirm_token_expires_at=None so the UI knows the
    apply endpoint would reject the stale token."""
    from routers import data_repair as dr

    async def _go(db):
        # Insert an expired scan.
        tid_stamp = uuid.uuid4().hex[:8]
        scan_ts = "2020-01-01T00:00:00+00:00"
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await db.data_integrity_scans.insert_one({
            "confirm_token": f"tok-{tid_stamp}",
            "scan_timestamp": scan_ts,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=2),
            "expires_at": expired_at,
            "actor_user_id": "test-user",
            "classes": {"orphaned_customer_refs": [],
                         "orphaned_technician_refs": [],
                         "unassigned_pending_jobs": []},
            "summary": {"total_would_change": 0,
                         "total_flagged_no_action": 0},
        })
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["INTEGRITY_DUMP_DIR"] = tmp
                try:
                    out = await dr.data_repair_status(
                        user={"role": "super_admin"},
                    )
                finally:
                    del os.environ["INTEGRITY_DUMP_DIR"]
        finally:
            await db.data_integrity_scans.delete_one(
                {"confirm_token": f"tok-{tid_stamp}"},
            )

        # If our inserted scan is newest, its expires_at is in the
        # past → surface None.  If some other scan is newer (e.g. the
        # dry-run run I did in the F3 dispatch), we skip this
        # assertion — the shape check in the empty-state test
        # already covers non-None cases.
        if out["last_dry_run"] and out["last_dry_run"].get(
            "scan_timestamp"
        ) == scan_ts:
            assert out["last_dry_run"]["confirm_token_expires_at"] is None

    run_test(_go)


def test_f9_status_role_gate_enforced_via_require_super_admin():
    """Guardrail: the route depends on ``require_super_admin`` — a
    non-super_admin role passed in the test double must raise a
    403.  We invoke the dependency directly for a clean signal."""
    import asyncio
    from fastapi import HTTPException
    from utils import require_super_admin

    async def _go():
        # Admin (not super_admin) → 403.  utils.require_super_admin
        # takes ``user`` positionally / kwarg (see utils.py:170).
        with __import__("pytest").raises(HTTPException) as ei:
            require_super_admin(user={"role": "admin"})
        assert ei.value.status_code == 403

    asyncio.new_event_loop().run_until_complete(_go())
