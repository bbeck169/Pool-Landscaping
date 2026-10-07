"""Phase K80.b (relaxed Feb-2026) · DOC-LOCK-POLICY-RELAX —
Status-based mutation gate for ``PUT /api/quotes/{id}``.

History
    * K80.b (initial): denied PUT on every non-``draft`` invoice
      and every non-``{draft,sent}`` estimate.
    * Editable-Sent-Docs Phase 1: added ``acknowledged_lock_bypass``
      ack path to unlock ``sent``/``accepted``/``paid``/``partial``/
      ``declined`` + the aged lifecycle statuses with an explicit
      operator confirmation.
    * Invoice-God-Mode: added super_admin silent bypass on the
      aged lifecycle statuses so the escalation role skips the ack
      popup entirely.
    * DOC-LOCK-POLICY-RELAX (Feb-2026, this ticket): product
      direction flipped. Estimates are now ALWAYS editable
      regardless of status. Invoices are editable UNLESS the
      status locks them per :data:`_HARD_LOCKED`. Only ``paid``,
      ``void``, and ``cancelled`` invoices stay read-only on PUT.
      Ack-bypass + super_admin-silent-bypass remain in-code but
      no longer have anything to unlock (they're dead code kept
      for API-surface stability; the exports below still resolve).

Policy (DOC-LOCK-POLICY-RELAX):

    +-----------+-----------------+------------+
    |  doc_type |     status      | PUT allow? |
    +-----------+-----------------+------------+
    | estimate  | any status      |    YES     |
    | invoice   | not in locked   |    YES     |
    | invoice   | paid            |    NO      |
    | invoice   | void            |    NO      |
    | invoice   | cancelled       |    NO      |
    +-----------+-----------------+------------+

Audit:
    Denials still write ``put_quote_status_denied`` (unchanged).
    Successful PUTs on any post-send status now write a NEW event
    ``put_quote_edit_after_send`` to a dedicated
    ``doc_edit_audit`` collection — see :func:`audit_put_success`.
    This gives ops a durable trail of mutations against docs that
    had already been exposed to the customer (via send or portal
    view), capturing editor identity + edited field names +
    monetary deltas. Required by DOC-LOCK-POLICY-RELAX risk C.

Denials raise ``HTTPException(409)`` with the structured body
``{ error, current_status, doc_type, message }``. ``doc_type``
uses the customer-friendly label ``estimate|invoice`` (the DB
field ``doc_type`` uses ``quote|invoice`` — this helper translates
so external API clients see a stable vocabulary).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException


# DOC-LOCK-POLICY-RELAX · Feb-2026 — hard-lock set per external
# doc_type. A status that lands in this set rejects PUT with a 409
# ``status_locked`` body. Everything else is editable.
#
# Estimates: empty — always editable per product direction.
# Invoices: ``paid`` (the ONLY accepted "read-only" state per gate
#           3a of this ticket) + ``void`` / ``cancelled`` (terminal
#           states, not legitimate edit targets even with ack).
_HARD_LOCKED: Dict[str, set[str]] = {
    "estimate": set(),
    "invoice": {"paid", "void", "cancelled"},
}


# Pre-DOC-LOCK-POLICY-RELAX structures. KEPT for backwards-compat so
# any external importer resolves without a NameError, but the gate
# no longer consults these — ``_HARD_LOCKED`` is the single source
# of truth. New policy work SHOULD edit ``_HARD_LOCKED``.
_ALLOWED: Dict[str, set[str]] = {
    "estimate": {"draft", "sent", "viewed", "accepted", "declined"},
    "invoice": {"draft", "sent", "viewed", "accepted", "declined",
                 "partial", "partially_paid",
                 "past_due", "unpaid", "overdue"},
}
_ALLOWED_WITH_ACK: Dict[str, set[str]] = {
    "estimate": set(),
    "invoice": set(),
}
_SUPER_ADMIN_SILENT_BYPASS: set[str] = set()


# DOC-LOCK-POLICY-RELAX · Feb-2026 — statuses considered "already
# exposed to the customer" at the time of edit. A successful PUT or
# PATCH on a doc in any of these statuses writes a
# ``put_quote_edit_after_send`` row to the ``doc_edit_audit``
# collection so the mutation is traceable for a future dispute.
_POST_SEND_STATUSES: set[str] = {
    "sent", "viewed", "accepted", "declined",
    "paid", "partial", "partially_paid",
    "past_due", "unpaid", "overdue",
}


# Monetary field names whose before/after values are captured on
# every ``audit_put_success`` row. Kept short + scalar — ``line_items``
# is captured by LENGTH only (per-line diffs blow up the audit row
# and the version-history snapshot in ``services/documents`` already
# captures the rich per-line change_summary).
_MONETARY_SCALAR_FIELDS: tuple = (
    "subtotal", "tax", "total", "amount_due", "amount_paid",
    "balance", "balance_due",
)


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


def should_super_admin_silent_bypass(
    quote: Dict[str, Any], role: Optional[str],
) -> bool:
    """DOC-LOCK-POLICY-RELAX · Feb-2026 — DEAD CODE kept for API
    stability.

    Before this ticket, super_admins silently bypassed the ack popup
    on aged-invoice statuses. The relaxed policy makes those
    statuses editable without any ack, so the function has nothing
    to unlock and always returns ``False``. Kept so external callers
    (``routers/quotes.py``) that still import + call it keep working
    without a NameError. New code should ignore this helper.
    """
    return False


def is_quote_mutable_for_put(
    quote: Dict[str, Any],
    *,
    bypass_lock: bool = False,
    role: Optional[str] = None,
) -> bool:
    """Pure predicate — returns whether a ``PUT`` may proceed.

    DOC-LOCK-POLICY-RELAX · Feb-2026 — radically simplified. The
    gate consults a single hard-lock set (:data:`_HARD_LOCKED`).
    ``bypass_lock`` and ``role`` are accepted for signature stability
    but no longer influence the decision — the relaxed policy is
    strictly status-based: estimates always pass, invoices pass
    unless the status is ``paid`` / ``void`` / ``cancelled``.
    """
    doc_type = _external_doc_type(quote)
    status = _current_status(quote)
    return status not in _HARD_LOCKED.get(doc_type, set())


def denial_payload(quote: Dict[str, Any]) -> Dict[str, Any]:
    """Build the ``409`` response body for a denied PUT.

    DOC-LOCK-POLICY-RELAX · Feb-2026 — denials now only fire on
    invoices in ``paid`` / ``void`` / ``cancelled``. The message
    text is tailored to the real reason (paid vs terminal) so the
    client toast is unambiguous. Estimates can never reach this
    path under the relaxed policy — the branch is retained as a
    defensive catch for data-migration oddities.
    """
    doc_type = _external_doc_type(quote)
    status = _current_status(quote)
    if doc_type == "invoice":
        if status in ("void", "cancelled"):
            msg = (
                f"This invoice is {status} and cannot be edited. "
                f"Issue a new invoice if the customer owes money."
            )
        else:  # paid
            msg = (
                "This invoice is paid and cannot be edited. "
                "Open the invoice edit modal to make a scoped "
                "change with the invoice-number confirmation, "
                "or void and reissue if a full rewrite is needed."
            )
    else:
        # Should be unreachable under the relaxed policy — estimates
        # are never hard-locked. Keep a safe generic message.
        msg = (
            f"This estimate is currently locked (status "
            f"'{status}'). Duplicate the estimate to make changes."
        )
    return {
        "error": "status_locked",
        "current_status": status,
        "doc_type": doc_type,
        "message": msg,
    }


def assert_quote_mutable_for_put(
    quote: Dict[str, Any],
    *,
    bypass_lock: bool = False,
    role: Optional[str] = None,
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

    Feb-2026 · Invoice God Mode — pass ``role`` so super_admins skip
    the lock entirely on ``past_due`` / ``unpaid`` / ``overdue``
    invoices (see :func:`should_super_admin_silent_bypass`).
    """
    if is_quote_mutable_for_put(quote, bypass_lock=bypass_lock, role=role):
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


async def audit_super_admin_silent_bypass(
    db,
    *,
    quote: Dict[str, Any],
    actor: Dict[str, Any],
    new_fields: Optional[Dict[str, Any]] = None,
) -> None:
    """Feb-2026 · Invoice God Mode — audit line for silent bypasses.

    Written whenever :func:`should_super_admin_silent_bypass` fires
    on a successful PUT. Distinct event name (``put_quote_status_
    super_admin_silent_bypass``) so ops dashboards can separate the
    silent path from the standard ack path — silent bypasses are
    rare and high-privilege, they warrant their own filter.

    ``new_fields`` receives the sanitised ``upd`` dict (post-strip of
    request-only flags like ``acknowledged_lock_bypass`` and
    ``edit_reason``) so the audit row captures exactly what the
    invoice mutated to. Best-effort: audit-log write failures MUST
    NOT convert a 200 into a 500.

    DOC-LOCK-POLICY-RELAX · Feb-2026 — kept for API-surface
    stability; :func:`should_super_admin_silent_bypass` now always
    returns ``False`` so this function is dead code. The row would
    still write if the caller somehow invoked it directly.
    """
    try:
        await db.audit_logs.insert_one({
            "event": "put_quote_status_super_admin_silent_bypass",
            "at": datetime.now(timezone.utc).isoformat(),
            "user_id": (actor or {}).get("id"),
            "user_email": (actor or {}).get("email"),
            "user_role": (actor or {}).get("role"),
            "tenant_id": quote.get("tenant_id"),
            "quote_id": quote.get("id"),
            "doc_type": _external_doc_type(quote),
            "old_status": _current_status(quote),
            "new_fields": dict(new_fields or {}),
        })
    except Exception:
        # Never fail the caller because of an audit-log write.
        pass


# ═════════════════════════════════════════════════════════════════
# DOC-LOCK-POLICY-RELAX · Feb-2026 — Successful-edit audit
# ═════════════════════════════════════════════════════════════════
def _diff_top_level_keys(
    before: Dict[str, Any], after: Dict[str, Any],
) -> List[str]:
    """Top-level keys where ``before[k] != after[k]`` (or key only
    present in one of the two). Ordering is deterministic (sorted)
    so audit rows are stable across runs. Internal mongo artefacts
    (``_id``) are filtered out so the row stays schema-stable."""
    out: set = set()
    for k in before.keys():
        if k.startswith("_"):
            continue
        if before.get(k) != after.get(k):
            out.add(k)
    for k in after.keys():
        if k.startswith("_"):
            continue
        if k not in before and after.get(k) is not None:
            out.add(k)
    return sorted(out)


def _monetary_delta(
    before: Dict[str, Any], after: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Capture the before/after values on every monetary scalar in
    :data:`_MONETARY_SCALAR_FIELDS` plus ``line_items`` LENGTH only.

    Full line_items diffs are already captured by
    ``services/documents.snapshot_before_mutation`` (which writes
    the richer ``change_summary`` to the versions collection); the
    audit row keeps a light-weight scalar footprint so it fits a
    standard log line + is cheap to query for "did this doc change
    monetarily after send?" questions.
    """
    delta: Dict[str, Dict[str, Any]] = {}
    for f in _MONETARY_SCALAR_FIELDS:
        b, a = before.get(f), after.get(f)
        if b != a:
            delta[f] = {"before": b, "after": a}
    b_lines = before.get("line_items") or []
    a_lines = after.get("line_items") or []
    if len(b_lines) != len(a_lines):
        delta["line_items.length"] = {
            "before": len(b_lines),
            "after": len(a_lines),
        }
    return delta


async def audit_put_success(
    db,
    *,
    before: Dict[str, Any],
    after: Dict[str, Any],
    actor: Dict[str, Any],
    source: str = "put_quote",
) -> None:
    """DOC-LOCK-POLICY-RELAX · Feb-2026 — write an audit row on every
    successful PUT/PATCH against a post-send doc.

    Fires ONLY when the doc's PRE-mutation status is in
    :data:`_POST_SEND_STATUSES`. Draft-only edits are high-volume
    and have no legal/dispute surface — they'd flood the audit
    collection and dilute the signal operators actually care about.

    Row shape (``doc_edit_audit`` collection)::

        {
          event: "put_quote_edit_after_send",
          at: ISO-8601 UTC string,
          tenant_id, doc_id, doc_type (estimate|invoice),
          status_at_edit,
          editor_user_id, editor_email, editor_role,
          edited_fields: [<top-level keys that changed>],
          monetary_delta: {
              <field>: { before, after },
              ...,
              [line_items.length]: { before, after },
          },
          source: "put_quote" | "patch_invoice",
        }

    Indexable by ``doc_id`` for a per-doc history page and sortable
    by ``at`` for a chronological view. Best-effort: audit write
    failures MUST NOT convert a 200 into a 500.
    """
    try:
        status = _current_status(before)
        if status not in _POST_SEND_STATUSES:
            return
        edited_fields = _diff_top_level_keys(before, after)
        monetary = _monetary_delta(before, after)
        await db.doc_edit_audit.insert_one({
            "event": "put_quote_edit_after_send",
            "at": datetime.now(timezone.utc).isoformat(),
            "tenant_id": before.get("tenant_id"),
            "doc_id": before.get("id"),
            "doc_type": _external_doc_type(before),
            "status_at_edit": status,
            "editor_user_id": (actor or {}).get("id"),
            "editor_email": (actor or {}).get("email"),
            "editor_role": (actor or {}).get("role"),
            "edited_fields": edited_fields,
            "monetary_delta": monetary,
            "source": source,
        })
    except Exception:
        # Never fail the caller because of an audit-log write.
        pass


__all__ = [
    "assert_quote_mutable_for_put",
    "audit_put_denial",
    "audit_put_success",
    "audit_super_admin_silent_bypass",
    "denial_payload",
    "is_quote_mutable_for_put",
    "should_super_admin_silent_bypass",
]
