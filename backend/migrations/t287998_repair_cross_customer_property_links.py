"""Ticket 287998 — one-shot, idempotent repair of cross-customer property links.

Problem
-------
``jobs`` and ``recurring_job_templates`` exist whose ``property_id`` points at
ANOTHER customer's property (e.g. 16 customers linked to one customer's
"22442 N 80th Lane" property).  The stored ``jobs.address`` snapshot was copied
from that foreign property, so the schedule shows one street on many cards and
the Navigate button routes there.  The read-path guards (``/api/jobs``
address correction, coord ladder) mask it on display; this migration fixes the
stored data.

Repair rule (per record whose linked property's ``customer_id`` differs from the
record's ``customer_id``)
---------------------------------------------------------------------------
1. SKIP when the two customers are the same person after a merge
   (``merged_into`` chain) — ~260 legacy jobs point at the merged-away
   duplicate's property; that is NOT a cross-customer link.
2. SKIP when the record's own customer doc is missing.
3. Repoint ``property_id`` to the customer's OWN first active, non-deleted
   property that has a usable address (``sort_order`` asc).
4. If the customer has no such property: ``$unset property_id`` (the resolver
   then falls back to the customer's own address fields).
5. Jobs only: rewrite ``address`` ONLY when the stored text still matches the
   foreign property's address (i.e. it is the copied snapshot).  A job whose
   address text is something else is left alone (``address_kept_custom``).
   ``recurring_job_templates`` carry no address field.

Safety
------
* **Idempotent:** a repaired record no longer matches the mismatch test, so a
  second run finds zero rows.  The write is conditional on the ``property_id``
  still being the one that was planned (safe under two pods booting at once).
* **Reversible:** the untouched original doc is stored once in
  ``repair_287998_backup`` (upsert on ``(collection, doc_id)`` with
  ``$setOnInsert`` — a rerun never overwrites the first backup).
* **Marker:** ``migrations_applied[name=MIGRATION_NAME]`` is stamped only after
  an execute run finishes with zero errors AND a verification scan finds nothing
  left to repair; otherwise the next boot simply retries.
* **Never blocks boot:** bounded by ``STARTUP_TIMEOUT_S``; the caller
  (``_run_structural_migration``) swallows exceptions.  Kill switch:
  ``T287998_DISABLE=1``.

CLI (dry-run by default)::

    python -m migrations.t287998_repair_cross_customer_property_links
    python -m migrations.t287998_repair_cross_customer_property_links --execute [--force]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from config import db, logger
from services.address_resolver import format_property_address

MIGRATION_NAME = "t287998_repair_cross_customer_property_links"
MARKER_COLLECTION = "migrations_applied"
BACKUP_COLLECTION = "repair_287998_backup"

# Ships ON: the operator asked for the repair to apply on the redeploy.
STARTUP_EXECUTE_MODE = True
STARTUP_TIMEOUT_S = 120

# Templates first so no new bad jobs are materialised from them mid-run.
COLLECTIONS = ("recurring_job_templates", "jobs")
_CHUNK = 500
_MERGE_HOPS = 5


# --------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB)
# --------------------------------------------------------------------------
def _norm(text: Any) -> str:
    """Case/punctuation-insensitive form used to compare address strings."""
    return re.sub(r"[^a-z0-9]", "", text.lower()) if isinstance(text, str) else ""


def _root_customer(cid: Optional[str], custs: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    """Follow the ``merged_into`` chain (bounded) to the surviving customer."""
    seen = set()
    for _ in range(_MERGE_HOPS):
        if not cid or cid in seen:
            break
        seen.add(cid)
        nxt = (custs.get(cid) or {}).get("merged_into")
        if not nxt:
            break
        cid = nxt
    return cid


def same_customer(a: Optional[str], b: Optional[str], custs: Mapping[str, Mapping[str, Any]]) -> bool:
    return bool(a and b) and (a == b or _root_customer(a, custs) == _root_customer(b, custs))


def _customer_fallback_address(cust: Mapping[str, Any]) -> str:
    for key in ("service_address", "address", "billing_address"):
        val = cust.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def plan_fix(
    coll: str,
    doc: Mapping[str, Any],
    prop: Optional[Mapping[str, Any]],
    custs: Mapping[str, Mapping[str, Any]],
    own_prop: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Decide what to do with one record.

    Returns ``{"action": <name>, "update": <mongo update or None>}`` where
    ``action`` is one of ``ok`` | ``skipped_merged`` | ``skipped_no_customer`` |
    ``repoint`` | ``clear``.  Pure — no I/O.
    """
    cid, pid = doc.get("customer_id"), doc.get("property_id")
    owner = (prop or {}).get("customer_id")
    if not pid or not cid or not prop or not owner or owner == cid:
        return {"action": "ok", "update": None}
    if same_customer(owner, cid, custs):
        return {"action": "skipped_merged", "update": None}
    cust = custs.get(cid)
    if not cust:
        return {"action": "skipped_no_customer", "update": None}

    foreign_norm = _norm(format_property_address(prop))
    cur_norm = _norm(doc.get("address"))
    # Rewrite the text only when it is still the copied foreign snapshot (or empty).
    is_snapshot = coll == "jobs" and (not cur_norm or cur_norm == foreign_norm)

    own_addr = format_property_address(own_prop) if own_prop else ""
    if own_prop and own_addr:
        upd: Dict[str, Any] = {"$set": {"property_id": own_prop["id"]}}
        if is_snapshot:
            upd["$set"]["address"] = own_addr
        return {"action": "repoint", "update": upd}

    upd = {"$unset": {"property_id": ""}}
    fallback = _customer_fallback_address(cust)
    if is_snapshot and fallback:
        upd["$set"] = {"address": fallback}
    return {"action": "clear", "update": upd}


# --------------------------------------------------------------------------
# DB plumbing
# --------------------------------------------------------------------------
async def _marker_present() -> bool:
    return bool(await db[MARKER_COLLECTION].find_one({"name": MIGRATION_NAME}))


async def _stamp_marker(summary: Dict[str, Any]) -> None:
    await db[MARKER_COLLECTION].update_one(
        {"name": MIGRATION_NAME},
        {"$set": {"name": MIGRATION_NAME, "applied_at": datetime.now(timezone.utc).isoformat(),
                  "summary": {k: v for k, v in summary.items() if k != "duration_s"}}},
        upsert=True,
    )


async def _load_customers(ids: set) -> Dict[str, Dict[str, Any]]:
    """Load customers + follow ``merged_into`` targets (bounded hops)."""
    out: Dict[str, Dict[str, Any]] = {}
    todo = {i for i in ids if i}
    for _ in range(_MERGE_HOPS + 1):
        todo -= set(out)
        if not todo:
            break
        rows = db.customers.find(
            {"id": {"$in": list(todo)}},
            {"_id": 0, "id": 1, "merged_into": 1, "service_address": 1,
             "address": 1, "billing_address": 1},
        )
        got = {r["id"]: r async for r in rows}
        out.update(got)
        todo = {r.get("merged_into") for r in got.values() if r.get("merged_into")}
    return out


async def _own_properties(cids: set) -> Dict[str, Dict[str, Any]]:
    """First active, non-deleted, addressable property per customer."""
    rows = [
        r async for r in db.properties.find(
            {"customer_id": {"$in": list(cids)}, "active": {"$ne": False}, "deleted_at": None},
            {"_id": 0, "id": 1, "customer_id": 1, "label": 1, "address": 1,
             "sort_order": 1, "created_at": 1},
        )
    ]
    rows.sort(key=lambda r: (r.get("sort_order") or 0, r.get("created_at") or ""))
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if format_property_address(r):
            out.setdefault(r["customer_id"], r)
    return out


async def _process_chunk(coll: str, chunk: List[dict], execute: bool, stats: Dict[str, int]) -> None:
    stats["scanned"] += len(chunk)
    pids = {d["property_id"] for d in chunk}
    props = {
        p["id"]: p async for p in db.properties.find(
            {"id": {"$in": list(pids)}},
            {"_id": 0, "id": 1, "customer_id": 1, "address": 1},
        )
    }
    cand = [
        d for d in chunk
        if props.get(d["property_id"], {}).get("customer_id")
        and d.get("customer_id") and props[d["property_id"]]["customer_id"] != d["customer_id"]
    ]
    if not cand:
        return
    involved = {d["customer_id"] for d in cand} | {props[d["property_id"]]["customer_id"] for d in cand}
    custs = await _load_customers(involved)
    own = await _own_properties({d["customer_id"] for d in cand})
    now_iso = datetime.now(timezone.utc).isoformat()
    for d in cand:
        plan = plan_fix(coll, d, props[d["property_id"]], custs, own.get(d["customer_id"]))
        action = plan["action"]
        if action in ("skipped_merged", "skipped_no_customer"):
            stats[action] += 1
            continue
        if action == "ok":
            continue
        stats["mismatched"] += 1
        upd = plan["update"]
        addr_changed = "address" in (upd.get("$set") or {})
        if coll == "jobs" and not addr_changed:
            stats["address_kept_custom"] += 1
        if not execute:
            stats["would_repoint" if action == "repoint" else "would_clear"] += 1
            continue
        full = await db[coll].find_one({"_id": d["_id"]})
        if not full or full.get("property_id") != d["property_id"]:
            continue  # changed under us — next run re-evaluates
        await db[BACKUP_COLLECTION].update_one(
            {"collection": coll, "doc_id": full.get("id")},
            {"$setOnInsert": {"migration": MIGRATION_NAME, "doc": full, "planned_update": upd,
                              "backed_up_at": now_iso}},
            upsert=True,
        )
        upd.setdefault("$set", {})["updated_at"] = now_iso  # so mobile delta-sync refreshes
        res = await db[coll].update_one({"_id": d["_id"], "property_id": d["property_id"]}, upd)
        if res.modified_count:
            stats["repointed" if action == "repoint" else "cleared"] += 1
            if addr_changed:
                stats["address_rewritten"] += 1


async def _scan(execute: bool, tenant_id: Optional[str]) -> Dict[str, int]:
    keys = ("scanned", "mismatched", "repointed", "cleared", "address_rewritten", "address_kept_custom",
            "would_repoint", "would_clear", "skipped_merged", "skipped_no_customer", "errors")
    stats = {k: 0 for k in keys}
    for coll in COLLECTIONS:
        q: Dict[str, Any] = {"property_id": {"$nin": [None, ""]}}
        if coll == "jobs":
            q["deleted_at"] = None
        if tenant_id:
            q["tenant_id"] = tenant_id
        chunk: List[dict] = []
        cursor = db[coll].find(q, {"_id": 1, "id": 1, "customer_id": 1, "property_id": 1, "address": 1})
        try:
            async for d in cursor:
                chunk.append(d)
                if len(chunk) >= _CHUNK:
                    await _process_chunk(coll, chunk, execute, stats)
                    chunk = []
            if chunk:
                await _process_chunk(coll, chunk, execute, stats)
        except Exception:  # noqa: BLE001 — count it, keep the marker unstamped, retry next boot
            stats["errors"] += 1
            logger.exception("[%s] %s pass failed", MIGRATION_NAME, coll)
    return stats


async def run(execute: bool = False, tenant_id: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    base = {"dry_run": not execute, "skipped_by_marker": False, "disabled": False, "tenant_filter": tenant_id}
    if os.environ.get("T287998_DISABLE") == "1":
        logger.warning("[%s] disabled via T287998_DISABLE=1", MIGRATION_NAME)
        return {**base, "disabled": True}
    if execute and not force and not tenant_id and await _marker_present():
        logger.info("[%s] marker present — skipping", MIGRATION_NAME)
        return {**base, "skipped_by_marker": True}

    stats = await _scan(execute, tenant_id)
    summary: Dict[str, Any] = {**base, **stats}
    if execute and not tenant_id and stats["errors"] == 0:
        remaining = (await _scan(False, None))["mismatched"]  # verification pass (dry)
        summary["remaining_after"] = remaining
        if remaining == 0:
            await _stamp_marker(summary)
            summary["marker_stamped"] = True
    summary["duration_s"] = round(time.time() - t0, 2)
    logger.info("[%s] %s", MIGRATION_NAME, summary)
    return summary


async def run_bounded(execute: bool) -> Dict[str, Any]:
    """Boot entrypoint: never holds startup longer than ``STARTUP_TIMEOUT_S``."""
    try:
        return await asyncio.wait_for(run(execute=execute), timeout=STARTUP_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("[%s] timed out after %ss — marker not stamped, will retry next boot",
                       MIGRATION_NAME, STARTUP_TIMEOUT_S)
        return {"dry_run": not execute, "timed_out": True}


def _cli_main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--execute", action="store_true", help="apply (default is dry-run)")
    ap.add_argument("--tenant", help="limit to one tenant (bypasses the marker)")
    ap.add_argument("--force", action="store_true", help="bypass the marker")
    a = ap.parse_args()
    print(asyncio.run(run(execute=a.execute, tenant_id=a.tenant, force=a.force)))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
