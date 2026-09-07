"""Phase I1.7.d · Feb-2026 — Unified tenant-provider health service.

One collection, one worker, one shape — covering AI, Maps, Calendars,
and Payments BYO. Front-end reads ``GET /tenants/me/integrations``
(which now embeds the latest health snapshot alongside each
``ConnectionSummary``).
"""
from __future__ import annotations

from .store import (
    HEALTH_COLLECTION,
    get_health,
    get_health_map_for_tenant,
    record_probe,
    upsert_health,
)
from .cron import (
    HEALTH_CRON_INTERVAL_SECONDS,
    provider_families,
    run_health_cycle_once,
    start_health_cron,
)

__all__ = [
    "HEALTH_COLLECTION", "HEALTH_CRON_INTERVAL_SECONDS",
    "get_health", "get_health_map_for_tenant", "record_probe",
    "upsert_health",
    "provider_families", "run_health_cycle_once", "start_health_cron",
]
