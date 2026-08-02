"""Phase 27 follow-up — seed one demo job assigned to Luis Marquez for
today's date so the tester can visually verify the Phase 27 avatar
swap on both:

  * ``/schedule`` (CalendarSchedule Grid mode)
  * Dispatch Board (TechLoadStrip)

Idempotent: the row is keyed by the stable id ``seed-phase27-today-job``.
Second run is a no-op that only updates ``scheduled_date`` to today (so
the tester never has to hunt for the job on a stale calendar day) and
``updated_at``.

Usage::

    python3 scripts/seed_phase27_demo_job.py [--dry-run]

Notes:
  * Tenant + tech user_id are pinned to the seed values that ship with
    the demo pod. If the seed pipeline ever re-generates them, this
    script logs a WARNING and exits cleanly — it will not create
    orphaned rows.
  * Job schema matches the ``db.jobs`` documents already present in
    the demo tenant (verified via a sample read). No new fields are
    invented.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import os                                                # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_phase27_demo_job")

# ── Constants pinned to the demo pod. ────────────────────────────
SEED_JOB_ID           = "seed-phase27-today-job"
DEMO_TENANT_ID        = "3814833a-dd0d-4bd9-90ea-351c24924649"
LUIS_USER_ID          = "e024e983-8515-4223-9e3f-1780ace5bf08"
LUIS_NAME             = "Luis Marquez"
LUIS_EMAIL            = "landscaper@aquaterra.com"

# Peoria, AZ (Vistancia neighborhood — matches the demo tenant name).
DEMO_LAT              = 33.7734
DEMO_LON              = -112.2378


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _preflight(db) -> Optional[Dict[str, Any]]:
    """Confirm the pinned tenant + Luis user still exist before writing.

    Returns Luis's user document on success, ``None`` if either is
    missing — in which case we log a WARNING and exit cleanly so we
    never leave orphan rows behind.
    """
    tenant = await db.tenants.find_one({"id": DEMO_TENANT_ID},
                                        {"_id": 0, "id": 1, "name": 1})
    if not tenant:
        log.warning("Demo tenant %s not found — bailing.", DEMO_TENANT_ID)
        return None
    user = await db.users.find_one(
        {"id": LUIS_USER_ID, "tenant_id": DEMO_TENANT_ID},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
         "technician_id": 1, "profile_photo_url": 1},
    )
    if not user:
        # Try email lookup as a fallback (seed re-run drift).
        user = await db.users.find_one(
            {"email": LUIS_EMAIL, "tenant_id": DEMO_TENANT_ID},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
             "technician_id": 1, "profile_photo_url": 1},
        )
        if not user:
            log.warning(
                "Luis Marquez (%s / %s) not found — bailing.",
                LUIS_USER_ID, LUIS_EMAIL,
            )
            return None
        log.info(
            "Note: Luis user_id has drifted from the pinned value; "
            "using db value %s.", user["id"],
        )
    return user


async def seed(dry_run: bool = False) -> Optional[str]:
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    try:
        user = await _preflight(db)
        if user is None:
            return None
        tech_uid = user["id"]
        now = _now_iso()
        today = _today_iso()

        payload: Dict[str, Any] = {
            "id": SEED_JOB_ID,
            "tenant_id": DEMO_TENANT_ID,
            "customer_id": "seed-phase27-demo-customer",
            "customer_name": "Phase 27 Demo Property",
            "title": "Phase 27 · Weekly Landscape Service",
            "service_type": "Weekly Landscape Service",
            "status": "scheduled",
            "scheduled_date": today,
            "address": "1234 W Vistancia Blvd, Peoria, AZ",
            "latitude": DEMO_LAT,
            "longitude": DEMO_LON,
            "notes": "Seeded by scripts/seed_phase27_demo_job.py — "
                     "used to verify TechAvatar swap.",
            "technician_id": tech_uid,
            "technician_name": user.get("name") or LUIS_NAME,
            "assigned_technician_id": tech_uid,
            "assigned_technician_name": user.get("name") or LUIS_NAME,
            "updated_at": now,
        }
        existing = await db.jobs.find_one({"id": SEED_JOB_ID},
                                           {"_id": 0, "id": 1})

        if dry_run:
            log.info("[dry-run] would %s job %s (assigned to %s)",
                      "update" if existing else "insert",
                      SEED_JOB_ID, tech_uid)
            return SEED_JOB_ID

        if existing:
            r = await db.jobs.update_one(
                {"id": SEED_JOB_ID}, {"$set": payload},
            )
            log.info("Updated job %s (matched=%d, modified=%d)",
                      SEED_JOB_ID, r.matched_count, r.modified_count)
        else:
            payload["created_at"] = now
            await db.jobs.insert_one(payload)
            log.info("Inserted job %s (tenant=%s, tech=%s)",
                      SEED_JOB_ID, DEMO_TENANT_ID, tech_uid)
        return SEED_JOB_ID
    finally:
        client.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    jid = asyncio.run(seed(dry_run=args.dry_run))
    if jid is None:
        return 1
    log.info("Done. Job id = %s", jid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
