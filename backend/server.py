from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
import logging

from config import client, db, logger
from seed import seed, seed_extras, seed_tech_today_demo, seed_landscaping_user, seed_landscape_tech_carlos, auto_heal_demo_passwords_if_needed, seed_prior_readings, seed_phase51k_finance, seed_mike_today_job
from routers import (
    notifications as notifications_router,
    stripe_payments as stripe_payments_router,
    auth, customers, technicians, jobs, quotes, leads, team, items, payments,
    operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin, ops, reports, legal, marketing_studio, sequences, ai_ops, google as google_router, phase11,
    realtime, csat, signatures,
    analytics, onboarding,
    lead_requests, mobile_push,
    tenants, workforce,
    business_os,
    schedule, social,
    service_reports,
    referrals,
    public_social,
    route_optimization,
    portal_chats, portal_appointments, portal_photos,
    employee_onboarding, assets, referral_tiers,
    seo_agentic, seo_phase17c,
    estimator, dunning, inventory,
    checks,
    dispatch,
    churn, seo_content_refresh,
    warranties,
    rbac,
    workstream,
    cfo,
    timeclock_landscaping,
    budgets,
    chemical_costs,
    recurring_jobs,
    stripe_admin,
    zillow_admin,
    ringcentral,
    ringcentral_customer,
    config as config_router,
    job_requests as job_requests_router,
    training as training_router,
    customer_equipment_photos as customer_equipment_photos_router,
    pool_calculators,
    document_generators,
    pricing_defaults_router,
    growth_playbook,
    training_nudge,
    recommendations_queue,
    templates_library,
    handbook,
    weekly_digest,
)

app = FastAPI(
    title="Pool CRM API",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
api_router = APIRouter(prefix="/api")

for module in [notifications_router,
               stripe_payments_router,
               auth, customers, technicians, jobs, quotes, leads, team, items, payments,
               operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin, ops, reports, legal, marketing_studio, sequences, ai_ops, google_router, phase11,
               realtime, csat, signatures,
               analytics, onboarding,
               lead_requests, mobile_push,
               tenants, workforce,
               business_os,
               schedule, social,
               service_reports,
               referrals,
               route_optimization,
               portal_chats, portal_appointments, portal_photos,
               employee_onboarding, assets, referral_tiers,
               seo_agentic, seo_phase17c,
               estimator, dunning, inventory,
               checks, dispatch,
               churn, seo_content_refresh,
               warranties,
               rbac,
               workstream,
               cfo,
               timeclock_landscaping,
               budgets,
               chemical_costs,
               recurring_jobs,
               stripe_admin,
               zillow_admin,
               ringcentral,
               ringcentral_customer,
               config_router,
               job_requests_router,
               training_router,
               customer_equipment_photos_router,
               pool_calculators,
               document_generators,
               pricing_defaults_router,
               growth_playbook,
               training_nudge,
               recommendations_queue,
               templates_library,
               handbook,
               weekly_digest]:
    api_router.include_router(module.router)


@api_router.get("/")
async def root():
    return {"message": "Pool CRM API"}


# Public short-link redirect — Phase 18A.1.
# Register into api_router (→ /api/r/{alias}) so the URL works through the
# Kubernetes ingress (which only forwards `/api/*`). Also mount at the app
# root (/r/{alias}) so the endpoint stays reachable when hitting the backend
# directly (dev, curl, tests). Must be registered BEFORE app.include_router.
api_router.include_router(public_social.router)

app.include_router(api_router)
app.include_router(public_social.router)

# SEC-P3-1 hotfix — no wildcard CORS with credentials. Read allowlist from
# ALLOWED_ORIGINS (comma-separated); auto-append APP_PUBLIC_URL if set.
_APP_ENV_MW = os.environ.get("APP_ENV", "preview").lower()
_allowed_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
_app_public = os.environ.get("APP_PUBLIC_URL", "").strip()
_origins = [o.strip() for o in _allowed_raw.split(",") if o.strip()]
if _app_public and _app_public not in _origins:
    _origins.append(_app_public)
if not _origins:
    if _APP_ENV_MW == "production":
        logging.getLogger("pool_crm").error(
            "ALLOWED_ORIGINS is unset in production — refusing to enable CORS.")
        _origins = []
    else:
        # Dev/preview convenience: fall back to APP_PUBLIC_URL or localhost.
        _origins = [_app_public or "http://localhost:3000"]
logging.getLogger("pool_crm").info(f"CORS allow_origins = {_origins}")

# SEC-P3-2 hotfix — auto-force ALLOW_TEST_HOOKS=0 in production, regardless
# of the value in the mounted env. Existing dev/preview behavior unchanged.
if _APP_ENV_MW == "production" and os.environ.get("ALLOW_TEST_HOOKS") == "1":
    logging.getLogger("pool_crm").warning(
        "APP_ENV=production forcing ALLOW_TEST_HOOKS=0 (was 1 in env).")
    os.environ["ALLOW_TEST_HOOKS"] = "0"

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


scheduler = AsyncIOScheduler(timezone="UTC")


# ── Cold-start optimization ───────────────────────────────────────────
# Only the demo-admin `seed()` + a Mongo ping stay on the sync boot path
# so that /api/auth/login is answerable within ~1s of process start.
# All heavier idempotent seeds and the APScheduler registration run in a
# background task fired 2s after boot. `/api/health/seeds` exposes the
# progress so the frontend / monitoring can display a "warming" hint.

SEEDS_COMPLETE: bool = False
SEEDS_PHASE: str = "pending"
SEEDS_STARTED_AT: str | None = None
SEEDS_COMPLETED_AT: str | None = None


async def _background_seed():
    """Runs every heavy, idempotent seed off the boot path.
    Every step is wrapped so one bad seed can't block the rest."""
    global SEEDS_COMPLETE, SEEDS_PHASE, SEEDS_COMPLETED_AT
    from datetime import datetime, timezone as _tz
    import asyncio
    SEEDS_PHASE = "running"
    logger.info("Background seed pipeline starting…")

    async def step(name: str, coro):
        global SEEDS_PHASE
        SEEDS_PHASE = name
        try:
            await coro
        except Exception as e:
            logger.warning(f"seed step {name} skipped: {e}")

    await step("seed_extras", seed_extras())
    # Backfill income category — kept as a raw update, not a helper.
    try:
        SEEDS_PHASE = "income_category_backfill"
        res = await db.quotes.update_many(
            {"$or": [{"line_items.category": {"$exists": False}},
                        {"line_items.category": None}]},
            {"$set": {"line_items.$[el].category": "Pool"}},
            array_filters=[{"$or": [{"el.category": {"$exists": False}},
                                     {"el.category": None}]}],
        )
        if res.modified_count:
            logger.info(f"Backfilled income category on {res.modified_count} docs")
    except Exception as e:
        logger.warning(f"income category backfill skipped: {e}")

    await step("legal_docs", legal.ensure_seeded())
    await step("marketing_templates", marketing_studio._seed_templates())
    await step("sequences", sequences.ensure_sequences_seeded())
    await step("ai_employees", ai_ops.ensure_ai_employees_seeded())
    await step("onboarding_demo", onboarding._seed_completed_for_demo())
    await step("lead_request_form", lead_requests._seed_lead_request_form())
    await step("tenant_backfill", tenants.run_tenant_backfill())
    await step("super_admin", tenants._seed_super_admin())
    await step("landscaping_user", seed_landscaping_user())
    await step("landscape_tech_carlos", seed_landscape_tech_carlos())
    await step("auto_heal_demo_passwords", auto_heal_demo_passwords_if_needed())
    await step("business_os", business_os.seed_business_os())
    await step("tech_today_demo", seed_tech_today_demo())
    await step("prior_readings", seed_prior_readings())
    await step("phase51k_finance", seed_phase51k_finance())
    await step("mike_today_job", seed_mike_today_job())
    await step("chemical_costs", chemical_costs.seed_chemical_costs())

    # Scheduler registration (needs the DB but not auth).
    try:
        SEEDS_PHASE = "scheduler"
        scheduler.add_job(seo.run_due_publishes, "interval", minutes=10,
                            id="seo_drip", replace_existing=True)
        scheduler.add_job(finances.run_monthly_chem_billing, "interval",
                            hours=24, id="chem_billing", replace_existing=True)
        # Phase 56.17 — daily autobilling schedule dispatcher.
        # Runs every day at 06:00 UTC; each plan's anchor date is
        # computed in the tenant's own timezone inside the job.
        scheduler.add_job(finances.run_daily_autobilling, "cron",
                            hour=6, minute=0, id="autobilling_daily",
                            replace_existing=True)
        scheduler.add_job(coverage.revert_expired_coverage, "interval",
                            hours=12, id="coverage_revert",
                            replace_existing=True)
        scheduler.add_job(finances.run_late_fee_assessment, "cron",
                            hour=2, minute=0, id="late_fees",
                            replace_existing=True)
        scheduler.add_job(marketing_studio.run_marketing_autopost,
                            "interval", minutes=10,
                            id="marketing_autopost", replace_existing=True)
        scheduler.add_job(sequences.run_sequences_tick, "interval",
                            minutes=15, id="sequences_tick",
                            replace_existing=True)
        scheduler.add_job(csat.run_csat_dispatch_tick, "interval",
                            minutes=5, id="csat_dispatch",
                            replace_existing=True)
        scheduler.add_job(dunning.run_dunning_scan, "interval",
                            minutes=60, id="dunning_scan",
                            replace_existing=True)
        # Phase 26.2 — daily weather scan across every tenant (05:00 UTC).
        scheduler.add_job(dispatch.scheduled_weather_scan_all, "cron",
                            hour=5, minute=0, id="weather_scan",
                            replace_existing=True)
        # Phase 27.1 — weekly churn rescore (Mondays 06:00 UTC).
        scheduler.add_job(churn.scheduled_churn_scan_all, "cron",
                            day_of_week="mon", hour=6, minute=0,
                            id="churn_scan", replace_existing=True)
        # Phase 28.1 — daily warranty expiration reminders (08:00 UTC).
        scheduler.add_job(
            warranties.scheduled_warranty_expiration_scan_all,
            "cron", hour=8, minute=0,
            id="warranty_expiration_scan", replace_existing=True)
        # Phase 50.G — Auto-Friday Pool Service Report email (17:00 UTC).
        from services.pool_service_email import run_weekly_pool_service_email
        scheduler.add_job(
            run_weekly_pool_service_email,
            "cron", day_of_week="fri", hour=17, minute=0,
            id="pool_service_weekly_email", replace_existing=True)
        # Phase 51.I — nightly recurring-job generator (02:00 UTC).
        from routers.recurring_jobs import run_recurring_job_generator
        scheduler.add_job(
            run_recurring_job_generator,
            "cron", hour=2, minute=0,
            id="recurring_job_generator", replace_existing=True)
        # Phase 54 — nightly RingCentral contact pull-sync (03:00 UTC).
        async def _rc_nightly_pull():
            try:
                from services.ringcentral_client import is_outbound_enabled, get_rc_platform
                if not await is_outbound_enabled(): return
                platform = get_rc_platform()
                resp = platform.get("/restapi/v1.0/account/~/extension/~/address-book/contact",
                                     {"perPage": 500})
                data = resp.json_dict() if hasattr(resp, "json_dict") else resp.json()
                for r in (data or {}).get("records") or []:
                    phone = r.get("businessPhone") or r.get("homePhone") or r.get("mobilePhone")
                    if not phone: continue
                    exists = await db.leads.find_one({"phone": phone, "source": "rc-contact-sync"})
                    if exists: continue
                    await db.leads.insert_one({
                        "id": __import__("utils").new_id(),
                        "source": "rc-contact-sync",
                        "phone": phone,
                        "name": f"{r.get('firstName','')} {r.get('lastName','')}".strip() or "Unknown",
                        "email": r.get("email"),
                        "created_at": __import__("utils").now_iso(),
                        "status": "new",
                    })
            except Exception:
                pass
        scheduler.add_job(
            _rc_nightly_pull,
            "cron", hour=3, minute=0,
            id="rc_contact_pull_sync", replace_existing=True)
        # Phase 52.A — monthly pricing insights digest (1st @ 09:00 UTC).
        from services.monthly_pricing_digest import run_monthly_pricing_digest
        scheduler.add_job(
            run_monthly_pricing_digest,
            "cron", day=1, hour=9, minute=0,
            id="monthly_pricing_digest", replace_existing=True)
        # Phase 4 · Batch C — Weekly digest email (Mondays 08:00 UTC).
        # Per-tenant timezone is honored inside the service; the cron
        # trigger fires globally at a reasonable US business hour.
        from services.weekly_digest import run_weekly_digest, ensure_indexes as _wd_indexes
        await _wd_indexes()
        scheduler.add_job(
            run_weekly_digest,
            "cron", day_of_week="mon", hour=8, minute=0,
            id="weekly_digest", replace_existing=True)
        logger.info("scheduler: weekly_digest registered (Mondays 08:00 UTC)")
        scheduler.start()
    except Exception as e:
        logger.warning(f"scheduler registration skipped: {e}")

    SEEDS_COMPLETED_AT = datetime.now(_tz.utc).isoformat()
    SEEDS_PHASE = "complete"
    SEEDS_COMPLETE = True
    logger.info("Background seed pipeline complete.")


@app.on_event("startup")
async def startup():
    global SEEDS_STARTED_AT
    import asyncio
    from datetime import datetime, timezone as _tz
    # Sync boot path — auth-critical only.
    try:
        await client.admin.command("ping")
        logger.info("MongoDB ping OK")
    except Exception as e:
        logger.error(f"MongoDB ping FAILED at startup: {e}")
    await seed()  # idempotent, ~ms after first run; creates demo admin.
    SEEDS_STARTED_AT = datetime.now(_tz.utc).isoformat()
    # Deployment audit (Phase 58.a) — ensure the deploy-blocker indexes
    # documented in db_indexes.py exist. Idempotent.
    try:
        from db_indexes import ensure_deployment_indexes
        await ensure_deployment_indexes()
    except Exception as e:
        logger.warning(f"ensure_deployment_indexes crashed: {e}")

    # Phase 56.3.A — idempotent one-shot: back-fill first_name / last_name
    # on any legacy customer doc that only has the combined `name` field.
    try:
        from routers.customers import migrate_customer_names_split
        migrated_n = await migrate_customer_names_split()
        logger.info(f"[phase56.3.A] customer name-split migration: {migrated_n} row(s)")
    except Exception as e:
        logger.warning(f"customer name-split migration crashed: {e}")

    async def _defer():
        try:
            await asyncio.sleep(2)
            await _background_seed()
        except Exception as e:
            logger.warning(f"background seed task crashed: {e}")

    asyncio.create_task(_defer())
    logger.info("Boot path complete — API is now accepting requests.")


@app.get("/api/health/seeds")
async def health_seeds():
    """Cold-start progress indicator. Anyone can poll this."""
    return {
        "complete": bool(SEEDS_COMPLETE),
        "phase": SEEDS_PHASE,
        "started_at": SEEDS_STARTED_AT,
        "completed_at": SEEDS_COMPLETED_AT,
    }


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    client.close()
