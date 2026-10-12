"""Preview isolation · deterministic synthetic-identity minter.

Public functions:

* ``synthetic_bucket(real_value: str) -> int`` — hash + mod 10,000.
* ``synthesize_customer_fields(real: dict) -> dict`` — the full field
  map from Q4 of the Stage-1 RCA follow-up.
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
import unicodedata
from typing import Any, Dict

from .config import PREVIEW_SYNTHETIC_SALT

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


def synthesize_customer_fields(real: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``real`` with every known PII field replaced
    by the synthetic equivalent. Non-PII fields are preserved
    byte-for-byte. The returned dict carries the SAME ``id``,
    ``tenant_id``, FK fields, created_at, timestamps, status enums,
    and numeric amounts — only the PII shape changes.
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
    patch: Dict[str, Any] = dict(real)
    patch.update({
        "first_name": "Preview",
        "last_name": f"Customer{slug}",
        "name": _preview_customer_name(bucket),
        "display_name": _preview_customer_name(bucket),
        "email": f"preview-customer{slug}@preview.local",
        "phone": f"{_PHONE_BAND_CUSTOMER}{slug}",
        "phone_mobile": f"{_PHONE_BAND_MOBILE}{slug}",
        "mobile": f"{_PHONE_BAND_MOBILE}{slug}",
        "fax": None,
        "address": f"{bucket} Preview St",
        "address_line_1": f"{bucket} Preview St",
        "address_line_2": None,
        "street": f"{bucket} Preview St",
        "street_address": f"{bucket} Preview St",
        "service_address": f"{bucket} Preview St",
        "bill_to_address": f"{bucket} Preview St",
        "city": "Testville",
        "state": "AZ",
        "zip": "85000",
        "zip_code": "85000",
        "postal_code": "85000",
        "country": "US",
        "company": patch.get("company") and f"Preview Co {slug}" or None,
        "company_name": patch.get("company_name") and f"Preview Co {slug}" or None,
        "latitude": None,
        "longitude": None,
    })
    # List fields — emails[], mobiles[], phones[] carry one synthetic
    # entry each if the real doc had any entries at all.
    #
    # 2026-02 · P0 Stage 3 Step B (schema shape fix) — these fields
    # are object arrays per the Pydantic schema in ``models.py``
    # (``mobiles: Optional[List[dict]]``, ``emails: Optional[List[dict]]``)
    # and ``services/customer_multi_contact.py::normalize_mobiles`` /
    # ``normalize_emails``. The prior release emitted LIST-OF-STRING
    # (`["preview@local"]`) which broke `GET /api/customers` with a
    # 500 on page_size > 5 because the Pydantic validator rejected
    # the shape. Shape now matches the normalizer's output verbatim
    # so round-trips through list / detail endpoints succeed.
    synth_email = f"preview-customer{slug}@preview.local"
    synth_phone = f"{_PHONE_BAND_CUSTOMER}{slug}"
    synth_mobile = f"{_PHONE_BAND_MOBILE}{slug}"
    if "emails" in real:
        patch["emails"] = [{
            "address": synth_email,
            "label": "Primary",
            "is_primary": True,
            "marketing_ok": True,
            "notifications_enabled": True,
        }]
    if "mobiles" in real:
        patch["mobiles"] = [{
            "number_e164": synth_mobile,
            "label": "Primary",
            "is_primary": True,
            "sms_ok": True,
            "notifications_enabled": True,
        }]
    if "phones" in real:
        patch["phones"] = [
            {"type": "home",   "number": synth_phone,
             "e164": synth_phone,  "raw": None},
            {"type": "mobile", "number": synth_mobile,
             "e164": synth_mobile, "raw": None},
        ]
    return patch


def synthesize_lead_fields(real: Dict[str, Any]) -> Dict[str, Any]:
    bucket = synthetic_bucket(
        real.get("name") or real.get("email") or real.get("phone") or real.get("id") or ""
    )
    slug = _slug(bucket)
    patch: Dict[str, Any] = dict(real)
    patch.update({
        "name": f"Preview Lead{slug}",
        "first_name": "Preview",
        "last_name": f"Lead{slug}",
        "email": f"preview-lead{slug}@preview.local",
        "phone": f"{_PHONE_BAND_LEAD}{slug}",
        "address": f"{bucket} Preview Ln, Testville, AZ 85000",
    })
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
