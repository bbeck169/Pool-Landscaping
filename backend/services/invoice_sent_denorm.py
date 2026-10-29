"""Invoice "Sent" denorm · Feb-2026 · Backlog Item #6

Stamps per-channel + aggregate send-timestamps directly onto the
invoice document in ``db.quotes`` (``doc_type="invoice"``) so the
invoice list page can render a "Sent" column (``email`` / ``sms``
/ ``both`` / ``—``) without an N+1 lookup into
``email_outbox`` / ``invoice_send_attempts`` / ``dunning_reminders``.

Operator spec (Backlog Item #6 — Option X, no backfill):

    * ``last_sent_at``          — latest ISO timestamp across any
                                    channel. ``$max`` write so re-runs
                                    can't go backwards in time.
    * ``last_sent_via``         — ``"email"`` | ``"sms"`` | ``"both"``.
                                    ``"both"`` is set as soon as BOTH
                                    channels have at least one
                                    successful send on the doc; once
                                    there, it stays (no downgrade).
    * ``last_email_sent_at``    — latest ISO timestamp for email
                                    sends only. ``$max`` write.
    * ``last_sms_sent_at``      — latest ISO timestamp for SMS
                                    sends only. ``$max`` write.

Callers are responsible for only invoking the helper AFTER a
confirmed-successful send. Failures must NOT stamp — operator spec
is explicit that a failed send should NOT advance the Sent column.

The helper never raises — a Mongo failure is logged and swallowed
so the enclosing send flow stays non-fatal. Empty / missing
``invoice_id`` or ``tenant_id`` short-circuits silently to protect
mis-wired callers.

Historical invoices without the four fields render as "—" on the
FE (``last_sent_at === undefined``) — intentional per operator
("no backfill").
"""
from __future__ import annotations

import logging
from typing import Optional

from config import db
from utils import now_iso


_LOG = logging.getLogger(__name__)


_CHANNEL_EMAIL = "email"
_CHANNEL_SMS = "sms"
_VALID_CHANNELS = {_CHANNEL_EMAIL, _CHANNEL_SMS}


async def stamp_invoice_sent(
    *, invoice_id: Optional[str], tenant_id: Optional[str],
    channel: str,
) -> None:
    """Stamp a per-channel + aggregate successful send on an invoice.

    Parameters
    ----------
    invoice_id : str | None
        The invoice id (``db.quotes.id`` with ``doc_type="invoice"``).
        Empty / None → silent no-op (protects mis-wired callers).
    tenant_id : str | None
        Tenant scope for the invoice. Empty / None → silent no-op.
    channel : str
        Either ``"email"`` or ``"sms"``. Any other value → silent
        no-op (defensive against future transport additions).

    Idempotency
    -----------
    All timestamp fields are written with ``$max``, so a stale /
    out-of-order replay of the same send event is a no-op (the
    existing-higher timestamp wins). ``last_sent_via`` is computed
    from the post-``$max`` document state and transitions
    one-way: ``email``/``sms`` → ``both`` once BOTH channels have
    a stamp. Never downgrades.
    """
    if not invoice_id or not tenant_id:
        return
    if channel not in _VALID_CHANNELS:
        return

    now = now_iso()
    channel_field = (
        "last_email_sent_at" if channel == _CHANNEL_EMAIL
        else "last_sms_sent_at"
    )
    other_field = (
        "last_sms_sent_at" if channel == _CHANNEL_EMAIL
        else "last_email_sent_at"
    )

    try:
        # Step 1 — $max the per-channel and aggregate timestamps.
        # ``$max`` on an absent field writes the new value; on a
        # present-and-higher value, writes nothing (idempotent).
        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id,
             "doc_type": "invoice"},
            {"$max": {channel_field: now, "last_sent_at": now}},
        )

        # Step 2 — compute ``last_sent_via`` from both-channel
        # presence AFTER the $max above has landed. We read the
        # other-channel field only; the current channel field is
        # guaranteed populated by this call.
        row = await db.quotes.find_one(
            {"id": invoice_id, "tenant_id": tenant_id,
             "doc_type": "invoice"},
            {"_id": 0, other_field: 1},
        ) or {}
        via = "both" if row.get(other_field) else channel

        await db.quotes.update_one(
            {"id": invoice_id, "tenant_id": tenant_id,
             "doc_type": "invoice"},
            {"$set": {"last_sent_via": via}},
        )
    except Exception as exc:  # noqa: BLE001 — never fail the send
        _LOG.warning(
            "invoice_sent_denorm: stamp failed invoice=%s channel=%s "
            "err=%s", invoice_id, channel, type(exc).__name__,
        )
