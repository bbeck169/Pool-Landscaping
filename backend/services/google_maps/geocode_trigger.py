"""P0-GEOCODE-LEAK-C2 · TD-62 (Feb-2026).

Append-only call-log instrumentation for every `geocode_address` + its
`geocode_and_persist_*` wrappers.  Phase 2 adds the enum + log writer
in a single pure-instrumentation commit; Phase 3 will consume the
telemetry to tune ``_CACHE_TTL_DAYS`` + the ``migration_status``
sentinel on the boot sweep.

Three public symbols:

  * :class:`GeocodeTrigger` — enum of ``trigger_reason`` values that
    propagate from every caller (routers / lifespan tasks / admin
    backfill endpoints) down to :func:`services.google_maps.geocoding.geocode_address`.
  * :class:`GeocodeOutcome` — enum of ``outcome`` values emitted at
    log-write time.  ``skipped_unchanged`` is reserved for Phase 3
    (hash-based short-circuit); the current implementation emits
    only ``no_addr``, ``skipped_cached``, ``hit``, and ``error``.
  * :func:`write_geocode_log` — fail-safe async helper that inserts
    one row into ``db.geocode_call_log``.  Any exception from the
    Mongo write is swallowed with a WARNING log — a telemetry
    outage must NEVER block the geocode path.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class GeocodeTrigger(str, Enum):
    """Canonical ``trigger_reason`` values.  Every call-site passes
    one; routers that haven't been updated yet fall through to
    :attr:`UNKNOWN` which flags a telemetry gap for cleanup."""

    PROPERTY_CREATE = "property_create"
    PROPERTY_PATCH_ADDR_CHANGE = "property_patch_addr_change"
    CUSTOMER_CREATE = "customer_create"
    CUSTOMER_PATCH_ADDR_CHANGE = "customer_patch_addr_change"
    LEAD_CREATE_PUBLIC = "lead_create_public"
    LEAD_CREATE_SENSE_CONVERT = "lead_create_sense_convert"
    CSV_IMPORT = "csv_import"
    MANUAL_REGEOCODE = "manual_regeocode"
    ADMIN_BACKFILL = "admin_backfill"
    BOOT_SWEEP = "boot_sweep"
    OPERATOR_FORCE = "operator_force"
    TENANT_HQ_PATCH = "tenant_hq_patch"
    AI_MEASURE_RESOLVE = "ai_measure_resolve"
    UNKNOWN = "unknown"


class GeocodeOutcome(str, Enum):
    """Outcome tag written to ``db.geocode_call_log`` per call."""

    HIT = "hit"
    SKIPPED_CACHED = "skipped_cached"
    SKIPPED_UNCHANGED = "skipped_unchanged"   # reserved for C3
    NO_ADDR = "no_addr"
    ERROR = "error"


# ─────────────────────────────────────────────────────────────────
# BACKEND vs USER split for the diagnostics endpoint.
# ─────────────────────────────────────────────────────────────────
# "backend" = fired by a lifespan task / cron / admin backfill
# "user" = fired by a user-visible save flow or operator click
_BACKEND_TRIGGERS = frozenset({
    GeocodeTrigger.BOOT_SWEEP.value,
    GeocodeTrigger.ADMIN_BACKFILL.value,
    GeocodeTrigger.CSV_IMPORT.value,
    GeocodeTrigger.MANUAL_REGEOCODE.value,
})


def is_backend_trigger(trigger_reason: str) -> bool:
    """Return True if ``trigger_reason`` is a backend/batch origin,
    False if user-triggered.  Unknown trigger_reasons are classified
    as backend so untraced calls don't under-count the leak side."""
    return trigger_reason in _BACKEND_TRIGGERS or trigger_reason == GeocodeTrigger.UNKNOWN.value


# ─────────────────────────────────────────────────────────────────
# Address hashing — shared with the ``geocode_address_hash`` field
# that routers write on customer/property save paths.  Keeps the
# diagnostics ``address_hash`` column join-able across the log + the
# persisted entity docs.
# ─────────────────────────────────────────────────────────────────
def hash_address(address: str) -> str:
    """SHA-256 hex digest of the trimmed/lowercased address.  Empty
    input → empty string so the log row can still land."""
    if not address:
        return ""
    return hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────
# Fail-safe log writer.
# ─────────────────────────────────────────────────────────────────
async def write_geocode_log(
    *,
    db_conn: Any,
    logger: Any,
    tenant_id: Optional[str],
    entity_type: str,
    entity_id: Optional[str],
    address: str,
    trigger_reason: str,
    outcome: str,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    api_key: Optional[str] = None,
) -> None:
    """Insert one row into ``db.geocode_call_log``.  Never raises.

    * ``started_at`` — if provided, ``duration_ms`` is computed; else
      stored as ``None``.
    * ``api_key`` — only the last 4 chars are stored (fingerprint for
      key-rotation attribution).  Pass ``None`` or empty to skip.
    """
    try:
        now = datetime.now(timezone.utc)
        duration_ms: Optional[int] = None
        if started_at is not None:
            try:
                duration_ms = int(
                    (now - started_at).total_seconds() * 1000,
                )
            except Exception:
                duration_ms = None
        fingerprint: Optional[str] = None
        if api_key:
            k = (api_key or "").strip()
            if len(k) >= 4:
                fingerprint = k[-4:]
        row = {
            "tenant_id": tenant_id,
            "entity_type": entity_type or "unknown",
            "entity_id": entity_id,
            "address": (address or "")[:512],       # cap to prevent runaway rows
            "address_hash": hash_address(address),
            "trigger_reason": trigger_reason or GeocodeTrigger.UNKNOWN.value,
            "outcome": outcome or GeocodeOutcome.ERROR.value,
            "lat": lat,
            "lng": lng,
            "error": (error or None),
            "called_at": now,
            "duration_ms": duration_ms,
            "api_key_fingerprint": fingerprint,
        }
        await db_conn.geocode_call_log.insert_one(row)
    except Exception as e:        # pragma: no cover — defensive
        try:
            logger.warning(
                "[geocode-call-log] insert failed (telemetry only, "
                "geocode result unaffected): %s", e,
            )
        except Exception:
            pass
