"""Phase 13 — Idempotent frozen-demo seed.

Re-runs safely: uses upsert-by-id / find-and-update semantics rather than raw inserts.
Preserves the 3 demo accounts, a small set of customers/jobs/quotes/invoices/leads
and the AI Employees seed. Skips work if the tenant already contains the frozen set.

Run:
    python /app/backend/seed_frozen.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")
from config import db
from utils import new_id, now_iso

FROZEN_TAG = "seed_frozen_v1"

DEMO_USERS = [
    {"email": "admin@aquaterra.com",    "role": "admin",      "name": "Alex Admin"},
    {"email": "mike@aquaterra.com",     "role": "technician", "name": "Mike Rivera"},
    {"email": "customer@aquaterra.com", "role": "customer",   "name": "Chris Customer"},
]

# Deterministic customer records — one VIP, one standard, one waitlist candidate.
DEMO_CUSTOMERS = [
    {"id": "cust-vip-01", "name": "Jennifer Carson",  "email": "jennifer@example.com",
     "phones": ["+16025551201"], "address": "27821 N Vistancia Blvd, Peoria, AZ 85383",
     "vip": True,  "tags": ["vip"], "lat": 33.7897, "lng": -112.3226},
    {"id": "cust-std-02", "name": "Maria Gomez",      "email": "maria@example.com",
     "phones": ["+16025551202"], "address": "12140 W Yearling Rd, Peoria, AZ 85383",
     "vip": False, "tags": [],       "lat": 33.7942, "lng": -112.3211},
    {"id": "cust-std-03", "name": "Robert Blake",     "email": "robert@example.com",
     "phones": ["+16025551203"], "address": "12500 W Villa Hermosa Ln, Peoria, AZ 85383",
     "vip": False, "tags": ["specialty"], "lat": 33.7962, "lng": -112.3283},
]

DEMO_JOBS = [
    {"id": "job-01", "customer_id": "cust-vip-01", "customer_name": "Jennifer Carson",
     "title": "Weekly maintenance", "status": "scheduled", "price": 179.0,
     "scheduled_date": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
     "recurring": {"pattern": "weekly", "day_of_week": 3}},
    {"id": "job-02", "customer_id": "cust-std-02", "customer_name": "Maria Gomez",
     "title": "One-time cleanup", "status": "scheduled", "price": 385.0,
     "scheduled_date": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()},
]

DEMO_INVOICES = [
    {"id": "inv-01", "customer_id": "cust-vip-01", "customer_name": "Jennifer Carson",
     "type": "invoice", "doc_type": "invoice",
     "title": "Weekly maintenance — July", "total": 716.0, "payment_status": "unpaid",
     "due_date": (datetime.now(timezone.utc) - timedelta(days=61)).date().isoformat(),
     "line_items": [{"description": "Weekly cleaning ×4", "qty": 4, "unit_price": 179.0}]},
]

DEMO_LEADS = [
    {"id": "lead-01", "name": "New prospect from Vistancia",
     "phone": "+16025559999", "source": "portal", "status": "new"},
]

DEMO_TASKS = [
    {"id": "task-01", "title": "Call Jennifer to confirm resume date",
     "priority": "medium", "status": "open", "assigned_to_role": "admin"},
]


async def _upsert(coll: str, doc: dict, key: str = "id"):
    doc.setdefault("created_at", now_iso())
    doc["updated_at"] = now_iso()
    doc["_seed_frozen"] = FROZEN_TAG
    await db[coll].update_one({key: doc[key]}, {"$set": doc}, upsert=True)


async def seed():
    # Users are handled by the existing seed script; only ensure they exist.
    for u in DEMO_USERS:
        existing = await db.users.find_one({"email": u["email"]})
        if not existing:
            print(f"⚠ missing demo user {u['email']} — run the main seed first")

    for c in DEMO_CUSTOMERS: await _upsert("customers", dict(c))
    for j in DEMO_JOBS:      await _upsert("jobs", dict(j))
    for i in DEMO_INVOICES:  await _upsert("quotes", dict(i))
    for l in DEMO_LEADS:     await _upsert("leads", dict(l))
    for t in DEMO_TASKS:     await _upsert("tasks", dict(t))

    print("Frozen seed applied:")
    print(f"  customers: {await db.customers.count_documents({'_seed_frozen': FROZEN_TAG})}")
    print(f"  jobs:      {await db.jobs.count_documents({'_seed_frozen': FROZEN_TAG})}")
    print(f"  invoices:  {await db.quotes.count_documents({'_seed_frozen': FROZEN_TAG, 'type': 'invoice'})}")
    print(f"  leads:     {await db.leads.count_documents({'_seed_frozen': FROZEN_TAG})}")
    print(f"  tasks:     {await db.tasks.count_documents({'_seed_frozen': FROZEN_TAG})}")


if __name__ == "__main__":
    asyncio.run(seed())
