"""Feb-2026 · Ticket #3 · Notification send-path gate.

Single source of truth for the four org-wide notification toggles
persisted at ``tenants.settings.notifications.*``. Every real send
path (email + SMS) MUST short-circuit through
:func:`is_org_notification_enabled` before hitting the actual
Resend / RingCentral call.

Contract:
  * Every kind defaults to ``True`` when the tenant doc has no
    ``settings.notifications.<kind>`` field.  This preserves
    backwards compatibility for tenants that pre-date Ticket #3.
  * Passing an unknown ``kind`` returns ``True`` (fail-open) so a
    typo in a call site can't silently silence a notification
    tenants haven't opted out of.  Callers should always use the
    exported :data:`NOTIFICATION_KEYS` constants.

Log format on skip:
    ``[org_settings.notification_skipped] tenant=<id> kind=<kind>``

The skip log is deliberately lightweight (INFO, one line) so ops
can grep prod logs to confirm a tenant's flag flip actually took
effect end-to-end.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger("org_settings.notifications_gate")


NOTIFICATION_KEYS = (
    "lead_confirmation",
    "tech_on_my_way",
    "job_completion_summary",
    "warranty_expiration",
)


def is_org_notification_enabled(
    tenant: Dict[str, Any], kind: str,
) -> bool:
    """Return True when the tenant permits sends of ``kind``.

    Missing ``settings.notifications.<kind>`` defaults to True.
    Unknown ``kind`` returns True (fail-open, see module docstring).
    """
    if kind not in NOTIFICATION_KEYS:
        return True
    settings = (tenant.get("settings") or {}).get("notifications") or {}
    v = settings.get(kind)
    if isinstance(v, bool):
        return v
    return True


def log_notification_skipped(tenant_id: str, kind: str) -> None:
    """One-line INFO for ops observability."""
    log.info(
        "[org_settings.notification_skipped] tenant=%s kind=%s",
        tenant_id, kind,
    )
