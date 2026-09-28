"""HD-A · Immutable tombstone writer.

Every hard-purge (``POST /api/hard-delete/{entity_type}/{id}/purge``)
writes a snapshot of the doc-as-it-existed-at-purge-time to
``db.hard_delete_tombstones`` BEFORE the rows are deleted. The
collection is append-only — no update / delete paths exist through
this module.

Tombstone shape
---------------
::

    {
      "id":              <uuid>,           # tombstone row id
      "entity_type":     "customer" | "job" | ...,
      "entity_id":       <original doc id>,
      "tenant_id":       <tenant>,
      "purged_at":       "2026-02-17T…Z",  # ISO 8601 UTC
      "purged_by":       <user id>,
      "purged_by_email": <user email>,
      "purge_reason":    <optional string>,
      "checksum":        <sha256 hex of snapshot>,
      "snapshot":        <full doc, ObjectId stripped>,
      "cascade_batch_id": <batch id if any>,
      "external_refs":   [                  # non-blocking audit refs
        {"kind": "communication_send", "id": "..."},
        {"kind": "outbound_email",     "id": "..."},
        ...
      ]
    }

Notes:
* ``snapshot`` captures the doc AT PURGE TIME, not at soft-delete
  time. This is deliberate — the audit trail must reflect what
  actually left the DB, even if the doc was tampered with during
  the soft-delete window.
* ``checksum`` is deterministic: ``sha256(json.dumps(snapshot,
  sort_keys=True, default=str))``. Cheap forensic invariant — a
  tombstone whose stored ``snapshot`` hash disagrees with its
  ``checksum`` was modified after write.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from config import db
from utils import new_id, now_iso


def _sanitize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``doc`` with the ``_id`` BSON field removed.

    Mongo's ``ObjectId`` isn't JSON-serialisable and — more
    importantly — the ``_id`` will differ across environments even
    for the same logical row, which corrupts checksum stability.
    """
    if not isinstance(doc, dict):
        return {}
    out = dict(doc)
    out.pop("_id", None)
    return out


def compute_checksum(snapshot: Dict[str, Any]) -> str:
    """Deterministic SHA-256 of the snapshot payload."""
    payload = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def collect_external_refs(
    entity_type: str, entity_id: str, tenant_id: str,
) -> List[Dict[str, Any]]:
    """Gather non-blocking external references for the audit trail.

    Currently walks ``communication_sends`` and ``outbound_emails``
    — both are ledger tables the platform never soft-deletes, so
    they'd survive a purge and become "dangling refs". Logging
    them into the tombstone means auditors can trace which comms
    predated a purged entity.
    """
    refs: List[Dict[str, Any]] = []

    # ``communication_sends`` — cross-service comms ledger.
    try:
        async for row in db.communication_sends.find(
            {"tenant_id": tenant_id,
              "$or": [
                  {f"context.{entity_type}_id": entity_id},
                  {"related_id": entity_id},
              ]},
            {"_id": 0, "id": 1, "channel": 1, "created_at": 1},
        ):
            refs.append({"kind": "communication_send", **row})
    except Exception:                                              # noqa: BLE001
        # Collection may not exist in every environment — skip.
        pass

    # ``outbound_emails`` — email delivery log.
    try:
        async for row in db.outbound_emails.find(
            {"tenant_id": tenant_id,
              "$or": [
                  {f"context.{entity_type}_id": entity_id},
                  {"related_id": entity_id},
                  {f"{entity_type}_id": entity_id},
              ]},
            {"_id": 0, "id": 1, "subject": 1, "created_at": 1},
        ):
            refs.append({"kind": "outbound_email", **row})
    except Exception:                                              # noqa: BLE001
        pass

    return refs


async def write_tombstone(
    *,
    entity_type: str,
    entity_id: str,
    tenant_id: str,
    snapshot: Dict[str, Any],
    purged_by_user_id: Optional[str],
    purged_by_email: Optional[str],
    purge_reason: Optional[str] = None,
    cascade_batch_id: Optional[str] = None,
    external_refs: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Insert one immutable row into ``db.hard_delete_tombstones``.

    The caller controls the snapshot — this module never re-reads
    the source doc so a caller can capture pre-mutation state
    reliably.
    """
    clean = _sanitize(snapshot)
    checksum = compute_checksum(clean)
    row = {
        "id": new_id(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "purged_at": now_iso(),
        "purged_by": purged_by_user_id,
        "purged_by_email": purged_by_email,
        "purge_reason": purge_reason,
        "cascade_batch_id": cascade_batch_id,
        "checksum": checksum,
        "snapshot": clean,
        "external_refs": list(external_refs or []),
    }
    await db.hard_delete_tombstones.insert_one(row)
    # Drop the mongo-injected ``_id`` before echoing back so
    # callers don't leak the ObjectId into JSON responses.
    row.pop("_id", None)
    return row


async def find_tombstone(*, tenant_id: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Convenience read used by tests — returns the most recent
    tombstone for ``entity_id`` in ``tenant_id`` (or ``None``).
    """
    row = await db.hard_delete_tombstones.find_one(
        {"tenant_id": tenant_id, "entity_id": entity_id},
        {"_id": 0},
        sort=[("purged_at", -1)],
    )
    return row
