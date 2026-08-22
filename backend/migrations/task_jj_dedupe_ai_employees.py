"""Phase 34 · Task JJ · Feb 2026 — AI Employees dedupe + integrity migration.

Root cause investigation (see the Task JJ investigation results in
the finish summary):

1. Two independent code paths inserted into ``db.ai_employees``:
   * ``routers/ai_ops.py::ensure_ai_employees_seeded`` inserted 9
     ``tenant_id=None`` rows for a legacy pre-multi-tenant seed.
   * ``routers/ai_employees.py::seed_ai_employees_for_tenant`` inserts
     10 tenant-scoped rows per tenant (the canonical seed).
2. ``GET /ai-ops/employees`` returned EVERY row across every tenant
   with no tenant filter → the admin `/ai-employees` UI listed the 9
   null-tenant legacy rows PLUS the current tenant's 10 tenant-scoped
   rows, showing 19+ "duplicate" personas.

The Task JJ code changes:
* ``ensure_ai_employees_seeded`` is now a no-op (kept for import
  stability).
* ``/ai-ops/employees`` and ``/ai-ops/employees/{eid}`` now filter by
  ``tenant_id``.
* This migration deletes the 9 legacy null-tenant rows once conversation
  references (if any) have been migrated to the tenant-scoped copy.
* A unique compound index ``(tenant_id, key)`` on ``ai_employees``
  guarantees the tenant-scoped seed can never insert a duplicate.

Idempotent. Safe to re-run.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db, logger


async def _migrate_conversation_refs(dropped_id: str, kept_id: str) -> int:
    """Repoint any ai_employee_conversations / ai_employee_messages
    rows that reference ``dropped_id`` to ``kept_id``. Returns the
    total number of rows updated."""
    total = 0
    for coll in ("ai_employee_conversations", "ai_employee_messages",
                    "ai_employee_actions"):
        try:
            res = await db[coll].update_many(
                {"employee_id": dropped_id},
                {"$set": {"employee_id": kept_id}},
            )
            total += (res.modified_count or 0)
        except Exception as e:                                   # noqa: BLE001
            logger.warning(f"[task-jj] repoint {coll} failed: {e}")
    return total


async def _drop_null_tenant_rows() -> tuple[int, int, List[Dict[str, Any]]]:
    """Phase 1 — delete every ``ai_employees`` row with ``tenant_id:
    None``.  Returns ``(dropped, refs_moved, merge_log_entries)``.

    Feb-2026 · P8 refactor — extracted from ``dedupe_ai_employees``
    unchanged from the pre-refactor behavior: best-effort repoint of
    conversation refs with ``kept_id=""`` (which effectively removes
    them from any tenant-scoped chat), then a hard delete, then a
    ``null_tenant_legacy`` audit entry appended to the merge log.
    """
    dropped = 0
    refs_moved = 0
    merge_log: List[Dict[str, Any]] = []
    async for row in db.ai_employees.find(
        {"tenant_id": None}, {"_id": 0, "id": 1, "slug": 1, "name": 1},
    ):
        rid = row.get("id")
        moved = await _migrate_conversation_refs(rid, kept_id="")
        refs_moved += moved
        await db.ai_employees.delete_one({"id": rid})
        dropped += 1
        merge_log.append({"tenant_id": None, "kind": "null_tenant_legacy",
                            "dropped_id": rid, "slug": row.get("slug"),
                            "name": row.get("name")})
    return dropped, refs_moved, merge_log


def _pick_survivor(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the row that wins a duplicate group.  Winner has the
    MOST non-null fields; tiebreak = ``updated_at`` DESCENDING (newest
    wins, matches the module docstring).  Rows with a NULL / empty
    ``updated_at`` sort LAST — they lose to any row with a real
    timestamp when field counts are otherwise tied.

    Feb-2026 · P8.5 — flipped ASC → DESC on ``updated_at`` per user
    directive.  Implemented as a two-pass stable sort so the secondary
    key can honour ``reverse=True`` independently of the primary key.
    """
    # Pass 1 (secondary): ``updated_at`` DESC, NULLs → "" → last.
    docs.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    # Pass 2 (primary): field-population count DESC; stable ordering
    # preserves the pass-1 tiebreak within each count bucket.
    docs.sort(key=lambda x: -sum(
        1 for v in x.values() if v not in (None, "", [], {})))
    return docs[0]


# Feb-2026 · P24 — fields that must survive a dedupe merge if the
# survivor's own copy is missing. Kept intentionally narrow — we only
# fill in values the survivor is *empty on*; we never overwrite a
# populated survivor field with a loser's value. Order does not
# matter; the first non-empty loser value wins per field.
_P24_PRESERVE_FIELDS = (
    "avatar_url",     # <-- the reported bug (persona portraits vanishing)
    "avatar_emoji",   # less critical but same class of loss
    "system_prompt",  # an admin-edited prompt shouldn't be lost if
                        #  it happened to only exist on a loser
    "read_access_scope",     # RR-scope config
    "brand_voice_snippet",   # T1 fix (AE1)
    "audience",
)


def _merge_preservable_fields(
    survivor: Dict[str, Any], all_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the ``$set`` dict for a fill-in-blanks merge from losers
    into the survivor. Never overwrites a value the survivor already
    has; empty-string and ``None`` on the survivor count as missing.
    """
    merged: Dict[str, Any] = {}
    for f in _P24_PRESERVE_FIELDS:
        current = survivor.get(f)
        if current not in (None, "", [], {}):
            continue
        for loser in all_docs:
            if loser.get("id") == survivor.get("id"):
                continue
            candidate = loser.get(f)
            if candidate not in (None, "", [], {}):
                merged[f] = candidate
                break
    return merged



async def _dedupe_within_tenant_groups() -> tuple[int, List[Dict[str, Any]]]:
    """Phase 2 — collapse ``(tenant_id, key)`` duplicate groups within
    each tenant. Returns ``(refs_moved, merge_log_entries)``.

    The aggregation pipeline, per-doc rehydration, sort key, ref
    repointing, delete ordering, and merge_log entry shape all match
    the pre-refactor implementation verbatim.
    """
    pipeline = [
        {"$match": {"tenant_id": {"$ne": None},
                     "key": {"$ne": None}}},
        {"$group": {"_id": {"tenant_id": "$tenant_id", "key": "$key"},
                     "count": {"$sum": 1},
                     "docs": {"$push": {"id": "$id",
                                             "updated_at": "$updated_at"}}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    refs_moved = 0
    merge_log: List[Dict[str, Any]] = []
    async for grp in db.ai_employees.aggregate(pipeline):
        docs = grp["docs"]
        full: List[Dict[str, Any]] = []
        for d in docs:
            doc = await db.ai_employees.find_one({"id": d["id"]}, {"_id": 0})
            if doc:
                full.append(doc)
        keep = _pick_survivor(full)
        # Feb-2026 · P24 — fill-in-blanks merge from losers → survivor
        # BEFORE deleting the losers. Prior behaviour dropped losers
        # whole, which meant an older row's ``avatar_url`` could be
        # lost forever if the newest-wins survivor happened not to
        # have one. Only fills fields that are None/empty on the
        # survivor; never overwrites populated survivor values.
        merged_fields = _merge_preservable_fields(keep, full)
        if merged_fields:
            await db.ai_employees.update_one(
                {"id": keep["id"]},
                {"$set": merged_fields},
            )
            keep.update(merged_fields)
        dropped_ids: List[str] = []
        for d in full:
            if d["id"] == keep["id"]:
                continue
            moved = await _migrate_conversation_refs(d["id"], keep["id"])
            refs_moved += moved
            await db.ai_employees.delete_one({"id": d["id"]})
            dropped_ids.append(d["id"])
        merge_log.append({
            "tenant_id": grp["_id"]["tenant_id"],
            "key": grp["_id"]["key"],
            "kept_id": keep["id"],
            "dropped_ids": dropped_ids,
            "merged_fields": sorted(merged_fields.keys()),
            "kind": "in_tenant_dupe",
        })
    return refs_moved, merge_log


async def _write_migration_log(*, before: int, null_tenant_dropped: int,
                                 merge_log: List[Dict[str, Any]],
                                 migrated_refs: int) -> None:
    """Phase 3 — best-effort insert into ``migration_log`` so admins
    can audit exactly which rows were dropped. Caller must only invoke
    when ``merge_log`` is non-empty (no-op runs must not persist a
    row — pinned by ``test_migration_log_written_only_when_work_happens``).
    """
    try:
        await db.migration_log.insert_one({
            "id": "task-jj-dedupe-" + str(before),
            "task": "task-jj-ai-employees-dedupe",
            "before": before,
            "after": await db.ai_employees.count_documents({}),
            "null_tenant_dropped": null_tenant_dropped,
            "in_tenant_merges": len([m for m in merge_log
                                            if m.get("kind") == "in_tenant_dupe"]),
            "migrated_refs": migrated_refs,
            "sample": merge_log[:20],
        })
    except Exception as e:                                       # noqa: BLE001
        logger.warning(f"[task-jj] migration_log write failed: {e}")


async def _ensure_unique_tenant_key_index() -> None:
    """Phase 4 — best-effort ``create_index`` for the compound unique
    ``(tenant_id, key)`` index. Idempotent — a repeat call is a no-op
    when the index already exists."""
    try:
        await db.ai_employees.create_index(
            [("tenant_id", 1), ("key", 1)],
            unique=True,
            partialFilterExpression={
                "tenant_id": {"$type": "string"},
                "key": {"$type": "string"},
            },
            name="phase34_task_jj_tenant_key_uniq",
        )
    except Exception as e:                                       # noqa: BLE001
        logger.warning(f"[task-jj] index install failed: {e}")


async def dedupe_ai_employees() -> Dict[str, Any]:
    """Task JJ — one-shot dedupe sweep.

    Deletes null-tenant legacy rows. For each duplicate group within a
    tenant, keeps the row with the most non-null fields (fallback
    ``updated_at DESC``) and repoints references before dropping the
    others. Records the operation in the ``migration_log`` collection
    so admins can audit exactly which rows were dropped.
    """
    before = await db.ai_employees.count_documents({})
    null_dropped, null_refs, null_log = await _drop_null_tenant_rows()
    dupe_refs, dupe_log = await _dedupe_within_tenant_groups()
    merge_log = null_log + dupe_log
    migrated_refs = null_refs + dupe_refs
    if merge_log:
        await _write_migration_log(
            before=before, null_tenant_dropped=null_dropped,
            merge_log=merge_log, migrated_refs=migrated_refs,
        )
    await _ensure_unique_tenant_key_index()
    result = {
        "before": before,
        "after": await db.ai_employees.count_documents({}),
        "null_tenant_dropped": null_dropped,
        "in_tenant_dupes_merged": len(
            [m for m in merge_log if m.get("kind") == "in_tenant_dupe"]),
        "conversation_refs_migrated": migrated_refs,
    }
    logger.info(f"[phase34-task-jj] ai_employees dedupe — {result}")
    return result
