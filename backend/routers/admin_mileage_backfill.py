"""P1 · Feb-2026 — Mileage backfill recompute endpoint.

Ships ``POST /api/admin/mileage/backfill-recompute?days=30&dry_run=false``
so an operator can re-run the (now-fixed) mileage calculator over
``time_entries`` rows that were silently closed with
``mileage_miles=0`` because of the pre-Feb-2026 collection
mismatch (classification D from the P1 investigation).

Behaviour
---------
    * Scans every ``time_entries`` row in the current tenant with
      ``clock_out_at`` within the last ``days`` days.
    * Re-runs ``routers.workforce._entry_mileage_miles`` against
      the ``gps_pings`` collection (post-fix path).
    * Updates ``mileage_miles`` in-place when the new value
      differs from the stored one.
    * ``dry_run=true`` → no writes, response still shows the
      ``would_update`` count + a sample of (entry_id, old, new).
    * Audit row ``mileage.backfill_recomputed`` with the response
      summary + the operator user id.

Admin-only.  Idempotent — running twice with the same window is
a no-op the second time because the recompute produces the same
value.  Tenant-scoped — never touches another tenant's rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant


router = APIRouter()
logger = logging.getLogger(__name__)


_SAMPLE_LIMIT = 50
_MAX_DAYS = 90


@router.post("/admin/mileage/backfill-recompute")
async def backfill_recompute(
    days: int = Query(
        30, ge=1, le=_MAX_DAYS,
        description="Lookback window in days.  Max 90.",
    ),
    dry_run: bool = Query(
        False,
        description="If true, log + return deltas without writing.",
    ),
    admin: Dict[str, Any] = Depends(require_admin),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Recompute ``time_entries.mileage_miles`` for closed shifts
    inside the lookback window using the fixed calculator.
    """
    from routers.workforce import (
        _entry_mileage_miles, _settings as _wf_settings,
    )

    start_dt = (datetime.now(timezone.utc)
                - timedelta(days=days))
    start_iso = start_dt.isoformat()
    settings = _wf_settings(tenant)
    tenant_id = tenant["id"]

    processed = 0
    updated = 0
    unchanged = 0
    errors = 0
    changes_sample: List[Dict[str, Any]] = []
    error_sample: List[Dict[str, Any]] = []

    cursor = db.time_entries.find(
        {"tenant_id": tenant_id,
         "clock_out_at": {"$gte": start_iso, "$ne": None}},
        {"_id": 0, "id": 1, "user_id": 1, "clock_in_at": 1,
         "clock_out_at": 1, "mileage_miles": 1, "status": 1},
    ).sort("clock_out_at", 1)

    async for entry in cursor:
        processed += 1
        try:
            new_miles = await _entry_mileage_miles(
                tenant_id, entry.get("id"),
                entry.get("user_id"),
                entry.get("clock_in_at"),
                entry.get("clock_out_at"),
                settings,
            )
            old_miles = entry.get("mileage_miles") or 0
            # Compare at 3 decimals to match the calculator's
            # rounding — avoids spurious updates from float noise.
            if round(float(new_miles), 3) == round(float(old_miles), 3):
                unchanged += 1
                continue
            if len(changes_sample) < _SAMPLE_LIMIT:
                changes_sample.append({
                    "entry_id": entry.get("id"),
                    "user_id": entry.get("user_id"),
                    "clock_in_at": entry.get("clock_in_at"),
                    "old": round(float(old_miles), 3),
                    "new": round(float(new_miles), 3),
                })
            if not dry_run:
                await db.time_entries.update_one(
                    {"id": entry.get("id"),
                     "tenant_id": tenant_id},
                    {"$set": {
                        "mileage_miles": new_miles,
                        "mileage_recomputed_at": now_iso(),
                        "mileage_recomputed_by": admin.get("id"),
                    }},
                )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            if len(error_sample) < 10:
                error_sample.append({
                    "entry_id": entry.get("id"),
                    "error": str(exc)[:200],
                })
            logger.warning(
                "[mileage.backfill_recomputed] entry=%s err=%s",
                entry.get("id"), exc,
            )

    summary = {
        "tenant_id": tenant_id,
        "days": days,
        "dry_run": dry_run,
        "processed": processed,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
        "changes_sample": changes_sample,
        "error_sample": error_sample,
    }

    # Audit row — fire-and-forget; log but don't 500 the response
    # if the audit write fails.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "action": "mileage.backfill_recomputed",
            "tenant_id": tenant_id,
            "actor_user_id": admin.get("id"),
            "summary": {k: v for k, v in summary.items()
                        if k not in ("changes_sample",
                                       "error_sample")},
            "created_at": now_iso(),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[mileage.backfill_recomputed] audit insert failed "
            "tenant=%s err=%s", tenant_id, exc,
        )

    return summary
