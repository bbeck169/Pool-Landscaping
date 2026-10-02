"""One-shot preview of the Joe & Pat Kail duplicate customers.

Read-only — zero writes. Run via:
    cd /app/backend && python tests/_kail_duplicate_preview.py
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import db  # noqa: E402


# Collections known to carry ``customer_id`` based on the discovery
# grep (see Task 2 step 3 — this list is the explicit set the user
# called out plus any additional ones a quick grep finds).
CUSTOMER_FK_COLLECTIONS = [
    "jobs", "properties", "invoices", "estimates", "quotes",
    "service_reports", "time_entries", "portal_users", "payments",
    "water_bodies", "inventory_reservations", "chemical_applications",
    "messages", "notes", "communications", "customer_notes",
    "autobilling_runs", "subscriptions", "recurring_jobs",
    "service_records", "documents", "equipment", "warranties",
    "pricebook_writeback_rows", "card_tokens",
]


def _redact_pw(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k in {"password", "password_hash", "hashed_password"}:
            continue
        out[k] = v
    return out


async def main():
    # 1. Fuzzy match on name — any customer whose ``name`` matches
    #    "Kail" (case-insensitive).  Also try ``first_name``/
    #    ``last_name`` if the project uses the split-name shape.
    out = {"query_matches": [], "fk_counts": {}, "soft_delete_schema": {}}

    cur = db.customers.find(
        {"name": {"$regex": "Kail", "$options": "i"}}, {"_id": 0},
    )
    matches = []
    async for d in cur:
        matches.append(d)

    # Also run the split-name shape in case the project uses it.
    cur2 = db.customers.find(
        {"$or": [
            {"first_name": {"$regex": "Kail", "$options": "i"}},
            {"last_name": {"$regex": "Kail", "$options": "i"}},
        ]},
        {"_id": 0},
    )
    seen_ids = {m.get("id") for m in matches}
    async for d in cur2:
        if d.get("id") not in seen_ids:
            matches.append(d)
            seen_ids.add(d.get("id"))

    out["query_matches"] = [_redact_pw(m) for m in matches]

    # 2. For each match, FK counts across the known collections.
    for m in matches:
        cid = m.get("id")
        tid = m.get("tenant_id")
        label = f"{cid} ({m.get('name') or m.get('email') or '?'})"
        counts = {}
        for coll in CUSTOMER_FK_COLLECTIONS:
            try:
                counts[coll] = await db[coll].count_documents(
                    {"customer_id": cid, "tenant_id": tid},
                )
            except Exception as e:
                counts[coll] = f"ERROR:{type(e).__name__}"
        out["fk_counts"][label] = counts

    # 3. Soft-delete schema probe on customers.
    sample = await db.customers.find_one({}, {"_id": 0})
    out["soft_delete_schema"] = {
        "has_is_deleted_field": sample is not None and "is_deleted" in sample,
        "has_deleted_at_field": sample is not None and "deleted_at" in sample,
        "has_is_active_field":  sample is not None and "is_active" in sample,
        "sample_keys": sorted(list((sample or {}).keys())),
    }

    # 4. Any additional collections with ``customer_id`` we might've
    #    missed — list all collections and check for at least one doc
    #    with a ``customer_id`` key (sampling-cheap probe).
    extra = []
    for coll_name in await db.list_collection_names():
        if coll_name in CUSTOMER_FK_COLLECTIONS:
            continue
        doc = await db[coll_name].find_one({"customer_id": {"$exists": True}}, {"_id": 0, "customer_id": 1})
        if doc:
            extra.append(coll_name)
    out["extra_collections_with_customer_id"] = extra

    import json
    print(json.dumps(out, default=str, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
