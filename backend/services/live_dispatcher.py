"""LDM-B · Feb-2026 — AI Live Dispatcher.

Cron-driven service that scans tenant fleets every 5 minutes for
technicians projected to arrive late at their next scheduled visit
and, when the projected delay exceeds the tenant-configured
threshold, fans out MARCO-branded SMS to the next N customers on
the route.

Wiring
──────
Registered from :mod:`server` alongside MARCO's proactive-todo
reminder cron (:mod:`services.marco_reminder_cron`). Cadence: 5
min ``IntervalTrigger``. The tick delegates to :func:`scan` which
is the deterministic, test-callable entry point.

Tenant-configurable rules (see LDM-A)
─────────────────────────────────────
``settings.automation_rules.dispatch_delay_threshold_mins`` (default 20)
``settings.automation_rules.dispatch_sms_customer_count`` (default 3)

Both fall back to the LDM-A canonical defaults when the field is
missing — the pod stays functional even before the
``automation_rules_v1`` backfill sentinel is stamped.

Persistence
───────────
``dispatch_events`` collection holds one row per fired dispatch::

    {
        id, tenant_id, tech_id, visit_id,
        delay_mins,                # rounded to 1 decimal
        customers_notified: [id],  # only status ∈ sent/deferred/skipped
        sent_count, deferred_count,
        skipped_count, failed_count,
        initiated_at,  initiated_by = "marco_live_dispatcher",
    }

Dedupe key ``(tenant_id, tech_id, visit_id)`` within a 30-minute
window — see :data:`DEDUPE_WINDOW_MINUTES`. Failed sends do NOT
consume the dedupe slot (transient errors retry next tick, per the
user-approved status matrix).

Status → dedupe-stamp matrix
────────────────────────────
``sent``               → stamp
``deferred``           → stamp   (queued for after-hours delivery)
``skipped_opted_out``  → stamp   (terminal decision even w/o SMS)
``failed``             → NO stamp (retry next scan)

Route helper
────────────
Reuses :func:`services.route_optimizer.haversine_miles` +
:data:`services.route_optimizer.AVG_SPEED_MPH` — no fallback
Haversine needed (per LDM-B pre-recon decisions). The 30 mph
constant embeds the same drive-time estimate the multi-stop
optimizer uses today.

Cross-tenant safety
───────────────────
Every mongo query includes ``tenant_id``. GPS pings are joined by
``user_id`` derived from ``users.find_one({technician_id, tenant_id})``
so a rogue tenant A tech_id echoed by tenant B's schedule can never
resolve to A's GPS state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from utils import new_id, now_iso


logger = logging.getLogger("live_dispatcher")


# ═════════════════════════════════════════════════════════════════════
# Tunable constants — see module docstring for rationale.
# ═════════════════════════════════════════════════════════════════════
GPS_FRESHNESS_MINUTES = 10
DEDUPE_WINDOW_MINUTES = 30
UPCOMING_LOOKAHEAD_HOURS = 24
INITIATED_BY = "marco_live_dispatcher"

# LDM-A defaults — mirrored here so the tick still fires with sane
# values when a pod comes up before the backfill sentinel is
# stamped. Bumping either constant means bumping the LDM-A model
# defaults too (see routers/tenants.py::AUTOMATION_RULE_DEFAULTS).
_DEFAULT_DISPATCH_THRESHOLD_MINS = 20
_DEFAULT_DISPATCH_SMS_CUSTOMER_COUNT = 3

# Statuses that "consume" the dedupe slot per the user-approved
# ruling. ``failed`` is intentionally absent — those retry next
# tick. Anything else means we've made a terminal decision for
# this (tenant, tech, visit) tuple.
_DEDUPE_STAMPING_STATUSES = frozenset({
    "sent", "deferred", "skipped_opted_out",
})


# ═════════════════════════════════════════════════════════════════════
# Public entry points.
# ═════════════════════════════════════════════════════════════════════
async def scan(
    db,
    *,
    now: Optional[datetime] = None,
    send_sms: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
) -> Dict[str, int]:
    """One deterministic sweep of all tenants.

    Returns aggregate counts so the tick + tests can assert on the
    scan outcome without re-reading persisted state::

        {
            "tenants_scanned": int,
            "techs_evaluated": int,
            "delays_detected": int,
            "dispatches_fired": int,
            "sms_sent": int,
            "sms_deferred": int,
            "sms_skipped": int,
            "sms_failed": int,
        }

    Parameters
    ----------
    db:
        Motor async DB handle.
    now:
        Reference "now" — tests pass a fixed datetime; production
        callers pass ``None`` and we default to
        ``datetime.now(timezone.utc)``.
    send_sms:
        DI hook — defaults to :func:`services.comms_sms_adapter.send_sms`
        when omitted. Tests inject a deterministic stub to avoid
        hitting the real adapter chain (BYO / quiet-hours defer /
        RC HTTP).
    """
    now = now or datetime.now(timezone.utc)
    if send_sms is None:
        from services.comms_sms_adapter import send_sms as _default_send_sms
        send_sms = _default_send_sms

    stats = {
        "tenants_scanned": 0,
        "techs_evaluated": 0,
        "delays_detected": 0,
        "dispatches_fired": 0,
        "sms_sent": 0,
        "sms_deferred": 0,
        "sms_skipped": 0,
        "sms_failed": 0,
    }

    async for tenant in db.tenants.find(
        {}, {"_id": 0, "id": 1, "settings.automation_rules": 1},
    ):
        stats["tenants_scanned"] += 1
        tid = tenant.get("id")
        if not tid:
            continue
        rules = _rules_with_defaults(tenant)
        threshold_mins = int(rules["dispatch_delay_threshold_mins"])
        sms_count = int(rules["dispatch_sms_customer_count"])
        await _scan_tenant(
            db, tid, now,
            threshold_mins=threshold_mins,
            sms_count=sms_count,
            send_sms=send_sms,
            stats=stats,
        )
    return stats


def register_live_dispatcher_cron(scheduler) -> None:
    """Hook into the APScheduler instance created in server.py.
    Mirrors :func:`services.marco_reminder_cron.register_marco_reminders_cron`
    — feed a coroutine function directly, ``AsyncIOScheduler`` awaits it."""
    if scheduler is None:
        return
    try:
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(
            _tick,
            IntervalTrigger(minutes=5),
            id="live_dispatcher.tick",
            replace_existing=True,
        )
        logger.info(
            "[live_dispatcher.cron] 5-min-cadence dispatcher tick"
            " registered",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "[live_dispatcher.cron] scheduler registration failed: %s",
            exc,
        )


# ═════════════════════════════════════════════════════════════════════
# Internal — tick + per-tenant loop.
# ═════════════════════════════════════════════════════════════════════
async def _tick() -> None:
    """Job entrypoint bound to APScheduler. Late-imports ``db``
    so this module doesn't require a live DB handle at import time
    (matches Lana / MARCO cron conventions)."""
    from server import db
    try:
        summary = await scan(db)
        if summary["dispatches_fired"]:
            logger.info(
                "[live_dispatcher.cron] tick fired dispatches=%s "
                "sms_sent=%s deferred=%s skipped=%s failed=%s",
                summary["dispatches_fired"],
                summary["sms_sent"],
                summary["sms_deferred"],
                summary["sms_skipped"],
                summary["sms_failed"],
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("[live_dispatcher.cron] tick failed: %s", exc)


async def _scan_tenant(
    db, tid: str, now: datetime,
    *,
    threshold_mins: int,
    sms_count: int,
    send_sms: Callable[..., Awaitable[Dict[str, Any]]],
    stats: Dict[str, int],
) -> None:
    """Find each tech with an imminent next-visit and evaluate the
    delay projection."""
    lookahead_iso = _to_iso_z(
        now + timedelta(hours=UPCOMING_LOOKAHEAD_HOURS),
    )

    # Pull scheduled visits in the "in-flight" window: any status="scheduled"
    # job whose scheduled_start is up to 24h in the future. NOTE the query
    # deliberately has NO lower bound — a scheduled job whose
    # scheduled_start is in the past is precisely the "running late"
    # case we're here to detect. Python-side dedupe by technician_id
    # keeps the first (earliest) row per tech.
    seen_techs: set = set()
    async for job in db.jobs.find(
        {
            "tenant_id": tid,
            "status": "scheduled",
            "scheduled_start": {"$lte": lookahead_iso},
            "technician_id": {"$exists": True, "$ne": None},
        },
        {"_id": 0},
    ).sort("scheduled_start", 1):
        tech_id = job.get("technician_id")
        if not tech_id or tech_id in seen_techs:
            continue
        seen_techs.add(tech_id)
        stats["techs_evaluated"] += 1
        try:
            await _evaluate_tech(
                db, tid, tech_id, next_visit=job, now=now,
                threshold_mins=threshold_mins,
                sms_count=sms_count,
                send_sms=send_sms,
                stats=stats,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[live_dispatcher] tenant=%s tech=%s eval error: %s",
                tid, tech_id, exc,
            )


async def _evaluate_tech(
    db, tid: str, tech_id: str, *,
    next_visit: Dict[str, Any],
    now: datetime,
    threshold_mins: int,
    sms_count: int,
    send_sms: Callable[..., Awaitable[Dict[str, Any]]],
    stats: Dict[str, int],
) -> None:
    """Delay-projection + notification flow for one (tenant, tech)."""
    # 1. Resolve GPS user_id via the users collection.  Job.technician_id
    #    maps to users.technician_id — a two-step join because
    #    gps_pings.user_id is the users.id primary key.
    user = await db.users.find_one(
        {"tenant_id": tid, "technician_id": tech_id},
        {"_id": 0, "id": 1},
    )
    if not user or not user.get("id"):
        return
    uid = user["id"]

    # 2. Latest gps_ping within the freshness window. captured_at is
    #    stored as an ISO Z string in the pings collection (see
    #    routers/gps_ingest.py); lexicographic comparison on ISO 8601
    #    is chronologically correct so we can query with $gte on the
    #    string directly.
    freshness_floor = _to_iso_z(
        now - timedelta(minutes=GPS_FRESHNESS_MINUTES),
    )
    recent = await db.gps_pings.find(
        {
            "tenant_id": tid,
            "user_id": uid,
            "captured_at": {"$gte": freshness_floor},
        },
        {"_id": 0, "lat": 1, "lon": 1, "captured_at": 1},
    ).sort("captured_at", -1).limit(1).to_list(1)
    if not recent:
        # No recent pings — tech isn't clocked in or hasn't checked in
        # since the freshness floor. Skip gracefully.
        return
    ping = recent[0]

    # 3. Extract next-visit geo — prefer site_* (persisted by the geocoder
    #    on job insert; see routers/jobs.py) then legacy latitude/longitude.
    dest_lat, dest_lng = _visit_geo(next_visit)
    if dest_lat is None or dest_lng is None:
        return

    # 4. Compute projected arrival and delay.
    scheduled_start_dt = _parse_iso(next_visit.get("scheduled_start"))
    if scheduled_start_dt is None:
        return
    from services.route_optimizer import haversine_miles, AVG_SPEED_MPH
    miles = haversine_miles(
        float(ping["lat"]), float(ping["lon"]),
        float(dest_lat), float(dest_lng),
    )
    travel_minutes = (miles / AVG_SPEED_MPH) * 60.0
    projected_arrival = now + timedelta(minutes=travel_minutes)
    delay_mins = (
        projected_arrival - scheduled_start_dt
    ).total_seconds() / 60.0
    if delay_mins <= threshold_mins:
        return
    stats["delays_detected"] += 1

    # 5. Dedupe — same (tenant, tech, visit) within the last 30 min
    #    → skip the whole flow.
    dedupe_floor = _to_iso_z(
        now - timedelta(minutes=DEDUPE_WINDOW_MINUTES),
    )
    existing = await db.dispatch_events.find_one(
        {
            "tenant_id": tid,
            "tech_id": tech_id,
            "visit_id": next_visit.get("id"),
            "initiated_at": {"$gte": dedupe_floor},
        },
        {"_id": 0, "id": 1},
    )
    if existing:
        return

    # 6. Pick the next N customers on route (chronological, starting
    #    with the delayed visit itself). Same "no lower bound" logic as
    #    the outer scan: a scheduled_start in the past just means that
    #    visit is running late — it still belongs on the route.
    upcoming = await db.jobs.find(
        {
            "tenant_id": tid,
            "technician_id": tech_id,
            "status": "scheduled",
            "scheduled_start": {
                "$lte": _to_iso_z(
                    now + timedelta(hours=UPCOMING_LOOKAHEAD_HOURS),
                ),
            },
        },
        {"_id": 0, "id": 1, "customer_id": 1, "scheduled_start": 1},
    ).sort("scheduled_start", 1).limit(sms_count).to_list(sms_count)

    per_status = {"sent": 0, "deferred": 0, "skipped": 0, "failed": 0}
    customers_notified: List[str] = []

    for visit in upcoming:
        cid = visit.get("customer_id")
        if not cid:
            continue
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "phones": 1},
        )
        if not cust:
            # LDM-E · Cross-tenant safety warning. A scheduled visit
            # references a customer_id that does NOT resolve within
            # this tenant's customers collection. That's either a
            # soft-deleted customer or (rarely) cross-tenant data
            # corruption — either way, refuse to send SMS and log
            # the incident. Skipping avoids any chance of leaking
            # SMS to another tenant's customer if the customer_id
            # happens to collide across tenants.
            logger.warning(
                "[live_dispatcher.security] cross_tenant_customer_id "
                "visit=%s tenant=%s customer_id=%s — skipping SMS",
                visit.get("id"), tid, cid,
            )
            continue
        phone = _resolve_phone(cust)
        if not phone:
            # Nothing to send — treat as skipped (terminal, dedupe-worthy)
            per_status["skipped"] += 1
            continue
        # SMS-RECIPIENT-FIX · Feb-2026 — customer-facing deny-list.
        # Delay-SMS fan-out → silently skip + WARN when the resolved
        # phone belongs to a workforce/tenant line. Matches the
        # ``on_my_way.py:321-333`` precedent byte-for-byte.
        try:
            from services.comms_hardening.deny_list import (
                strip_admin_owned_recipients,
            )
            _kept, _stripped = await strip_admin_owned_recipients(
                tenant_id=tid, kind="customer_facing", channel="sms",
                recipients=[phone],
                context={"trigger": "live_dispatcher_delay",
                          "visit_id": visit.get("id"),
                          "tech_id": tech_id, "customer_id": cid},
            )
            if _stripped:
                logger.warning(
                    "[live_dispatcher] denied_admin_owned_recipient "
                    "tenant=%s tech=%s customer=%s phone=%s",
                    tid, tech_id, cid, phone,
                )
                per_status["skipped"] += 1
                continue
            phone = _kept[0] if _kept else phone
        except Exception as exc:  # noqa: BLE001 — never break cron
            logger.warning(
                "[live_dispatcher] deny_list crashed — proceeding "
                "without strip (fail-open): %s", exc,
            )
        body = _compose_delay_sms(
            customer_name=cust.get("name") or "there",
            projected_arrival=projected_arrival,
            delay_mins=delay_mins,
        )
        try:
            from services.comms_env_guard import CommsContext
            result = await send_sms(
                tenant_id=tid, to_phone=phone, body=body,
                context=CommsContext.SYSTEM,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[live_dispatcher] send_sms raised — treating as "
                "failed (retry next tick). tenant=%s tech=%s "
                "customer=%s err=%s",
                tid, tech_id, cid, exc,
            )
            per_status["failed"] += 1
            continue
        status = (result or {}).get("status") or "failed"
        if status == "sent":
            per_status["sent"] += 1
        elif status == "deferred":
            per_status["deferred"] += 1
        elif status == "skipped_opted_out":
            per_status["skipped"] += 1
        else:
            per_status["failed"] += 1
        if status in _DEDUPE_STAMPING_STATUSES:
            customers_notified.append(cid)

    stats["sms_sent"] += per_status["sent"]
    stats["sms_deferred"] += per_status["deferred"]
    stats["sms_skipped"] += per_status["skipped"]
    stats["sms_failed"] += per_status["failed"]

    # 7. Persist dispatch_events ONLY if at least one status
    #    consumed the dedupe slot. All-failed batches leave the
    #    window open so the next tick retries.
    if not customers_notified:
        return
    stats["dispatches_fired"] += 1
    await db.dispatch_events.insert_one({
        "id": new_id(),
        "tenant_id": tid,
        "tech_id": tech_id,
        "visit_id": next_visit.get("id"),
        "delay_mins": round(delay_mins, 1),
        "customers_notified": customers_notified,
        "sent_count": per_status["sent"],
        "deferred_count": per_status["deferred"],
        "skipped_count": per_status["skipped"],
        "failed_count": per_status["failed"],
        "initiated_at": now_iso(),
        "initiated_by": INITIATED_BY,
    })


# ═════════════════════════════════════════════════════════════════════
# Helpers.
# ═════════════════════════════════════════════════════════════════════
def _rules_with_defaults(tenant: Dict[str, Any]) -> Dict[str, int]:
    """Read tenant.settings.automation_rules with LDM-A canonical
    defaults. Handles both fully-missing and partially-missing
    sub-docs."""
    rules = (
        (tenant.get("settings") or {}).get("automation_rules") or {}
    )
    return {
        "dispatch_delay_threshold_mins": (
            rules.get("dispatch_delay_threshold_mins")
            if isinstance(rules.get("dispatch_delay_threshold_mins"), int)
            else _DEFAULT_DISPATCH_THRESHOLD_MINS
        ),
        "dispatch_sms_customer_count": (
            rules.get("dispatch_sms_customer_count")
            if isinstance(rules.get("dispatch_sms_customer_count"), int)
            else _DEFAULT_DISPATCH_SMS_CUSTOMER_COUNT
        ),
    }


def _visit_geo(visit: Dict[str, Any]):
    """Return (lat, lng) from the job document, prefer site_* fields
    (populated by the geocoder on insert), else legacy latitude/longitude.
    Any pair that isn't fully-numeric returns (None, None)."""
    for lat_key, lng_key in (
        ("site_lat", "site_lng"),
        ("latitude", "longitude"),
    ):
        lat = visit.get(lat_key)
        lng = visit.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return lat, lng
    return None, None


def _resolve_phone(cust: Dict[str, Any]) -> str:
    """Best-effort phone resolution — prefer top-level ``phone``
    string, fall back to first ``phones[].number`` entry."""
    p = cust.get("phone")
    if isinstance(p, str) and p.strip():
        return p.strip()
    for entry in (cust.get("phones") or []):
        if isinstance(entry, dict):
            n = entry.get("number") or entry.get("phone")
            if isinstance(n, str) and n.strip():
                return n.strip()
        elif isinstance(entry, str) and entry.strip():
            return entry.strip()
    return ""


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp — accepts trailing Z or explicit
    offset. Returns UTC-aware datetime, or None on parse failure."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _to_iso_z(dt: datetime) -> str:
    """Format ``dt`` as ISO-Z-suffixed UTC string (matches the shape
    ``gps_pings.captured_at`` uses so string comparisons are
    apples-to-apples)."""
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


def _compose_delay_sms(
    *,
    customer_name: str,
    projected_arrival: datetime,
    delay_mins: float,
) -> str:
    """MARCO-branded SMS body with the new ETA. Kept short so single-
    segment GSM-7 delivery is the common case."""
    eta_local = projected_arrival.astimezone(timezone.utc).strftime(
        "%I:%M %p UTC",
    ).lstrip("0")
    first_name = (customer_name or "there").split()[0]
    return (
        f"Hi {first_name}, this is MARCO on behalf of your service "
        f"team — your tech is running about "
        f"{int(round(delay_mins))} min behind schedule. New ETA: "
        f"{eta_local}. We appreciate your patience."
    )


__all__ = [
    "scan",
    "register_live_dispatcher_cron",
    "GPS_FRESHNESS_MINUTES",
    "DEDUPE_WINDOW_MINUTES",
    "UPCOMING_LOOKAHEAD_HOURS",
    "INITIATED_BY",
]
