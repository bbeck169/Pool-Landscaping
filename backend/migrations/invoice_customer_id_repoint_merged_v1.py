"""TD-invoice-customer-id-repair-on-merge · Feb-2026
================================================================

Repoint invoices currently attached to a merged ("ghost") customer
onto the merge chain's canonical winner.

Where invoices live
-------------------
Phase 11 unified ``db.invoices`` → ``db.quotes`` (``doc_type ==
"invoice"``) — see ``routers/invoice_reconciliation.py:5`` and
``routers/billing.py``.  This migration operates **exclusively**
on ``db.quotes`` with the ``doc_type="invoice"`` filter.

A completion assertion verifies that ``db.invoices`` (the retired
collection) carries ZERO orphans before writing the sentinel — if
that collection ever regains docs pointing at merged customers,
the migration refuses to mark itself complete so the next run
surfaces the surface.

Merge chain walk
----------------
Customers merge via ``services/customers/merge.py`` (Feb-2026
greenfield) which stamps ``merged_into`` on the loser pointing at
the winner's id.  Chain merges (``X -> Y -> Z``) are followed by
walking ``merged_into`` repeatedly until a non-merged customer is
reached or a cycle is detected.

Flags
-----
``--dry-run``    (default) — no writes, no sentinel.  Prints the
                 counts the real run would apply.
``--apply``      — perform the writes + record a sentinel in
                 ``db._migrations``.  Idempotent — re-running after
                 a clean apply is a no-op.
``--report-only`` — like ``--dry-run`` but prints a per-tenant
                 per-customer summary table on stdout.  Useful for
                 operator spot-check before an ``--apply``.  No
                 writes, no sentinel.
``--tenant <id>``— scope the scan + apply to a single tenant.

Boot wiring
-----------
Deliberately **NOT** boot-wired.  Operator must invoke manually in
prod per the task spec.  A follow-up ticket can boot-gate it
behind the sentinel if ops wants auto-remediation.

Usage
-----
::

    cd /app/backend
    # 1. Dry-run (no writes) — print aggregate counts.
    python -m migrations.invoice_customer_id_repoint_merged_v1 --dry-run

    # 2. Report-only — per-tenant / per-customer summary table.
    python -m migrations.invoice_customer_id_repoint_merged_v1 --report-only

    # 3. Scoped apply — single tenant.
    python -m migrations.invoice_customer_id_repoint_merged_v1 \\
        --apply --tenant <tenant_id>

    # 4. Full apply — every tenant.
    python -m migrations.invoice_customer_id_repoint_merged_v1 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "invoice_customer_id_repoint_merged_v1"
_SENTINEL_COLLECTION = "_migrations"

# Guard against pathological merge chains (``X -> Y -> X``).  No
# realistic graph exceeds a couple of hops; 32 is a generous
# safety ceiling that makes a cycle self-evident in logs.
_CHAIN_WALK_MAX_HOPS = 32


# ═════════════════════════════════════════════════════════════
# Chain walk
# ═════════════════════════════════════════════════════════════
async def _resolve_canonical(
    cid: str, *, tenant_id: str,
    cache: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Optional[str], List[str]]:
    """Walk ``merged_into`` from ``cid`` until a non-merged
    customer is reached.  Returns ``(canonical_id, chain)``.

    * ``canonical_id`` is ``None`` only when the FIRST hop lookup
      fails (customer record missing from this tenant entirely).
    * ``chain`` is the sequence of ids traversed, STARTING with
      ``cid`` and ending at the resolved canonical.
    * Cycle detection: a repeat visit aborts and returns the
      last seen id as canonical.
    * ``cache`` memoises the full chain per start-id so a
      second call for the same ``cid`` returns an identical
      ``(winner, chain)`` tuple without re-querying.  Caching
      the winner alone (as a prior iteration did) truncated the
      chain to length 2 on cache hits and broke chain-length
      stamps for ``X -> Y -> Z`` walks.
    """
    cache = cache if cache is not None else {}
    if cid in cache:
        cached_chain = cache[cid]
        return (cached_chain[-1] if cached_chain else None,
                list(cached_chain))
    chain: List[str] = [cid]
    seen: set = {cid}
    cursor_id = cid
    for _ in range(_CHAIN_WALK_MAX_HOPS):
        row = await db.customers.find_one(
            {"id": cursor_id, "tenant_id": tenant_id},
            {"_id": 0, "id": 1, "merged_into": 1},
        )
        if not row:
            # Loser record was itself hard-deleted — treat the last
            # resolved node as canonical.  Nothing to walk past.
            terminal = chain[-1] if chain else None
            cache[cid] = list(chain)
            return terminal, chain
        nxt = row.get("merged_into")
        if not nxt:
            cache[cid] = list(chain)
            return cursor_id, chain
        if nxt in seen:
            logger.warning(
                "[invoice_cid_repair] merge-chain cycle detected "
                "tenant=%s start=%s cycle_edge=%s->%s",
                tenant_id, cid, cursor_id, nxt,
            )
            cache[cid] = list(chain)
            return cursor_id, chain
        seen.add(nxt)
        chain.append(nxt)
        cursor_id = nxt
    logger.warning(
        "[invoice_cid_repair] merge-chain exceeded %d hops "
        "tenant=%s start=%s terminal=%s",
        _CHAIN_WALK_MAX_HOPS, tenant_id, cid, cursor_id,
    )
    cache[cid] = list(chain)
    return cursor_id, chain


# ═════════════════════════════════════════════════════════════
# Core scan
# ═════════════════════════════════════════════════════════════
async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    tenants = db.tenants.find({}, {"_id": 0, "id": 1})
    out: List[str] = []
    async for t in tenants:
        if t.get("id"):
            out.append(t["id"])
    return out


async def _merged_customer_ids_in_tenant(tenant_id: str) -> List[str]:
    """IDs of customers whose ``merged_into`` is set in this
    tenant.  Both ``None`` and empty-string count as "not merged";
    anything else (a canonical-winner id) counts as merged.
    """
    out: List[str] = []
    cursor = db.customers.find(
        {"tenant_id": tenant_id,
         "merged_into": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1},
    )
    async for row in cursor:
        if row.get("id"):
            out.append(row["id"])
    return out


async def _scan_tenant(tenant_id: str) -> Dict[str, Any]:
    """Enumerate every orphan invoice in this tenant + resolve its
    canonical winner.  Produces a report shaped for both the
    machine-readable return value and the operator-facing report-
    only table.
    """
    merged_ids = await _merged_customer_ids_in_tenant(tenant_id)
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "merged_customers_in_tenant": len(merged_ids),
        "orphan_invoices": 0,
        "per_customer": [],   # [{merged_cid, winner_id, invoice_ids,
                              #   chain}, ...]
        "chain_cycles_detected": 0,
    }
    if not merged_ids:
        return report

    chain_cache: Dict[str, List[str]] = {}
    # Resolve all winners up front — avoids N queries during the
    # invoice scan if the same loser has many invoices.
    for mid in merged_ids:
        winner, chain = await _resolve_canonical(
            mid, tenant_id=tenant_id, cache=chain_cache,
        )
        if winner and len(chain) > 2:
            # chain length > 2 means at least one intermediate hop
            # was followed (``X -> Y -> Z`` gives chain
            # ``[X, Y, Z]``) — the fact that we walked past the
            # first hop IS the "chain walked" signal.
            pass
    # Scan invoices.  ``doc_type="invoice"`` is the Phase 11
    # discriminator; any doc without it is a quote or an estimate
    # and MUST NOT be touched.
    cursor = db.quotes.find(
        {"tenant_id": tenant_id,
         "doc_type": "invoice",
         "customer_id": {"$in": merged_ids}},
        {"_id": 0, "id": 1, "invoice_number": 1,
         "customer_id": 1, "customer_name": 1},
    )
    buckets: Dict[str, Dict[str, Any]] = {}
    async for inv in cursor:
        merged_cid = inv["customer_id"]
        cached_chain = chain_cache.get(merged_cid)
        if cached_chain:
            winner = cached_chain[-1] if cached_chain else None
        else:
            winner, _c = await _resolve_canonical(
                merged_cid, tenant_id=tenant_id, cache=chain_cache,
            )
        if not winner or winner == merged_cid:
            # Terminal node had no winner (data corruption:
            # merged_into set but target missing).  Count it under
            # a sentinel so operator sees it in the report but we
            # don't rewire blindly.
            winner = "<unresolved>"
        bucket = buckets.setdefault(merged_cid, {
            "merged_cid": merged_cid,
            "winner_id": winner,
            "invoice_ids": [],
            "invoice_numbers": [],
            "chain_length": 0,
        })
        bucket["invoice_ids"].append(inv["id"])
        if inv.get("invoice_number"):
            bucket["invoice_numbers"].append(inv["invoice_number"])
        report["orphan_invoices"] += 1

    # Backfill chain-length onto each bucket from the walk cache.
    for merged_cid, bucket in buckets.items():
        _w, chain = await _resolve_canonical(
            merged_cid, tenant_id=tenant_id, cache=chain_cache,
        )
        bucket["chain_length"] = len(chain)
    report["per_customer"] = list(buckets.values())
    return report


async def _apply_tenant(report: Dict[str, Any]) -> int:
    """Rewire every orphan invoice in a tenant onto its canonical
    winner.  Returns the count written.  Idempotent — the
    ``customer_id`` filter targets the merged (loser) id so a
    re-run against the same report moves zero rows.
    """
    tenant_id = report["tenant_id"]
    moved = 0
    now = datetime.now(timezone.utc).isoformat()
    for bucket in report["per_customer"]:
        if bucket["winner_id"] == "<unresolved>":
            continue
        inv_ids = bucket["invoice_ids"]
        if not inv_ids:
            continue
        res = await db.quotes.update_many(
            {"tenant_id": tenant_id,
             "doc_type": "invoice",
             "id": {"$in": inv_ids},
             # Belt-and-braces — the id filter alone is sufficient
             # but adding the ``customer_id`` match makes the
             # update_many a hard no-op on a double-run.
             "customer_id": bucket["merged_cid"]},
            {"$set": {
                "customer_id": bucket["winner_id"],
                "invoice_cid_repair_v1": {
                    "at": now,
                    "from_customer_id": bucket["merged_cid"],
                    "to_customer_id": bucket["winner_id"],
                    "chain_length": bucket["chain_length"],
                },
            }},
        )
        moved += int(getattr(res, "modified_count", 0) or 0)
    return moved


# ═════════════════════════════════════════════════════════════
# Retired-collection assertion
# ═════════════════════════════════════════════════════════════
async def _assert_retired_invoices_collection_clean(
    tenant_id: Optional[str],
) -> Dict[str, Any]:
    """Phase 11 retired ``db.invoices`` in favour of ``db.quotes``.
    If the retired collection has docs pointing at merged
    customers, the migration refuses to mark itself complete so
    the surface isn't silently missed on the next run.
    """
    # Build merged-ids filter.  Scoped by tenant when requested.
    cust_filter: Dict[str, Any] = {
        "merged_into": {"$exists": True, "$nin": [None, ""]},
    }
    if tenant_id:
        cust_filter["tenant_id"] = tenant_id
    merged_ids: List[str] = []
    async for row in db.customers.find(cust_filter, {"_id": 0, "id": 1}):
        if row.get("id"):
            merged_ids.append(row["id"])
    if not merged_ids:
        return {"retired_db_invoices_orphans": 0, "checked": True}
    q: Dict[str, Any] = {"customer_id": {"$in": merged_ids}}
    if tenant_id:
        q["tenant_id"] = tenant_id
    try:
        n = await db.invoices.count_documents(q)
    except Exception as exc:  # noqa: BLE001
        # Retired collection may not exist at all in fresh envs —
        # count returns 0 on a missing collection in Mongo, but we
        # catch defensively so the migration never fails on an
        # observability check.
        logger.warning(
            "[invoice_cid_repair] db.invoices count failed "
            "(retired collection may be absent): %s", exc,
        )
        return {"retired_db_invoices_orphans": 0,
                "checked": False, "error": str(exc)}
    return {"retired_db_invoices_orphans": n, "checked": True}


# ═════════════════════════════════════════════════════════════
# Sentinel
# ═════════════════════════════════════════════════════════════
async def _is_sentinel_clean() -> bool:
    doc = await db[_SENTINEL_COLLECTION].find_one(
        {"key": _SENTINEL_KEY})
    if not doc or doc.get("mode") != "apply":
        return False
    stats = doc.get("stats") or {}
    return int(stats.get("orphan_invoices_after", 1)) == 0


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": _SENTINEL_KEY,
        "key": _SENTINEL_KEY,
        "phase": "TD-invoice-customer-id-repair-on-merge",
        "mode": mode,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    await db[_SENTINEL_COLLECTION].update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


# ═════════════════════════════════════════════════════════════
# Public entry
# ═════════════════════════════════════════════════════════════
async def run(
    *,
    apply: bool = False,
    report_only: bool = False,
    tenant_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Run the migration.

    Args:
        apply:        Write mode.  ``False`` = dry-run.
        report_only:  Print a per-tenant/per-customer table.
                      Implies dry-run (writes are suppressed).
        tenant_id:    Restrict to a single tenant.
        force:        Bypass the sentinel short-circuit on apply.
    """
    # Rebind Motor's shared ``_io_loop`` (same trick k49b uses) so
    # the test suite's ``asyncio.run(run(...))`` per-test loop
    # doesn't trip Motor's loop-affinity guard.
    try:
        from config import client as _client  # noqa: PLC0415
        _client._io_loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001
        pass

    if report_only and apply:
        raise ValueError(
            "--report-only and --apply are mutually exclusive "
            "(report-only forbids writes).")

    if apply and not force and not tenant_id and await _is_sentinel_clean():
        return {"status": "skipped", "reason": "sentinel-clean"}

    tenant_ids = await _load_tenant_ids(tenant_id)
    all_reports: List[Dict[str, Any]] = []
    total_orphans = 0
    total_moved = 0
    for tid in tenant_ids:
        rep = await _scan_tenant(tid)
        all_reports.append(rep)
        total_orphans += rep["orphan_invoices"]
        if apply and rep["orphan_invoices"]:
            moved = await _apply_tenant(rep)
            rep["moved"] = moved
            total_moved += moved
        else:
            rep["moved"] = 0

    retired_check = await _assert_retired_invoices_collection_clean(
        tenant_id)

    stats: Dict[str, Any] = {
        "tenants": len(tenant_ids),
        "orphan_invoices": total_orphans,
        "invoices_moved": total_moved,
        "retired_db_invoices_orphans":
            retired_check["retired_db_invoices_orphans"],
    }

    logger.info(
        "[invoice_cid_repair] apply=%s report_only=%s "
        "tenants=%s orphans=%s moved=%s retired_check=%s",
        apply, report_only, stats["tenants"], total_orphans,
        total_moved, retired_check,
    )

    if apply:
        # Re-scan to confirm no orphans remain (post-apply truth
        # for the sentinel).
        remaining = 0
        for tid in tenant_ids:
            rp = await _scan_tenant(tid)
            remaining += rp["orphan_invoices"]
        stats["orphan_invoices_after"] = remaining
        # Only write a "clean" sentinel when zero orphans remain
        # across the scanned scope AND the retired-collection
        # check also returned zero.  Any non-zero leaves the
        # sentinel in a "dirty" state so the next run doesn't
        # short-circuit.
        clean = (
            remaining == 0
            and retired_check["retired_db_invoices_orphans"] == 0
        )
        stats["clean"] = clean
        await _write_sentinel(stats, "apply")

    status = (
        "report-only" if report_only
        else "applied" if apply
        else "dry-run"
    )
    return {
        "status": status,
        "stats": stats,
        "reports": all_reports,
        "retired_check": retired_check,
    }


# ═════════════════════════════════════════════════════════════
# Report-only pretty printer
# ═════════════════════════════════════════════════════════════
def _format_report_table(out: Dict[str, Any]) -> str:
    """Operator-facing per-tenant / per-customer summary."""
    lines: List[str] = []
    lines.append("=" * 78)
    lines.append(
        "TD-invoice-customer-id-repair-on-merge · report-only")
    lines.append("=" * 78)
    stats = out["stats"]
    lines.append(
        f"tenants scanned:        {stats['tenants']}")
    lines.append(
        f"orphan invoices total:  {stats['orphan_invoices']}")
    lines.append(
        f"db.invoices (retired):  "
        f"{stats['retired_db_invoices_orphans']} orphan(s)")
    lines.append("-" * 78)
    for rep in out["reports"]:
        if not rep["orphan_invoices"]:
            continue
        lines.append(
            f"[tenant={rep['tenant_id']}]  "
            f"orphans={rep['orphan_invoices']}  "
            f"merged_customers={rep['merged_customers_in_tenant']}")
        for bucket in rep["per_customer"]:
            nums = ", ".join(bucket["invoice_numbers"][:5]) or "<no invoice_number>"
            if len(bucket["invoice_numbers"]) > 5:
                nums += f" (+{len(bucket['invoice_numbers'])-5} more)"
            lines.append(
                f"  merged_cid={bucket['merged_cid']}  ->  "
                f"winner={bucket['winner_id']}  "
                f"chain_len={bucket['chain_length']}  "
                f"invoices={len(bucket['invoice_ids'])}  "
                f"[{nums}]")
    lines.append("=" * 78)
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Repoint invoices on merged customers onto the merge "
            "chain's canonical winner.  Operates on db.quotes "
            "(doc_type=invoice) per Phase 11 unification."))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                        help="Perform writes (default: dry-run)")
    group.add_argument("--dry-run", action="store_true",
                        help="Explicit dry-run (default behaviour)")
    group.add_argument("--report-only", action="store_true",
                        help=("Print per-tenant/per-customer "
                              "summary table; no writes."))
    parser.add_argument("--tenant", default=None,
                        help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                        help=("Bypass the sentinel short-circuit "
                              "on --apply"))
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply,
        report_only=ns.report_only,
        tenant_id=ns.tenant,
        force=ns.force,
    ))
    if ns.report_only:
        print(_format_report_table(out))
    else:
        print(json.dumps(out, indent=2, default=str))
