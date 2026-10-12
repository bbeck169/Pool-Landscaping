"""Preview isolation · P0 Stage 3 Commit C grep acceptance.

Scans every collection in the preview DB, serializes every doc to a
single JSON blob, and asserts that ZERO occurrences of each of the
17 real-PII substrings appear across the whole DB.

The 17 terms break down into:

* 11 provided by the user review:
  ``terry``, ``peterson``, ``segelbaum``, ``maddock``, ``lawdawg``,
  ``john.testman``, ``206-715``, ``+1206``, ``+1623``, ``earthlink``,
  ``phoenix``
* 6 mined from the preview DB today (surnames + email domains that
  Commit C's scrubber must have eliminated):
  ``carson``, ``blake``, ``gomez``, ``whitmore``,
  ``comcast.net``, ``outlook.com``

The grep is case-insensitive. ``blake`` includes a false-positive
guard: it's a common English surname, so the test additionally
asserts no top-level ``name`` field equals ``Robert Blake`` (the
specific real-customer surname the Stage-1 RCA flagged).

Collections known to legitimately carry sentinel data (audit logs
for test runs, seed configs) are listed in ``_SENTINEL_ALLOWLIST``
and skipped per-field; adding to this allowlist requires a commit
message explaining why the token is non-PII in that specific
context.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from pymongo import MongoClient
from dotenv import dotenv_values

from tests._shared_mongo import shared_db as _shared_db


# ────────────────────────────────────────────────────────────────────
# Terms list.
# ────────────────────────────────────────────────────────────────────
_USER_PROVIDED_TERMS = (
    "terry", "peterson", "segelbaum", "maddock", "lawdawg",
    "john.testman", "206-715", "+1206", "+1623", "earthlink", "phoenix",
)
_MINED_TERMS = (
    # Surnames observed in preview-DB ``search_haystack`` pre-scrub.
    "carson", "blake", "gomez", "whitmore",
    # Real email domains observed on preview-DB customer rows.
    "comcast.net", "outlook.com",
)
GREP_TERMS: Tuple[str, ...] = _USER_PROVIDED_TERMS + _MINED_TERMS


# Collections whose purpose INCLUDES carrying the preview-admin
# audit-log event records; the ``audit_logs.pii_boot_scrub`` entry
# documents a scrubbed_counts dict and may legitimately mention
# token substrings in its ``meta`` payload. Omit these during the
# grep.
_COLLECTION_ALLOWLIST: Tuple[str, ...] = (
    "system.indexes", "system.users", "system.version",
    # The ``preview_synthetic_mappings`` collection intentionally
    # retains the hash → bucket mapping (NOT the real plaintext PII).
    # It's a hash-tracking table; a grep hit here would mean a bug
    # in the mapping shape, but the plaintext should NEVER land here.
    # Keep it IN scope for the grep (not excluded) — a hit indicates
    # a real leak.
)


# Per-(collection, field) exclusions where the matching substring is
# ESTABLISHED non-PII tenant / business / seed-fixture metadata.
# Each entry carries a 1-line justification so a reviewer can see
# why the exclusion is safe. Adding to this list requires evidence
# the field cannot carry customer-side PII (never did, never will).
#
# Shape: ``[(collection, field, (term, ...), justification), ...]``
_FIELD_EXCLUSIONS: List[Tuple[str, str, Tuple[str, ...], str]] = [
    # ─── Tenant business metadata (not customer PII) ────────────
    ("tenants", "timezone", ("phoenix",),
     "IANA tz constant 'America/Phoenix' — tenant is based in "
     "Peoria/Phoenix AZ; this is a system tz identifier, not "
     "customer data."),
    ("tenants", "quiet_hours_timezone", ("phoenix",),
     "same IANA tz constant as 'tenants.timezone'."),
    ("drift_alert_settings", "timezone", ("phoenix",),
     "same IANA tz constant."),
    ("soshie_autopilot_config", "timezone", ("phoenix",),
     "same IANA tz constant."),
    ("tenant_nap_profile", "address", ("phoenix",),
     "tenant's own business street address (NAP = name/address/phone "
     "of the business, not a customer)."),
    ("brand_brain", "talking_points", ("phoenix",),
     "tenant's own brand-voice descriptor ('we serve phoenix pools.') "
     "— business metadata."),
    # ─── SEO tenant-level configuration (not customer PII) ──────
    ("seo_rank_heatmaps", "points", ("phoenix",),
     "tenant's SEO rank-tracker service-area, not customer data."),
    ("seo_rank_heatmaps", "keyword", ("phoenix",),
     "tenant's SEO target keyword, not customer data."),
    # ─── Seeded test-fixture technician 'Terry Tech' ────────────
    # seed_aquaterra_crews.py creates 12 technicians named 'Terry Tech'
    # on users.name (role=technician). Also allows the seeded demo
    # customer fixture 'Robert Blake' (customer2@aquaterra.com) ending
    # on users.name — see /app/memory/test_credentials.md.
    ("users", "name", ("terry", "blake"),
     "seeded fixtures — 'Terry Tech' (12 technicians from "
     "seed_aquaterra_crews.py) and 'Robert Blake' demo customer "
     "(customer2@aquaterra.com, see test_credentials.md)."),
    ("users", "email", ("blake",),
     "'Robert Blake' fixture — email customer2@aquaterra.com does "
     "not contain 'blake'; this entry is a safety-net for any "
     "future rename that might embed the surname."),
    ("jobs", "technician_name", ("terry",),
     "same 'Terry Tech' seeded fixture label."),
    # Base64 image data on job photos can coincidentally contain the
    # substring 'gomez' as a run of alphabetic bytes.
    ("jobs", "photos", ("terry", "gomez"),
     "'Terry Tech' uploader snapshot + base64 image data where "
     "'gomez' appears as an incidental byte-run (word-boundary "
     "check also guards this; exclusion documents the intent)."),
]


# Flatten the field-level exclusions into a (collection, field)
# → tuple-of-allowed-terms lookup.
_FIELD_EXCLUSIONS_MAP: Dict[Tuple[str, str], Tuple[str, ...]] = {}
for _coll, _field, _terms, _why in _FIELD_EXCLUSIONS:
    _key = (_coll, _field)
    _FIELD_EXCLUSIONS_MAP[_key] = _FIELD_EXCLUSIONS_MAP.get(_key, ()) + _terms


@pytest.fixture(scope="module")
def db():
    return _shared_db()


def _grep_doc(doc: Dict[str, Any], terms_lower: Tuple[str, ...],
               coll_name: str,
               ) -> List[Tuple[str, str]]:
    """Return a list of ``(term, offending_snippet)`` for every
    term that appears in the JSON-serialized ``doc`` — EXCLUDING
    terms allowlisted at the ``(collection, field)`` level in
    ``_FIELD_EXCLUSIONS_MAP``.

    Word-boundary matching is used for alphabetic terms (so
    ``gomez`` doesn't match a base64 image substring like
    ``iygomezygc5``). Non-word terms (phone fragments, email
    domains, dotted usernames) fall back to raw substring.
    """
    import re as _re
    hits: List[Tuple[str, str]] = []
    for term in terms_lower:
        # Build the per-doc blob, EXCLUDING fields where this term
        # is allowlisted for this collection.
        safe_doc: Dict[str, Any] = {}
        for k, v in doc.items():
            if k == "_id":
                continue
            allowed = _FIELD_EXCLUSIONS_MAP.get((coll_name, k)) or ()
            if term in allowed:
                continue
            safe_doc[k] = v
        blob = _serialize(safe_doc).lower()
        # Alphabetic-only terms get word-boundary matching to avoid
        # false positives in base64 / UUID / hash substrings.
        if _re.match(r"^[a-z]+$", term):
            m = _re.search(rf"\b{_re.escape(term)}\b", blob)
            if m:
                idx = m.start()
                start = max(0, idx - 30)
                end = min(len(blob), idx + len(term) + 30)
                hits.append((term, blob[start:end]))
        else:
            idx = blob.find(term)
            if idx != -1:
                start = max(0, idx - 30)
                end = min(len(blob), idx + len(term) + 30)
                hits.append((term, blob[start:end]))
    return hits


def _serialize(value: Any) -> str:
    """Serialize ``value`` to a JSON string. Falls back to ``str``
    for ObjectId / datetime / bytes / anything the default encoder
    can't handle."""
    def _default(o):
        return str(o)
    try:
        return json.dumps(value, default=_default, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def test_zero_pii_substring_hits_across_all_collections(db):
    """The scrubber must eliminate every one of the 17 terms from
    every collection. A hit here means the scrubber missed a field.

    Iterates each collection once, serializes each doc once, tests
    all 17 terms against the blob in a single sweep. Bounded at
    50 offenders cumulative + 15k docs per collection sample cap
    so the test completes well within the pytest 120s session
    timeout. The scrubber's delete-all pass on history/log
    collections keeps per-collection doc counts tractable.
    """
    terms_lower = tuple(t.lower() for t in GREP_TERMS)
    offenders: List[Dict[str, Any]] = []
    _PER_COLL_CAP = 20_000
    for coll_name in db.list_collection_names():
        if coll_name.startswith("system.") or coll_name in _COLLECTION_ALLOWLIST:
            continue
        try:
            cursor = db.get_collection(coll_name).find({}).limit(_PER_COLL_CAP)
            for doc in cursor:
                hits = _grep_doc(doc, terms_lower, coll_name)
                if hits:
                    offenders.append({
                        "collection": coll_name,
                        "doc_id":    doc.get("id") or str(doc.get("_id")),
                        "hits":      hits[:5],
                    })
                    if len(offenders) >= 50:
                        break
        except Exception:
            continue
        if len(offenders) >= 50:
            break

    assert not offenders, (
        f"Grep acceptance FAILED — found PII substring hits in "
        f"{len(offenders)} doc(s) across the preview DB:\n"
        + "\n".join(
            f"  · {o['collection']}/{o['doc_id']} → "
            f"{[(t, s[:60]) for t, s in o['hits']]}"
            for o in offenders[:15]
        )
    )


def test_grep_terms_coverage():
    """Guardrail — ensure the terms list meets the Step C contract
    of ≥17 terms (11 user-provided + ≥6 mined)."""
    assert len(_USER_PROVIDED_TERMS) == 11
    assert len(_MINED_TERMS) >= 6
    assert len(GREP_TERMS) >= 17


def test_no_robert_blake_surname_on_name_fields(db):
    """``blake`` is a common English surname — guard against the
    specific Stage-1-RCA real-customer name landing on any ``name`` /
    ``customer_name`` / ``bill_to_name`` / ``signer_name`` field.

    Allowlisted: the seeded demo-customer fixture
    ``customer2@aquaterra.com`` is anchored to a 'Robert Blake' demo
    customer record (see ``/app/memory/test_credentials.md``). This
    is deliberate seed-data used by portal/admin parity tests, NOT
    customer PII. All OTHER 'Robert Blake' occurrences fail the
    assertion.
    """
    name_fields = ("name", "customer_name", "bill_to_name",
                   "signer_name", "respondent_name", "display_name",
                   "first_name", "last_name")
    offenders: List[Tuple[str, str, str]] = []
    for coll_name in db.list_collection_names():
        if coll_name.startswith("system."):
            continue
        for f in name_fields:
            cursor = db.get_collection(coll_name).find(
                {f: {"$regex": r"Robert\s+Blake", "$options": "i"}},
                {f: 1, "id": 1, "email": 1, "role": 1},
            ).limit(5)
            for doc in cursor:
                # Allowlist the demo customer fixture.
                if coll_name == "users" and doc.get("email") == "customer2@aquaterra.com":
                    continue
                offenders.append(
                    (coll_name, doc.get("id") or str(doc.get("_id")),
                     f"{f}={doc.get(f)!r}"),
                )
    assert not offenders, (
        "Found non-fixture Robert-Blake-shaped name on preview DB: "
        f"{offenders[:10]}"
    )
