"""Dedicated APScheduler worker — production scheduler process.

Feb-2026 · D2 production boot hardening.

**Ops runbook**

    cd /app/backend
    ENABLE_SCHEDULER=true python -m scripts.run_scheduler

The ``ENABLE_SCHEDULER=true`` override is REQUIRED — even in
production — so this specific process registers + runs scheduled
jobs.  Web workers keep ``ENABLE_SCHEDULER=false`` (see
``boot_flags.py``) so no duplicate cron work fires.

Run exactly ONE of these per environment (supervisor / systemd /
docker sidecar).  Running two duplicates every scheduled job.

Behaviour:
1.  Set ``ENABLE_SCHEDULER=true`` on this process's env before the
    server module is imported.
2.  Import ``server`` — its FastAPI ``startup`` event handler
    registers all ``scheduler.add_job(...)`` calls and calls
    ``scheduler.start()`` because the gate is now on.
3.  Block forever so the AsyncIO event loop keeps ticking.

This process does NOT bind to an HTTP port — uvicorn is never
started, so it doesn't compete with web workers on port 8001.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Force scheduler ON for this process regardless of prod / dev defaults.
os.environ["ENABLE_SCHEDULER"] = "true"

# Allow ``python -m scripts.run_scheduler`` from /app/backend.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("scheduler_worker")
    log.info("[scheduler-worker] starting — ENABLE_SCHEDULER=true forced")

    # Import triggers server.py module load.  The FastAPI startup
    # event handler is defined but NOT auto-fired outside of an ASGI
    # lifespan, so we invoke it manually below.
    from server import scheduler, startup  # noqa: E402

    # Fire the startup event handler once.  It registers scheduler
    # jobs (gated by should_enable_scheduler(), which is now True
    # because we set ENABLE_SCHEDULER=true above) and then calls
    # ``scheduler.start()`` on the shared singleton.
    try:
        await startup()
    except Exception as exc:  # noqa: BLE001
        log.exception(f"[scheduler-worker] startup crashed: {exc}")
        return 1

    # The startup event also runs background_seed via
    # ``asyncio.create_task(_defer())`` — give it 5s to schedule the
    # jobs (they land inside the background task).
    await asyncio.sleep(5)
    n = len(scheduler.get_jobs())
    log.info(
        f"[scheduler-worker] scheduler.running={scheduler.running} "
        f"registered_jobs={n}"
    )
    if n == 0:
        log.warning(
            "[scheduler-worker] zero jobs registered — "
            "background_seed may still be running; scheduler will "
            "pick up jobs as they land."
        )

    # Block until SIGINT / SIGTERM.
    stop_event = asyncio.Event()

    def _shutdown(signum, _frame):
        log.info(f"[scheduler-worker] received signal {signum}, shutting down")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            pass  # not always available (e.g. inside a thread)

    await stop_event.wait()

    try:
        scheduler.shutdown(wait=False)
        log.info("[scheduler-worker] scheduler stopped cleanly")
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[scheduler-worker] scheduler shutdown warning: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
