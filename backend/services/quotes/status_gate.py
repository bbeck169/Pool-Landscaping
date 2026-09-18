"""Phase K80.b · Feb-2026 — Status-based mutation gate for
``PUT /api/quotes/{id}``.

Purpose:
    Close the security gap surfaced by K80 recon. Before K80.b the
    PUT endpoint accepted a full ``line_items[]`` replace on any
    quote/invoice regardless of status — a curl could rewrite a
    ``paid`` invoice's charges. This gate is enforced server-side
    ONLY on ``PUT``. ``PATCH /api/quotes/{id}`` keeps its existing,
    more permissive triad (terminal/sent-confirm/paid-typed-number)
    which is intentionally separate policy — reviewers should not
    "align" the two without an explicit product decision.

Policy (locked by product on this session):

    +-----------+-----------------+------------+
    |  doc_type |     status      | PUT allow? |
    +-----------+-----------------+------------+
    | estimate  | draft           |    YES     |
    | estimate  | sent            |    YES     |
    | estimate  | accepted        |    NO      |
    | estimate  | declined        |    NO      |
    | estimate  | voided (void)   |    NO      |
    | invoice   | draft           |    YES     |
    | invoice   | sent            |    NO      |  ← delta vs PATCH
    | invoice   | partially_paid  |    NO      |
    | invoice   | paid            |    NO      |
    | invoice   | voided          |    NO      |
    +-----------+-----------------+------------+

Denials raise ``HTTPException(409)`` with the structured body
``{ error, current_status, doc_type, message }``. ``doc_type``
uses the customer-friendly label ``estimate|invoice`` (the DB
field ``doc_type`` uses ``quote|invoice`` — this helper translates
so external API clients see a stable vocabulary).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException


# Allowed statuses per external doc_type. Any status not in this set
# is denied. We whitelist rather than blacklist so that unexpected
# statuses (data-migration artefacts, future workflow additions) fail
# closed by default.
_ALLOWED: Dict[str, set[str]] = {
    "estimate": {"draft", "sent"},
    "invoice": {"draft"},
}

# Feb-2026 · Editable Sent Docs · Phase 1 — statuses that unlock
# with an explicit ``acknowledged_lock_bypass=True`` body flag from
# the frontend confirm-dialog. Anything NOT in this set stays hard-
# locked regardless of the flag (``void`` / ``cancelled``).
#
# Feb 2026 · Follow-up — admin/super_admin operators need to correct
# invoices that have aged into ``past_due`` / ``unpaid`` / ``overdue``
# state (data entry errors, disputed line items) without a
# void-and-re-issue dance. Added the three lifecycle statuses to the
# invoice ack-bypass list. The estimate list is intentionally NOT
# widened here — those statuses don't apply to quotes.
_ALLOWED_WITH_ACK: Dict[str, set[str]] = {
    "estimate": {"accepted", "declined"},
    "invoice": {"sent", "accepted", "paid", "partial",
                 "past_due", "unpaid", "overdue"},
}


def _external_doc_type(quote: Dict[str, Any]) -> str:
    """Map DB ``doc_type`` (quote/invoice) → external label
    (estimate/invoice). Falls back to ``estimate`` when missing
    (the K48 pre-doc_type era stored plain quotes without the
    field)."""
    raw = (quote.get("doc_type") or "").lower()
    if raw == "invoice":
        return "invoice"
    # "quote" and everything else → estimate.
    return "estimate"


def _current_status(quote: Dict[str, Any]) -> str:
    """Normalise the quote status for the gate. Falls back to
    ``draft`` when the field is absent."""
    return (quote.get("status") or "draft").lower()


def is_quote_mutable_for_put(
    quote: Dict[str, Any], *, bypass_lock: bool = False,
) -> bool:
    """Pure predicate — returns whether a ``PUT`` may proceed.

    Feb-2026 · Editable Sent Docs · Phase 1 — with
    ``bypass_lock=True`` (frontend confirm-dialog ack), the caller
    additionally unlocks statuses in :data:`_ALLOWED_WITH_ACK`.
    Statuses NOT in either set stay locked (``void`` / ``cancelled``).
    """
    doc_type = _external_doc_type(quote)
    status = _current_status(quote)
    if status in _ALLOWED.get(doc_type, set()):
        return True
    if bypass_lock and status in _ALLOWED_WITH_ACK.get(doc_type, set()):
        return True
    return False


def denial_payload(quote: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ``409`` response body for a denied PUT."""
    doc_type = _external_doc_type(quote)
    status = _current_status(quote)
    if doc_type == "invoice":
        msg = (
            f"This invoice is locked because its status is "
            f"'{status}'. Only draft invoices accept full edits via "
            f"PUT. Void the invoice and issue a new one, or use the "
            f"invoice edit modal for a scoped change."
        )
    else:
        msg = (
            f"This estimate is locked because its status is "
            f"'{status}'. Only draft and sent estimates accept full "
            f"edits via PUT. Duplicate the estimate to make changes."
        )
    return {
        "error": "status_locked",
        "current_status": status,
        "doc_type": doc_type,
        "message": msg,
    }


def assert_quote_mutable_for_put(
    quote: Dict[str, Any], *, bypass_lock: bool = False,
) -> None:
    """Raise ``HTTPException(409)`` if the quote's status forbids PUT.

    Callers should invoke this immediately after loading the doc,
    BEFORE reading ``body`` for mutations, so we don't waste a
    validation pass on rejected writes.

    Feb-2026 · Editable Sent Docs · Phase 1 — pass ``bypass_lock=True``
    when the caller has an explicit
    ``acknowledged_lock_bypass: true`` in the request body from the
    frontend confirm-dialog. This unlocks ``sent``/``accepted``/
    ``paid``/``partial``/``declined`` per :data:`_ALLOWED_WITH_ACK`.
    """
    if is_quote_mutable_for_put(quote, bypass_lock=bypass_lock):
        return
    raise HTTPException(status_code=409, detail=denial_payload(quote))


async def audit_put_denial(
    db,
    *,
    quote: Dict[str, Any],
    actor: Dict[str, Any],
) -> None:
    """Persist a single audit row for every denied PUT.

    Best-effort: audit-log write failures MUST NOT convert a 409 into
    a 500. Callers wrap the coroutine in ``try/except`` (or, for
    routers that already do, call it before raising the 409).
    """
    try:
        await db.audit_logs.insert_one({
            "event": "put_quote_status_denied",
            "at": datetime.now(timezone.utc).isoformat(),
            "user_id": (actor or {}).get("id"),
            "user_email": (actor or {}).get("email"),
            "tenant_id": quote.get("tenant_id"),
            "quote_id": quote.get("id"),
            "doc_type": _external_doc_type(quote),
            "current_status": _current_status(quote),
        })
    except Exception:
        # Never fail the caller because of an audit-log write.
        pass


__all__ = [
    "assert_quote_mutable_for_put",
    "audit_put_denial",
    "denial_payload",
    "is_quote_mutable_for_put",
]
