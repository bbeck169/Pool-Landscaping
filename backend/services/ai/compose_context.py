"""TD-ai-phase1 · Oct-2026 — context assembler for ``POST /api/ai/draft-reply``.

Positive allowlist (NOT a negative blocklist) of recipient-context
fields that are permitted to leave the server when composing a draft:

  * ``first_name``             (last_name intentionally excluded)
  * ``service_type``           (e.g. "weekly maintenance" / "pump repair")
  * ``upcoming_visit_date_iso`` (ISO date only — no address, no job id)
  * ``redacted_prior_message`` (operator-supplied; run through
                                ``services.ai.pii_redactor.redact_pii``)

Every other field on the resolved customer / lead document is DROPPED
before the context dict is handed to the prompt builder. New context
fields require a new entry in :data:`ALLOWED_CONTEXT_FIELDS` + a
passing pytest coverage lock.

The caller (router) does the Mongo resolution; this module does the
scoping + the shape lock + the final redaction pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Positive allowlist. Any field present in the resolved recipient doc
# that is NOT in this set is DROPPED when assembling the context sent
# to the LLM. Enforced by :func:`assemble_context`.
ALLOWED_CONTEXT_FIELDS = frozenset({
    "first_name",
    "service_type",
    "upcoming_visit_date_iso",
    "redacted_prior_message",
})

# Fields that routinely appear on a customer/lead doc + MUST never
# leave the server. Not enforced here (the allowlist already drops
# them) — codified only to document the privacy guarantee.
DISALLOWED_PII_FIELDS = frozenset({
    "last_name", "name", "address", "address_line1", "address_line2",
    "city", "state", "zip", "zip_code", "postal_code",
    "phone", "phone_e164", "phones", "email", "emails",
    "ssn", "social_security_number", "tax_id",
    "card_last4", "payment_token", "stripe_customer_id",
    "invoice_amount", "balance_due", "total_cents", "total",
    "portal_token", "magic_link", "reset_token",
    "lat", "lon", "longitude", "latitude",
    "notes", "private_notes",  # may contain PII
})


def _redact(text: Optional[str]) -> Optional[str]:
    """Lazy import to avoid loading the regex module when the caller
    passes an empty prior_message."""
    if not text or not text.strip():
        return None
    from services.ai.pii_redactor import redact_pii
    return redact_pii(text)


async def resolve_recipient(
    *, db, tenant_id: str, recipient_type: str, recipient_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch the recipient doc from Mongo and return the raw doc. Tenant
    scoping is enforced here — a doc from a different tenant returns
    None so the router can 404. Returns None when not found."""
    if recipient_type == "customer":
        return await db.customers.find_one(
            {"id": recipient_id, "tenant_id": tenant_id}, {"_id": 0},
        )
    if recipient_type == "lead":
        return await db.leads.find_one(
            {"id": recipient_id, "tenant_id": tenant_id}, {"_id": 0},
        )
    return None


async def _resolve_upcoming_visit(
    *, db, tenant_id: str, customer_id: Optional[str],
) -> Optional[str]:
    """Return the ISO date (YYYY-MM-DD) of the next scheduled job for
    this customer, or None. Only pulls ``scheduled_date`` — no address,
    no technician id, no job id leaves the function."""
    if not customer_id:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        row = await db.jobs.find_one(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "scheduled_date": {"$gte": today},
                "deleted_at": {"$in": [None, ""]},
            },
            {"_id": 0, "scheduled_date": 1},
            sort=[("scheduled_date", 1)],
        )
    except Exception:
        return None
    if not row:
        return None
    val = row.get("scheduled_date")
    return str(val) if val else None


def _service_type_from_doc(doc: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction. Customers often have ``service_type``
    directly; leads carry ``interest`` or ``service_interest`` instead.
    None when no sensible field is present."""
    for k in ("service_type", "service_interest", "interest",
                "primary_service", "service"):
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:120]
    return None


async def assemble_context(
    *, db, tenant_id: str, recipient_type: str, recipient_id: str,
    prior_message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the allowlisted context dict ready to feed the prompt
    builder. Returns None when the recipient does not resolve under
    the active tenant.

    Output shape is strictly::

        {
          "first_name":              Optional[str],
          "service_type":            Optional[str],
          "upcoming_visit_date_iso": Optional[str],
          "redacted_prior_message":  Optional[str],
        }

    Every key in the output is in :data:`ALLOWED_CONTEXT_FIELDS`;
    nothing else is attached.
    """
    doc = await resolve_recipient(
        db=db, tenant_id=tenant_id,
        recipient_type=recipient_type, recipient_id=recipient_id,
    )
    if not doc:
        return None
    first_name_raw = (
        doc.get("first_name")
        or (doc.get("name") or "").split(" ")[0]
        or None
    )
    first_name = (first_name_raw or "").strip() or None
    customer_id_for_visit = (
        recipient_id if recipient_type == "customer" else None
    )
    upcoming = await _resolve_upcoming_visit(
        db=db, tenant_id=tenant_id, customer_id=customer_id_for_visit,
    )
    assembled = {
        "first_name":              first_name,
        "service_type":            _service_type_from_doc(doc),
        "upcoming_visit_date_iso": upcoming,
        "redacted_prior_message":  _redact(prior_message),
    }
    # Hard-enforce the positive allowlist. Any key not in the set is
    # dropped — defensive, in case a future contributor adds a field
    # to this dict literal without updating ALLOWED_CONTEXT_FIELDS.
    return {k: v for k, v in assembled.items()
                if k in ALLOWED_CONTEXT_FIELDS}
