"""Shared fixture: per-test-call loop binding for F7 tests.

Motor collections carry loop affinity — the FastAPI startup binds
``config.db`` to the app's default loop, but pytest coroutines run on
a fresh loop.  ``run_test(coro_factory)``:

  1. Snapshots the current module-level ``db`` handles.
  2. Creates a fresh loop.
  3. Instantiates a Motor client + DB handle bound to that loop.
  4. Rebinds every module-level ``db`` handle used by the F7 code
     paths so the coroutine sees a loop-consistent collection.
  5. Calls ``coro_factory(db)`` to build the coroutine.
  6. Runs the coroutine to completion.
  7. **Restores the original module DB handles** so downstream
     pytest files that assume the process-default binding (e.g.
     HTTP-driven tests hitting a live uvicorn) don't inherit our
     closed loop's DB.
  8. Closes the loop.
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


_REBOUND_MODULES = (
    "config",
    "routers.admin_health_check",
    "routers.analytics_monthly",
    "routers.charge_templates",
    "routers.crew_productivity",
    "routers.customers",
    "routers.communication_timeline",
    "routers.dashboard_revenue",
    "routers.data_repair",
    "routers.drift_alerts",
    "routers.job_media_line_items",
    "routers.income_categories",
    "routers.jobs",
    "routers.portal_admin",
    "routers.recurring_jobs",
    "routers.schedule_reorder",
    "routers.soshie_brand_ingest",
    "routers.soshie_moderation",
    "routers.stripe_router",
    "routers.reports_business_snapshot",
    "routers.tenants",
    "server",
    "services.auto_invoice",
    "services.drift_alerting",
    "services.payments.stripe_charge",
    "services.pricebook.writeback",
    "services.customer_multi_contact",
    "services.migrations.perf1_missing_tenant_indexes",
    "services.soshie.autopilot_config",
    "services.soshie.autopilot_scheduler",
    "services.soshie.brand_ingest",
    "services.soshie.brand_ingest_jobs",
    "services.soshie.llm_moderation",
    "services.soshie.moderation",
    "utils",
)


def _snapshot_dbs():
    """Return {module_name: original_db_handle}, importing lazily."""
    import importlib
    out = {}
    for name in _REBOUND_MODULES:
        mod = importlib.import_module(name)
        out[name] = getattr(mod, "db", None)
    return out


def _apply_dbs(mapping):
    import importlib
    for name, handle in mapping.items():
        mod = importlib.import_module(name)
        setattr(mod, "db", handle)


def _rebind(loop):
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    db = client[os.environ["DB_NAME"]]
    _apply_dbs({name: db for name in _REBOUND_MODULES})
    return db


def run_test(coro_factory):
    """coro_factory(db) → coroutine.

    Rebinds the F7 code paths to a fresh loop-bound DB, runs the
    coroutine, then restores the original bindings so downstream
    HTTP-driven tests aren't poisoned by a closed loop.
    """
    original = _snapshot_dbs()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        db = _rebind(loop)
        return loop.run_until_complete(coro_factory(db))
    finally:
        _apply_dbs(original)
        loop.close()
