"""Feb-2026 · Public check-in auto-enqueue helpers.

Called from ``routers/jobs.py`` right after a job flips to
``status='completed'``. Adds an ADDITIVE surface: existing
tech-initiated ``POST /api/checkins/{id}/submit-public`` still
works unchanged (rows land with ``source='tech'``); jobs that
complete without a tech submission ALSO produce a moderation-queue
row automatically (``source='auto'``).

Tenant setting gate:
  ``tenants.settings.auto_enqueue_public_checkins`` (bool)
  * ``True`` OR missing → auto-enqueue on completion.
  * ``False``           → do nothing.

Idempotency:
  * Unique compound index on ``(tenant_id, source_job_id)`` means
    a re-flip on the same job is a no-op via ``DuplicateKeyError``.
  * We ALSO short-circuit before insert if the row already exists,
    to avoid a noisy exception log on the happy path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from config import db
from services.coord_obfuscator import obfuscate_coords
from utils import new_id, now_iso

logger = logging.getLogger("services.public_checkin_enqueue")


AUTO_ENQUEUE_SETTING = "auto_enqueue_public_checkins"


def _month_year(iso_ts: Optional[str]) -> str:
    """Convert an ISO timestamp to a public-safe ``"Month YYYY"``
    string. Never leaks a specific day."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime  # noqa: PLC0415 — local
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return ""


def _area_label(cust: Dict[str, Any]) -> str:
    """Best-effort "Peoria, AZ" label. Falls back to whatever
    city/state fields exist on the customer row — matches the
    heterogeneity of the ``customers`` collection today."""
    city = (cust.get("address_city") or cust.get("city")
              or (cust.get("property") or {}).get("city") or "")
    state = (cust.get("address_state") or cust.get("state")
               or (cust.get("property") or {}).get("state") or "")
    city = str(city).strip()
    state = str(state).strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


async def _tenant_auto_enabled(tenant_id: str) -> bool:
    """Read the per-tenant feature flag. Default: True (opt-out)."""
    if not tenant_id:
        return False
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "settings": 1},
    )
    if not tenant:
        return False
    settings = tenant.get("settings") or {}
    val = settings.get(AUTO_ENQUEUE_SETTING)
    if val is None:
        return True
    return bool(val)


async def enqueue_public_checkin_for_completed_job(
    job: Dict[str, Any],
    *,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert a ``pending_review`` row on
    ``db.public_checkins`` for ``job`` if:

      * The tenant has ``auto_enqueue_public_checkins`` on
        (or unset — default on).
      * No prior row exists for this ``source_job_id``.
      * The job has a resolvable ``customer_id``.

    Never raises. Returns a summary dict:

        {"enqueued": bool, "reason": str, "public_checkin_id": str?}
    """
    tenant_id = job.get("tenant_id")
    job_id = job.get("id")
    customer_id = job.get("customer_id")
    if not tenant_id or not job_id:
        return {"enqueued": False, "reason": "missing_ids"}

    if not await _tenant_auto_enabled(tenant_id):
        return {"enqueued": False, "reason": "tenant_setting_off"}

    # Idempotency: match on ``(tenant_id, source_job_id)``.
    prior = await db.public_checkins.find_one(
        {"tenant_id": tenant_id, "source_job_id": job_id},
        {"_id": 0, "id": 1, "state": 1, "source": 1},
    )
    if prior:
        return {"enqueued": False,
                 "reason": "already_enqueued",
                 "public_checkin_id": prior.get("id"),
                 "existing_state": prior.get("state"),
                 "existing_source": prior.get("source")}

    # Load customer for coords + area label.
    cust: Dict[str, Any] = {}
    if customer_id:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "latitude": 1, "longitude": 1,
             "address_city": 1, "address_state": 1,
             "city": 1, "state": 1, "property": 1,
             "id": 1},
        ) or {}

    lat_raw = cust.get("latitude")
    lng_raw = cust.get("longitude")
    if lat_raw is None or lng_raw is None:
        # No geocode → no pin. Log at DEBUG and skip — this is the
        # normal state for customers still awaiting geocoding
        # (Phase 17 backfill is fire-and-forget).
        logger.debug(
            "auto-enqueue skipped: job=%s customer=%s missing coords",
            job_id, customer_id,
        )
        return {"enqueued": False, "reason": "no_customer_coords"}

    lat_public, lng_public = obfuscate_coords(
        lat_raw, lng_raw, seed=str(job_id),
    )
    area_label = _area_label(cust)
    completed_at = (job.get("completed_at")
                     or job.get("closed_at")
                     or now_iso())
    completed_at_month_year = _month_year(completed_at)

    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        # ``source_checkin_id`` is the compound key of the
        # ``tenant_source_unique`` index. Tech-submitted rows set it
        # to the underlying check-in id; auto rows have no check-in,
        # so we DERIVE a stable, unique-per-job token to avoid
        # colliding on ``(tenant_id, null)`` — the index is NOT sparse,
        # so multiple ``None`` values would raise E11000 and cap us at
        # one auto row per tenant forever.
        "source_checkin_id": f"auto:{job_id}",
        "source_job_id": job_id,
        "source": "auto",                    # discriminator vs 'tech'
        "submitted_by_user_id": actor_user_id,
        "submitted_at": now_iso(),
        "state": "pending_review",
        "photo_license_ack": False,          # no photos in auto-enqueue
        "service_name": job.get("service_type") or "",
        "service_category": (job.get("service_category")
                              or "").strip().lower() or None,
        "description": "",
        "tags": [],
        "photos": [],
        "raw_address": {},                   # not needed for pin
        "masked_address": None,
        # ── Map-specific fields (new, Feb-2026) ────────────────────
        "lat_raw": lat_raw,                  # admin view only
        "lng_raw": lng_raw,                  # admin view only
        "lat_public": lat_public,            # public map endpoint
        "lng_public": lng_public,
        "area_label": area_label,
        "completed_at": completed_at,
        "completed_at_month_year": completed_at_month_year,
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "reviewer_notes": None,
        "approved_at": None,
        "approved_by_user_id": None,
        "unpublished_at": None,
        "unpublished_by_user_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    try:
        await db.public_checkins.insert_one(row)
    except Exception as exc:  # noqa: BLE001 — never break the caller
        # DuplicateKeyError from ``tenant_source_unique`` is treated
        # as a benign idempotency retry — but we still LOG it at
        # WARN so a systemic collision surfaces in error dashboards
        # (silently swallowing E11000 previously masked a real bug
        # where every auto row landed on the same ``(tenant_id, null)``
        # key).
        msg = str(exc).lower()
        if "duplicate" in msg or "e11000" in msg:
            logger.warning(
                "public_checkin auto-enqueue hit duplicate key "
                "(likely retry): tenant=%s job=%s source_checkin_id=%s: %s",
                tenant_id, job_id, row.get("source_checkin_id"), exc,
            )
            return {"enqueued": False, "reason": "duplicate_race"}
        logger.warning("public_checkin auto-enqueue insert failed: %s", exc)
        return {"enqueued": False, "reason": "insert_error"}

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "event": "public_checkin_auto_enqueued",
            "email": None,
            "ip_address": None,
            "status": "success",
            "details": (f"public_id={row['id']} job={job_id} "
                          f"lat_public={lat_public} "
                          f"lng_public={lng_public}"),
            "tenant_id": tenant_id,
            "created_at": now_iso(),
        })
    except Exception as exc:  # pragma: no cover — audit-only
        logger.warning("audit insert for auto-enqueue failed: %s", exc)

    return {"enqueued": True,
             "reason": "ok",
             "public_checkin_id": row["id"]}
