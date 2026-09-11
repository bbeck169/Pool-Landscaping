"""Feb-2026 · Phase 1 — Tech "On my way" SMS endpoint.

POST /api/jobs/{job_id}/on-my-way

One-tap SMS notification from a technician (or a dispatcher acting on
their behalf) to the customer, with an auto-computed ETA when the
caller supplies their live coordinates.

Design invariants:
    * Auth: JWT-authenticated. Role in {technician, manager, admin,
      super_admin}. Portal/customer roles → 403.
    * Body is server-rendered. Clients cannot supply the SMS body.
    * Once-per-job-per-day guard: if a ``communications`` row already
      exists for the same job on the same tenant-local day with
      ``template_key="tech_on_my_way"``, the endpoint returns
      ``{sent: false, reason: "already_sent_today"}`` (200, not 4xx —
      the UI renders a friendly toast).
    * All environment gates (``APP_ENV`` / ``RC_OUTBOUND_ENABLED`` /
      demo whitelist) are respected via ``is_comm_allowed``. If the
      gate blocks, the endpoint returns ``{sent: false,
      reason: "outbound_disabled"}`` and inserts no row.

Reuses:
    * ``services.comms_sms_adapter.send_sms`` (RingCentral).
    * ``services.google_maps.directions.compute_route_no_optimize``
      (Google Routes v2) for the ETA.
    * ``services.comms.gate.is_comm_allowed`` for prod/demo policy.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant


router = APIRouter()


_ALLOWED_ROLES = {"technician", "manager", "admin", "super_admin"}
_ETA_CAP_MINUTES = 90
_TEMPLATE_KEY = "tech_on_my_way"


class OnMyWayBody(BaseModel):
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    # Mobile Phase 2 · Feb-2026 — the flush worker tags each replay
    # with the timestamp at which the tech originally hit the "On
    # my way" button (ISO8601 UTC). Absent / malformed values fall
    # through as a normal (non-delayed) send.
    queued_at: Optional[str] = None


def _short_street(addr: Optional[str]) -> str:
    """Strip city/state/zip from a formatted address, keeping just the
    street portion for the SMS body. Falls back to the raw string when
    the address has no comma."""
    if not addr:
        return ""
    return str(addr).split(",", 1)[0].strip()


def _first_name(record: Dict[str, Any], fallback_key: str = "name") -> str:
    """Best-effort first-name extraction from a customer/user doc."""
    first = (record.get("first_name") or "").strip()
    if first:
        return first
    full = (record.get(fallback_key) or "").strip()
    return full.split(" ", 1)[0] if full else ""


def _company_name(tenant: Dict[str, Any]) -> str:
    """``tenants.company_name`` takes precedence; falls back to
    ``tenants.name``."""
    return (tenant.get("company_name") or tenant.get("name") or "").strip()


async def _lookup_property_and_address(job: Dict[str, Any],
                                          customer: Dict[str, Any],
                                          tenant_id: str) -> Dict[str, Any]:
    """Return a dict with best-effort ``lat``, ``lng``, ``address_short``
    and ``address_full``. Reads from the property doc when the job has
    a ``property_id``; otherwise falls back to the customer's stored
    address / coordinates.
    """
    prop = None
    pid = job.get("property_id") or customer.get("primary_property_id")
    if pid:
        prop = await db.properties.find_one(
            {"id": pid, "tenant_id": tenant_id}, {"_id": 0},
        )
    addr = None
    lat = lng = None
    if prop:
        addr_obj = prop.get("address") or {}
        addr = " ".join(
            (addr_obj.get(k) or "").strip()
            for k in ("line1", "line2", "city", "state", "postal_code")
            if addr_obj.get(k)
        ).strip() or None
        # Comma-separated form for parity with the customer.address shape.
        parts = [addr_obj.get(k) for k in ("line1", "city", "state") if addr_obj.get(k)]
        if parts:
            addr = ", ".join(parts)
        lat = prop.get("lat") or (prop.get("coords") or {}).get("lat")
        lng = prop.get("lng") or (prop.get("coords") or {}).get("lng")
    if not addr:
        addr = (customer.get("address") or "").strip() or None
    if lat is None or lng is None:
        lat = customer.get("lat")
        lng = customer.get("lng")
    return {
        "lat": float(lat) if lat is not None else None,
        "lng": float(lng) if lng is not None else None,
        "address_full": addr,
        "address_short": _short_street(addr),
    }


async def _already_sent_today(tenant_id: str, job_id: str) -> bool:
    """Once-per-job-per-day guard. Uses a naive UTC-day window; a
    tenant-local day would need the tenant timezone which not every
    tenant doc carries — UTC is close enough for a first ship and
    matches how the existing ``communications`` timeline aggregates."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return bool(await db.communications.find_one({
        "tenant_id": tenant_id,
        "job_id": job_id,
        "channel": "sms",
        "template_key": _TEMPLATE_KEY,
        "sent_at": {"$gte": day_start.isoformat()},
    }, {"_id": 0, "id": 1}))


async def _eta_minutes(origin_lat: Optional[float],
                        origin_lng: Optional[float],
                        dest_lat: Optional[float],
                        dest_lng: Optional[float],
                        tenant_id: str) -> Optional[int]:
    """Google Routes v2 point-to-point ETA in minutes; ``None`` when
    either endpoint is missing coordinates or the API call fails.

    Chunk 3 · Feb-2026 — ``tenant_id`` is threaded so the call routes
    through the BYO Maps dispatcher when ``MAPS_BYO_ENABLED=true``."""
    if (origin_lat is None or origin_lng is None
            or dest_lat is None or dest_lng is None):
        return None
    try:
        from services.google_maps.directions import compute_route_no_optimize
        route = await compute_route_no_optimize(
            (origin_lat, origin_lng),
            [(dest_lat, dest_lng)],
            tenant_id=tenant_id,
        )
    except Exception as e:  # pragma: no cover — network path
        logger.warning("[on_my_way] directions API failed: %s", e)
        return None
    if not route:
        return None
    secs = int(route.get("total_duration_s") or 0)
    if secs <= 0:
        return None
    mins = max(1, round(secs / 60))
    return min(mins, _ETA_CAP_MINUTES)


def _render_body(customer_first: str, tech_first: str, company: str,
                  address_short: str, eta_minutes: Optional[int]) -> str:
    """Server-side template renderer. Clients cannot supply the body."""
    prefix = f"Hi {customer_first}, this is {tech_first} from {company}."
    where = f" I'm on my way to {address_short}." if address_short else " I'm on my way."
    if eta_minutes:
        where = where.rstrip(".") + f" and should arrive in about {eta_minutes} minutes."
    return f"{prefix}{where} Reply STOP to opt out."


@router.post("/jobs/{job_id}/on-my-way")
async def on_my_way(
    job_id: str,
    body: OnMyWayBody,
    request: Request,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    # Phase O4 · Feb-2026 — Idempotency wiring.  A tech tapping the
    # "On my way" button while the mobile SMS gate is still loading
    # can double-fire the request; the queue also replays if the
    # response was lost.  Cached response wins the whole path so the
    # once-per-job-per-day guard is only exercised on the FIRST call.
    from utils_idempotency import replay_or_reserve, store_response
    idem_body = body.dict(exclude_unset=False)
    idem_key, cached = await replay_or_reserve(
        request, tenant["id"], "POST /jobs/{jid}/on-my-way", idem_body,
    )
    if cached is not None:
        return cached

    async def _sar(_resp: dict) -> dict:
        if idem_key:
            await store_response(idem_key, "POST /jobs/{jid}/on-my-way",
                                  tenant["id"], _resp, idem_body)
        return _resp

    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ROLES:
        raise HTTPException(403, "role not permitted")

    tid = tenant["id"]
    job = await db.jobs.find_one({"id": job_id, "tenant_id": tid}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "job not found")

    # Mobile Phase 2 · Feb-2026 — suppress-if-advanced. When the
    # queued op finally flushes we may find the job has since moved
    # past in-progress (completed by someone else, cancelled, etc).
    # Send would be misleading, so return ``suppressed=true`` and
    # let mobile mark the queued op discarded in Sync Center.
    from services.mobile_offline_sync import (
        is_delayed_queued_at,
        job_is_past_in_progress,
        DELAYED_ON_MY_WAY_SUFFIX,
    )
    if job_is_past_in_progress(job):
        return await _sar({
            "sent": False,
            "suppressed": True,
            "reason": "job_already_advanced",
        })

    tech_id = job.get("technician_id") or job.get("tech_user_id")
    if not tech_id:
        raise HTTPException(422, "job has no assigned technician")
    tech = await db.users.find_one(
        {"$or": [
            {"id": tech_id, "tenant_id": tid},
            {"technician_id": tech_id, "tenant_id": tid},
        ]}, {"_id": 0})
    if not tech:
        raise HTTPException(422, "assigned technician not found")

    cust = await db.customers.find_one(
        {"id": job.get("customer_id"), "tenant_id": tid}, {"_id": 0})
    if not cust:
        raise HTTPException(422, "customer not found for job")

    # Guardrails (200 with reason, not 4xx).
    if cust.get("is_demo") or cust.get("demo"):
        return await _sar({"sent": False, "reason": "customer_blocked"})
    if cust.get("blocked") or cust.get("is_blocked"):
        return await _sar({"sent": False, "reason": "customer_blocked"})
    if cust.get("sms_opt_in") is False:
        return await _sar({"sent": False, "reason": "sms_opt_in_false"})
    phone = (cust.get("phone")
             or (cust.get("mobiles") or [{}])[0].get("number_e164"))
    if not phone:
        return await _sar({"sent": False, "reason": "no_phone"})
    if await _already_sent_today(tid, job_id):
        return await _sar({"sent": False, "reason": "already_sent_today"})

    # ETA (best-effort).
    prop = await _lookup_property_and_address(job, cust, tid)
    eta_min = await _eta_minutes(
        body.origin_lat, body.origin_lng,
        prop["lat"], prop["lng"],
        tid,
    )

    # Body render.
    sms_body = _render_body(
        customer_first=_first_name(cust) or "there",
        tech_first=_first_name(tech) or "your technician",
        company=_company_name(tenant) or "our team",
        address_short=prop["address_short"],
        eta_minutes=eta_min,
    )
    # Mobile Phase 2 · Feb-2026 — delayed-send transparency. When
    # the tech's tap sat in the offline queue for more than 10 min
    # before the network came back, append a short suffix so the
    # customer isn't confused by a "coming now" message that
    # arrives 40 min late.
    if is_delayed_queued_at(body.queued_at):
        sms_body = sms_body + DELAYED_ON_MY_WAY_SUFFIX

    # Env / demo gate.
    from services.comms.gate import is_comm_allowed
    allowed = await is_comm_allowed(
        recipient_identifier=phone,
        comm_type="sms",
        tenant_id=tid,
        provider="ringcentral",
        trigger_action="tech_on_my_way",
    )
    if not allowed:
        logger.warning(
            "[on_my_way] outbound gate blocked send tenant=%s job=%s user=%s",
            tid, job_id, user.get("id"),
        )
        return await _sar({"sent": False, "reason": "outbound_disabled"})

    # Backlog #iv · Feb-2026 — Customer-facing deny-list guardrail.
    # Ensures no admin/workforce/tenant-owned phone ever receives a
    # customer-facing SMS even if the customer record was corrupted
    # or the ``COMMS_TEST_ALLOWLIST_PHONES`` env is misconfigured.
    from services.comms_hardening.deny_list import (
        strip_admin_owned_recipients,
    )
    kept, stripped = await strip_admin_owned_recipients(
        tenant_id=tid, kind="customer_facing", channel="sms",
        recipients=[phone],
        context={"trigger": "on_my_way", "job_id": job_id,
                  "customer_id": (cust or {}).get("id")},
    )
    if stripped:
        # The one and only recipient was an admin-owned line — block.
        return await _sar({"sent": False, "reason": "denied_admin_owned_recipient",
                "stripped": stripped})
    phone = kept[0] if kept else phone

    # Real / mocked send.
    from services.comms_sms_adapter import send_sms
    result = await send_sms(tid, phone, sms_body)
    status = result.get("status")
    provider_id = result.get("provider_id")
    if status in ("failed",):
        logger.warning(
            "[on_my_way] send failed tenant=%s job=%s error=%s",
            tid, job_id, result.get("error"),
        )
        return await _sar({"sent": False, "reason": "send_failed"})

    # Communications row.
    now = now_iso()
    comm_id = new_id()
    doc = {
        "id": comm_id,
        "tenant_id": tid,
        "customer_id": cust["id"],
        "job_id": job_id,
        "channel": "sms",
        "direction": "outbound",
        "template_key": _TEMPLATE_KEY,
        "body": sms_body,
        "to": phone,
        "sent_by_user_id": user.get("id"),
        "sent_at": now,
        "status": "sent" if status in ("sent", "mocked") else "queued",
        "provider_message_id": provider_id,
    }
    await db.communications.insert_one(doc)
    logger.info(
        "[on_my_way] sent tenant=%s job=%s customer=%s comm=%s eta=%s status=%s",
        tid, job_id, cust["id"], comm_id, eta_min, status,
    )
    return await _sar({
        "sent": True,
        "eta_minutes": eta_min,
        "communication_id": comm_id,
    })
