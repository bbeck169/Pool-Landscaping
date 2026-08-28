"""Backlog #iv · Feb-2026 — Unified dispatch idempotency guard.

The audit for Backlog #iv surfaced two orthogonal duplicate-send
patterns:

1. **Scheduler multi-fire** — the pool-service weekly email cron
   (``services/pool_service_email.py``) has no dedup ledger and is
   registered on every process that boots with
   ``ENABLE_SCHEDULER=true``.  With N such processes, every Friday
   17:00 UTC tick fires N sends per tenant.
2. **Adapter caller-supplied idempotency is optional** — the
   ``sms_send_ledger`` guard in ``services/sms/rc_adapter.py`` only
   activates when the caller passes ``idempotency_key=``.  Many
   customer-facing dispatchers (``on_my_way``, service-report
   completion SMS) skip that argument, so a repeat trigger sends
   twice.

This module unifies both concerns behind a single collection —
``db.notification_dispatch_log`` — enforced by a compound unique
index on ``(tenant_id, notification_type, recipient_id, dedupe_key)``
so the DB catches races between concurrent processes.

Usage
-----
::

    from services.comms_hardening.dispatch_guard import guard_and_log
    from services.comms_hardening.dispatch_guard import mark_dispatch_result

    verdict = await guard_and_log(
        tenant_id=tid,
        notification_type="pool_service_report",
        recipient_id=user_id_or_hashed_email,
        dedupe_key=f"pool_service_report:{tid}:{iso_week}",
        channel="email",
        resolved_address="admin@example.com",
    )
    if not verdict["allowed"]:
        # ``verdict["reason"]`` will be ``"already_dispatched"`` or
        # ``"log_write_failed"``.  Second call with the same
        # ``dedupe_key`` short-circuits.
        return {"skipped": True, "reason": verdict["reason"]}

    result = await real_send_via_provider(...)
    await mark_dispatch_result(
        verdict["dispatch_id"], status=result["status"],
        provider_id=result.get("provider_id"),
        error=result.get("error"),
    )

Recipient-id conventions
------------------------
``recipient_id`` MUST be a stable identifier — never a raw phone or
email string, because those change (customer edits, provider re-
formatting).  Prefer:

    * ``customer_id`` (customer-facing sends)
    * ``user_id`` (admin/tech-facing sends)
    * ``hash_email(email)`` (pure-email destinations without a stable id)
    * ``hash_phone(phone)`` (pure-phone destinations without a stable id)

The two helpers below produce the hash form:  the first-16 chars of
the lower-cased ``sha256`` hex digest.  Callers must not hand-roll
this — future callers should always reach for these helpers so the
convention stays consistent.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Optional

from config import db
from utils import new_id, now_iso


logger = logging.getLogger("notifications.dispatch_guard")


# ═════════════════════════════════════════════════════════════════════
# Stable recipient-id helpers (documented + reused by callers)
# ═════════════════════════════════════════════════════════════════════
def hash_email(email: str) -> str:
    """``sha256(email.strip().lower()).hexdigest()[:16]`` — stable, 16-
    char lowercase hex fingerprint of an email.  Never returns an
    empty string for a non-empty input."""
    s = (email or "").strip().lower()
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def hash_phone(phone: str) -> str:
    """Digits-only, last-10, then ``sha256`` → 16-char lowercase
    hex.  Absorbs formatting differences between ``+16028874400`` /
    ``602-887-4400`` / ``(602) 887-4400``."""
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        return ""
    last10 = digits[-10:]
    return hashlib.sha256(last10.encode("utf-8")).hexdigest()[:16]


# ═════════════════════════════════════════════════════════════════════
# Insert-then-send guard
# ═════════════════════════════════════════════════════════════════════
async def guard_and_log(
    *,
    tenant_id: str,
    notification_type: str,
    recipient_id: str,
    dedupe_key: str,
    channel: str,
    resolved_address: str,
    subject: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attempt to reserve a dispatch slot in ``notification_dispatch_log``.

    Returns a dict:

    * ``allowed: bool`` — ``True`` when the caller may proceed to
      the live provider; ``False`` when a duplicate already exists.
    * ``dispatch_id: Optional[str]`` — the id of the reserved log
      row (present when ``allowed=True``); ``None`` on dedupe.
    * ``reason: str`` —
        * ``"reserved"`` on success.
        * ``"already_dispatched"`` when the compound unique index
          rejected the insert (a prior dispatch for the same key
          exists).
        * ``"log_write_failed"`` on any other Mongo error (guard
          fails-open — caller decides whether to proceed; the
          typical decision is "proceed and log at the adapter
          layer" so a transient Mongo blip doesn't drop the notice).

    The insert-then-send pattern relies on a **compound unique
    index** ``(tenant_id, notification_type, recipient_id,
    dedupe_key)`` — that's what makes the guard race-safe across N
    concurrent processes.  See ``services/migrations/
    notification_dispatch_log.py``.
    """
    if not all([tenant_id, notification_type, dedupe_key, channel]):
        # Fail-open — never break the caller on a bad input.
        logger.warning(
            "guard_and_log missing inputs · tenant_id=%s notification_type=%s "
            "dedupe_key=%s channel=%s — falling open (allowed=True)",
            tenant_id, notification_type, dedupe_key, channel,
        )
        return {"allowed": True, "dispatch_id": None,
                "reason": "invalid_inputs_fail_open"}

    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "notification_type": notification_type,
        "recipient_id": recipient_id or "",
        "dedupe_key": dedupe_key,
        "channel": channel,
        "resolved_address": resolved_address or "",
        "subject": subject or "",
        "status": "reserved",
        "provider_id": None,
        "error": None,
        "attempt_count": 0,
        "reserved_at": now_iso(),
        "sent_at": None,
        "metadata": metadata or {},
    }
    try:
        await db.notification_dispatch_log.insert_one(doc)
        return {"allowed": True, "dispatch_id": doc["id"], "reason": "reserved"}
    except Exception as exc:                                    # noqa: BLE001
        # Distinguish DuplicateKeyError (idempotent skip) from
        # anything else (fail-open).  The driver-agnostic name-check
        # keeps us portable across motor / pymongo versions.
        if type(exc).__name__ == "DuplicateKeyError":
            logger.info(
                "[dispatch_guard] dedupe hit · tenant=%s type=%s "
                "recipient=%s key=%s",
                tenant_id, notification_type, recipient_id, dedupe_key,
            )
            return {"allowed": False, "dispatch_id": None,
                    "reason": "already_dispatched"}
        logger.warning(
            "[dispatch_guard] log write failed · tenant=%s type=%s key=%s: %s",
            tenant_id, notification_type, dedupe_key, exc,
        )
        return {"allowed": True, "dispatch_id": None,
                "reason": "log_write_failed"}


async def mark_dispatch_result(
    dispatch_id: Optional[str],
    *,
    status: str,
    provider_id: Optional[str] = None,
    error: Optional[str] = None,
    attempt_count: Optional[int] = None,
) -> None:
    """Update a previously-reserved dispatch row with the final
    provider result.  Safe no-op when ``dispatch_id`` is ``None`` —
    caller doesn't have to guard.  ``status`` should be one of
    ``sent`` / ``failed`` / ``mocked`` / ``dry_run`` / ``deferred``.
    """
    if not dispatch_id:
        return
    upd: Dict[str, Any] = {
        "status": status,
        "sent_at": now_iso(),
    }
    if provider_id is not None:
        upd["provider_id"] = provider_id
    if error is not None:
        upd["error"] = error
    if attempt_count is not None:
        upd["attempt_count"] = attempt_count
    try:
        await db.notification_dispatch_log.update_one(
            {"id": dispatch_id}, {"$set": upd},
        )
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(
            "[dispatch_guard] result mark failed · id=%s status=%s: %s",
            dispatch_id, status, exc,
        )
