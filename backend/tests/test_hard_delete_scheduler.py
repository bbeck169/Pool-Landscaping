"""HARD-DELETE · HD-B · Feb-2026 — nightly-purge scheduler tests.

Verifies the APScheduler binding introduced in
``services.hard_delete.scheduler``. Deterministic — no real cron
firings occur; we drive ``start()`` / ``stop()`` and assert on the
module-level singleton + the exposed diagnostic hooks.

Test-mode bypass
----------------
``pytest`` always sets ``PYTEST_CURRENT_TEST`` when a test runs,
which the scheduler binding treats as a hard bypass. The tests
that verify the bypass rely on that env var directly; the tests
that verify the "would bind" path have to temporarily unset the
env var + set the enabled flag.
"""
from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any

import pytest


@pytest.fixture
def sched_module(monkeypatch):
    """Reload the scheduler module fresh so each test starts with
    ``_scheduler is None`` regardless of the module import order.
    """
    from services.hard_delete import scheduler as sch
    importlib.reload(sch)
    yield sch
    # Force-teardown any lingering scheduler before the next test.
    asyncio.new_event_loop().run_until_complete(sch.stop())
    importlib.reload(sch)


def _clear_pytest_env(monkeypatch):
    """Temporarily drop PYTEST_CURRENT_TEST so the bind path
    doesn't short-circuit on the test-mode bypass."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def _in_loop(fn):
    """Run ``fn()`` inside a fresh event loop so ``AsyncIOScheduler.start()``
    can obtain a running loop.  APScheduler's asyncio scheduler
    binds to ``asyncio.get_running_loop()`` at ``start()`` time.
    """
    async def _wrapper():
        return fn()
    return asyncio.new_event_loop().run_until_complete(_wrapper())


# ─── ENABLED flag ─────────────────────────────────────────────────

def test_scheduler_binds_when_enabled_true(sched_module, monkeypatch):
    _clear_pytest_env(monkeypatch)
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_HOUR", "3")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_MINUTE", "0")

    sched = _in_loop(sched_module.start)
    assert sched is not None
    assert sched_module.is_bound() is True
    job = sched.get_job(sched_module._JOB_ID)
    assert job is not None
    # The trigger is a CronTrigger with hour=3, minute=0.
    trg = job.trigger
    fields = {f.name: str(f) for f in trg.fields}
    assert fields["hour"] == "3"
    assert fields["minute"] == "0"


def test_scheduler_skipped_when_enabled_false(sched_module, monkeypatch):
    _clear_pytest_env(monkeypatch)
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "false")

    sched = sched_module.start()
    assert sched is None
    assert sched_module.is_bound() is False
    assert sched_module.get_scheduler() is None


def test_scheduler_skipped_under_pytest(sched_module, monkeypatch):
    """PYTEST_CURRENT_TEST is set for every test — the bind must
    refuse. This is what keeps the production suite deterministic.
    """
    # Simulate a normal pytest invocation env (should already be
    # set — assert defensively).
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_dummy")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")

    sched = sched_module.start()
    assert sched is None
    assert sched_module.is_bound() is False


# ─── Env overrides ────────────────────────────────────────────────

def test_scheduler_honours_hour_minute_env_override(sched_module, monkeypatch):
    _clear_pytest_env(monkeypatch)
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_HOUR", "14")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_MINUTE", "37")

    _in_loop(sched_module.start)
    job = sched_module.get_scheduler().get_job(sched_module._JOB_ID)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "14"
    assert fields["minute"] == "37"


def test_cron_config_reflects_env(monkeypatch):
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_HOUR", "5")
    monkeypatch.setenv("HD_NIGHTLY_PURGE_MINUTE", "30")
    monkeypatch.setenv("SCHEDULER_TZ", "UTC")
    monkeypatch.setenv("HD_RETENTION_DAYS", "45")
    from services.hard_delete import scheduler as sch
    cfg = sch.cron_config()
    assert cfg["enabled"] is True
    assert cfg["hour"] == 5
    assert cfg["minute"] == 30
    assert cfg["timezone"] == "UTC"
    assert cfg["retention_days"] == 45


def test_cron_config_defaults(monkeypatch):
    monkeypatch.delenv("HD_NIGHTLY_PURGE_HOUR", raising=False)
    monkeypatch.delenv("HD_NIGHTLY_PURGE_MINUTE", raising=False)
    monkeypatch.delenv("SCHEDULER_TZ", raising=False)
    monkeypatch.delenv("HD_RETENTION_DAYS", raising=False)
    from services.hard_delete import scheduler as sch
    cfg = sch.cron_config()
    assert cfg["hour"] == 3
    assert cfg["minute"] == 0
    assert cfg["timezone"] == "America/Los_Angeles"
    assert cfg["retention_days"] == 30


# ─── Idempotency + shutdown ───────────────────────────────────────

def test_scheduler_start_is_idempotent(sched_module, monkeypatch):
    _clear_pytest_env(monkeypatch)
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")

    first = _in_loop(sched_module.start)
    second = _in_loop(sched_module.start)
    assert first is second
    assert sched_module.is_bound() is True


def test_scheduler_shutdown_clears_singleton(sched_module, monkeypatch):
    _clear_pytest_env(monkeypatch)
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", "true")

    _in_loop(sched_module.start)
    assert sched_module.is_bound() is True

    asyncio.new_event_loop().run_until_complete(sched_module.stop())
    assert sched_module.get_scheduler() is None
    assert sched_module.is_bound() is False


def test_scheduler_shutdown_safe_when_never_started(sched_module):
    # No start() call — should be a no-op.
    asyncio.new_event_loop().run_until_complete(sched_module.stop())
    assert sched_module.get_scheduler() is None


# ─── _in_test_mode helper ─────────────────────────────────────────

def test_in_test_mode_true_when_env_set(monkeypatch):
    from services.hard_delete import scheduler as sch
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_dummy")
    assert sch._in_test_mode() is True


def test_in_test_mode_false_when_env_unset(monkeypatch):
    from services.hard_delete import scheduler as sch
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert sch._in_test_mode() is False


# ─── Flag parsing edge cases ──────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("no", False), ("off", False), ("", True),
])
def test_flag_true_default(monkeypatch, val, expected):
    from services.hard_delete import scheduler as sch
    monkeypatch.setenv("HD_NIGHTLY_PURGE_ENABLED", val)
    # Empty string → still the default (True).
    assert sch._flag_true("HD_NIGHTLY_PURGE_ENABLED") is expected
