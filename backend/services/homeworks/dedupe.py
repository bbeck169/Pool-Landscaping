"""Phase 55-b · Aug-2026 — Customer dedupe engine.

Given a mapped customer payload, return a tuple of
``(dedupe_status, matched_target_id)``. Rules are spec-locked:

  * ``new``       — neither email nor phone match any existing tenant customer.
  * ``matched``   — email OR phone match a SINGLE existing customer
                    (email and phone must agree if both matched).
  * ``conflict``  — email and phone match DIFFERENT existing customers,
                    or a single field matches multiple customers.

Normalization:
  * Email — lowercased + stripped. Matched via case-insensitive regex
    so any historical mixed-case emails still dedupe.
  * Phone — every non-digit stripped. Compared against BOTH the
    ``phone`` and ``home_phone`` fields on target customers.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Set, Tuple


def normalize_email(v: Any) -> str:
    return (str(v) if v is not None else "").strip().lower()


def normalize_phone(v: Any) -> str:
    digits = re.sub(r"\D", "", str(v) if v is not None else "")
    # US country code normalization — strip a leading ``1`` when the
    # result would be an 11-digit NANP number. Handles the common
    # case where one system stores ``+1 (555) 123-4567`` and another
    # stores ``555.123.4567``.
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


async def dedupe_customer(
    tenant_id: str, mapped: dict, db_ref: Any,
) -> Tuple[str, Optional[str]]:
    """Return ``(dedupe_status, matched_target_id)``.

    ``db_ref`` is the Motor db handle (or a fake); the function scopes
    every query by ``tenant_id`` so cross-tenant matches can never
    happen even by accident.
    """
    email = normalize_email(mapped.get("email"))
    phone = normalize_phone(mapped.get("phone"))

    email_ids: Set[str] = set()
    phone_ids: Set[str] = set()

    if email:
        # Case-insensitive exact match — anchored regex.
        cursor = db_ref.customers.find(
            {"tenant_id": tenant_id,
              "email": {"$regex": f"^{re.escape(email)}$",
                         "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        async for c in cursor:
            if c.get("id"):
                email_ids.add(c["id"])

    if phone:
        # Full scan with in-Python normalization — acceptable at one-
        # shot migration scale. Could be replaced with a stored
        # ``phone_e164`` field + index if the tenant has ≥100k
        # customers, but Homeworks target tenants are small-business.
        cursor = db_ref.customers.find(
            {"tenant_id": tenant_id},
            {"_id": 0, "id": 1, "phone": 1, "home_phone": 1},
        )
        async for c in cursor:
            for cand in (c.get("phone"), c.get("home_phone")):
                if normalize_phone(cand) == phone:
                    if c.get("id"):
                        phone_ids.add(c["id"])
                    break

    all_ids = email_ids | phone_ids
    if not all_ids:
        return "new", None

    # Both signals present → require agreement.
    if email_ids and phone_ids and email_ids != phone_ids:
        overlap = email_ids & phone_ids
        if len(overlap) == 1:
            return "matched", next(iter(overlap))
        return "conflict", None

    if len(all_ids) == 1:
        return "matched", next(iter(all_ids))

    # Single-key match to multiple customers → conflict too.
    return "conflict", None
