"""Preview isolation · boot-time scrubber.

Defense-in-depth layer that scans the preview DB on every boot and
re-synthesizes any row whose PII shape doesn't match the preview
namespace. The ingress decorator (commit 1/5) prevents NEW real
PII writes; this scrubber catches:

  * Rows that pre-date the decorator (the 120 real-PII customers
    on preview DB today).
  * Rows that slipped past the decorator because a new ingress
    endpoint shipped without wiring the guard.
  * Rows written by one-off migrations that don't go through the
    API ingress layer.

Guarantees:

  * Idempotent — once rows carry ``name = Preview Customer{slug}``,
    the match regex no longer fires, so the second boot is a
    no-op.
  * 24-hour dedup — the audit-log entry
    (``{event: "pii_boot_scrub"}``) is checked at the start; if
    the most recent entry is < 24h old, the scrub skips entirely.
    Protects against crash-loop restart storms.
  * Production env: STRICT NO-OP via ``is_production_env()``
    guard at the top of ``run_once()``. Production never touches
    PII rows regardless of env config.
  * Localhost-only MongoDB — reuses the same guard as
    ``scripts/scrub_preview_pii.py``: refuses to run against a
    non-``localhost``/``127.0.0.1`` MONGO_URL.

Scrubs across the full related-collection surface (Refinement 3):
  * customers, leads, outreach_prospects, marketing_subscribers,
    widget_form_submissions, instaquote_submissions
  * users (role=customer rows only — admin accounts untouched)
  * quotes, invoices (customer_name / bill_to_* snapshots)
  * jobs (customer_name snapshot)
  * estimates (bill_to_* snapshots)
  * contracts, signed_contracts (signer_name / signer_email)
  * csat_responses (respondent_name / email)
  * messages, communication_timeline, email_templates, sms_templates
    (free-text body redaction only — these aren't customer rows,
    so pattern-match + redact rather than full re-synthesize)
  * webhook_events (raw payload redaction)
  * calendar_events (customer_name snapshot)
  * audit_logs (free-text event-detail redaction)
  * geocode_cache (dropped entirely — stale real-address hits)

Missing collections are skipped quietly — the scrubber reports a
per-collection count regardless.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from .config import is_preview_env, is_production_env
from .synthesizer import (
    synthetic_bucket,
    synthesize_customer_fields,
    synthesize_lead_fields,
    synthesize_subscriber_fields,
)
from .redactor import redact_free_text

_log = logging.getLogger(__name__)

_DEDUP_WINDOW_HRS = 24
# ``^Preview (Customer|Lead|Subscriber|Co) 0000-9999`` — the full
# preview-namespace shape.
_PREVIEW_NAME_RE = re.compile(
    r"^Preview (Customer|Lead|Subscriber|Co )\s*\d{4}", re.IGNORECASE,
)
_PREVIEW_EMAIL_RE = re.compile(
    r"^preview-(customer|lead|subscriber|portal)\d{4}@preview\.local$",
    re.IGNORECASE,
)


def _is_localhost_mongo() -> bool:
    url = os.environ.get("MONGO_URL", "")
    return "localhost" in url or "127.0.0.1" in url


def _needs_scrub(row: Dict[str, Any]) -> bool:
    """Return True iff ``row`` carries PII that doesn't match the
    preview namespace."""
    name = row.get("name") or ""
    email = row.get("email") or ""
    if _PREVIEW_NAME_RE.match(name):
        return False
    if _PREVIEW_EMAIL_RE.match(email):
        return False
    # Anything else — real-shape or empty — needs the full
    # synthesize pass.
    return bool(name or email or row.get("phone") or row.get("address"))


async def _recent_scrub_exists(db) -> bool:
    """24h dedup guard. Returns True iff a ``pii_boot_scrub`` or
    ``pii_scrub`` audit row exists in the last window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HRS)).isoformat()
    try:
        q = {
            "event": {"$in": ["pii_boot_scrub", "pii_scrub"]},
            "at": {"$gte": cutoff},
        }
        n = await db.audit_logs.count_documents(q)
        return n > 0
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] dedup check failed: {exc}")
        return False


async def _scrub_customer_rows(db, coll_name: str,
                                 synth_fn, counts: Dict[str, int]) -> None:
    """Walk one collection, re-synthesize rows that fail
    ``_needs_scrub``. Writes a per-row update; batched in-memory
    pass with ``bulk_write`` for throughput."""
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    scrubbed = 0
    try:
        cursor = coll.find(
            {}, {"_id": 1, "id": 1, "name": 1, "email": 1, "phone": 1,
                  "address": 1, "first_name": 1, "last_name": 1,
                  "phones": 1, "emails": 1, "mobiles": 1,
                  "custom_fields": 1, "notes": 1, "tenant_id": 1,
                  "role": 1}
        )
        async for row in cursor:
            # Users collection — only scrub role=customer rows.
            if coll_name == "users" and row.get("role") != "customer":
                continue
            if not _needs_scrub(row):
                continue
            patch = synth_fn(row)
            # Preserve immutable identity fields.
            patch.pop("_id", None)
            patch.pop("id", None)
            patch.pop("tenant_id", None)
            patch.pop("role", None)
            await coll.update_one({"_id": row["_id"]}, {"$set": patch})
            scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] {coll_name} scrub error: {exc}")
    counts[coll_name] = scrubbed


async def _redact_free_text_in_coll(db, coll_name: str,
                                      fields: list,
                                      counts: Dict[str, int]) -> None:
    """Walk one collection, redact free-text fields in place."""
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    scrubbed = 0
    projection = {"_id": 1, **{f: 1 for f in fields}}
    try:
        cursor = coll.find({}, projection)
        async for row in cursor:
            patch = {}
            for f in fields:
                v = row.get(f)
                if isinstance(v, str):
                    red = redact_free_text(v)
                    if red != v:
                        patch[f] = red
            if patch:
                await coll.update_one({"_id": row["_id"]}, {"$set": patch})
                scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] {coll_name} redact error: {exc}")
    counts[coll_name] = scrubbed


async def _snapshot_scrub(db, coll_name: str,
                            name_field: str, email_field: Optional[str],
                            address_field: Optional[str],
                            counts: Dict[str, int]) -> None:
    """Scrub denormalized snapshot fields on non-customer collections
    (``quotes.customer_name``, ``invoices.bill_to_name``, etc.)."""
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    scrubbed = 0
    projection = {"_id": 1, name_field: 1}
    if email_field: projection[email_field] = 1
    if address_field: projection[address_field] = 1
    try:
        cursor = coll.find({name_field: {"$exists": True}}, projection)
        async for row in cursor:
            name = row.get(name_field) or ""
            if _PREVIEW_NAME_RE.match(name):
                continue
            if not name:
                continue
            bucket = synthetic_bucket(name)
            slug = f"{bucket:04d}"
            patch = {name_field: f"Preview Customer{slug}"}
            if email_field and row.get(email_field):
                patch[email_field] = f"preview-customer{slug}@preview.local"
            if address_field and row.get(address_field):
                patch[address_field] = f"{bucket} Preview St"
            await coll.update_one({"_id": row["_id"]}, {"$set": patch})
            scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(
            f"[preview_scrubber] {coll_name}.{name_field} snapshot "
            f"scrub error: {exc}"
        )
    counts[coll_name] = counts.get(coll_name, 0) + scrubbed


async def run_once(db, *, force: bool = False) -> Dict[str, Any]:
    """Run the full multi-collection scrub pass. Returns a report.

    * Production env: strict no-op.  Returns ``{"skipped":
      "production_env"}`` without touching anything.
    * 24h dedup: skipped if a recent scrub audit exists, unless
      ``force=True``.
    * Non-localhost Mongo: refuses to run.
    """
    if is_production_env():
        return {"skipped": "production_env", "scrubbed_counts": {}}
    if not _is_localhost_mongo():
        _log.warning(
            "[preview_scrubber] MONGO_URL is not localhost — "
            "refusing to run (defense in depth)."
        )
        return {"skipped": "non_localhost_mongo", "scrubbed_counts": {}}
    if not force and await _recent_scrub_exists(db):
        return {"skipped": "recent_scrub_within_24h", "scrubbed_counts": {}}

    counts: Dict[str, int] = {}

    # Pass 1 — primary customer-shaped collections.
    await _scrub_customer_rows(db, "customers", synthesize_customer_fields, counts)
    await _scrub_customer_rows(db, "leads", synthesize_lead_fields, counts)
    await _scrub_customer_rows(db, "outreach_prospects", synthesize_lead_fields, counts)
    await _scrub_customer_rows(db, "marketing_subscribers",
                                 synthesize_subscriber_fields, counts)
    await _scrub_customer_rows(db, "widget_form_submissions",
                                 synthesize_lead_fields, counts)
    await _scrub_customer_rows(db, "instaquote_submissions",
                                 synthesize_customer_fields, counts)
    await _scrub_customer_rows(db, "users", synthesize_customer_fields, counts)

    # Pass 2 — denormalized snapshots on business collections.
    await _snapshot_scrub(db, "quotes", "customer_name", "customer_email",
                            "customer_address", counts)
    await _snapshot_scrub(db, "invoices", "bill_to_name", "bill_to_email",
                            "bill_to_address", counts)
    await _snapshot_scrub(db, "jobs", "customer_name", None, None, counts)
    await _snapshot_scrub(db, "estimates", "bill_to_name", "bill_to_email",
                            "bill_to_address", counts)
    await _snapshot_scrub(db, "contracts", "signer_name", "signer_email",
                            None, counts)
    await _snapshot_scrub(db, "signed_contracts", "signer_name",
                            "signer_email", None, counts)
    await _snapshot_scrub(db, "csat_responses", "respondent_name",
                            "email", None, counts)
    await _snapshot_scrub(db, "calendar_events", "customer_name", None,
                            None, counts)

    # Pass 3 — free-text redaction on message / template / audit bodies.
    await _redact_free_text_in_coll(db, "messages",
                                     ["body", "preview"], counts)
    await _redact_free_text_in_coll(db, "communication_timeline",
                                     ["body", "subject"], counts)
    await _redact_free_text_in_coll(db, "outbound_emails",
                                     ["body", "html", "subject"], counts)
    await _redact_free_text_in_coll(db, "email_templates",
                                     ["last_test_recipient", "last_test_subject"],
                                     counts)
    await _redact_free_text_in_coll(db, "sms_templates",
                                     ["last_test_recipient"], counts)
    await _redact_free_text_in_coll(db, "webhook_events",
                                     ["payload_json", "raw_body"], counts)
    await _redact_free_text_in_coll(db, "audit_logs",
                                     ["detail", "message"], counts)

    # Pass 4 — drop stale geocode-cache (real-address resolver hits).
    try:
        if hasattr(db, "geocode_cache"):
            res = await db.geocode_cache.delete_many(
                {"address_hash": {"$ne": None}}
            )
            counts["geocode_cache"] = res.deleted_count
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] geocode_cache drop error: {exc}")
        counts["geocode_cache"] = 0

    total = sum(counts.values())

    # Audit-log entry — enables the 24h dedup on the next boot.
    try:
        await db.audit_logs.insert_one({
            "event": "pii_boot_scrub",
            "actor": "system:preview_boot_scrubber",
            "at": datetime.now(timezone.utc).isoformat(),
            "meta": {"scrubbed_counts": counts, "total": total},
        })
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] audit insert error: {exc}")

    _log.info(
        f"[preview_scrubber] completed · total_rows_scrubbed={total} "
        f"counts={counts}"
    )
    return {"ok": True, "scrubbed_counts": counts, "total": total}


__all__ = ["run_once"]
