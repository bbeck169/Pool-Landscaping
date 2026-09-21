"""Feb 2026 · Customer Merge · Phase 1 — audit log writer.

Every executed merge (manual or auto, dry-run excluded) writes to
``customer_merge_audit``. Reversal fields are stamped at write-time
even though the reversal endpoint is deferred — that way we don't
schema-migrate the collection later.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db
from utils import new_id, now_iso


AUDIT_COLLECTION = "customer_merge_audit"


async def write_merge_audit(
    tenant_id: str,
    primary_id: str,
    secondary_ids: List[str],
    initiated_by: str,
    match_type: Optional[str],
    confidence: Optional[str],
    fields_reconciled: Dict[str, Any],
    empty_fields_filled: Dict[str, Any],
    related_records_rewired: Dict[str, int],
    # Phase M1 · Feb-2026 — extended snapshot fields for the manual
    # merge-wizard endpoint. Auto-merge callers still pass None and
    # the columns stay off the audit doc so the audit-viewer UI
    # continues to work unchanged.
    duplicate_snapshots: Optional[List[Dict[str, Any]]] = None,
    field_choices: Optional[Dict[str, str]] = None,
    merge_source: Optional[str] = None,
) -> str:
    """Insert one audit row. Returns the audit id."""
    aid = f"audit_{new_id()}"
    doc = {
        "id": aid,
        "tenant_id": tenant_id,
        "primary_id": primary_id,
        "secondary_ids": list(secondary_ids or []),
        "initiated_by": initiated_by or "unknown",
        "match_type": match_type,
        "confidence": confidence,
        "fields_reconciled": fields_reconciled or {},
        "empty_fields_filled": empty_fields_filled or {},
        "related_records_rewired": related_records_rewired or {},
        "created_at": now_iso(),
        "reversed_at": None,
        "reversed_by": None,
    }
    if duplicate_snapshots is not None:
        doc["duplicate_snapshots"] = duplicate_snapshots
    if field_choices is not None:
        doc["field_choices"] = dict(field_choices or {})
    if merge_source is not None:
        doc["merge_source"] = merge_source
    await db[AUDIT_COLLECTION].insert_one(doc)
    return aid


async def list_merge_audit(
    tenant_id: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Latest N audit rows for the tenant, newest first."""
    limit = max(1, min(int(limit or 100), 500))
    cur = db[AUDIT_COLLECTION].find(
        {"tenant_id": tenant_id},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    return await cur.to_list(limit)
