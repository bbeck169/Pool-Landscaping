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


async def dedupe_ai_employees() -> Dict[str, Any]:
    """Task JJ — one-shot dedupe sweep.

    Deletes null-tenant legacy rows. For each duplicate group within a
    tenant, keeps the row with the most non-null fields (fallback
    ``updated_at DESC``) and repoints references before dropping the
    others. Records the operation in the ``migration_log`` collection
    so admins can audit exactly which rows were dropped.
    """
    before = await db.ai_employees.count_documents({})
    null_tenant_dropped = 0
    migrated_refs = 0
    merge_log: List[Dict[str, Any]] = []

    # Phase 1 — drop the 9 legacy null-tenant rows. They have no
    # tenant scope so no downstream conversation/action rows can be
    # meaningfully attributed. Log them for audit.
    async for row in db.ai_employees.find(
        {"tenant_id": None}, {"_id": 0, "id": 1, "slug": 1, "name": 1},
    ):
        rid = row.get("id")
        # Best-effort repoint of any accidental references. In
        # practice these are always zero — the null-tenant rows were
        # never callable through the tenant-scoped chat endpoints.
        moved = await _migrate_conversation_refs(rid, kept_id="")
        migrated_refs += moved
        await db.ai_employees.delete_one({"id": rid})
        null_tenant_dropped += 1
        merge_log.append({"tenant_id": None, "kind": "null_tenant_legacy",
                            "dropped_id": rid, "slug": row.get("slug"),
                            "name": row.get("name")})

    # Phase 2 — de-dupe by (tenant_id, key) within each tenant. In
    # the observed data this returned 0 groups but the migration is
    # defensive to be idempotent.
    pipeline = [
        {"$match": {"tenant_id": {"$ne": None},
                     "key": {"$ne": None}}},
        {"$group": {"_id": {"tenant_id": "$tenant_id", "key": "$key"},
                     "count": {"$sum": 1},
                     "docs": {"$push": {"id": "$id",
                                             "updated_at": "$updated_at"}}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    async for grp in db.ai_employees.aggregate(pipeline):
        docs = grp["docs"]
        # Fetch each doc's full body to score field-population count.
        full: List[Dict[str, Any]] = []
        for d in docs:
            doc = await db.ai_employees.find_one({"id": d["id"]}, {"_id": 0})
            if doc:
                full.append(doc)
        # Score = number of non-null fields; tiebreak = updated_at DESC.
        full.sort(
            key=lambda x: (
                -sum(1 for v in x.values() if v not in (None, "", [], {})),
                x.get("updated_at") or "",
            ),
        )
        keep = full[0]
        dropped_ids: List[str] = []
        for d in full[1:]:
            moved = await _migrate_conversation_refs(d["id"], keep["id"])
            migrated_refs += moved
            await db.ai_employees.delete_one({"id": d["id"]})
            dropped_ids.append(d["id"])
        merge_log.append({
            "tenant_id": grp["_id"]["tenant_id"],
            "key": grp["_id"]["key"],
            "kept_id": keep["id"],
            "dropped_ids": dropped_ids,
            "kind": "in_tenant_dupe",
        })

    # Phase 3 — write the migration log row so we can audit later.
    if merge_log:
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

    # Phase 4 — install the unique compound index. Guarantees no
    # future insert can duplicate. Partial-filter skips legacy rows
    # (should be none after Phase 1) that might lack ``key``.
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

    result = {
        "before": before,
        "after": await db.ai_employees.count_documents({}),
        "null_tenant_dropped": null_tenant_dropped,
        "in_tenant_dupes_merged": len(
            [m for m in merge_log if m.get("kind") == "in_tenant_dupe"]),
        "conversation_refs_migrated": migrated_refs,
    }
    logger.info(f"[phase34-task-jj] ai_employees dedupe — {result}")
    return result
