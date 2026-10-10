"""Phase 33 Step B · Feb-2026 — PDF-import auto-create customer helper.

Materialises every ``PENDING::<uuid>`` sentinel in a mapper preview
list into a real ``db.customers`` row BEFORE the commit path's
unresolved-customer gate runs. Prior to this helper, any preview
carrying a PENDING sentinel blocked the entire batch commit (400
``unresolved_customers``) and required manual operator intervention
via the admin review UI — even when the extractor had already
captured a name, address, and phone that would be trivially
sufficient to spin a fresh customer row.

Dedupe policy (approved Phase 33 investigation ruling):

  Primary key   — ``(tenant_id, name_lower_trimmed, address_lower_trimmed)``
                  Both halves non-empty.
  Fallback key  — ``(tenant_id, name_lower_trimmed)`` when address blank.
  Fallback key  — ``(tenant_id, phone_digits)`` when name blank.

In-batch dedupe runs first — two previews referencing the same
pending customer_id (or two different pending ids whose extracted
name+address collide, which happens when the mapper processes two
PDFs for the same new customer in one upload batch) collapse into
ONE ``db.customers.insert_one`` call. DB-side dedupe then runs
against existing ``db.customers`` so an invoice referencing a
customer who already exists under a different pending id resolves
to the pre-existing row with zero inserts.

Rows that carry NO identifying info (name AND address AND phone
all blank) are left as truly manual-review previews and surface to
the caller via :class:`AutoCreateResult.manual_review_needed`. The
caller (``pdf_commit.commit_batch``) then raises
``UnresolvedCustomersError`` for those residuals only.

Side effects
------------

* Mutates each resolved preview in-place — ``quote_in.customer_id``
  (and ``payment_in.customer_id`` when attached) is rewritten from
  the ``PENDING::`` sentinel to the real ``customer_id``.
  Downstream duplicate-scan + paid-status checks + ``insert_many``
  then operate on the resolved id.
* Inserts into ``db.customers`` — new rows carry
  ``source="pdf_import"`` and ``created_via="pdf_import_auto"`` for
  audit traceability. The regular customer-create helper chain
  (``_sync_customer_names`` / ``_apply_multi_contact`` /
  ``_apply_vip_stamp``) is NOT invoked — those are UI conveniences
  the operator can trigger from the Customer Detail page after the
  batch commits. The haystack writer IS invoked so the newly
  minted customer shows up in global search on next poll.
* Stamps ``pending_import_customers.resolved_customer_id`` on
  every walked pending row so a resumed commit never re-dedupes
  the same pending id.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils import new_id


logger = logging.getLogger("imports.customer_autocreate")


# ═════════════════════════════════════════════════════════════
# Public dataclasses
# ═════════════════════════════════════════════════════════════
@dataclass
class AutoCreatedCustomer:
    """One previously-PENDING customer that now resolves to a
    real ``db.customers`` row (new insert OR dedupe hit against
    an existing row).

    Attributes:
      * ``source_doc_index`` — index of the FIRST preview the
        pending customer appeared on (if the same pending
        customer appears on multiple previews, only the first
        is reported here; the resolved id is applied to all).
      * ``pending_customer_id`` — the uuid portion of the
        original ``PENDING::<uuid>`` sentinel.
      * ``extracted_name`` / ``extracted_address`` /
        ``extracted_phone`` — raw extractor values persisted
        onto the real customer row.
      * ``resolved_customer_id`` — the real ``db.customers.id``
        the preview was rewritten to.
      * ``action`` — one of:
          - ``"created"`` — new ``db.customers`` row inserted.
          - ``"deduped_db"`` — matched an existing customer
            via the primary / fallback dedupe keys. No insert.
          - ``"deduped_batch"`` — matched another pending row
            inside the SAME batch (first occurrence inserted,
            later occurrences resolve to the first insert).
    """
    source_doc_index: int
    pending_customer_id: str
    extracted_name: Optional[str]
    extracted_address: Optional[str]
    extracted_phone: Optional[str]
    resolved_customer_id: str
    action: str  # "created" | "deduped_db" | "deduped_batch"


@dataclass
class ManualReviewPreview:
    """One preview whose pending row carries no identifying
    info (name AND address AND phone all blank) — auto-create
    cannot resolve. The caller surfaces these as the only
    residual ``UnresolvedCustomersError`` cases.
    """
    source_doc_index: int
    pending_customer_id: Optional[str]
    extracted_name: Optional[str]
    reason: str = "no_identifying_info"


@dataclass
class AutoCreateResult:
    auto_created: List[AutoCreatedCustomer] = field(default_factory=list)
    manual_review_needed: List[ManualReviewPreview] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════
# Normalisation helpers (shared across in-batch + DB lookups)
# ═════════════════════════════════════════════════════════════
def _norm_text(s: Optional[str]) -> str:
    """Lowercase + strip + collapse interior whitespace. Blank
    inputs normalise to ``""`` so missing-field dedupe tiers
    cleanly skip."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _norm_phone(s: Optional[str]) -> str:
    """Reduce a phone to digits-only. ``"(555) 123-4567"`` →
    ``"5551234567"``. Leading country-code 1 is retained so
    US pairs like ``"1-555-123-4567"`` and ``"555-123-4567"``
    do NOT dedupe (defensive — two numbers that differ by a
    country code might actually be different customers).
    """
    if not s:
        return ""
    return re.sub(r"\D", "", str(s))


# ═════════════════════════════════════════════════════════════
# Public entry point
# ═════════════════════════════════════════════════════════════
async def auto_create_pending_customers(
    *,
    previews: List[Dict[str, Any]],
    batch: Dict[str, Any],
    tenant_id: str,
    operator: Dict[str, Any],
    db,
) -> AutoCreateResult:
    """Resolve every ``PENDING::<uuid>`` sentinel in ``previews``
    by either (a) matching to an existing ``db.customers`` row
    via the dedupe policy or (b) inserting a fresh row.

    Mutates ``previews`` in-place. See module docstring for
    the full contract.
    """
    batch_id = batch.get("id") or batch.get("batch_id")
    result = AutoCreateResult()

    # ── Phase 1: collect pending ids referenced by previews ──
    # Walk BOTH ``quote_in.customer_id`` AND ``payment_in.customer_id``
    # since the mapper may stamp PENDING sentinels onto either.
    pending_refs: Dict[str, List[Tuple[int, str]]] = {}
    for preview in previews:
        source_doc_index = int(preview.get("source_doc_index", -1))
        for field_name in ("quote_in", "payment_in"):
            sub = preview.get(field_name) or {}
            cid = sub.get("customer_id") or ""
            if isinstance(cid, str) and cid.startswith("PENDING::"):
                pending_id = cid[len("PENDING::"):]
                pending_refs.setdefault(pending_id, []).append(
                    (source_doc_index, field_name)
                )

    if not pending_refs:
        return result

    # ── Phase 2: load pending_import_customers rows ──────────
    # Single ``find`` with ``$in`` keeps this to one round-trip.
    pending_rows: Dict[str, Dict[str, Any]] = {}
    cursor = db.pending_import_customers.find(
        {
            "tenant_id": tenant_id,
            "id": {"$in": list(pending_refs.keys())},
        },
        {"_id": 0},
    )
    async for row in cursor:
        pending_rows[row["id"]] = row

    # ── Phase 3: resolve each pending row ────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    # In-batch dedupe map: dedupe-key → resolved_customer_id
    batch_dedupe: Dict[str, str] = {}

    for pending_id, refs in pending_refs.items():
        pending_row = pending_rows.get(pending_id)
        first_doc_idx = refs[0][0]

        if pending_row is None:
            # The sentinel points at a pending row that no longer
            # exists (manual deletion / cross-batch race). We can't
            # resolve it — surface as manual-review.
            result.manual_review_needed.append(ManualReviewPreview(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=None,
                reason="pending_row_missing",
            ))
            continue

        # Idempotency: a prior commit attempt may have already
        # stamped ``resolved_customer_id`` on this row. Trust it
        # and skip the full dedupe/insert dance.
        prior_resolved = pending_row.get("resolved_customer_id")
        if prior_resolved:
            _apply_resolution_to_previews(
                previews=previews, refs=refs,
                resolved_customer_id=prior_resolved,
                resolved_name=pending_row.get("extracted_customer_name") or "",
            )
            result.auto_created.append(AutoCreatedCustomer(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=pending_row.get("extracted_customer_name"),
                extracted_address=pending_row.get("extracted_address"),
                extracted_phone=pending_row.get("extracted_phone"),
                resolved_customer_id=prior_resolved,
                action="deduped_db",
            ))
            continue

        name = pending_row.get("extracted_customer_name") or ""
        address = pending_row.get("extracted_address") or ""
        phone = pending_row.get("extracted_phone") or ""
        email = pending_row.get("extracted_email") or ""

        norm_name = _norm_text(name)
        norm_addr = _norm_text(address)
        norm_phone = _norm_phone(phone)

        if not norm_name and not norm_addr and not norm_phone:
            # Zero signal — surface as manual-review.
            result.manual_review_needed.append(ManualReviewPreview(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=name or None,
                reason="no_identifying_info",
            ))
            continue

        dedupe_key = _build_dedupe_key(norm_name, norm_addr, norm_phone)

        # Tier 1: in-batch dedupe.
        if dedupe_key in batch_dedupe:
            resolved_id = batch_dedupe[dedupe_key]
            _apply_resolution_to_previews(
                previews=previews, refs=refs,
                resolved_customer_id=resolved_id,
                resolved_name=name,
            )
            await _stamp_pending_resolved(
                db=db, tenant_id=tenant_id,
                pending_id=pending_id, resolved_id=resolved_id,
                at_iso=now_iso,
            )
            result.auto_created.append(AutoCreatedCustomer(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=name,
                extracted_address=address,
                extracted_phone=phone,
                resolved_customer_id=resolved_id,
                action="deduped_batch",
            ))
            continue

        # Tier 2: DB-side dedupe against existing customers.
        existing = await _find_existing_customer(
            db=db, tenant_id=tenant_id,
            norm_name=norm_name, norm_addr=norm_addr,
            norm_phone=norm_phone,
        )
        if existing:
            resolved_id = existing["id"]
            batch_dedupe[dedupe_key] = resolved_id
            _apply_resolution_to_previews(
                previews=previews, refs=refs,
                resolved_customer_id=resolved_id,
                resolved_name=existing.get("name") or name,
            )
            await _stamp_pending_resolved(
                db=db, tenant_id=tenant_id,
                pending_id=pending_id, resolved_id=resolved_id,
                at_iso=now_iso,
            )
            result.auto_created.append(AutoCreatedCustomer(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=name,
                extracted_address=address,
                extracted_phone=phone,
                resolved_customer_id=resolved_id,
                action="deduped_db",
            ))
            continue

        # Tier 3: insert a fresh ``db.customers`` row.
        new_customer_id = await _insert_auto_customer(
            db=db, tenant_id=tenant_id, batch_id=batch_id,
            name=name, address=address, phone=phone, email=email,
            operator=operator, at_iso=now_iso,
        )
        batch_dedupe[dedupe_key] = new_customer_id
        _apply_resolution_to_previews(
            previews=previews, refs=refs,
            resolved_customer_id=new_customer_id,
            resolved_name=name,
        )
        await _stamp_pending_resolved(
            db=db, tenant_id=tenant_id,
            pending_id=pending_id, resolved_id=new_customer_id,
            at_iso=now_iso,
        )
        result.auto_created.append(AutoCreatedCustomer(
            source_doc_index=first_doc_idx,
            pending_customer_id=pending_id,
            extracted_name=name,
            extracted_address=address,
            extracted_phone=phone,
            resolved_customer_id=new_customer_id,
            action="created",
        ))

    if result.auto_created or result.manual_review_needed:
        logger.info(
            "[pdf-import.autocreate] tenant=%s batch=%s "
            "pending_refs=%d created=%d deduped_db=%d "
            "deduped_batch=%d manual_review=%d",
            tenant_id, batch_id, len(pending_refs),
            sum(1 for c in result.auto_created if c.action == "created"),
            sum(1 for c in result.auto_created if c.action == "deduped_db"),
            sum(1 for c in result.auto_created if c.action == "deduped_batch"),
            len(result.manual_review_needed),
        )

    return result


# ═════════════════════════════════════════════════════════════
# Internals
# ═════════════════════════════════════════════════════════════
def _build_dedupe_key(
    norm_name: str, norm_addr: str, norm_phone: str,
) -> str:
    """Compose the deterministic dedupe key honouring the
    primary → fallback → phone-only tier ordering.

    * both name AND address present → ``name|address``
    * name present, address blank   → ``name|``
    * name blank, phone present     → ``phone:<digits>``
    * every tier empty              → unreachable (caller
      pre-filters zero-signal rows into manual_review_needed).
    """
    if norm_name and norm_addr:
        return f"{norm_name}|{norm_addr}"
    if norm_name:
        return f"{norm_name}|"
    return f"phone:{norm_phone}"


async def _find_existing_customer(
    *, db, tenant_id: str,
    norm_name: str, norm_addr: str, norm_phone: str,
) -> Optional[Dict[str, Any]]:
    """DB-side dedupe lookup. Scans the tenant's customers once,
    projecting only the fields the dedupe keys reference. The
    tenant-scoped find keeps the working set bounded; for the
    import-batch cardinality this helper is called on, that's
    well within acceptable latency.
    """
    projection = {"_id": 0, "id": 1, "name": 1, "address": 1, "phone": 1}
    cursor = db.customers.find(
        {"tenant_id": tenant_id, "deleted_at": {"$in": [None, "", False]}},
        projection,
    )
    async for row in cursor:
        row_name = _norm_text(row.get("name"))
        row_addr = _norm_text(row.get("address"))
        row_phone = _norm_phone(row.get("phone"))
        if norm_name and norm_addr:
            if row_name == norm_name and row_addr == norm_addr:
                return row
        elif norm_name:
            if row_name == norm_name:
                return row
        elif norm_phone:
            if row_phone == norm_phone:
                return row
    return None


async def _insert_auto_customer(
    *, db, tenant_id: str, batch_id: Optional[str],
    name: str, address: str, phone: str, email: str,
    operator: Dict[str, Any], at_iso: str,
) -> str:
    """Insert one fresh ``db.customers`` row with the audit
    sentinels Phase 33 locked in. Returns the new row's id.
    """
    new_customer_id = new_id()
    doc: Dict[str, Any] = {
        "id": new_customer_id,
        "tenant_id": tenant_id,
        "name": name or "",
        "address": address or "",
        "billing_address": "",
        "phone": phone or "",
        "home_phone": "",
        "email": email or "",
        "notes": "",
        "tags": [],
        "waitlisted": False,
        "secondary_addresses": [],
        "is_vip": False,
        "created_at": at_iso,
        "updated_at": at_iso,
        # Phase 33 Step B · Feb-2026 — provenance sentinels.
        # Downstream readers (Customer Detail, audit reports,
        # bulk-import rollback) read these to distinguish
        # auto-created customers from operator-created ones.
        "source": "pdf_import",
        "created_via": "pdf_import_auto",
        "created_by_user_id": (operator or {}).get("id"),
        "created_from_import_batch_id": batch_id,
    }
    # Haystack powers the customers-list fast path. The helper
    # is a pure in-place mutator — safe to run before insert.
    try:
        from services.customers_search_haystack import apply_haystack
        apply_haystack(doc)
    except Exception as exc:  # noqa: BLE001
        # Non-fatal — the boot-time backfill migration will
        # catch this row on the next pass.
        logger.warning(
            "[pdf-import.autocreate] haystack apply failed for "
            "tenant=%s customer=%s (non-fatal): %s",
            tenant_id, new_customer_id, exc,
        )
    await db.customers.insert_one(doc)
    return new_customer_id


async def _stamp_pending_resolved(
    *, db, tenant_id: str, pending_id: str,
    resolved_id: str, at_iso: str,
) -> None:
    """Mark the ``pending_import_customers`` row resolved so a
    retried commit short-circuits straight to the ``deduped_db``
    tier without re-running the full dedupe scan.
    """
    await db.pending_import_customers.update_one(
        {"tenant_id": tenant_id, "id": pending_id},
        {"$set": {
            "resolved_customer_id": resolved_id,
            "resolved_via": "pdf_import_auto",
            "resolved_at": at_iso,
        }},
    )


def _apply_resolution_to_previews(
    *,
    previews: List[Dict[str, Any]],
    refs: List[Tuple[int, str]],
    resolved_customer_id: str,
    resolved_name: str,
) -> None:
    """Rewrite ``quote_in.customer_id`` / ``payment_in.customer_id``
    on every preview that referenced the resolved pending id.
    Also refreshes ``customer_name`` so downstream readers (audit,
    FE badge rendering) see the canonical name on the resolved row.
    """
    by_idx: Dict[int, Dict[str, Any]] = {
        int(p.get("source_doc_index", -1)): p for p in previews
    }
    for source_doc_index, field_name in refs:
        preview = by_idx.get(source_doc_index)
        if preview is None:
            continue
        sub = preview.get(field_name) or {}
        sub["customer_id"] = resolved_customer_id
        if resolved_name and not sub.get("customer_name"):
            sub["customer_name"] = resolved_name
        preview[field_name] = sub
