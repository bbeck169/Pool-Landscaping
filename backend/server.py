from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import client, db, logger
from seed import seed, seed_extras
from routers import (
    auth, customers, technicians, jobs, quotes, leads, team, items, payments,
    operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin,
)

app = FastAPI(
    title="Pool CRM API",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
api_router = APIRouter(prefix="/api")

for module in [auth, customers, technicians, jobs, quotes, leads, team, items, payments,
               operations, finances, marketing, admin, dashboard, portal, seo, gbp, card, maintenance, d2d, estimates, coverage, attendance, render, cad, measurements, property, weather, impexp, chemicals, billing, portal_admin]:
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
    # Background auto-publish drip: check for due SEO articles every 10 minutes.
    scheduler.add_job(seo.run_due_publishes, "interval", minutes=10, id="seo_drip", replace_existing=True)
    # Auto-bill accrued chemical invoices once a month (checked daily; bills months that have ended).
    scheduler.add_job(finances.run_monthly_chem_billing, "interval", hours=24, id="chem_billing", replace_existing=True)
    # Auto-revert temporary route coverage after its week ends (checked daily).
    scheduler.add_job(coverage.revert_expired_coverage, "interval", hours=12, id="coverage_revert", replace_existing=True)
    scheduler.start()
    logger.info("SEO auto-publish + chemical billing schedulers started")


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    client.close()
