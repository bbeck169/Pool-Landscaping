"""Pricebook writeback · Feb-2026 · Invoice inline edit sprint.

Fans out AFTER a successful invoice / quote save to update (or
create) linked pricebook items when a line-item carries the
``pricebook_writeback=True`` flag. Never blocks the invoice save —
this is a purely additive side-effect.

Rules:
  1. Only lines with ``pricebook_writeback == True`` are processed.
  2. Lines with an ``item_id`` / ``pricebook_item_id`` update that
     row's ``unit_price`` (and ``category`` if the line's category
     resolves cleanly to a known income category).
  3. Lines without a pricebook FK become NEW pricebook items using
     ``description`` as the item name (case-insensitive dedup against
     the tenant's existing items — if a name match exists, we UPDATE
     it instead of creating a duplicate).
  4. Every writeback row is audited to ``db.pricebook_writeback_events``
     with a compact before/after diff, the actor + timestamp, and
     the parent invoice id for the ledger.
  5. Tenant boundary is authoritative: never touches an item that
     doesn't belong to the caller's tenant.
  6. Idempotency: the last write for a given ``pricebook_item_id``
     in a single payload wins. Two lines writing back to the same
     item is a "last-write-wins" contract by design; a note is
     emitted so the frontend can warn the operator.

The helper NEVER raises — every failure is logged and returned in
the response for visibility; the invoice save always stands.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db, logger


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _find_matching_pricebook_item(
    tenant_id: str, description: str,
) -> Optional[Dict[str, Any]]:
    """Case-insensitive name lookup on the caller's tenant."""
    if not tenant_id or not description or not description.strip():
        return None
    import re as _re
    return await db.items.find_one(
        {
            "tenant_id": tenant_id,
            "name": {"$regex": f"^{_re.escape(description.strip())}$",
                     "$options": "i"},
            "$or": [{"deleted_at": None},
                    {"deleted_at": {"$exists": False}}],
        },
        {"_id": 0},
    )


async def process_pricebook_writebacks(
    *,
    tenant_id: str,
    invoice_id: str,
    line_items: List[Dict[str, Any]],
    actor: Dict[str, Any],
    origin: str = "pricebook_writeback",
) -> Dict[str, Any]:
    """Iterate line items with ``pricebook_writeback=True`` and
    reflect the invoice's ``unit_price`` / ``category`` back into the
    pricebook. Runs AFTER the invoice save transaction settles so a
    later invoice-save failure never mutates the pricebook.

    P55 · Feb-2026 — also propagates the modern taxonomy fields
    (``income_category_id`` / ``income_category_name`` /
    ``service_category_id`` / ``service_category_name``) from the
    invoice line onto the Pricebook row via ``$set``. Existing rows
    that lacked the modern fields have them created (Q2/Option A).
    The legacy scalar ``category`` is kept in lockstep with
    ``income_category_id`` for backward-compat readers.

    ``origin`` — call-graph marker passed through to any downstream
    sync-orchestrator invocation from this path. Defaults to
    ``"pricebook_writeback"``, which is the origin that
    ``sync_invoice_line_to_pricebook`` short-circuits on (loop
    prevention). Kept as a kwarg so an alternate caller (e.g. a
    future bulk endpoint) can pass its own marker.

    Returns:
        ``{"processed": N, "updated": [item_ids],
          "created": [item_ids], "skipped": [line_indexes],
          "warnings": [str], "errors": [str]}``
    """
    updated: List[str] = []
    created: List[str] = []
    skipped: List[int] = []
    warnings: List[str] = []
    errors: List[str] = []

    if not tenant_id:
        return {"processed": 0, "updated": updated, "created": created,
                "skipped": skipped, "warnings": warnings,
                "errors": ["missing tenant_id — writeback skipped"]}

    # Detect "two lines write to the same pricebook item" and warn —
    # last write wins (deterministic given the payload order).
    seen_pb_ids: Dict[str, int] = {}
    for idx, li in enumerate(line_items or []):
        if not li.get("pricebook_writeback"):
            continue
        pb_id = li.get("item_id") or li.get("pricebook_item_id")
        if pb_id:
            if pb_id in seen_pb_ids:
                warnings.append(
                    f"lines {seen_pb_ids[pb_id]} and {idx} both writeback "
                    f"to pricebook item {pb_id} — last edit wins"
                )
            seen_pb_ids[pb_id] = idx

    for idx, li in enumerate(line_items or []):
        if not li.get("pricebook_writeback"):
            continue
        try:
            desc = (li.get("description") or "").strip()
            if not desc:
                skipped.append(idx)
                warnings.append(f"line {idx} has no description — writeback skipped")
                continue
            try:
                new_price = float(li.get("unit_price") or 0)
            except (TypeError, ValueError):
                skipped.append(idx)
                warnings.append(f"line {idx} has invalid unit_price — writeback skipped")
                continue
            new_category = (li.get("category") or "").strip() or None
            # P55 · Feb-2026 — modern taxonomy fields on the line
            # item. Empty strings are treated as absent so an
            # unset line doesn't nuke the Pricebook row's category.
            _li_income_id = (li.get("income_category_id") or "").strip() or None
            _li_income_nm = (li.get("income_category_name") or "").strip() or None
            _li_service_id = (li.get("service_category_id") or "").strip() or None
            _li_service_nm = (li.get("service_category_name") or "").strip() or None

            pb_id = li.get("item_id") or li.get("pricebook_item_id")
            existing: Optional[Dict[str, Any]] = None
            if pb_id:
                existing = await db.items.find_one(
                    {"id": pb_id, "tenant_id": tenant_id},
                    {"_id": 0},
                )
                if existing is None:
                    # FK pointed at another tenant's item (or a deleted
                    # one). Don't cross the tenant boundary — fall
                    # through to the name-match branch below.
                    pb_id = None

            if not existing:
                existing = await _find_matching_pricebook_item(tenant_id, desc)

            if existing:
                target_id = existing["id"]
                if existing.get("tenant_id") and existing["tenant_id"] != tenant_id:
                    errors.append(
                        f"tenant boundary violation blocked for item {target_id}"
                    )
                    continue
                before = {
                    "unit_price": existing.get("unit_price"),
                    "category": existing.get("category"),
                }
                patch: Dict[str, Any] = {
                    "unit_price": new_price,
                    "updated_at": _now().isoformat(),
                    "updated_by_user_id": (actor or {}).get("id"),
                }
                if new_category and new_category != existing.get("category"):
                    patch["category"] = new_category
                # P55 · Feb-2026 — modern taxonomy fields. \$set
                # creates them on rows that lacked them (Q2/Option
                # A) and updates them where present. NEVER sets to
                # None from an absent line — Pricebook is master;
                # a downstream ephemeral clear must not wipe the
                # master (Q · policy).
                if _li_income_id and _li_income_id != existing.get("income_category_id"):
                    patch["income_category_id"] = _li_income_id
                    # Legacy \`category\` scalar in lockstep.
                    patch["category"] = _li_income_id
                if _li_income_nm and _li_income_nm != existing.get("income_category_name"):
                    patch["income_category_name"] = _li_income_nm
                if _li_service_id and _li_service_id != existing.get("service_category_id"):
                    patch["service_category_id"] = _li_service_id
                if _li_service_nm and _li_service_nm != existing.get("service_category_name"):
                    patch["service_category_name"] = _li_service_nm
                await db.items.update_one(
                    {"id": target_id, "tenant_id": tenant_id},
                    {"$set": patch},
                )
                updated.append(target_id)
                await _write_audit(
                    tenant_id=tenant_id, invoice_id=invoice_id,
                    line_item_index=idx, pricebook_item_id=target_id,
                    action="update", actor=actor,
                    before=before,
                    after={"unit_price": new_price,
                            "category": patch.get("category") or existing.get("category")},
                )
            else:
                # No pricebook match — create a new row using the
                # line's description as the name.
                new_id_val = str(uuid.uuid4())
                doc = {
                    "id": new_id_val,
                    "tenant_id": tenant_id,
                    "name": desc,
                    "unit_price": new_price,
                    "unit": "each",
                    "category": _li_income_id or new_category or "Other",
                    "item_type": "service",  # created via writeback → service (unlocked pricing)
                    "created_at": _now().isoformat(),
                    "created_by_user_id": (actor or {}).get("id"),
                    "source": "invoice_writeback",
                    "source_invoice_id": invoice_id,
                }
                # P55 · Feb-2026 — modern taxonomy fields on
                # freshly-created Pricebook rows. Omit keys with
                # empty values so we never insert dead ``None``s.
                if _li_income_id:
                    doc["income_category_id"] = _li_income_id
                if _li_income_nm:
                    doc["income_category_name"] = _li_income_nm
                if _li_service_id:
                    doc["service_category_id"] = _li_service_id
                if _li_service_nm:
                    doc["service_category_name"] = _li_service_nm
                await db.items.insert_one(dict(doc))
                created.append(new_id_val)
                await _write_audit(
                    tenant_id=tenant_id, invoice_id=invoice_id,
                    line_item_index=idx, pricebook_item_id=new_id_val,
                    action="create", actor=actor,
                    before=None,
                    after={"unit_price": new_price,
                            "category": doc["category"], "name": desc},
                )
        except Exception as exc:                                     # noqa: BLE001
            errors.append(f"line {idx}: {type(exc).__name__}: {exc}")
            logger.exception(
                "[pricebook_writeback] failed for invoice=%s line=%d",
                invoice_id, idx,
            )

    return {
        "processed": len(updated) + len(created),
        "updated": updated,
        "created": created,
        "skipped": skipped,
        "warnings": warnings,
        "errors": errors,
    }


async def _write_audit(
    *,
    tenant_id: str,
    invoice_id: str,
    line_item_index: int,
    pricebook_item_id: str,
    action: str,
    actor: Dict[str, Any],
    before: Optional[Dict[str, Any]],
    after: Dict[str, Any],
) -> None:
    """Log a single writeback event. Best-effort — never re-raises."""
    try:
        await db.pricebook_writeback_events.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "invoice_id": invoice_id,
            "line_item_index": line_item_index,
            "pricebook_item_id": pricebook_item_id,
            "action": action,
            "before": before,
            "after": after,
            "actor_user_id": (actor or {}).get("id"),
            "actor_email": (actor or {}).get("email"),
            "actor_role": (actor or {}).get("role"),
            "source": "invoice_writeback",
            "created_at": _now().isoformat(),
        })
    except Exception:                                                # noqa: BLE001
        logger.exception(
            "[pricebook_writeback.audit] insert failed for invoice=%s",
            invoice_id,
        )
