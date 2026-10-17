"""TD-55b · Feb-2026 — APScheduler registration for the GDPR purge.

Locks the two guarantees the dispatch brief called out:
  (1) ``register_forms_purge_cron`` attaches a job for
      :func:`purge_expired_form_submissions` on a 03:00 UTC daily
      cron, with the stable ``id="td55b.form_submissions_purge"``
      and ``replace_existing=True`` so hot-reload / supervisor-
      restart cycles stay idempotent.
  (2) The ``_td55b_tick`` wrapper swallows exceptions from the
      underlying purge coroutine — a bad sweep MUST NOT crash the
      scheduler engine and take sibling jobs down with it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def test_register_forms_purge_cron_adds_job_with_correct_shape():
    """TD-55b (1) — the registration function attaches ONE job with
    the operator-locked cadence (03:00 UTC daily) + the stable id
    + ``replace_existing=True`` behaviour."""
    from routers.marketing_forms import (
        register_forms_purge_cron, _td55b_tick,
    )

    # ``replace_existing=True`` on APScheduler is honored only when
    # the scheduler is actually running (unstarted schedulers hold
    # jobs in a pending-list that doesn't dedupe).  Drive the
    # scheduler through its real start → add → shutdown cycle so
    # the idempotency assertion exercises the production path.
    async def _run():
        sched = AsyncIOScheduler(timezone="UTC")
        sched.start(paused=True)
        try:
            register_forms_purge_cron(sched)
            jobs = [j for j in sched.get_jobs()
                     if j.id == "td55b.form_submissions_purge"]
            assert len(jobs) == 1, "exactly one job must be registered"

            job = jobs[0]
            # Scheduler stores the coroutine function on ``job.func``.
            assert job.func is _td55b_tick, (
                "the tick wrapper (not the raw coroutine) must be "
                "the scheduled callable so exceptions are swallowed"
            )

            trigger = job.trigger
            assert isinstance(trigger, CronTrigger)
            # Trigger field cadence lock — ``hour=3, minute=0``.
            fields = {f.name: str(f) for f in trigger.fields}
            assert fields.get("hour") == "3", (
                f"expected hour=3, got hour={fields.get('hour')!r}"
            )
            assert fields.get("minute") == "0", (
                f"expected minute=0, got minute={fields.get('minute')!r}"
            )
            # Timezone lock — UTC.
            assert str(trigger.timezone) == "UTC"

            # Second call is idempotent via ``replace_existing=True``.
            register_forms_purge_cron(sched)
            jobs_after = [j for j in sched.get_jobs()
                           if j.id == "td55b.form_submissions_purge"]
            assert len(jobs_after) == 1, (
                "replace_existing must keep the job count at 1 "
                "across re-registration (hot-reload / supervisor-"
                "restart)"
            )
        finally:
            sched.shutdown(wait=False)
    asyncio.run(_run())


def test_register_forms_purge_cron_is_a_noop_when_scheduler_is_none():
    """Unit tests that drive :func:`purge_expired_form_submissions`
    directly don't need an APScheduler — the registration function
    must gracefully no-op on ``None`` so test fixtures stay simple."""
    from routers.marketing_forms import register_forms_purge_cron
    # Should not raise.
    register_forms_purge_cron(None)


def test__td55b_tick_swallows_underlying_coroutine_exceptions(caplog):
    """TD-55b (2) — the tick wrapper swallows every exception from
    the underlying purge coroutine so the scheduler engine stays
    up.  Verified by patching the purge function to raise, running
    the tick, and asserting no exception propagates."""
    import logging
    from routers import marketing_forms as mf

    async def _exploding_purge():
        raise RuntimeError("db connection reset")

    with patch.object(mf, "purge_expired_form_submissions",
                        _exploding_purge):
        with caplog.at_level(logging.ERROR, logger=mf.logger.name):
            # If the wrapper did NOT swallow, this call would re-raise.
            asyncio.run(mf._td55b_tick())

    # The failure path logs via ``logger.exception`` → ERROR level +
    # the "tick failed" marker so operators can spot it in
    # supervisor logs.
    failure_lines = [r for r in caplog.records
                      if "[forms-purge]" in r.getMessage()
                      and "tick failed" in r.getMessage()]
    assert failure_lines, (
        "the tick wrapper must log the failure via logger.exception "
        "with the ``[forms-purge] tick failed`` marker so operators "
        "see swallowed exceptions in supervisor logs"
    )
    # And it logs ``exc_info`` so the full traceback is captured.
    assert failure_lines[0].exc_info is not None


def test__td55b_tick_happy_path_logs_purged_count(caplog):
    """TD-55b (2) regression — the happy path logs the summary line
    with the ``total_purged`` count so operators can tail the daily
    sweep in supervisor logs."""
    import logging
    from routers import marketing_forms as mf

    async def _fake_purge():
        return {"total_purged": 7, "per_tenant": {"T-a": 7},
                "ran_at": "2026-02-15T03:00:00+00:00"}

    with patch.object(mf, "purge_expired_form_submissions", _fake_purge):
        with caplog.at_level(logging.INFO, logger=mf.logger.name):
            asyncio.run(mf._td55b_tick())

    completion_lines = [r for r in caplog.records
                         if "[forms-purge] completed" in r.getMessage()]
    assert completion_lines, (
        "the tick must log a ``[forms-purge] completed · purged N "
        "expired submissions in {ms}ms`` summary on happy path"
    )
    msg = completion_lines[0].getMessage()
    assert "7" in msg, (
        f"completion summary must include the purged count 7 — got {msg!r}"
    )
