"""Phase K21 · Feb-2026 — regression tests for the K21 perf-index seed.

Mirrors the K15 test shape:
  1. Dry-run reports ``would_create`` for every K21 index that's
     missing and does NOT touch Mongo.
  2. ``--apply`` creates every K21 index on its collection.
  3. Second ``--apply`` is idempotent — every row reports
     ``already_present``.
  4. ``--verify`` exits 1 with per-index MISSING lines when any are
     absent; exits 0 with an ``all K21 indexes present.`` footer
     once every K21 index exists.

Every test drops the K21 indexes at setup + teardown so the suite
is self-contained regardless of prior manual runs.  Non-K21
indexes on each collection stay untouched.
"""
from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from scripts import k21_seed_perf_indexes as seed


load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _drop_k21():
    """Remove any pre-existing K21 indexes so the test starts from
    a clean slate."""
    for coll, name, _ in seed._K21_INDEXES:
        try:
            _sync[coll].drop_index(name)
        except Exception:  # noqa: BLE001
            pass


def _existing(coll: str) -> set[str]:
    return {idx["name"] for idx in _sync[coll].list_indexes()}


def _run_main(*args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = seed.main(list(args))
    return rc, buf.getvalue()


def _pre_and_teardown(fn):
    def wrapped(*a, **kw):
        _drop_k21()
        try:
            return fn(*a, **kw)
        finally:
            _drop_k21()
    wrapped.__name__ = fn.__name__
    return wrapped


@_pre_and_teardown
def test_k21_dry_run_reports_would_create_and_writes_nothing():
    baseline = {coll: _existing(coll) for coll, _, _ in seed._K21_INDEXES}
    rc, out = _run_main()  # no --apply → dry-run
    assert rc == 0, out
    for coll, name, _ in seed._K21_INDEXES:
        assert f"[k21] {coll}.{name} — would_create" in out
    # No writes.
    for coll, name, _ in seed._K21_INDEXES:
        assert name not in _existing(coll)
    # No side-effect drops either.
    for coll, before in baseline.items():
        assert before == _existing(coll)


@_pre_and_teardown
def test_k21_apply_creates_every_index():
    rc, out = _run_main("--apply")
    assert rc == 0, out
    for coll, name, keys in seed._K21_INDEXES:
        assert f"[k21] {coll}.{name} — created" in out
        after = {idx["name"]: list(idx.get("key", {}).items())
                 for idx in _sync[coll].list_indexes()}
        assert after.get(name) == keys, (
            f"{coll}.{name} key mismatch: expected {keys}, got "
            f"{after.get(name)!r}"
        )


@_pre_and_teardown
def test_k21_apply_is_idempotent():
    rc1, out1 = _run_main("--apply")
    assert rc1 == 0, out1

    rc2, out2 = _run_main("--apply")
    assert rc2 == 0, out2
    for coll, name, _ in seed._K21_INDEXES:
        assert f"[k21] {coll}.{name} — already_present" in out2
        # No duplicates.
        names = [i["name"] for i in _sync[coll].list_indexes()]
        assert names.count(name) == 1


@_pre_and_teardown
def test_k21_verify_flags_missing_then_present():
    rc, out = _run_main("--verify")
    assert rc == 1, out
    for coll, name, _ in seed._K21_INDEXES:
        assert f"MISSING — {coll}.{name}" in out

    _run_main("--apply")

    rc, out = _run_main("--verify")
    assert rc == 0, out
    assert "all K21 indexes present." in out
    for coll, name, _ in seed._K21_INDEXES:
        assert f"[  OK   ] {coll}.{name}" in out


@_pre_and_teardown
def test_k21_tenant_id_flag_is_noop_and_still_dry_runs():
    rc, out = _run_main("--tenant-id", "affdfbfa-88b9-4baa-ae45-2ef78531b6e4")
    assert rc == 0, out
    assert "would_create" in out
    for coll, name, _ in seed._K21_INDEXES:
        assert name not in _existing(coll)


@_pre_and_teardown
def test_k21_reports_skipped_covered_indexes_on_every_run():
    """The ``_SKIPPED`` list must surface in every mode so a future
    engineer doesn't re-add the redundant indexes ‘just to be safe’."""
    _, dry_out = _run_main()
    _, apply_out = _run_main("--apply")
    _, verify_out = _run_main("--verify")
    for coll, name, _why in seed._SKIPPED:
        line = f"{coll}.{name}"
        assert line in dry_out
        assert line in apply_out
        assert line in verify_out
