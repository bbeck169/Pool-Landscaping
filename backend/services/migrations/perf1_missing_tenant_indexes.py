"""PERF-1 · Feb-2026 — Missing ``tenant_id`` indexes on hot collections.

Sentinel: ``perf1_missing_tenant_indexes_v1``.  Idempotent +
sentinel-guarded. Creates ``(tenant_id, 1)`` compound index on six
collections that the pre-serve boot path fans out against per-tenant.

Audit finding
-------------
Fresh audit on Feb-2026 showed all six collections carried ONLY the
implicit ``_id_`` index.  The largest offender by far is
``service_checklists`` at **553,388 docs** — every pre-serve
per-tenant lookup was a full-collection scan.  Adding
``(tenant_id, 1)`` reduces those lookups to index-anchored scans.

Collections indexed (name, index name, doc-count at audit)
    * ``leads``                                       (22 docs)
    * ``form_submissions``                            (3 docs)
    * ``marketing_templates``                         (3,849 docs)
    * ``marketing_sequences``                         (811 docs)
    * ``customer_categories``                         (1,434 docs)
    * ``service_checklists``                          (553,388 docs)

Small collections still get the index — cheap to create, matches the
"consistent hot-collection index policy" the rest of the codebase
uses, and future growth stays index-anchored.

Runs from boot (guarded by ``RUN_STARTUP_INDEXES`` and by the
sentinel). Force-run via the super_admin admin-migrations endpoint if
you ever need to re-run against a re-hydrated preview DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db


logger = logging.getLogger("perf1_missing_tenant_indexes_migration")

_SENTINEL_ID = "perf1_missing_tenant_indexes_v1"

# Each entry: (collection_name, index_name).  Index name is
# deterministic so we can look it up cheaply in ``list_indexes``.
_TARGETS: List[tuple[str, str]] = [
    ("leads",                 "perf1_leads_tenant_idx"),
    ("form_submissions",      "perf1_form_submissions_tenant_idx"),
    ("marketing_templates",   "perf1_marketing_templates_tenant_idx"),
    ("marketing_sequences",   "perf1_marketing_sequences_tenant_idx"),
    ("customer_categories",   "perf1_customer_categories_tenant_idx"),
    ("service_checklists",    "perf1_service_checklists_tenant_idx"),
]


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one({"id": _SENTINEL_ID}, {"_id": 0})


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


async def run_perf1_missing_tenant_indexes_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the six ``(tenant_id, 1)`` indexes if missing.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "indexes_created": <int>,
             "already_present": <int>,
             "errors": [...],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {"status": "skipped",
                    "reason": "sentinel_present",
                    "sentinel": sentinel}

    summary: Dict[str, Any] = {
        "indexes_created": 0,
        "already_present": 0,
        "errors": [],
        "targets": [],
    }

    for coll_name, idx_name in _TARGETS:
        target_result: Dict[str, Any] = {
            "collection": coll_name, "index": idx_name,
        }
        try:
            existing = set()
            async for idx in db[coll_name].list_indexes():
                existing.add(idx.get("name") or "")
            if idx_name in existing:
                target_result["status"] = "already_present"
                summary["already_present"] += 1
            else:
                # background=True is preserved (the driver still
                # honors it under the covers on 4.2+ engines even
                # though it's a no-op — kept for readers).
                await db[coll_name].create_index(
                    [("tenant_id", 1)],
                    name=idx_name,
                    background=True,
                )
                target_result["status"] = "created"
                summary["indexes_created"] += 1
        except Exception as exc:                                    # noqa: BLE001
            target_result["status"] = "error"
            target_result["error"] = str(exc)
            summary["errors"].append(target_result)
            logger.warning(
                "[perf1] index %s.%s failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target_result)

    if not summary["errors"]:
        await _write_sentinel(summary)

    logger.info(
        "[perf1] indexes_created=%s already_present=%s errors=%s",
        summary["indexes_created"], summary["already_present"],
        len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
