"""Unit tests for ``backend/boot_flags.py`` — the three production
boot-hardening gates.

The helpers are pure ``os.environ`` readers so we can patch env in a
fixture and reload defaults without touching the running server.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def flags(monkeypatch):
    """Return a freshly-imported ``boot_flags`` module with a helper
    to patch the env + re-snapshot."""
    import boot_flags  # noqa: F401 — re-imported to ensure fresh module state
    importlib.reload(boot_flags)

    def _set(**env: str):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        # Boot flags read env on every call, so no reload needed.
        return boot_flags

    yield _set


# ═══ APP_ENV detection ══════════════════════════════════════════════
def test_is_production_true_when_app_env_set(flags):
    bf = flags(APP_ENV="production")
    assert bf.is_production() is True


def test_is_production_case_insensitive(flags):
    bf = flags(APP_ENV="PRODUCTION")
    assert bf.is_production() is True


def test_is_production_false_default(flags):
    bf = flags(APP_ENV="preview")
    assert bf.is_production() is False


# ═══ SEED_DEMO_DATA ═════════════════════════════════════════════════
def test_seed_demo_data_default_on_in_dev(flags):
    bf = flags(APP_ENV="preview")
    assert bf.should_seed_demo_data() is True


def test_seed_demo_data_off_when_prod_regardless_of_flag(flags, monkeypatch):
    """Belt-and-braces posture — prod=off even if flag is missing."""
    bf = flags(APP_ENV="production")
    monkeypatch.delenv("SEED_DEMO_DATA", raising=False)
    assert bf.should_seed_demo_data() is False


def test_seed_demo_data_off_when_prod_even_if_flag_true(flags):
    """Explicit flag=true does NOT override APP_ENV=production."""
    bf = flags(APP_ENV="production", SEED_DEMO_DATA="true")
    assert bf.should_seed_demo_data() is False


def test_seed_demo_data_off_when_flag_false_in_dev(flags):
    """Non-prod but explicit opt-out."""
    bf = flags(APP_ENV="preview", SEED_DEMO_DATA="false")
    assert bf.should_seed_demo_data() is False


def test_seed_demo_data_case_insensitive(flags):
    bf = flags(APP_ENV="preview", SEED_DEMO_DATA="FALSE")
    assert bf.should_seed_demo_data() is False


# ═══ RUN_STARTUP_INDEXES ════════════════════════════════════════════
def test_startup_indexes_default_on_in_dev(flags):
    bf = flags(APP_ENV="preview")
    assert bf.should_run_startup_indexes() is True


def test_startup_indexes_off_in_prod(flags, monkeypatch):
    bf = flags(APP_ENV="production")
    monkeypatch.delenv("RUN_STARTUP_INDEXES", raising=False)
    assert bf.should_run_startup_indexes() is False


def test_startup_indexes_off_when_explicit_false(flags):
    bf = flags(APP_ENV="preview", RUN_STARTUP_INDEXES="false")
    assert bf.should_run_startup_indexes() is False


# ═══ ENABLE_SCHEDULER ═══════════════════════════════════════════════
def test_scheduler_default_on_in_dev(flags):
    bf = flags(APP_ENV="preview")
    assert bf.should_enable_scheduler() is True


def test_scheduler_off_in_prod(flags, monkeypatch):
    bf = flags(APP_ENV="production")
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    assert bf.should_enable_scheduler() is False


def test_scheduler_forced_on_by_worker_script(flags):
    """The dedicated scheduler worker sets ENABLE_SCHEDULER=true in
    its own env — but we still hard-off in production.
    That's why run_scheduler.py runs as its OWN process without
    APP_ENV=production (the ops runbook clarifies this).
    """
    bf = flags(APP_ENV="preview", ENABLE_SCHEDULER="true")
    assert bf.should_enable_scheduler() is True


# ═══ snapshot() ═════════════════════════════════════════════════════
def test_snapshot_returns_all_five_keys(flags):
    bf = flags(APP_ENV="preview")
    snap = bf.snapshot()
    assert set(snap.keys()) == {
        "app_env", "is_production",
        "seed_demo_data", "run_startup_indexes", "enable_scheduler",
    }


def test_snapshot_prod_all_off(flags, monkeypatch):
    bf = flags(APP_ENV="production")
    for k in ("SEED_DEMO_DATA", "RUN_STARTUP_INDEXES", "ENABLE_SCHEDULER"):
        monkeypatch.delenv(k, raising=False)
    snap = bf.snapshot()
    assert snap["is_production"] is True
    assert snap["seed_demo_data"] is False
    assert snap["run_startup_indexes"] is False
    assert snap["enable_scheduler"] is False


def test_snapshot_dev_all_on(flags, monkeypatch):
    bf = flags(APP_ENV="preview")
    for k in ("SEED_DEMO_DATA", "RUN_STARTUP_INDEXES", "ENABLE_SCHEDULER"):
        monkeypatch.delenv(k, raising=False)
    snap = bf.snapshot()
    assert snap["is_production"] is False
    assert snap["seed_demo_data"] is True
    assert snap["run_startup_indexes"] is True
    assert snap["enable_scheduler"] is True
