"""Boot-time env flags — production hardening (Feb-2026 D2).

Three flags gate optional startup work so a production web worker can
boot fast + slim:

* ``SEED_DEMO_DATA``       — demo/sample rows (customers, jobs, prior
                             chemical readings, per-tenant demo tech
                             users, etc.).
* ``RUN_STARTUP_INDEXES``  — inline ``create_index`` / router-level
                             ``ensure_indexes()`` blocks that run at
                             boot.  Prod runs them out-of-band via
                             ``python -m scripts.ensure_indexes``.
* ``ENABLE_SCHEDULER``     — the APScheduler ``AsyncIOScheduler`` +
                             all ``scheduler.add_job(...)`` calls
                             + ``scheduler.start()``.  Prod runs
                             them via ``python -m scripts.run_scheduler``.

Effective value (per user directive, option "c" — belt-and-braces):

    ENABLED = (APP_ENV != "production") AND (env(FLAG, "true") != "false")

So the flag is:
* OFF whenever ``APP_ENV=production`` — regardless of the explicit
  flag value.  Even a misconfigured production deploy that forgets
  to set the flags stays lean.
* OFF whenever the explicit env value is literally ``"false"`` (case-
  insensitive) — same posture for non-prod environments that want to
  opt out (e.g. a preview pod under memory pressure).
* ON otherwise (dev + preview default).

Boot migrations (tenant_backfill, super_admin bootstrap, ToS
backfill, phase21 rebrand, quickbooks_cleanup, tenants timezone
backfill, etc.) do NOT go through this file — they run
unconditionally because they are one-shot production upgrades, not
demo data.  See server.py comments at their call sites.
"""
from __future__ import annotations

import os


def _app_env() -> str:
    return (os.environ.get("APP_ENV", "preview") or "preview").lower()


def _flag(name: str, default: str = "true") -> bool:
    """Return True iff the env value is not literally ``"false"``.

    Any other value — including the empty string, ``"0"``, ``"no"``,
    or an unset env var — evaluates to True (the safer default for
    dev).  ``"false"`` is the sole opt-out sentinel to keep this
    unambiguous when it shows up in logs.
    """
    return (os.environ.get(name, default) or default).lower() != "false"


def is_production() -> bool:
    """``True`` iff ``APP_ENV=production``."""
    return _app_env() == "production"


def should_seed_demo_data() -> bool:
    """Gate for demo/sample seeds (customers, jobs, prior readings,
    demo tech users, per-tenant sample inventory/pricebook).
    """
    return (not is_production()) and _flag("SEED_DEMO_DATA", "true")


def should_run_startup_indexes() -> bool:
    """Gate for ``create_index`` / ``ensure_indexes()`` calls that
    normally run inside the FastAPI startup event.
    """
    return (not is_production()) and _flag("RUN_STARTUP_INDEXES", "true")


def should_enable_scheduler() -> bool:
    """Gate for APScheduler job registration + ``.start()``.

    When ``False``, the ``scheduler`` singleton is still constructed
    (so any module that imports it doesn't crash) — no jobs are
    added and the scheduler is never started.

    Feb-2026 · Notification-bundle audit fix — the dedicated
    scheduler-worker process (``scripts/run_scheduler.py``) exports
    ``SCHEDULER_WORKER=1`` so it can honour cron registration EVEN
    when ``APP_ENV=production``. Web workers keep the flag unset
    (or ``0``) so no duplicate cron work fires there. Without this
    override, ``(not is_production())`` shorts the entire gate to
    False in prod and every cron becomes dead code.
    """
    if (os.environ.get("SCHEDULER_WORKER") or "").strip() == "1":
        return _flag("ENABLE_SCHEDULER", "true")
    return (not is_production()) and _flag("ENABLE_SCHEDULER", "true")


def snapshot() -> dict:
    """Read the current effective values.

    Read each call, so tests that patch ``os.environ`` after import
    still see the fresh value.
    """
    return {
        "app_env": _app_env(),
        "is_production": is_production(),
        "seed_demo_data": should_seed_demo_data(),
        "run_startup_indexes": should_run_startup_indexes(),
        "enable_scheduler": should_enable_scheduler(),
    }
