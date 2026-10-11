"""Preview isolation · payload sanitizer + REJECT pattern enforcement.

The three callables below are the sole entrypoints for ingress-site
sanitization:

* ``sanitize_pii_payload(data, kind)`` — accepts a dict / list / str /
  None. On production env it's a no-op (returns the input
  unchanged). On preview env it recurses through dicts + lists, maps
  every known PII field name to its synthetic equivalent, runs the
  free-text redactor on notes-shape fields, and raises
  ``PIIIngressRejected`` if the payload carries a live Stripe token,
  a raw SSN, a CC number, or a DOB-shaped date.

* ``sanitize_csv_rows(rows, kind)`` — same contract for a list of
  dicts (CSV import). Each row is sanitized in isolation.

* ``sanitize_pdf_extracted_rows(rows)`` — same for the PDF-invoice
  importer's extracted rows (``routers/imports.py`` consumes this).

The decorator pattern is actually implemented as (a) an ASGI
middleware for JSON-body routes (zero-touch, see ``middleware.py``)
and (b) an explicit function call for CSV / PDF / multipart routes
that the handler invokes right after parsing the body.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from .config import is_production_env
from .redactor import redact_free_text
from .synthesizer import (
    synthesize_customer_fields,
    synthesize_lead_fields,
    synthesize_subscriber_fields,
)


class PIIIngressRejected(Exception):
    """Raised by the sanitizer when a payload carries a REJECT-class
    field (live Stripe payment-method tokens, raw SSNs, CC numbers,
    DL numbers, or DOB-shaped dates). The FastAPI exception handler
    translates this to HTTP 400 with code ``pii.ingress_rejected``.
    """

    def __init__(self, reason: str, field: str, value_hint: str = ""):
        self.reason = reason
        self.field = field
        self.value_hint = value_hint[:20]
        super().__init__(f"PII ingress rejected: {reason} on field '{field}'")


# ────────────────────────────────────────────────────────────────────
# Field maps — per-kind set of top-level keys that get synthesized.
# ────────────────────────────────────────────────────────────────────
_CUSTOMER_PII_KEYS = {
    "name", "first_name", "last_name", "display_name", "full_name",
    "email", "emails",
    "phone", "phones", "phone_mobile", "mobile", "mobiles", "fax",
    "address", "address_line_1", "address_line_2", "street",
    "street_address", "service_address", "bill_to_address",
    "city", "state", "zip", "zip_code", "postal_code", "country",
    "company", "company_name", "business_name",
    "latitude", "longitude",
}
_LEAD_PII_KEYS = _CUSTOMER_PII_KEYS
_SUBSCRIBER_PII_KEYS = {
    "name", "first_name", "last_name", "display_name",
    "email", "phone",
}
_FREE_TEXT_KEYS = {
    "notes", "service_notes", "description", "internal_notes",
    "memo", "signer_message",
}
_CUSTOM_FIELDS_KEYS = {"custom_fields"}
_TAGS_KEYS = {"tags"}

# ────────────────────────────────────────────────────────────────────
# REJECT patterns — raise rather than sanitize.
# ────────────────────────────────────────────────────────────────────
_SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")
_DOB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CC_RE = re.compile(r"^(?:\d[ \-]?){13,19}$")
_LIVE_STRIPE_PM = re.compile(r"^pm_live_[A-Za-z0-9]+$")
_LIVE_STRIPE_CUS = re.compile(r"^cus_live_[A-Za-z0-9]+$")
# Any Stripe token that doesn't carry the ``_test_`` prefix.
_STRIPE_NON_TEST = re.compile(r"^(pm_|cus_|src_|ba_)(?!test_)[A-Za-z0-9_]+$")
_DL_RE = re.compile(r"^[A-Z]{1,2}\d{6,10}$")
_DOB_FIELD_NAMES = {"dob", "date_of_birth", "birthday"}


def _reject_check(key: str, value: Any) -> None:
    """Raise ``PIIIngressRejected`` if ``value`` matches a REJECT
    pattern. No-op on non-strings or None."""
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_check(key, item)
        return
    if not isinstance(value, str):
        return
    v = value.strip()
    kname = key.lower()
    if _SSN_RE.match(v):
        raise PIIIngressRejected("ssn_rejected", key, v)
    if kname in _DOB_FIELD_NAMES and _DOB_RE.match(v):
        raise PIIIngressRejected("dob_rejected", key, v)
    if _CC_RE.match(v):
        raise PIIIngressRejected("cc_rejected", key, v)
    if _DL_RE.match(v) and "licens" in kname:
        raise PIIIngressRejected("dl_rejected", key, v)
    if _LIVE_STRIPE_PM.match(v) or _LIVE_STRIPE_CUS.match(v):
        raise PIIIngressRejected("live_stripe_token_rejected", key, v)
    # Catch-all: any Stripe-looking token without ``_test_`` on
    # non-sandbox envs. On preview, we don't want live tokens at
    # all — refuse the write.
    if "stripe" in kname and _STRIPE_NON_TEST.match(v) and "test" not in v:
        raise PIIIngressRejected("live_stripe_token_rejected", key, v)


# ────────────────────────────────────────────────────────────────────
# Sanitization — recursive dict/list walk.
# ────────────────────────────────────────────────────────────────────
def _sanitize_dict(data: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """Walk ``data`` once. Returns a NEW dict — caller's input is
    not mutated."""
    out: Dict[str, Any] = {}
    # Pass 1 — REJECT check across every top-level field.
    for k, v in data.items():
        _reject_check(k, v)

    # Pass 2 — merge in the kind-specific synthetic patch for the
    # recognized PII keys. We copy ``data`` first, then
    # ``synthesize_*_fields`` only touches the known keys.
    if kind == "customer":
        base = synthesize_customer_fields(data)
    elif kind == "lead":
        base = synthesize_lead_fields(data)
    elif kind == "subscriber":
        base = synthesize_subscriber_fields(data)
    else:
        base = dict(data)

    # Pass 3 — redact free-text fields + custom_fields values.
    for k, v in base.items():
        if k in _FREE_TEXT_KEYS and isinstance(v, str):
            out[k] = redact_free_text(v)
        elif k in _CUSTOM_FIELDS_KEYS and isinstance(v, dict):
            out[k] = {ck: redact_free_text(cv) if isinstance(cv, str) else cv
                       for ck, cv in v.items()}
        elif k in _TAGS_KEYS and isinstance(v, list):
            # Tags are typically short labels; leave them pass-through
            # (per Refinement 1 — tag registry lookup is a follow-up).
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _sanitize_dict(v, kind=kind)
        elif isinstance(v, list):
            out[k] = [
                _sanitize_dict(item, kind=kind) if isinstance(item, dict)
                else item
                for item in v
            ]
        else:
            out[k] = v
    return out


def sanitize_pii_payload(data: Any, kind: str = "customer") -> Any:
    """Public entrypoint. Production env → identity. Preview env →
    sanitized copy. Raises ``PIIIngressRejected`` on REJECT patterns.

    ``kind`` is one of ``customer``, ``lead``, ``subscriber``, or
    ``generic`` (free-text only — no field-level synthesis).
    """
    if is_production_env():
        return data
    if data is None:
        return None
    if isinstance(data, dict):
        return _sanitize_dict(data, kind=kind)
    if isinstance(data, list):
        return [sanitize_pii_payload(item, kind=kind) for item in data]
    if isinstance(data, str):
        return redact_free_text(data)
    return data


def sanitize_csv_rows(rows: Iterable[Dict[str, Any]],
                       kind: str = "customer") -> List[Dict[str, Any]]:
    """Sanitize a CSV-import row list. Each row is a dict of
    column-name → cell-value. Production: identity. Preview:
    synthesized."""
    if is_production_env():
        return list(rows)
    return [_sanitize_dict(r, kind=kind) for r in rows]


def sanitize_pdf_extracted_rows(rows: Iterable[Dict[str, Any]]
                                 ) -> List[Dict[str, Any]]:
    """Thin alias for the PDF-invoice importer. The extractor
    returns rows with ``customer_name`` / ``bill_to_address`` /
    etc. keys — the customer synth-field map handles them."""
    return sanitize_csv_rows(rows, kind="customer")


__all__ = [
    "PIIIngressRejected",
    "sanitize_pii_payload",
    "sanitize_csv_rows",
    "sanitize_pdf_extracted_rows",
]
