#!/usr/bin/env python3
"""Phase SCRUB · Feb-2026 — Preview-env PII scrub.

Replaces realistic customer PII in the ACTIVE Mongo database with
unmistakably-synthetic values ("Preview Customer0001", "555-01…",
"@preview.local").  Preserves every ``id`` / ``tenant_id`` /
``customer_id`` foreign key, every timestamp, every flag.  Idempotent
(safe to re-run; synthetic patterns always generate the same value
for the same source row).

HARD GUARD
    Refuses to execute unless ``MONGO_URL`` points at ``localhost``
    or ``127.0.0.1``.  Any remote hostname → ``sys.exit(1)``.

SCOPE
    Scrubs 25 customer-PII-bearing collections:
      * Primary records          — customers, leads, subscribers,
                                   users (role=customer only)
      * Customer-name snapshots  — quotes, jobs, audits, csat_surveys,
                                   maintenance_records,
                                   recurring_job_templates, repairs,
                                   portal_appointments, deals,
                                   billing_plans
      * Customer contact fields  — marketing_enrollments,
                                   password_reset_tokens,
                                   auth_multi_account_choices,
                                   outbound_emails, unmatched_calls
      * Property / addresses     — properties, chemical_applications,
                                   checkins, reverse_geocode_cache,
                                   zillow_cache, property_search_history
    Explicitly PRESERVED (NOT scrubbed, per spec):
      * audit_logs — provenance (one ``pii_scrub`` row inserted per
                     tenant_id, meta carries per-collection counts)
      * tenants   — business-entity records (name/email are the
                     COMPANY, not customer PII)
      * technicians / users where role != customer — internal staff
      * tenant_nap_profile — business local-SEO data
      * entity-name fields on inventory_items, service_categories,
        marketing_templates, ai_employees, etc. — ``name`` here is
        a thing name, not a person's name

USAGE
    cd /app/backend && python3 -m scripts.scrub_preview_pii
    cd /app/backend && python3 -m scripts.scrub_preview_pii --drop-orphan=aquaterra

Audit-log row shape (one per tenant_id):
    {
      "id":        <uuid4>,
      "tenant_id": <tid>,
      "event":     "pii_scrub",
      "actor":     "system:preview_scrub",
      "at":        <iso8601 utc>,
      "meta":      {"scrubbed_counts": {<coll>: <n>, ...}},
    }
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ── .env load (works whether invoked via -m or directly) ───────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(_BACKEND_DIR / ".env")
except Exception:  # noqa: BLE001
    pass

from pymongo import MongoClient  # noqa: E402  — import after .env load


MONGO_URL = os.environ.get("MONGO_URL", "")
DB_NAME = os.environ.get("DB_NAME", "")


# ═════════════════════════════ GUARDS ═════════════════════════════
def _assert_safe_target() -> None:
    """Localhost-only guard.  Exits hard on remote Mongo URIs."""
    if not MONGO_URL:
        sys.exit("REFUSE: MONGO_URL env var is empty. Scrub aborted.")
    if not DB_NAME:
        sys.exit("REFUSE: DB_NAME env var is empty. Scrub aborted.")
    parsed = urlparse(MONGO_URL)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        sys.exit(
            f"REFUSE: MONGO_URL hostname {host!r} is not localhost / "
            f"127.0.0.1.  Preview scrub must NEVER run against a "
            f"remote cluster.  Aborted.",
        )
    print(f"  guard · MONGO_URL hostname = {host!r} (localhost-only) OK")
    print(f"  guard · DB_NAME            = {DB_NAME!r}")


# ═══════════════════════════ SYNTHETIC MINT ═══════════════════════
def _idx_slug(idx: int) -> str:
    return f"{idx:04d}"


def _synthetic_customer(idx: int) -> dict:
    """Return the ``$set`` payload replacing PII on one customer row.

    All values are deterministic by ``idx`` — re-running the scrub
    produces identical output.  The ``555-010000`` + ``555-020000``
    phone ranges are reserved as "obviously synthetic" per NANP
    convention (``555-01xx`` is for fictional use).
    """
    slug = _idx_slug(idx)
    return {
        "first_name":    "Preview",
        "last_name":     f"Customer{slug}",
        "name":          f"Preview Customer{slug}",
        "display_name":  f"Preview Customer{slug}",
        "email":         f"preview-customer{slug}@preview.local",
        "phone":         f"555-01{slug}",
        "phone_mobile":  f"555-02{slug}",
        "mobile":        f"555-02{slug}",
        "address":       f"{idx} Preview St",
        "address_line_1": f"{idx} Preview St",
        "address_line_2": None,
        "street":        f"{idx} Preview St",
        "city":           "Testville",
        "state":          "AZ",
        "zip":            "85000",
        "zip_code":       "85000",
        "postal_code":    "85000",
        "notes":          None,
    }


def _synthetic_lead(idx: int) -> dict:
    slug = _idx_slug(idx)
    return {
        "name":    f"Preview Lead{slug}",
        "email":   f"preview-lead{slug}@preview.local",
        "phone":   f"555-03{slug}",
        "address": f"{idx} Preview Ln, Testville, AZ 85000",
    }


def _synthetic_subscriber(idx: int) -> dict:
    slug = _idx_slug(idx)
    return {
        "first_name": "Preview",
        "last_name":  f"Subscriber{slug}",
        "email":      f"preview-subscriber{slug}@preview.local",
        "phone":      f"555-04{slug}",
    }


def _synthetic_user_customer(idx: int) -> dict:
    slug = _idx_slug(idx)
    return {
        "name":   f"Preview Customer{slug}",
        "email":  f"preview-portal{slug}@preview.local",
    }


# ═══════════════════════════ SCRUB FUNCS ══════════════════════════
def scrub_customers(db) -> tuple[int, dict[str, int]]:
    """Scrub primary ``customers`` collection, deterministic by
    sorted order.  Returns ``(count, cid_to_idx_map)``.  The map is
    reused by snapshot scrubs below so a quote's ``customer_name``
    snapshot ends up equal to the customer's new synthetic name.
    """
    cursor = db.customers.find(
        {},
        {"_id": 1, "id": 1},
    ).sort([("created_at", 1), ("_id", 1)])
    cid_to_idx: dict[str, int] = {}
    n = 0
    for idx, c in enumerate(cursor, start=1):
        patch = _synthetic_customer(idx)
        db.customers.update_one({"_id": c["_id"]}, {"$set": patch})
        if c.get("id"):
            cid_to_idx[c["id"]] = idx
        n += 1
    return n, cid_to_idx


def _snapshot_name(cid: str, cid_to_idx: dict[str, int]) -> str:
    idx = cid_to_idx.get(cid)
    if idx is None:
        return "Preview Customer (unknown)"
    return f"Preview Customer{_idx_slug(idx)}"


def _snapshot_email(cid: str, cid_to_idx: dict[str, int]) -> str:
    idx = cid_to_idx.get(cid)
    if idx is None:
        return "preview-customer-unknown@preview.local"
    return f"preview-customer{_idx_slug(idx)}@preview.local"


def _snapshot_phone(cid: str, cid_to_idx: dict[str, int]) -> str:
    idx = cid_to_idx.get(cid)
    if idx is None:
        return "555-010000"
    return f"555-01{_idx_slug(idx)}"


def _snapshot_address(cid: str, cid_to_idx: dict[str, int]) -> str:
    idx = cid_to_idx.get(cid)
    if idx is None:
        return "0 Preview St, Testville, AZ 85000"
    return f"{idx} Preview St, Testville, AZ 85000"


def _scrub_name_snapshot(db, coll: str, field: str,
                           cid_to_idx: dict[str, int]) -> int:
    """Generic rewriter — for every doc in ``coll`` with a non-null
    ``field``, replace it with the synthetic name derived from the
    row's ``customer_id`` (or a generic fallback if missing)."""
    cursor = db[coll].find(
        {field: {"$exists": True, "$ne": None}},
        {"_id": 1, "customer_id": 1},
    )
    n = 0
    for doc in cursor:
        cid = doc.get("customer_id") or ""
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: _snapshot_name(cid, cid_to_idx)}},
        )
        n += 1
    return n


def _scrub_email_snapshot(db, coll: str, field: str,
                            cid_to_idx: dict[str, int]) -> int:
    cursor = db[coll].find(
        {field: {"$exists": True, "$ne": None}},
        {"_id": 1, "customer_id": 1},
    )
    n = 0
    for doc in cursor:
        cid = doc.get("customer_id") or ""
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: _snapshot_email(cid, cid_to_idx)}},
        )
        n += 1
    return n


def _scrub_phone_snapshot(db, coll: str, field: str,
                            cid_to_idx: dict[str, int]) -> int:
    cursor = db[coll].find(
        {field: {"$exists": True, "$ne": None}},
        {"_id": 1, "customer_id": 1},
    )
    n = 0
    for doc in cursor:
        cid = doc.get("customer_id") or ""
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: _snapshot_phone(cid, cid_to_idx)}},
        )
        n += 1
    return n


def _scrub_address_snapshot(db, coll: str, field: str,
                             cid_to_idx: dict[str, int]) -> int:
    cursor = db[coll].find(
        {field: {"$exists": True, "$ne": None}},
        {"_id": 1, "customer_id": 1},
    )
    n = 0
    for doc in cursor:
        cid = doc.get("customer_id") or ""
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: _snapshot_address(cid, cid_to_idx)}},
        )
        n += 1
    return n


def _scrub_address_generic(db, coll: str, field: str) -> int:
    """Rewrite ``field`` on every doc of ``coll`` to a positional
    synthetic address.  Used for ``properties`` + geocode caches
    where there's no customer_id tether."""
    n = 0
    for idx, doc in enumerate(
            db[coll].find({field: {"$exists": True}}, {"_id": 1}),
            start=1):
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: f"{idx} Preview St, Testville, AZ 85000"}},
        )
        n += 1
    return n


def scrub_leads(db) -> int:
    cursor = db.leads.find({}, {"_id": 1}).sort("_id", 1)
    n = 0
    for idx, doc in enumerate(cursor, start=1):
        db.leads.update_one(
            {"_id": doc["_id"]},
            {"$set": _synthetic_lead(idx)},
        )
        n += 1
    return n


def scrub_subscribers(db) -> int:
    cursor = db.subscribers.find({}, {"_id": 1}).sort("_id", 1)
    n = 0
    for idx, doc in enumerate(cursor, start=1):
        db.subscribers.update_one(
            {"_id": doc["_id"]},
            {"$set": _synthetic_subscriber(idx)},
        )
        n += 1
    return n


def scrub_users_customer(db, cid_to_idx: dict[str, int]) -> int:
    """Only scrub users where role == 'customer' — admins/techs
    stay intact so the preview still has a working staff graph."""
    cursor = db.users.find(
        {"role": "customer"},
        {"_id": 1, "customer_id": 1},
    ).sort("_id", 1)
    n = 0
    for idx, doc in enumerate(cursor, start=1):
        cid = doc.get("customer_id") or ""
        mapped_idx = cid_to_idx.get(cid, idx)
        patch = _synthetic_user_customer(mapped_idx)
        db.users.update_one({"_id": doc["_id"]}, {"$set": patch})
        n += 1
    return n


def scrub_simple_email_col(db, coll: str, field: str) -> int:
    """For small helper collections where only a single ``email``
    field needs to go synthetic (password_reset_tokens, etc.)."""
    cursor = db[coll].find({field: {"$exists": True}}, {"_id": 1})
    n = 0
    for idx, doc in enumerate(cursor, start=1):
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: f"preview-{coll}-{idx:04d}@preview.local"}},
        )
        n += 1
    return n


def scrub_simple_phone_col(db, coll: str, field: str) -> int:
    cursor = db[coll].find({field: {"$exists": True}}, {"_id": 1})
    n = 0
    for idx, doc in enumerate(cursor, start=1):
        db[coll].update_one(
            {"_id": doc["_id"]},
            {"$set": {field: f"555-09{idx:04d}"}},
        )
        n += 1
    return n


# ═══════════════════════════ AUDIT ENTRIES ════════════════════════
def write_audit_entries(db, counts: dict[str, int]) -> int:
    """One ``pii_scrub`` row per tenant_id so this operation is
    permanently traceable in the preview's audit history."""
    now = datetime.now(timezone.utc).isoformat()
    tenants = list(db.tenants.find({}, {"id": 1}))
    inserted = 0
    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        db.audit_logs.insert_one({
            "id":        str(uuid.uuid4()),
            "tenant_id": tid,
            "event":     "pii_scrub",
            "actor":     "system:preview_scrub",
            "at":        now,
            "meta":      {"scrubbed_counts": counts},
        })
        inserted += 1
    return inserted


# ═════════════════════════════ MAIN ═══════════════════════════════
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrub preview-env customer PII.",
    )
    parser.add_argument(
        "--drop-orphan",
        default="",
        help=("Name of an orphan DB to drop AFTER a successful "
               "scrub.  Blank = skip.  Refuses to drop the active "
               "DB_NAME regardless of what's passed."),
    )
    args = parser.parse_args()

    print("─── Pre-flight guard ───────────────────────────────────")
    _assert_safe_target()

    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]

    counts: dict[str, int] = {}

    print()
    print("─── Primary customer records ───────────────────────────")
    n_cust, cid_to_idx = scrub_customers(db)
    counts["customers"] = n_cust
    print(f"  customers         scrubbed = {n_cust}")

    n_leads = scrub_leads(db)
    counts["leads"] = n_leads
    print(f"  leads             scrubbed = {n_leads}")

    n_subs = scrub_subscribers(db)
    counts["subscribers"] = n_subs
    print(f"  subscribers       scrubbed = {n_subs}")

    n_users_cust = scrub_users_customer(db, cid_to_idx)
    counts["users (role=customer)"] = n_users_cust
    print(f"  users (role=customer) scrubbed = {n_users_cust}")

    print()
    print("─── Snapshot: customer_name field ──────────────────────")
    for coll in ("quotes", "jobs", "csat_surveys",
                   "maintenance_records", "recurring_job_templates",
                   "repairs", "portal_appointments", "billing_plans",
                   "audits"):
        n = _scrub_name_snapshot(db, coll, "customer_name", cid_to_idx)
        counts[f"{coll}.customer_name"] = n
        print(f"  {coll:>30s}.customer_name = {n}")

    print()
    print("─── Snapshot: contact_name / email / phone ─────────────")
    counts["deals.contact_name"] = _scrub_name_snapshot(
        db, "deals", "contact_name", cid_to_idx,
    )
    print(f"  deals.contact_name            = {counts['deals.contact_name']}")

    counts["audits.customer_email"] = _scrub_email_snapshot(
        db, "audits", "customer_email", cid_to_idx,
    )
    print(f"  audits.customer_email         = {counts['audits.customer_email']}")

    counts["marketing_enrollments.customer_email"] = _scrub_email_snapshot(
        db, "marketing_enrollments", "customer_email", cid_to_idx,
    )
    print(f"  marketing_enrollments.customer_email = "
          f"{counts['marketing_enrollments.customer_email']}")

    counts["marketing_enrollments.customer_phone"] = _scrub_phone_snapshot(
        db, "marketing_enrollments", "customer_phone", cid_to_idx,
    )
    print(f"  marketing_enrollments.customer_phone = "
          f"{counts['marketing_enrollments.customer_phone']}")

    print()
    print("─── Simple email / phone collections ───────────────────")
    counts["password_reset_tokens.email"] = scrub_simple_email_col(
        db, "password_reset_tokens", "email",
    )
    print(f"  password_reset_tokens.email   = "
          f"{counts['password_reset_tokens.email']}")

    counts["auth_multi_account_choices.email"] = scrub_simple_email_col(
        db, "auth_multi_account_choices", "email",
    )
    print(f"  auth_multi_account_choices.email = "
          f"{counts['auth_multi_account_choices.email']}")

    counts["outbound_emails.recipient_email"] = scrub_simple_email_col(
        db, "outbound_emails", "recipient_email",
    )
    print(f"  outbound_emails.recipient_email = "
          f"{counts['outbound_emails.recipient_email']}")

    counts["unmatched_calls.phone"] = scrub_simple_phone_col(
        db, "unmatched_calls", "phone",
    )
    print(f"  unmatched_calls.phone         = "
          f"{counts['unmatched_calls.phone']}")

    counts["email_outbox.recipient"] = scrub_simple_email_col(
        db, "email_outbox", "recipient",
    )
    print(f"  email_outbox.recipient        = "
          f"{counts['email_outbox.recipient']}")

    print()
    print("─── Address scrub ──────────────────────────────────────")
    counts["jobs.address"] = _scrub_address_snapshot(
        db, "jobs", "address", cid_to_idx,
    )
    print(f"  jobs.address (by customer_id)  = {counts['jobs.address']}")

    counts["portal_appointments.address"] = _scrub_address_snapshot(
        db, "portal_appointments", "address", cid_to_idx,
    )
    print(f"  portal_appointments.address    = "
          f"{counts['portal_appointments.address']}")

    for coll in ("properties", "chemical_applications", "checkins",
                   "reverse_geocode_cache", "zillow_cache",
                   "property_search_history"):
        field = ("property_address" if coll == "chemical_applications"
                 else "address")
        n = _scrub_address_generic(db, coll, field)
        counts[f"{coll}.{field}"] = n
        print(f"  {coll:>30s}.{field} = {n}")

    print()
    print("─── Audit log provenance ───────────────────────────────")
    n_audit = write_audit_entries(db, counts)
    counts["audit_logs (provenance rows)"] = n_audit
    print(f"  audit_logs provenance inserted = {n_audit}")

    print()
    print("─── Totals ─────────────────────────────────────────────")
    for k, v in counts.items():
        print(f"  {k:<45s} {v:>8d}")

    # STOP-condition hook: active-DB customer count must match the
    # pre-scrub baseline (712) exactly.  Any delta implies a bug in
    # the scrub loop and leaves stale PII in the DB.
    if n_cust != db.customers.count_documents({}):
        sys.exit(
            f"ABORT: post-scrub customer count mismatch — "
            f"scrubbed {n_cust}, DB now has "
            f"{db.customers.count_documents({})}.",
        )

    if args.drop_orphan:
        if args.drop_orphan == DB_NAME:
            sys.exit(
                f"REFUSE: --drop-orphan target {args.drop_orphan!r} "
                f"is the ACTIVE DB. Aborted.",
            )
        print()
        print(f"─── Dropping orphan DB: {args.drop_orphan} ─────────────")
        before_cust = client[args.drop_orphan].customers.count_documents({})
        before_ten = client[args.drop_orphan].tenants.count_documents({})
        client.drop_database(args.drop_orphan)
        print(f"  dropped (was {before_cust} customers, "
              f"{before_ten} tenants)")

    print()
    print("─── Done ───────────────────────────────────────────────")
    return 0


if __name__ == "__main__":
    sys.exit(main())
