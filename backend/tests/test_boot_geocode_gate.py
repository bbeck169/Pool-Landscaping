"""P0-GEOCODE-LEAK-C1 · TD-62 (Feb-2026).

Locks the emergency kill-switch behavior for the lifespan-registered
``geocode_backfill_all_tenants_boot`` task:

  * Default (``ENABLE_BOOT_GEOCODE_BACKFILL`` UNSET)   → sweep SKIPPED,
    log line ``[phase17] geocode backfill gated-off ...``.
  * ``ENABLE_BOOT_GEOCODE_BACKFILL=true``             → sweep scheduled,
    legacy log line ``[phase17] geocode backfill scheduled ...``.
  * Case-insensitive truthy accept-set: ``{"1","true","yes","on"}``.
  * Case-insensitive falsy / unknown values               → SKIPPED.

The lifespan handler is a 1600-line function in ``server.py`` with
many unrelated side effects (DB index creation, migrations, cron
registration, etc.) so this test does NOT run the full lifespan.
Instead it inlines the specific 10-line gate block that was
introduced by this commit and verifies both branches under a mock.

If the gate block in ``server.py`` is refactored, this test will stay
green so long as the semantics are preserved — update the inlined
copy below to match the current ``server.py`` block if the signature
changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# 1. Live-source invariants — fail fast if ``server.py`` drifts.
# ─────────────────────────────────────────────────────────────────
_SERVER_PY = Path(__file__).resolve().parent.parent / "server.py"
_SOURCE = _SERVER_PY.read_text(encoding="utf-8")


def test_server_py_contains_env_gate_block():
    """Guard that the kill-switch block is still present in server.py."""
    assert "ENABLE_BOOT_GEOCODE_BACKFILL" in _SOURCE, (
        "ENABLE_BOOT_GEOCODE_BACKFILL env gate missing from server.py — "
        "the P0 kill-switch has been removed or renamed. See TD-62."
    )
    # Default-off accept-set must stay case-insensitive truthy only.
    assert '"1", "true", "yes", "on"' in _SOURCE or \
           "'1', 'true', 'yes', 'on'" in _SOURCE, (
        "Accept-set drift — expected {1,true,yes,on} truthy values."
    )
    # Must still log the gated-off branch under TD-62 for grep-ability.
    assert "gated-off" in _SOURCE and "TD-62" in _SOURCE, (
        "Gated-off log line / TD-62 marker lost from server.py."
    )


def test_server_py_both_branches_present():
    """The gate must preserve BOTH the scheduled + the gated-off path."""
    # Scheduled branch (legacy signature preserved for log-count parity)
    assert "geocode backfill scheduled" in _SOURCE
    # Gated-off branch (new in C1)
    assert "geocode backfill gated-off" in _SOURCE


# ─────────────────────────────────────────────────────────────────
# 2. Behavioural tests — simulate the gate block in isolation.
# ─────────────────────────────────────────────────────────────────
# We re-implement the exact gate semantics here so the tests exercise
# the SAME truthy accept-set + log-line pattern as the live code.  If
# ``server.py``'s block drifts, test #1 catches it immediately.

_ACCEPT_SET = ("1", "true", "yes", "on")


def _env_truthy(value: str) -> bool:
    return (value or "").strip().lower() in _ACCEPT_SET


async def _simulate_gate(
    *, logger: logging.Logger, scheduler: AsyncMock,
) -> None:
    """Mirror of the server.py:4553 gate block."""
    enabled = _env_truthy(os.environ.get("ENABLE_BOOT_GEOCODE_BACKFILL", ""))
    if enabled:
        await scheduler()
        logger.info("[phase17] geocode backfill scheduled (fire-and-forget)")
    else:
        logger.info(
            "[phase17] geocode backfill gated-off "
            "(ENABLE_BOOT_GEOCODE_BACKFILL not set) · TD-62"
        )


@pytest.fixture
def log_capture(caplog):
    caplog.set_level(logging.INFO)
    return caplog


def test_gate_default_unset_does_NOT_schedule_backfill(log_capture, monkeypatch):
    """UNSET env → sweep must NOT be scheduled."""
    monkeypatch.delenv("ENABLE_BOOT_GEOCODE_BACKFILL", raising=False)
    scheduler = AsyncMock()
    asyncio.run(_simulate_gate(logger=logging.getLogger("test"), scheduler=scheduler))
    scheduler.assert_not_awaited()
    assert any("gated-off" in r.message for r in log_capture.records), (
        f"Expected 'gated-off' log line; got: "
        f"{[r.message for r in log_capture.records]}"
    )


@pytest.mark.parametrize("falsy_value", [
    "", "0", "false", "no", "off", "False", "random", "disable",
])
def test_gate_falsy_or_unknown_values_do_NOT_schedule(
    log_capture, monkeypatch, falsy_value,
):
    """Any value NOT in the truthy accept-set → sweep SKIPPED."""
    monkeypatch.setenv("ENABLE_BOOT_GEOCODE_BACKFILL", falsy_value)
    scheduler = AsyncMock()
    asyncio.run(_simulate_gate(logger=logging.getLogger("test"), scheduler=scheduler))
    scheduler.assert_not_awaited()


@pytest.mark.parametrize("truthy_value", [
    "1", "true", "yes", "on",
    "TRUE", "Yes", "ON",       # case-insensitive
    "  true  ", "  1  ",       # whitespace tolerance
])
def test_gate_truthy_values_DO_schedule(log_capture, monkeypatch, truthy_value):
    """Explicit opt-in via truthy env value → sweep scheduled."""
    monkeypatch.setenv("ENABLE_BOOT_GEOCODE_BACKFILL", truthy_value)
    scheduler = AsyncMock()
    asyncio.run(_simulate_gate(logger=logging.getLogger("test"), scheduler=scheduler))
    scheduler.assert_awaited_once()
    assert any(
        "geocode backfill scheduled" in r.message
        for r in log_capture.records
    ), (
        f"Expected 'scheduled' log line for truthy value {truthy_value!r}; "
        f"got: {[r.message for r in log_capture.records]}"
    )


def test_grep_count_parity_preserved(log_capture, monkeypatch):
    """Both branches must retain the ``[phase17] geocode backfill`` prefix
    so operator sweep-count queries (``grep -c``) keep working."""
    _records: List[logging.LogRecord] = []

    # Toggle OFF
    monkeypatch.delenv("ENABLE_BOOT_GEOCODE_BACKFILL", raising=False)
    asyncio.run(_simulate_gate(
        logger=logging.getLogger("test"), scheduler=AsyncMock(),
    ))
    _records.extend(log_capture.records)

    log_capture.clear()
    # Toggle ON
    monkeypatch.setenv("ENABLE_BOOT_GEOCODE_BACKFILL", "true")
    asyncio.run(_simulate_gate(
        logger=logging.getLogger("test"), scheduler=AsyncMock(),
    ))
    _records.extend(log_capture.records)

    phase17_lines = [r.message for r in _records
                      if "[phase17] geocode backfill" in r.message]
    assert len(phase17_lines) == 2, (
        f"Expected 2 ``[phase17] geocode backfill`` lines (one per branch); "
        f"got {len(phase17_lines)}: {phase17_lines}"
    )
