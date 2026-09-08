"""Feb-2026 · Mobile Phase 2 offline-sync helpers.

Centralised so every write endpoint that needs to differentiate a
mobile-offline replay from a normal web write reads the same
predicates. Deliberately small — no framework glue, no ORM
imports. Consumers pass the FastAPI :class:`Request` in.

Client contract (locked with the mobile agent):

  * ``X-Client-Source: mobile-offline-sync`` — set by the flush
    worker when replaying queued writes. Presence is the only
    signal we treat as "this is a mobile-offline dispatch". Any
    other value (or missing header) is treated as a normal write.

  * ``X-Client-Updated-At: <iso8601>`` — the client's local last-
    modified timestamp for the entity BEFORE the tech's edit.
    Optional. When present + older than the server's
    ``updated_at``, the endpoint logs a row to
    ``mobile_write_conflicts`` but still accepts the write
    (tech-wins policy, per user directive Feb-2026).

Video caps (strict mobile-only overrides — do NOT touch the
generous defaults in :mod:`routers.media_uploads`):

  * ``MOBILE_MAX_VIDEO_BYTES = 25 MB`` — mobile clips are captured
    at up to 30s @ 1080p ~ 8-15 MB; 25 MB with 2× headroom keeps
    the tail well below the flush worker's 5-min network budget.
  * ``MOBILE_MAX_VIDEO_DURATION_S = 32.0`` — 30s hard cap + 2s
    slack for encoder rounding (per user brief).
  * ``MOBILE_STRICT_MIMES`` — mp4 + quicktime only; iOS records
    quicktime, Android records mp4. Anything else is unexpected
    input and gets 400'd loudly rather than silently stored.

Delayed on-my-way transparency (per user directive Feb-2026):

  * ``DELAYED_ON_MY_WAY_THRESHOLD_S = 600`` — if the mobile client
    tags the request with a ``queued_at`` older than 10 minutes,
    the SMS body picks up
    :data:`DELAYED_ON_MY_WAY_SUFFIX` so the customer knows the
    ping is real but late.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Request

from config import db
from utils import new_id, now_iso

_LOG = logging.getLogger("mobile.offline_sync")


# ─────────────────────────────────────────────────────────────────
# Client-source detection
# ─────────────────────────────────────────────────────────────────
MOBILE_OFFLINE_SYNC_SOURCE = "mobile-offline-sync"


def is_mobile_offline_sync(request: Request) -> bool:
    """True iff the caller declared itself the mobile flush worker.

    Deliberately case-insensitive on the value — clients across
    versions may lower/title-case the string.
    """
    src = (request.headers.get("X-Client-Source") or "").strip().lower()
    return src == MOBILE_OFFLINE_SYNC_SOURCE


def client_updated_at(request: Request) -> Optional[str]:
    """Return the ``X-Client-Updated-At`` header verbatim (ISO8601)
    or None. String comparison against the server ``updated_at`` is
    valid because both are UTC ISO8601 with the same precision.
    """
    val = (request.headers.get("X-Client-Updated-At") or "").strip()
    return val or None


# ─────────────────────────────────────────────────────────────────
# Video caps (strict, mobile-only overrides)
# ─────────────────────────────────────────────────────────────────
MOBILE_MAX_VIDEO_BYTES = 25 * 1024 * 1024
MOBILE_MAX_VIDEO_DURATION_S = 32.0
MOBILE_STRICT_MIMES = {"video/mp4", "video/quicktime"}


# ─────────────────────────────────────────────────────────────────
# On-my-way delayed-send transparency
# ─────────────────────────────────────────────────────────────────
DELAYED_ON_MY_WAY_THRESHOLD_S = 600
DELAYED_ON_MY_WAY_SUFFIX = " (sent when tech reconnected)"


def is_delayed_queued_at(queued_at: Optional[str]) -> bool:
    """Return True iff ``queued_at`` (ISO8601 UTC) is older than
    :data:`DELAYED_ON_MY_WAY_THRESHOLD_S` seconds. Missing / malformed
    values return False — we never surface a stale suffix on a
    normally-timed request.
    """
    if not queued_at:
        return False
    try:
        # ``fromisoformat`` handles the ``+00:00`` / ``-07:00`` shapes
        # the mobile client emits. Strip ``Z`` suffix which
        # ``fromisoformat`` on Python 3.11 does not accept.
        raw = queued_at.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        ts = datetime.fromisoformat(raw)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age >= DELAYED_ON_MY_WAY_THRESHOLD_S


# Job statuses that are "past in-progress" — an on-my-way SMS for
# a job in one of these states is either useless (already onsite)
# or misleading (job completed by someone else). Return
# ``suppressed=true`` and let mobile mark the queued op discarded.
JOB_STATUSES_PAST_IN_PROGRESS = {
    "completed", "done", "closed", "canceled", "cancelled",
    "no_show", "no-show",
}


def job_is_past_in_progress(job: Dict[str, Any]) -> bool:
    """True iff the job's current status is one of the terminal /
    past-in-progress states. Case-insensitive."""
    status = str((job or {}).get("status") or "").strip().lower()
    return status in JOB_STATUSES_PAST_IN_PROGRESS


# ─────────────────────────────────────────────────────────────────
# Tech-wins conflict audit
# ─────────────────────────────────────────────────────────────────
_CONFLICTS_COLLECTION = "mobile_write_conflicts"


async def log_write_conflict(
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
    tech_user_id: Optional[str],
    fields_overwritten: list,
    client_updated_at_iso: str,
    server_updated_at_iso: Optional[str],
) -> None:
    """Persist a tech-wins overwrite for audit. Best-effort — never
    raises up to the caller (the tech's write must succeed
    regardless of audit-log health, per policy).

    The row is deliberately narrow — no full-doc snapshots, no
    diffs. Ops can grep by ``entity_id`` + ``tech_user_id`` when
    reviewing a disputed edit; the point-in-time entity state is
    already recoverable from Mongo's oplog if needed.
    """
    try:
        await db[_CONFLICTS_COLLECTION].insert_one({
            "id": new_id(),
            "tenant_id": tenant_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tech_user_id": tech_user_id,
            "fields_overwritten": list(fields_overwritten or []),
            "client_updated_at": client_updated_at_iso,
            "server_updated_at": server_updated_at_iso,
            "created_at": now_iso(),
            # Real datetime for any future TTL / range queries.
            "created_at_dt": datetime.now(timezone.utc),
        })
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "[mobile.offline_sync] conflict audit insert failed: %s: %s",
            type(exc).__name__, exc,
        )


def should_log_conflict(
    server_updated_at_iso: Optional[str],
    client_updated_at_iso: Optional[str],
) -> bool:
    """Return True iff the server was modified AFTER the client's
    snapshot — the exact condition that qualifies the write as a
    tech-wins overwrite. Missing values (either side) → False
    (nothing to audit).

    Both timestamps are ISO8601 UTC; plain string comparison is
    safe because ISO8601 lexicographic order matches chronological
    order at the same precision level.
    """
    if not (server_updated_at_iso and client_updated_at_iso):
        return False
    try:
        return str(server_updated_at_iso) > str(client_updated_at_iso)
    except Exception:  # noqa: BLE001
        return False
