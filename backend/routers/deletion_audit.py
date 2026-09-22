"""Feb-2026 · Item 3 — Deletion audit + restore.

New collection ``db.deletion_audit`` stores a per-row snapshot every
time an invoice or payment is soft-deleted. The audit page (super_admin
only) reads from it, and the restore endpoint reverses the soft-delete
flip and reverses cascade side-effects.

Distinct from the legacy ``db.audit_log`` collection — that one is
kept for back-compat with existing consumers (analytics, older
report jobs). Both collections are written on every delete so no
downstream reader breaks.

Schema
------
    {
      id: str,                         # new_id()
      tenant_id: str,
      resource_type: "invoice"|"payment",
      resource_id: str,                # quotes._id equivalent
      action: "delete",                # "restore" written on undo
      user_id: str,
      user_email: str,
      timestamp: ISO string,
      snapshot: dict,                  # pre-delete row minus _id
      cascade_deleted_ids: list[str],  # empty in this codebase — the
                                       # payment IS the invoice; kept
                                       # for schema parity with the
                                       # user's Item-3 spec.
      deletion_reason: str | None,
      stripe_reconciliation_note: str | None,
    }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant


logger = logging.getLogger("deletion_audit")

router = APIRouter()

COLLECTION = "deletion_audit"


# ─────────────────────────────────────────────────────────────────────
# Writer — called by ``routers/quotes.py`` soft-delete helpers.
# ─────────────────────────────────────────────────────────────────────
async def write_deletion_audit_entry(
    *,
    tenant_id: str,
    resource_type: str,               # "invoice" | "payment" | "customer" | "lead"
    resource_id: str,
    user: Dict[str, Any],
    snapshot: Dict[str, Any],
    cascade_deleted_ids: Optional[List[str]] = None,
    deletion_reason: Optional[str] = None,
    stripe_reconciliation_note: Optional[str] = None,
    bulk_op_id: Optional[str] = None,
) -> str:
    """Persist a single deletion audit entry. Never blocks the caller
    on a write error — logs and returns an empty string on failure.

    Snapshot is truncated to a sane cap (strips ``_id`` if present).

    Feb-2026 · Customer Delete UX overhaul — ``"customer"`` accepted
    as a resource_type. Hard-delete of a customer row writes the
    full pre-delete snapshot (minus ``password_hash`` and
    ``password_reset_token`` — scrubbed by the caller) so forensic
    reconstruction is possible even though the row is gone from
    ``db.customers``. ``cascade_deleted_ids`` stays ``[]`` for
    customer because hard-delete never cascades — kept for schema
    parity with the invoice/payment shape.

    Phase P6 · Feb-2026 — ``"lead"`` accepted as a resource_type
    for the Leads bulk-hard-delete (POST /api/leads/bulk-hard-delete)
    AND the retrofitted single-row DELETE /api/leads/{lid}.
    ``bulk_op_id`` is an optional grouping key stamped on every row
    a bulk call writes — every row inside a single bulk request
    shares the same UUID so the group is queryable as a set.
    Legacy single-row callers pass ``None``.  Persisted verbatim
    into the audit doc so downstream analytics (the super-admin
    deletion viewer, forensic reconstruction) can filter.
    Phase P23 · Feb-2026 — ``"technician"`` accepted as a
    resource_type for the new ``DELETE /api/technicians/{id}``
    endpoint. Soft-delete (default) and force-reassign paths BOTH
    write a snapshot row here; the force path also writes one
    ``"job"`` row per reassigned job, sharing a ``bulk_op_id`` so
    the group is queryable as a set.
    """
    if resource_type not in ("invoice", "payment", "customer", "lead",
                              "recurring_job", "job", "master_service",
                              "technician"):
        raise ValueError(
            f"resource_type must be invoice|payment|customer|lead|"
            f"recurring_job|job|master_service|technician, got "
            f"{resource_type!r}"
        )
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": "delete",
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "timestamp": now_iso(),
        "snapshot": {k: v for k, v in (snapshot or {}).items() if k != "_id"},
        "cascade_deleted_ids": list(cascade_deleted_ids or []),
        "deletion_reason": deletion_reason,
        "stripe_reconciliation_note": stripe_reconciliation_note,
        "bulk_op_id": bulk_op_id,
    }
    try:
        await db[COLLECTION].insert_one(doc)
    except Exception as exc:  # noqa: BLE001 — never block the delete
        logger.warning("[deletion_audit] insert failed: %s", exc)
        return ""
    return doc["id"]


# ─────────────────────────────────────────────────────────────────────
# Route gate
# ─────────────────────────────────────────────────────────────────────
def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


# ─────────────────────────────────────────────────────────────────────
# GET /admin/audit/deletions
# ─────────────────────────────────────────────────────────────────────
@router.get("/admin/audit/deletions",
             operation_id="admin.audit.deletions.list")
async def list_deletions(
    resource_type: Optional[str] = Query(None,
        description="Filter by 'invoice' | 'payment'"),
    start: Optional[str] = Query(None,
        description="ISO date (inclusive) — timestamp >= start"),
    end: Optional[str] = Query(None,
        description="ISO date (inclusive) — timestamp <= end"),
    limit: int = Query(200, ge=1, le=1000),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    # Phase P6 · Feb-2026 — extend the filter allowlist to include
    # ``lead`` so the Leads bulk-hard-delete rows are retrievable
    # through the same super-admin viewer that already surfaces
    # invoice / payment deletions.  ``customer`` was already an
    # accepted resource_type on the writer but was silently
    # dropped from THIS filter's allowlist — including it here
    # closes that pre-existing gap by adjacency.
    if resource_type in ("invoice", "payment", "customer", "lead"):
        q["resource_type"] = resource_type
    if start or end:
        ts_q: Dict[str, str] = {}
        if start:
            ts_q["$gte"] = start
        if end:
            # inclusive upper bound; strings are ISO so lexicographic
            # ordering works.
            ts_q["$lte"] = end
        q["timestamp"] = ts_q
    rows = await db[COLLECTION].find(q, {"_id": 0}).sort(
        "timestamp", -1,
    ).to_list(limit)
    return {"count": len(rows), "rows": rows}


# ─────────────────────────────────────────────────────────────────────
# POST /admin/audit/deletions/{id}/restore
# ─────────────────────────────────────────────────────────────────────
@router.post("/admin/audit/deletions/{aid}/restore",
              operation_id="admin.audit.deletions.restore")
async def restore_deletion(aid: str,
                           user: Dict[str, Any] = Depends(get_current_user),
                           tenant: Dict[str, Any] = Depends(get_current_tenant)):
    """Reverse a soft-delete recorded in the audit log.

    * For ``invoice`` — clears ``deleted_at`` / ``deleted_by_user_id``
      on ``db.quotes``.
    * For ``payment`` — restores the pre-delete ``payment_status`` +
      ``amount_paid`` from the snapshot and clears
      ``payment_deleted_at``.
    """
    _require_super_admin(user)
    entry = await db[COLLECTION].find_one(
        {"id": aid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not entry:
        raise HTTPException(404, "audit_entry_not_found")
    resource_type = entry.get("resource_type")
    resource_id = entry.get("resource_id")
    snapshot = entry.get("snapshot") or {}

    if resource_type == "invoice":
        r = await db.quotes.update_one(
            {"id": resource_id, "tenant_id": tenant["id"]},
            {"$set": {
                "deleted_at": None,
                "deleted_by_user_id": None,
                "restored_at": now_iso(),
                "restored_by_user_id": user.get("id"),
            }},
        )
        if not getattr(r, "matched_count", 0):
            raise HTTPException(404, "invoice_not_found_for_restore")
        # Also restore any cascade-deleted payments recorded on the
        # entry. In this codebase the payment IS the invoice, so
        # cascade_deleted_ids is normally empty — but any historical
        # entry that carries ids gets a best-effort revert.
        for cid in entry.get("cascade_deleted_ids") or []:
            try:
                await db.quotes.update_one(
                    {"id": cid, "tenant_id": tenant["id"]},
                    {"$set": {"payment_deleted_at": None,
                                "payment_deleted_by_user_id": None}},
                )
            except Exception:                       # noqa: BLE001
                pass
    elif resource_type == "payment":
        # Restore the pre-delete payment_status + amount_paid from
        # the snapshot; if the snapshot is missing (very old entry),
        # fall back to marking as ``paid`` with existing amounts.
        restore_status = snapshot.get("payment_status") or "paid"
        restore_amount = float(snapshot.get("amount_paid") or 0)
        r = await db.quotes.update_one(
            {"id": resource_id, "tenant_id": tenant["id"]},
            {"$set": {
                "payment_status": restore_status,
                "amount_paid": restore_amount,
                "paid_at": snapshot.get("paid_at") or now_iso(),
                "payment_deleted_at": None,
                "payment_deleted_by_user_id": None,
                "restored_at": now_iso(),
                "restored_by_user_id": user.get("id"),
            }},
        )
        if not getattr(r, "matched_count", 0):
            raise HTTPException(404, "payment_not_found_for_restore")
    else:
        raise HTTPException(400, f"unknown_resource_type:{resource_type}")

    # Write a mirror audit entry with action='restore' so the trail
    # is bidirectional.
    try:
        restore_doc = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": "restore",
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "timestamp": now_iso(),
            "restored_from_audit_id": aid,
        }
        await db[COLLECTION].insert_one(restore_doc)
    except Exception as exc:                          # noqa: BLE001
        logger.warning("[deletion_audit] restore audit failed: %s", exc)

    return {"ok": True, "restored_id": resource_id,
              "resource_type": resource_type}
