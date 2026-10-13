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

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

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
    # Feb-2026 · match-ladder expansion — populated when the
    # ladder's fuzzy tier found 2+ candidates at the minimum
    # distance so the FE can render the inline picker.  Each
    # entry is a dict with keys ``customer_id`` /
    # ``customer_name`` / ``customer_status`` / ``fuzzy_distance``.
    candidates: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MatchedExistingCustomer:
    """Feb-2026 · match-ladder expansion — one preview whose
    pending row resolved to an EXISTING customer via the ladder
    (any tier: active / inactive / muted / fuzzy).  No new
    customer row is inserted; the preview's ``customer_id`` is
    rewritten to the matched row's id, same mutation shape as
    :class:`AutoCreatedCustomer` with ``action="deduped_db"``.

    Distinct from :class:`AutoCreatedCustomer` because downstream
    audit + preview UI need to distinguish "attached to active"
    from "attached to inactive / muted / fuzzy" — the latter
    three are forensically interesting (operator should confirm
    the match post-commit).
    """
    source_doc_index: int
    pending_customer_id: str
    extracted_name: Optional[str]
    extracted_address: Optional[str]
    extracted_phone: Optional[str]
    matched_customer_id: str
    matched_customer_name: str
    matched_customer_status: str   # "active" | "inactive" | "muted"
    match_method: str              # "exact" | "fuzzy"
    match_confidence: float
    fuzzy_distance: Optional[int] = None


@dataclass
class AutoCreateResult:
    auto_created: List[AutoCreatedCustomer] = field(default_factory=list)
    manual_review_needed: List[ManualReviewPreview] = field(default_factory=list)
    # Feb-2026 · match-ladder expansion — populated when the
    # ladder resolved a pending row to an existing customer
    # (any tier).  Caller audit path reads this to emit the
    # ``customers_matched_{inactive,muted,fuzzy}`` lists.
    matched_existing: List[MatchedExistingCustomer] = field(default_factory=list)


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
    customer_match_overrides: Optional[Dict[str, str]] = None,
) -> AutoCreateResult:
    """Resolve every ``PENDING::<uuid>`` sentinel in ``previews``
    by either (a) matching to an existing ``db.customers`` row
    via the dedupe policy or (b) inserting a fresh row.

    Mutates ``previews`` in-place. See module docstring for
    the full contract.

    Feb-2026 · auto-create UX ticket — pendings on previews
    flagged ``customer_extraction_confidence == "low"`` (Bug 3
    post-processor) are routed to ``manual_review_needed`` with
    ``reason="customer_extraction_confidence_low"`` instead of
    being auto-created.  Hard rule: low-confidence extractions
    cannot mint real customer rows.

    Feb-2026 · match-ladder expansion — before falling through
    to insert, run :func:`run_match_ladder` for the extracted
    name/address/phone and attach to the matched existing
    customer when the ladder returns a hit.  ``customer_match_
    overrides`` is a per-pending-id dict mapping pending ids
    to override actions:

      * ``"reject_fuzzy"`` — operator reviewed the dry-run
        fuzzy match and rejected it.  Skip the fuzzy tier for
        this pending; still try exact tiers (dispatch spec:
        "backend honors it — does NOT attach to the fuzzy-
        matched customer").  If exact tiers also miss, falls
        through to auto-create.

    Ambiguous fuzzy matches (ladder returns ``requires_manual_
    resolution``) are added to ``manual_review_needed`` with
    ``candidates`` populated so the FE can render the picker.
    """
    batch_id = batch.get("id") or batch.get("batch_id")
    result = AutoCreateResult()
    overrides = customer_match_overrides or {}

    # Collect low-confidence pending ids FIRST so we never
    # auto-create for a row Bug 3 demoted.
    low_conf_pids = collect_low_confidence_pending_ids(previews)

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

        # Low-confidence gate — Bug 3 flagged this pending's name
        # as doc-number-shaped. Never auto-create; route to
        # manual_review for operator resolution.
        if pending_id in low_conf_pids:
            result.manual_review_needed.append(ManualReviewPreview(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=(pending_row or {}).get(
                    "extracted_customer_name"
                ),
                reason="customer_extraction_confidence_low",
            ))
            continue

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

        # Tier 2: DB-side ladder — exact (per status) then fuzzy.
        # Feb-2026 · match-ladder expansion — the previous
        # ``_find_existing_customer`` scanned the full not-soft-
        # deleted pool with normalized name/address/phone equality
        # and did NOT partition by ``is_active`` / ``is_muted``.
        # The ladder now surfaces the matched row's status
        # (active / inactive / muted / fuzzy) + method so the
        # audit payload + preview UI can distinguish forensically-
        # interesting attachments ("inactive" / "muted" / "fuzzy")
        # from the common active-exact case.  Rejected-fuzzy
        # overrides from the FE are honoured by cycling the
        # fuzzy ceiling down to 0 for just this pending.
        from services.imports.customer_match_ladder import (
            run_match_ladder, _FUZZY_MAX_DIST,
        )
        reject_fuzzy = (overrides.get(pending_id) == "reject_fuzzy")
        ladder = await run_match_ladder(
            db=db, tenant_id=tenant_id,
            extracted_name=name,
            extracted_address=address,
            extracted_phone=phone,
            # Lower the ceiling to -1 so fuzzy tier never fires
            # when the operator rejected the dry-run fuzzy match.
            # Negative ceiling makes every candidate's distance >
            # ceiling, so the fuzzy branch is a no-op.  Tiers 1-3
            # (exact per status) still run.
            max_fuzzy_distance=(-1 if reject_fuzzy else _FUZZY_MAX_DIST),
        )
        if ladder.match_status in {"active", "inactive", "muted",
                                     "fuzzy_match"}:
            resolved_id = ladder.matched_customer_id or ""
            resolved_name = ladder.matched_customer_name or name
            batch_dedupe[dedupe_key] = resolved_id
            _apply_resolution_to_previews(
                previews=previews, refs=refs,
                resolved_customer_id=resolved_id,
                resolved_name=resolved_name,
            )
            await _stamp_pending_resolved(
                db=db, tenant_id=tenant_id,
                pending_id=pending_id, resolved_id=resolved_id,
                at_iso=now_iso,
            )
            # The caller distinguishes "matched existing" from
            # "auto-created" via the ``matched_existing`` list.
            # The legacy ``auto_created`` list still carries
            # ``action="deduped_db"`` for back-compat with the
            # pre-ladder commit path's audit shape — any
            # consumer that already walks ``auto_created`` with
            # ``action == "deduped_db"`` still sees these rows.
            matched = MatchedExistingCustomer(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=name,
                extracted_address=address,
                extracted_phone=phone,
                matched_customer_id=resolved_id,
                matched_customer_name=resolved_name,
                matched_customer_status=(
                    ladder.matched_customer_status or "active"
                ),
                match_method=ladder.match_method or "exact",
                match_confidence=ladder.match_confidence or 1.0,
                fuzzy_distance=ladder.fuzzy_distance,
            )
            result.matched_existing.append(matched)
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
        if ladder.match_status == "requires_manual_resolution":
            # Fuzzy ambiguity (2+ candidates at min distance) —
            # the ladder never silently attaches to the wrong
            # customer.  Operator picks via inline picker.
            result.manual_review_needed.append(ManualReviewPreview(
                source_doc_index=first_doc_idx,
                pending_customer_id=pending_id,
                extracted_name=name or None,
                reason="fuzzy_match_ambiguous",
                candidates=[
                    {
                        "customer_id": c.customer_id,
                        "customer_name": c.customer_name,
                        "customer_status": c.customer_status,
                        "fuzzy_distance": c.fuzzy_distance,
                    } for c in ladder.candidates
                ],
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


def compute_dedup_group_id(
    *,
    name: Optional[str],
    address: Optional[str],
    phone: Optional[str],
) -> str:
    """Public helper — stable short id for a (name, address, phone)
    tuple using the same dedupe-key as the commit path. Used by
    ``classify_pending_for_preview`` so the preview badge count
    matches what commit actually produces.

    Returns an 8-char hex digest of the dedupe key.  Collisions
    are astronomically rare for the import-batch cardinality this
    helper is called on (dozens of pending rows at most).
    """
    norm_name = _norm_text(name)
    norm_addr = _norm_text(address)
    norm_phone = _norm_phone(phone)
    if not norm_name and not norm_addr and not norm_phone:
        # Zero-signal row — caller should not call this; return a
        # sentinel so collisions are impossible in practice.
        return "zerosig_" + hashlib.sha256(
            (name or address or phone or "").encode("utf-8")
        ).hexdigest()[:8]
    key = _build_dedupe_key(norm_name, norm_addr, norm_phone)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def collect_low_confidence_pending_ids(
    previews: List[Dict[str, Any]],
) -> Set[str]:
    """Walk previews and collect every ``pending_customer_id`` on
    a row flagged by Bug 3's post-processor as
    ``customer_extraction_confidence == "low"``.  Those pendings
    MUST NOT auto-create — the extracted name is untrustworthy
    (matched a doc-number pattern) and the operator has to resolve
    manually before commit.
    """
    out: Set[str] = set()
    for preview in previews or []:
        for field_name in ("quote_in", "payment_in"):
            sub = preview.get(field_name) or {}
            if sub.get("customer_extraction_confidence") != "low":
                continue
            cid = sub.get("customer_id") or ""
            if isinstance(cid, str) and cid.startswith("PENDING::"):
                out.add(cid[len("PENDING::"):])
    return out


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
        # Feb-2026 · auto-create UX ticket — explicit alias +
        # service_category default. ``created_by`` is a sibling
        # alias to ``source`` so audit queries that filter on
        # ``created_by`` land auto-created rows without a schema
        # migration. ``service_category="both"`` is the safe
        # default per the ``customers.service_category`` enum
        # (``pool`` | ``landscaping`` | ``both`` | ``unset``);
        # operators may refine on the Customer Detail page after
        # the batch commits.
        "created_by": "pdf_import",
        "service_category": "both",
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
