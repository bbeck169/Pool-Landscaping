"""Feb-2026 · Multi-contact Phase-1 · migration HTTP endpoint.

Wraps :func:`services.customer_multi_contact.migrate_customer_multi_contact`
in an admin-only HTTP surface with dry-run + tenant-scope + count
reporting. The underlying function is idempotent and
``$exists=False``-guarded, so re-invocations are safe.

    POST /api/admin/migrations/customer-contacts-to-arrays
    Query:
      dry_run   : bool  (default True — no writes)
      tenant_id : str?  (None = all tenants)

    Response:
      {
        "dry_run": true|false,
        "scope": {"tenant_id": "..." | null},
        "candidates_scanned": N,
        "candidates_would_migrate": N,   (dry_run only)
        "migrated": N,                   (wet-run only)
        "elapsed_ms": N
      }

Auth: super_admin only. Non-super-admin → 403.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])


_SUPER_ADMIN_ROLES = {"super_admin", "owner"}


@router.post(
    "/admin/migrations/customer-contacts-to-arrays",
    operation_id="admin.customer_contacts_to_arrays",
)
async def customer_contacts_to_arrays(
    dry_run: bool = Query(True),
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Backfill ``customers.mobiles`` / ``customers.emails`` arrays
    from the scalar ``phone`` / ``email`` fields for legacy docs.
    """
    role = (user.get("role") or "").lower()
    if role not in _SUPER_ADMIN_ROLES:
        raise HTTPException(status_code=403,
                              detail="Super admin access required")

    from server import db
    from services.customer_multi_contact import (
        migrate_customer_multi_contact,
    )

    t0 = time.time()
    tenant_filter: Optional[Dict[str, Any]] = None
    if tenant_id:
        tenant_filter = {"tenant_id": tenant_id}

    # Cheap scan — count docs the underlying migration would touch.
    scan_q = dict(tenant_filter or {})
    scan_q["$or"] = [
        {"mobiles": {"$exists": False}},
        {"emails":  {"$exists": False}},
    ]
    candidates = await db.customers.count_documents(scan_q)

    if dry_run:
        # No writes — return the count so ops can size the wet-run.
        return {
            "dry_run": True,
            "scope": {"tenant_id": tenant_id},
            "candidates_scanned": candidates,
            "candidates_would_migrate": candidates,
            "migrated": 0,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }

    migrated = await migrate_customer_multi_contact(
        tenant_filter=tenant_filter,
    )
    return {
        "dry_run": False,
        "scope": {"tenant_id": tenant_id},
        "candidates_scanned": candidates,
        "migrated": migrated,
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
