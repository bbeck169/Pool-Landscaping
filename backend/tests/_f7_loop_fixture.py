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
    "emailer",
    "routers.admin_health_check",
    "routers.analytics_monthly",
    "routers.analytics_proposal",
    "routers.auth",
    "routers.charge_templates",
    "routers.crew_productivity",
    "routers.customers",
    "routers.communication_timeline",
    "routers.dashboard_revenue",
    "routers.data_repair",
    "routers.drift_alerts",
    "routers.gps_auto_start",
    "routers.job_media_line_items",
    "routers.income_categories",
    "routers.intelligence_alerts",
    "routers.job_timers",
    "routers.jobs",
    "routers.workstream",
    "routers.mobile_sync",
    "routers.industry_checklists",
    "routers.deletion_audit",
    "routers.marketing_media",
    "routers.portal_admin",
    "routers.recurring_jobs",
    "routers.resend_webhooks",
    "routers.ringcentral",
    "routers.schedule_reorder",
    "routers.soshie_brand_ingest",
    "routers.soshie_moderation",
    "routers.stripe_router",
    "routers.team",
    "routers.technicians",
    "routers.tenant_org_settings",
    "routers.user_recent_colors",
    "routers.reports_business_snapshot",
    "routers.reports_attrition",
    "routers.reports_time_to_get_paid",
    "routers.reports_revenue_by_service",
    "routers.reports_recurring_vs_project",
    "routers.reports_client_lifetime_value",
    "routers.reports_close_ratio",
    "routers.reports_time_to_close",
    "routers.reports_labor_efficiency",
    "routers.reports_booked_out_capacity",
    "routers.tenants",
    "routers.tech_brief",
    "routers.sales_pipeline",
    "routers.health_payments",
    "routers.dashboard_action_cards",
    "routers.service_categories",
    "routers.category_references",
    "routers.leads",
    "routers.tenant_memberships",
    "routers.admin_users",
    "routers.portal_agreements",
    "routers.messages_unread",
    "routers.reference_currencies",
    "routers.weekly_digest",
    "routers.auth",
    "services.user_tenants",
    "services.customer_properties",
    "server",
    "services.auto_invoice",
    "services.intelligence.alerts",
    "services.intelligence.chemistry_upsell_scan",
    "services.intelligence.churn_risk_scan",
    "services.intelligence.missed_service_scan",
    "services.intelligence.renewal_scan",
    "services.drift_alerting",
    "services.payments.stripe_charge",
    "services.pricebook.writeback",
    "services.customer_multi_contact",
    "services.migrations.perf1_missing_tenant_indexes",
    "services.tech_id_resolver",
    "migrations.p23_restore_ethan_steven_technicians",
    "migrations.p29_clear_landscape_required_overrides",
    "migrations.p30_add_card_sms_template",
    "migrations.p30_customers_stripe_customer_id_unique",
    "migrations.p36_clear_nonpool_required_overrides",
    "migrations.p38_backfill_scheduled_date",
    "migrations.p38_1_reverse_backfill_scheduled_start",
    "routers.telematics_webhooks",
    "routers.cad",
    # PORTAL-QUOTE-DECLINE-REQUIRE-REASON · Feb-2026 — the portal
    # decline handler (``phase_a_decline_via_token`` etc.) calls
    # ``db.quotes``/``db.audit_logs`` directly off the module-level
    # ``db`` binding.  Add here so ``test_portal_quote_decline_
    # required_reason.py`` can drive the handler in-process.
    "routers.estimate_viewer",
    # ``phase_a_decline_via_token`` ultimately calls ``_build_payload``
    # which lives in ``routers.invoice_viewer`` and reads
    # ``db.tenants`` + ``db.customers`` off its own module-level ``db``.
    "routers.invoice_viewer",
    # WINGMAN-ESCALATION-EMAIL-FIX · Feb-2026 — the admin notification
    # fan-out at ``services.notifications._dispatch_email`` reads
    # ``db.users``/``db.email_delivery_log`` directly off its own
    # module-level ``db`` binding.  Added so
    # ``test_wingman_escalation_email_absolute_url.py`` can drive
    # the dispatcher in-process.
    "services.notifications",
    "services.telematics",
    "services.telematics.registry",
    "services.telematics._helpers",
    "services.telematics.webhook_url",
    "services.telematics_geotab_poller",
    "scripts.ensure_indexes",
    "scripts.p35_photo_backfill",
    "services.soshie.autopilot_config",
    "services.soshie.autopilot_scheduler",
    "services.soshie.brand_ingest",
    "services.soshie.brand_ingest_jobs",
    "services.soshie.llm_moderation",
    "services.soshie.moderation",
    "utils",
    "utils_idempotency",
    # Phase 11 · Feb-2026 — recurring labor costs router + service.
    "routers.recurring_labor_costs",
    "services.recurring_labor_cost",
    "services.labor_cost",
    "services.finance.ebit",
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
