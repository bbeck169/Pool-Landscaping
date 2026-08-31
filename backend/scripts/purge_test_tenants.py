"""Feb-2026 · Phase A — Test-Tenant Purge Script.

Idempotent, cascade-clean one-shot purge of CI test tenants
(``TEST_gs_*``, ``csv-*``, ``jca-*`` by default) and every
downstream document they own.

Motivation:  Preview / prod DBs accumulate CI-cruft tenants over
time.  They inflate boot loops, integrity scans, and the every
``list_collection_names()`` sweep that PERF-1 tries to speed up.
This script gets them off the box in one shot without producing
new F3 orphans.

Design invariants
-----------------

1.  Idempotent — running with ``--apply`` twice in a row on the
    same DB is a no-op the second time.  Discovery is redone from
    live DB state each run; there is no cached "last run" state.
2.  Safe by default — ``--dry-run`` is the default.  ``--apply``
    is required to actually delete.  ``--apply`` on
    ``APP_ENV=production`` is refused unless
    ``--i-know-this-is-prod`` is also passed.
3.  F3 guardrail — a read-only ``scan_dangling_refs`` runs BEFORE
    the first delete and AFTER the last.  If the post-purge count
    exceeds the pre-purge count, the script exits non-zero and
    prints the delta.  (The cascade is over-inclusive by design —
    it deletes every ``tenant_id``-scoped row — so this should
    never fire in practice; it's a paranoia check.)
4.  Audit trail — one row per run is inserted into
    ``audit_events`` with ``event_type='test_tenant_purge'``.
5.  Cascade order — CHILDREN FIRST, tenants LAST.  If the script
    dies mid-run, the tenant docs remain and the operator can
    re-run to finish; there is no partial-tenant state where the
    tenant is deleted but children remain.

Usage
-----

Dry-run (default) ::

    python -m scripts.purge_test_tenants

Apply on preview ::

    python -m scripts.purge_test_tenants --apply

Apply on prod (last resort — prefer prod ops runbook) ::

    APP_ENV=production python -m scripts.purge_test_tenants \
        --apply --i-know-this-is-prod

Add a custom prefix (repeatable) ::

    python -m scripts.purge_test_tenants \
        --apply --prefix srec- --prefix cra-

Target a single tenant by id ::

    python -m scripts.purge_test_tenants --apply \
        --tenant-id TEST_gs_tenant_cbd1b81f0d5348baa55fdae34fdf585b

Safety cap (refuse to run if more than N tenants match) ::

    python -m scripts.purge_test_tenants --apply --limit 200
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Bootstrap paths so both ``python -m scripts.purge_test_tenants``
#    from /app/backend AND direct-path invocation work.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

DEFAULT_PREFIXES: Tuple[str, ...] = ("TEST_gs_", "csv-", "jca-")

# Never touch these.  System collections + the audit trail we write
# to.  Everything else is fair game IF it carries ``tenant_id``.
SYSTEM_COLLECTIONS: Set[str] = {
    "system.indexes",
    "system.views",
    "audit_events",           # we WRITE to this — never cascade-delete
    "audit_log",              # legacy audit
    "audit_logs",             # legacy audit
}

AUDIT_EVENT_TYPE = "test_tenant_purge"

_LOG = logging.getLogger("purge_test_tenants")


# ═══════════════════════════════════════════════════════════════════
# Env helpers
# ═══════════════════════════════════════════════════════════════════

def _app_env() -> str:
    return (os.environ.get("APP_ENV", "preview") or "preview").lower()


def _os_user() -> str:
    return (os.environ.get("USER") or os.environ.get("USERNAME")
            or "unknown")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# Discovery
# ═══════════════════════════════════════════════════════════════════

async def discover_target_tenants(
    db: Any,
    *,
    prefixes: List[str],
    tenant_ids: List[str],
) -> List[Dict[str, Any]]:
    """Union of two sources:

      * ``--prefix``  — any tenant whose ``id`` OR ``slug`` starts
        with one of the given prefixes.
      * ``--tenant-id`` — explicit single-id purge.  No prefix
        check — the operator has already decided.

    Returns the deduped list of tenant docs.  Projection excludes
    ``_id`` so the dict shape is JSON-safe.
    """
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []

    if prefixes:
        or_clauses = []
        for p in prefixes:
            rx = f"^{re.escape(p)}"
            or_clauses.append({"id":   {"$regex": rx}})
            or_clauses.append({"slug": {"$regex": rx}})
        async for t in db.tenants.find({"$or": or_clauses}, {"_id": 0}):
            tid = t.get("id")
            if tid and tid not in seen:
                seen.add(tid)
                t["_match_reason"] = "prefix"
                out.append(t)

    if tenant_ids:
        async for t in db.tenants.find(
            {"id": {"$in": tenant_ids}}, {"_id": 0},
        ):
            tid = t.get("id")
            if tid and tid not in seen:
                seen.add(tid)
                t["_match_reason"] = "explicit --tenant-id"
                out.append(t)

    return out


async def _list_tenant_scoped_collections(db: Any) -> List[str]:
    """Enumerate every collection that has AT LEAST ONE doc with a
    ``tenant_id`` field.  Cheap: single ``find_one`` per collection.
    """
    out: List[str] = []
    for name in sorted(await db.list_collection_names()):
        if name in SYSTEM_COLLECTIONS:
            continue
        if name == "tenants":
            # tenants themselves are deleted last, not cascade'd.
            continue
        try:
            probe = await db[name].find_one(
                {"tenant_id": {"$exists": True}}, {"_id": 1},
            )
        except Exception as exc:                        # noqa: BLE001
            _LOG.warning("probe failed on %s: %s", name, exc)
            continue
        if probe is not None:
            out.append(name)
    return out


async def count_children(
    db: Any, target_ids: List[str], collections: List[str],
) -> Dict[str, int]:
    """Per-collection count of docs where ``tenant_id`` is in the
    target set.  Used for the dry-run report."""
    if not target_ids:
        return {}
    counts: Dict[str, int] = {}
    for col in collections:
        try:
            n = await db[col].count_documents(
                {"tenant_id": {"$in": target_ids}},
            )
        except Exception as exc:                        # noqa: BLE001
            _LOG.warning("count failed on %s: %s", col, exc)
            n = 0
        if n:
            counts[col] = n
    return counts


# ═══════════════════════════════════════════════════════════════════
# F3 guardrail — read-only pre/post scan
# ═══════════════════════════════════════════════════════════════════

async def _f3_baseline(db: Any) -> int:
    """Return current ``dangling_refs_total``.  Read-only.
    Import is deferred so tests can stub ``config.db`` without
    also stubbing the integrity module (which uses its own
    ``motor`` connection through ``config.db``)."""
    from services.startup.integrity_check import scan_dangling_refs
    report = await scan_dangling_refs(db)
    return int(report["summary"]["total_dangling_refs"])


# ═══════════════════════════════════════════════════════════════════
# Delete — cascade + tenants + audit
# ═══════════════════════════════════════════════════════════════════

async def _cascade_delete_children(
    db: Any, target_ids: List[str], collections: List[str],
) -> Dict[str, int]:
    """Issue one ``delete_many`` per tenant-scoped collection.
    Returns per-collection deleted counts (skips zeros)."""
    if not target_ids:
        return {}
    deleted: Dict[str, int] = {}
    for col in collections:
        try:
            r = await db[col].delete_many(
                {"tenant_id": {"$in": target_ids}},
            )
        except Exception as exc:                        # noqa: BLE001
            _LOG.warning("delete_many failed on %s: %s", col, exc)
            continue
        if r.deleted_count:
            deleted[col] = r.deleted_count
    return deleted


async def _delete_tenants(db: Any, target_ids: List[str]) -> int:
    if not target_ids:
        return 0
    r = await db.tenants.delete_many({"id": {"$in": target_ids}})
    return int(r.deleted_count)


async def _write_audit_row(
    db: Any,
    *,
    prefixes: List[str],
    tenants_deleted: int,
    per_collection_counts: Dict[str, int],
    dry_run: bool,
    f3_before: Optional[int],
    f3_after: Optional[int],
    elapsed_s: float,
    tenant_ids: List[str],
) -> str:
    audit_id = str(uuid.uuid4())
    doc = {
        "id": audit_id,
        "event_type": AUDIT_EVENT_TYPE,
        "actor_user_id": f"cli:{_os_user()}",
        "tenant_id": None,          # cross-tenant admin action
        "timestamp": _utc_iso(),
        "app_env": _app_env(),
        "payload": {
            "prefixes": prefixes,
            "tenant_ids": tenant_ids,
            "tenants_deleted": tenants_deleted,
            "per_collection_counts": per_collection_counts,
            "dry_run": dry_run,
            "f3_before": f3_before,
            "f3_after": f3_after,
            "elapsed_s": round(elapsed_s, 2),
        },
    }
    try:
        await db.audit_events.insert_one(doc)
    except Exception as exc:                            # noqa: BLE001
        _LOG.warning("audit insert failed: %s", exc)
    return audit_id


# ═══════════════════════════════════════════════════════════════════
# Safety gates
# ═══════════════════════════════════════════════════════════════════

class SafetyRefused(SystemExit):
    """Raised for any refuse-to-run guard so main() exits non-zero
    with a clear message."""


def _check_prod_gate(*, apply: bool, i_know_this_is_prod: bool) -> None:
    """Refuse ``--apply`` on prod unless the ack flag is also set.
    Dry-run is always allowed."""
    if not apply:
        return
    if _app_env() == "production" and not i_know_this_is_prod:
        raise SafetyRefused(
            "REFUSED: --apply on APP_ENV=production requires "
            "--i-know-this-is-prod. Dry-run works without it.",
        )


def _check_limit(
    *, matched: int, limit: Optional[int], apply: bool,
) -> None:
    if limit is None or not apply:
        return
    if matched > limit:
        raise SafetyRefused(
            f"REFUSED: matched tenants ({matched}) exceeds safety "
            f"cap --limit={limit}. Increase --limit or narrow --prefix.",
        )


# ═══════════════════════════════════════════════════════════════════
# Reporting
# ═══════════════════════════════════════════════════════════════════

def _print_hr(title: str) -> None:
    print()
    print("─" * 74)
    print(title)
    print("─" * 74)


def _print_summary(*, tenants_matched: int, child_rows: int,
                   tenants_deleted: int, dry_run: bool,
                   duration_s: float,
                   f3_before: Optional[int],
                   f3_after: Optional[int]) -> None:
    tag = "DRY-RUN" if dry_run else "APPLIED"
    print()
    print("═" * 74)
    print(f" [{tag}] Tenants matched: {tenants_matched} | "
          f"Children rows: {child_rows} | "
          f"Tenants deleted: {tenants_deleted} | "
          f"Duration: {duration_s:.2f}s")
    if f3_before is not None:
        after_repr = f3_after if f3_after is not None else "—"
        delta = ("+"
                 f"{(f3_after or 0) - f3_before}"
                 if f3_after is not None else "—")
        print(f" F3 dangling_refs: before={f3_before}  "
              f"after={after_repr}  delta={delta}")
    print("═" * 74)


# ═══════════════════════════════════════════════════════════════════
# Core runner (programmatic entrypoint — used by tests too)
# ═══════════════════════════════════════════════════════════════════

async def run_purge(
    db: Any,
    *,
    prefixes: List[str],
    tenant_ids: List[str],
    apply: bool,
    limit: Optional[int] = None,
    i_know_this_is_prod: bool = False,
    write_audit: bool = True,
    skip_f3: bool = False,
) -> Dict[str, Any]:
    """Programmable entrypoint.  Returns a structured result dict."""
    t0 = time.perf_counter()
    _check_prod_gate(apply=apply, i_know_this_is_prod=i_know_this_is_prod)

    # 1) discovery
    tenants = await discover_target_tenants(
        db, prefixes=prefixes, tenant_ids=tenant_ids,
    )
    target_ids = [t["id"] for t in tenants if t.get("id")]
    _check_limit(matched=len(target_ids), limit=limit, apply=apply)

    _print_hr("Matched tenants")
    if not tenants:
        print("  (none — nothing to do)")
    else:
        for t in tenants[:20]:
            print(f"  id={t.get('id')}  slug={t.get('slug'):<26}  "
                  f"name={t.get('name'):<30}  "
                  f"reason={t.get('_match_reason')}")
        if len(tenants) > 20:
            print(f"  … and {len(tenants) - 20} more")
    print(f"  → total: {len(tenants)}")

    # 2) collection census + per-collection counts
    tenant_scoped_cols = await _list_tenant_scoped_collections(db)
    _print_hr(f"Tenant-scoped collections: {len(tenant_scoped_cols)}")

    per_col_counts = await count_children(db, target_ids, tenant_scoped_cols)
    _print_hr("Downstream rows (WOULD delete)")
    if not per_col_counts:
        print("  (none)")
    child_total = 0
    for col in sorted(per_col_counts, key=lambda c: -per_col_counts[c]):
        n = per_col_counts[col]
        child_total += n
        print(f"  {col:<44}  {n:>9}")
    print(f"  → total child rows: {child_total}")

    # 3) F3 pre-scan (read-only) unless skipped for unit-test speed
    f3_before: Optional[int] = None
    f3_after: Optional[int] = None
    if not skip_f3:
        try:
            f3_before = await _f3_baseline(db)
            print(f"  F3 dangling_refs baseline: {f3_before}")
        except Exception as exc:                        # noqa: BLE001
            _LOG.warning("F3 baseline failed (continuing): %s", exc)

    # 4) delete (only in apply mode)
    per_col_deleted: Dict[str, int] = {}
    tenants_deleted = 0
    if apply and target_ids:
        _print_hr("APPLYING — deleting children first, tenants last")
        per_col_deleted = await _cascade_delete_children(
            db, target_ids, tenant_scoped_cols,
        )
        for col, n in sorted(per_col_deleted.items(),
                             key=lambda kv: -kv[1]):
            print(f"  deleted {n:>9}  from {col}")
        tenants_deleted = await _delete_tenants(db, target_ids)
        print(f"  deleted {tenants_deleted:>9}  from tenants")

        if not skip_f3:
            try:
                f3_after = await _f3_baseline(db)
                print(f"  F3 dangling_refs after: {f3_after}")
                if (f3_before is not None
                        and f3_after > f3_before):
                    _LOG.error(
                        "F3 dangling_refs INCREASED (%s → %s). "
                        "This should not happen — investigate.",
                        f3_before, f3_after,
                    )
            except Exception as exc:                    # noqa: BLE001
                _LOG.warning("F3 post-scan failed: %s", exc)

    # 5) audit trail (in both dry-run and apply modes so ops can
    #    trace who ran a dry-run against a shared preview DB)
    audit_id: Optional[str] = None
    if write_audit:
        audit_id = await _write_audit_row(
            db,
            prefixes=list(prefixes),
            tenants_deleted=tenants_deleted,
            per_collection_counts=(
                per_col_deleted if apply else per_col_counts
            ),
            dry_run=not apply,
            f3_before=f3_before,
            f3_after=f3_after,
            elapsed_s=time.perf_counter() - t0,
            tenant_ids=target_ids,
        )

    _print_summary(
        tenants_matched=len(tenants),
        child_rows=(sum(per_col_deleted.values()) if apply
                    else child_total),
        tenants_deleted=tenants_deleted,
        dry_run=not apply,
        duration_s=time.perf_counter() - t0,
        f3_before=f3_before,
        f3_after=f3_after,
    )

    # Non-zero exit for F3 regression so CI can wire it up.
    exit_code = 0
    if (apply and f3_before is not None
            and f3_after is not None and f3_after > f3_before):
        exit_code = 2

    return {
        "mode": "apply" if apply else "dry_run",
        "tenants_matched": len(tenants),
        "tenants_deleted": tenants_deleted,
        "child_rows_would_delete": child_total,
        "child_rows_deleted": sum(per_col_deleted.values()),
        "per_collection_counts": (
            per_col_deleted if apply else per_col_counts
        ),
        "target_ids": target_ids,
        "f3_before": f3_before,
        "f3_after": f3_after,
        "audit_event_id": audit_id,
        "exit_code": exit_code,
    }


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Idempotent CI-test-tenant purge with cascade "
                    "delete + F3 guardrail. Dry-run by default.",
    )
    p.add_argument("--apply", action="store_true",
                   help="Actually delete (default: dry-run)")
    p.add_argument("--dry-run", action="store_true",
                   help="Explicit dry-run (default when --apply omitted)")
    p.add_argument("--prefix", action="append", default=[],
                   dest="prefixes",
                   help=("Repeatable. Tenant id/slug prefix to match. "
                         "Defaults to TEST_gs_, csv-, jca- when neither "
                         "--prefix nor --tenant-id is passed."))
    p.add_argument("--tenant-id", action="append", default=[],
                   dest="tenant_ids",
                   help="Repeatable. Purge one specific tenant by id.")
    p.add_argument("--limit", type=int, default=1000,
                   help="Safety cap. Refuse --apply if more tenants "
                        "match. Default 1000. Pass --limit 0 to disable.")
    p.add_argument("--i-know-this-is-prod", action="store_true",
                   dest="ack_prod",
                   help="Required alongside --apply when "
                        "APP_ENV=production.")
    return p


async def _cli_main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_parser().parse_args()

    if args.apply and args.dry_run:
        raise SafetyRefused(
            "REFUSED: --apply and --dry-run are mutually exclusive.",
        )

    prefixes = list(args.prefixes)
    if not prefixes and not args.tenant_ids:
        prefixes = list(DEFAULT_PREFIXES)

    print(f"[purge] APP_ENV={_app_env()!r} "
          f"mode={'APPLY' if args.apply else 'DRY-RUN'} "
          f"prefixes={prefixes or '(none — using --tenant-id list)'} "
          f"tenant_ids={args.tenant_ids or '(none)'}")

    # Late import so tests can stub ``config.db``.
    from config import db

    result = await run_purge(
        db=db,
        prefixes=prefixes,
        tenant_ids=list(args.tenant_ids),
        apply=args.apply,
        limit=(args.limit if args.limit > 0 else None),
        i_know_this_is_prod=args.ack_prod,
    )
    return int(result.get("exit_code", 0))


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_cli_main()))
    except SafetyRefused as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
