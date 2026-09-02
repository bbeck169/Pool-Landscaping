"""Phase K31 · Feb-2026 — SMS affirmative-consent gate (A2P 10DLC).

Layered on top of the existing rc_adapter's suppression + demo-whitelist
gates.  Opt-IN, tenant-scoped, and grandfather-aware so tenants that
enable the compliance mode don't accidentally break their in-flight
customer conversations.

Policy (per user's dispatch):
  * ``tenants.sms_consent_gate_enabled = False`` (default) → this
    module is a no-op.  Legacy behaviour preserved for every tenant
    that hasn't opted into the compliance mode.
  * ``tenants.sms_consent_gate_enabled = True`` → ``has_sms_consent``
    returns True iff any of:
      1. ``customers.sms_consent_captured_at`` is a non-empty
         timestamp on the customer record (explicit opt-in captured
         through the app's own opt-in surface — landing page,
         portal onboarding, invoice-view checkbox, etc.).
      2. There is at least one prior successful outbound SMS to
         this customer on record — ``notification_dispatch_log``
         with ``channel="sms"`` and a terminal-success provider
         status.  **Grandfather-if-prior-send** — preserves
         in-flight conversations at the moment the tenant flips
         the toggle.
  * Otherwise the gate blocks.  The block is logged as
    ``[COMMS_CONSENT] blocked cid=<> tenant=<> category=<> reason=<>``
    and the caller sees ``provider_status="no_consent"`` from the
    RC adapter.

Not a general-purpose consent framework — this ships the minimum
surface needed to satisfy the RingCentral A2P 10DLC banner and give
plofv-tenant ops a documented path to flip the switch after
capturing consent for their customer book.
"""
from __future__ import annotations

import logging
from typing import Optional

from config import db


_LOG = logging.getLogger("comms.consent_gate")


# Provider statuses that count as a "successful prior outbound" for
# the grandfather rule.  Kept in one place so the compliance policy
# is inspectable.
_TERMINAL_SUCCESS = {
    "sent", "queued", "delivered", "accepted", "mocked", "dry_run",
}


async def _tenant_consent_gate_on(tenant_id: str) -> bool:
    """Return True iff the tenant has explicitly opted into the
    K31 SMS consent gate.  Default is False."""
    if not tenant_id:
        return False
    t = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "sms_consent_gate_enabled": 1},
    )
    return bool((t or {}).get("sms_consent_gate_enabled"))


async def _has_prior_successful_sms(tenant_id: str,
                                       customer_id: str) -> bool:
    """Grandfather check — did we successfully SMS this customer
    at least once before?  Reads ``notification_dispatch_log`` for
    a channel=sms row scoped to the customer with a terminal-
    success status.
    """
    if not (tenant_id and customer_id):
        return False
    hit = await db.notification_dispatch_log.find_one(
        {"tenant_id": tenant_id, "recipient_id": customer_id,
         "channel": "sms",
         "provider_status": {"$in": list(_TERMINAL_SUCCESS)}},
        {"_id": 0, "id": 1},
    )
    return hit is not None


async def has_sms_consent(tenant_id: Optional[str],
                            customer_id: Optional[str],
                            category: Optional[str] = None) -> bool:
    """Public entry point wired into ``services.sms.rc_adapter.send``.

    Returns True when the outbound SMS is compliant to send.  Fails
    OPEN when the tenant hasn't opted in, or when required inputs
    are missing — the goal is to be a zero-risk overlay for tenants
    that haven't flipped the switch, and a rock-solid gate for the
    ones that have.
    """
    # No tenant → we can't scope the toggle. Return True (unchanged
    # legacy behaviour) so unrelated code paths that call send()
    # without a tenant_id aren't broken by K31.
    if not tenant_id:
        return True
    enabled = await _tenant_consent_gate_on(tenant_id)
    if not enabled:
        return True
    # Beyond this line the tenant explicitly opted in.
    if not customer_id:
        # Outbound SMS with no linked customer_id under consent-gate
        # mode is blocked — every real customer SMS must resolve to
        # a customer record.  Ad-hoc admin sends should route through
        # the K9 admin-notify surface, not the customer pipeline.
        _LOG.info(
            "[COMMS_CONSENT] blocked tenant=%s category=%s "
            "reason=no_customer_id",
            tenant_id, category,
        )
        return False

    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "sms_consent_captured_at": 1},
    ) or {}
    if cust.get("sms_consent_captured_at"):
        return True
    # Grandfather — at least one prior successful outbound.
    if await _has_prior_successful_sms(tenant_id, customer_id):
        return True
    _LOG.info(
        "[COMMS_CONSENT] blocked cid=%s tenant=%s category=%s "
        "reason=no_consent_record",
        customer_id, tenant_id, category,
    )
    return False
