"""Feb-2026 — Bulk hard-delete for uncategorized line items.

Pure planning + math + audit helpers.  The Mongo-touching orchestration
and hook fan-out (snapshot_before_mutation, invalidate_signature_if_present)
live in the router (``backend/routers/income_categories.py``); everything
here is Mongo-free so the code path is unit-testable without a live DB.

Public surface
--------------

* :class:`DeleteRequest`, :class:`DeleteSkip`, :class:`PlanResult`,
  :class:`ApplyResult` — plain dataclasses for the planning /
  application phases.

* :func:`plan_deletions` — takes the router-supplied payload plus the
  invoice docs the router already loaded, and returns a per-invoice
  execution plan (``deletes_by_invoice: Dict[invoice_id, List[Plan]]``)
  plus a ``skipped[]`` list.  Handles every skip code:

    - ``not_found_or_cross_tenant`` (invoice not in ``invoices_by_id``)
    - ``line_index_out_of_bounds``  (``line_item_index`` >=
      ``len(line_items)``)
    - ``content_shifted``           (description or unit_price on the
      current invoice line doesn't match the frontend-snapshotted
      values — G.1a concurrency guard)
    - ``locked_paid``               (invoice.payment_status == "paid"
      and ``acknowledged_lock_bypass`` is False)
    - ``already_deleted``           (same ``(invoice_id, line_index)``
      appears twice in the payload — first wins, second skipped)

* :func:`apply_deletions` — takes one invoice doc + a list of planned
  indices, deletes in descending index order (safe against intra-array
  index drift), returns ``(new_line_items, deleted_snapshots)``.

* :func:`recompute_totals` — thin wrapper around
  ``routers.quotes.compute_totals`` that also computes
  ``remaining_balance = max(total - amount_paid, 0)`` — clamped at 0
  so a paid invoice whose line is removed doesn't go negative.

* :func:`build_audit_row` — one ``audit_logs`` row per line deleted;
  event=``line_item.hard_delete``.  Mirrors the recategorize precedent
  at ``income_categories.py:866-877`` verbatim.

* :func:`build_undo_audit_row` — event=``line_item.hard_delete.undo``
  with ``undo_of: <bulk_op_id>``.

Locked semantics (§G rulings):

* G.1a — concurrency guard on ``(description, unit_price)``.
* G.2  — cap 100 rows / call (enforced in the router; this module
  does NOT enforce; ``plan_deletions`` is happy with any count).
* G.3b — per-invoice atomic with ``updated_at`` guard (router
  concern; this module is pure).
* G.4c — ``locked_paid`` skip unless ``acknowledged_lock_bypass``.
* G.5a — one audit row per line; shared ``bulk_op_id``.
* G.6a + G.6c — hard delete + companion undo endpoint replays.
* G.7  — 5 skip codes enumerated above.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ── Skip codes (G.7 taxonomy) ──────────────────────────────────
SKIP_NOT_FOUND = "not_found_or_cross_tenant"
SKIP_INDEX_OOB = "line_index_out_of_bounds"
SKIP_CONTENT_SHIFTED = "content_shifted"
SKIP_LOCKED_PAID = "locked_paid"
SKIP_ALREADY_DELETED = "already_deleted"


# ═════════════════════════════════════════════════════════════
# Dataclasses
# ═════════════════════════════════════════════════════════════
@dataclass
class DeleteRequest:
    """One row from the frontend payload.  Description + unit_price
    are the concurrency-guard snapshot values."""
    invoice_id: str
    line_item_index: int
    description: str
    unit_price: float


@dataclass
class DeleteSkip:
    """One row that could not be deleted; goes into the response's
    ``skipped[]`` array."""
    invoice_id: str
    line_item_index: int
    code: str


@dataclass
class LinePlan:
    """One planned deletion inside one invoice.  ``description``
    and ``unit_price`` are the guard values captured from the
    payload — we re-check them against the LIVE invoice doc during
    ``plan_deletions`` (not during ``apply_deletions``; the router
    holds the doc between plan + apply)."""
    line_item_index: int
    description: str
    unit_price: float


@dataclass
class PlanResult:
    """What :func:`plan_deletions` returns."""
    deletes_by_invoice: Dict[str, List[LinePlan]] = field(
        default_factory=dict,
    )
    skipped: List[DeleteSkip] = field(default_factory=list)


@dataclass
class ApplyResult:
    """What :func:`apply_deletions` returns."""
    new_line_items: List[Dict[str, Any]]
    deleted_snapshots: List[Dict[str, Any]]


# ═════════════════════════════════════════════════════════════
# Planning
# ═════════════════════════════════════════════════════════════
def plan_deletions(
    payload: List[DeleteRequest],
    *,
    invoices_by_id: Dict[str, Dict[str, Any]],
    acknowledged_lock_bypass: bool = False,
) -> PlanResult:
    """Compute the per-invoice deletion plan + build the ``skipped[]``
    list.  Pure function — no Mongo.

    ``invoices_by_id`` MUST already be tenant-scoped by the router
    (a missing key is treated as "cross-tenant or not-found" — same
    skip code, matches B2.B posture where we never distinguish
    between the two).

    Duplicate-in-payload handling (G.5a-companion): iterate in
    payload order; the FIRST occurrence of a given
    ``(invoice_id, line_item_index)`` gets planned, later
    duplicates go to ``skipped`` with code ``already_deleted``.

    ``acknowledged_lock_bypass`` is a global flag (per-payload, not
    per-row) — an admin either acknowledges the "some of these are
    paid invoices" warning for the whole batch or they don't.
    """
    result = PlanResult()
    # Track "planned" pairs so a duplicate payload row can be
    # marked ``already_deleted`` without touching the invoice.
    seen_pairs: set = set()

    for row in payload:
        pair = (row.invoice_id, row.line_item_index)
        if pair in seen_pairs:
            result.skipped.append(DeleteSkip(
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                code=SKIP_ALREADY_DELETED,
            ))
            continue

        inv = invoices_by_id.get(row.invoice_id)
        if inv is None:
            result.skipped.append(DeleteSkip(
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                code=SKIP_NOT_FOUND,
            ))
            continue

        # Locked-paid gate.
        payment_status = (inv.get("payment_status") or "").lower()
        if payment_status == "paid" and not acknowledged_lock_bypass:
            result.skipped.append(DeleteSkip(
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                code=SKIP_LOCKED_PAID,
            ))
            continue

        lines = inv.get("line_items") or []
        if row.line_item_index < 0 or row.line_item_index >= len(lines):
            result.skipped.append(DeleteSkip(
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                code=SKIP_INDEX_OOB,
            ))
            continue

        live_line = lines[row.line_item_index] or {}
        # G.1a — concurrency guard.
        live_desc = live_line.get("description") or ""
        live_up = _to_float(live_line.get("unit_price"))
        payload_desc = row.description or ""
        payload_up = _to_float(row.unit_price)
        if live_desc != payload_desc or not _floats_match(live_up, payload_up):
            result.skipped.append(DeleteSkip(
                invoice_id=row.invoice_id,
                line_item_index=row.line_item_index,
                code=SKIP_CONTENT_SHIFTED,
            ))
            continue

        # All guards passed — plan the delete.
        seen_pairs.add(pair)
        result.deletes_by_invoice.setdefault(row.invoice_id, []).append(
            LinePlan(
                line_item_index=row.line_item_index,
                description=payload_desc,
                unit_price=payload_up,
            )
        )

    return result


# ═════════════════════════════════════════════════════════════
# Application (memory-only mutation)
# ═════════════════════════════════════════════════════════════
def apply_deletions(
    invoice_doc: Dict[str, Any],
    planned: List[LinePlan],
) -> ApplyResult:
    """Apply the planned deletions to one invoice's ``line_items``
    array.  Returns the new array + the list of removed line
    snapshots (for audit).

    IMPORTANT: deletes in DESCENDING index order so intra-array
    index drift never breaks a multi-index deletion.  This matches
    the "safe deletion pattern" locked by the spec.
    """
    lines = list(invoice_doc.get("line_items") or [])
    # Sort planned indices descending; index dedupe was already done
    # in ``plan_deletions``.
    planned_sorted = sorted(planned, key=lambda p: p.line_item_index,
                             reverse=True)
    deleted_snapshots: List[Dict[str, Any]] = []
    for plan in planned_sorted:
        # Extra safety: bail if the index shifted out of bounds
        # somehow (should never happen since plan_deletions already
        # validated the bounds against the same doc the router
        # passes here).
        if plan.line_item_index < 0 or plan.line_item_index >= len(lines):
            continue
        snap = dict(lines[plan.line_item_index] or {})
        # Carry the original index inside the snapshot so undo can
        # log where the line lived pre-delete.
        snap["_pre_delete_index"] = plan.line_item_index
        deleted_snapshots.append(snap)
        del lines[plan.line_item_index]
    # Reverse the snapshots list so callers see them in
    # ascending-index order (matches the payload order, less
    # confusing for humans reading audit rows).
    deleted_snapshots.reverse()
    return ApplyResult(
        new_line_items=lines,
        deleted_snapshots=deleted_snapshots,
    )


# ═════════════════════════════════════════════════════════════
# Totals recompute
# ═════════════════════════════════════════════════════════════
def recompute_totals(
    invoice_doc: Dict[str, Any],
    new_line_items: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Recompute ``subtotal / tax / total / remaining_balance`` using
    the CANONICAL helper (``routers.quotes.compute_totals``) so we
    stay in lockstep with every other line-item write path in the
    codebase.

    ``remaining_balance`` clamps at 0 — the customer already paid;
    removing a line MAY overshoot the paid amount but we do NOT go
    negative (see G.4c ruling; frontend surfaces the warning
    pre-modal).
    """
    # Lazy import — avoids a circular import at module-load time.
    from routers.quotes import compute_totals

    tax_rate = _to_float(invoice_doc.get("tax_rate"))
    subtotal, tax, total = compute_totals(new_line_items, tax_rate)
    amount_paid = _to_float(invoice_doc.get("amount_paid"))
    remaining_balance = round(max(total - amount_paid, 0.0), 2)
    return {
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "remaining_balance": remaining_balance,
    }


# ═════════════════════════════════════════════════════════════
# Audit row builders (§G.5a)
# ═════════════════════════════════════════════════════════════
def build_audit_row(
    *,
    tenant_id: str,
    invoice_id: str,
    line_item_index: int,
    line_snapshot: Dict[str, Any],
    actor: Dict[str, Any],
    bulk_op_id: str,
    deletion_reason: Optional[str] = None,
    at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One ``audit_logs`` row per deleted line item.

    Row shape mirrors ``line_item.recategorize`` at
    ``income_categories.py:866-877`` verbatim + adds ``bulk_op_id``
    + ``line_snapshot`` + ``deletion_reason``:

    .. code-block:: python

        {
            "id": <uuid>,
            "tenant_id": <str>,
            "event": "line_item.hard_delete",
            "invoice_id": <str>,
            "line_item_index": <int>,
            "line_snapshot": <full-line-dict>,
            "actor_id": <str>,
            "actor_email": <str>,
            "actor_role": <str>,
            "bulk_op_id": <uuid>,
            "deletion_reason": <str|None>,
            "created_at": <iso>,
        }
    """
    if at is None:
        at = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "event": "line_item.hard_delete",
        "invoice_id": invoice_id,
        "line_item_index": line_item_index,
        "line_snapshot": _strip_pre_delete_index(line_snapshot),
        "actor_id": (actor or {}).get("id"),
        "actor_email": (actor or {}).get("email"),
        "actor_role": ((actor or {}).get("role") or "").lower(),
        "bulk_op_id": bulk_op_id,
        "deletion_reason": deletion_reason,
        "created_at": at.isoformat(),
    }


def build_undo_audit_row(
    *,
    tenant_id: str,
    invoice_id: str,
    line_snapshot: Dict[str, Any],
    reinserted_at_index: int,
    actor: Dict[str, Any],
    undo_of_bulk_op_id: str,
    at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Audit row for the undo path (§G.6c).

    Note: ``reinserted_at_index`` is the NEW position — undo appends
    to the END of the current ``line_items`` array (safe under
    concurrent edits per G.6c ruling), not the original index the
    line was at pre-delete.  The original index is carried inside
    the pre-delete audit row's ``line_item_index`` field for
    forensic reconstruction.
    """
    if at is None:
        at = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "event": "line_item.hard_delete.undo",
        "invoice_id": invoice_id,
        "line_item_index": reinserted_at_index,
        "line_snapshot": _strip_pre_delete_index(line_snapshot),
        "actor_id": (actor or {}).get("id"),
        "actor_email": (actor or {}).get("email"),
        "actor_role": ((actor or {}).get("role") or "").lower(),
        "undo_of": undo_of_bulk_op_id,
        "created_at": at.isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════
def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _floats_match(a: float, b: float, tol: float = 0.005) -> bool:
    """Guard against tiny FP drift on the concurrency-check."""
    return abs(a - b) <= tol


def _strip_pre_delete_index(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Remove the ``_pre_delete_index`` marker before writing the
    line snapshot to audit_logs.  The marker is internal to
    ``apply_deletions`` — it lets the undo endpoint carry the
    original index in the audit row's ``line_item_index`` field
    instead."""
    if not snap or "_pre_delete_index" not in snap:
        return snap
    out = dict(snap)
    out.pop("_pre_delete_index", None)
    return out
