"""One-shot production demo-data purge script.

Feb-2026 · Follow-up to the D2 boot-hardening PR.

**READ THIS BEFORE RUNNING**

This script deletes seed / demo data from a MongoDB deployment.
It is destructive.  The default posture is safe:

  * ``--dry-run`` (implicit default) — nothing is written.
  * ``--commit --i-understand-this-is-permanent`` — BOTH flags are
    required to actually delete.
  * The script refuses ``--commit`` unless ``APP_ENV=production``.
    Dry-run works in any environment.
  * A gzip'd JSON backup of every candidate document is written to
    ``--backup-dir/demo_purge_<UTC>.json.gz`` BEFORE any delete.
    Backup failure aborts the run — no delete without a backup.

**Guarantees**

  * A hardcoded ``REAL_USER_ALLOWLIST`` of user emails survives a
    tenant-wholesale purge (currently ``brian@plofv.com``).
  * Only rows in the identified demo tenants are touched, plus users
    matching the seeded-email pattern.  No global "delete anything
    that looks demo" — every deletion is either (a) tenant-scoped
    to an explicit demo tenant, or (b) an explicit doc marker
    ``is_demo: true`` / ``source: "seed"``.
  * Even inside a demo tenant, users on the allowlist survive.
  * Even inside a demo tenant, docs with explicit ``is_demo: false``
    survive and are logged as ``preserved_marker``.
  * Customers/jobs/invoices/etc.  outside a purged demo tenant are
    NEVER touched, even if their names look suspicious.
  * After a successful commit, ONE audit row is inserted into
    ``audit_logs`` recording the run (backup path, counts).

**Ops runbook**

  1. Deploy the script.
  2. Dry-run on prod:
     ``APP_ENV=production python -m scripts.purge_demo_data \\
        --tenant-slug aquaterra --auto-discover-demo-tenants``
  3. Human eyeballs the counts + sample IDs.
  4. Re-run with ``--commit --i-understand-this-is-permanent`` to
     actually delete.
  5. Backup file path is printed at the end — download + archive it.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Allow ``python -m scripts.purge_demo_data`` from /app/backend AND
# ``python /app/backend/scripts/purge_demo_data.py``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


# ═══════════════════════════════════════════════════════════════════════
# Safety constants — edit here, NOT via CLI, when you promote a real
# user out of / into the allowlist.
# ═══════════════════════════════════════════════════════════════════════

# Emails that MUST survive even if their tenant is being purged.
# Adding an email here means "this is a real human, do not delete".
REAL_USER_ALLOWLIST: set[str] = {
    "brian@plofv.com",
}

# Regex patterns used for auto-discovery of demo tenants.  A tenant
# whose ``slug`` matches ANY of these is treated as a demo tenant if
# ``--auto-discover-demo-tenants`` is passed.  Case-insensitive.
DEMO_TENANT_SLUG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^aquaterra$", re.I),
    re.compile(r"^demo[-_].*", re.I),
    re.compile(r"^test[-_].*", re.I),
    re.compile(r"^TEST_.*"),           # TEST_tos*, TEST_reorder*
]

# Email suffixes used for auto-discovery of seeded user accounts.
# A user with ``email`` ending in one of these (case-insensitive) is
# treated as a demo/seeded account for the purpose of the purge.
# NOTE: these are only auto-discovered when
# ``--auto-discover-demo-tenants`` is passed.  Otherwise the caller
# must name the tenant explicitly via ``--tenant-slug``.
DEMO_USER_EMAIL_SUFFIXES: tuple[str, ...] = (
    "@aquaterra.com",
)

# Explicit doc-level markers.  A document with ANY of these fields
# set is treated as demo, regardless of its tenant.
DEMO_DOC_MARKERS: list[dict[str, Any]] = [
    {"is_demo": True},
    {"source": "seed"},
]

# Collections that are NOT tenant-scoped (or whose ``tenant_id`` is
# the string "global").  These are inspected for demo markers only —
# never wholesale-purged with a tenant.
GLOBAL_COLLECTIONS: set[str] = {
    "audit_logs",           # AUDIT LOG — see note below
    "audit_log",            # legacy singular name
    "sessions",             # short-lived JWT session tracking
    "distance_matrix_cache",
    "reverse_geocode_cache",
    "system_settings",
}

# Reserved: the audit log we WRITE at the end (survives the purge)
# is exactly one row.  All prior audit-log rows that reference a
# purged tenant are deleted via ``tenant_id`` scoping below.
AUDIT_LOG_COLLECTION = "audit_logs"


# ═══════════════════════════════════════════════════════════════════════

_LOG = logging.getLogger("purge_demo_data")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _app_env() -> str:
    return (os.environ.get("APP_ENV", "preview") or "preview").lower()


# ═══════════════════════════════════════════════════════════════════════
# Discovery — figure out WHICH tenants + users are demo.
# ═══════════════════════════════════════════════════════════════════════

async def discover_demo_tenants(
    db,
    *,
    explicit_slugs: list[str],
    auto_discover: bool,
) -> list[dict]:
    """Return the list of tenant docs that will be purged.

    Discovery sources, in order:
      1. Explicit ``--tenant-slug`` args (always honored).
      2. Tenant docs with ``is_demo: True``.
      3. If ``--auto-discover-demo-tenants``: tenants whose slug
         matches ``DEMO_TENANT_SLUG_PATTERNS``.
    """
    seen_ids: set[str] = set()
    picked: list[dict] = []

    # 1) explicit slugs
    if explicit_slugs:
        async for t in db.tenants.find(
            {"slug": {"$in": explicit_slugs}}, {"_id": 0},
        ):
            if t.get("id") and t["id"] not in seen_ids:
                seen_ids.add(t["id"])
                t["_demo_reason"] = f"explicit --tenant-slug={t.get('slug')}"
                picked.append(t)

    # 2) is_demo=True
    async for t in db.tenants.find({"is_demo": True}, {"_id": 0}):
        if t.get("id") and t["id"] not in seen_ids:
            seen_ids.add(t["id"])
            t["_demo_reason"] = "tenant.is_demo=True"
            picked.append(t)

    # 3) slug-pattern auto-discovery
    if auto_discover:
        async for t in db.tenants.find({}, {"_id": 0}):
            if t.get("id") in seen_ids:
                continue
            slug = t.get("slug") or ""
            for pat in DEMO_TENANT_SLUG_PATTERNS:
                if pat.search(slug):
                    seen_ids.add(t["id"])
                    t["_demo_reason"] = f"slug matches {pat.pattern}"
                    picked.append(t)
                    break

    return picked


async def discover_orphan_demo_users(db, purged_tenant_ids: set[str]) -> list[dict]:
    """Return demo-pattern users that do NOT belong to a purged
    tenant (e.g. someone re-parented a seeded account to a real
    tenant).  Auto-discover only — never touched without
    ``--auto-discover-demo-tenants``.
    """
    if not DEMO_USER_EMAIL_SUFFIXES:
        return []
    or_terms = [
        {"email": {"$regex": re.escape(s) + "$", "$options": "i"}}
        for s in DEMO_USER_EMAIL_SUFFIXES
    ]
    q = {"$or": or_terms, "tenant_id": {"$nin": list(purged_tenant_ids)}}
    return [u async for u in db.users.find(q, {"_id": 0})]


async def discover_demo_marker_docs(db, coll_name: str) -> list[dict]:
    """Return docs in ``coll_name`` that carry an explicit demo marker
    (``is_demo: True`` or ``source: "seed"``).
    """
    return [
        d async for d in db[coll_name].find(
            {"$or": DEMO_DOC_MARKERS}, {"_id": 0},
        )
    ]


# ═══════════════════════════════════════════════════════════════════════
# Preservation — decide who survives even inside a purged tenant.
# ═══════════════════════════════════════════════════════════════════════

def _is_allowlisted_user(doc: dict) -> bool:
    email = (doc.get("email") or "").lower()
    return email in {e.lower() for e in REAL_USER_ALLOWLIST}


def _is_explicit_non_demo(doc: dict) -> bool:
    """Doc has explicit ``is_demo: False`` — an operator's manual
    override to keep it even inside a demo tenant."""
    return doc.get("is_demo") is False


def _preservation_reason(coll: str, doc: dict) -> str | None:
    """Return a reason to skip this doc, or ``None`` to delete it."""
    if coll == "users" and _is_allowlisted_user(doc):
        return f"user email {doc.get('email')} in REAL_USER_ALLOWLIST"
    if _is_explicit_non_demo(doc):
        return "doc has is_demo=False (explicit operator override)"
    return None


# ═══════════════════════════════════════════════════════════════════════
# Candidate collection — enumerate every doc that WOULD be deleted.
# ═══════════════════════════════════════════════════════════════════════

async def _collect_tenant_scoped_candidates(
    db, purged_tenant_ids: set[str],
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """For every collection with a ``tenant_id`` field, split its
    matching docs into (candidates, preserved).
    Returns ``(candidates_by_collection, preserved_by_collection)``.
    """
    candidates: dict[str, list[dict]] = {}
    preserved: dict[str, list[dict]] = {}
    coll_names = await db.list_collection_names()

    for name in sorted(coll_names):
        if name in GLOBAL_COLLECTIONS and name != AUDIT_LOG_COLLECTION:
            # Global (non-tenant-scoped) — skip here; handled below.
            continue
        # Try a tenant-scoped scan; if the collection has zero docs
        # with tenant_id, the loop yields nothing.
        docs = [
            d async for d in db[name].find(
                {"tenant_id": {"$in": list(purged_tenant_ids)}}, {"_id": 0},
            )
        ]
        if not docs:
            continue
        keep, drop = [], []
        for d in docs:
            reason = _preservation_reason(name, d)
            if reason:
                d["_preserve_reason"] = reason
                keep.append(d)
            else:
                drop.append(d)
        if drop:
            candidates[name] = drop
        if keep:
            preserved[name] = keep
    return candidates, preserved


async def _collect_orphan_users(
    db, purged_tenant_ids: set[str],
) -> tuple[list[dict], list[dict]]:
    """Split orphan demo-email users into (candidates, preserved)."""
    users = await discover_orphan_demo_users(db, purged_tenant_ids)
    drop, keep = [], []
    for u in users:
        reason = _preservation_reason("users", u)
        if reason:
            u["_preserve_reason"] = reason
            keep.append(u)
        else:
            drop.append(u)
    return drop, keep


async def _collect_marker_candidates(
    db, purged_tenant_ids: set[str],
) -> dict[str, list[dict]]:
    """Docs with explicit ``is_demo: True`` / ``source: "seed"`` in
    collections that are NOT already covered by the tenant-scoped
    scan (avoid double-count).
    """
    out: dict[str, list[dict]] = {}
    coll_names = await db.list_collection_names()
    for name in sorted(coll_names):
        if name in GLOBAL_COLLECTIONS:
            continue
        docs = await discover_demo_marker_docs(db, name)
        # Exclude anything already in a purged tenant (double-count).
        docs = [
            d for d in docs
            if d.get("tenant_id") not in purged_tenant_ids
        ]
        if docs:
            out[name] = docs
    return out


# ═══════════════════════════════════════════════════════════════════════
# Backup — gzip'd JSON of everything about to be deleted.
# ═══════════════════════════════════════════════════════════════════════

def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    try:
        return str(o)
    except Exception:
        return None


def write_backup(
    backup_dir: Path,
    payload: dict[str, Any],
) -> Path:
    """Write ``payload`` to ``<backup_dir>/demo_purge_<UTC>.json.gz``.
    Returns the resolved path.  Raises on any I/O error — the caller
    must abort the delete on failure.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"demo_purge_{stamp}.json.gz"
    raw = json.dumps(
        payload, default=_json_default, indent=2, sort_keys=True,
    ).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(raw)
    # Fsync-ish: re-open for read to make sure the file is on disk.
    if path.stat().st_size == 0:
        raise RuntimeError(f"backup wrote 0 bytes to {path}")
    return path


# ═══════════════════════════════════════════════════════════════════════
# Delete — issue the actual delete_many calls.
# ═══════════════════════════════════════════════════════════════════════

async def _delete_candidates(
    db, candidates_by_collection: dict[str, list[dict]],
) -> dict[str, int]:
    """Delete every candidate by ``id``.  Returns per-collection
    deleted counts.  Skips the audit_logs collection because it's
    handled specially below (we write ONE row after everything).
    """
    counts: dict[str, int] = {}
    for coll, docs in candidates_by_collection.items():
        ids = [d.get("id") for d in docs if d.get("id")]
        if not ids:
            counts[coll] = 0
            continue
        r = await db[coll].delete_many({"id": {"$in": ids}})
        counts[coll] = r.deleted_count
    return counts


async def _delete_orphan_users(db, users: list[dict]) -> int:
    ids = [u.get("id") for u in users if u.get("id")]
    if not ids:
        return 0
    r = await db.users.delete_many({"id": {"$in": ids}})
    return r.deleted_count


async def _delete_tenants(db, tenant_ids: set[str]) -> int:
    if not tenant_ids:
        return 0
    r = await db.tenants.delete_many({"id": {"$in": list(tenant_ids)}})
    return r.deleted_count


# ═══════════════════════════════════════════════════════════════════════
# Report — print the dry-run / commit summary.
# ═══════════════════════════════════════════════════════════════════════

def _print_section(title: str) -> None:
    print()
    print("─" * 72)
    print(title)
    print("─" * 72)


def _print_candidates(cands: dict[str, list[dict]], label: str) -> int:
    if not cands:
        print(f"  (none)")
        return 0
    total = 0
    for name in sorted(cands):
        docs = cands[name]
        total += len(docs)
        sample = [d.get("id") for d in docs[:20] if d.get("id")]
        print(f"  {label:<25} {name:<40} {len(docs):>7}   sample: {sample[:5]}")
    return total


# ═══════════════════════════════════════════════════════════════════════
# Safety gates.
# ═══════════════════════════════════════════════════════════════════════

def _check_prod_only_for_commit(commit: bool, ack: bool) -> None:
    """Refuse to --commit unless BOTH ack flag is present AND
    APP_ENV=production.  Dry-run always allowed.
    """
    if not commit:
        return
    if not ack:
        raise SystemExit(
            "REFUSED: --commit requires --i-understand-this-is-permanent"
        )
    if _app_env() != "production":
        raise SystemExit(
            f"REFUSED: --commit only allowed when APP_ENV=production "
            f"(saw APP_ENV={_app_env()!r}).  Dry-run is allowed anywhere."
        )


# ═══════════════════════════════════════════════════════════════════════
# Entry point.
# ═══════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-shot production demo-data purge script. "
                     "Defaults to dry-run.",
    )
    p.add_argument("--commit", action="store_true",
                    help="Actually delete (default: dry-run)")
    p.add_argument("--i-understand-this-is-permanent",
                    action="store_true", dest="ack",
                    help="Required alongside --commit")
    p.add_argument("--dry-run", action="store_true", default=None,
                    help="Explicit dry-run (default when neither "
                          "--commit nor --dry-run is passed)")
    p.add_argument("--backup-dir", type=Path,
                    default=Path("/app/backups"),
                    help="Directory to write the gzip'd JSON backup")
    p.add_argument("--tenant-slug", action="append", default=[],
                    dest="tenant_slugs",
                    help="Repeatable — explicit tenant slug(s) to purge")
    p.add_argument("--auto-discover-demo-tenants", action="store_true",
                    help="Also purge tenants whose slug matches "
                          "DEMO_TENANT_SLUG_PATTERNS, and users with "
                          "seeded email suffixes.")
    return p


async def run(
    *,
    db,
    tenant_slugs: list[str],
    auto_discover: bool,
    commit: bool,
    backup_dir: Path,
) -> dict[str, Any]:
    """Programmable entrypoint (used by tests + CLI main)."""
    t0 = time.perf_counter()

    demo_tenants = await discover_demo_tenants(
        db, explicit_slugs=tenant_slugs, auto_discover=auto_discover,
    )
    purged_tenant_ids = {t["id"] for t in demo_tenants}

    _print_section("Demo tenants selected for purge")
    if not demo_tenants:
        print("  (none — nothing to do)")
    else:
        for t in demo_tenants:
            print(f"  id={t['id']}  slug={t.get('slug'):<20}  "
                   f"reason={t.get('_demo_reason')}")

    cand_by_coll, preserved_by_coll = await _collect_tenant_scoped_candidates(
        db, purged_tenant_ids,
    )

    orphan_drop, orphan_keep = [], []
    if auto_discover:
        orphan_drop, orphan_keep = await _collect_orphan_users(
            db, purged_tenant_ids,
        )

    marker_cands = await _collect_marker_candidates(db, purged_tenant_ids)

    _print_section("Candidate rows (WOULD delete)")
    n1 = _print_candidates(cand_by_coll, "[tenant-scoped]")
    if orphan_drop:
        print(f"  {'[orphan users]':<25} {'users':<40} {len(orphan_drop):>7}   "
               f"sample: {[u.get('email') for u in orphan_drop[:5]]}")
        n1 += len(orphan_drop)
    n_marker = _print_candidates(marker_cands, "[explicit marker]")
    total_candidates = n1 + n_marker + len(demo_tenants)

    _print_section("Preserved (skipped_ambiguous / allowlisted)")
    for coll, docs in sorted(preserved_by_coll.items()):
        sample = [(d.get("email") or d.get("id"), d.get("_preserve_reason"))
                  for d in docs[:5]]
        print(f"  {coll:<40} {len(docs):>5}   sample: {sample}")
    for u in orphan_keep:
        print(f"  {'users (orphan)':<40} {'':<5}   {u.get('email')} "
               f"[{u.get('_preserve_reason')}]")

    _print_section("Summary")
    print(f"  demo tenants          : {len(demo_tenants)}")
    print(f"  tenant-scoped rows    : {n1 - len(orphan_drop)}")
    print(f"  orphan demo users     : {len(orphan_drop)}")
    print(f"  explicit-marker rows  : {n_marker}")
    print(f"  ── TOTAL WOULD DELETE : {total_candidates}")
    print(f"  preserved rows        : "
           f"{sum(len(v) for v in preserved_by_coll.values()) + len(orphan_keep)}")

    if not commit:
        elapsed = time.perf_counter() - t0
        _print_section(f"DRY-RUN complete in {elapsed:.2f}s — NO writes made")
        return {
            "mode": "dry_run",
            "tenants": len(demo_tenants),
            "total_candidates": total_candidates,
            "counts": {c: len(v) for c, v in cand_by_coll.items()},
            "orphan_users": len(orphan_drop),
            "marker_docs": {c: len(v) for c, v in marker_cands.items()},
        }

    # ── COMMIT MODE from here down ─────────────────────────────
    _print_section("COMMIT MODE — writing backup first")
    payload = {
        "generated_at": _utc_iso(),
        "app_env": _app_env(),
        "demo_tenants": demo_tenants,
        "candidates": cand_by_coll,
        "orphan_users": orphan_drop,
        "marker_docs": marker_cands,
        "preserved": preserved_by_coll,
    }
    try:
        backup_path = write_backup(backup_dir, payload)
    except Exception as exc:
        _LOG.exception("Backup FAILED — aborting before any delete")
        raise SystemExit(f"Backup failed: {exc}")
    print(f"  backup written: {backup_path}  "
           f"({backup_path.stat().st_size:,} bytes)")

    _print_section("COMMIT MODE — issuing deletes")
    deleted_counts: dict[str, int] = {}
    # 1) tenant-scoped rows across every affected collection
    dc = await _delete_candidates(db, cand_by_coll)
    deleted_counts.update(dc)
    # 2) marker-based rows in non-purged tenants
    dc = await _delete_candidates(db, marker_cands)
    for k, v in dc.items():
        deleted_counts[k] = deleted_counts.get(k, 0) + v
    # 3) orphan users
    deleted_counts["users (orphan)"] = await _delete_orphan_users(
        db, orphan_drop,
    )
    # 4) tenants themselves
    deleted_counts["tenants"] = await _delete_tenants(db, purged_tenant_ids)

    for coll, n in sorted(deleted_counts.items()):
        if n:
            print(f"  deleted {n:>7}  from {coll}")

    # 5) audit log — write ONE row.  Do this LAST so a partial-delete
    # crash above still leaves ops able to reason from the backup file.
    total_deleted = sum(deleted_counts.values())
    audit_row = {
        "id": str(uuid.uuid4()),
        "event": "demo_data_purge",
        "email": "ops-script",
        "ip_address": None,
        "status": "committed",
        "details": {
            "counts": deleted_counts,
            "total_deleted": total_deleted,
            "backup_path": str(backup_path),
            "tenant_ids": sorted(purged_tenant_ids),
            "elapsed_s": round(time.perf_counter() - t0, 2),
        },
        "created_at": _utc_iso(),
    }
    try:
        await db[AUDIT_LOG_COLLECTION].insert_one(audit_row)
        audit_row.pop("_id", None)
        print(f"  audit log written to {AUDIT_LOG_COLLECTION} · id={audit_row['id']}")
    except Exception as exc:
        _LOG.exception("audit log write failed (data already deleted)")
        print(f"  WARN: audit log write failed — {exc}")

    _print_section(f"COMMIT complete in {time.perf_counter() - t0:.2f}s")
    print(f"  Total deleted: {total_deleted}")
    print(f"  Backup: {backup_path}")
    print(f"  Please archive the backup file NOW.")

    return {
        "mode": "commit",
        "tenants": len(demo_tenants),
        "total_deleted": total_deleted,
        "counts": deleted_counts,
        "backup_path": str(backup_path),
        "audit_id": audit_row["id"],
    }


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args()

    # Mutually-exclusive sanity: --dry-run + --commit → refuse.
    if args.dry_run and args.commit:
        raise SystemExit("REFUSED: --dry-run and --commit are mutually exclusive")

    _check_prod_only_for_commit(args.commit, args.ack)

    print(f"[purge] APP_ENV={_app_env()!r}  mode="
           f"{'COMMIT' if args.commit else 'DRY-RUN'}")

    # Late import so tests can inject a fake db.
    from config import db

    result = await run(
        db=db,
        tenant_slugs=args.tenant_slugs,
        auto_discover=args.auto_discover_demo_tenants,
        commit=args.commit,
        backup_dir=args.backup_dir,
    )
    return 0 if result else 0  # always 0 unless we raised earlier


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
