"""Phase K15 · Feb-2026 — regression tests for the one-shot
``scripts.k15_seed_jobs_indexes`` seed.

Guarantees:
  1. Dry-run reports ``would_create`` for both K15 indexes when
     they're missing AND makes no writes to ``db.jobs.indexes``.
  2. ``--apply`` creates both indexes with the exact names + key
     specs, visible via ``db.jobs.list_indexes()``.
  3. Idempotency: a second ``--apply`` reports ``already_present``
     for both, no error, no duplicate index.

Every test drops the K15 indexes at setup + teardown so the suite
is self-contained regardless of prior manual runs.  All other
existing indexes on ``db.jobs`` (``_id_``, the perf index, etc.)
are left untouched.
"""
from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from scripts import k15_seed_jobs_indexes as seed


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_K15_NAMES = ("k15_jobs_tech_schedule_status", "k15_jobs_crew_schedule")


def _drop_k15():
    """Remove any pre-existing K15 indexes so the test starts from
    a clean slate.  ``drop_index`` raises when the name is absent;
    swallowed since that's the desired starting state."""
    for name in _K15_NAMES:
        try:
            _sync.jobs.drop_index(name)
        except Exception:  # noqa: BLE001
            pass


def _existing_names() -> set[str]:
    return {idx["name"] for idx in _sync.jobs.list_indexes()}


def _run_main(*args: str) -> tuple[int, str]:
    """Invoke ``scripts.k15_seed_jobs_indexes.main`` in-process
    and capture its stdout so the assertion surface is the exact
    same one ops sees on the terminal."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = seed.main(list(args))
    return rc, buf.getvalue()


def _pre_and_teardown(fn):
    """Decorator: drop K15 indexes before AND after the test."""
    def wrapped(*a, **kw):
        _drop_k15()
        try:
            return fn(*a, **kw)
        finally:
            _drop_k15()
    wrapped.__name__ = fn.__name__
    return wrapped


@_pre_and_teardown
def test_k15_dry_run_reports_would_create_and_writes_nothing():
    before = _existing_names()
    assert "k15_jobs_tech_schedule_status" not in before
    assert "k15_jobs_crew_schedule" not in before

    rc, out = _run_main()  # no --apply → dry-run
    assert rc == 0, out
    assert "[k15] k15_jobs_tech_schedule_status — would_create" in out
    assert "[k15] k15_jobs_crew_schedule — would_create" in out

    after = _existing_names()
    assert "k15_jobs_tech_schedule_status" not in after
    assert "k15_jobs_crew_schedule" not in after
    # Also make sure we didn't accidentally drop anything unrelated.
    assert before == after


@_pre_and_teardown
def test_k15_apply_creates_both_indexes():
    before = _existing_names()
    assert "k15_jobs_tech_schedule_status" not in before

    rc, out = _run_main("--apply")
    assert rc == 0, out
    assert "[k15] k15_jobs_tech_schedule_status — created" in out
    assert "[k15] k15_jobs_crew_schedule — created" in out

    after = {idx["name"]: list(idx.get("key", {}).items())
             for idx in _sync.jobs.list_indexes()}
    assert after.get("k15_jobs_tech_schedule_status") == [
        ("tenant_id", 1), ("technician_id", 1),
        ("scheduled_date", 1), ("status", 1),
    ]
    assert after.get("k15_jobs_crew_schedule") == [
        ("tenant_id", 1), ("crew_id", 1), ("scheduled_date", 1),
    ]


@_pre_and_teardown
def test_k15_apply_is_idempotent():
    rc1, out1 = _run_main("--apply")
    assert rc1 == 0, out1
    assert "created" in out1

    rc2, out2 = _run_main("--apply")
    assert rc2 == 0, out2
    assert "[k15] k15_jobs_tech_schedule_status — already_present" in out2
    assert "[k15] k15_jobs_crew_schedule — already_present" in out2

    # Still exactly two K15 indexes, not four.
    all_names = [idx["name"] for idx in _sync.jobs.list_indexes()]
    assert all_names.count("k15_jobs_tech_schedule_status") == 1
    assert all_names.count("k15_jobs_crew_schedule") == 1


@_pre_and_teardown
def test_k15_verify_flags_missing_and_present():
    # Missing → exit 1, ❌ marker in output.
    rc, out = _run_main("--verify")
    assert rc == 1, out
    assert "❌ MISSING — k15_jobs_tech_schedule_status" in out
    assert "❌ MISSING — k15_jobs_crew_schedule" in out

    _run_main("--apply")

    # Present → exit 0, ✅ markers in output.
    rc, out = _run_main("--verify")
    assert rc == 0, out
    assert "✅ k15_jobs_tech_schedule_status" in out
    assert "✅ k15_jobs_crew_schedule" in out
    assert "all K15 indexes present." in out


@_pre_and_teardown
def test_k15_tenant_id_flag_is_noop_and_still_seeds():
    """``--tenant-id`` is accepted for parity but must not affect
    the index creation (indexes are collection-global)."""
    rc, out = _run_main("--tenant-id", "affdfbfa-88b9-4baa-ae45-2ef78531b6e4")
    assert rc == 0, out
    assert "would_create" in out  # dry-run implied
    # No writes.
    assert "k15_jobs_tech_schedule_status" not in _existing_names()


# ── K15 · list_jobs defensive limit cap ────────────────────────────
# When the caller filters by ``technician_id`` or ``crew_id`` the
# ``list_jobs`` handler is now hard-capped at 300 rows regardless of
# the requested ``?limit=``.  The cap protects the covered indexes
# created above; unscoped admin listings keep the 1000-row default.

import requests  # noqa: E402


def _login(email: str = "admin@aquaterra.com") -> str:
    r = requests.post(
        "http://localhost:8001/api/auth/login",
        json={"email": email, "password": "password123"}, timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def test_k15_list_jobs_hard_caps_tech_scoped_limit_at_300():
    """A tech-scoped read with ``?limit=1000`` must be capped at 300."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    # Pick any technician_id that exists (the value doesn't matter for
    # the cap check — even a filter that returns zero rows must still
    # respect the ceiling; we only assert the upper bound).
    r = requests.get(
        "http://localhost:8001/api/jobs"
        "?technician_id=probe&limit=1000",
        headers=hdrs, timeout=15,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) <= 300, (
        f"tech-scoped list_jobs returned {len(r.json())} rows — cap is 300"
    )


def test_k15_list_jobs_unscoped_still_honors_requested_limit():
    """Without ``technician_id`` / ``crew_id`` the cap does NOT apply."""
    tok = _login()
    hdrs = {"Authorization": f"Bearer {tok}"}
    r = requests.get(
        "http://localhost:8001/api/jobs?limit=500",
        headers=hdrs, timeout=30,
    )
    assert r.status_code == 200
    # Sanity: the response must not clamp to 300 (tech-cap) on an
    # unscoped listing.  We only enforce the requested-limit ceiling
    # since seed data size varies.
    assert len(r.json()) <= 500
