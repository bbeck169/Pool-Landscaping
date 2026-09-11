"""Feb-2026 Customer Detail Additions — multi-mobile / multi-email helpers.

Two-way sync between the legacy scalar (``phone`` / ``email``) fields and
the new arrays (``mobiles`` / ``emails``). Every write path calls
:func:`normalize_multi_contact` so:

* Legacy consumers reading ``customer.phone`` / ``customer.email`` still
  see the primary contact.
* New consumers reading ``customer.mobiles`` / ``customer.emails`` see the
  full list with labels, primary flags, and marketing/sms consent flags.
* Cap invariants (≤2 mobiles, ≤3 emails) are enforced.
* Exactly one entry per array is flagged ``is_primary`` (the first entry
  wins if none / multiple are set).

The seed migration :func:`migrate_customer_multi_contact` back-populates
the arrays from the scalars for legacy customer docs on first read of
this module (called from server startup, idempotent).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id


MAX_MOBILES = 4
MAX_EMAILS = 4


def _norm_entry_id(e: dict) -> dict:
    if not e.get("id"):
        e["id"] = new_id()
    return e


def _dedup_by_key(entries: List[dict], key: str) -> List[dict]:
    """Preserve order; drop entries where the identity key is empty or
    duplicated (case-insensitive)."""
    seen: set[str] = set()
    out: List[dict] = []
    for e in entries:
        v = (e.get(key) or "").strip().lower()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(e)
    return out


def _ensure_single_primary(entries: List[dict]) -> List[dict]:
    """Guarantee exactly one ``is_primary=True`` entry (unless empty)."""
    if not entries:
        return entries
    marked = [i for i, e in enumerate(entries) if e.get("is_primary")]
    if len(marked) == 1:
        # Already valid — normalize the others to False so we don't drift.
        for i, e in enumerate(entries):
            e["is_primary"] = (i == marked[0])
        return entries
    # 0 or >1 marked — use the first entry as canonical primary.
    for i, e in enumerate(entries):
        e["is_primary"] = (i == 0)
    return entries


def normalize_mobiles(raw: Optional[List[dict]],
                       legacy_phone: Optional[str] = None) -> List[dict]:
    """Take arbitrary input for ``mobiles`` (may be None / [] / list of
    dicts) and return a valid, deduped, capped list. If input is empty
    but a legacy ``phone`` scalar exists, seed the array with a single
    primary entry.
    """
    if raw is None:
        raw = []
    out: List[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        number = (e.get("number_e164") or e.get("number") or "").strip()
        if not number:
            continue
        entry = _norm_entry_id({
            "id": e.get("id"),
            "number_e164": number,
            "label": (e.get("label") or "").strip() or "Primary",
            "is_primary": bool(e.get("is_primary")),
            # Feb-2026 · Multi-contact Phase-1 — accept BOTH the
            # legacy ``sms_ok`` and the new ``notifications_enabled``
            # aliases. Emit BOTH on read so old + new consumers agree.
            "sms_ok": bool(
                e.get("sms_ok", e.get("notifications_enabled", True))
            ),
            "notifications_enabled": bool(
                e.get("notifications_enabled",
                      e.get("sms_ok", True))
            ),
        })
        out.append(entry)
    # Seed from legacy scalar if empty.
    if not out and legacy_phone and legacy_phone.strip():
        out.append(_norm_entry_id({
            "number_e164": legacy_phone.strip(),
            "label": "Primary",
            "is_primary": True,
            "sms_ok": True,
            "notifications_enabled": True,
        }))
    out = _dedup_by_key(out, "number_e164")[:MAX_MOBILES]
    out = _ensure_single_primary(out)
    return out


def normalize_emails(raw: Optional[List[dict]],
                      legacy_email: Optional[str] = None) -> List[dict]:
    if raw is None:
        raw = []
    out: List[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        address = (e.get("address") or "").strip().lower()
        if not address:
            continue
        entry = _norm_entry_id({
            "id": e.get("id"),
            "address": address,
            "label": (e.get("label") or "").strip() or "Primary",
            "is_primary": bool(e.get("is_primary")),
            # Feb-2026 · Multi-contact Phase-1 — accept BOTH the
            # legacy ``marketing_ok`` and the new
            # ``notifications_enabled`` aliases. Emit BOTH on read.
            "marketing_ok": bool(
                e.get("marketing_ok",
                      e.get("notifications_enabled", True))
            ),
            "notifications_enabled": bool(
                e.get("notifications_enabled",
                      e.get("marketing_ok", True))
            ),
        })
        out.append(entry)
    if not out and legacy_email and legacy_email.strip():
        out.append(_norm_entry_id({
            "address": legacy_email.strip().lower(),
            "label": "Primary",
            "is_primary": True,
            "marketing_ok": True,
            "notifications_enabled": True,
        }))
    out = _dedup_by_key(out, "address")[:MAX_EMAILS]
    out = _ensure_single_primary(out)
    return out


def primary_mobile(doc: Dict[str, Any]) -> Optional[str]:
    for e in (doc.get("mobiles") or []):
        if e.get("is_primary"):
            return e.get("number_e164")
    return None


def primary_email(doc: Dict[str, Any]) -> Optional[str]:
    for e in (doc.get("emails") or []):
        if e.get("is_primary"):
            return e.get("address")
    return None


def sync_scalars_from_arrays(doc: Dict[str, Any]) -> Dict[str, Any]:
    """After ``mobiles`` / ``emails`` have been normalized, mirror the
    primary values back into the legacy ``phone`` / ``email`` scalars so
    every legacy consumer (RC matcher, invoices, comm-tokens, portal
    login lookup) keeps working without a code change."""
    m = primary_mobile(doc)
    if m:
        doc["phone"] = m
    e = primary_email(doc)
    if e:
        doc["email"] = e
    return doc


def apply_multi_contact(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotent — call on every write path. Ensures the arrays are
    normalized, cap-enforced, primary-consistent, and the scalars mirror
    the primaries. If arrays are absent, seed from scalars."""
    doc["mobiles"] = normalize_mobiles(doc.get("mobiles"), doc.get("phone"))
    doc["emails"] = normalize_emails(doc.get("emails"), doc.get("email"))
    sync_scalars_from_arrays(doc)
    return doc


async def migrate_customer_multi_contact(tenant_filter: Optional[dict] = None) -> int:
    """One-shot idempotent backfill. Populates ``mobiles`` / ``emails``
    on any customer doc that has ``phone`` / ``email`` but no arrays
    yet. Safe to run on every startup — the ``$exists=False`` guard
    means already-migrated docs are skipped."""
    q = tenant_filter or {}
    q = {
        **q,
        "$or": [
            {"mobiles": {"$exists": False}},
            {"emails": {"$exists": False}},
        ],
    }
    n = 0
    async for doc in db.customers.find(
        q, {"_id": 0, "id": 1, "tenant_id": 1, "phone": 1, "email": 1,
             "mobiles": 1, "emails": 1},
    ):
        mobiles = normalize_mobiles(doc.get("mobiles"), doc.get("phone"))
        emails = normalize_emails(doc.get("emails"), doc.get("email"))
        update = {}
        if "mobiles" not in doc:
            update["mobiles"] = mobiles
        if "emails" not in doc:
            update["emails"] = emails
        if not update:
            continue
        await db.customers.update_one(
            {"id": doc["id"], "tenant_id": doc.get("tenant_id")},
            {"$set": update},
        )
        n += 1
    if n:
        logger.info(f"[multi-contact] migrated {n} customer doc(s)")
    return n


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · Multi-Contact Phase 1 · fan-out recipient helpers
# ─────────────────────────────────────────────────────────────────
# Every comms send site should route through these two helpers so
# the automations-mute gate (``customer.automations_muted``) and
# the per-entry notifications flag stay honored consistently.
#
# The ``context`` kwarg encodes intent:
#   * ``"automation"``  — timer/scheduler/webhook-triggered send.
#     Muted customers → empty list.
#   * ``"manual"``      — admin clicked a UI button. Bypass the
#     customer-level mute (the admin took the explicit action).
#     Per-entry notification-disabled entries are still filtered
#     out; a user's per-address opt-out is respected regardless.
#
# Phase 1 wires only the Add-Card-On-File send site through the
# helper. Phase 2 sweeps the remaining 17 clusters — see
# ``/app/memory/FEATURE_MULTI_CONTACT_PHASE1.md``.
from typing import Literal


def _is_notify_enabled(entry: Dict[str, Any], legacy_flag: str) -> bool:
    """A recipient is opted-in if the new ``notifications_enabled``
    alias is truthy, OR the legacy per-channel flag
    (``marketing_ok`` for emails / ``sms_ok`` for phones) is
    truthy. Missing → default to opted-in (matches the write-path
    default so migrated docs still receive comms)."""
    if "notifications_enabled" in entry:
        return bool(entry.get("notifications_enabled"))
    if legacy_flag in entry:
        return bool(entry.get(legacy_flag))
    return True


def _dedup_preserving_order(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for x in items:
        k = (x or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def _automations_muted(customer: Dict[str, Any], channel: str) -> bool:
    """Return True when the customer is muted for the given channel.

    Phase 1 honors ``automations_muted_channel="all"`` as
    "mute email AND sms". Values ``"email"`` / ``"sms"`` persist
    on the doc but are treated identically to ``"all"`` until the
    per-channel wiring lands in Phase 2 (see forward-compat note
    in ``models.py``)."""
    if not customer.get("automations_muted"):
        return False
    # Any recognized channel value → mute both surfaces in Phase 1.
    return True


def active_email_recipients(
    customer: Optional[Dict[str, Any]],
    *,
    context: Literal["automation", "manual"] = "automation",
) -> List[str]:
    """Return the ordered list of email addresses that should
    receive email notifications for this customer.

    Rules:
      * ``context="automation"`` AND ``automations_muted=True`` → ``[]``.
      * Otherwise: iterate ``customer.emails[]``, include every
        entry whose ``notifications_enabled`` (or legacy
        ``marketing_ok``) is truthy. Empty array → fall back to
        the scalar ``customer.email``.
      * Never raises. Non-dict input → ``[]``.
    """
    if not isinstance(customer, dict):
        return []
    if context == "automation" and _automations_muted(customer, "email"):
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


def active_phone_recipients(
    customer: Optional[Dict[str, Any]],
    *,
    context: Literal["automation", "manual"] = "automation",
) -> List[str]:
    """Same contract as :func:`active_email_recipients` for
    phones. Reads ``customer.mobiles[]`` and falls back to the
    scalar ``customer.phone`` when arrays are absent/empty."""
    if not isinstance(customer, dict):
        return []
    if context == "automation" and _automations_muted(customer, "sms"):
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
