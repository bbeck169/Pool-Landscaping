"""Phase 40 · Feb-2026 — seed the default sick-leave policy + sample
time-off requests for the aquaterra demo tenant.

Also backfills a ``hire_date`` on ``landscaper@aquaterra.com`` (Luis
Marquez) more than 90 days ago so the demo user has usable balance
past the waiting period.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import dotenv_values
from pymongo import MongoClient

BE_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = BE_ENV.get("MONGO_URL")
DB_NAME = BE_ENV.get("DB_NAME")

db = MongoClient(MONGO_URL)[DB_NAME]

TENANT_SLUG = "aquaterra"
tenant = db.tenants.find_one({"slug": TENANT_SLUG})
assert tenant, f"tenant '{TENANT_SLUG}' not found — seed timeoff aborted"
TID = tenant["id"]

# 1) Default policy
policy = db.time_off_policies.find_one({"tenant_id": TID})
if not policy:
    db.time_off_policies.insert_one({
        "id": "policy_" + TID,
        "tenant_id": TID,
        "accrual_numerator": 1,
        "accrual_denominator": 30,
        "annual_cap_hours": 24,
        "waiting_period_days": 90,
        "active": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": None,
    })
    print(f"seed · created time_off_policy for tenant {TID}")
else:
    print(f"seed · policy already present for tenant {TID} — leaving as-is")

# 2) hire_date backfill for landscaper@aquaterra.com
lm = db.users.find_one({"tenant_id": TID, "email": "landscaper@aquaterra.com"})
if lm:
    if not lm.get("hire_date"):
        hire = datetime.now(timezone.utc) - timedelta(days=200)
        db.users.update_one({"id": lm["id"]}, {"$set": {"hire_date": hire}})
        print(f"seed · backfilled hire_date on landscaper@aquaterra.com → {hire.date()}")
    else:
        print("seed · landscaper hire_date already present")
else:
    print("seed · landscaper@aquaterra.com user not found (skipping backfill)")

# 3) Sample time-off requests
mike = db.users.find_one({"tenant_id": TID, "email": "carlos@aquaterra.com"})
if lm and mike and db.time_off_requests.count_documents({"tenant_id": TID}) == 0:
    now_iso = datetime.now(timezone.utc).isoformat()
    def _mk(user_id, offset_days, hours, kind, status, notes=""):
        d = (datetime.now(timezone.utc) + timedelta(days=offset_days)).date().isoformat()
        return {
            "id": f"tor_{user_id[:6]}_{status}_{offset_days}",
            "tenant_id": TID, "user_id": user_id,
            "type": kind, "from_date": d, "to_date": d, "hours": hours,
            "reason": notes or "seed demo",
            "status": status,
            "approver_id": None, "decided_at": None, "decision_notes": "",
            "created_at": now_iso, "updated_at": now_iso,
        }
    seeds = [
        _mk(lm["id"], 7, 8, "sick", "pending", "Feeling under the weather"),
        _mk(lm["id"], 14, 4, "personal", "pending", "Doctor appointment"),
        _mk(mike["id"], -30, 8, "sick", "approved", "Approved sample"),
        _mk(mike["id"], -14, 4, "personal", "rejected", "Rejected sample"),
    ]
    db.time_off_requests.insert_many(seeds)
    print(f"seed · inserted {len(seeds)} sample time_off_requests")
else:
    print("seed · time_off_requests already present or demo users missing")

print("seed · done")
