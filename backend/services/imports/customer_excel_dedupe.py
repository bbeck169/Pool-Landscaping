"""TD-customer-ai-excel-csv-import · Feb-2026
=============================================

Duplicate detection shim for the Excel/CSV AI import flow.

Operator Q2 decision: ANY-match duplicate semantics — a mapped row
is classified as a duplicate when EITHER of (name via match
ladder, email exact, phone digit-exact) resolves to a live
non-merged customer in the tenant.

Signal precedence for the suggested-action heuristic (strongest
first — the FIRST signal that fires wins; others surface as
secondary candidates in the preview UI):

  1. ``exact_email``   — ``customers.email`` matches on
                         ``.lower().strip()`` equality.
  2. ``exact_phone``   — digit-normalized phone (US-biased: just
                         strip every non-digit; ``phone``-vs-
                         ``home_phone`` is treated interchangeably
                         on the file side).
  3. ``ladder_exact_name`` or ``ladder_fuzzy_name`` — delegates to
                         :func:`customer_match_ladder.run_match_ladder`
                         which already filters merged customers
                         + soft-deleted rows + applies the fuzzy
                         Levenshtein ceiling of 2.

Match pool filter mirrors ``customers_excel_import.commit`` so
the preview can trust that whatever customer_id it attaches to
on commit is still live + not merged.

The matcher does NOT run when the mapped row carries no name AND
no email AND no phone — those rows are classified ``no_signal``
by the caller (the preview UI will surface them with a mandatory
``create`` action and no attach option).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.imports.customer_match_ladder import run_match_ladder


logger = logging.getLogger("imports.customer_excel_dedupe")

_PHONE_DIGIT_RE = re.compile(r"\D+")


@dataclass
class DupeCandidate:
    customer_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    match_reason: str = ""      # exact_email / exact_phone / name_ladder


@dataclass
class DupeReport:
    match_status: str = "no_signal"
    #   no_signal | no_match | exact_email | exact_phone |
    #   ladder_exact_name | ladder_fuzzy_name | ambiguous
    candidates: List[DupeCandidate] = field(default_factory=list)
    suggested_action: str = "create"       # create | attach | skip


def _normalize_phone(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return _PHONE_DIGIT_RE.sub("", str(raw))


def _normalize_email(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return str(raw).strip().lower()


async def _probe_email(
    *, db, tenant_id: str, email_norm: str,
) -> Optional[Dict[str, Any]]:
    if not email_norm:
        return None
    # Case-insensitive exact match. ``customers.email`` is
    # historically stored lowercase per routers/customers.py, but
    # legacy rows may carry mixed-case so we probe both forms.
    row = await db.customers.find_one(
        {
            "tenant_id": tenant_id,
            "email": email_norm,
            "deleted_at": {"$in": [None, "", False]},
            "$or": [
                {"merged_into": None},
                {"merged_into": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    )
    if row:
        return row
    # Fallback — regex equality for legacy mixed-case rows.
    escaped = re.escape(email_norm)
    return await db.customers.find_one(
        {
            "tenant_id": tenant_id,
            "email": {"$regex": f"^{escaped}$", "$options": "i"},
            "deleted_at": {"$in": [None, "", False]},
            "$or": [
                {"merged_into": None},
                {"merged_into": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
    )


async def _probe_phone(
    *, db, tenant_id: str, phone_digits: str,
) -> Optional[Dict[str, Any]]:
    if not phone_digits:
        return None
    # Match on any customer whose primary phone / home_phone has
    # the same digit sequence.  We can't index-match on a
    # digit-stripped form server-side; projection-fetch the small
    # pool of candidates matching a loose regex and digit-compare
    # in Python.  Pool is bounded by the tenant's customer count.
    tail = phone_digits[-10:] if len(phone_digits) >= 7 else phone_digits
    pattern = ".*".join(re.escape(c) for c in tail)
    cursor = db.customers.find(
        {
            "tenant_id": tenant_id,
            "deleted_at": {"$in": [None, "", False]},
            "$or": [
                {"phone": {"$regex": pattern}},
                {"home_phone": {"$regex": pattern}},
            ],
            "$and": [
                {"$or": [
                    {"merged_into": None},
                    {"merged_into": {"$exists": False}},
                ]},
            ],
        },
        {"_id": 0, "id": 1, "name": 1, "email": 1,
         "phone": 1, "home_phone": 1},
    )
    async for row in cursor:
        for field_name in ("phone", "home_phone"):
            v = row.get(field_name) or ""
            cand_digits = _normalize_phone(v)
            if not cand_digits:
                continue
            # Tail-match on 10 digits (US-biased) so a stored
            # ``+1 (555) 123-4567`` (11 digits) matches an imported
            # ``5551234567`` (10 digits).  Full-equality fallback
            # for international numbers.
            if cand_digits == phone_digits:
                return row
            if (len(cand_digits) >= 10
                    and len(phone_digits) >= 10
                    and cand_digits[-10:] == phone_digits[-10:]):
                return row
    return None


async def detect_duplicate(
    *,
    db,
    tenant_id: str,
    mapped_fields: Dict[str, Any],
) -> DupeReport:
    """Run the three-signal probe and return a ``DupeReport``.

    Operator Q2: ANY-match wins — the first signal that fires
    becomes ``match_status``, every other matched customer surfaces
    as a secondary candidate for the operator to override via the
    preview dropdown.
    """
    report = DupeReport()

    email_norm = _normalize_email(mapped_fields.get("email"))
    phone_digits = _normalize_phone(
        mapped_fields.get("phone") or mapped_fields.get("home_phone")
    )
    name_hint = (mapped_fields.get("name") or "").strip()

    if not email_norm and not phone_digits and not name_hint:
        report.match_status = "no_signal"
        report.suggested_action = "create"
        return report

    picked: Optional[Dict[str, Any]] = None
    secondary: List[DupeCandidate] = []

    # 1 — email
    email_hit = await _probe_email(
        db=db, tenant_id=tenant_id, email_norm=email_norm,
    )
    if email_hit:
        picked = email_hit
        report.match_status = "exact_email"

    # 2 — phone (only if email didn't fire)
    phone_hit = await _probe_phone(
        db=db, tenant_id=tenant_id, phone_digits=phone_digits,
    )
    if phone_hit:
        if picked is None:
            picked = phone_hit
            report.match_status = "exact_phone"
        elif phone_hit.get("id") != picked.get("id"):
            secondary.append(DupeCandidate(
                customer_id=phone_hit["id"],
                name=phone_hit.get("name") or "",
                email=phone_hit.get("email"),
                phone=phone_hit.get("phone"),
                match_reason="exact_phone",
            ))

    # 3 — name ladder
    if name_hint:
        ladder = await run_match_ladder(
            db=db, tenant_id=tenant_id,
            extracted_name=name_hint,
            extracted_phone=mapped_fields.get("phone"),
        )
        ladder_hit = None
        ladder_status = None
        if ladder.match_status in ("active", "inactive", "muted"):
            ladder_hit = {
                "id": ladder.matched_customer_id,
                "name": ladder.matched_customer_name,
            }
            ladder_status = "ladder_exact_name"
        elif ladder.match_status == "fuzzy_match":
            ladder_hit = {
                "id": ladder.matched_customer_id,
                "name": ladder.matched_customer_name,
            }
            ladder_status = "ladder_fuzzy_name"
        if ladder_hit and ladder_hit.get("id"):
            if picked is None:
                # Projection-light hit — hydrate email+phone so the
                # preview UI's candidate card can render all three
                # signals.
                hydrated = await db.customers.find_one(
                    {"id": ladder_hit["id"], "tenant_id": tenant_id},
                    {"_id": 0, "id": 1, "name": 1,
                     "email": 1, "phone": 1},
                )
                if hydrated:
                    picked = hydrated
                    report.match_status = (
                        ladder_status or "ladder_exact_name"
                    )
            elif ladder_hit["id"] != picked.get("id"):
                hydrated = await db.customers.find_one(
                    {"id": ladder_hit["id"], "tenant_id": tenant_id},
                    {"_id": 0, "id": 1, "name": 1,
                     "email": 1, "phone": 1},
                )
                if hydrated:
                    secondary.append(DupeCandidate(
                        customer_id=hydrated["id"],
                        name=hydrated.get("name") or "",
                        email=hydrated.get("email"),
                        phone=hydrated.get("phone"),
                        match_reason=(
                            ladder_status or "ladder_exact_name"
                        ),
                    ))

    if picked is None:
        report.match_status = "no_match"
        report.suggested_action = "create"
        return report

    report.candidates.append(DupeCandidate(
        customer_id=picked["id"],
        name=picked.get("name") or "",
        email=picked.get("email"),
        phone=picked.get("phone"),
        match_reason=report.match_status,
    ))
    report.candidates.extend(secondary)
    report.suggested_action = "attach"
    return report


__all__ = [
    "DupeCandidate", "DupeReport",
    "detect_duplicate",
    "_normalize_email", "_normalize_phone",
]
