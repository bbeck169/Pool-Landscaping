"""Ticket 287964 - repair jobs / recurring_job_templates whose property_id
belongs to a DIFFERENT customer.

DRY-RUN by default (prints what it would change, writes nothing).
Pass --apply to write.  Every changed document is first copied, unmodified,
into the ``repair_287964_backup`` collection (restorable by id).

Repair rule for a record whose linked property's customer_id != record.customer_id:
  1. repoint to the customer's own primary property (if it exists, is not
     deleted and is owned by that customer) and, for jobs, refresh the
     stored ``address`` string from it;
  2. otherwise clear property_id (resolver then falls back to the customer's
     own address fields) and, for jobs, refresh ``address`` from the
     customer's service/address/billing string when one exists.

Usage:
  python scripts/repair_cross_customer_property_links.py [--tenant ID] [--future-only]
  python scripts/repair_cross_customer_property_links.py --apply [--tenant ID]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.address_resolver import format_property_address  # noqa: E402

BACKUP = "repair_287964_backup"
COLLECTIONS = ("jobs", "recurring_job_templates")


def _db():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), ".env"))
    except Exception:
        pass
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _customer_fallback_address(cust: dict) -> str:
    for k in ("service_address", "address", "billing_address"):
        v = cust.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def plan_repair(doc: dict, props: dict, custs: dict):
    """Return an update dict, or None when the record is fine.  Pure function."""
    pid, cid = doc.get("property_id"), doc.get("customer_id")
    prop = props.get(pid)
    if not pid or not cid or not prop:
        return None
    owner = prop.get("customer_id")
    if not owner or owner == cid:
        return None
    cust = custs.get(cid) or {}
    own = props.get(cust.get("primary_property_id"))
    if own and not own.get("deleted_at") and own.get("customer_id") in (None, cid) \
            and format_property_address(own):
        upd = {"$set": {"property_id": own["id"]}}
        upd["$set"]["address"] = format_property_address(own)
        return upd
    upd = {"$unset": {"property_id": ""}}
    fb = _customer_fallback_address(cust)
    if fb:
        upd["$set"] = {"address": fb}
    return upd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--tenant")
    ap.add_argument("--future-only", action="store_true",
                    help="only jobs scheduled today or later (templates always included)")
    a = ap.parse_args()
    db = _db()
    today = dt.date.today().isoformat()
    total = 0
    for coll in COLLECTIONS:
        q = {"property_id": {"$nin": [None, ""]}}
        if a.tenant:
            q["tenant_id"] = a.tenant
        if a.future_only and coll == "jobs":
            q["$or"] = [{"scheduled_date": {"$gte": today}},
                        {"scheduled_start": {"$gte": today}}]
        docs = list(db[coll].find(q))
        pids = {d["property_id"] for d in docs}
        cids = {d.get("customer_id") for d in docs if d.get("customer_id")}
        custs = {c["id"]: c for c in db.customers.find({"id": {"$in": list(cids)}})}
        pids |= {c.get("primary_property_id") for c in custs.values()
                 if c.get("primary_property_id")}
        props = {p["id"]: p for p in db.properties.find({"id": {"$in": list(pids)}})}
        changed = 0
        for d in docs:
            upd = plan_repair(d, props, custs)
            if not upd:
                continue
            changed += 1
            print(f"[{coll}] {d.get('id')} cust={d.get('customer_id')} "
                  f"bad_property={d.get('property_id')} -> {upd}")
            if a.apply:
                db[BACKUP].insert_one({"collection": coll, "doc": d,
                                       "backed_up_at": dt.datetime.utcnow()})
                db[coll].update_one({"_id": d["_id"]}, upd)
        print(f"== {coll}: scanned={len(docs)} mismatched={changed} "
              f"{'APPLIED' if a.apply else 'DRY-RUN (no writes)'}")
        total += changed
    print(f"TOTAL mismatched records: {total}")


if __name__ == "__main__":
    main()
