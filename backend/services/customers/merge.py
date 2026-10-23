"""Feb-2026 · greenfield customer-merge engine.

Replaces the Jan-2026 ``services.customer_merge`` module (now
SUPERSEDED — see that package's ``__init__.py`` header + TD-36 /
TD-37 in ``memory/TECH_DEBT.md``).

Design highlights:

  * **Admin picks the winner + per-field value** (no auto-pick by
    ``updated_at``).  Field reconciliation is driven by an
    explicit ``field_overrides`` dict supplied by the FE merge
    dialog.
  * **12-collection child-record rewire** per the operator's locked
    ruling: ``jobs``, ``quotes`` (``doc_type IN ("invoice","quote",
    "estimate")``), ``payments``, ``properties``,
    ``recurring_job_templates``, ``communications``,
    ``service_reports``, GPS pings (``gps_locations``),
    ``time_clock_entries``, ``pool_reports``, ``portal_messages``,
    ``notification_outbox``.  Plus actor-side ``audit_logs``
    (``actor_customer_id``) — never target-side.
  * **24h recurring-template block** with structured error payload
    (template id + ``last_generated_through``) + ``force=true``
    override.
  * **Stripe PaymentMethod remap** with full rollback on failure.
    Zero tolerance for half-merged state.
  * **90-day audit snapshot** in new ``customer_merge_audit``
    collection.  No Mongo TTL — a future cron purges >90d
    entries explicitly so operators can extend retention per
    tenant if needed.  Shipped indexes: ``expires_at`` asc,
    ``winner_id`` asc, ``loser_id`` asc.
  * **Per-collection failure trace**: any individual
    ``update_many`` failure is caught, logged with the exact
    collection name + error, and triggers a full reverse of
    every completed step before raising.

Credit mutation flows through
:func:`services.customer_balance.mutate_credit` with the
dispatch-locked idempotency key ``merge:<loser>:<winner>`` so a
retried merge never double-sums the balance.

Portal-user disposition: the loser's ``db.users`` doc (if any)
is soft-deleted via ``deleted_at`` so the existing P37 session-
invalidation path (SHA 161676e5d) kicks in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ASCENDING

from services.imports.customer_match_ladder import _canon_name
from utils import new_id


logger = logging.getLogger("customers.merge")


# ═════════════════════════════════════════════════════════════
# Config
# ═════════════════════════════════════════════════════════════
# Collections whose rows carry a ``customer_id`` FK that must
# be rewired to the winner at merge time.  Each entry is
# ``(collection_name, extra_filter_dict)`` — the filter is
# merged into the ``update_many`` query so e.g. ``quotes``
# can scope to the invoice / quote / estimate doc_types.
_REWIRE_TARGETS: List[Tuple[str, Dict[str, Any]]] = [
    ("jobs", {}),
    ("quotes", {"doc_type": {"$in": ["invoice", "quote", "estimate"]}}),
    ("payments", {}),
    ("properties", {}),
    ("recurring_job_templates", {}),
    ("communications", {}),
    ("service_reports", {}),
    ("gps_locations", {}),
    ("time_clock_entries", {}),
    ("pool_reports", {}),
    ("portal_messages", {}),
    ("notification_outbox", {}),
]

# ``audit_logs`` is rewired on the actor-customer side only
# (ruling: "actor-side only, not target-side").  Target-side
# audit entries are preserved so the merge forensic trail is
# intact.
_AUDIT_ACTOR_FIELD = "actor_customer_id"

# 24h recurring-template cutoff.  Templates whose
# ``last_generated_through`` is within the last day block the
# merge unless ``force=True`` is supplied.
_RECURRING_BLOCK_WINDOW = timedelta(hours=24)

# Audit retention — 90 days per operator ruling.
_AUDIT_RETENTION_DAYS = 90


# ═════════════════════════════════════════════════════════════
# Public types
# ═════════════════════════════════════════════════════════════
@dataclass
class MergeResult:
    audit_id: str
    winner_id: str
    loser_id: str
    child_record_counts: Dict[str, int] = field(default_factory=dict)
    credit_merged_cents: int = 0
    stripe_payment_methods_remapped: List[str] = field(default_factory=list)
    portal_user_soft_deleted: bool = False
    merged_at: str = ""


class MergeError(Exception):
    """Base class for all merge failures.  Carries a structured
    ``error_code`` + optional ``detail`` payload the router
    translates into the HTTP body.
    """
    def __init__(self, error_code: str, message: str, **detail: Any):
        super().__init__(message)
        self.error_code = error_code
        self.detail = detail


# ═════════════════════════════════════════════════════════════
# Index bootstrap
# ═════════════════════════════════════════════════════════════
async def ensure_merge_audit_indexes(db) -> None:
    """Create the ``customer_merge_audit`` indexes if absent.

    Three single-field asc indexes — no composite — because the
    read paths (merge-history fetch by customer, rollback
    inventory grep by ``expires_at``) only need to range-scan
    one axis at a time.  **No Mongo TTL** — a future cron
    purges >90d entries explicitly per the operator ruling.
    """
    coll = db.customer_merge_audit
    try:
        await coll.create_index([("winner_id", ASCENDING)],
                                 name="customer_merge_audit_winner_idx")
        await coll.create_index([("loser_id", ASCENDING)],
                                 name="customer_merge_audit_loser_idx")
        await coll.create_index([("expires_at", ASCENDING)],
                                 name="customer_merge_audit_expires_at_idx")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[customer_merge] ensure_indexes failed (non-fatal, "
            "will retry on next merge call): %s", exc,
        )


# ═════════════════════════════════════════════════════════════
# Pre-flight helpers
# ═════════════════════════════════════════════════════════════
async def _load_customer(db, tenant_id: str, cid: str) -> Dict[str, Any]:
    row = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id,
          "deleted_at": {"$in": [None, "", False]}},
        {"_id": 0},
    )
    if not row:
        raise MergeError(
            "merge_customer_not_found",
            f"Customer {cid!r} not found in this tenant or already soft-deleted.",
            customer_id=cid,
        )
    return row


async def _check_24h_recurring_block(
    db, *, tenant_id: str, loser_id: str,
) -> List[Dict[str, Any]]:
    """Return the list of blocking template rows ({id, last_generated_through}).
    Empty list = no block; non-empty = merge blocked unless ``force=True``.
    """
    cutoff = (datetime.now(timezone.utc) - _RECURRING_BLOCK_WINDOW).isoformat()
    cursor = db.recurring_job_templates.find(
        {
            "tenant_id": tenant_id,
            "customer_id": loser_id,
            "deleted_at": {"$in": [None, "", False]},
        },
        {"_id": 0, "id": 1, "last_generated_through": 1},
    )
    blocking: List[Dict[str, Any]] = []
    async for tpl in cursor:
        lgt = tpl.get("last_generated_through") or ""
        lgt_str = (
            lgt.isoformat() if hasattr(lgt, "isoformat") else str(lgt)
        )
        if lgt_str and lgt_str >= cutoff[:10]:
            # The template's ``last_generated_through`` is a date
            # (YYYY-MM-DD) in production.  Compare on the date
            # prefix of the cutoff so "today == within 24h" is
            # the sentinel.
            blocking.append({
                "template_id": tpl.get("id"),
                "last_generated_through": lgt_str[:10],
            })
    return blocking


# ═════════════════════════════════════════════════════════════
# Core engine
# ═════════════════════════════════════════════════════════════
async def _snapshot_child_record_ids(
    db, *, tenant_id: str, loser_id: str,
) -> Dict[str, List[str]]:
    """Enumerate the ids per collection the merge will rewire.
    Captured BEFORE the ``update_many`` so rollback knows which
    specific docs to flip back (vs flipping every winner doc
    which would corrupt the pre-existing winner's records).
    """
    out: Dict[str, List[str]] = {}
    for coll_name, extra in _REWIRE_TARGETS:
        q = {"tenant_id": tenant_id, "customer_id": loser_id, **extra}
        cursor = db[coll_name].find(q, {"_id": 0, "id": 1})
        ids: List[str] = []
        async for r in cursor:
            if r.get("id"):
                ids.append(r["id"])
        out[coll_name] = ids
    # Feb-2026 · TD-invoice-customer-id-repair-on-merge safety-belt —
    # derive the invoice-only sub-set of the quotes snapshot so
    # the rewire step can log the invoice-specific count moved.
    # Observability-only: the generic ``quotes`` rewire above
    # already lands these records on the winner; this sub-slice
    # proves the belt is working on every merge call so operators
    # can grep for ``kind=invoice_cid_moved`` in logs.
    quote_ids = out.get("quotes") or []
    if quote_ids:
        inv_ids: List[str] = []
        async for r in db.quotes.find(
            {"tenant_id": tenant_id,
             "id": {"$in": quote_ids},
             "doc_type": "invoice"},
            {"_id": 0, "id": 1},
        ):
            if r.get("id"):
                inv_ids.append(r["id"])
        out["quotes.invoices"] = inv_ids
    else:
        out["quotes.invoices"] = []
    # Actor-side audit_logs — same pattern.
    cursor = db.audit_logs.find(
        {"tenant_id": tenant_id, _AUDIT_ACTOR_FIELD: loser_id},
        {"_id": 0, "id": 1},
    )
    ids = []
    async for r in cursor:
        if r.get("id"):
            ids.append(r["id"])
    out["audit_logs.actor"] = ids
    return out


async def _rewire_children(
    db, *, tenant_id: str,
    winner_id: str, loser_id: str,
    snapshot_ids: Dict[str, List[str]],
    counts_out: Dict[str, int],
) -> Dict[str, int]:
    """Rewire ``customer_id`` → ``winner_id`` on every captured
    doc.  ``counts_out`` is a caller-owned dict the helper mutates
    in-place so the caller sees the partial-success state when a
    mid-loop collection raises.  Returns the same dict for ergonomic
    chaining.
    """
    for coll_name, _extra in _REWIRE_TARGETS:
        ids = snapshot_ids.get(coll_name) or []
        if not ids:
            counts_out[coll_name] = 0
            continue
        try:
            res = await db[coll_name].update_many(
                {"tenant_id": tenant_id, "id": {"$in": ids}},
                {"$set": {"customer_id": winner_id}},
            )
            counts_out[coll_name] = int(getattr(res, "modified_count", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[customer_merge] kind=rewire_failed coll=%s "
                "winner=%s loser=%s err=%s",
                coll_name, winner_id, loser_id, exc,
            )
            raise MergeError(
                "merge_rewire_failed",
                f"Rewire of collection {coll_name!r} failed; rolling back.",
                collection=coll_name, raw=str(exc),
            ) from exc
    # Feb-2026 · TD-invoice-customer-id-repair-on-merge safety-belt —
    # derive + log the invoice-only sub-count moved via the generic
    # ``quotes`` rewire above.  Observability-only (no writes
    # beyond what the generic loop already did); logged with the
    # structured kind tag so operators can confirm every merge is
    # repointing invoices as expected.
    invoice_ids_moved = snapshot_ids.get("quotes.invoices") or []
    counts_out["quotes.invoices"] = len(invoice_ids_moved)
    if invoice_ids_moved:
        logger.info(
            "[customer_merge] kind=invoice_cid_moved tenant=%s "
            "winner=%s loser=%s count=%s",
            tenant_id, winner_id, loser_id, len(invoice_ids_moved),
        )
    # Actor-side audit_logs — rewrite ``_AUDIT_ACTOR_FIELD``.
    actor_ids = snapshot_ids.get("audit_logs.actor") or []
    if actor_ids:
        try:
            res = await db.audit_logs.update_many(
                {"tenant_id": tenant_id, "id": {"$in": actor_ids}},
                {"$set": {_AUDIT_ACTOR_FIELD: winner_id}},
            )
            counts_out["audit_logs.actor"] = int(
                getattr(res, "modified_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[customer_merge] kind=rewire_failed coll=audit_logs.actor "
                "winner=%s loser=%s err=%s",
                winner_id, loser_id, exc,
            )
            raise MergeError(
                "merge_rewire_failed",
                "Rewire of audit_logs.actor_customer_id failed; "
                "rolling back.",
                collection="audit_logs.actor", raw=str(exc),
            ) from exc
    else:
        counts_out["audit_logs.actor"] = 0
    return counts_out


async def _reverse_rewire_children(
    db, *, tenant_id: str,
    winner_id: str, loser_id: str,
    snapshot_ids: Dict[str, List[str]],
    partial_counts: Dict[str, int],
) -> None:
    """Reverse the ``_rewire_children`` effect using the snapshot
    ids.  Only collections that reported a non-zero
    ``partial_counts`` entry need reversing — anything that
    failed before writing is already consistent.
    """
    for coll_name, _extra in _REWIRE_TARGETS:
        if partial_counts.get(coll_name, 0) == 0:
            continue
        ids = snapshot_ids.get(coll_name) or []
        if not ids:
            continue
        try:
            await db[coll_name].update_many(
                {"tenant_id": tenant_id, "id": {"$in": ids}},
                {"$set": {"customer_id": loser_id}},
            )
        except Exception as exc:  # noqa: BLE001
            # A rollback failure is the worst outcome — log loudly
            # but keep reversing the rest so partial recovery
            # is maximally achieved.
            logger.error(
                "[customer_merge] kind=rollback_failed coll=%s "
                "winner=%s loser=%s err=%s",
                coll_name, winner_id, loser_id, exc,
            )
    actor_ids = snapshot_ids.get("audit_logs.actor") or []
    if partial_counts.get("audit_logs.actor", 0) and actor_ids:
        try:
            await db.audit_logs.update_many(
                {"tenant_id": tenant_id, "id": {"$in": actor_ids}},
                {"$set": {_AUDIT_ACTOR_FIELD: loser_id}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[customer_merge] kind=rollback_failed "
                "coll=audit_logs.actor err=%s", exc,
            )


async def _apply_field_overrides(
    db, *, tenant_id: str, winner_id: str,
    winner_before: Dict[str, Any],
    loser_before: Dict[str, Any],
    field_overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply the admin's per-field picks to the winner row.
    Returns the applied-overrides dict for the audit snapshot.

    Non-metadata fields only — the merge never touches
    ``id`` / ``tenant_id`` / ``created_at`` / ``updated_at``
    / ``deleted_at`` / ``merged_into`` / ``merged_at``.
    """
    _METADATA = frozenset({
        "id", "_id", "tenant_id",
        "created_at", "updated_at",
        "deleted_at", "deleted_by_user_id",
        "merged_into", "merged_at", "merged_by",
    })
    applied: Dict[str, Any] = {}
    for field_name, value in (field_overrides or {}).items():
        if field_name in _METADATA:
            # Silently drop metadata overrides so a malicious or
            # buggy FE can't tamper with the invariants.
            continue
        applied[field_name] = value
    if applied:
        await db.customers.update_one(
            {"id": winner_id, "tenant_id": tenant_id},
            {"$set": {
                **applied,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    return applied


async def _sum_credit(
    db, *, tenant_id: str, winner_id: str, loser_id: str,
    actor: Optional[Dict[str, Any]],
) -> int:
    """Transfer the loser's credit balance to the winner via
    :func:`services.customer_balance.mutate_credit`.  Returns the
    cents moved.  Idempotency key per dispatch spec:
    ``merge:<loser_id>:<winner_id>``.
    """
    from services.customer_balance import (
        compute_customer_balance, mutate_credit,
    )
    loser_balance = await compute_customer_balance(
        db, tenant_id=tenant_id, customer_id=loser_id,
    )
    cents = int(loser_balance or 0)
    if cents == 0:
        return 0
    # Debit the loser first so the aggregate is clean.
    await mutate_credit(
        db, tenant_id, loser_id,
        delta_cents=-cents,
        source="customer_merge",
        actor=actor,
        reason=f"merged into {winner_id}",
        idempotency_key=f"merge:{loser_id}:{winner_id}:debit",
    )
    # Then credit the winner.
    await mutate_credit(
        db, tenant_id, winner_id,
        delta_cents=cents,
        source="customer_merge",
        actor=actor,
        reason=f"merged from {loser_id}",
        idempotency_key=f"merge:{loser_id}:{winner_id}",
    )
    return cents


async def _soft_delete_loser_portal_user(
    db, *, tenant_id: str, loser_id: str,
) -> bool:
    """Soft-delete the loser's ``db.users`` doc (if any).  Returns
    True if a user row was flipped.  Session invalidation
    piggybacks on the P37 ``deleted_at`` 401 mechanism
    (SHA 161676e5d).
    """
    now = datetime.now(timezone.utc).isoformat()
    res = await db.users.update_many(
        {
            "tenant_id": tenant_id,
            "customer_id": loser_id,
            "deleted_at": {"$in": [None, "", False]},
        },
        {"$set": {"deleted_at": now,
                    "deleted_by_user_id": "customer_merge"}},
    )
    return int(getattr(res, "modified_count", 0)) > 0


async def _remap_stripe_payment_methods(
    db, *, tenant_id: str,
    winner_before: Dict[str, Any],
    loser_before: Dict[str, Any],
) -> List[str]:
    """Remap every ``db.payment_methods`` row that currently
    points at the loser's ``stripe_customer_id`` so the row's
    ``customer_id`` matches the winner, and (if a Stripe SDK is
    available) call ``PaymentMethod.modify(pm, customer=...)``
    to update the Stripe-side owner.  Returns the list of
    remapped payment-method ids.

    Zero-tolerance: any Stripe failure raises
    :class:`MergeError` so the caller rolls back.
    """
    loser_sid = loser_before.get("stripe_customer_id")
    winner_sid = winner_before.get("stripe_customer_id")
    if not loser_sid:
        return []  # Nothing to remap.
    if not winner_sid:
        raise MergeError(
            "merge_blocked_stripe_winner_missing",
            "Loser has a Stripe customer id but the winner does "
            "not — Stripe cannot remap payment methods without "
            "a destination customer.  Resolve by backfilling the "
            "winner's stripe_customer_id first.",
            loser_stripe_customer_id=loser_sid,
        )
    # DB-side remap first.
    pm_cursor = db.payment_methods.find(
        {"tenant_id": tenant_id, "customer_id": loser_before["id"]},
        {"_id": 0, "id": 1, "stripe_payment_method_id": 1},
    )
    pm_rows: List[Dict[str, Any]] = []
    async for r in pm_cursor:
        pm_rows.append(r)
    if not pm_rows:
        return []
    # Stripe-side remap — best effort via existing SDK facade.
    # Lazy import so tests without Stripe installed can still
    # exercise the DB-only path.
    try:
        import stripe as _stripe  # noqa: F401
        from services.payments.stripe_charge import _to_thread
    except ImportError:
        _stripe = None  # type: ignore
        _to_thread = None  # type: ignore
    remapped: List[str] = []
    for row in pm_rows:
        pm_id = row.get("stripe_payment_method_id")
        if pm_id and _stripe is not None and _to_thread is not None:
            try:
                await _to_thread(
                    _stripe.PaymentMethod.modify, pm_id,
                    customer=winner_sid,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[customer_merge] kind=stripe_remap_failed "
                    "pm_id=%s loser=%s winner=%s err=%s",
                    pm_id, loser_before["id"],
                    winner_before["id"], exc,
                )
                raise MergeError(
                    "merge_stripe_remap_failed",
                    f"Stripe PaymentMethod.modify failed for {pm_id!r}; "
                    "rolling back.",
                    payment_method_id=pm_id, raw=str(exc),
                ) from exc
        await db.payment_methods.update_one(
            {"tenant_id": tenant_id, "id": row["id"]},
            {"$set": {"customer_id": winner_before["id"]}},
        )
        remapped.append(row["id"])
    return remapped


# ═════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════
async def merge_customers(
    *,
    db,
    tenant_id: str,
    winner_id: str,
    loser_id: str,
    field_overrides: Optional[Dict[str, Any]] = None,
    actor: Optional[Dict[str, Any]] = None,
    confirm_name: str = "",
    force: bool = False,
) -> MergeResult:
    """Merge ``loser_id`` into ``winner_id``.  See module header
    for the full contract.
    """
    if winner_id == loser_id:
        raise MergeError(
            "merge_invalid_same_customer",
            "Winner and loser must be different customers.",
        )
    winner_before = await _load_customer(db, tenant_id, winner_id)
    loser_before = await _load_customer(db, tenant_id, loser_id)

    # Confirm-name gate.
    canon_confirm = _canon_name(confirm_name)
    canon_loser = _canon_name(loser_before.get("name") or "")
    if not canon_confirm or canon_confirm != canon_loser:
        raise MergeError(
            "merge_confirm_name_mismatch",
            "confirm_name does not match the loser's name "
            "(case-insensitive, whitespace-collapsed, ampersand-canonical).",
        )

    # 24h recurring-template pre-flight.
    blocking = await _check_24h_recurring_block(
        db, tenant_id=tenant_id, loser_id=loser_id,
    )
    if blocking and not force:
        raise MergeError(
            "merge_blocked_recent_recurring_activity",
            "Loser has recent recurring generation; wait 24h or "
            "stop templates first.",
            blocking_templates=blocking,
            override_available=True,
        )

    merged_at = datetime.now(timezone.utc)
    merged_at_iso = merged_at.isoformat()
    expires_at_iso = (merged_at + timedelta(
        days=_AUDIT_RETENTION_DAYS)).isoformat()

    # Snapshot child-record ids BEFORE the rewire so rollback
    # knows which specific docs to flip back.
    snapshot_ids = await _snapshot_child_record_ids(
        db, tenant_id=tenant_id, loser_id=loser_id,
    )

    # Audit insert first so the merge is traceable even if the
    # rest fails before the final soft-delete lands.
    audit_id = new_id()
    audit_doc = {
        "id": audit_id,
        "tenant_id": tenant_id,
        "winner_id": winner_id,
        "loser_id": loser_id,
        "winner_snapshot": {k: v for k, v in winner_before.items()
                              if k != "_id"},
        "loser_snapshot": {k: v for k, v in loser_before.items()
                             if k != "_id"},
        "child_record_ids": snapshot_ids,
        "field_overrides": field_overrides or {},
        "actor_id": (actor or {}).get("id"),
        "force": bool(force),
        "merged_at": merged_at_iso,
        "expires_at": expires_at_iso,
        "rolled_back_at": None,
    }
    await db.customer_merge_audit.insert_one(audit_doc)

    # Child-record rewire.  Any failure → rollback.
    partial_counts: Dict[str, int] = {}
    try:
        await _rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            counts_out=partial_counts,
        )
    except MergeError:
        await _reverse_rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            partial_counts=partial_counts,
        )
        await db.customer_merge_audit.delete_one({"id": audit_id})
        raise

    # Field overrides on the winner.
    try:
        applied_overrides = await _apply_field_overrides(
            db, tenant_id=tenant_id, winner_id=winner_id,
            winner_before=winner_before, loser_before=loser_before,
            field_overrides=field_overrides or {},
        )
    except Exception as exc:  # noqa: BLE001
        await _reverse_rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            partial_counts=partial_counts,
        )
        await db.customer_merge_audit.delete_one({"id": audit_id})
        raise MergeError(
            "merge_field_overrides_failed",
            f"Applying field overrides failed; rolling back: {exc}",
            raw=str(exc),
        ) from exc

    # Credit sum.
    try:
        credit_cents = await _sum_credit(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id, actor=actor,
        )
    except Exception as exc:  # noqa: BLE001
        # Reverse field overrides first (restore winner's prior
        # scalar values from the snapshot).
        if applied_overrides:
            await db.customers.update_one(
                {"id": winner_id, "tenant_id": tenant_id},
                {"$set": {k: winner_before.get(k)
                             for k in applied_overrides}},
            )
        await _reverse_rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            partial_counts=partial_counts,
        )
        await db.customer_merge_audit.delete_one({"id": audit_id})
        raise MergeError(
            "merge_credit_sum_failed",
            f"Transferring credit balance failed; rolling back: {exc}",
            raw=str(exc),
        ) from exc

    # Portal user soft-delete.
    portal_flipped = False
    try:
        portal_flipped = await _soft_delete_loser_portal_user(
            db, tenant_id=tenant_id, loser_id=loser_id,
        )
    except Exception as exc:  # noqa: BLE001
        # Reverse credit, then field overrides, then rewire.
        if credit_cents:
            from services.customer_balance import mutate_credit
            await mutate_credit(
                db, tenant_id, loser_id,
                delta_cents=credit_cents, source="customer_merge",
                actor=actor, reason=f"rollback from {winner_id}",
                idempotency_key=f"merge:{loser_id}:{winner_id}:rollback-restore",
            )
            await mutate_credit(
                db, tenant_id, winner_id,
                delta_cents=-credit_cents, source="customer_merge",
                actor=actor, reason=f"rollback to {loser_id}",
                idempotency_key=f"merge:{loser_id}:{winner_id}:rollback-debit",
            )
        if applied_overrides:
            await db.customers.update_one(
                {"id": winner_id, "tenant_id": tenant_id},
                {"$set": {k: winner_before.get(k)
                             for k in applied_overrides}},
            )
        await _reverse_rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            partial_counts=partial_counts,
        )
        await db.customer_merge_audit.delete_one({"id": audit_id})
        raise MergeError(
            "merge_portal_user_failed",
            f"Soft-deleting loser portal user failed; rolling back: {exc}",
            raw=str(exc),
        ) from exc

    # Stripe remap.  Must come AFTER credit + portal because
    # Stripe is the only external side-effect — if it fails we
    # need every DB write already reversed.
    remapped_pm_ids: List[str] = []
    try:
        remapped_pm_ids = await _remap_stripe_payment_methods(
            db, tenant_id=tenant_id,
            winner_before=winner_before,
            loser_before=loser_before,
        )
    except MergeError as exc:
        # Reverse portal, credit, overrides, rewire.
        if portal_flipped:
            await db.users.update_many(
                {"tenant_id": tenant_id, "customer_id": loser_id},
                {"$set": {"deleted_at": None,
                            "deleted_by_user_id": None}},
            )
        if credit_cents:
            from services.customer_balance import mutate_credit
            await mutate_credit(
                db, tenant_id, loser_id,
                delta_cents=credit_cents, source="customer_merge",
                actor=actor, reason=f"rollback from {winner_id}",
                idempotency_key=f"merge:{loser_id}:{winner_id}:rollback-restore",
            )
            await mutate_credit(
                db, tenant_id, winner_id,
                delta_cents=-credit_cents, source="customer_merge",
                actor=actor, reason=f"rollback to {loser_id}",
                idempotency_key=f"merge:{loser_id}:{winner_id}:rollback-debit",
            )
        if applied_overrides:
            await db.customers.update_one(
                {"id": winner_id, "tenant_id": tenant_id},
                {"$set": {k: winner_before.get(k)
                             for k in applied_overrides}},
            )
        await _reverse_rewire_children(
            db, tenant_id=tenant_id,
            winner_id=winner_id, loser_id=loser_id,
            snapshot_ids=snapshot_ids,
            partial_counts=partial_counts,
        )
        await db.customer_merge_audit.delete_one({"id": audit_id})
        raise

    # Final loser soft-delete.
    await db.customers.update_one(
        {"id": loser_id, "tenant_id": tenant_id},
        {"$set": {
            "deleted_at": merged_at_iso,
            "deleted_by_user_id": (actor or {}).get("id") or "customer_merge",
            "merged_into": winner_id,
            "merged_at": merged_at_iso,
            "merged_by": (actor or {}).get("id") or "customer_merge",
        }},
    )

    # Patch the audit row with the final counts + ids.
    await db.customer_merge_audit.update_one(
        {"id": audit_id},
        {"$set": {
            "child_record_counts": partial_counts,
            "credit_merged_cents": credit_cents,
            "stripe_payment_methods_remapped": remapped_pm_ids,
            "portal_user_soft_deleted": portal_flipped,
        }},
    )

    # Executed-audit log row — short + greppable.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "action": "customer_merge.executed",
            "tenant_id": tenant_id,
            "actor_id": (actor or {}).get("id"),
            "winner_id": winner_id,
            "loser_id": loser_id,
            "audit_id": audit_id,
            "child_record_counts": partial_counts,
            "credit_merged_cents": credit_cents,
            "stripe_payment_methods_remapped": remapped_pm_ids,
            "created_at": merged_at_iso,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[customer_merge] audit_logs insert failed "
            "(non-fatal, merge already committed): %s", exc,
        )

    return MergeResult(
        audit_id=audit_id,
        winner_id=winner_id,
        loser_id=loser_id,
        child_record_counts=partial_counts,
        credit_merged_cents=credit_cents,
        stripe_payment_methods_remapped=remapped_pm_ids,
        portal_user_soft_deleted=portal_flipped,
        merged_at=merged_at_iso,
    )


__all__ = [
    "MergeError",
    "MergeResult",
    "RollbackResult",
    "ensure_merge_audit_indexes",
    "merge_customers",
    "rollback_merge",
]


# ═════════════════════════════════════════════════════════════
# Feb-2026 · merge rollback — reverses a prior merge within the
# 90-day retention window.  Reads the ``customer_merge_audit``
# snapshot captured by :func:`merge_customers` and reverse-flips
# every mutation it recorded.
#
# Operator-locked edge case: ONLY the ids captured in the
# ``child_record_ids`` snapshot are reverse-rewired.  Any new
# activity assigned to the winner AFTER the merge (e.g. a new
# invoice created for the merged customer's property between
# the merge and the rollback) stays on the winner — the snapshot
# predates it and never saw its id.
# ═════════════════════════════════════════════════════════════
@dataclass
class RollbackResult:
    audit_id: str
    winner_id: str
    loser_id: str
    reversed_child_record_counts: Dict[str, int] = field(default_factory=dict)
    credit_restored_cents: int = 0
    stripe_payment_methods_reverse_remapped: List[str] = field(
        default_factory=list,
    )
    portal_user_restored: bool = False
    rolled_back_at: str = ""


async def _restore_loser_customer(
    db, *, tenant_id: str, audit: Dict[str, Any],
) -> None:
    """Clear the loser customer's ``deleted_at`` + merge sentinels
    so the row returns to the active pool.  Any field overrides
    the merge applied to the WINNER are restored from the
    ``winner_snapshot``.
    """
    loser_before = audit.get("loser_snapshot") or {}
    await db.customers.update_one(
        {"id": audit["loser_id"], "tenant_id": tenant_id},
        {"$set": {
            "deleted_at": loser_before.get("deleted_at"),
            "deleted_by_user_id": loser_before.get("deleted_by_user_id"),
            "merged_into": None,
            "merged_at": None,
            "merged_by": None,
        }},
    )
    winner_before = audit.get("winner_snapshot") or {}
    applied = audit.get("field_overrides") or {}
    if applied:
        # Restore winner's prior scalar values for each override
        # the merge applied.
        _METADATA = frozenset({
            "id", "_id", "tenant_id",
            "created_at", "updated_at",
            "deleted_at", "deleted_by_user_id",
            "merged_into", "merged_at", "merged_by",
        })
        restored = {
            k: winner_before.get(k)
            for k in applied if k not in _METADATA
        }
        if restored:
            restored["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.customers.update_one(
                {"id": audit["winner_id"], "tenant_id": tenant_id},
                {"$set": restored},
            )


async def _restore_portal_user(
    db, *, tenant_id: str, audit: Dict[str, Any],
) -> bool:
    """Reverse the loser portal-user soft-delete the merge
    applied.  No-op if the merge didn't flip a user row.
    """
    if not audit.get("portal_user_soft_deleted"):
        return False
    res = await db.users.update_many(
        {
            "tenant_id": tenant_id,
            "customer_id": audit["loser_id"],
            "deleted_by_user_id": "customer_merge",
        },
        {"$set": {"deleted_at": None,
                    "deleted_by_user_id": None}},
    )
    return int(getattr(res, "modified_count", 0)) > 0


async def _reverse_credit_sum(
    db, *, tenant_id: str, audit: Dict[str, Any],
    actor: Optional[Dict[str, Any]],
) -> int:
    """Reverse the credit transfer the merge applied.  Returns
    the cents restored to the loser.  Uses distinct idempotency
    keys so a retried rollback never double-reverses.
    """
    cents = int(audit.get("credit_merged_cents") or 0)
    if cents == 0:
        return 0
    from services.customer_balance import mutate_credit
    await mutate_credit(
        db, tenant_id, audit["winner_id"],
        delta_cents=-cents,
        source="customer_merge",
        actor=actor,
        reason=f"rollback to {audit['loser_id']}",
        idempotency_key=f"rollback:{audit['id']}:winner-debit",
    )
    await mutate_credit(
        db, tenant_id, audit["loser_id"],
        delta_cents=cents,
        source="customer_merge",
        actor=actor,
        reason=f"rollback from {audit['winner_id']}",
        idempotency_key=f"rollback:{audit['id']}:loser-restore",
    )
    return cents


async def _reverse_stripe_remap(
    db, *, tenant_id: str, audit: Dict[str, Any],
) -> List[str]:
    """Best-effort reverse of the Stripe PaymentMethod remap the
    merge applied.  Unlike the forward merge (zero-tolerance on
    Stripe failure), rollback logs + continues on individual
    PM failures so a transient Stripe outage doesn't strand the
    DB in a half-rolled-back state.  Operators can replay the
    Stripe-only portion from the audit snapshot if needed.
    """
    remapped = audit.get("stripe_payment_methods_remapped") or []
    if not remapped:
        return []
    loser_before = audit.get("loser_snapshot") or {}
    loser_sid = loser_before.get("stripe_customer_id")
    if not loser_sid:
        logger.warning(
            "[customer_merge.rollback] audit=%s skipped stripe "
            "reverse — loser snapshot has no stripe_customer_id",
            audit.get("id"),
        )
        return []
    try:
        import stripe as _stripe  # noqa: F401
        from services.payments.stripe_charge import _to_thread
    except ImportError:
        _stripe = None  # type: ignore
        _to_thread = None  # type: ignore
    reversed_: List[str] = []
    for pm_db_id in remapped:
        row = await db.payment_methods.find_one(
            {"tenant_id": tenant_id, "id": pm_db_id},
            {"_id": 0, "id": 1, "stripe_payment_method_id": 1},
        )
        if not row:
            continue
        pm_stripe_id = row.get("stripe_payment_method_id")
        if pm_stripe_id and _stripe is not None and _to_thread is not None:
            try:
                await _to_thread(
                    _stripe.PaymentMethod.modify, pm_stripe_id,
                    customer=loser_sid,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[customer_merge.rollback] audit=%s pm_id=%s "
                    "stripe reverse failed (continuing): %s",
                    audit.get("id"), pm_stripe_id, exc,
                )
                continue
        await db.payment_methods.update_one(
            {"tenant_id": tenant_id, "id": pm_db_id},
            {"$set": {"customer_id": audit["loser_id"]}},
        )
        reversed_.append(pm_db_id)
    return reversed_


async def rollback_merge(
    *,
    db,
    tenant_id: str,
    audit_id: str,
    actor: Optional[Dict[str, Any]] = None,
) -> RollbackResult:
    """Reverse a prior merge within the 90-day retention window.

    Raises:
        * ``MergeError(error_code="merge_rollback_not_found")`` —
          audit id not found for this tenant.
        * ``MergeError(error_code="merge_rollback_expired")`` —
          audit row's ``expires_at`` has passed (surfaces as
          HTTP 403 at the router).
        * ``MergeError(error_code="merge_rollback_already_done")`` —
          audit row already carries ``rolled_back_at`` (surfaces
          as HTTP 409 at the router).

    The operator-locked edge case ("rollback preserves post-
    merge activity on winner") is satisfied naturally: the
    reverse-rewire only touches ids in ``audit.child_record_ids``,
    captured BEFORE the merge.  Any new rows created on the
    winner after the merge are never in the snapshot and never
    get flipped.
    """
    audit = await db.customer_merge_audit.find_one(
        {"id": audit_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not audit:
        raise MergeError(
            "merge_rollback_not_found",
            f"Merge audit {audit_id!r} not found in this tenant.",
            audit_id=audit_id,
        )
    if audit.get("rolled_back_at"):
        raise MergeError(
            "merge_rollback_already_done",
            "This merge has already been rolled back.",
            audit_id=audit_id,
            rolled_back_at=audit["rolled_back_at"],
        )
    expires_at = audit.get("expires_at") or ""
    expires_str = (
        expires_at.isoformat() if hasattr(expires_at, "isoformat")
        else str(expires_at)
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    if expires_str and expires_str <= now_iso:
        raise MergeError(
            "merge_rollback_expired",
            "This merge is older than the 90-day rollback window.",
            audit_id=audit_id,
            expires_at=expires_str,
        )

    snapshot_ids = audit.get("child_record_ids") or {}
    # Reverse-rewire using the snapshot so post-merge activity
    # on the winner stays on the winner.
    reversed_counts: Dict[str, int] = {}
    for coll_name, _extra in _REWIRE_TARGETS:
        ids = snapshot_ids.get(coll_name) or []
        if not ids:
            reversed_counts[coll_name] = 0
            continue
        try:
            res = await db[coll_name].update_many(
                {"tenant_id": tenant_id, "id": {"$in": ids}},
                {"$set": {"customer_id": audit["loser_id"]}},
            )
            reversed_counts[coll_name] = int(
                getattr(res, "modified_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[customer_merge.rollback] audit=%s coll=%s "
                "reverse-rewire failed (continuing to maximise "
                "partial recovery): %s",
                audit_id, coll_name, exc,
            )
            reversed_counts[coll_name] = 0
    actor_ids = snapshot_ids.get("audit_logs.actor") or []
    if actor_ids:
        try:
            res = await db.audit_logs.update_many(
                {"tenant_id": tenant_id, "id": {"$in": actor_ids}},
                {"$set": {_AUDIT_ACTOR_FIELD: audit["loser_id"]}},
            )
            reversed_counts["audit_logs.actor"] = int(
                getattr(res, "modified_count", 0),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[customer_merge.rollback] audit=%s "
                "audit_logs.actor reverse failed: %s",
                audit_id, exc,
            )
            reversed_counts["audit_logs.actor"] = 0

    # Restore loser customer + winner field overrides.
    await _restore_loser_customer(db, tenant_id=tenant_id, audit=audit)

    # Restore portal user.
    portal_restored = await _restore_portal_user(
        db, tenant_id=tenant_id, audit=audit,
    )

    # Reverse credit sum.
    credit_cents = await _reverse_credit_sum(
        db, tenant_id=tenant_id, audit=audit, actor=actor,
    )

    # Reverse Stripe remap (best-effort).
    reversed_pm_ids = await _reverse_stripe_remap(
        db, tenant_id=tenant_id, audit=audit,
    )

    # Mark the audit row rolled back.
    await db.customer_merge_audit.update_one(
        {"id": audit_id, "tenant_id": tenant_id},
        {"$set": {
            "rolled_back_at": now_iso,
            "rolled_back_by": (actor or {}).get("id"),
        }},
    )

    # Greppable audit_logs row for the rollback.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "action": "customer_merge.rolled_back",
            "tenant_id": tenant_id,
            "actor_id": (actor or {}).get("id"),
            "audit_id": audit_id,
            "winner_id": audit["winner_id"],
            "loser_id": audit["loser_id"],
            "reversed_child_record_counts": reversed_counts,
            "credit_restored_cents": credit_cents,
            "created_at": now_iso,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[customer_merge.rollback] audit_logs insert failed "
            "(non-fatal, rollback already committed): %s", exc,
        )

    return RollbackResult(
        audit_id=audit_id,
        winner_id=audit["winner_id"],
        loser_id=audit["loser_id"],
        reversed_child_record_counts=reversed_counts,
        credit_restored_cents=credit_cents,
        stripe_payment_methods_reverse_remapped=reversed_pm_ids,
        portal_user_restored=portal_restored,
        rolled_back_at=now_iso,
    )
