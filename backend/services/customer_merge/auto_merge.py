"""Feb 2026 · Customer Merge · Phase 3 — auto-merge sweep.

Cron entry point + boot-cleanup helper. Both use the Phase 1
detection engine to find high-confidence duplicate groups
(``exact_email`` OR ``exact_phone``) and hand them to the Phase 1
:func:`merge_customers` executor with ``initiated_by="auto"``.

Low-confidence groups (``exact_name_address`` / ``fuzzy_name``) are
NEVER auto-merged — they land in the manual review queue exposed by
:func:`routers.customer_merge.merge_candidates`.

Primary selection
-----------------
The record with the **oldest** ``created_at`` wins. This preserves
the surviving row's identity (external systems that keep a link to
the older customer_id still resolve). Field values from the newer
records still take precedence via the executor's newest-wins
reconciliation — the two heuristics are orthogonal.

Feature flag
------------
``AUTO_MERGE_ENABLED`` (env, default ``true``). When ``false`` the
cron logs ``auto_merge_disabled`` and returns a no-op summary; the
admin "Force sweep" endpoint still runs (super_admin override so
ops can dry-run against production).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db

from services.customer_merge.detection import detect_duplicates_for_tenant
from services.customer_merge.executor import merge_customers


logger = logging.getLogger("customer_merge.auto")


HIGH_CONFIDENCE_TYPES = frozenset({"exact_email", "exact_phone"})


def _env_flag_enabled() -> bool:
    """``AUTO_MERGE_ENABLED`` — default ``true``. Any of
    ``0/false/no/off`` (case-insensitive) disables the cron."""
    raw = (os.environ.get("AUTO_MERGE_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str) or not v.strip():
        return datetime(2999, 1, 1, tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(2999, 1, 1, tzinfo=timezone.utc)


async def _pick_primary_and_secondaries(
    tenant_id: str,
    customer_ids: List[str],
) -> Optional[Dict[str, Any]]:
    """Load the given customers and return
    ``{"primary_id": id, "secondary_ids": [id, ...]}`` with primary =
    oldest ``created_at``. Skips already-merged rows (they slipped
    into the detection group before their merge got flushed) and
    returns None if fewer than 2 mergeable rows remain."""
    rows = await db.customers.find(
        {"tenant_id": tenant_id, "id": {"$in": list(customer_ids)}},
        {"_id": 0, "id": 1, "created_at": 1, "merged_into": 1},
    ).to_list(len(customer_ids) + 5)
    live = [r for r in rows if not r.get("merged_into")]
    if len(live) < 2:
        return None
    live.sort(key=lambda r: _parse_dt(r.get("created_at")))
    primary = live[0]["id"]
    secondaries = [r["id"] for r in live[1:]]
    return {"primary_id": primary, "secondary_ids": secondaries}


async def auto_merge_high_confidence_duplicates(
    tenant_id: str,
    *,
    initiated_by: str = "auto",
) -> Dict[str, Any]:
    """Run one auto-merge pass against a single tenant. Returns::

        {
          "tenant_id":   "...",
          "groups_found_high":            <int>,
          "groups_skipped_low_confidence":<int>,
          "groups_auto_merged":           <int>,
          "records_affected":             <int>,  # sum of secondaries merged
          "audit_ids":                    ["audit_...", ...],
          "errors":                       [{"group": {...}, "error": "..."}],
        }
    """
    summary: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "groups_found_high": 0,
        "groups_skipped_low_confidence": 0,
        "groups_auto_merged": 0,
        "records_affected": 0,
        "audit_ids": [],
        "errors": [],
    }

    try:
        groups = await detect_duplicates_for_tenant(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[auto-merge] detection failed for %s", tenant_id)
        summary["errors"].append({"group": None, "error": f"detection: {exc}"})
        return summary

    for g in groups:
        if (g.get("confidence") or "").lower() != "high":
            summary["groups_skipped_low_confidence"] += 1
            continue
        if (g.get("match_type") or "") not in HIGH_CONFIDENCE_TYPES:
            # Defense-in-depth — confidence == high should imply the
            # match_type set, but never trust the detector blindly.
            summary["groups_skipped_low_confidence"] += 1
            continue
        summary["groups_found_high"] += 1
        pick = await _pick_primary_and_secondaries(
            tenant_id, list(g.get("customer_ids") or []),
        )
        if not pick:
            # Every candidate has already been merged (racy re-run
            # window). Treat as a soft skip rather than an error.
            continue
        try:
            result = await merge_customers(
                tenant_id=tenant_id,
                primary_id=pick["primary_id"],
                secondary_ids=pick["secondary_ids"],
                strategy="newest_wins",
                initiated_by=initiated_by,
                dry_run=False,
                match_type=g.get("match_type"),
                confidence="high",
            )
            if result.get("no_op"):
                continue
            summary["groups_auto_merged"] += 1
            summary["records_affected"] += len(result.get("secondary_ids") or [])
            if result.get("audit_id"):
                summary["audit_ids"].append(result["audit_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[auto-merge] merge failed tenant=%s primary=%s: %s",
                tenant_id, pick["primary_id"], exc,
            )
            summary["errors"].append({
                "group": {"match_type": g.get("match_type"),
                            "customer_ids": g.get("customer_ids")},
                "error": str(exc),
            })
    return summary


async def run_auto_merge_sweep_all_tenants(
    *,
    initiated_by: str = "auto",
    respect_env_flag: bool = True,
) -> Dict[str, Any]:
    """Daily 09:15 UTC cron entry. Per-tenant isolation — one tenant's
    crash never blocks another. Returns a rollup summary of the
    per-tenant reports."""
    if respect_env_flag and not _env_flag_enabled():
        logger.info("[auto-merge] auto_merge_disabled via AUTO_MERGE_ENABLED flag")
        return {
            "tenants_scanned": 0, "auto_merge_enabled": False,
            "groups_found_high": 0, "groups_auto_merged": 0,
            "groups_skipped_low_confidence": 0,
            "records_affected": 0, "audit_ids": [], "errors": [],
            "per_tenant": [], "ran_at": datetime.now(timezone.utc).isoformat(),
        }

    rollup: Dict[str, Any] = {
        "tenants_scanned": 0, "auto_merge_enabled": True,
        "groups_found_high": 0, "groups_auto_merged": 0,
        "groups_skipped_low_confidence": 0,
        "records_affected": 0, "audit_ids": [], "errors": [],
        "per_tenant": [],
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }

    tenants = await db.tenants.find(
        {"$or": [{"active": {"$ne": False}},
                   {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1, "slug": 1, "name": 1},
    ).to_list(1000)

    for t in tenants:
        tid = t.get("id")
        if not tid:
            continue
        rollup["tenants_scanned"] += 1
        try:
            per = await auto_merge_high_confidence_duplicates(
                tid, initiated_by=initiated_by,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("[auto-merge] tenant %s crashed", tid)
            rollup["errors"].append({"tenant_id": tid, "error": str(exc)})
            continue
        rollup["groups_found_high"] += per["groups_found_high"]
        rollup["groups_auto_merged"] += per["groups_auto_merged"]
        rollup["groups_skipped_low_confidence"] += per["groups_skipped_low_confidence"]
        rollup["records_affected"] += per["records_affected"]
        rollup["audit_ids"].extend(per["audit_ids"])
        rollup["errors"].extend(per["errors"])
        rollup["per_tenant"].append({
            "tenant_id": tid, "tenant_slug": t.get("slug"),
            **{k: per[k] for k in (
                "groups_found_high", "groups_auto_merged",
                "groups_skipped_low_confidence", "records_affected",
            )},
        })

    logger.info(
        "[auto-merge] sweep complete · tenants=%d · high_groups=%d · "
        "auto_merged=%d · low_skipped=%d · records=%d · errors=%d",
        rollup["tenants_scanned"], rollup["groups_found_high"],
        rollup["groups_auto_merged"], rollup["groups_skipped_low_confidence"],
        rollup["records_affected"], len(rollup["errors"]),
    )
    return rollup


async def cron_daily_auto_merge() -> None:
    """APScheduler entry point — no return value. Wraps
    :func:`run_auto_merge_sweep_all_tenants` in an outer try so the
    scheduler thread never dies on a crash."""
    try:
        await run_auto_merge_sweep_all_tenants()
    except Exception:  # noqa: BLE001
        logger.exception("[auto-merge] cron crashed at top level")
