"""HD-A · Cascade PREVIEW helper — computes descendant counts +
external refs without any side effects.

Used by the FE ``preview-cascade`` endpoint so an admin sees
exactly what a ``/soft`` call will affect before confirming.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db

from .cascade import _find_blocking_stripe_refs
from .registry import EntitySpec, get_spec


async def _walk_family_counts(
    spec: EntitySpec, doc_id: str, tenant_id: str,
    counts: Dict[str, int],
    visited: set,
) -> None:
    for rule in spec.children_specs:
        child_spec = get_spec(rule.entity_type)
        if not child_spec:
            continue
        cursor = db[rule.collection].find(
            {rule.parent_field: doc_id, "tenant_id": tenant_id,
              # Only count NOT-already-soft-deleted rows in the preview
              # — those are what a fresh /soft call would touch.
              "$or": [
                  {"deleted_at": None},
                  {"deleted_at": {"$exists": False}},
                  {"is_deleted": False},
              ]},
            {"_id": 0, "id": 1, "photos": 1},
        )
        async for row in cursor:
            key = (rule.collection, row["id"])
            if key in visited:
                continue
            visited.add(key)
            counts[rule.collection] = counts.get(rule.collection, 0) + 1
            # Bookkeeping — embedded photos live inside job.photos[] +
            # service_reports.photos[]. Bubble them up as a
            # convenience count so the modal can render "N photos".
            embedded = row.get("photos") or []
            if embedded:
                counts["photos"] = counts.get("photos", 0) + len(embedded)
            await _walk_family_counts(
                child_spec, row["id"], tenant_id, counts, visited,
            )


async def preview_cascade(
    entity_type: str, doc_id: str, tenant_id: str,
) -> Dict[str, Any]:
    """Return counts + external refs for a doc's cascade WITHOUT
    mutating any state.
    """
    spec = get_spec(entity_type)
    if not spec:
        return {"error_code": "unsupported_entity_type",
                "entity_type": entity_type}

    root = await db[spec.collection].find_one(
        {"id": doc_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1,
        "deleted_at": 1, "photos": 1},
    )
    if not root:
        return {"error_code": "not_found",
                "entity_type": entity_type, "id": doc_id}

    counts: Dict[str, int] = {}
    visited: set = {(spec.collection, doc_id)}
    # Include embedded photos on the root itself if any.
    if root.get("photos"):
        counts["photos"] = len(root["photos"])
    await _walk_family_counts(spec, doc_id, tenant_id, counts, visited)

    # External refs — leverage the same walker the purge uses, but
    # cascade.py's helper needs the exact spec.
    external_refs: List[Dict[str, Any]] = await _find_blocking_stripe_refs(
        spec, doc_id, tenant_id,
    )

    return {
        "entity_type": entity_type,
        "id": doc_id,
        "already_soft_deleted": bool(root.get("deleted_at")),
        "child_counts": counts,
        "external_refs": external_refs,
        "would_block_purge": bool(external_refs),
    }
