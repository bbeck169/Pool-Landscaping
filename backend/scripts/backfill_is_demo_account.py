#!/usr/bin/env python3
"""Feb-2026 · Comms whitelist backfill (P0 safety directive).

Idempotent. Safe to re-run any number of times.

Sets ``is_demo_account = True`` on:
  1. The seed staff accounts (``super@aquaterra.com``,
     ``admin@aquaterra.com``, ``manager@aquaterra.com``,
     ``landscaper@aquaterra.com``, ``customer@aquaterra.com``)
  2. The founder-operator (``brian@plofv.com``)
  3. Any ``users`` or ``customers`` row whose email domain matches
     ``DEMO_EMAIL_DOMAINS_ALLOWLIST`` (env var, comma-separated,
     defaults to ``@aquaterra.com,@plofv.com,@mailinator.com``)

All OTHER users + customers get ``is_demo_account = False`` (set
explicitly so downstream gate lookups don't rely on missing-field
defaulting). The gate helper does ``bool(row.get("is_demo_account"))``
so a missing field would also fail-closed — the explicit False is
belt-and-braces + makes the field greppable in Mongo.

Prints a JSON report of counts for audit.

Usage::

    cd /app/backend && python3 -m scripts.backfill_is_demo_account
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Dict

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")


_SEED_STAFF_EMAILS = [
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "manager@aquaterra.com",
    "landscaper@aquaterra.com",
    "customer@aquaterra.com",
    "brian@plofv.com",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowlist_domains() -> list[str]:
    raw = os.environ.get(
        "DEMO_EMAIL_DOMAINS_ALLOWLIST",
        "@aquaterra.com,@plofv.com,@mailinator.com",
    )
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _domain_regex(domains: list[str]) -> Dict[str, object]:
    # Build one anchored $regex against joined suffixes.
    escaped = "|".join(d.replace(".", r"\.") for d in domains)
    return {"$regex": f"({escaped})$", "$options": "i"}


async def _run() -> Dict[str, object]:
    from config import db

    domains = _allowlist_domains()
    dom_re = _domain_regex(domains)
    now = _now_iso()
    report: Dict[str, object] = {
        "at": now,
        "allowlist_domains": domains,
        "seed_staff_emails": _SEED_STAFF_EMAILS,
    }

    # 1. USERS —
    # 1a. Seed staff + brian → demo=True (always).
    seed_users = await db.users.update_many(
        {"email": {"$in": _SEED_STAFF_EMAILS}},
        {"$set": {"is_demo_account": True,
                   "is_demo_account_backfilled_at": now}},
    )
    # 1b. Domain-matching users → demo=True (skip seed-matched rows).
    dom_users = await db.users.update_many(
        {"$and": [
            {"email": dom_re},
            {"email": {"$nin": _SEED_STAFF_EMAILS}},
        ]},
        {"$set": {"is_demo_account": True,
                   "is_demo_account_backfilled_at": now}},
    )
    # 1c. Everyone else → demo=False (only where the flag isn't already
    # set to True, to preserve any prior operator opt-ins).
    other_users = await db.users.update_many(
        {"$or": [
            {"is_demo_account": {"$exists": False}},
            {"is_demo_account": False},
        ]},
        {"$set": {"is_demo_account": False,
                   "is_demo_account_backfilled_at": now}},
    )
    users_flagged_true = await db.users.count_documents(
        {"is_demo_account": True})
    report["users"] = {
        "seed_matched": int(seed_users.matched_count),
        "seed_modified": int(seed_users.modified_count),
        "domain_matched": int(dom_users.matched_count),
        "domain_modified": int(dom_users.modified_count),
        "other_touched": int(other_users.modified_count),
        "total_true_after_backfill": int(users_flagged_true),
    }

    # 2. CUSTOMERS —
    # 2a. Domain-matching customers → demo=True.
    dom_cust = await db.customers.update_many(
        {"email": dom_re},
        {"$set": {"is_demo_account": True,
                   "is_demo_account_backfilled_at": now}},
    )
    # 2b. Everyone else → demo=False (idempotency clause same as users).
    other_cust = await db.customers.update_many(
        {"$or": [
            {"is_demo_account": {"$exists": False}},
            {"is_demo_account": False},
        ]},
        {"$set": {"is_demo_account": False,
                   "is_demo_account_backfilled_at": now}},
    )
    cust_flagged_true = await db.customers.count_documents(
        {"is_demo_account": True})
    total_cust = await db.customers.count_documents({})
    report["customers"] = {
        "domain_matched": int(dom_cust.matched_count),
        "domain_modified": int(dom_cust.modified_count),
        "other_touched": int(other_cust.modified_count),
        "total_true_after_backfill": int(cust_flagged_true),
        "total_customers": int(total_cust),
    }

    return report


def main() -> int:
    report = asyncio.run(_run())
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
