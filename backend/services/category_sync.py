"""P55 · Category sync orchestrator (Feb-2026).

Central choke-point for cross-record propagation of the
income + service category taxonomy fields. Two entry points:

  1. ``sync_recurring_template_to_children(...)`` — fans out a
     Recurring Template's category change to all *linked unpaid*
     Invoices (grandchildren via jobs). Jobs are DELIBERATELY
     NOT updated — see the P55 Q1/Option B design decision in
     ``memory/PRD.md``: jobs don't carry category fields today,
     so introducing them here would be write-only dead code.

  2. ``sync_invoice_line_to_pricebook(...)`` — writes an invoice
     line's category back to the master Pricebook item
     (``db.items`` row).

## Field write shapes (grep-verified · Feb-2026)

* Invoice line items (``quotes.line_items[]``) carry SIX
  category fields in lockstep (Q3):
      income modern:  income_category_id, income_category_name
      income legacy:  category, category_name  (aliases for the
                        income pair; both are set by the existing
                        ``_apply_line_item_recategorize`` handler)
      service modern: service_category_id, service_category_name
  The service pair has NO legacy alias.

* Pricebook items (``items``) carry FOUR modern fields + one
  legacy scalar (Q2):
      income_category_id, income_category_name,
      service_category_id, service_category_name,
      category  (legacy scalar; kept in lockstep with
                  income_category_id when the modern id is set)

* Recurring templates (``recurring_job_templates``) carry the
  4-tuple modern only. Handled by the PATCH wire, not this
  module.

## Loop prevention (55.4)

Every entry-point requires ``origin`` (kwarg). The module-level
``_SKIP_TABLE`` maps callee → set-of-origins-to-short-circuit.
Short-circuit returns ``SyncResult.no_op()`` with
``skipped_loop_count=1`` for observability. This is call-graph
loop breaking, NOT database CAS.

For ``sync_recurring_template_to_children`` the reserved slot is
populated with the ``_RESERVED_SELF_LOOP`` sentinel — a marker
string suffixed ``_do_not_pass_`` that no real caller ever
passes. Real callers use ``"recurring_template_edit"`` (from the
recurring-jobs PATCH handler). Keeping the reserved slot with a
sentinel — instead of a plausible-looking origin string — is
what prevents the Feb-2026 shipping bug (Commit 6, Option C):
before the fix, the reserved slot held the same string the PATCH
handler passed, silently disabling the entire template → invoice
fan-out. See PRD § P55 Category Sync Orchestrator for the full
recount.

## Price protection (55.5)

The SET clauses in both entry points are HARD-CODED WHITELISTS
of the category fields listed above. No price, quantity, tax,
discount, total, or ``_snapshot`` field is ever in the SET
clause. Introspection-friendly for tests — see
``test_price_snapshot_protection`` in
``backend/tests/test_p55_category_sync.py``.

## Tenant scoping

Every query filter passes ``tenant_id``. Cross-tenant
propagation is impossible by construction.

## Idempotency

Mongo's ``modified_count`` returns 0 when a ``$set`` writes the
same value already on disk. Second identical run therefore
yields ``updated_count == 0``.

## None / clear direction (Q · additional policy call)

* ``sync_recurring_template_to_children`` — passing ``None`` for
  a category id explicitly CLEARS that pair on child invoices.
  The template is source of truth for the chain; a template
  clear must propagate downstream.

* ``sync_invoice_line_to_pricebook`` — passing ``None`` SKIPS
  the write to Pricebook for that pair. Pricebook is the master;
  a downstream ephemeral clear on one invoice line must NOT
  wipe the master row.

The default value for either kwarg is the module-level
``_UNSET`` sentinel — passing nothing means "don't touch that
pair on child docs", distinct from an explicit ``None`` clear.

## Category-name lookup failure (55.5 halt-and-report)

If a caller passes a non-empty category_id that doesn't resolve
to an active category doc on the current tenant, the entry
point raises ``CategorySyncNameLookupError``. The caller
translates to HTTP 422 with
``{"code": "category_deleted_after_source_write",
  "category_id": <id>}``. No silent null-write path exists.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from config import db

logger = logging.getLogger("category_sync")


# ══════════════════════════════════════════════════════════════════
# Sentinel + result + exception types
# ══════════════════════════════════════════════════════════════════
class _UnsetType:
    """Sentinel for "kwarg not supplied by caller". Distinct
    from ``None`` (which means "explicitly clear" per the
    direction policy above)."""
    __slots__ = ()

    def __repr__(self) -> str:                            # pragma: no cover
        return "_UNSET"

    def __bool__(self) -> bool:                            # pragma: no cover
        return False


_UNSET: Any = _UnsetType()


def _is_unset(v: Any) -> bool:
    return isinstance(v, _UnsetType)


class CategorySyncNameLookupError(Exception):
    """Raised when a category_id is provided (non-empty) but no
    matching active category exists in the tenant's category
    collection. Caller translates to HTTP 422 with
    ``{"code": "category_deleted_after_source_write",
       "category_id": <id>}``.
    """

    def __init__(self, category_id: str, collection: str):
        self.category_id = category_id
        self.collection = collection
        super().__init__(
            f"category '{category_id}' not found in "
            f"{collection} (deleted after source write?)"
        )


@dataclass(frozen=True)
class SyncResult:
    """P55 sync-orchestrator return contract.

    ``errors_by_id`` maps target-doc-id → error-string; populated
    only on partial-failure scenarios (a target update raised).
    Empty on the happy path.
    """
    updated_count: int = 0
    skipped_paid_count: int = 0
    skipped_loop_count: int = 0
    errors_by_id: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def no_op(cls, *, skipped_loop_count: int = 1) -> "SyncResult":
        """Loop-prevention short-circuit return value."""
        return cls(skipped_loop_count=skipped_loop_count)


# ══════════════════════════════════════════════════════════════════
# Loop-prevention table (55.4)
# ══════════════════════════════════════════════════════════════════
# ``_RESERVED_SELF_LOOP`` — sentinel documenting where a future
# self-loop protection origin would slot in for
# ``sync_recurring_template_to_children``. Not a real origin: no
# caller ever passes this string, and the double-underscore +
# ``_do_not_pass_`` suffix make accidental adoption impossible.
#
# The reserved slot exists because the P55 grep-pass (Q4 · policy)
# committed to keeping a documented anchor for a hypothetical
# future "invoice → template" arrow. If such a path is ever
# introduced (e.g. an audit path that re-fires the template sync
# from an invoice mutation), its origin string is added to the
# ``sync_recurring_template_to_children`` skip set alongside this
# sentinel — the sentinel itself is left in place so the design
# intent is greppable from a single anchor.
#
# Shipping-bug context (Feb-2026, P55 · Commit 6 · Option C):
# Commits 1 + 2 landed with the string ``"recurring_template_edit"``
# used simultaneously as (a) the PATCH-time entry-point origin AND
# (b) the reserved short-circuit slot. Result: every real PATCH
# fan-out short-circuited on itself and the template → invoice
# propagation was inert in production. Option C fixes it by using
# the sentinel here so the entry origin (still
# ``"recurring_template_edit"``) can never collide.
_RESERVED_SELF_LOOP = "__reserved_self_loop_do_not_pass__"

_SKIP_TABLE: Dict[str, Set[str]] = {
    "sync_invoice_line_to_pricebook": {
        # Already came FROM the pricebook — don't loop back.
        "pricebook_writeback",
    },
    "sync_recurring_template_to_children": {
        # Reserved slot for future self-loop protection.
        # See ``_RESERVED_SELF_LOOP`` docblock above.
        _RESERVED_SELF_LOOP,
    },
}


# ══════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_category_name(
    tenant_id: str,
    category_id: str,
    *,
    collection: str,
) -> str:
    """Look up the active (non-archived) category name for the
    given id on the given tenant. Raises
    ``CategorySyncNameLookupError`` if the id doesn't resolve —
    the 55.5 halt-and-report guard."""
    cat = await db[collection].find_one(
        {"id": category_id, "tenant_id": tenant_id,
         "is_archived": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not cat:
        raise CategorySyncNameLookupError(
            category_id=category_id, collection=collection,
        )
    return cat.get("name") or ""


async def _write_sync_audit(
    *, tenant_id: str,
    source_type: str, source_id: str,
    origin_marker: str,
    diff_summary: Dict[str, Any],
    result: SyncResult,
    actor_id: Optional[str] = None,
) -> None:
    """One ``audit_logs`` row per orchestrator invocation
    (Q5 · Option B). Bounded shape — no per-row id list.
    Best-effort; a write failure logs + returns without raising
    so the sync outcome is preserved for the caller."""
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "event": "category.sync_from_template",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "source": {"type": source_type, "id": source_id},
            "origin_marker": origin_marker,
            "diff_summary": diff_summary,
            "updated_count": result.updated_count,
            "skipped_paid_count": result.skipped_paid_count,
            "skipped_loop_count": result.skipped_loop_count,
            "errors_by_id_count": len(result.errors_by_id),
            "created_at": _now_iso(),
        })
    except Exception:                                     # noqa: BLE001
        logger.exception(
            "[category_sync.audit] insert failed for "
            "source=%s id=%s", source_type, source_id,
        )


# ══════════════════════════════════════════════════════════════════
# Entry point 1 — Recurring template → linked unpaid invoices
# ══════════════════════════════════════════════════════════════════
async def sync_recurring_template_to_children(
    tenant_id: str,
    recurring_job_id: str,
    *,
    origin: str,
    service_category_id: Any = _UNSET,     # str | None | _UNSET
    income_category_id: Any = _UNSET,      # str | None | _UNSET
    actor_id: Optional[str] = None,
) -> SyncResult:
    """Propagate a Recurring Template's category change to all
    linked unpaid Invoices (grandchildren via jobs).

    Q1/Option B — Jobs are NOT updated (jobs don't carry
    category fields today).

    Semantic per field kwarg:
      * ``_UNSET`` (default) → don't touch that pair on child docs.
      * ``None`` → CLEAR that pair (write None to id + name +
        legacy alias where present).
      * non-empty ``str`` → resolve name, write id + name.

    Returns SyncResult with:
      * updated_count       — # invoices whose line_items were
                               modified (Mongo ``modified_count``).
      * skipped_paid_count — # paid invoices linked to this
                               template chain (informational).
      * skipped_loop_count — 1 if the call short-circuited on
                               the loop-prevention table.
      * errors_by_id       — invoice_id → error string on
                               per-doc failures.
    """
    # 55.4 · loop prevention (call-graph level, not DB CAS).
    if origin in _SKIP_TABLE["sync_recurring_template_to_children"]:
        logger.info(
            "[category_sync.recurring→children] short-circuit "
            "origin=%s tpl=%s", origin, recurring_job_id,
        )
        return SyncResult.no_op()

    # Nothing to sync?
    if _is_unset(service_category_id) and _is_unset(income_category_id):
        return SyncResult()

    # 55.5 · resolve names UP-FRONT before any write, so a name
    # lookup failure raises before any child doc is touched.
    income_name: Optional[str] = None
    service_name: Optional[str] = None
    if not _is_unset(income_category_id) and income_category_id:
        income_name = await _resolve_category_name(
            tenant_id, income_category_id,
            collection="income_categories",
        )
    if not _is_unset(service_category_id) and service_category_id:
        service_name = await _resolve_category_name(
            tenant_id, service_category_id,
            collection="service_categories",
        )

    # Walk the chain — templates → jobs (id-only) → invoices.
    # Jobs are NOT mutated (Q1/Option B), only used to enumerate
    # the linked invoice universe via job_id ∈ that set.
    job_ids = []
    async for j in db.jobs.find(
        {"tenant_id": tenant_id,
         "recurring_template_id": recurring_job_id},
        {"_id": 0, "id": 1},
    ):
        job_ids.append(j["id"])

    if not job_ids:
        # No child jobs → no linked invoices possible → done.
        result = SyncResult()
        diff_summary = _build_diff_summary(
            income_category_id, service_category_id,
        )
        await _write_sync_audit(
            tenant_id=tenant_id,
            source_type="recurring_template",
            source_id=recurring_job_id,
            origin_marker=origin,
            diff_summary=diff_summary,
            result=result,
            actor_id=actor_id,
        )
        return result

    # Fetch each unpaid linked invoice.
    unpaid = await db.quotes.find(
        {"tenant_id": tenant_id,
         "doc_type": "invoice",
         "job_id": {"$in": job_ids},
         "payment_status": {"$ne": "paid"}},
        {"_id": 0, "id": 1, "line_items": 1},
    ).to_list(5000)

    # Count paid invoices for informational skipped_paid_count.
    paid_count = await db.quotes.count_documents({
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "job_id": {"$in": job_ids},
        "payment_status": "paid",
    })

    # For each unpaid invoice, build a per-line SET clause.
    # 6 fields per line item (Q3). Lockstep write across all
    # lines on the invoice.
    #
    # No-op guard (55.5 · idempotency): filter set_ops to only
    # include fields whose target value differs from the current
    # value on the line item. If every field on every line is
    # already at the target value, skip the write entirely.
    updated_count = 0
    errors: Dict[str, str] = {}
    for inv in unpaid:
        line_items = inv.get("line_items") or []
        if not line_items:
            continue
        set_ops: Dict[str, Any] = {}
        for idx, li in enumerate(line_items):
            # Compute the target values for this line.
            new_income_id = (
                (income_category_id or None)
                if not _is_unset(income_category_id) else None
            )
            new_income_name = (
                (income_name if income_category_id else None)
                if not _is_unset(income_category_id) else None
            )
            new_service_id = (
                (service_category_id or None)
                if not _is_unset(service_category_id) else None
            )
            new_service_name = (
                (service_name if service_category_id else None)
                if not _is_unset(service_category_id) else None
            )
            # Only emit SET ops for fields whose current value
            # differs from the target — this is what turns a
            # re-run into a genuine no-op.
            if not _is_unset(income_category_id):
                # Income modern pair.
                if li.get("income_category_id") != new_income_id:
                    set_ops[
                        f"line_items.{idx}.income_category_id"
                    ] = new_income_id
                if li.get("income_category_name") != new_income_name:
                    set_ops[
                        f"line_items.{idx}.income_category_name"
                    ] = new_income_name
                # Income legacy aliases (Q3 lockstep).
                if li.get("category") != new_income_id:
                    set_ops[f"line_items.{idx}.category"] = new_income_id
                if li.get("category_name") != new_income_name:
                    set_ops[f"line_items.{idx}.category_name"] = new_income_name
            if not _is_unset(service_category_id):
                if li.get("service_category_id") != new_service_id:
                    set_ops[
                        f"line_items.{idx}.service_category_id"
                    ] = new_service_id
                if li.get("service_category_name") != new_service_name:
                    set_ops[
                        f"line_items.{idx}.service_category_name"
                    ] = new_service_name

        # If nothing would change on any line, skip the write
        # entirely — this is the true idempotency guard: no DB
        # touch, no ``updated_at`` bump, no modified_count.
        if not set_ops:
            continue

        # Non-empty change set — bump ``updated_at`` and write.
        set_ops["updated_at"] = _now_iso()

        try:
            # NOTE the ``payment_status != paid`` re-guard on the
            # write filter — protects against a paid-transition
            # race between the read and the write.
            r = await db.quotes.update_one(
                {"id": inv["id"], "tenant_id": tenant_id,
                 "doc_type": "invoice",
                 "payment_status": {"$ne": "paid"}},
                {"$set": set_ops},
            )
            if r.modified_count > 0:
                updated_count += 1
        except Exception as e:                             # noqa: BLE001
            errors[inv["id"]] = str(e)

    result = SyncResult(
        updated_count=updated_count,
        skipped_paid_count=paid_count,
        errors_by_id=errors,
    )
    diff_summary = _build_diff_summary(
        income_category_id, service_category_id,
    )
    await _write_sync_audit(
        tenant_id=tenant_id,
        source_type="recurring_template",
        source_id=recurring_job_id,
        origin_marker=origin,
        diff_summary=diff_summary,
        result=result,
        actor_id=actor_id,
    )
    return result


# ══════════════════════════════════════════════════════════════════
# Entry point 2 — Invoice line → Pricebook master
# ══════════════════════════════════════════════════════════════════
async def sync_invoice_line_to_pricebook(
    tenant_id: str,
    invoice_id: str,
    line_item_id: str,
    *,
    origin: str,
    service_category_id: Any = _UNSET,     # str | None | _UNSET
    income_category_id: Any = _UNSET,      # str | None | _UNSET
    actor_id: Optional[str] = None,
) -> SyncResult:
    """Propagate an invoice line's category change back to the
    master Pricebook item (``db.items`` row).

    Q2/Option A — writes the 4 modern taxonomy fields on
    ``db.items`` via ``$set``; also keeps the legacy scalar
    ``category`` in lockstep with ``income_category_id``.

    Semantic per field kwarg (differs from template→children):
      * ``_UNSET`` (default) → don't touch that pair on the
        Pricebook row.
      * ``None`` → SKIP the write for that pair. Pricebook is
        master; a downstream ephemeral clear on one invoice
        line must NOT wipe the master row (Q · policy).
      * non-empty ``str`` → resolve name, write id + name.

    Line-item identification: uses ``line_item_id`` to locate
    the target line's ``pricebook_item_id`` or legacy alias
    ``item_id`` FK on ``db.items``. Missing FK → no-op.
    """
    # 55.4 · loop prevention.
    if origin in _SKIP_TABLE["sync_invoice_line_to_pricebook"]:
        logger.info(
            "[category_sync.invoice→pricebook] short-circuit "
            "origin=%s inv=%s li=%s",
            origin, invoice_id, line_item_id,
        )
        return SyncResult.no_op()

    # Determine what's actually writable (None = skip per Q).
    def _writable(v: Any) -> bool:
        return (not _is_unset(v)) and v is not None and v != ""

    write_income = _writable(income_category_id)
    write_service = _writable(service_category_id)
    if not write_income and not write_service:
        return SyncResult()

    # Resolve names before any write.
    income_name: Optional[str] = None
    service_name: Optional[str] = None
    if write_income:
        income_name = await _resolve_category_name(
            tenant_id, income_category_id,
            collection="income_categories",
        )
    if write_service:
        service_name = await _resolve_category_name(
            tenant_id, service_category_id,
            collection="service_categories",
        )

    # Locate the invoice line + its Pricebook FK.
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id,
         "doc_type": "invoice"},
        {"_id": 0, "line_items": 1},
    )
    if not inv:
        return SyncResult()

    target_pb_id: Optional[str] = None
    for li in (inv.get("line_items") or []):
        if li.get("id") == line_item_id:
            # Grep-verified · writeback.py:96 dual-key.
            target_pb_id = (
                li.get("pricebook_item_id") or li.get("item_id")
            )
            break

    if not target_pb_id:
        # No pricebook FK on this line — nothing to sync.
        return SyncResult()

    # Build the SET clause — hard whitelist. Modern 4 + legacy
    # ``category`` scalar (in lockstep with income_category_id).
    #
    # No-op guard (55.5 · idempotency): only include SET ops
    # for fields whose target value differs from the current
    # value on the Pricebook row.
    pb_row = await db.items.find_one(
        {"id": target_pb_id, "tenant_id": tenant_id},
        {"_id": 0},
    ) or {}
    set_ops: Dict[str, Any] = {}
    if write_income:
        if pb_row.get("income_category_id") != income_category_id:
            set_ops["income_category_id"] = income_category_id
        if pb_row.get("income_category_name") != income_name:
            set_ops["income_category_name"] = income_name
        if pb_row.get("category") != income_category_id:
            set_ops["category"] = income_category_id  # legacy scalar
    if write_service:
        if pb_row.get("service_category_id") != service_category_id:
            set_ops["service_category_id"] = service_category_id
        if pb_row.get("service_category_name") != service_name:
            set_ops["service_category_name"] = service_name

    if not set_ops:
        # Idempotent no-op — Pricebook row already at target
        # values. Skip the write; still emit the audit row so
        # the ops ledger reflects the (0-update) invocation.
        result = SyncResult()
        diff_summary = _build_diff_summary(
            income_category_id if write_income else _UNSET,
            service_category_id if write_service else _UNSET,
        )
        await _write_sync_audit(
            tenant_id=tenant_id,
            source_type="invoice_line",
            source_id=f"{invoice_id}:{line_item_id}",
            origin_marker=origin,
            diff_summary=diff_summary,
            result=result,
            actor_id=actor_id,
        )
        return result

    set_ops["updated_at"] = _now_iso()

    r = await db.items.update_one(
        {"id": target_pb_id, "tenant_id": tenant_id},
        {"$set": set_ops},
    )
    result = SyncResult(
        updated_count=1 if r.modified_count > 0 else 0,
    )
    diff_summary = _build_diff_summary(
        income_category_id if write_income else _UNSET,
        service_category_id if write_service else _UNSET,
    )
    await _write_sync_audit(
        tenant_id=tenant_id,
        source_type="invoice_line",
        source_id=f"{invoice_id}:{line_item_id}",
        origin_marker=origin,
        diff_summary=diff_summary,
        result=result,
        actor_id=actor_id,
    )
    return result


# ══════════════════════════════════════════════════════════════════
# Diff-summary shape (Q5 audit contract)
# ══════════════════════════════════════════════════════════════════
def _build_diff_summary(
    income_category_id: Any,
    service_category_id: Any,
) -> Dict[str, Any]:
    """Bounded audit-payload shape. ``to`` may be ``None``
    (explicit clear) or the target id. Absent keys mean "not
    touched by this sync"."""
    out: Dict[str, Any] = {}
    if not _is_unset(income_category_id):
        out["income_category_id"] = {"to": income_category_id or None}
    if not _is_unset(service_category_id):
        out["service_category_id"] = {"to": service_category_id or None}
    return out


# Re-export public API surface.
__all__ = [
    "SyncResult",
    "CategorySyncNameLookupError",
    "sync_recurring_template_to_children",
    "sync_invoice_line_to_pricebook",
    "_UNSET",
    "_SKIP_TABLE",
    "_RESERVED_SELF_LOOP",
]
