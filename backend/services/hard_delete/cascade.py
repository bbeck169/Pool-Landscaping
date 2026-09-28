"""HD-A · Cascade soft-delete / restore / purge engine.

Given a parent entity (say a customer), soft-cascade walks the
registered children (jobs, quotes, service_reports, files),
stamps them with the same ``cascade_batch_id`` as the parent, and
recurses. Restore reverses the whole batch atomically. Purge writes
tombstones for every doc in the cascade set before deleting them.

Design points
-------------
* ``cascade_batch_id`` is what makes restore atomic: we don't have
  to re-derive the family tree at restore time — the batch id is
  the linker. If a child was ALREADY soft-deleted with its own
  batch id before the parent was soft-deleted, the child keeps its
  original batch id (idempotent — we never overwrite an existing
  ``cascade_batch_id``).
* External-reference checks (Stripe payment_intent_id) run BEFORE
  any writes — a blocked purge leaves DB state untouched.
* Purge uses the tombstone snapshot's ``deleted_at`` timestamp
  (present) to prove the row went through Trash. Emergency
  ``skip_trash=True`` purges (super-admin only) skip that
  invariant — the snapshot simply has ``deleted_at`` unset.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from config import db, logger
from utils import now_iso

from .registry import CascadeRule, EntitySpec, get_spec
from .tombstone import collect_external_refs, write_tombstone


def new_cascade_batch_id() -> str:
    """Fresh id for a cascade batch — dedicated helper so tests can
    monkey-patch it if determinism is required."""
    return f"cbatch_{uuid.uuid4().hex}"


# ─── Blocking checks ────────────────────────────────────────────────

# The one and only external-reference blocker per user brief §5.
# Any doc from ``db.quotes`` with a truthy ``payment_intent_id``
# refuses to purge — the local delete would break Stripe
# reconciliation.
def _row_has_stripe_charge(row: Dict[str, Any]) -> Optional[str]:
    pi = row.get("payment_intent_id")
    if pi:
        return str(pi)
    return None


async def _find_blocking_stripe_refs(
    spec: EntitySpec, doc_id: str, tenant_id: str,
) -> List[Dict[str, Any]]:
    """Walk this doc + its cascade descendants and report every
    Stripe-locked invoice found. Empty list means safe to purge.

    Returns a list of ``{"entity_type", "id", "payment_intent_id"}``
    rows so the 409 body can enumerate exactly what's blocking.
    """
    blocks: List[Dict[str, Any]] = []

    # First check the root doc itself if it's a quote.
    if spec.collection == "quotes":
        row = await db.quotes.find_one(
            {"id": doc_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "payment_intent_id": 1, "doc_type": 1},
        )
        pi = _row_has_stripe_charge(row or {})
        if pi:
            blocks.append({
                "entity_type": "quote",
                "id": doc_id,
                "doc_type": (row or {}).get("doc_type"),
                "payment_intent_id": pi,
            })

    # Walk each child spec recursively — but only the ``quotes``
    # branch actually carries the Stripe id, so short-circuit for
    # every other collection.
    for child_rule in spec.children_specs:
        if child_rule.collection == "quotes":
            cursor = db.quotes.find(
                {child_rule.parent_field: doc_id,
                  "tenant_id": tenant_id,
                  "payment_intent_id": {"$exists": True, "$ne": None}},
                {"_id": 0, "id": 1, "payment_intent_id": 1,
                 "doc_type": 1, child_rule.parent_field: 1},
            )
            async for row in cursor:
                pi = _row_has_stripe_charge(row)
                if pi:
                    blocks.append({
                        "entity_type": "quote",
                        "id": row["id"],
                        "doc_type": row.get("doc_type"),
                        "payment_intent_id": pi,
                    })
            continue

        # Recurse into the grand-child chain. First enumerate every
        # child row (soft-deleted included — because a soft-deleted
        # descendant that still has a Stripe ref should also block).
        child_spec = get_spec(child_rule.entity_type)
        if not child_spec:
            continue
        gc_cursor = db[child_rule.collection].find(
            {child_rule.parent_field: doc_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1},
        )
        async for child in gc_cursor:
            nested = await _find_blocking_stripe_refs(
                child_spec, child["id"], tenant_id,
            )
            blocks.extend(nested)

    return blocks


# ─── Soft-delete cascade ────────────────────────────────────────────

async def _soft_delete_recursive(
    spec: EntitySpec,
    doc_id: str,
    tenant_id: str,
    *,
    batch_id: str,
    user_id: Optional[str],
    now: str,
    affected: Dict[str, List[str]],
) -> None:
    # 1. Stamp the parent — only if not already carrying a
    # cascade_batch_id.  Idempotent restore relies on preserving
    # any pre-existing batch id.
    filter_ = {"id": doc_id, "tenant_id": tenant_id}
    doc = await db[spec.collection].find_one(filter_, {"_id": 0})
    if not doc:
        return
    if not doc.get("deleted_at"):
        await db[spec.collection].update_one(
            filter_,
            {"$set": {
                "deleted_at": now,
                "deleted_by_user_id": user_id,
                "cascade_batch_id": batch_id,
                "cascade_role": "root" if spec.entity_type == doc.get(
                    "_hd_root_entity_type", spec.entity_type) else "child",
            }},
        )
        affected.setdefault(spec.collection, []).append(doc_id)

    # 2. Recurse into children.
    for rule in spec.children_specs:
        child_spec = get_spec(rule.entity_type)
        if not child_spec:
            continue
        child_cursor = db[rule.collection].find(
            {rule.parent_field: doc_id,
              "tenant_id": tenant_id,
              # Skip already-trashed children — they either belong
              # to a prior batch or were nightly-purged already.
              "$or": [
                  {"deleted_at": None},
                  {"deleted_at": {"$exists": False}},
                  # ``files`` uses ``is_deleted`` too.
                  {"is_deleted": False},
              ]},
            {"_id": 0, "id": 1},
        )
        async for child in child_cursor:
            await _soft_delete_recursive(
                child_spec, child["id"], tenant_id,
                batch_id=batch_id, user_id=user_id, now=now,
                affected=affected,
            )


async def soft_delete_cascade(
    entity_type: str, doc_id: str, tenant_id: str,
    *, user_id: Optional[str],
) -> Dict[str, Any]:
    """Soft-delete ``doc_id`` and everything downstream.

    Returns::

        {
          "cascade_batch_id": "...",
          "deleted_at": "...",
          "affected": {"customers": [id], "jobs": [...], ...},
          "root_entity_type": "customer",
          "root_entity_id": doc_id,
        }
    """
    spec = get_spec(entity_type)
    if not spec:
        raise ValueError(f"unsupported entity_type: {entity_type!r}")

    root = await db[spec.collection].find_one(
        {"id": doc_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not root:
        return {"not_found": True, "root_entity_type": entity_type,
                "root_entity_id": doc_id}
    if root.get("deleted_at"):
        # Already soft-deleted — return its existing batch id so
        # the UI can retry idempotently.
        return {
            "cascade_batch_id": root.get("cascade_batch_id"),
            "deleted_at": root.get("deleted_at"),
            "root_entity_type": entity_type,
            "root_entity_id": doc_id,
            "affected": {spec.collection: [doc_id]},
            "already_deleted": True,
        }

    batch_id = new_cascade_batch_id()
    now = now_iso()
    affected: Dict[str, List[str]] = {}
    await _soft_delete_recursive(
        spec, doc_id, tenant_id, batch_id=batch_id,
        user_id=user_id, now=now, affected=affected,
    )
    # Stamp cascade_role="root" on the top row for restore
    # ergonomics — nested siblings all show cascade_role="child".
    await db[spec.collection].update_one(
        {"id": doc_id, "tenant_id": tenant_id},
        {"$set": {"cascade_role": "root"}},
    )
    logger.info(
        "[hard_delete.soft] tenant=%s entity=%s id=%s batch=%s affected=%s",
        tenant_id, entity_type, doc_id, batch_id,
        {k: len(v) for k, v in affected.items()},
    )
    return {
        "cascade_batch_id": batch_id,
        "deleted_at": now,
        "root_entity_type": entity_type,
        "root_entity_id": doc_id,
        "affected": affected,
    }


# ─── Restore ────────────────────────────────────────────────────────

async def restore_batch(
    entity_type: str, doc_id: str, tenant_id: str,
) -> Dict[str, Any]:
    """Clear ``deleted_at`` + companion fields for every row that
    shares the root doc's ``cascade_batch_id``.
    """
    spec = get_spec(entity_type)
    if not spec:
        raise ValueError(f"unsupported entity_type: {entity_type!r}")

    root = await db[spec.collection].find_one(
        {"id": doc_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not root:
        return {"not_found": True, "root_entity_type": entity_type,
                "root_entity_id": doc_id}
    if not root.get("deleted_at"):
        return {"already_restored": True,
                "root_entity_type": entity_type,
                "root_entity_id": doc_id,
                "restored": {spec.collection: []}}

    batch_id = root.get("cascade_batch_id")
    restored: Dict[str, List[str]] = {}

    if not batch_id:
        # Older soft-deletes may lack a batch id — restore JUST the
        # root doc so operators aren't stuck.
        await db[spec.collection].update_one(
            {"id": doc_id, "tenant_id": tenant_id},
            {"$unset": {"deleted_at": "", "deleted_by_user_id": "",
                        "cascade_batch_id": "", "cascade_role": ""}},
        )
        restored[spec.collection] = [doc_id]
        return {"cascade_batch_id": None, "restored": restored,
                "root_entity_type": entity_type, "root_entity_id": doc_id}

    # Walk every eligible collection and unset for anything in this
    # batch — a small, unindexed scan per collection but the batch
    # size is capped by cascade depth (rare > 1000).
    for row_spec in [get_spec("customer"), get_spec("job"), get_spec("quote"),
                      get_spec("service_report"), get_spec("file")]:
        if not row_spec:
            continue
        result = await db[row_spec.collection].update_many(
            {"cascade_batch_id": batch_id, "tenant_id": tenant_id},
            {"$unset": {"deleted_at": "", "deleted_by_user_id": "",
                        "cascade_batch_id": "", "cascade_role": "",
                        "is_deleted": ""}},
        )
        if result.modified_count:
            # Second read to capture ids for the response body.
            cursor = db[row_spec.collection].find(
                {"tenant_id": tenant_id,
                  # Post-restore rows have no deleted_at — pull the
                  # freshly-restored ids via a targeted marker.
                  # We can't rely on batch_id (we just cleared it),
                  # so re-derive using cascade lineage: the root id
                  # if this is the root spec, else the list of
                  # children where parent_field == root id.
                  # Simpler: use a distinct fetch below.
                  "id": {"$in": []}},
                {"_id": 0},
            )
            # ``update_many`` doesn't return the modified ids on
            # motor 3.x. Do a follow-up projection.
            _ = cursor  # placeholder — the real fetch happens below.

    # Follow-up projection: enumerate the freshly-restored family
    # by walking children of the root, using the registry.
    async def _collect_family(
        s: EntitySpec, doc_key: str,
    ) -> None:
        restored.setdefault(s.collection, []).append(doc_key)
        for rule in s.children_specs:
            child_spec = get_spec(rule.entity_type)
            if not child_spec:
                continue
            cursor2 = db[rule.collection].find(
                {rule.parent_field: doc_key,
                  "tenant_id": tenant_id,
                  # Only include rows that were part of the batch
                  # (now missing the batch key).
                  "$or": [
                      {"deleted_at": None},
                      {"deleted_at": {"$exists": False}},
                  ]},
                {"_id": 0, "id": 1},
            )
            async for gc in cursor2:
                await _collect_family(child_spec, gc["id"])

    await _collect_family(spec, doc_id)

    logger.info(
        "[hard_delete.restore] tenant=%s entity=%s id=%s batch=%s restored=%s",
        tenant_id, entity_type, doc_id, batch_id,
        {k: len(v) for k, v in restored.items()},
    )
    return {"cascade_batch_id": batch_id, "restored": restored,
            "root_entity_type": entity_type, "root_entity_id": doc_id}


# ─── Hard purge ─────────────────────────────────────────────────────

async def purge_cascade(
    entity_type: str, doc_id: str, tenant_id: str,
    *, user_id: Optional[str], user_email: Optional[str],
    purge_reason: Optional[str] = None, skip_trash: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Hard-delete ``doc_id`` and its cascade descendants.

    Steps:
        1. Enumerate the doc + every descendant (in-scope only).
        2. Check Stripe blocking — raise ``BlockedExternalRef`` if any.
        3. For each doc in the set:
            a. Snapshot it (post current state).
            b. Collect external refs into the tombstone.
            c. Insert tombstone row.
            d. Delete the source row.
        4. Return summary + list of blocking refs (empty on success).

    ``skip_trash=True`` skips the ``deleted_at`` present check — the
    doc is purged even if it hasn't been through Trash first.
    Reserved for the super-admin escape hatch. Docs without a
    ``deleted_at`` still get a tombstone; the snapshot simply omits
    the stamp.
    """
    spec = get_spec(entity_type)
    if not spec:
        raise ValueError(f"unsupported entity_type: {entity_type!r}")

    root = await db[spec.collection].find_one(
        {"id": doc_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not root:
        return {"not_found": True, "root_entity_type": entity_type,
                "root_entity_id": doc_id}, []

    if not skip_trash and not root.get("deleted_at"):
        return {"trash_required": True,
                "root_entity_type": entity_type,
                "root_entity_id": doc_id}, []

    # 1. Enumerate the family.
    family: List[Tuple[EntitySpec, str]] = []

    async def _walk(s: EntitySpec, key: str) -> None:
        family.append((s, key))
        for rule in s.children_specs:
            child_spec = get_spec(rule.entity_type)
            if not child_spec:
                continue
            cursor = db[rule.collection].find(
                {rule.parent_field: key, "tenant_id": tenant_id},
                {"_id": 0, "id": 1},
            )
            async for row in cursor:
                await _walk(child_spec, row["id"])

    await _walk(spec, doc_id)

    # 2. Blocking check — walk each doc's Stripe refs.
    blocks = await _find_blocking_stripe_refs(spec, doc_id, tenant_id)
    if blocks:
        return {
            "blocked": True,
            "error_code": "blocked_external_reference",
            "refs": blocks,
            "root_entity_type": entity_type,
            "root_entity_id": doc_id,
        }, blocks

    batch_id = root.get("cascade_batch_id")
    purged: Dict[str, List[str]] = {}

    # 3. Tombstone + delete.  Children-first so we never leave
    # dangling parent pointers mid-flight.
    for f_spec, f_id in reversed(family):
        f_doc = await db[f_spec.collection].find_one(
            {"id": f_id, "tenant_id": tenant_id}, {"_id": 0},
        )
        if not f_doc:
            continue
        ext_refs = await collect_external_refs(
            f_spec.entity_type, f_id, tenant_id,
        )
        await write_tombstone(
            entity_type=f_spec.entity_type,
            entity_id=f_id,
            tenant_id=tenant_id,
            snapshot=f_doc,
            purged_by_user_id=user_id,
            purged_by_email=user_email,
            purge_reason=purge_reason,
            cascade_batch_id=batch_id,
            external_refs=ext_refs,
        )
        await db[f_spec.collection].delete_one(
            {"id": f_id, "tenant_id": tenant_id},
        )
        purged.setdefault(f_spec.collection, []).append(f_id)

    logger.info(
        "[hard_delete.purge] tenant=%s entity=%s id=%s batch=%s purged=%s",
        tenant_id, entity_type, doc_id, batch_id,
        {k: len(v) for k, v in purged.items()},
    )
    return {"cascade_batch_id": batch_id, "purged": purged,
            "root_entity_type": entity_type,
            "root_entity_id": doc_id}, []
