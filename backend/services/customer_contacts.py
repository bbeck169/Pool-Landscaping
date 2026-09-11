"""Feb-2026 · Multi-contact Phase-1 · fan-out recipient helpers.

Wraps the existing multi-contact array shape (see
``services.customer_multi_contact``) with two thin helpers that
every comms send site should route through:

    active_email_recipients(customer) -> List[str]
    active_phone_recipients(customer)  -> List[str]

Contract:

* Return normalized addresses (lowercased emails, E.164 phones)
  where **notifications are enabled** (matches either the
  ``notifications_enabled`` alias or the legacy
  ``marketing_ok`` / ``sms_ok`` flag).
* Preserve entry order — primary first (the multi-contact
  normalizer guarantees this).
* Deduplicate defensively even though the write-path normalizer
  already dedupes; belt-and-braces for legacy docs that might
  bypass ``apply_multi_contact``.
* Fallback to the scalar ``customer.email`` / ``customer.phone``
  when the array is absent OR empty — so pre-migration customer
  docs continue to receive comms exactly as before.

This module intentionally does NOT wire itself into any send
site — the Phase-2 sweep will do that per-cluster (see
``/app/memory/FEATURE_CUSTOMER_MULTI_CONTACTS_PHASE1.md``).
Phase 1 ships the helper + tests only, so the fan-out is
reviewable before any live comms surface changes behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _is_notify_enabled(entry: Dict[str, Any], legacy_flag: str) -> bool:
    """A recipient is opted-in if the new ``notifications_enabled``
    alias is truthy OR the legacy per-channel flag
    (``marketing_ok`` for emails / ``sms_ok`` for phones) is
    truthy. Missing → default to opted-in (matches the write-path
    default so migration-only rows still receive comms)."""
    if "notifications_enabled" in entry:
        return bool(entry.get("notifications_enabled"))
    if legacy_flag in entry:
        return bool(entry.get(legacy_flag))
    return True


def _dedup_preserving_order(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for x in items:
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def active_email_recipients(customer: Optional[Dict[str, Any]]) -> List[str]:
    """Return the ordered list of email addresses that should
    receive notifications for this customer.

    * Reads ``customer.emails[]`` first — every entry with
      ``notifications_enabled`` (or legacy ``marketing_ok``)
      truthy is included.
    * Falls back to the scalar ``customer.email`` when the array
      is missing/empty.
    * Never raises; empty input → empty list.
    """
    if not isinstance(customer, dict):
        return []
    entries = customer.get("emails") or []
    out: List[str] = []
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            addr = (e.get("address") or "").strip().lower()
            if not addr:
                continue
            if _is_notify_enabled(e, "marketing_ok"):
                out.append(addr)
    if not out:
        scalar = (customer.get("email") or "").strip().lower()
        if scalar:
            out.append(scalar)
    return _dedup_preserving_order(out)


def active_phone_recipients(customer: Optional[Dict[str, Any]]) -> List[str]:
    """Same contract as :func:`active_email_recipients` for
    phones. Reads ``customer.mobiles[]`` (canonical schema —
    see ``services.customer_multi_contact``) and falls back to
    the scalar ``customer.phone``.
    """
    if not isinstance(customer, dict):
        return []
    entries = customer.get("mobiles") or []
    out: List[str] = []
    if isinstance(entries, list):
        for e in entries:
            if not isinstance(e, dict):
                continue
            number = (e.get("number_e164") or e.get("number") or "").strip()
            if not number:
                continue
            if _is_notify_enabled(e, "sms_ok"):
                out.append(number)
    if not out:
        scalar = (customer.get("phone") or "").strip()
        if scalar:
            out.append(scalar)
    return _dedup_preserving_order(out)


def recipient_count_summary(customer: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Convenience for toast-wording callers that want to display
    ``"Sent to N recipients"``. Independent count per channel."""
    return {
        "email": len(active_email_recipients(customer)),
        "phone": len(active_phone_recipients(customer)),
    }
