"""Phase T6 companion — Seed 4 system-owned document_templates.

Idempotent by (is_system=True, code). Run in-session via:
    python -m migrations.seed_canonical_templates

Templates land as `is_system: True, tenant_id: "system"` so a future
T4.1 UI update can badge them SYSTEM and require clone-to-edit.
"""
from __future__ import annotations
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from config import db
from utils import now_iso, new_id


CANONICAL_POOL_CHECKLIST = [
    "Skim surface & empty baskets", "Brush walls & tile line",
    "Vacuum pool", "Empty pump basket", "Backwash filter if needed",
    "Check equipment operation", "Test water chemistry",
    "Add chemicals as needed", "Log readings & notes",
    "Secure gate on exit",
]
CANONICAL_LANDSCAPE_CHECKLIST = [
    "Sprayed or Pulled Weeds", "Checked Irrigation", "Trimmed Bushes",
    "Mowed Grass", "Edged Grass", "Blow Property", "Raked Rocks",
    "Locked Gate", "Trimmed Trees", "Irrigation Repair",
]
NEW_CUSTOMER_ONBOARDING = [
    "Measured pool volume (L × W × avg depth × 7.48)",
    "Recorded pool shape + condition",
    "Noted equipment brands + model numbers (pump / filter / heater / SWG)",
    "Logged gate code + access notes",
    "Verified customer contact + billing info",
    "Took before-photo: equipment pad",
    "Took before-photo: pool walls",
    "Took before-photo: plumbing / valves",
    "Confirmed visit day preference",
    "Left welcome packet on-site",
]
WINTERIZATION_POOL = [
    "Drained lines to below freeze depth", "Lowered water level",
    "Added polyquat / winterizer", "Disconnected heater breaker",
    "Blew out plumbing lines with compressor", "Installed safety cover",
    "Logged closing chemistry (pH, Alk, hardness)",
    "Photographed equipment shutdown state",
]

TEMPLATES = [
    {
        "code": "weekly_pool_service",
        "name": "Weekly Pool Service",
        "visit_type": "pool",
        "readings_rows": ["pH", "Chlorine", "Alkalinity",
                            "Calcium Hardness", "CYA", "Salt", "Temp"],
        "checklist_items": CANONICAL_POOL_CHECKLIST,
    },
    {
        "code": "weekly_landscape",
        "name": "Weekly Landscape Maintenance",
        "visit_type": "landscape",
        "readings_rows": [],
        "checklist_items": CANONICAL_LANDSCAPE_CHECKLIST,
    },
    {
        "code": "new_customer_onboarding",
        "name": "New Customer Onboarding",
        "visit_type": "both",
        "readings_rows": ["pH", "Chlorine", "Alkalinity", "Calcium Hardness", "CYA", "Salt"],
        "checklist_items": NEW_CUSTOMER_ONBOARDING,
    },
    {
        "code": "winterization",
        "name": "Winterization Service",
        "visit_type": "pool",
        "readings_rows": ["pH", "Chlorine", "Alkalinity", "Calcium Hardness"],
        "checklist_items": WINTERIZATION_POOL,
    },
]


async def main():
    seeded = []
    skipped = []
    now = now_iso()
    for t in TEMPLATES:
        existing = await db.document_templates.find_one(
            {"is_system": True, "code": t["code"]}, {"_id": 0, "id": 1})
        if existing:
            skipped.append(t["code"])
            continue
        doc = {
            "id": new_id(),
            "is_system": True,
            "tenant_id": "system",
            "code": t["code"],
            "name": t["name"],
            "visit_type": t["visit_type"],
            "readings_rows": t["readings_rows"],
            "checklist_items": t["checklist_items"],
            "include_photos_section": True,
            "include_customer_signature_line": True,
            "include_tech_signature_line": True,
            "include_notes_section": True,
            "include_notes_internal": True,
            "include_notes_customer": True,
            "created_by": "system",
            "created_at": now,
            "updated_at": now,
        }
        await db.document_templates.insert_one(doc)
        seeded.append(t["code"])
    print(f"seeded: {seeded}")
    print(f"skipped (already present): {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
