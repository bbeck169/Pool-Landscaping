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
    # Batch 12C · Feb 2026 — ambiguous-match digest (email + SMS,
    # 24h cooldown). Silent when the count is 0.
    try:
        await _fire_ambiguous_alert(tenant, summary)
    except Exception as exc:  # pragma: no cover — defensive, never
                                # crashes the tenant loop.
        logger.warning(
            f"[stripe-sync-ambiguous] tenant={tid} fanout failed: {exc}"
        )
    return summary


# ─── Batch 12C · Feb 2026 — Ambiguous-match digest fanout ─────────────
AMBIG_KIND = "stripe_sync_ambiguous"
AMBIG_COOLDOWN_HOURS = 24


async def _ambig_recently_alerted(tenant_id: str) -> bool:
    state = await db.ops_alerts_state.find_one(
        {"tenant_id": tenant_id, "kind": AMBIG_KIND},
        {"_id": 0, "last_ran_at": 1},
    )
    if not state or not state.get("last_ran_at"):
        return False
    try:
        dt = datetime.fromisoformat(str(state["last_ran_at"])
                                       .replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=AMBIG_COOLDOWN_HOURS)
    return dt >= cutoff


async def _resolve_ambig_recipients(tenant: dict) -> Dict[str, List[str]]:
    """Mirrors the Stripe key-health alert fanout logic: emails go to
    every admin/super_admin user on the tenant; SMS uses the tenant's
    escalation list falling back to the first admin's phone."""
    tid = tenant["id"]
    users = await db.users.find(
        {"tenant_id": tid,
          "role": {"$in": ["admin", "super_admin"]},
          "active": {"$ne": False}},
        {"_id": 0, "email": 1, "phone": 1},
    ).to_list(50)
    emails = [u["email"] for u in users if u.get("email")]
    sms = list(tenant.get("sms_escalation_recipients") or [])
    if not sms:
        for u in users:
            if u.get("phone"):
                sms = [u["phone"]]
                break
    return {"emails": emails, "sms": sms}


async def _fire_ambiguous_alert(tenant: dict, summary: Dict[str, Any]) -> None:
    """Fan-out email + SMS when ``ambiguous_matches`` is non-empty.

    * Renders bodies via ``render_template()`` — never inline-
      substitutes. Uses the ``stripe_sync_ambiguous_matches`` +
      ``stripe_sync_ambiguous_matches_sms`` templates seeded by
      ``services.add_card_links.seed_add_card_templates_for_tenant``.
    * Records ``marketing_deliveries`` rows keyed on
      ``trigger_entity.kind="stripe_sync_ambiguous"``.
    * 24-hour cooldown via ``ops_alerts_state{kind=AMBIG_KIND}`` — a
      subsequent scheduled run with ambiguous > 0 stays silent until
      the window elapses.
    * NEVER fires when ambiguous count is 0.
    """
    matches = summary.get("ambiguous_matches") or []
    if not matches:
        return
    tid = tenant["id"]
    if await _ambig_recently_alerted(tid):
        logger.info(
            f"[stripe-sync-ambiguous] tenant={tid} skipped=cooldown "
            f"(within {AMBIG_COOLDOWN_HOURS}h)"
        )
        return

    from services.marketing.merge_tags import render_context, render_template

    email_tpl = await db.marketing_templates.find_one(
        {"tenant_id": tid, "code": "stripe_sync_ambiguous_matches"},
        {"_id": 0},
    )
    sms_tpl = await db.marketing_templates.find_one(
        {"tenant_id": tid, "code": "stripe_sync_ambiguous_matches_sms"},
        {"_id": 0},
    )

    sample = ", ".join(
        (m.get("customer_name") or m.get("email") or m.get("customer_id") or "?")
        for m in matches[:3]
    ) + (f" (+{len(matches) - 3} more)" if len(matches) > 3 else "")

    base_url = (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or (tenant.get("brand") or {}).get("public_origin")
        or "https://poolscape-audit.preview.emergentagent.com"
    )
    resolver_url = f"{base_url.rstrip('/')}/settings/billing#stripe-sync-section"

    ctx = render_context(
        tenant=tenant,
        ambiguous_match_count=len(matches),
        ambiguous_match_sample=sample,
        add_card_link=resolver_url,  # reused as the "Review" deep link
    )
    trigger_id = f"stripe_sync_ambig:{tid}:{now_iso()[:13]}"
    recipients = await _resolve_ambig_recipients(tenant)
    sent_email = 0
    sent_sms = 0

    if email_tpl:
        subject_r, _ = render_template(email_tpl.get("subject") or "", ctx)
        body_r, _ = render_template(email_tpl.get("body") or "", ctx)
        try:
            from services.comms_email_adapter import send_email
            import asyncio as _asyncio
            for em in recipients["emails"]:
                try:
                    res = await _asyncio.wait_for(send_email(
                        tenant_id=tid, to_email=em,
                        subject=subject_r, html=body_r,
                        from_name=(tenant.get("name") or None),
                    ), timeout=8.0)
                    await db.marketing_deliveries.insert_one({
                        "id": new_id(), "tenant_id": tid,
                        "customer_id": None,
                        "channel": "email", "kind": "transactional",
                        "recipient": em, "recipient_email": em,
                        "subject": subject_r, "body": body_r,
                        "subject_rendered": subject_r,
                        "body_rendered": body_r,
                        "trigger_entity": {"kind": AMBIG_KIND, "id": tid},
                        "trigger_id": trigger_id,
                        "provider": (res or {}).get("provider"),
                        "provider_status": (res or {}).get("status"),
                        "delivered": (res or {}).get("status", "").startswith("sent"),
                        "created_at": now_iso(), "sent_at": now_iso(),
                    })
                    sent_email += 1
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        f"[stripe-sync-ambiguous] email send to {em} failed: {exc}"
                    )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"[stripe-sync-ambiguous] email path failed: {exc}")

    if sms_tpl:
        sms_body_r, _ = render_template(sms_tpl.get("body") or "", ctx)
        try:
            from utils import send_sms
            import asyncio as _asyncio
            for phone in recipients["sms"]:
                try:
                    await _asyncio.wait_for(
                        _asyncio.to_thread(send_sms, phone, sms_body_r),
                        timeout=8.0,
                    )
                    await db.marketing_deliveries.insert_one({
                        "id": new_id(), "tenant_id": tid,
                        "customer_id": None,
                        "channel": "sms", "kind": "transactional",
                        "recipient": phone, "recipient_phone": phone,
                        "subject": None, "body": sms_body_r,
                        "body_rendered": sms_body_r,
                        "trigger_entity": {"kind": AMBIG_KIND, "id": tid},
                        "trigger_id": trigger_id,
                        "delivered": True,
                        "created_at": now_iso(), "sent_at": now_iso(),
                    })
                    sent_sms += 1
                except Exception as exc:  # pragma: no cover
                    logger.warning(
                        f"[stripe-sync-ambiguous] sms send to {phone} failed: {exc}"
                    )
        except Exception as exc:  # pragma: no cover
            logger.warning(f"[stripe-sync-ambiguous] sms path failed: {exc}")

    # Cooldown state stamp — set even when fanout was 0/0 to avoid
    # retrying every cron tick for the same 24h window.
    await db.ops_alerts_state.update_one(
        {"tenant_id": tid, "kind": AMBIG_KIND},
        {"$set": {"tenant_id": tid, "kind": AMBIG_KIND,
                    "last_ran_at": now_iso(),
                    "last_ambiguous_count": len(matches)},
          "$setOnInsert": {"id": new_id(), "created_at": now_iso()}},
        upsert=True,
    )
    logger.info(
        f"[stripe-sync-ambiguous] tenant={tid} "
        f"ambiguous={len(matches)} email={sent_email} sms={sent_sms}"
    )


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
