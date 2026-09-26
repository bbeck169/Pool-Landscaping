"""QV-service · Feb-2026 — Quote view tracker.

Records every customer-facing view of a quote — public tokenized
magic link OR authenticated portal — into the ``quote_views``
collection and denormalises three aggregate fields onto the quote
doc for cheap list rendering: ``first_viewed_at``, ``last_viewed_at``
and ``view_count``.

Byte-parity with :mod:`services.invoice_view_tracker` except for two
QV-service-specific additions:

* ``ua_class`` — coarse User-Agent classification stamped on every
  event doc via :func:`services.ua_class.classify_ua`. Not
  denormalised on the quote doc; the event log carries it for the
  admin history endpoint + future analytics rollups.

* **Auto-transition** ``sent`` → ``viewed``. After the denorm
  update, we atomically CAS the quote's status when its pre-view
  value is EXACTLY ``"sent"``. Never touches ``draft`` /
  ``viewed`` / ``accepted`` / ``declined``. On successful flip
  we insert a fire-and-forget ``db.audit_logs`` row so ops has
  an off-doc paper trail (mirrors ``quote.mark_sent`` audit).

Design constants mirror the invoice sibling verbatim:

* 30-second dedupe per (``quote_id``, ``source``) — swallows the
  classic double-open (email preview + real click).
* Sources normalised to ``("email", "sms", "portal", "link")``.
  Anything else → ``"link"``.
* Never raises — the tracker is a pure side-effect of the read
  path.
* ``config.db`` is read at CALL time (not import time) so the
  module is inherently loop-safe under the F7 pytest loop-rebind
  fixture. Avoids adding another entry to
  ``tests/_f7_loop_fixture.py``'s ``_REBOUND_MODULES`` list.

The public API is a single coroutine plus the boot bootstrap +
history-summary read helper::

    from services.quote_view_tracker import record_quote_view
    await record_quote_view(
        quote_id=qid, tenant_id=tenant_id,
        source="portal",  # "email" | "sms" | "portal" | "link"
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import config
from services.ua_class import classify_ua


_LOG = logging.getLogger("quote.view_tracker")


# Sources normalised to a small closed set — anything else is
# stamped as ``"link"`` (the neutral fallback used by mint helpers
# that don't know the send channel). Aligned with
# ``invoice_view_tracker._VALID_SOURCES`` byte-for-byte.
_VALID_SOURCES = ("email", "sms", "portal", "link")

# Dedupe window — same value as invoice tracker. Refresh in <30s
# collapses to one view; distinct sessions across the window each
# register as a new view.
_DEDUPE_SECONDS = 30

# Cap free-form fields so a malicious UA / X-Forwarded-For chain
# can't blow up a document size.
_MAX_UA_LEN = 512
_MAX_IP_LEN = 64


def _norm_source(raw: Optional[str]) -> str:
    """Coerce arbitrary input to one of the allowed source strings."""
    s = (raw or "").strip().lower()
    return s if s in _VALID_SOURCES else "link"


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return None
    v = str(value)
    return v[:limit] if len(v) > limit else v


def _now_iso() -> str:
    """Small local helper — avoids reaching into ``utils`` at import
    time so the module's dep graph stays flat."""
    return datetime.now(timezone.utc).isoformat()


async def ensure_quote_view_indexes() -> None:
    """Idempotent index creation. Called from application startup.

    * ``(quote_id, viewed_at desc)`` — primary query pattern
      driving both the admin history endpoint and any future
      aggregate-rebuild path.
    * ``(tenant_id, viewed_at desc)`` — per-tenant "recently
      viewed" reports without leaving Mongo.
    """
    try:
        await config.db.quote_views.create_index(
            [("quote_id", 1), ("viewed_at", -1)],
            name="idx_quote_views_qid_ts",
        )
        await config.db.quote_views.create_index(
            [("tenant_id", 1), ("viewed_at", -1)],
            name="idx_quote_views_tenant_ts",
        )
    except Exception as exc:  # pragma: no cover — index race on boot
        _LOG.warning("quote_view_tracker: index bootstrap failed: %s", exc)


async def _recent_duplicate_exists(
    quote_id: str, source: str, now: datetime,
) -> bool:
    """Return True if we recorded the same (quote_id, source) view
    within the dedupe window. Silent on Mongo errors — dedupe is
    an optimisation, not a correctness constraint.
    """
    try:
        cutoff = (now - timedelta(seconds=_DEDUPE_SECONDS)).isoformat()
        row = await config.db.quote_views.find_one(
            {"quote_id": quote_id, "source": source,
                "viewed_at": {"$gte": cutoff}},
            {"_id": 1},
        )
        return row is not None
    except Exception:
        return False


async def _maybe_auto_transition_to_viewed(
    *, quote_id: str, tenant_id: str, source: str, now_iso: str,
) -> None:
    """Fire the ``sent`` → ``viewed`` auto-transition atomically.

    Uses a status-guarded ``update_one`` — the filter includes
    ``status: "sent"`` so:

    * ``draft`` / ``viewed`` / ``accepted`` / ``declined`` quotes
      never flip (``modified_count == 0`` → no-op, no audit row).
    * Two concurrent views on the same ``sent`` quote race safely:
      one wins the CAS (``modified_count == 1`` → audit row), the
      other loses (``modified_count == 0`` → skips audit). Exactly
      one audit row per real transition.

    Audit row insert is fire-and-forget — any Mongo blip on
    ``audit_logs`` is logged and swallowed so a bad audit collection
    can never blank a valid customer view.
    """
    try:
        res = await config.db.quotes.update_one(
            {
                "id": quote_id,
                "tenant_id": tenant_id,
                "doc_type": "quote",
                "status": "sent",
            },
            {"$set": {
                "status": "viewed",
                "auto_viewed_at": now_iso,
                "updated_at": now_iso,
            }},
        )
    except Exception as exc:
        _LOG.warning(
            "quote_view_tracker: auto-transition update failed for "
            "quote=%s: %s", quote_id, exc,
        )
        return
    if getattr(res, "modified_count", 0) <= 0:
        # Either the quote isn't in ``sent`` state (draft / viewed /
        # accepted / declined) or another concurrent view already
        # flipped it — either way, no audit row is warranted.
        return
    try:
        await config.db.audit_logs.insert_one({
            "event": "quote.auto_transition_viewed",
            "quote_id": quote_id,
            "tenant_id": tenant_id,
            "status_before": "sent",
            "status_after": "viewed",
            "source": source,
            "at": now_iso,
        })
    except Exception as exc:
        _LOG.warning(
            "quote_view_tracker: audit insert failed for quote=%s: %s",
            quote_id, exc,
        )


async def record_quote_view(
    *, quote_id: str, tenant_id: str, source: Optional[str],
    user_agent: Optional[str] = None, ip: Optional[str] = None,
) -> None:
    """Log a single quote view. Never raises.

    ``quote_id`` and ``tenant_id`` MUST be non-empty — the caller
    is expected to have already validated the quote + tenant
    (magic-link JWT verify, portal auth, etc.). Empty inputs
    silently no-op to protect the read path from mis-wired
    callers.
    """
    if not quote_id or not tenant_id:
        return
    src = _norm_source(source)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    if await _recent_duplicate_exists(quote_id, src, now):
        return

    ua = _truncate(user_agent, _MAX_UA_LEN)
    ip_addr = _truncate(ip, _MAX_IP_LEN)
    ua_cls = classify_ua(ua)

    event_doc = {
        "quote_id": quote_id,
        "tenant_id": tenant_id,
        "source": src,
        "viewed_at": now_iso,
        "user_agent": ua,
        "ua_class": ua_cls,
        "ip": ip_addr,
    }

    try:
        await config.db.quote_views.insert_one(event_doc)
    except Exception as exc:
        _LOG.warning(
            "quote_view_tracker: insert failed for quote=%s src=%s: %s",
            quote_id, src, exc,
        )
        return

    # Denormalise aggregate fields on the quote document. Uses
    # ``$min`` for ``first_viewed_at`` (earliest wins), ``$max`` for
    # ``last_viewed_at`` (latest wins), ``$inc`` for the counter.
    # Filter restricts to ``doc_type == "quote"`` so a shared-code
    # helper can never accidentally stamp an invoice.
    try:
        await config.db.quotes.update_one(
            {"id": quote_id, "tenant_id": tenant_id,
                "doc_type": "quote"},
            {
                "$min": {"first_viewed_at": now_iso},
                "$max": {"last_viewed_at": now_iso},
                "$inc": {"view_count": 1},
            },
        )
    except Exception as exc:
        _LOG.warning(
            "quote_view_tracker: denorm update failed for quote=%s: %s",
            quote_id, exc,
        )
        # Continue to the auto-transition anyway — the customer's
        # view is real even if the denorm write hiccupped.

    # QV4=c narrow status guard — flip ``sent`` → ``viewed`` iff
    # the quote is currently in ``sent`` state. Atomic CAS.
    await _maybe_auto_transition_to_viewed(
        quote_id=quote_id, tenant_id=tenant_id,
        source=src, now_iso=now_iso,
    )


async def fetch_quote_views_summary(
    *, quote_id: str, tenant_id: str, limit: int = 100,
) -> dict:
    """Return the view summary for the admin history endpoint.

    Shape (mirrors :func:`services.invoice_view_tracker.fetch_invoice_views_summary`
    but with ``quote_id`` + ``ua_class`` in the event rows):

    .. code-block:: json

        {
            "quote_id": "...",
            "first_viewed_at": "2026-02-01T00:00:00+00:00" | null,
            "last_viewed_at":  "2026-02-04T18:12:00+00:00" | null,
            "view_count": 3,
            "events": [
                {"viewed_at": "...", "source": "portal",
                    "user_agent": "...", "ua_class": "iPhone Safari",
                    "ip": "..."},
                ...
            ]
        }
    """
    quote = await config.db.quotes.find_one(
        {"id": quote_id, "tenant_id": tenant_id, "doc_type": "quote"},
        {"_id": 0, "first_viewed_at": 1, "last_viewed_at": 1,
            "view_count": 1},
    ) or {}

    cursor = config.db.quote_views.find(
        {"quote_id": quote_id, "tenant_id": tenant_id},
        {"_id": 0},
    ).sort("viewed_at", -1).limit(max(1, min(int(limit or 100), 500)))
    events = await cursor.to_list(length=None)

    return {
        "quote_id": quote_id,
        "first_viewed_at": quote.get("first_viewed_at"),
        "last_viewed_at": quote.get("last_viewed_at"),
        "view_count": int(quote.get("view_count") or 0),
        "events": events,
    }
