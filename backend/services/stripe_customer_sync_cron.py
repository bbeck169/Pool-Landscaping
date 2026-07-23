"""Phase 12B · Feb 2026 — Weekly Stripe customer sync cron.

Follows the same per-tenant local-hour dispatch pattern used by the
Phase 10 referral watcher and Phase 11 equipment tracker digest:

* :func:`hourly_scan` is registered with APScheduler at ``minute=0``
  every hour.
* Each tick iterates every tenant, resolves its local time (fallback
  ``America/Phoenix``) and dispatches the sync **only when it is
  Thursday 02:00 in that tenant's own timezone**. This keeps the
  cron globally cheap while still hitting every tenant at their
  intended clock time.

Guardrails:

* Skips outright when ``STRIPE_MODE != "live"`` (test-mode) — logs an
  info line + no work performed.
* Skips tenants without ``stripe_account_id`` (i.e. Stripe live wiring
  never configured) with a WARN.
* 4-hour cooldown: if a manual run (or any prior scheduled run)
  completed within 4h of the current slot, the tenant is skipped for
  this cycle. State is persisted on ``ops_alerts_state`` keyed on
  ``{tenant_id, kind: "stripe_customer_sync"}`` — mirrors the pattern
  used by the referral watcher's cool-down guard.
* On success the tenant document is stamped with
  ``last_stripe_customer_sync_at`` + ``last_stripe_customer_sync_summary``
  so the settings UI "Last synced" indicator reflects both manual and
  automated runs.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db, logger
from services.stripe_customer_sync import run_stripe_customer_sync
from utils import now_iso, new_id

DEFAULT_TZ = "America/Phoenix"
KIND = "stripe_customer_sync"
COOLDOWN_HOURS = 4
DISPATCH_WEEKDAY = 3   # Thursday (Mon=0)
DISPATCH_HOUR_LOCAL = 2


def _tenant_tz(tenant: dict) -> str:
    tz = (tenant.get("timezone") or "").strip()
    return tz or DEFAULT_TZ


def _now_local(tenant: dict) -> datetime:
    try:
        return datetime.now(ZoneInfo(_tenant_tz(tenant)))
    except Exception:
        return datetime.now(ZoneInfo(DEFAULT_TZ))


def _stripe_mode() -> str:
    """Reads the pod-wide Stripe mode. ``live`` unlocks the cron;
    anything else short-circuits."""
    from services.stripe_client import mode as _mode_fn
    try:
        return (_mode_fn() or "").lower()
    except Exception:
        # Fallback to raw env — resilient against import-time errors
        # in the stripe_client helper.
        key = os.environ.get("STRIPE_SECRET_KEY", "")
        if key.startswith("sk_live_"):
            return "live"
        if key.startswith("sk_test_"):
            return "test"
        return ""


async def _recently_ran(tenant_id: str) -> bool:
    """True if a run of any kind completed for this tenant in the last
    ``COOLDOWN_HOURS`` hours. Reads from both the tenant doc and the
    ``ops_alerts_state`` audit row so a manual API-triggered run also
    counts (Phase 12B ``run_stripe_customer_sync`` stamps
    ``tenant.stripe_sync_last_run_at`` at completion)."""
    tenant = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "stripe_sync_last_run_at": 1,
          "last_stripe_customer_sync_at": 1},
    ) or {}
    stamps = [tenant.get("stripe_sync_last_run_at"),
                tenant.get("last_stripe_customer_sync_at")]
    state = await db.ops_alerts_state.find_one(
        {"tenant_id": tenant_id, "kind": KIND},
        {"_id": 0, "last_ran_at": 1},
    )
    if state and state.get("last_ran_at"):
        stamps.append(state.get("last_ran_at"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=COOLDOWN_HOURS)
    for s in stamps:
        if not s:
            continue
        try:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                return True
        except Exception:
            continue
    return False


async def _record_run(tenant_id: str, summary: Dict[str, Any],
                       *, reason: Optional[str] = None) -> None:
    """Persist the run stamp both on the tenant doc (for the settings
    UI) and on ``ops_alerts_state`` (for the cool-down guard)."""
    now = now_iso()
    brief = {
        "examined": summary.get("examined"),
        "linked": len(summary.get("linked") or []),
        "updated_card_flag": len(summary.get("updated_card_flag") or []),
        "ambiguous_matches": len(summary.get("ambiguous_matches") or []),
        "skipped_no_contact": summary.get("skipped_no_contact"),
        "no_op": summary.get("no_op"),
        "finished_at": summary.get("finished_at"),
        "source": reason or "cron",
    }
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {
            "last_stripe_customer_sync_at": now,
            "last_stripe_customer_sync_summary": brief,
        }},
    )
    await db.ops_alerts_state.update_one(
        {"tenant_id": tenant_id, "kind": KIND},
        {"$set": {"tenant_id": tenant_id, "kind": KIND,
                    "last_ran_at": now, "last_summary": brief},
          "$setOnInsert": {"id": new_id(), "created_at": now}},
        upsert=True,
    )


async def run_weekly_for_tenant(tenant: dict) -> Dict[str, Any]:
    """Sync one tenant. Returns the summary dict from
    :func:`run_stripe_customer_sync` (plus a ``source`` marker). Does
    not raise — errors are logged and returned as
    ``{"error": "<msg>"}`` so a single tenant's failure never crashes
    the scheduler tick."""
    tid = tenant["id"]
    if not tenant.get("stripe_account_id"):
        logger.warning(
            f"[stripe-customer-sync] tenant={tid} skipped=no_stripe_account"
        )
        return {"skipped": "no_stripe_account"}
    try:
        summary = await run_stripe_customer_sync(tid, dry_run=False)
    except Exception as exc:
        logger.warning(
            f"[stripe-customer-sync] tenant={tid} error={exc}"
        )
        return {"error": str(exc)}
    await _record_run(tid, summary)
    logger.info(
        f"[stripe-customer-sync] tenant={tid} "
        f"examined={summary.get('examined')} "
        f"linked={len(summary.get('linked') or [])} "
        f"updated_card_flag={len(summary.get('updated_card_flag') or [])} "
        f"ambiguous={len(summary.get('ambiguous_matches') or [])} "
        f"skipped={summary.get('skipped_no_contact')}"
    )
    return summary


async def hourly_scan() -> Dict[str, Any]:
    """APScheduler entry point — registered at ``minute=0`` every hour.

    On each tick:
    1. Bails out immediately if ``STRIPE_MODE != "live"``.
    2. Iterates every tenant; for each, checks whether it is currently
       Thursday 02:00 in that tenant's local timezone.
    3. Applies the 4h cool-down guard.
    4. Dispatches the sync via :func:`run_weekly_for_tenant`.

    Returns a summary dict ``{fired: [ids], skipped_cooldown: [ids],
    skipped_not_configured: [ids], skipped_wrong_slot: <int>,
    total: <int>, stripe_mode: <str>}``.
    """
    mode = _stripe_mode()
    if mode != "live":
        logger.info(
            f"[stripe-customer-sync-cron] skipped whole tick — "
            f"stripe_mode={mode!r} (live required)"
        )
        return {"stripe_mode": mode, "skipped_whole_tick": True}

    tenants = await db.tenants.find(
        {}, {"_id": 0, "id": 1, "timezone": 1, "stripe_account_id": 1},
    ).to_list(2000)
    fired: List[str] = []
    skipped_cooldown: List[str] = []
    skipped_not_configured: List[str] = []
    skipped_wrong_slot = 0
    for t in tenants:
        tid = t.get("id")
        try:
            local = _now_local(t)
        except Exception as exc:
            logger.warning(
                f"[stripe-customer-sync-cron] tz resolve failed for "
                f"{tid}: {exc}"
            )
            continue
        # Thursday 02:00 local. This branch is what keeps the tick
        # per-tenant-local rather than global-UTC.
        if (local.weekday() != DISPATCH_WEEKDAY
             or local.hour != DISPATCH_HOUR_LOCAL):
            skipped_wrong_slot += 1
            continue
        if not t.get("stripe_account_id"):
            skipped_not_configured.append(tid)
            logger.warning(
                f"[stripe-customer-sync-cron] tenant={tid} "
                f"skipped=no_stripe_account"
            )
            continue
        if await _recently_ran(tid):
            skipped_cooldown.append(tid)
            logger.info(
                f"[stripe-customer-sync-cron] tenant={tid} "
                f"skipped=manual_recent (within {COOLDOWN_HOURS}h)"
            )
            continue
        try:
            await run_weekly_for_tenant(t)
            fired.append(tid)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                f"[stripe-customer-sync-cron] tenant={tid} run failed: {exc}"
            )
    return {
        "stripe_mode": mode,
        "fired": fired,
        "skipped_cooldown": skipped_cooldown,
        "skipped_not_configured": skipped_not_configured,
        "skipped_wrong_slot": skipped_wrong_slot,
        "total": len(tenants),
    }
