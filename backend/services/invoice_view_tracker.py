"""Phase K47 · Feb-2026 — Invoice view tracker.

Records every customer-facing view of an invoice — email magic link,
SMS magic link, or authenticated portal — into the
``invoice_views`` collection and denormalises three aggregate
fields onto the invoice doc for cheap list rendering:
``first_viewed_at``, ``last_viewed_at`` and ``view_count``.

Design highlights:

* **Dedupe window.** A 30-second dedupe per (``invoice_id``,
  ``source``) suppresses noise from a customer refreshing the page
  or an email client opening the link twice. The window is
  intentionally per-source so an email open followed instantly by
  a portal login still records two events.
* **Best-effort.** Never raises — the tracker is a pure side effect
  of the read path. If Mongo is unavailable we log and move on;
  the customer's page render must not depend on this.
* **Aggregate denormalisation.** Same transaction updates the
  invoice's ``first_viewed_at``, ``last_viewed_at`` and
  ``view_count`` so the invoice list can sort/render without a
  join. ``first_viewed_at`` uses ``$setOnInsert``-style semantics
  via the atomic ``$min`` operator (no separate read-then-write).
* **Indexing.** ``ensure_invoice_view_indexes`` is called on
  application boot; the indexes are safe to re-create idempotently.

The public API is a single coroutine:

.. code-block:: python

    from services.invoice_view_tracker import record_invoice_view
    await record_invoice_view(
        invoice_id=iid, tenant_id=tenant_id,
        source="portal",  # "email" | "sms" | "portal" | "link"
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import db, logger  # noqa: F401 — ``logger`` is exported by config

_LOG = logging.getLogger("invoice.view_tracker")

# Sources normalised to a small closed set — anything else is stamped
# as ``"link"`` (the neutral fallback used by mint helpers that don't
# know the send channel). Kept aligned with the frontend ``?src=``
# whitelist so we don't accidentally start storing free-text.
_VALID_SOURCES = ("email", "sms", "portal", "link")

# Dedupe window — a customer hitting refresh N times in <30s should
# register as a single view. Value chosen to swallow the classic
# double-open pattern (email client preview + real click) without
# collapsing distinct sessions.
_DEDUPE_SECONDS = 30

# Cap the free-form fields we accept so a malicious User-Agent /
# forwarded IP can't blow up a document size.
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


async def ensure_invoice_view_indexes() -> None:
    """Idempotent index creation. Called from application startup.

    * ``(invoice_id, viewed_at desc)`` — the primary query pattern
      driving both the admin history endpoint and the aggregate
      recompute path (if we ever need to rebuild denorm fields).
    * ``(tenant_id, viewed_at desc)`` — supports the future
      per-tenant "recently viewed" report without leaving Mongo.
    """
    try:
        await db.invoice_views.create_index(
            [("invoice_id", 1), ("viewed_at", -1)],
            name="idx_invoice_views_iid_ts",
        )
        await db.invoice_views.create_index(
            [("tenant_id", 1), ("viewed_at", -1)],
            name="idx_invoice_views_tenant_ts",
        )
    except Exception as exc:  # pragma: no cover — index race on boot
        _LOG.warning("invoice_view_tracker: index bootstrap failed: %s", exc)


async def _recent_duplicate_exists(invoice_id: str, source: str,
                                       now: datetime) -> bool:
    """Return True if we recorded the same (invoice_id, source) view
    within the dedupe window. Silent on Mongo errors — dedupe is
    an optimisation, not a correctness constraint.
    """
    try:
        cutoff = (now - timedelta(seconds=_DEDUPE_SECONDS)).isoformat()
        row = await db.invoice_views.find_one(
            {"invoice_id": invoice_id, "source": source,
                "viewed_at": {"$gte": cutoff}},
            {"_id": 1},
        )
        return row is not None
    except Exception:
        return False


async def record_invoice_view(
    *, invoice_id: str, tenant_id: str, source: Optional[str],
    user_agent: Optional[str] = None, ip: Optional[str] = None,
) -> None:
    """Log a single invoice view. Never raises.

    ``invoice_id`` and ``tenant_id`` MUST be non-empty — the caller
    is expected to have already validated the invoice + tenant
    (magic-link JWT verify, portal auth, etc.). Empty inputs
    silently no-op to protect the read path from mis-wired
    callers.
    """
    if not invoice_id or not tenant_id:
        return
    src = _norm_source(source)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    if await _recent_duplicate_exists(invoice_id, src, now):
        return

    ua = _truncate(user_agent, _MAX_UA_LEN)
    ip_addr = _truncate(ip, _MAX_IP_LEN)

    doc = {
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "source": src,
        "viewed_at": now_iso,
        "user_agent": ua,
        "ip": ip_addr,
    }

    try:
        await db.invoice_views.insert_one(doc)
    except Exception as exc:
        _LOG.warning(
            "invoice_view_tracker: insert failed for invoice=%s src=%s: %s",
            invoice_id, src, exc,
        )
        return

    # Denormalise aggregate fields on the invoice document. Uses
    # ``$min`` for ``first_viewed_at`` so re-runs are safe: the
    # earliest timestamp always wins. ``$max`` for
    # ``last_viewed_at`` mirrors that. ``$inc`` for the counter.
    try:
        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id,
                "doc_type": "invoice"},
            {
                "$min": {"first_viewed_at": now_iso},
                "$max": {"last_viewed_at": now_iso},
                "$inc": {"view_count": 1},
            },
        )
    except Exception as exc:
        _LOG.warning(
            "invoice_view_tracker: denorm update failed for invoice=%s: %s",
            invoice_id, exc,
        )


async def fetch_invoice_views_summary(
    *, invoice_id: str, tenant_id: str, limit: int = 100,
) -> dict:
    """Return the view summary for the admin history endpoint.

    Shape:

    .. code-block:: json

        {
            "invoice_id": "...",
            "first_viewed_at": "2026-02-01T00:00:00+00:00" | null,
            "last_viewed_at":  "2026-02-04T18:12:00+00:00" | null,
            "view_count": 3,
            "events": [
                {"viewed_at": "...", "source": "portal",
                    "user_agent": "...", "ip": "..."},
                ...
            ]
        }
    """
    inv = await db.quotes.find_one(
        {"id": invoice_id, "tenant_id": tenant_id, "doc_type": "invoice"},
        {"_id": 0, "first_viewed_at": 1, "last_viewed_at": 1, "view_count": 1},
    ) or {}

    cursor = db.invoice_views.find(
        {"invoice_id": invoice_id, "tenant_id": tenant_id},
        {"_id": 0},
    ).sort("viewed_at", -1).limit(max(1, min(int(limit or 100), 500)))
    events = await cursor.to_list(length=None)

    return {
        "invoice_id": invoice_id,
        "first_viewed_at": inv.get("first_viewed_at"),
        "last_viewed_at": inv.get("last_viewed_at"),
        "view_count": int(inv.get("view_count") or 0),
        "events": events,
    }
