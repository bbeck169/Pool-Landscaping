"""Feb-2026 · Optimize Route fixture seed.

Idempotent seed that ensures at least one same-day / same-tech
scenario exists in the preview Mongo so the tester can exercise the
``POST /api/schedule/optimize-route`` Google Directions v2 + Haversine
fallback branches end-to-end.

Fixture shape (4 stops, one tech, real-ish Phoenix-metro coordinates):

  ┌──────────┬─────────────┬──────────────────────────────┬──────────────┐
  │ Job ID   │ Time        │ Address                      │ (lat, lng)   │
  ├──────────┼─────────────┼──────────────────────────────┼──────────────┤
  │ seed-opt-1 │ 08:00 local │ 1234 W Vistancia Blvd, Peoria │ (33.7734, -112.2378) │
  │ seed-opt-2 │ 09:30 local │ 6825 W Bell Rd, Glendale     │ (33.6389, -112.2016) │
  │ seed-opt-3 │ 11:00 local │ 2800 N 15th Ave, Phoenix     │ (33.4823, -112.0916) │
  │ seed-opt-4 │ 13:00 local │ 4155 N 44th St, Phoenix      │ (33.4948, -111.9840) │
  └──────────┴─────────────┴──────────────────────────────┴──────────────┘

Date: **+14 days from today** (recomputed on every run so the fixture
never rots; +14 keeps it outside the 1-10 day window the live route-
optimization approval test suite uses). ``scheduled_start`` is written
as an ISO-UTC timestamp because the optimize-route router filters on
that field exactly.

Tech: reuses **Mike Rivera** (``mike@aquaterra.com`` — pinned by
email lookup because the seed pod's user_id can drift). Falls back
to any user with ``role="technician"`` if Mike is missing.

Usage::

    python3 backend/scripts/seed_optimize_route_fixture.py [--dry-run]

Second and subsequent runs update ``scheduled_date``/``scheduled_start``
+ ``updated_at`` only — never duplicate rows.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_optimize_route_fixture")


# ── Auto-discovered per pod at runtime. We look up the tenant by
#    slug ("aquaterra") because the pinned demo pod's tenant_id
#    drifts across forks — the slug is stable in every fork.
DEMO_TENANT_SLUG = "aquaterra"
TECH_EMAIL       = "mike@aquaterra.com"       # Mike Rivera — pool tech
FIXTURE_CUSTOMER_ID = "seed-optimize-route-customer"


# ── Fixture rows. Times are local Phoenix (UTC−7 no DST). We
#    convert to UTC before writing. Each stop gets its own dedicated
#    property row (``property_id``) so the ``resolve_stop_geo``
#    resolver returns correct per-stop coords — without a dedicated
#    property the customer→property auto-backfill attaches ALL jobs
#    to a single shared property (customer's address), which collapses
#    every optimize-route call to a zero-distance response.
# ─────────────────────────────────────────────────────────────────
FIXTURE_STOPS: List[Dict[str, Any]] = [
    {"job_id": "seed-opt-1", "property_id": "seed-opt-prop-1",
     "start_local_hhmm": "08:00",
     "title": "Weekly Pool Service",
     "address": "1234 W Vistancia Blvd, Peoria, AZ 85383",
     "postal_code": "85383",
     "lat": 33.7734, "lng": -112.2378},
    {"job_id": "seed-opt-2", "property_id": "seed-opt-prop-2",
     "start_local_hhmm": "09:30",
     "title": "Salt Cell Replacement",
     "address": "6825 W Bell Rd, Glendale, AZ 85308",
     "postal_code": "85308",
     "lat": 33.6389, "lng": -112.2016},
    {"job_id": "seed-opt-3", "property_id": "seed-opt-prop-3",
     "start_local_hhmm": "11:00",
     "title": "Filter Cartridge Service",
     "address": "2800 N 15th Ave, Phoenix, AZ 85021",
     "postal_code": "85021",
     "lat": 33.4823, "lng": -112.0916},
    {"job_id": "seed-opt-4", "property_id": "seed-opt-prop-4",
     "start_local_hhmm": "13:00",
     "title": "Chemical Rebalance",
     "address": "4155 N 44th St, Phoenix, AZ 85018",
     "postal_code": "85018",
     "lat": 33.4948, "lng": -111.9840},
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fixture_date_iso() -> str:
    # Fixture lives at today+14 days — outside the 1-10 day window
    # used by the live route-optimization approval test suite (which
    # calls ``_future_date(1..10)``), so our seeded jobs never pollute
    # ``TEST_optroute_*`` fixtures on the shared preview Mongo.
    return (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()


def _to_utc_iso(date_iso: str, hhmm: str) -> str:
    """Convert local Phoenix (UTC−7 static — no DST in AZ) → UTC ISO."""
    h, m = hhmm.split(":")
    # Phoenix stays on MST year-round → +7h to reach UTC.
    utc_dt = datetime(
        int(date_iso[0:4]), int(date_iso[5:7]), int(date_iso[8:10]),
        int(h), int(m), 0, tzinfo=timezone.utc,
    ) + timedelta(hours=7)
    return utc_dt.isoformat()


async def _find_tech(db, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Look up Mike Rivera by email, then fall back to any tech."""
    user = await db.users.find_one(
        {"email": TECH_EMAIL, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
          "technician_id": 1, "role": 1},
    )
    if user:
        return user
    log.warning("%s not found — falling back to any technician.", TECH_EMAIL)
    fallback = await db.users.find_one(
        {"tenant_id": tenant_id, "role": "technician"},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
          "technician_id": 1, "role": 1},
    )
    if fallback:
        log.info("Using fallback tech %s (%s).",
                  fallback.get("name"), fallback.get("email"))
    return fallback


async def _upsert_property(db, tenant_id: str,
                             stop: Dict[str, Any], dry_run: bool) -> None:
    """Dedicated property row per stop so ``resolve_stop_geo`` returns
    the correct per-job coords. Without this the customer→property
    auto-backfill attaches ALL jobs to a single shared property
    (using the customer's address) and every optimize-route call
    collapses to a zero-distance response.

    Uses stable ids (``seed-opt-prop-N``) so subsequent runs update
    in place.
    """
    now = _now_iso()
    pid = stop["property_id"]
    if dry_run:
        log.info("[dry-run] would upsert property %s @ (%s, %s)",
                  pid, stop["lat"], stop["lng"])
        return
    # Store the address as the structured shape the resolver reads.
    addr_struct = {
        "line1": stop["address"], "line2": None,
        "city": None, "state": None,
        "postal_code": stop.get("postal_code"), "country": "US",
    }
    await db.properties.update_one(
        {"id": pid, "tenant_id": tenant_id},
        {
            "$setOnInsert": {
                "id": pid,
                "tenant_id": tenant_id,
                "customer_id": FIXTURE_CUSTOMER_ID,
                "created_at": now,
            },
            "$set": {
                "label": stop["title"],
                "address": addr_struct,
                "lat": stop["lat"],
                "lng": stop["lng"],
                "active": True,
                # Skip lazy-geocode — coords are canonical.
                "geocoded_at": now,
                "geocoded_address": stop["address"],
                "updated_at": now,
            },
        },
        upsert=True,
    )


async def _upsert_customer(db, tenant_id: str, dry_run: bool) -> None:
    """Single fixture customer that all 4 jobs link to (satisfies the
    ``customers.find_one`` requirement in ``create_job`` when the
    tester exercises write paths downstream). Idempotent."""
    now = _now_iso()
    if dry_run:
        log.info("[dry-run] would upsert customer %s", FIXTURE_CUSTOMER_ID)
        return
    await db.customers.update_one(
        {"id": FIXTURE_CUSTOMER_ID, "tenant_id": tenant_id},
        {
            "$setOnInsert": {
                "id": FIXTURE_CUSTOMER_ID,
                "tenant_id": tenant_id,
                "created_at": now,
                "is_active": True,
            },
            "$set": {
                "name": "Optimize Route Fixture · Multi-stop Day",
                "address": FIXTURE_STOPS[0]["address"],
                "latitude": FIXTURE_STOPS[0]["lat"],
                "longitude": FIXTURE_STOPS[0]["lng"],
                "service_lat": FIXTURE_STOPS[0]["lat"],
                "service_lng": FIXTURE_STOPS[0]["lng"],
                "service_address": FIXTURE_STOPS[0]["address"],
                "service_days": ["mon", "tue", "wed",
                                    "thu", "fri", "sat", "sun"],
                "updated_at": now,
            },
        },
        upsert=True,
    )


async def _upsert_job(db, tenant_id: str, tech: Dict[str, Any],
                       stop: Dict[str, Any], date_iso: str,
                       dry_run: bool) -> Dict[str, Any]:
    now = _now_iso()
    scheduled_start = _to_utc_iso(date_iso, stop["start_local_hhmm"])
    payload: Dict[str, Any] = {
        "id": stop["job_id"],
        "tenant_id": tenant_id,
        "customer_id": FIXTURE_CUSTOMER_ID,
        "customer_name": "Optimize Route Fixture · Multi-stop Day",
        # P1 · Per-stop property so ``resolve_stop_geo`` returns
        # the correct per-job coords (no shared-property collapse).
        "property_id": stop["property_id"],
        "property_label": stop["title"],
        "title": stop["title"],
        "service_type": stop["title"],
        "status": "scheduled",
        "scheduled_date": date_iso,
        "scheduled_start": scheduled_start,
        "address": stop["address"],
        "postal_code": stop.get("postal_code"),
        # Both shapes on the job doc — the optimizer reads either.
        "latitude": stop["lat"],
        "longitude": stop["lng"],
        "site_lat": stop["lat"],
        "site_lng": stop["lng"],
        # Every write-side identity field the codebase historically
        # populates. Keeps ``effective_tid`` reads consistent.
        "technician_id": tech["id"],
        "technician_name": tech.get("name") or "Fixture Tech",
        "assigned_technician_id": tech["id"],
        "assigned_technician_name": tech.get("name") or "Fixture Tech",
        "assigned_to": tech["id"],
        "tech_user_id": tech["id"],
        "notes": "Seeded by scripts/seed_optimize_route_fixture.py — "
                  "used by the tester to exercise "
                  "POST /api/schedule/optimize-route branches.",
        "updated_at": now,
    }
    existing = await db.jobs.find_one({"id": stop["job_id"]},
                                        {"_id": 0, "id": 1})
    if dry_run:
        log.info("[dry-run] would %s job %s @ %s (tech=%s)",
                  "update" if existing else "insert",
                  stop["job_id"], scheduled_start, tech["id"])
        return payload
    if existing:
        await db.jobs.update_one(
            {"id": stop["job_id"]}, {"$set": payload},
        )
        log.info("Updated job %s @ %s", stop["job_id"], scheduled_start)
    else:
        payload["created_at"] = now
        await db.jobs.insert_one(payload)
        log.info("Inserted job %s @ %s", stop["job_id"], scheduled_start)
    return payload


async def _resolve_tenant(db) -> Optional[Dict[str, Any]]:
    """Locate the demo tenant on any pod.

    Resolution order:
      1. Slug lookup (``aquaterra``) — stable on the shared preview pod.
      2. Single-tenant pod fallback — when the pod has exactly one
         tenant (fresh dev container, forked pod), just use it.

    Returns ``None`` when both strategies fail so the caller can
    surface a helpful error instead of writing to the wrong tenant.
    """
    tenant = await db.tenants.find_one(
        {"slug": DEMO_TENANT_SLUG}, {"_id": 0, "id": 1, "name": 1, "slug": 1},
    )
    if tenant:
        return tenant
    # Slug missing — see if the pod has exactly one tenant.
    total = await db.tenants.count_documents({})
    if total == 1:
        only = await db.tenants.find_one(
            {}, {"_id": 0, "id": 1, "name": 1, "slug": 1},
        )
        if only:
            log.info(
                "Slug %r not found but pod has exactly one tenant — "
                "using %r (%s).",
                DEMO_TENANT_SLUG, only.get("name"), only.get("id"),
            )
            return only
    return None


async def seed(dry_run: bool = False) -> Dict[str, Any]:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    try:
        tenant = await _resolve_tenant(db)
        if not tenant:
            log.error(
                "No usable tenant — slug=%r missing and pod has ≠1 "
                "tenants. Bailing.",
                DEMO_TENANT_SLUG,
            )
            return {"ok": False, "reason": "tenant_missing"}
        tenant_id = tenant["id"]
        tech = await _find_tech(db, tenant_id)
        if not tech:
            log.error("No usable technician in tenant %s — bailing.",
                       tenant_id)
            return {"ok": False, "reason": "tech_missing"}

        date_iso = _fixture_date_iso()
        await _upsert_customer(db, tenant_id, dry_run)

        job_ids: List[str] = []
        for stop in FIXTURE_STOPS:
            # Per-stop property MUST land before the job insert so
            # the ``resolve_stop_geo`` resolver never falls back to
            # the auto-backfill's shared customer-address property.
            await _upsert_property(db, tenant_id, stop, dry_run)
            await _upsert_job(db, tenant_id, tech, stop, date_iso, dry_run)
            job_ids.append(stop["job_id"])

        result = {
            "ok": True,
            "date": date_iso,
            "tenant_id": tenant_id,
            "technician_user_id": tech["id"],
            "technician_email": tech.get("email"),
            "job_ids": job_ids,
            "stop_count": len(job_ids),
        }
        log.info("Fixture ready:")
        log.info("  Date:                %s", result["date"])
        log.info("  Tenant:              %s", result["tenant_id"])
        log.info("  Technician:          %s (%s)",
                  result["technician_email"], result["technician_user_id"])
        log.info("  Job IDs:             %s", ", ".join(job_ids))
        log.info("  Test URL (POST):     /api/schedule/optimize-route")
        log.info("  Test body:           %s",
                  {"date": result["date"],
                   "technician_id": result["technician_user_id"]})
        return result
    finally:
        client.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = asyncio.run(seed(dry_run=args.dry_run))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
