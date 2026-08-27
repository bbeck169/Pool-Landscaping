"""Feb 2026 · Customer Merge · Phase 1 — merge write path.

Strategy: ``newest_wins`` (the only supported strategy in Phase 1).

Reconciliation rules
--------------------
For every non-metadata field on the primary customer doc:

1. If the primary field is empty / missing → fill from the first
   non-empty secondary value (any secondary wins here — "first non-
   empty" is deterministic given a stable ``secondary_ids`` order).
2. If both primary AND secondary have differing non-empty values →
   the record with the newer ``updated_at`` (falling back to
   ``created_at``) wins. If the primary is newer or equal → keep
   primary; if a secondary is newer → overwrite primary with that
   secondary's value.
3. Metadata fields (``id``, ``tenant_id``, ``created_at``,
   ``updated_at``, ``deleted_at``, ``merged_into``, ``merged_at``,
   ``merged_by``, ``_id``) are NEVER touched on the primary and are
   ONLY stamped on secondaries (``merged_into``, ``merged_at``,
   ``merged_by``).

Related-record rewire
---------------------
FK field ``customer_id`` on: ``jobs``, ``quotes`` (invoices +
estimates unified), ``payments``, ``service_reports``,
``estimates`` (legacy separate collection), ``leads``. Per-tenant
scoped bulk update. Counts returned in the response dict split by
the buckets Phase 2 UI expects: ``jobs / invoices / payments /
service_reports / estimates / leads``.

Dry-run
-------
``dry_run=True`` — compute every value + count, do NOT execute
writes. Idempotent — safe to invoke repeatedly.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db
from utils import now_iso

from services.customer_merge.audit import write_merge_audit


_METADATA_FIELDS = frozenset({
    "id", "_id", "tenant_id",
    "created_at", "updated_at",
    "deleted_at", "deleted_by_user_id",
    "merged_into", "merged_at", "merged_by",
})


def _parse_dt(v: Any) -> datetime:
    """Tolerant ISO parse; returns epoch on failure so missing/bad
    values always lose the newest-wins comparison."""
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str) or not v.strip():
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _row_age(row: Dict[str, Any]) -> datetime:
    return _parse_dt(row.get("updated_at") or row.get("created_at"))


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict, tuple, set)):
        return len(v) == 0
    return False


def _reconcile(
    primary: Dict[str, Any],
    secondaries: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Return ``(patch_for_primary, fields_reconciled, empty_fields_filled)``.

    * ``patch_for_primary`` — the ``$set`` payload to apply to the
      primary doc. Only fields that CHANGE are included; a no-op
      reconciliation returns an empty patch.
    * ``fields_reconciled`` — {field: new_value} for conflicts
      resolved by newest-wins (primary already had a value; a
      newer secondary overwrote it).
    * ``empty_fields_filled`` — {field: filled_value} for fields
      the primary was missing and a secondary populated.
    """
    patch: Dict[str, Any] = {}
    reconciled: Dict[str, Any] = {}
    filled: Dict[str, Any] = {}
    p_age = _row_age(primary)

    # Union of every non-metadata key across primary + all secondaries.
    keys: set[str] = set()
    for d in (primary, *secondaries):
        for k in (d or {}).keys():
            if k not in _METADATA_FIELDS:
                keys.add(k)

    for k in keys:
        p_val = primary.get(k)
        if _is_empty(p_val):
            # Rule 1 — fill from first non-empty secondary in order.
            for s in secondaries:
                s_val = s.get(k)
                if not _is_empty(s_val):
                    patch[k] = s_val
                    filled[k] = s_val
                    break
            continue
        # Rule 2 — newest-wins on conflict. Only iterate secondaries
        # whose value differs from the primary's.
        winner_val = p_val
        winner_age = p_age
        overrode = False
        for s in secondaries:
            s_val = s.get(k)
            if _is_empty(s_val):
                continue
            if s_val == winner_val:
                continue
            s_age = _row_age(s)
            if s_age > winner_age:
                winner_val = s_val
                winner_age = s_age
                overrode = True
        if overrode:
            patch[k] = winner_val
            reconciled[k] = winner_val
    return patch, reconciled, filled


# ─── Related-record rewire ──────────────────────────────────────────
# Collection name → (rewire_all: bool, extra_bucket_split: fn|None).
# ``extra_bucket_split`` splits the collection's rewired count into
# named buckets (used by ``quotes``: doc_type=invoice vs estimate).
async def _rewire_related(
    tenant_id: str,
    primary_id: str,
    secondary_ids: List[str],
    dry_run: bool,
) -> Dict[str, int]:
    """Return per-bucket counts of docs whose ``customer_id`` points
    at one of ``secondary_ids`` and would be (or were) rewired to
    ``primary_id``. Bucket keys match the Phase-2 UI contract."""
    base = {
        "tenant_id": tenant_id,
        "customer_id": {"$in": list(secondary_ids or [])},
    }
    counts = {
        "jobs": 0, "invoices": 0, "payments": 0,
        "service_reports": 0, "estimates": 0, "leads": 0,
    }
    if not secondary_ids:
        return counts

    # Straightforward per-collection buckets.
    for coll_name, bucket in (
        ("jobs", "jobs"),
        ("payments", "payments"),
        ("service_reports", "service_reports"),
        ("leads", "leads"),
    ):
        n = await db[coll_name].count_documents(base)
        counts[bucket] = n
        if n and not dry_run:
            await db[coll_name].update_many(
                base, {"$set": {"customer_id": primary_id}},
            )

    # ``quotes`` — unified invoices + estimates. Split by doc_type.
    inv_q = {**base, "doc_type": "invoice"}
    est_q = {**base, "doc_type": "estimate"}
    counts["invoices"] = await db.quotes.count_documents(inv_q)
    quote_est = await db.quotes.count_documents(est_q)
    # Legacy separate estimates collection also carries the FK.
    legacy_est = await db.estimates.count_documents(base)
    counts["estimates"] = quote_est + legacy_est
    if not dry_run:
        if counts["invoices"]:
            await db.quotes.update_many(
                inv_q, {"$set": {"customer_id": primary_id}},
            )
        if quote_est:
            await db.quotes.update_many(
                est_q, {"$set": {"customer_id": primary_id}},
            )
        if legacy_est:
            await db.estimates.update_many(
                base, {"$set": {"customer_id": primary_id}},
            )
    return counts


# ─── Public API ─────────────────────────────────────────────────────
async def merge_customers(
    tenant_id: str,
    primary_id: str,
    secondary_ids: List[str],
    strategy: str = "newest_wins",
    initiated_by: str = "unknown",
    dry_run: bool = False,
    match_type: Optional[str] = None,
    confidence: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge ``secondary_ids`` into ``primary_id``. Returns::

        {
          "primary_id": "...",
          "secondary_ids": [...],
          "fields_reconciled": {...},
          "empty_fields_filled": {...},
          "related_records_rewired": {...},
          "audit_id": "..." | None,   # None in dry-run mode
          "dry_run": bool,
        }
    """
    if strategy != "newest_wins":
        raise ValueError(f"unsupported strategy: {strategy!r}")
    if not tenant_id:
        raise ValueError("tenant_id required")
    if not primary_id:
        raise ValueError("primary_id required")
    if not secondary_ids:
        raise ValueError("secondary_ids required (non-empty list)")
    if primary_id in secondary_ids:
        raise ValueError("primary_id cannot appear in secondary_ids")

    primary = await db.customers.find_one(
        {"id": primary_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not primary:
        raise LookupError(f"primary customer not found: {primary_id}")
    if primary.get("merged_into"):
        raise ValueError(
            f"primary customer is itself merged (into "
            f"{primary['merged_into']!r})"
        )

    secondaries: List[Dict[str, Any]] = []
    for sid in secondary_ids:
        srow = await db.customers.find_one(
            {"id": sid, "tenant_id": tenant_id}, {"_id": 0},
        )
        if not srow:
            raise LookupError(f"secondary customer not found: {sid}")
        if srow.get("merged_into"):
            # Idempotency guard — silently skip already-merged rows.
            continue
        secondaries.append(srow)

    if not secondaries:
        # Every requested secondary is already merged.
        return {
            "primary_id": primary_id,
            "secondary_ids": list(secondary_ids),
            "fields_reconciled": {},
            "empty_fields_filled": {},
            "related_records_rewired": {
                "jobs": 0, "invoices": 0, "payments": 0,
                "service_reports": 0, "estimates": 0, "leads": 0,
            },
            "audit_id": None,
            "dry_run": bool(dry_run),
            "no_op": True,
        }

    patch, reconciled, filled = _reconcile(primary, secondaries)
    # ``updated_at`` is a metadata field — bump it if we actually
    # patched something so downstream consumers see the merge point.
    if patch and not dry_run:
        patch["updated_at"] = now_iso()

    rewired = await _rewire_related(
        tenant_id, primary_id,
        [s["id"] for s in secondaries],
        dry_run,
    )

    audit_id: Optional[str] = None
    if not dry_run:
        if patch:
            await db.customers.update_one(
                {"id": primary_id, "tenant_id": tenant_id},
                {"$set": patch},
            )
        merged_at = now_iso()
        for s in secondaries:
            await db.customers.update_one(
                {"id": s["id"], "tenant_id": tenant_id},
                {"$set": {
                    "merged_into": primary_id,
                    "merged_at": merged_at,
                    "merged_by": initiated_by or "unknown",
                    "updated_at": merged_at,
                }},
            )
        audit_id = await write_merge_audit(
            tenant_id=tenant_id,
            primary_id=primary_id,
            secondary_ids=[s["id"] for s in secondaries],
            initiated_by=initiated_by,
            match_type=match_type,
            confidence=confidence,
            fields_reconciled=reconciled,
            empty_fields_filled=filled,
            related_records_rewired=rewired,
        )

    return {
        "primary_id": primary_id,
        "secondary_ids": [s["id"] for s in secondaries],
        "fields_reconciled": reconciled,
        "empty_fields_filled": filled,
        "related_records_rewired": rewired,
        "audit_id": audit_id,
        "dry_run": bool(dry_run),
    }
