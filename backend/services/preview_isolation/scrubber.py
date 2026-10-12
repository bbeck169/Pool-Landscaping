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

Scrubs across the full related-collection surface:
  * customers, leads, outreach_prospects, marketing_subscribers,
    widget_form_submissions, instaquote_submissions
  * users (role=customer rows only — admin accounts untouched)
  * quotes, invoices (customer_name / bill_to_* / search_haystack
    snapshots — Step C expansion)
  * jobs (customer_name / email / phone / address / haystack)
  * estimates (bill_to_* + customer_* snapshots)
  * contracts, signed_contracts (signer_name / signer_email)
  * csat_responses (respondent_name / email)
  * recurring_job_templates, service_reports, payments, tasks,
    appointments, portal_appointments (customer_* snapshots —
    Step C expansion)
  * messages, communication_timeline, email_templates, sms_templates
    (free-text body redaction only — these aren't customer rows,
    so pattern-match + redact rather than full re-synthesize)
  * webhook_events (raw payload redaction)
  * calendar_events (customer_name snapshot)
  * audit_logs (free-text event-detail redaction)
  * geocode_cache (dropped entirely — stale real-address hits)

Missing collections are skipped quietly — the scrubber reports a
per-collection count regardless.

2026-02 · P0 Stage 3 Step C — ``_needs_scrub`` + projection
expanded to inspect denormalized / nested PII fields
(``search_haystack``, ``phone_raw``, ``mobile_raw``,
``latitude`` / ``longitude`` / ``service_location``,
``geocode_address_hash``, ``service_address.*``,
``custom_fields.*``, partial-dict email/mobile/phone shapes) so
pre-sync rows whose top-level ``name`` is already in the preview
namespace but whose denormalized surface still carries real
PII are correctly re-synthesized.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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
# Phone bands produced by the synthesizer: 555-01xxxx / 555-02xxxx /
# 555-03xxxx / 555-04xxxx (with or without the hyphen).
_PREVIEW_PHONE_RE = re.compile(r"^555-?0[1-4]\d{4}$")
# Haystack must start with the synth name prefix.
_PREVIEW_HAYSTACK_PREFIX_RE = re.compile(
    r"^preview (customer|lead|subscriber)\d{4}", re.IGNORECASE,
)
# IPv4 — RFC 5737 TEST-NET-{1,2,3} + loopback + unspecified are
# considered non-PII sentinels; any other routable IPv4 is PII.
_IP_SAFE = {"0.0.0.0", "127.0.0.1", "::1"}
_IP_SAFE_PREFIX = ("192.0.2.", "198.51.100.", "203.0.113.", "10.", "192.168.",
                    "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
                    "172.31.", "169.254.", "fe80:", "fc00:", "fd00:")


def _is_localhost_mongo() -> bool:
    url = os.environ.get("MONGO_URL", "")
    return "localhost" in url or "127.0.0.1" in url


def _is_safe_ip(value: Any) -> bool:
    """``True`` iff ``value`` is a sentinel / RFC-5737 TEST-NET /
    private-range / link-local IP — i.e. not PII."""
    if not isinstance(value, str):
        return True
    v = value.strip().lower()
    if not v:
        return True
    if v in _IP_SAFE:
        return True
    return v.startswith(_IP_SAFE_PREFIX)


def _is_preview_shaped_phone(value: Any) -> bool:
    if value is None or value == "":
        return True
    if not isinstance(value, str):
        return False
    return bool(_PREVIEW_PHONE_RE.match(value.strip()))


def _is_preview_shaped_haystack(value: Any) -> bool:
    if value is None or value == "":
        return True
    if not isinstance(value, str):
        return True
    return bool(_PREVIEW_HAYSTACK_PREFIX_RE.match(value.strip()))


def _has_full_email_shape(entries: Any) -> bool:
    """``True`` iff every entry in ``entries`` is a dict with the
    full normalizer-shape keys."""
    if not isinstance(entries, list):
        return True
    required = {"address", "label", "is_primary",
                 "marketing_ok", "notifications_enabled"}
    return all(
        isinstance(e, dict) and required.issubset(e.keys())
        for e in entries
    )


def _has_full_mobile_shape(entries: Any) -> bool:
    if not isinstance(entries, list):
        return True
    required = {"number_e164", "label", "is_primary",
                 "sms_ok", "notifications_enabled"}
    return all(
        isinstance(e, dict) and required.issubset(e.keys())
        for e in entries
    )


def _has_full_phone_shape(entries: Any) -> bool:
    if not isinstance(entries, list):
        return True
    required = {"type", "number", "e164", "raw"}
    return all(
        isinstance(e, dict) and required.issubset(e.keys())
        for e in entries
    )


def _needs_scrub(row: Dict[str, Any]) -> bool:
    """Return ``True`` iff ``row`` carries any trace of real PII.

    Covers both ingress-site and denormalized / nested surfaces:
    name / email / phone / search_haystack / phone_raw /
    address_line1 / geo fields / geocode_address_hash /
    partial-dict ``emails`` / ``mobiles`` / ``phones`` arrays.
    """
    # Primary PII fields.
    name = row.get("name") or ""
    email = row.get("email") or ""
    phone = row.get("phone") or ""
    if name and not _PREVIEW_NAME_RE.match(name):
        return True
    if email and not _PREVIEW_EMAIL_RE.match(email):
        return True
    if phone and not _is_preview_shaped_phone(phone):
        return True
    # Denormalized / nested.
    if not _is_preview_shaped_haystack(row.get("search_haystack")):
        return True
    for key in ("phone_raw", "mobile_raw"):
        v = row.get(key)
        if v and isinstance(v, str) and not _is_preview_shaped_phone(v):
            return True
    # Geo fields — any non-null leaks (lat/lng tied to real address).
    for key in ("latitude", "longitude", "service_lat", "service_lng",
                 "service_location", "geocode_address_hash"):
        if row.get(key) is not None:
            return True
    # Legacy denorm trios + no-underscore line1.
    for key in ("address_line1", "address_city", "address_state",
                 "address_zip", "service_city", "service_state",
                 "service_zip", "billing_city", "billing_state",
                 "billing_zip"):
        v = row.get(key)
        if v and v not in ("Testville", "AZ", "85000", "US"):
            # Any non-sentinel string leaks.
            if isinstance(v, str) and not v.startswith(
                ("Preview ", "Testville", "preview-"),
            ):
                # Numeric-only legacy ``address_line1`` (e.g. "123
                # Preview St") coming off our own synth starts with a
                # digit, so allow those via the ``NNN Preview St`` shape.
                if not re.match(r"^\d+ Preview\b", v):
                    return True
    # Partial-dict array shapes — Commit C normalizes these to the
    # full normalizer-schema shape.
    if "emails" in row and not _has_full_email_shape(row.get("emails")):
        return True
    if "mobiles" in row and not _has_full_mobile_shape(row.get("mobiles")):
        return True
    if "phones" in row and not _has_full_phone_shape(row.get("phones")):
        return True
    # Nested ``service_address`` carrying anything other than Testville.
    sa = row.get("service_address")
    if isinstance(sa, dict):
        for k, v in sa.items():
            if v and isinstance(v, str) and v not in (
                "Testville", "AZ", "85000", "US",
            ) and not re.match(r"^\d+ Preview\b", v):
                return True
    # Multi-contact scalars — Preview emits ``None`` for all of these.
    for key in ("master_billing_contact_email",
                 "master_billing_contact_phone",
                 "alert_email", "alert_phone",
                 "fax", "home_phone"):
        v = row.get(key)
        if v and isinstance(v, str) and v.strip():
            return True
    return False


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


# ────────────────────────────────────────────────────────────────────
# Pass 1 — primary customer-shaped collections.
# ────────────────────────────────────────────────────────────────────
# 2026-02 · P0 Stage 3 Step C — projection widened to full doc. The
# previous 14-field projection masked ``search_haystack`` /
# ``phone_raw`` / ``service_address`` / ``latitude`` from
# ``_needs_scrub``, which returned False on the 191 rows whose
# top-level name was already in preview namespace but whose
# denormalized surface still carried real PII. Pulling the full
# doc is cheap on ≤2k customer-shape collections and ensures the
# synth patch covers every field the synthesizer touches.
async def _scrub_customer_rows(db, coll_name: str,
                                 synth_fn, counts: Dict[str, int]) -> None:
    """Walk one collection, re-synthesize rows that fail
    ``_needs_scrub``."""
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    scrubbed = 0
    try:
        cursor = coll.find({})  # full doc; see Step C note above.
        async for row in cursor:
            # Users collection — only scrub role=customer rows.
            if coll_name == "users" and row.get("role") != "customer":
                continue
            if not _needs_scrub(row):
                # Additional user-only sweep: IP + photo on preview-
                # shape user rows that otherwise look clean.
                if coll_name == "users":
                    extra = _user_ip_photo_patch(row)
                    if extra:
                        await coll.update_one(
                            {"_id": row["_id"]}, {"$set": extra},
                        )
                        scrubbed += 1
                continue
            patch = synth_fn(row)
            # Preserve immutable identity fields.
            patch.pop("_id", None)
            patch.pop("id", None)
            patch.pop("tenant_id", None)
            patch.pop("role", None)
            # Users: also sanitize IP + photo in the same update.
            if coll_name == "users":
                patch.update(_user_ip_photo_patch(row) or {})
            # Customers: stripe fields nullout on scrub (legacy real
            # tokens → no sandbox counterpart on preview).
            if coll_name == "customers":
                patch.update(_customer_stripe_nullout(row))
            # Only $set the keys that actually differ from the row to
            # minimize write amplification + oplog pressure.
            diff = {k: v for k, v in patch.items() if row.get(k) != v}
            if diff:
                await coll.update_one({"_id": row["_id"]}, {"$set": diff})
                scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] {coll_name} scrub error: {exc}")
    counts[coll_name] = scrubbed


def _user_ip_photo_patch(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a `$set` dict that neutralises PII on a user row:
    * ``first_access_ip`` → ``"0.0.0.0"`` if routable
    * ``profile_photo_url`` / ``avatar`` → ``/preview/avatar-{bucket}.png``
      if URL, ``None`` if base64, left alone if empty
    """
    out: Dict[str, Any] = {}
    for key in ("first_access_ip", "last_portal_login_ip"):
        v = row.get(key)
        if v and not _is_safe_ip(v):
            out[key] = "0.0.0.0"
    bucket = synthetic_bucket(row.get("email") or row.get("name") or row.get("id") or "")
    for key in ("profile_photo_url", "avatar"):
        v = row.get(key)
        if not v:
            continue
        if not isinstance(v, str):
            continue
        if v.startswith("data:"):
            # Base64 — unsafe (may embed real face). Null out.
            out[key] = None
        elif v.startswith(("http://", "https://", "/")):
            if "/preview/avatar-" not in v:
                out[key] = f"/preview/avatar-{bucket:04d}.png"
    return out


def _customer_stripe_nullout(row: Dict[str, Any]) -> Dict[str, Any]:
    """Null the Stripe denorm fields on preview — the legacy live
    tokens have no sandbox counterpart, so leaving them in place
    creates a dead-link UX AND a correlation vector back to the
    real customer."""
    out: Dict[str, Any] = {}
    for key in ("stripe_customer_id", "stripe_default_payment_method_id",
                 "stripe_card_brand", "stripe_card_last4",
                 "stripe_sync_status", "stripe_synced_at"):
        if row.get(key):
            out[key] = None
    return out


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
                            snapshot_fields: Dict[str, str],
                            counts: Dict[str, int]) -> None:
    """Scrub denormalized snapshot fields on business collections.

    ``snapshot_fields`` is ``{db_field_name: kind}`` where ``kind`` is
    one of ``name`` / ``email`` / ``phone`` / ``address`` /
    ``haystack``. The anchor for the synthetic bucket is the first
    name-kind value found on the row (so a quote's
    ``bill_to_name = "Terry Peterson"`` hashes to the same preview
    bucket as the customer row).
    """
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    scrubbed = 0
    projection = {"_id": 1, **{f: 1 for f in snapshot_fields}}
    try:
        cursor = coll.find({}, projection)
        async for row in cursor:
            # Determine anchor from the first name/email that's not
            # already preview-shape.
            anchor = ""
            name_field = next((f for f, k in snapshot_fields.items()
                                if k == "name" and row.get(f)), None)
            if name_field and row.get(name_field):
                v = row[name_field]
                if _PREVIEW_NAME_RE.match(v or ""):
                    continue  # Already preview-shape; skip row.
                anchor = v
            else:
                # Try email/haystack as anchor.
                for f, k in snapshot_fields.items():
                    if k in ("email", "haystack") and row.get(f):
                        anchor = row[f]
                        break
                if not anchor:
                    continue
            bucket = synthetic_bucket(anchor)
            slug = f"{bucket:04d}"
            name = f"Preview Customer{slug}"
            email = f"preview-customer{slug}@preview.local"
            phone = f"555-01{slug}"
            street = f"{bucket} Preview St"
            haystack = f"{name.lower()} {email} {phone}".strip()
            patch = {}
            for f, k in snapshot_fields.items():
                v = row.get(f)
                if v is None:
                    continue
                if k == "name":
                    patch[f] = name
                elif k == "email":
                    patch[f] = email
                elif k == "phone":
                    patch[f] = phone
                elif k == "address":
                    patch[f] = street
                elif k == "haystack":
                    patch[f] = haystack
            if patch:
                await coll.update_one({"_id": row["_id"]}, {"$set": patch})
                scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(
            f"[preview_scrubber] {coll_name} snapshot scrub error: {exc}"
        )
    counts[coll_name] = counts.get(coll_name, 0) + scrubbed


# Snapshot-field maps for Pass 2.
# 2026-02 · P0 Stage 3 Step C — expanded from 8 collections to 15,
# matching the per-collection inventory in Step A §4.
_SNAPSHOT_MAPS: Dict[str, Dict[str, str]] = {
    "quotes": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone", "customer_address": "address",
        "bill_to_name": "name", "bill_to_email": "email",
        "bill_to_phone": "phone", "bill_to_address": "address",
        "search_haystack": "haystack",
    },
    "invoices": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
        "bill_to_name": "name", "bill_to_email": "email",
        "bill_to_address": "address",
        "search_haystack": "haystack",
    },
    "jobs": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone", "customer_address": "address",
        "search_haystack": "haystack",
    },
    "estimates": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
        "bill_to_name": "name", "bill_to_email": "email",
        "bill_to_address": "address",
        "search_haystack": "haystack",
    },
    "recurring_job_templates": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
    },
    "service_reports": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
    },
    "payments": {
        "customer_name": "name", "customer_email": "email",
    },
    "tasks": {
        "customer_name": "name", "customer_email": "email",
    },
    "appointments": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
    },
    "portal_appointments": {
        "customer_name": "name", "customer_email": "email",
        "customer_phone": "phone",
    },
    "contracts": {
        "signer_name": "name", "signer_email": "email",
    },
    "signed_contracts": {
        "signer_name": "name", "signer_email": "email",
    },
    "csat_responses": {
        "respondent_name": "name", "email": "email",
    },
    "calendar_events": {
        "customer_name": "name",
    },
}


async def _scrub_messages_sender_name(db, counts: Dict[str, int]) -> None:
    """``messages.sender_name`` on ``sender=customer`` rows carries
    the real customer name. Replace with ``Preview Customer{slug}``
    where slug derives from the current (post-synth) customer name.
    AI/business senders (``sender_name="Marina (AI)"`` etc.) are
    left intact.

    Also blanket-redact ``text`` on customer-sender rows — the
    free-text template is ``AI escalation from {real_name} · {skill}
    concierge\\nReason: ...\\nCustomer said: {real_quote}`` which
    carries real names + real quoted messages that the standard
    free-text redactor can't catch (names aren't regex-matchable).
    """
    if not hasattr(db, "messages"):
        return
    scrubbed = 0
    text_scrubbed = 0
    try:
        cursor = db.messages.find(
            {"sender": "customer",
             "$or": [
                 {"sender_name": {"$exists": True, "$ne": None,
                                    "$not": {"$regex": r"^Preview ",
                                               "$options": "i"}}},
                 {"text": {"$exists": True, "$nin": [None, ""]}},
             ]},
            {"_id": 1, "sender_name": 1, "text": 1, "customer_id": 1},
        )
        async for row in cursor:
            patch = {}
            name = row.get("sender_name") or ""
            if name and not _PREVIEW_NAME_RE.match(name):
                bucket = synthetic_bucket(name)
                patch["sender_name"] = f"Preview Customer{bucket:04d}"
                scrubbed += 1
            text = row.get("text") or ""
            # Blanket redact — names aren't regex-matchable so even
            # after the sender_name is scrubbed, the ``text`` can
            # embed real names verbatim.
            if text and text != "[preview — original customer message redacted]":
                patch["text"] = "[preview — original customer message redacted]"
                text_scrubbed += 1
            if patch:
                await db.messages.update_one(
                    {"_id": row["_id"]}, {"$set": patch},
                )
    except Exception as exc:  # pragma: no cover
        _log.warning(
            f"[preview_scrubber] messages.sender_name scrub error: {exc}",
        )
    counts["messages_sender_name"] = scrubbed
    counts["messages_text"] = text_scrubbed


async def _delete_all(db, coll_name: str, counts: Dict[str, int],
                        extra_filter: Optional[Dict[str, Any]] = None) -> None:
    """Delete all docs from a historical/log collection whose
    content pre-dates the preview-isolation layer. These tables
    hold audit trails / archive snapshots / 3rd-party cache
    payloads that carry real-PII strings in nested JSON blobs that
    aren't scrubbable in-place (``snapshot``, ``payload``,
    ``tool_calls``, ``tokens_resolved``). Deleting the rows is the
    only tractable way to purge the PII without parsing arbitrary
    JSON. The collections repopulate from preview-side writes.
    """
    if not hasattr(db, coll_name):
        counts[coll_name] = 0
        return
    coll = getattr(db, coll_name)
    try:
        res = await coll.delete_many(extra_filter or {})
        counts[coll_name] = res.deleted_count
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] {coll_name} delete error: {exc}")
        counts[coll_name] = 0


async def _scrub_properties(db, counts: Dict[str, int]) -> None:
    """Null the geo-identifier fields on ``properties``. The main
    ``address`` string gets regenerated by the migration from
    customer-scrub (``backfilled_from_customer=True`` rows), but
    the ``geocoded_address`` / ``lat`` / ``lng`` / ``geocoded_place_id``
    retain the real Google Maps place identifier even after
    ``address`` is swapped. Null them."""
    if not hasattr(db, "properties"):
        return
    scrubbed = 0
    try:
        cursor = db.properties.find(
            {"$or": [
                {"geocoded_address": {"$exists": True, "$nin": [None, ""]}},
                {"lat": {"$exists": True, "$ne": None}},
                {"lng": {"$exists": True, "$ne": None}},
                {"geocoded_place_id": {"$exists": True, "$nin": [None, ""]}},
                {"site_contact.name": {"$exists": True, "$nin": [None, ""]}},
                {"site_contact.phone": {"$exists": True, "$nin": [None, ""]}},
                {"site_contact.phone_e164": {"$exists": True, "$nin": [None, ""]}},
                {"site_contact.email": {"$exists": True, "$nin": [None, ""]}},
                {"site_contact.mobiles.0": {"$exists": True}},
                {"site_contact.emails.0": {"$exists": True}},
                # Nested ``address.*`` with any non-Testville city.
                {"address.city": {"$exists": True,
                                     "$nin": [None, "", "Testville"]}},
                {"address.line1": {"$exists": True,
                                      "$nin": [None, "", "1 Preview St"],
                                      "$not": {"$regex": r"^\d+ Preview\b"}}},
            ]},
            {"_id": 1, "geocoded_address": 1, "lat": 1, "lng": 1,
             "geocoded_place_id": 1, "site_contact": 1, "address": 1},
        )
        async for row in cursor:
            patch: Dict[str, Any] = {}
            for k in ("geocoded_address", "lat", "lng",
                        "geocoded_place_id", "latitude", "longitude"):
                if row.get(k):
                    patch[k] = None
            sc = row.get("site_contact")
            if isinstance(sc, dict):
                # Scrub nested name/email/phone leaves PLUS the
                # arrays (``mobiles[]`` / ``emails[]``) that
                # Site-Contact Phase 1 added. Preserve structural
                # keys (``is_primary_contact``, ``id``).
                new_sc = dict(sc)
                for k in ("name", "email", "phone", "phone_e164"):
                    if new_sc.get(k):
                        new_sc[k] = None
                # Clear nested PII arrays — safer than trying to
                # replace with synthetic shapes since we don't carry
                # the customer anchor into this scrub pass.
                if isinstance(new_sc.get("mobiles"), list) and new_sc["mobiles"]:
                    new_sc["mobiles"] = []
                if isinstance(new_sc.get("emails"), list) and new_sc["emails"]:
                    new_sc["emails"] = []
                patch["site_contact"] = new_sc
            # ``address`` may be a scalar string OR a nested
            # ``{line1, line2, city, state, postal_code, country}``
            # dict. Scrub the nested shape so real street-level PII
            # (``'1509 e maddock rd'``, city ``'Peoria'``) doesn't
            # survive on properties backfilled from pre-scrub
            # imports.
            addr = row.get("address")
            if isinstance(addr, dict):
                patch["address"] = {
                    "line1": "1 Preview St",
                    "line2": None,
                    "city": "Testville",
                    "state": "AZ",
                    "postal_code": "85000",
                    "country": "US",
                }
            if patch:
                await db.properties.update_one(
                    {"_id": row["_id"]}, {"$set": patch},
                )
                scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] properties scrub error: {exc}")
    counts["properties"] = scrubbed


async def _scrub_portal_chat_messages(db, counts: Dict[str, int]) -> None:
    """``portal_chat_messages.sender_name`` / ``body`` on customer
    rows — same blanket-redact pattern as ``messages``."""
    if not hasattr(db, "portal_chat_messages"):
        return
    scrubbed = 0
    try:
        cursor = db.portal_chat_messages.find(
            {"sender_role": "customer",
             "sender_name": {"$exists": True, "$ne": None,
                               "$not": {"$regex": r"^Preview ",
                                          "$options": "i"}}},
            {"_id": 1, "sender_name": 1, "body": 1},
        )
        async for row in cursor:
            patch: Dict[str, Any] = {}
            name = row.get("sender_name") or ""
            if name:
                bucket = synthetic_bucket(name)
                patch["sender_name"] = f"Preview Customer{bucket:04d}"
            if row.get("body"):
                patch["body"] = "[preview — original message redacted]"
            if patch:
                await db.portal_chat_messages.update_one(
                    {"_id": row["_id"]}, {"$set": patch},
                )
                scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(
            f"[preview_scrubber] portal_chat_messages scrub error: {exc}",
        )
    counts["portal_chat_messages"] = scrubbed


async def _scrub_jobs_technician_name(db, counts: Dict[str, int]) -> None:
    """``jobs.technician_name`` denorm — recompute from the current
    technician's user record. Rows where technician_name doesn't
    match any current technician get nulled so stale snapshots
    don't leak."""
    if not hasattr(db, "jobs"):
        return
    # Build a tech-id → current-name lookup (users with
    # role=technician — their names are already preview-shape OR
    # legit test-fixture tech names like "Terry Tech" which are
    # NOT customer PII).
    tech_map: Dict[str, str] = {}
    try:
        async for u in db.users.find({"role": "technician"}, {"id": 1, "name": 1}):
            if u.get("id") and u.get("name"):
                tech_map[u["id"]] = u["name"]
    except Exception:
        pass
    # Walk jobs where technician_name is set but doesn't match the
    # current tech_map value — i.e. a stale real-PII snapshot.
    scrubbed = 0
    try:
        cursor = db.jobs.find(
            {"technician_name": {"$exists": True, "$nin": [None, ""]}},
            {"_id": 1, "technician_id": 1, "technician_name": 1},
        )
        async for row in cursor:
            tid = row.get("technician_id")
            current = tech_map.get(tid)
            snap = row.get("technician_name") or ""
            if current and snap == current:
                continue
            if current:
                await db.jobs.update_one(
                    {"_id": row["_id"]},
                    {"$set": {"technician_name": current}},
                )
            else:
                await db.jobs.update_one(
                    {"_id": row["_id"]},
                    {"$set": {"technician_name": None}},
                )
            scrubbed += 1
    except Exception as exc:  # pragma: no cover
        _log.warning(f"[preview_scrubber] jobs.technician_name error: {exc}")
    counts["jobs_technician_name"] = scrubbed


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
    for coll_name, snapshot_map in _SNAPSHOT_MAPS.items():
        await _snapshot_scrub(db, coll_name, snapshot_map, counts)

    # ────────────────────────────────────────────────────────────
    # Pass 2b — Step C expansion: stateful user-facing collections.
    # ────────────────────────────────────────────────────────────
    await _scrub_properties(db, counts)
    await _scrub_portal_chat_messages(db, counts)
    await _scrub_jobs_technician_name(db, counts)
    # leads.referrer_customer_name — snapshot-shape single field.
    await _snapshot_scrub(db, "leads",
                            {"referrer_customer_name": "name"}, counts)

    # Pass 3 — free-text redaction on message / template / audit bodies.
    # Step C expansion: ``messages.text`` + ``messages.sender_name``
    # (``sender_name`` carries real customer names on ``sender=customer``
    # rows; the redactor pattern-match + customer-scoped synth
    # happens in ``_scrub_messages_sender_name`` below).
    await _redact_free_text_in_coll(db, "messages",
                                     ["body", "preview", "text",
                                      "sender_name"], counts)
    await _scrub_messages_sender_name(db, counts)
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

    # ────────────────────────────────────────────────────────────
    # Pass 3b — Step C expansion: delete-all on pure historical /
    # log / audit / snapshot collections. These tables hold archived
    # customer PII in nested JSON blobs (``snapshot``, ``payload``,
    # ``tool_calls``, ``meta``, ``tokens_resolved``) that are not
    # scrubbable in-place without parsing arbitrary JSON per-row.
    # On preview, no admin flow depends on these histories — they
    # repopulate from post-scrub preview-side writes.
    # ``audit_logs`` is purged with a filter that preserves our own
    # ``pii_boot_scrub`` entries (otherwise the 24h dedup breaks).
    # ────────────────────────────────────────────────────────────
    for coll_name in (
        "deletion_audit", "hard_delete_tombstones",
        "invoice_status_audit", "document_versions",
        "audit_events", "workstream_events",
        "marketing_event_ledger", "outbound_emails",
        "comms_send_log", "comms_suppression_log",
        "marketing_deliveries", "communication_sends",
        "communications_log", "dunning_reminders",
        "customer_phone_cleanup_log",
        "notification_dispatch_log", "ai_copilot_log",
        "ai_employee_messages", "zillow_cache",
    ):
        await _delete_all(db, coll_name, counts)
    # audit_logs — keep our own scrub audit entries only.
    await _delete_all(db, "audit_logs", counts,
                       extra_filter={"event": {"$nin": ["pii_boot_scrub",
                                                            "pii_scrub"]}})
    # notifications — delete inbound-customer-message kinds (titles
    # embed real names); operational system alerts (inventory_low_stock,
    # scorecard_digest, etc.) survive.
    await _delete_all(db, "notifications", counts,
                       extra_filter={
                           "$or": [
                               {"kind": "inbound_customer_message"},
                               {"title": {"$regex": r"(carson|peterson|segelbaum|maddock|lawdawg|whitmore|blake|gomez|hernandez)", "$options": "i"}},
                               {"body":  {"$regex": r"(carson|peterson|segelbaum|maddock|lawdawg|whitmore|blake|gomez|hernandez)", "$options": "i"}},
                           ],
                       })

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
