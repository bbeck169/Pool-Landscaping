"""Seed script — Phase 34 · Feb-2026
================================================================

Idempotent demo-media seed for the customer portal of
``admin@aquaterra.com``. Provisions:

  - 2 completed jobs on TWO different visit dates
  - 2 service reports (one per job), each with **2 photos** → 4 photos total
  - 2 customer-visible videos (one per job)

This gives testers enough material to visually verify the
Phase 34 portal date-grouping feature on
``/portal/photos``, ``/portal/videos`` and
``/portal/service-reports``.

The script uses **fixed, deterministic IDs** (prefixed with
``seed-portal-media-``) and ``upsert`` operations, so it can be
re-run safely — nothing is duplicated, nothing collides with
production-shaped records.

Usage
-----
::

    cd /app/backend && python -m scripts.seed_portal_media

Environment
-----------
Reads ``MONGO_URL`` + ``DB_NAME`` from the backend ``.env``. No
network calls; nothing is emailed or SMS'd.

Guardrail
---------
This script is **DEV/PREVIEW ONLY**. It targets the
demo tenant that owns ``admin@aquaterra.com``. If that user is not
found the script exits with a non-zero status and touches nothing.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorClient

# Make sure ``backend/.env`` is loaded whether we're invoked from
# ``/app`` or ``/app/backend``.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:  # pragma: no cover — dotenv is a hard dep in this repo
    pass


# ── Configuration ─────────────────────────────────────────────────────
CUSTOMER_EMAIL = "admin@aquaterra.com"

# Two visit dates ~3 weeks apart so the date-group headers are
# clearly distinct in the UI. Times are chosen to fall inside the
# work day.
DATE_A = "2026-02-10"  # newest
DATE_B = "2026-01-20"  # older

# Deterministic IDs keep the seed idempotent.
JOB_A = "seed-portal-media-job-a"
JOB_B = "seed-portal-media-job-b"
REPORT_A = "seed-portal-media-report-a"
REPORT_B = "seed-portal-media-report-b"

# Publicly-hosted placeholder images. Pexels URLs are stable, CDN-
# cached, and don't require an API key. Videos use the tenant's own
# S3/media route path — the actual media file is not required for
# the portal date-group UI verification (the page renders the tile
# from metadata alone; the player will 404 gracefully if the blob
# isn't backed).
POOL_PHOTOS = [
    "https://images.pexels.com/photos/261101/pexels-photo-261101.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/261102/pexels-photo-261102.jpeg?auto=compress&cs=tinysrgb&w=1200",
]
LANDSCAPE_PHOTOS = [
    "https://images.pexels.com/photos/1108572/pexels-photo-1108572.jpeg?auto=compress&cs=tinysrgb&w=1200",
    "https://images.pexels.com/photos/1005058/pexels-photo-1005058.jpeg?auto=compress&cs=tinysrgb&w=1200",
]

VIDEO_A = {
    "id": "seed-portal-media-video-a",
    "storage_path": (
        "poolcrm/{tid}/job/" + JOB_A + "/seed-video-a.mp4"
    ),
    "mime": "video/mp4",
    "size_bytes": 2_450_000,
    "duration_seconds": 24,
    "original_filename": "pool-visit-highlight.mp4",
    "caption": "Weekly pool visit — filter backwash + brushing walls",
}
VIDEO_B = {
    "id": "seed-portal-media-video-b",
    "storage_path": (
        "poolcrm/{tid}/job/" + JOB_B + "/seed-video-b.mp4"
    ),
    "mime": "video/mp4",
    "size_bytes": 3_140_000,
    "duration_seconds": 41,
    "original_filename": "landscape-mow-highlight.mp4",
    "caption": "Front-yard mow + edging pass",
}


def _iso(day_str: str, hh: int, mm: int) -> str:
    """Build an ISO timestamp on the given day (UTC)."""
    y, m, d = [int(x) for x in day_str.split("-")]
    dt = datetime(y, m, d, hh, mm, 0, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


async def _seed() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME missing from environment.",
              file=sys.stderr)
        sys.exit(2)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    user = await db.users.find_one({"email": CUSTOMER_EMAIL})
    if not user:
        print(f"ERROR: user {CUSTOMER_EMAIL} not found — nothing to seed.",
              file=sys.stderr)
        sys.exit(3)

    tenant_id = user["tenant_id"]
    customer_id = user.get("customer_id")
    if not customer_id:
        # Fall back to the customer row by email in the same tenant.
        cust = await db.customers.find_one(
            {"tenant_id": tenant_id, "email": CUSTOMER_EMAIL}
        )
        customer_id = (cust or {}).get("id")
    if not customer_id:
        print(f"ERROR: no customer row linked to {CUSTOMER_EMAIL}.",
              file=sys.stderr)
        sys.exit(4)

    customer_name = (
        await db.customers.find_one({"id": customer_id}, {"_id": 0, "name": 1})
    ) or {}
    customer_name = customer_name.get("name") or "Portal Test Customer"

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    async def _upsert_job(job_id: str, day: str, kind: str,
                          title: str, video_meta: dict) -> None:
        video = {
            **video_meta,
            "storage_path": video_meta["storage_path"].format(tid=tenant_id),
            "uploaded_at": _iso(day, 15, 30),
            "uploaded_by_user_id": "seed-portal-media-tech",
            "uploaded_by_name": "Demo Tech",
            "visibility": "customer",
            "is_deleted": False,
        }
        await db.jobs.update_one(
            {"id": job_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "id": job_id,
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "title": title,
                    "service_type": kind,
                    "scheduled_date": day,
                    "scheduled_start": _iso(day, 14, 0),
                    "status": "completed",
                    "technician_id": "seed-portal-media-tech",
                    "technician_name": "Demo Tech",
                    "address": "9825 W Camino De Oro, Peoria AZ 85383",
                    "notes": "Seed record — see /app/backend/scripts/seed_portal_media.py.",
                    "photos": [],
                    "videos": [video],
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def _upsert_report(report_id: str, job_id: str, day: str,
                             kind: str, photos: list) -> None:
        photo_docs = [
            {
                "url": url,
                "thumb": url,
                "caption": caption,
                "tags": ["customer"],
            }
            for url, caption in photos
        ]
        submitted_at = _iso(day, 16, 15)
        await db.service_reports.update_one(
            {"id": report_id, "tenant_id": tenant_id},
            {
                "$set": {
                    "id": report_id,
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "tech_id": "seed-portal-media-tech",
                    "template": kind,
                    "chemical_readings": [],
                    "chemicals_added": [],
                    "checklist_items": [
                        {"id": f"{report_id}-c1", "label": "Skim + brush walls",
                         "required": True, "checked": True, "notes": None},
                        {"id": f"{report_id}-c2", "label": "Filter check",
                         "required": True, "checked": True, "notes": None},
                    ],
                    "photos": photo_docs,
                    "videos": [],
                    "notes": (
                        "Everything looked great — pool clear, "
                        "equipment running normally."
                        if kind == "pool"
                        else "Lawn cut short of the drought stress zone; "
                             "trimmed hedge fronts and edged walk."
                    ),
                    "customer_notes": (
                        "Skimmed, brushed, chlorine dosed. "
                        "Water clarity excellent."
                        if kind == "pool"
                        else "Mow + edge complete. Beds refreshed."
                    ),
                    "public_uuid": f"public-{report_id}",
                    "status": "submitted",
                    "started_at": _iso(day, 14, 5),
                    "submitted_at": submitted_at,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    # ── DATE A — pool visit ────────────────────────────────────────
    await _upsert_job(JOB_A, DATE_A, "pool",
                      "Weekly pool service", VIDEO_A)
    await _upsert_report(
        REPORT_A, JOB_A, DATE_A, "pool",
        photos=[
            (POOL_PHOTOS[0], "Water crystal clear after brush + shock"),
            (POOL_PHOTOS[1], "Skimmer basket cleared, cover latched"),
        ],
    )

    # ── DATE B — landscape visit ───────────────────────────────────
    await _upsert_job(JOB_B, DATE_B, "landscape",
                      "Bi-weekly landscape service", VIDEO_B)
    await _upsert_report(
        REPORT_B, JOB_B, DATE_B, "landscape",
        photos=[
            (LANDSCAPE_PHOTOS[0], "Front lawn — freshly mowed"),
            (LANDSCAPE_PHOTOS[1], "Backyard hedge line — trimmed & edged"),
        ],
    )

    # ── Summary ──────────────────────────────────────────────────
    photos_count = await db.service_reports.count_documents(
        {"tenant_id": tenant_id,
         "id": {"$in": [REPORT_A, REPORT_B]}}
    )
    jobs_count = await db.jobs.count_documents(
        {"tenant_id": tenant_id, "id": {"$in": [JOB_A, JOB_B]}}
    )
    print("Portal media seed complete")
    print(f"  tenant_id     = {tenant_id}")
    print(f"  customer_id   = {customer_id}")
    print(f"  jobs upserted = {jobs_count}")
    print(f"  reports       = {photos_count} × (2 photos each = 4 photos)")
    print(f"  videos        = 2  (visibility=customer)")
    print(f"  dates         = {DATE_A}, {DATE_B}")
    client.close()


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
