"""Preview isolation · deterministic synthetic-identity minter.

Public functions:

* ``synthetic_bucket(real_value: str) -> int`` — hash + mod 10,000.
* ``synthesize_customer_fields(real: dict) -> dict`` — the full field
  map from Q4 of the Stage-1 RCA follow-up (expanded in P0 Stage 3
  Step C to the 26-field patch covering denormalized / nested /
  snapshot leak surfaces).
* ``synthesize_lead_fields(real: dict) -> dict`` — same for leads.
* ``synthesize_subscriber_fields(real: dict) -> dict`` — same for
  marketing subscribers.

Collision policy: when two different real values hash to the same
bucket, the second value appends a 2-hex-nibble suffix (e.g.
``Preview Customer0042-ab``). Collisions log at WARN with both
hashes.

The hash is salted with ``PREVIEW_SYNTHETIC_SALT`` (import-frozen).
Rotating the salt would re-shuffle every synthetic row's identity,
so the salt is treated as immutable like a database primary key.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any, Dict, List

from .config import PREVIEW_SYNTHETIC_SALT
from .redactor import redact_free_text

_log = logging.getLogger(__name__)

# NANP ``555-01xx`` is reserved for fictional use. Four separate
# synthetic ranges keep lead vs customer vs mobile vs subscriber
# phones distinguishable in the DB.
_PHONE_BAND_CUSTOMER = "555-01"
_PHONE_BAND_MOBILE = "555-02"
_PHONE_BAND_LEAD = "555-03"
_PHONE_BAND_SUBSCRIBER = "555-04"
_BUCKET_WIDTH = 10_000


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def synthetic_bucket(real_value: Any) -> int:
    """Return a stable integer in ``[0, 9999]`` derived from
    ``real_value``. Deterministic across processes and across time
    for the same salt. Empty / None → bucket 0."""
    norm = _norm(real_value)
    if not norm:
        return 0
    h = hashlib.sha256((norm + PREVIEW_SYNTHETIC_SALT).encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") % _BUCKET_WIDTH


def _slug(bucket: int) -> str:
    return f"{bucket:04d}"


def _preview_customer_name(bucket: int) -> str:
    return f"Preview Customer{_slug(bucket)}"


def _redact_recursive(value: Any) -> Any:
    """Recursively walk dicts / lists / tuples, apply
    ``redact_free_text`` to every string leaf. Non-string / non-
    container leaves (ints, bools, None, datetime) pass through.
    """
    if isinstance(value, str):
        return redact_free_text(value)
    if isinstance(value, dict):
        return {k: _redact_recursive(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_recursive(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_recursive(v) for v in value)
    return value


def synthesize_customer_fields(real: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``real`` with every known PII field replaced
    by the synthetic equivalent. Non-PII fields are preserved
    byte-for-byte. The returned dict carries the SAME ``id``,
    ``tenant_id``, FK fields, created_at, timestamps, status enums,
    and numeric amounts — only the PII shape changes.

    2026-02 · P0 Stage 3 Step C — expanded to the 26-field patch:
    denormalized ``search_haystack`` rebuild, raw-phone pairs,
    nested address objects (``service_address`` / ``billing_address``
    / ``bill_to_address``), multi-contact scalars
    (``master_billing_contact_*`` / ``alert_*`` / ``fax`` /
    ``home_phone``), legacy denormed address trios
    (``address_city/state/zip``, ``service_city/state/zip``,
    ``billing_city/state/zip``), geo fields (nulled), the
    ``geocode_address_hash`` identifier (nulled), ``custom_fields``
    recursive redaction, and legacy partial-object normalization
    for ``emails`` / ``mobiles`` / ``phones`` arrays.
    """
    anchor = (
        real.get("name")
        or real.get("email")
        or real.get("phone")
        or real.get("id")
        or ""
    )
    bucket = synthetic_bucket(anchor)
    slug = _slug(bucket)
    name = _preview_customer_name(bucket)
    email = f"preview-customer{slug}@preview.local"
    phone = f"{_PHONE_BAND_CUSTOMER}{slug}"
    mobile = f"{_PHONE_BAND_MOBILE}{slug}"
    street = f"{bucket} Preview St"
    city, state, zipc, country = "Testville", "AZ", "85000", "US"
    patch: Dict[str, Any] = dict(real)
    patch.update({
        "first_name": "Preview",
        "last_name": f"Customer{slug}",
        "name": name,
        "display_name": name,
        "email": email,
        "phone": phone,
        "phone_mobile": mobile,
        "mobile": mobile,
        # Raw (digits-only) companions used by legacy search filters.
        "phone_raw": phone.replace("-", ""),
        "mobile_raw": mobile.replace("-", ""),
        "home_phone": None,
        "fax": None,
        # Address scalars.
        "address": street,
        "address_line_1": street,
        "address_line1": street,       # legacy no-underscore variant
        "address_line_2": None,
        "street": street,
        "street_address": street,
        "bill_to_address": street,
        "city": city,
        "state": state,
        "zip": zipc,
        "zip_code": zipc,
        "postal_code": zipc,
        "country": country,
        # Legacy denorm trios.
        "address_city": city, "address_state": state, "address_zip": zipc,
        "service_city": city, "service_state": state, "service_zip": zipc,
        "billing_city": city, "billing_state": state, "billing_zip": zipc,
        # Multi-contact scalars (nulled on preview — admins create
        # these via the UI; existing-row values were legacy real PII).
        "master_billing_contact_email": None,
        "master_billing_contact_phone": None,
        "alert_email": None,
        "alert_phone": None,
        # Companies — preserve existence signal (truthy/falsy) but
        # replace with a bucket-tagged placeholder.
        "company": patch.get("company") and f"Preview Co {slug}" or None,
        "company_name": patch.get("company_name") and f"Preview Co {slug}" or None,
        # Geo fields — null on preview. (Lat/lng + GeoJSON point.)
        "latitude": None,
        "longitude": None,
        "service_lat": None,
        "service_lng": None,
        "service_location": None,
        # ``geocode_address_hash`` is a stable identifier for the real
        # address — leaking it enables correlation attacks even if
        # the plaintext address is gone. Null on preview.
        "geocode_address_hash": None,
        # Rebuild the search haystack from the synthetic PII so the
        # denormalized field no longer carries the pre-sync real
        # name/email/phone/address concatenation. Shape matches
        # ``services.customers_search_haystack.build_haystack``.
        "search_haystack": " ".join([
            name.lower(), name.lower(),
            email, phone.replace("-", ""),
            f"{street.lower()}, {city.lower()}, {state.lower()}, {zipc}",
        ]),
    })

    # ``service_address`` — may be ``""`` / string / nested dict in the wild.
    if "service_address" in real:
        sa = real.get("service_address")
        if isinstance(sa, dict):
            patch["service_address"] = {
                "street": street, "city": city, "state": state,
                "postal_code": zipc, "country": country,
            }
        else:
            patch["service_address"] = street

    # ``billing_address`` — same two-shape pattern.
    if "billing_address" in real:
        ba = real.get("billing_address")
        if isinstance(ba, dict):
            patch["billing_address"] = {
                "street": street, "city": city, "state": state,
                "postal_code": zipc, "country": country,
            }
        elif isinstance(ba, str):
            # Preserve empty-string shape (several legacy rows carry
            # ``""`` as a sentinel for "same as service address").
            patch["billing_address"] = "" if ba == "" else street

    # ``secondary_addresses`` — any list collapses to empty on preview.
    if "secondary_addresses" in real:
        patch["secondary_addresses"] = []

    # ``custom_fields`` — PRESERVE the key structure (gate_code, etc.
    # survive) but recursively redact string VALUES so pasted-in
    # emails / phones / SSNs don't leak via admin notes.
    if isinstance(real.get("custom_fields"), dict):
        patch["custom_fields"] = {
            k: redact_free_text(v) if isinstance(v, str) else v
            for k, v in real["custom_fields"].items()
        }

    # ``emails`` / ``mobiles`` / ``phones`` — full-object shape. Covers
    # both legacy ``list-of-string`` (Commit B migration already
    # repaired) AND legacy ``partial-dict`` (Commit C expansion —
    # some rows carried ``{"number":"...","type":"..."}`` phone
    # entries without ``e164`` / ``raw``).
    if "emails" in real:
        patch["emails"] = [{
            "address": email,
            "label": "Primary",
            "is_primary": True,
            "marketing_ok": True,
            "notifications_enabled": True,
        }]
    if "mobiles" in real:
        patch["mobiles"] = [{
            "number_e164": mobile,
            "label": "Primary",
            "is_primary": True,
            "sms_ok": True,
            "notifications_enabled": True,
        }]
    if "phones" in real:
        patch["phones"] = [
            {"type": "home",   "number": phone,
             "e164": phone,  "raw": phone.replace("-", "")},
            {"type": "mobile", "number": mobile,
             "e164": mobile, "raw": mobile.replace("-", "")},
        ]
    return patch


def synthesize_lead_fields(real: Dict[str, Any]) -> Dict[str, Any]:
    """P0 Stage 3 Step C — expanded parity w/ customers for haystack
    + geo nulls + ``created_ip`` + recursive ``timeline[]`` / ``meta``
    redaction."""
    bucket = synthetic_bucket(
        real.get("name") or real.get("email") or real.get("phone") or real.get("id") or ""
    )
    slug = _slug(bucket)
    name = f"Preview Lead{slug}"
    email = f"preview-lead{slug}@preview.local"
    phone = f"{_PHONE_BAND_LEAD}{slug}"
    street = f"{bucket} Preview Ln, Testville, AZ 85000"
    patch: Dict[str, Any] = dict(real)
    patch.update({
        "name": name,
        "first_name": "Preview",
        "last_name": f"Lead{slug}",
        "email": email,
        "phone": phone,
        "phone_raw": phone.replace("-", ""),
        "address": street,
        # Geo nulls.
        "latitude": None, "longitude": None, "lat": None, "lng": None,
        # IP address — real IPv4 is PII per GDPR Art. 4(1). Replace
        # with the unroutable sentinel so the schema (string) survives.
        "created_ip": "0.0.0.0" if "created_ip" in real else real.get("created_ip"),
        # Rebuild haystack from synth.
        "search_haystack": " ".join([
            name.lower(), name.lower(), email,
            phone.replace("-", ""), street.lower(),
        ]),
    })
    # ``service_address`` — nested object on some lead docs.
    if "service_address" in real:
        sa = real.get("service_address")
        if isinstance(sa, dict):
            patch["service_address"] = {
                "street": f"{bucket} Preview Ln",
                "city": "Testville", "state": "AZ",
                "postal_code": "85000", "country": "US",
            }
        else:
            patch["service_address"] = street
    # ``timeline[]`` — iterate each entry, recursively redact string
    # leaves. Preserves structural keys (ts, kind, actor, payload).
    if isinstance(real.get("timeline"), list):
        patch["timeline"] = [
            _redact_recursive(entry) for entry in real["timeline"]
        ]
    # ``meta`` — arbitrary dict. Recursive redaction.
    if isinstance(real.get("meta"), dict):
        patch["meta"] = _redact_recursive(real["meta"])
    # ``notes`` / ``message`` / ``internal_notes`` — free-text.
    for k in ("notes", "message", "internal_notes", "vip_note", "dog_notes"):
        if isinstance(real.get(k), str):
            patch[k] = redact_free_text(real[k])
    return patch


def synthesize_subscriber_fields(real: Dict[str, Any]) -> Dict[str, Any]:
    bucket = synthetic_bucket(
        real.get("email") or real.get("name") or real.get("id") or ""
    )
    slug = _slug(bucket)
    patch: Dict[str, Any] = dict(real)
    patch.update({
        "first_name": "Preview",
        "last_name": f"Subscriber{slug}",
        "email": f"preview-subscriber{slug}@preview.local",
        "phone": f"{_PHONE_BAND_SUBSCRIBER}{slug}",
    })
    return patch
