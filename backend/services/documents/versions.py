"""Feb-2026 · Editable Sent Docs · Phase 1 — shared version-history
helper. One implementation covers three doc types:

  * ``quote``               → ``db.quotes`` where ``doc_type != "invoice"``
  * ``invoice``             → ``db.quotes`` where ``doc_type == "invoice"``
  * ``estimator_estimate``  → ``db.estimator_estimates``
  * ``estimate``            → ``db.estimates`` (legacy)

Public API:

  * :func:`snapshot_before_mutation` — mandatory call right BEFORE a
    write to any of the above collections. It:
      1. Ensures a baseline (``v1``, ``is_baseline=True``) row exists
         in ``db.document_versions`` for this doc.
      2. Inserts a new version row snapshotting the pre-edit state.
      3. Never raises — a version failure must NOT break the parent
         write. It logs and returns ``None`` in the failure case; the
         caller keeps going. (Losing a version row is annoying;
         losing the customer's edit because our audit crashed is
         unacceptable.)
  * :func:`invalidate_signature_if_present` — if the doc has a
    signed signature row, mark it ``superseded_at=now`` and clear
    ``signature_status`` on the doc. Returns True iff a signature
    was invalidated. Fire this AFTER the parent write succeeds.
  * :func:`normalize_doc_type` — kebab / underscore variants → the
    canonical value used in ``document_versions.doc_type``.

Guarantees:

  * Baseline (v1) captures pre-edit state EXACTLY ONCE per doc.
    Idempotent — a second call for the same doc is a no-op if v1
    already exists.
  * Version numbers are monotonic per ``(doc_type, doc_id)`` via a
    counted insert. No gaps unless a mid-flight insert raced and
    lost — the ``(doc_type, doc_id, version)`` unique index would
    make the loser retry.
  * ``doc_number`` immutability is enforced by callers, not here —
    this helper just snapshots what it's given.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import db


log = logging.getLogger("documents.versions")


# Canonical set of doc_type values used in ``db.document_versions``.
CANONICAL_DOC_TYPES = {
    "quote", "invoice", "estimator_estimate", "estimate",
}

# URL-friendly aliases → canonical.
_ALIAS_MAP = {
    "quotes":     "quote",
    "invoices":   "invoice",
    "estimator":  "estimator_estimate",
    "estimator-estimate": "estimator_estimate",
    "estimator_estimates": "estimator_estimate",
    "estimates":  "estimate",
}


def normalize_doc_type(raw: str) -> Optional[str]:
    """Return the canonical doc_type or None when unknown."""
    if not raw:
        return None
    v = raw.strip().lower().replace("-", "_")
    if v in CANONICAL_DOC_TYPES:
        return v
    return _ALIAS_MAP.get(v) or _ALIAS_MAP.get(v.replace("_", "-"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redact_snapshot(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo internals + any hydration-only fields before the
    snapshot lands in ``document_versions``. Keeps the row size
    reasonable and prevents ``_id`` collisions on re-hydrate."""
    out = dict(doc or {})
    out.pop("_id", None)
    return out


def _money(v: Any) -> float:
    """Coerce to float defensively — line_items subtotals may arrive
    as Decimal / int / str depending on the caller."""
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _line_item_signature(li: Any) -> tuple:
    """Feb-2026 · Phase 2 — canonical shape of a single line item
    for the change-summary diff.  We hash on
    ``(description, qty, unit_price, category)`` — the four fields
    users perceive as "the same line item".  ``id`` is ignored
    because the frontend regenerates it on every save (see
    ``QuoteInvoiceDetail`` :contentReference).
    """
    if not isinstance(li, dict):
        return (str(li), 0.0, 0.0, "")
    return (
        str(li.get("description") or li.get("name") or "").strip().lower(),
        _money(li.get("qty")),
        _money(li.get("unit_price") or li.get("price")),
        str(li.get("category") or "").strip().lower(),
    )


_SUMMARY_FIELDS = (
    ("subtotal", "$"),
    ("tax", "$"),
    ("total", "$"),
    ("amount_paid", "$"),
    ("due_date", "date"),
    ("notes", "text"),
    ("terms", "text"),
    ("title", "text"),
    ("status", "text"),
)


def compute_change_summary(
    prev_snapshot: Optional[Dict[str, Any]],
    curr_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Feb-2026 · Phase 2 — return a short human string + a numeric
    ``diff_field_count`` describing how ``curr_snapshot`` differs
    from ``prev_snapshot``.

    Returns ``{"change_summary": None, "diff_field_count": 0}`` when
    ``prev_snapshot`` is missing (baseline version) or the two
    snapshots are byte-identical.  Otherwise returns a short
    comma-joined string of the highest-signal changes plus the
    total count of high-signal fields that moved.

    Kept intentionally deterministic — the same input always
    produces the same string — so drawer copy is stable across
    reloads and pytest can pin the assertion.
    """
    if not prev_snapshot or not curr_snapshot:
        return {"change_summary": None, "diff_field_count": 0}

    parts: list[str] = []
    diff_count = 0

    # ── Line items ───────────────────────────────────────────
    prev_li = prev_snapshot.get("line_items") or []
    curr_li = curr_snapshot.get("line_items") or []
    if isinstance(prev_li, list) and isinstance(curr_li, list):
        prev_sigs = [_line_item_signature(li) for li in prev_li]
        curr_sigs = [_line_item_signature(li) for li in curr_li]
        added = max(0, len(curr_sigs) - len(prev_sigs))
        removed = max(0, len(prev_sigs) - len(curr_sigs))
        # An "edit" is a line item whose signature changed at the
        # same index — count only up to min(len).  This intentionally
        # over-counts reorders as edits (cheap approximation vs. a
        # full LCS), which is fine for a summary blurb.
        edited = 0
        for a, b in zip(prev_sigs, curr_sigs):
            if a != b:
                edited += 1
        if added:
            parts.append(
                f"{added} line item{'s' if added != 1 else ''} added",
            )
            diff_count += 1
        if removed:
            parts.append(
                f"{removed} line item{'s' if removed != 1 else ''} removed",
            )
            diff_count += 1
        if edited:
            parts.append(
                f"{edited} line item{'s' if edited != 1 else ''} edited",
            )
            diff_count += 1

    # ── Money + text field deltas ────────────────────────────
    for field, kind in _SUMMARY_FIELDS:
        prev_v = prev_snapshot.get(field)
        curr_v = curr_snapshot.get(field)
        if kind == "$":
            p, c = _money(prev_v), _money(curr_v)
            if abs(p - c) < 0.005:
                continue
            delta = c - p
            sign = "+" if delta >= 0 else "-"
            parts.append(
                f"{field} {sign}${abs(delta):,.2f}",
            )
            diff_count += 1
        else:
            if (prev_v or "") == (curr_v or ""):
                continue
            # Text/date fields: just note that they changed — the
            # raw new value is often multi-line notes not worth
            # inlining into a summary blurb.
            label = "Notes" if field == "notes" else (
                "Terms" if field == "terms" else field.title()
            )
            parts.append(f"{label} updated")
            diff_count += 1

    # Byte-identical snapshots → nothing to report.
    if not parts:
        return {"change_summary": None, "diff_field_count": 0}

    return {
        "change_summary": ", ".join(parts),
        "diff_field_count": diff_count,
    }


async def _next_version_number(*, doc_type: str, doc_id: str) -> int:
    """Return the next monotonic version number for this doc."""
    last = await db.document_versions.find_one(
        {"doc_type": doc_type, "doc_id": doc_id},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    if last and isinstance(last.get("version"), int):
        return last["version"] + 1
    return 1


async def snapshot_before_mutation(
    *,
    doc_type: str,
    doc_id: str,
    tenant_id: Optional[str],
    current_doc: Dict[str, Any],
    saved_by_user: Dict[str, Any],
    status_at_edit: Optional[str] = None,
    reason: Optional[str] = None,
    lock_bypass_ack: bool = False,
    signature_invalidated: bool = False,
    new_doc: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Ensure baseline + insert pre-edit snapshot. Return the newly
    inserted version row (metadata only, no snapshot body) or
    ``None`` on failure. Never raises.

    Idempotency: safe to call twice in the same request as long as
    the caller does its own ordering — a second call would insert a
    third version identical to the second.

    ``current_doc`` MUST be the pre-mutation state. The caller
    reads the doc, calls this helper, then applies the mutation.
    """
    canonical = normalize_doc_type(doc_type)
    if not canonical:
        log.warning("[documents.versions] unknown doc_type=%r — skipping",
                    doc_type)
        return None
    if not doc_id or not current_doc:
        return None

    try:
        # 1. Baseline check — insert v1 if this doc has no history yet.
        existing = await db.document_versions.find_one(
            {"doc_type": canonical, "doc_id": doc_id},
            {"_id": 0, "version": 1},
            sort=[("version", -1)],
        )
        if not existing:
            baseline = {
                "id": str(uuid.uuid4()),
                "doc_type": canonical,
                "doc_id": doc_id,
                "tenant_id": tenant_id,
                "version": 1,
                "is_baseline": True,
                "snapshot": _redact_snapshot(current_doc),
                "saved_by_user_id": "system",
                "saved_by_user_email": "system",
                "saved_by_role": "system",
                "saved_at": _now(),
                "status_at_edit": status_at_edit
                                    or (current_doc.get("status") or "draft"),
                "reason": "retroactive_baseline",
                "changed_fields": [],
                # Feb-2026 · Phase 2 — baseline has no prior snapshot
                # to diff against by definition.
                "change_summary": None,
                "diff_field_count": 0,
                "lock_bypass_ack": False,
                "signature_invalidated": False,
                "restore_of_version": None,
            }
            await db.document_versions.insert_one(dict(baseline))
            next_v = 2
        else:
            next_v = existing["version"] + 1

        # Feb-2026 · Phase 2 — the change_summary attached to v(N)
        # describes the edit that transitions the current state
        # (``current_doc``, pre-mutation) into the target state
        # (``new_doc``, post-mutation).  This is the intuitive UI
        # semantics — every non-baseline row's summary describes
        # "the edit that produced this snapshot's context" (not
        # a diff between prior stored versions, which would over-
        # report when snapshots are duplicated across a single
        # baseline-plus-first-edit pair).
        if new_doc is not None:
            _summary = compute_change_summary(current_doc, new_doc)
        else:
            _summary = {"change_summary": None, "diff_field_count": 0}

        # 2. Insert the pre-mutation snapshot.
        row = {
            "id": str(uuid.uuid4()),
            "doc_type": canonical,
            "doc_id": doc_id,
            "tenant_id": tenant_id,
            "version": next_v,
            "is_baseline": False,
            "snapshot": _redact_snapshot(current_doc),
            "saved_by_user_id": (saved_by_user or {}).get("id")
                                  or (saved_by_user or {}).get("_id") or "",
            "saved_by_user_email": (saved_by_user or {}).get("email") or "",
            "saved_by_role": (saved_by_user or {}).get("role") or "",
            "saved_at": _now(),
            "status_at_edit": status_at_edit
                                or (current_doc.get("status") or "draft"),
            "reason": reason,
            "changed_fields": [],
            # Feb-2026 · Phase 2 — write-time diff summary.
            "change_summary": _summary["change_summary"],
            "diff_field_count": _summary["diff_field_count"],
            "lock_bypass_ack": bool(lock_bypass_ack),
            "signature_invalidated": bool(signature_invalidated),
            "restore_of_version": None,
        }
        await db.document_versions.insert_one(dict(row))
        # Return metadata-only (client doesn't need the full body).
        meta = {k: v for k, v in row.items() if k != "snapshot"}
        return meta
    except Exception as exc:  # noqa: BLE001
        # Never let audit take down the parent write.
        log.exception(
            "[documents.versions] snapshot failed doc_type=%s doc_id=%s: %s",
            canonical, doc_id, exc,
        )
        return None


async def invalidate_signature_if_present(
    *,
    doc_type: str,
    doc_id: str,
    tenant_id: Optional[str],
    collection,
) -> bool:
    """If the doc has a signed signature row, mark that signature
    row ``superseded_at=now`` and clear ``signature_status`` on the
    doc. Idempotent — repeat calls are a no-op once the row is
    already superseded.

    Returns True iff a signature was newly invalidated. Never
    raises.

    ``collection`` is the Mongo collection object for the parent
    doc (``db.quotes`` / ``db.estimator_estimates`` / etc.).
    """
    try:
        # ``db.signatures`` uses ``doc_id`` (Phase 15A convention).
        # Legacy rows may key on ``quote_id``; check both.
        sig_q = {
            "$or": [
                {"doc_id": doc_id},
                {"quote_id": doc_id},
            ],
            "signed_at": {"$ne": None},
            "superseded_at": None,
        }
        if tenant_id:
            sig_q["tenant_id"] = tenant_id
        sig = await db.signatures.find_one(sig_q, {"_id": 0, "id": 1})
        if not sig:
            return False
        now = _now().isoformat()
        await db.signatures.update_one(
            {"id": sig["id"]},
            {"$set": {"superseded_at": now,
                       "superseded_reason": "doc_edited_after_signature"}},
        )
        # Clear the doc-side status hint. Preserve the sig id for
        # audit — the doc can still cross-ref via ``db.signatures``.
        update_q = {"id": doc_id}
        if tenant_id:
            update_q["tenant_id"] = tenant_id
        await collection.update_one(
            update_q,
            {"$set": {"signature_status": "superseded",
                       "signature_superseded_at": now}},
        )
        log.info(
            "[documents.versions] signature invalidated doc_type=%s "
            "doc_id=%s sig=%s",
            doc_type, doc_id, sig.get("id"),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.exception(
            "[documents.versions] signature invalidation failed "
            "doc_id=%s: %s", doc_id, exc,
        )
        return False


async def has_signature(*, doc_id: str, tenant_id: Optional[str]) -> bool:
    """Return True iff a signed, not-yet-superseded signature exists
    for this doc. Used by the caller to decide whether to fire
    :func:`invalidate_signature_if_present` at all."""
    try:
        sig_q = {
            "$or": [
                {"doc_id": doc_id},
                {"quote_id": doc_id},
            ],
            "signed_at": {"$ne": None},
            "superseded_at": None,
        }
        if tenant_id:
            sig_q["tenant_id"] = tenant_id
        sig = await db.signatures.find_one(sig_q, {"_id": 0, "id": 1})
        return bool(sig)
    except Exception:  # noqa: BLE001
        return False
