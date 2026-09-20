"""Phase A1 · Feb-2026 · Proactive Intelligence — alert store helper.

Central write helper for the ``intelligence_alerts`` collection.
Producers (A1 missed-service, and later A2 chemistry upsell / A3
churn risk / A4 renewal) all funnel through :func:`emit_alert` so
the schema, dedup semantics, and audit hygiene are consistent.

Idempotency contract
--------------------
* ``alert_key`` is a caller-supplied stable dedup key
  (recommended shape: ``<category>:<entity>:<id>:<scope>``, e.g.
  ``missed_service:job:{job_id}:2026-02-14``).
* A unique compound index on ``(tenant_id, alert_key)`` (installed
  by :func:`ensure_indexes`) collapses re-emits into a no-op — the
  first alert for a given key wins.
* Callers get back ``(inserted: bool, doc: dict)``. When
  ``inserted=False`` the collision is a normal dedup event — do
  NOT log it as an error.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import DuplicateKeyError

from config import db

logger = logging.getLogger("intelligence.alerts")

ALLOWED_SEVERITIES = ("urgent", "recommended", "info")
ALLOWED_CATEGORIES = (
    "missed_service",     # A1
    "chemistry_upsell",   # A2
    "churn_risk",         # A3
    "renewal_due",        # A4
)


async def ensure_indexes() -> None:
    """Create the tenant-scoped and dedup indexes. Idempotent — Motor
    silently skips when the index already exists at the same key
    pattern. Called from the app boot alongside the other
    ``ensure_indexes`` helpers."""
    # Compound: recent unread alerts per tenant.
    await db.intelligence_alerts.create_index(
        [("tenant_id", 1), ("dismissed_at", 1),
         ("created_at", -1)],
        name="intel_alerts_by_tenant_time",
    )
    # Compound: read-state filter (unread stream).
    await db.intelligence_alerts.create_index(
        [("tenant_id", 1), ("read_at", 1), ("created_at", -1)],
        name="intel_alerts_by_read_state",
    )
    # Unique dedup — one alert per (tenant, alert_key). Producers
    # rely on the constraint to make :func:`emit_alert` idempotent.
    await db.intelligence_alerts.create_index(
        [("tenant_id", 1), ("alert_key", 1)],
        name="intel_alerts_dedup", unique=True,
    )
    # Category filter (chip filter on the full-list page).
    await db.intelligence_alerts.create_index(
        [("tenant_id", 1), ("category", 1), ("created_at", -1)],
        name="intel_alerts_by_category",
    )


async def emit_alert(
    tenant_id: str,
    *,
    category: str,
    severity: str,
    alert_key: str,
    title: str,
    body: str,
    customer_id: Optional[str] = None,
    job_id: Optional[str] = None,
    actor_context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Insert an alert or dedup against an existing one.

    :returns: ``(inserted, doc)`` — ``inserted=True`` on first
        write, ``False`` when the unique dedup index rejected the
        insert (this is a NORMAL outcome, not an error).
    """
    if not tenant_id:
        raise ValueError("emit_alert: tenant_id is required")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(
            f"emit_alert: unknown category {category!r}. "
            f"Allowed: {ALLOWED_CATEGORIES}"
        )
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"emit_alert: unknown severity {severity!r}. "
            f"Allowed: {ALLOWED_SEVERITIES}"
        )
    if not alert_key:
        raise ValueError("emit_alert: alert_key is required")
    doc = {
        "tenant_id":       tenant_id,
        "alert_key":       alert_key,
        "severity":        severity,
        "category":        category,
        "title":           title or "",
        "body":            body or "",
        "customer_id":     customer_id,
        "job_id":          job_id,
        "actor_context":   dict(actor_context or {}),
        "created_at":      datetime.now(timezone.utc),
        "read_at":         None,
        "dismissed_at":    None,
        "acknowledged_by": None,
    }
    try:
        await db.intelligence_alerts.insert_one(doc)
        return True, doc
    except DuplicateKeyError:
        # Dedup — normal path.
        existing = await db.intelligence_alerts.find_one(
            {"tenant_id": tenant_id, "alert_key": alert_key},
        )
        return False, existing or doc
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "emit_alert failed tenant=%s category=%s key=%s: %s",
            tenant_id, category, alert_key, exc,
        )
        return False, doc
