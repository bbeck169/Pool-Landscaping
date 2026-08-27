"""Feb 2026 · Marketing · Phase 1 — Central event registry.

The Custom Trigger Builder (Phase 2 UI) needs a single catalog it can
render as the "which event fires this?" dropdown, plus a machine-
readable spec for every event's constraints:

  * ``entity`` — what the event is about (lead, job, invoice, etc.).
    The evaluator uses this to know which document to hydrate when
    evaluating filters.
  * ``scheduled`` — whether the event has a native ``scheduled_at``
    time (used to decide whether a ``before`` delay makes sense).
  * ``allow_negative_offset`` — whether a ``{mode:"before", value:N}``
    delay is valid for this event. Guards against nonsense like
    "3 days BEFORE new_lead" (which has no future time to anchor
    to).

The keys here are the canonical wire-format event names used
throughout ``on_event(...)`` calls, ``marketing_sequences.trigger``
docs, and the ``marketing_event_ledger`` collection. Adding a new
event to this catalog is the only "canonical" place — every
consumer imports from here.
"""
from __future__ import annotations

from typing import Any, Dict, List


EVENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "new_lead": {
        "label": "New lead created",
        "entity": "lead",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "lead_status_changed": {
        "label": "Lead status changed",
        "entity": "lead",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "estimate_sent": {
        "label": "Estimate sent",
        "entity": "estimate",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "estimate_signed": {
        "label": "Estimate signed",
        "entity": "estimate",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "job_scheduled": {
        "label": "Job scheduled",
        "entity": "job",
        "scheduled": True,
        "allow_negative_offset": True,
    },
    "job_scheduled_reminder_1d": {
        "label": "1 day before scheduled job",
        "entity": "job",
        "scheduled": True,
        "allow_negative_offset": True,
    },
    "job_completed": {
        "label": "Job completed",
        "entity": "job",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "job_cancelled": {
        "label": "Job cancelled",
        "entity": "job",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "invoice_sent": {
        "label": "Invoice sent",
        "entity": "invoice",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "invoice_paid": {
        "label": "Invoice paid",
        "entity": "invoice",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "invoice_overdue": {
        "label": "Invoice overdue",
        "entity": "invoice",
        "scheduled": True,
        "allow_negative_offset": False,
    },
    "payment_failed": {
        "label": "Payment failed",
        "entity": "payment",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "customer_birthday": {
        "label": "Customer birthday",
        "entity": "customer",
        "scheduled": True,
        "allow_negative_offset": True,
    },
    "service_anniversary": {
        "label": "Service anniversary",
        "entity": "customer",
        "scheduled": True,
        "allow_negative_offset": True,
    },
    "chemistry_out_of_range": {
        "label": "Chemistry out of range",
        "entity": "job",
        "scheduled": False,
        "allow_negative_offset": False,
    },
    "repair_flagged": {
        "label": "Repair job flagged",
        "entity": "job",
        "scheduled": False,
        "allow_negative_offset": False,
    },
}


# Backwards-compat map — legacy sequence docs stored ``trigger_type``
# values that need to translate to the Phase-1 canonical keys. Add
# aliases here only; never rename an already-shipped canonical key.
LEGACY_TRIGGER_ALIASES: Dict[str, str] = {
    # legacy → canonical
    "service_completed":       "job_completed",
    "customer_created":        "new_lead",         # M5c called it customer_created
    "review_left":             "estimate_signed",  # closest match
    "estimate_accepted":       "estimate_signed",
    "invoice_past_due_3_days": "invoice_overdue",  # collapse specialised keys
    "invoice_past_due_7_days": "invoice_overdue",
    "invoice_past_due_14_days":"invoice_overdue",
    "invoice_past_due_N_days": "invoice_overdue",  # canonical parameterised form
    "birthday":                "customer_birthday",
    "segment_join":            "new_lead",         # closest — segment_join → treat as lead
}


def canonicalize_event_key(key: str) -> str:
    """Return the canonical event name for either a canonical key
    or a known legacy alias. Unknown values are returned unchanged
    so the migration can log them for manual review."""
    if not key:
        return ""
    key = str(key).strip()
    if key in EVENT_CATALOG:
        return key
    return LEGACY_TRIGGER_ALIASES.get(key, key)


def list_events() -> List[Dict[str, Any]]:
    """Return the catalog as a stable-ordered list suitable for
    rendering as a dropdown in the Phase-2 builder UI.

    Each entry adds a ``key`` field alongside the metadata so the
    frontend can render ``{event.key: event.label}`` without extra
    normalisation.
    """
    return [
        {"key": k, **v} for k, v in EVENT_CATALOG.items()
    ]


def is_valid_event(key: str) -> bool:
    """Guard used by the trigger schema validator."""
    return canonicalize_event_key(key) in EVENT_CATALOG


def supports_negative_offset(key: str) -> bool:
    """``True`` iff the event has ``allow_negative_offset: True`` in
    the catalog — used to gate the ``{mode:"before"}`` delay
    validation."""
    entry = EVENT_CATALOG.get(canonicalize_event_key(key))
    return bool(entry and entry.get("allow_negative_offset"))


def is_scheduled_event(key: str) -> bool:
    entry = EVENT_CATALOG.get(canonicalize_event_key(key))
    return bool(entry and entry.get("scheduled"))
