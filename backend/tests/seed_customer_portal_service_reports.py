"""Phase 56.16-followup — seed 2 submitted service reports for the demo
customer (customer@aquaterra.com) so the customer portal UI has real data.

Creates:
- 1 completed POOL job + submitted pool service_report (readings,
  chemicals added, checklist, mixed photos including `internal` + `issue`
  tagged photos to prove backend redaction, customer_notes, and
  algae_remediation observation).
- 1 completed LANDSCAPE job + submitted landscape service_report with
  the canonical Phase 56.16 10-item list + customer_notes.

Safe to re-run (idempotent by test-marker `phase56_16_followup_seed`).

Usage:
    python /app/backend/tests/seed_customer_portal_service_reports.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from datetime import datetime, timezone, timedelta  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
import uuid  # noqa: E402


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _new_id():
    return str(uuid.uuid4())


async def main():
    env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    client = AsyncIOMotorClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]

    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        print("ERROR: aquaterra tenant not found")
        return 1
    tid = tenant["id"]

    user = await db.users.find_one(
        {"email": "customer@aquaterra.com", "role": "customer"}, {"_id": 0}
    )
    if not user:
        print("ERROR: customer@aquaterra.com user not found")
        return 1
    cid = user.get("customer_id")
    if not cid:
        print("ERROR: customer user has no customer_id linkage")
        return 1

    customer = await db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0})
    if not customer:
        print(f"ERROR: customer record {cid} not in tenant {tid}")
        return 1

    tech = (
        await db.users.find_one(
            {"email": "mike@aquaterra.com", "role": "technician"}, {"_id": 0}
        )
        or {}
    )
    tech_id = tech.get("technician_id") or tech.get("id") or "seed-tech"
    tech_name = tech.get("name") or "Mike Rivera"

    now = datetime.now(timezone.utc)
    pool_visit = now - timedelta(days=3)
    landscape_visit = now - timedelta(days=1)

    marker = "phase56_16_followup_seed"

    # ── POOL job + report ───────────────────────────────────────────────
    existing_pool = await db.service_reports.find_one(
        {"tenant_id": tid, "customer_id": cid, "template": "pool",
         "seed_marker": marker}, {"_id": 0}
    )
    if existing_pool:
        print(f"Pool seed already present: sr={existing_pool['id']}")
        pool_sr_id = existing_pool["id"]
    else:
        pool_job_id = _new_id()
        pool_job = {
            "id": pool_job_id,
            "tenant_id": tid,
            "customer_id": cid,
            "customer_name": customer.get("name"),
            "technician_id": tech_id,
            "technician_name": tech_name,
            "title": "Weekly Pool Service",
            "service_type": "Pool Cleaning",
            "job_type": "pool",
            "address": customer.get("address") or customer.get("service_address"),
            "status": "completed",
            "scheduled_start": _iso(pool_visit),
            "scheduled_end": _iso(pool_visit + timedelta(hours=1)),
            "price": 120.0,
            "photos": [],
            "created_at": _iso(pool_visit - timedelta(hours=6)),
            "seed_marker": marker,
        }
        await db.jobs.insert_one(pool_job)

        pool_sr_id = _new_id()
        pool_sr = {
            "id": pool_sr_id,
            "tenant_id": tid,
            "job_id": pool_job_id,
            "customer_id": cid,
            "tech_id": tech_id,
            "tech_name": tech_name,
            "template": "pool",
            "status": "submitted",
            "chemical_readings": [
                {"key": "combined_chlorine", "name": "Combined Chlorine",
                 "unit": "ppm", "value": "0.2"},
                {"key": "chlorine", "name": "Free Chlorine",
                 "unit": "ppm", "value": "2.0"},
                {"key": "ph", "name": "pH", "unit": "", "value": "7.5"},
                {"key": "alkalinity", "name": "Total Alkalinity",
                 "unit": "ppm", "value": "100"},
                {"key": "cyanuric", "name": "Cyanuric Acid",
                 "unit": "ppm", "value": "40"},
                {"key": "salt", "name": "Salt", "unit": "ppm", "value": "3200"},
            ],
            "chemicals_added": [
                {"name": "Liquid Chlorine", "amount": "1.0", "unit": "gal",
                 "category": "sanitizer"},
                {"name": "Muriatic Acid", "amount": "16", "unit": "oz",
                 "category": "ph_adjust"},
                {"name": "Algaecide", "amount": "8", "unit": "oz",
                 "category": "algae_remediation"},
            ],
            "checklist_items": [
                {"id": _new_id(), "label": "Test & balance water chemistry",
                 "required": True, "checked": True, "notes": None},
                {"id": _new_id(), "label": "Skim surface & empty baskets",
                 "required": True, "checked": True, "notes": None},
                {"id": _new_id(), "label": "Brush walls, steps & tile line",
                 "required": True, "checked": True, "notes": None},
                {"id": _new_id(), "label": "Vacuum pool floor",
                 "required": True, "checked": True, "notes": None},
                {"id": _new_id(), "label": "Check filter pressure / backwash",
                 "required": False, "checked": True, "notes": None},
                {"id": _new_id(), "label": "Inspect pump & equipment",
                 "required": True, "checked": True, "notes": None},
            ],
            "not_tested_flags": {},
            "observations": {"visible_algae": "light"},
            "notes": "",
            "customer_notes": (
                "Pool looked great after treatment — clarity restored and "
                "chemistry balanced. Recommend running your pump 8 hours "
                "daily during this heat wave."
            ),
            # INTERNAL — must NEVER leak to the customer portal.
            "internal_notes": (
                "SEEDED-INTERNAL: raise CYA to 50 next week; skimmer basket "
                "showing crack, monitor. Do not surface to customer."
            ),
            "photos": [
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1562016600-ece13e8ba570?auto=format&fit=crop&w=640&q=70",
                 "label": "Pool after service",
                 "tags": ["after"]},
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1571902943202-507ec2618e8f?auto=format&fit=crop&w=640&q=70",
                 "label": "Equipment area — SEED INTERNAL",
                 "tags": ["internal"]},
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1571902943202-507ec2618e8f?auto=format&fit=crop&w=640&q=70",
                 "label": "Cracked skimmer basket — SEED ISSUE",
                 "tags": ["issue"]},
            ],
            "started_at": _iso(pool_visit),
            "submitted_at": _iso(pool_visit + timedelta(hours=1)),
            "created_at": _iso(pool_visit),
            "updated_at": _iso(pool_visit + timedelta(hours=1)),
            "seed_marker": marker,
        }
        await db.service_reports.insert_one(pool_sr)
        print(f"Seeded pool sr={pool_sr_id} + job={pool_job_id}")

    # ── LANDSCAPE job + report ─────────────────────────────────────────
    existing_land = await db.service_reports.find_one(
        {"tenant_id": tid, "customer_id": cid, "template": "landscape",
         "seed_marker": marker}, {"_id": 0}
    )
    if existing_land:
        print(f"Landscape seed already present: sr={existing_land['id']}")
        land_sr_id = existing_land["id"]
    else:
        land_job_id = _new_id()
        land_job = {
            "id": land_job_id,
            "tenant_id": tid,
            "customer_id": cid,
            "customer_name": customer.get("name"),
            "technician_id": tech_id,
            "technician_name": tech_name,
            "title": "Monthly Landscape Maintenance",
            "service_type": "Landscaping",
            "job_type": "landscape",
            "address": customer.get("address") or customer.get("service_address"),
            "status": "completed",
            "scheduled_start": _iso(landscape_visit),
            "scheduled_end": _iso(landscape_visit + timedelta(hours=2)),
            "price": 180.0,
            "photos": [],
            "created_at": _iso(landscape_visit - timedelta(hours=6)),
            "seed_marker": marker,
        }
        await db.jobs.insert_one(land_job)

        # Canonical 10-item order from config_landscape_checklist.
        land_labels = [
            "Sprayed or Pulled Weeds",
            "Checked Irrigation",
            "Trimmed Bushes",
            "Mowed Grass",
            "Edged Grass",
            "Blow Property",
            "Raked Rocks",
            "Locked Gate",
            "Trimmed Trees",
            "Irrigation Repair",
        ]
        land_sr_id = _new_id()
        land_sr = {
            "id": land_sr_id,
            "tenant_id": tid,
            "job_id": land_job_id,
            "customer_id": cid,
            "tech_id": tech_id,
            "tech_name": tech_name,
            "template": "landscape",
            "status": "submitted",
            "chemical_readings": [],
            "chemicals_added": [],
            "checklist_items": [
                # Mark 8 of 10 as done to reflect a realistic visit —
                # "Trimmed Trees" and "Irrigation Repair" left unchecked.
                {"id": _new_id(), "label": lbl, "required": False,
                 "checked": (lbl not in ("Trimmed Trees", "Irrigation Repair")),
                 "notes": None}
                for lbl in land_labels
            ],
            "not_tested_flags": {},
            "observations": {},
            "notes": "",
            "customer_notes": (
                "Property is looking sharp. Bougainvillea by the back gate "
                "will need a heavier trim next month. Irrigation zones all "
                "cycling normally."
            ),
            "internal_notes": (
                "SEEDED-INTERNAL: replace zone-3 solenoid at next visit; "
                "tools left near garage door — do not surface."
            ),
            "photos": [
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1508163356464-9066f7a6a5d1?auto=format&fit=crop&w=640&q=70",
                 "label": "Trimmed hedgerow", "tags": ["after"]},
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?auto=format&fit=crop&w=640&q=70",
                 "label": "Front lawn edge", "tags": ["after"]},
                {"id": _new_id(),
                 "url": "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?auto=format&fit=crop&w=640&q=70",
                 "label": "Zone 3 controller — SEED ISSUE",
                 "tags": ["issue"]},
            ],
            "started_at": _iso(landscape_visit),
            "submitted_at": _iso(landscape_visit + timedelta(hours=2)),
            "created_at": _iso(landscape_visit),
            "updated_at": _iso(landscape_visit + timedelta(hours=2)),
            "seed_marker": marker,
        }
        await db.service_reports.insert_one(land_sr)
        print(f"Seeded landscape sr={land_sr_id} + job={land_job_id}")

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
