"""Task N Round 2 · Phase N.6 · Feb-2026 — Notification recipient resolver.

Pure function.  Given a ``tenant`` document, returns a de-duplicated
list of ``{"channel", "address", "recipient_id"}`` triples ready
for fanout by any notifier.  No side effects, no I/O.

Naming rationale (Phase N.5 §A): the field it reads —
``lead_notification_recipients`` — is a legacy name kept for
backward compatibility.  In the tenant Settings UI this field is
labeled "Notification Recipients" (no "Lead" prefix), so the
naming awkwardness lives only in Python.  A rename to
``notification_recipients`` was considered under R.2 but deferred
because it would touch model + migration + Settings UI + every
existing consumer, whereas the ops surface it powers ("notify me
here on ops events") is EXACTLY what Task N Round 2 needs.
Round 3 can rename if the ambiguity ages poorly.

Resolution chain (locked, per Phase N.5 §A):

  1. Iterate ``tenant.lead_notification_recipients`` (per-recipient
     opt-in flags respected — one entry can be email-only, another
     sms-only, another both).
  2. Fold in ``tenant.lead_alert_email_recipients`` (flat CSV list;
     every entry treated as email-opted-in).
  3. Fold in ``tenant.lead_alert_sms_recipients`` (flat CSV list;
     every entry treated as sms-opted-in).
  4. Dedupe by ``(channel, address)`` — the earliest hit wins so
     structured entries in ``lead_notification_recipients`` keep
     their ``recipient_id`` when the same address is also present
     in a legacy flat list.

The output preserves order (structured entries first, then the
flat lists) so downstream logging surfaces the canonical
identifier when both are present.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def resolve_note_notification_recipients(
    tenant: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Return the fanout list for note-change notifications.

    Empty list when ``tenant`` is ``None`` / has no recipient fields —
    the caller logs a WARN and skips the send (never raises).
    """
    if not tenant:
        return []

    out: List[Dict[str, str]] = []
    seen: set = set()  # ``(channel, address_lower)`` dedupe keys.

    # ── Structured recipients (per-channel opt-in flags) ────────
    for r in (tenant.get("lead_notification_recipients") or []):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        email = (r.get("email") or "").strip()
        phone = (r.get("phone") or "").strip()
        email_opt = bool(r.get("email_opt_in"))
        sms_opt = bool(r.get("sms_opt_in"))
        if email and email_opt:
            key = ("email", email.lower())
            if key not in seen:
                seen.add(key)
                out.append({"channel": "email",
                            "address": email,
                            "recipient_id": rid})
        if phone and sms_opt:
            key = ("sms", phone)
            if key not in seen:
                seen.add(key)
                out.append({"channel": "sms",
                            "address": phone,
                            "recipient_id": rid})

    # ── Legacy flat lists (all opted-in by presence) ────────────
    for email in (tenant.get("lead_alert_email_recipients") or []):
        email = (email or "").strip()
        if not email:
            continue
        key = ("email", email.lower())
        if key not in seen:
            seen.add(key)
            out.append({"channel": "email",
                        "address": email,
                        "recipient_id": ""})
    for phone in (tenant.get("lead_alert_sms_recipients") or []):
        phone = (phone or "").strip()
        if not phone:
            continue
        key = ("sms", phone)
        if key not in seen:
            seen.add(key)
            out.append({"channel": "sms",
                        "address": phone,
                        "recipient_id": ""})

    return out
