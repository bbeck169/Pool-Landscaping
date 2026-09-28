"""FLEET-A · Customer "on the way" notification.

Fires from ``POST /api/fleet/checkin`` with ``kind="on_the_way"``.

Design:
    * Computes ETA at fire time. If ``duration_s > 15 * 60`` we
      SKIP the notification (avoids spam for far-out arrivals; the
      tech can trigger again when closer).
    * Dedup: no more than one send per ``(tech_user_id, job_id)``
      per 4 hours. Backed by ``fleet_notification_dedup`` collection
      with a Mongo TTL index.
    * Channels: honours ``customer.email_opt_in`` /
      ``customer.sms_opt_in``. If both are True, sends both.
    * SAFE-SEND: every call passes ``context=CommsContext.SYSTEM``
      because these are rule-based, not agent-generated.
    * Never raises — failures are logged and returned in the
      response payload so the checkin endpoint can surface them
      as JSON warnings.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from config import db, logger
from services.comms_email_adapter import send_email
from services.comms_env_guard import CommsContext
from services.comms_sms_adapter import send_sms
from services.fleet.eta import compute_eta, ETAResult
from utils import new_id, now_iso

_MAX_NOTIFY_MINUTES = 15
_DEDUP_WINDOW_HOURS = 4


@dataclass
class NotifyOutcome:
    """Return shape for both the checkin endpoint + the tests."""
    sent: bool
    reason: Optional[str] = None          # "sent" | "eta_too_far" | ...
    eta_minutes: Optional[int] = None
    channels: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None


async def _dedup_recent(tenant_id: str, tech_user_id: str,
                          job_id: str) -> bool:
    """True when a dedup row exists inside the 4h window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUP_WINDOW_HOURS)
    row = await db.fleet_notification_dedup.find_one({
        "tenant_id": tenant_id,
        "tech_user_id": tech_user_id,
        "job_id": job_id,
        "sent_at_dt": {"$gte": cutoff},
    })
    return row is not None


async def _record_dedup(tenant_id: str, tech_user_id: str,
                          job_id: str) -> None:
    now = datetime.now(timezone.utc)
    await db.fleet_notification_dedup.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "tech_user_id": tech_user_id,
        "job_id": job_id,
        "sent_at": now.isoformat().replace("+00:00", "Z"),
        # A datetime-typed sentinel too, so the TTL index on
        # ``sent_at_dt`` can auto-purge stale rows in Mongo.
        "sent_at_dt": now,
    })


def _first_name(name: Optional[str]) -> str:
    if not name:
        return "there"
    return (name.split() or ["there"])[0]


async def _load_context(
    tenant_id: str, tech_user_id: str, job_id: str,
) -> Dict[str, Any]:
    """Load customer + tech + job records used for template
    rendering. Never raises — returns empty dicts on miss."""
    job = await db.jobs.find_one(
        {"id": job_id, "tenant_id": tenant_id},
        {"_id": 0},
    ) or {}
    customer = {}
    if job.get("customer_id"):
        customer = await db.customers.find_one(
            {"id": job["customer_id"], "tenant_id": tenant_id},
            {"_id": 0},
        ) or {}
    tech = await db.users.find_one(
        {"id": tech_user_id, "tenant_id": tenant_id},
        {"_id": 0},
    ) or {}
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0},
    ) or {}
    return {"job": job, "customer": customer, "tech": tech, "tenant": tenant}


def _job_coords(job: Dict[str, Any]) -> Optional[tuple]:
    """Best-effort geo pick — job.latitude/longitude wins, then
    job.site_lat/lng, then job.lat/lng. Returns ``None`` if no
    coordinates are available."""
    for lat_key, lng_key in (
        ("latitude", "longitude"),
        ("site_lat", "site_lng"),
        ("lat", "lng"),
    ):
        lat, lng = job.get(lat_key), job.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    return None


async def maybe_send_on_the_way(
    *,
    tenant_id: str,
    tech_user_id: str,
    job_id: str,
    tech_lat: Optional[float],
    tech_lng: Optional[float],
) -> NotifyOutcome:
    """Compute ETA, decide, dedup, dispatch. Returns an outcome
    dict the checkin endpoint can echo verbatim.
    """
    # Load the pieces we need for template rendering + geocoding.
    ctx = await _load_context(tenant_id, tech_user_id, job_id)
    job = ctx["job"]
    customer = ctx["customer"]
    tenant = ctx["tenant"]
    tech = ctx["tech"]
    if not job or not customer:
        return NotifyOutcome(sent=False, reason="missing_context")

    coords = _job_coords(job)
    if not coords or tech_lat is None or tech_lng is None:
        return NotifyOutcome(sent=False, reason="missing_coordinates")

    eta = await compute_eta(
        tech_lat, tech_lng, coords[0], coords[1],
    )
    eta_minutes = int(round(eta.duration_s / 60.0))
    if eta_minutes > _MAX_NOTIFY_MINUTES:
        logger.info(
            "[fleet.notify] skip — eta_minutes=%s > %s (tenant=%s job=%s)",
            eta_minutes, _MAX_NOTIFY_MINUTES, tenant_id, job_id,
        )
        return NotifyOutcome(
            sent=False, reason="eta_too_far",
            eta_minutes=eta_minutes, provider=eta.provider,
        )

    # Dedup — one send per (tech, job) per 4h.
    if await _dedup_recent(tenant_id, tech_user_id, job_id):
        logger.info(
            "[fleet.notify] skip — dedup window active (tenant=%s tech=%s job=%s)",
            tenant_id, tech_user_id, job_id,
        )
        return NotifyOutcome(
            sent=False, reason="dedup_within_window",
            eta_minutes=eta_minutes, provider=eta.provider,
        )

    # Render template.
    company = (
        (tenant.get("branding") or {}).get("display_name")
        or tenant.get("name") or "your service provider"
    )
    tech_first = _first_name(tech.get("name") or tech.get("display_name"))
    cust_first = _first_name(customer.get("name") or customer.get("first_name"))
    address = (
        job.get("service_address") or job.get("address")
        or (customer.get("service_address") or "your location")
    )
    subject = f"Your {company} tech is on the way"
    text_body = (
        f"Hi {cust_first}, {tech_first} is {eta_minutes} minute"
        f"{'' if eta_minutes == 1 else 's'} away and headed to {address}."
    )
    html_body = (
        f"<p>Hi {cust_first},</p>"
        f"<p>{tech_first} is <strong>{eta_minutes} minute"
        f"{'' if eta_minutes == 1 else 's'}</strong> away and headed to "
        f"<strong>{address}</strong>.</p>"
    )

    channels: Dict[str, Any] = {}

    email_opt_in = customer.get("email_opt_in")
    if email_opt_in is None:
        # Fallback for older customers with no explicit preference —
        # default to opt-in for transactional SYSTEM comms so we
        # don't silently swallow the notification.
        email_opt_in = True
    if email_opt_in and customer.get("email"):
        channels["email"] = await send_email(
            tenant_id=tenant_id,
            to_email=customer["email"],
            subject=subject,
            html=html_body,
            context=CommsContext.SYSTEM,
        )
    else:
        channels["email"] = {"status": "skipped_opt_out_or_missing"}

    sms_opt_in = customer.get("sms_opt_in")
    phone = customer.get("phone") or customer.get("mobile") or (
        (customer.get("mobiles") or [{}])[0].get("number_e164")
        if customer.get("mobiles") else None
    )
    if sms_opt_in and phone:
        channels["sms"] = await send_sms(
            tenant_id=tenant_id,
            to_phone=phone,
            body=text_body,
            context=CommsContext.SYSTEM,
        )
    else:
        channels["sms"] = {"status": "skipped_opt_out_or_missing"}

    await _record_dedup(tenant_id, tech_user_id, job_id)
    logger.info(
        "[fleet.notify] sent tenant=%s tech=%s job=%s eta=%sm provider=%s "
        "email_status=%s sms_status=%s",
        tenant_id, tech_user_id, job_id, eta_minutes, eta.provider,
        (channels.get("email") or {}).get("status"),
        (channels.get("sms") or {}).get("status"),
    )
    return NotifyOutcome(
        sent=True, reason="sent",
        eta_minutes=eta_minutes, channels=channels,
        provider=eta.provider,
    )
