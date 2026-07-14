from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import client, db, logger
from seed import seed, seed_extras
from routers import (
    auth, customers, technicians, jobs, quotes, leads, team, items, payments,
    operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin, ops, reports, legal, marketing_studio, sequences, ai_ops, google as google_router, phase11,
    realtime, csat, signatures,
    analytics, onboarding,
    lead_requests, mobile_push,
    tenants,
    workforce,
    business_os,
    schedule,
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
               schedule]:
    api_router.include_router(module.router)


@api_router.get("/")
async def root():
    return {"message": "Pool CRM API"}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup():
    await seed()
    await seed_extras()
    # Backfill: ensure every existing invoice/quote line item has an income category.
    try:
        res = await db.quotes.update_many(
            {"$or": [{"line_items.category": {"$exists": False}}, {"line_items.category": None}]},
            {"$set": {"line_items.$[el].category": "Pool"}},
            array_filters=[{"$or": [{"el.category": {"$exists": False}}, {"el.category": None}]}],
        )
        if res.modified_count:
            logger.info(f"Backfilled income category on {res.modified_count} quote/invoice docs")
    except Exception as e:
        logger.warning(f"income category backfill skipped: {e}")
    # Seed legal documents (idempotent).
    try:
        await legal.ensure_seeded()
    except Exception as e:
        logger.warning(f"legal doc seed skipped: {e}")
    # Seed marketing templates + sequences (idempotent, Phase 7).
    try:
        await marketing_studio._seed_templates()
        await sequences.ensure_sequences_seeded()
        await ai_ops.ensure_ai_employees_seeded()
    except Exception as e:
        logger.warning(f"phase-7 seeds skipped: {e}")
    # Phase 15B: mark demo admin as onboarded so the wizard doesn't hijack the demo.
    try:
        await onboarding._seed_completed_for_demo()
    except Exception as e:
        logger.warning(f"onboarding demo seed skipped: {e}")
    # Phase 15B slot-in: seed the Lead Request form template (idempotent).
    try:
        await lead_requests._seed_lead_request_form()
    except Exception as e:
        logger.warning(f"lead-request form seed skipped: {e}")
    # Phase 15D Stage 1: seed default tenant + backfill tenant_id on every
    # collection. Idempotent — only touches rows missing the field.
    try:
        await tenants.run_tenant_backfill()
    except Exception as e:
        logger.warning(f"tenant backfill skipped: {e}")
    # Phase 15D Stage 2: seed super_admin account.
    try:
        await tenants._seed_super_admin()
    except Exception as e:
        logger.warning(f"super_admin seed skipped: {e}")
    # Phase 16B — seed Business OS assets (SOPs / roles / KPIs / LeanBoards).
    try:
        await business_os.seed_business_os()
    except Exception as e:
        logger.warning(f"phase 16B seeds skipped: {e}")
    # Background auto-publish drip: check for due SEO articles every 10 minutes.
    scheduler.add_job(seo.run_due_publishes, "interval", minutes=10, id="seo_drip", replace_existing=True)
    # Auto-bill accrued chemical invoices once a month (checked daily; bills months that have ended).
    scheduler.add_job(finances.run_monthly_chem_billing, "interval", hours=24, id="chem_billing", replace_existing=True)
    # Auto-revert temporary route coverage after its week ends (checked daily).
    scheduler.add_job(coverage.revert_expired_coverage, "interval", hours=12, id="coverage_revert", replace_existing=True)
    # Assess automatic late fees on unpaid invoices past their grace period (daily @ 02:00 UTC).
    scheduler.add_job(finances.run_late_fee_assessment, "cron", hour=2, minute=0, id="late_fees", replace_existing=True)
    # Phase 7: marketing autopost + sequence ticker.
    scheduler.add_job(marketing_studio.run_marketing_autopost, "interval", minutes=10, id="marketing_autopost", replace_existing=True)
    scheduler.add_job(sequences.run_sequences_tick, "interval", minutes=15, id="sequences_tick", replace_existing=True)
    # Phase 15A — CSAT auto-send dispatcher (checks pending survey queue every 5 min).
    scheduler.add_job(csat.run_csat_dispatch_tick, "interval", minutes=5, id="csat_dispatch", replace_existing=True)
    scheduler.start()
    logger.info("SEO auto-publish + chemical billing + late-fee + marketing_autopost + sequences_tick schedulers registered")


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    client.close()
