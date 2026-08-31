"""Phase F5 · Feb-2026 — shared lead-extraction helpers.

**Single source of truth** for turning a form-submission ``values``
dict into a ``leads`` insert doc.  Both the legacy public-form
path (``routers/marketing.py::submit_public_form``) and the widget-
form path (``routers/marketing_forms.py::submit_widget_form``) MUST
import from this module.  A test-time identity assertion locks
that consolidation so the two callers cannot drift again.

Historical context (see /app/memory/PHASE_F5_LEAD_EXTRACTION.md):
prior Feb-2026 patches added a narrow alias whitelist that missed
``first_name`` / ``last_name`` / ``cell_phone`` / ``description`` /
``company_name`` / ``city`` / ``state`` / ``zip``.  Submissions on
those keys landed as leads named ``"Website Visitor"`` with empty
contact columns.  This module expands the alias universe AND adds
first+last name composition, whitespace guarding, and denormalised
address parts on the lead schema so the drop can't recur.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── Alias tables ──────────────────────────────────────────────────
_NAME_ALIASES: List[str] = ["name", "full_name", "fullname"]
_FIRST_NAME_ALIASES: List[str] = ["first_name", "fname", "given_name"]
_LAST_NAME_ALIASES: List[str] = [
    "last_name", "lname", "surname", "family_name",
]
_EMAIL_ALIASES: List[str] = ["email", "email_address"]
_PHONE_ALIASES: List[str] = [
    "phone", "phone_number", "tel", "mobile",
    "cell_phone", "home_phone", "work_phone", "mobile_phone",
]
_NOTES_ALIASES: List[str] = [
    "message", "notes", "details", "comments",
    "description", "description_of_service_needed", "service_needed",
]
_ADDRESS_ALIASES: List[str] = [
    "address", "street_address", "service_address", "street",
]
_CITY_ALIASES: List[str] = ["city", "town"]
_STATE_ALIASES: List[str] = ["state", "region", "province"]
_ZIP_ALIASES: List[str] = [
    "zip", "zipcode", "zip_code", "postal_code", "postcode",
]
_COMPANY_ALIASES: List[str] = [
    "company", "company_name", "business", "business_name",
    "organization",
]
_SERVICE_INTEREST_ALIASES: List[str] = [
    "service_interest", "requested_service", "service", "interest",
]

# Sentinel string for a submission that yielded no usable contact.
# Historical value; do not change without a coordinated backfill
# because the P19 + F5 backfill migrations query on it.
WEBSITE_VISITOR_FALLBACK = "Website Visitor"


def first_str(d: Optional[Dict[str, Any]], keys: List[str]) -> Optional[str]:
    """First non-empty string value under any of ``keys`` in ``d``.

    Empty and whitespace-only strings are treated as missing so
    a form with a required field that the visitor left blank but
    that still POSTed as ``""`` doesn't accidentally shadow a
    later alias.  Non-string values (ints, floats, bools) are
    coerced via ``str()`` and then whitespace-guarded.
    """
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = v if isinstance(v, str) else str(v)
        s = s.strip()
        if s:
            return s
    return None


def compose_name(vals: Dict[str, Any]) -> Optional[str]:
    """Compose ``"First Last"`` from any first/last-name aliases.

    Returns None if neither piece is present.  Whitespace is
    collapsed so ``"  First  "`` + ``"  Last  "`` renders as
    ``"First Last"``.
    """
    first = first_str(vals, _FIRST_NAME_ALIASES) or ""
    last = first_str(vals, _LAST_NAME_ALIASES) or ""
    composed = f"{first} {last}".strip()
    return composed or None


def extract_contact_fields(vals: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Return the full extracted contact record for a form submission.

    Keys are stable and safe to spread into either a ``leads``
    insert or an ``_upsert_lead_from_submission`` call — every
    downstream consumer picks the subset it needs.

    Name-resolution priority:
      1. Direct name aliases (``name`` / ``full_name`` / ``fullname``).
      2. Composed first+last aliases.
      3. None (caller falls back to the WEBSITE_VISITOR sentinel).
    """
    vals = vals or {}
    direct_name = first_str(vals, _NAME_ALIASES)
    composed_name = compose_name(vals) if not direct_name else None
    resolved_name = direct_name or composed_name

    return {
        "name": resolved_name,
        "first_name": first_str(vals, _FIRST_NAME_ALIASES),
        "last_name": first_str(vals, _LAST_NAME_ALIASES),
        "email": first_str(vals, _EMAIL_ALIASES),
        "phone": first_str(vals, _PHONE_ALIASES),
        "message": first_str(vals, _NOTES_ALIASES),
        "address": first_str(vals, _ADDRESS_ALIASES),
        "city": first_str(vals, _CITY_ALIASES),
        "state": first_str(vals, _STATE_ALIASES),
        "zip": first_str(vals, _ZIP_ALIASES),
        "company_name": first_str(vals, _COMPANY_ALIASES),
        "service_interest": first_str(vals, _SERVICE_INTEREST_ALIASES),
    }


def lead_row_from_form_values(*, tid: str, vals: Dict[str, Any],
                                 source_label: str) -> Dict[str, Any]:
    """Build a ``db.leads`` insert doc from ``vals``.

    This is the public-form path's helper (``marketing.py``).
    ``routers/marketing_forms.py`` uses ``extract_contact_fields``
    directly because it upserts via a different code path — but
    they resolve the same field set through this module.
    """
    # Local import avoids a circular import: services -> utils.
    from utils import new_id, now_iso

    fields = extract_contact_fields(vals)
    return {
        "id": new_id(),
        "tenant_id": tid,
        "name": fields["name"] or WEBSITE_VISITOR_FALLBACK,
        "first_name": fields["first_name"] or "",
        "last_name": fields["last_name"] or "",
        "phone": fields["phone"] or "",
        "email": fields["email"] or "",
        "address": fields["address"] or "",
        "service_address": fields["address"] or "",
        "city": fields["city"] or "",
        "state": fields["state"] or "",
        "zip": fields["zip"] or "",
        "company_name": fields["company_name"] or "",
        "service_interest": fields["service_interest"] or None,
        "message": fields["message"] or "",
        "source": source_label or "Web Form",
        "status": "new",
        "notes": fields["message"] or "",
        "est_value": 0.0,
        "created_at": now_iso(),
    }


# Backwards-compat re-export — some callers still import
# ``_first_str`` / ``_lead_row_from_form_values`` (underscore
# prefix) via ``routers.marketing`` for legacy reasons.  Keep an
# alias so mass-renaming existing imports isn't required.
_first_str = first_str
_lead_row_from_form_values = lead_row_from_form_values
