from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import client, db, logger
from seed import seed, seed_extras, seed_tech_today_demo
from routers import (
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
)

app = FastAPI(
    title="Pool CRM API",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
api_router = APIRouter(prefix="/api")

for module in [auth, customers, technicians, jobs, quotes, leads, team, items, payments,
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
               workstream]:
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

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
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
    await step("business_os", business_os.seed_business_os())
    await step("tech_today_demo", seed_tech_today_demo())

    # Scheduler registration (needs the DB but not auth).
    try:
        SEEDS_PHASE = "scheduler"
        scheduler.add_job(seo.run_due_publishes, "interval", minutes=10,
                            id="seo_drip", replace_existing=True)
        scheduler.add_job(finances.run_monthly_chem_billing, "interval",
                            hours=24, id="chem_billing", replace_existing=True)
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
