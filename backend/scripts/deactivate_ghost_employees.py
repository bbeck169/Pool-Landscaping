"""Feb-2026 · Operator-run tool — deactivate ghost employees.

Safer than deletion: reversible, preserves audit history, matches
the pattern used by the shipped hard-delete endpoints (which snapshot
before delete). Default run is dry-run; a real write requires
``--apply`` + ``TENANT_ID`` env + a typed ``yes`` confirmation.

CONFIGURATION — ENVIRONMENT VARIABLES ONLY:
    MONGO_URI      — required, no default
    MONGO_DB_NAME  — required, no default
    TENANT_ID      — required for ``--apply`` — refuses to run
                     without an explicit tenant to protect against
                     cross-tenant data mutation

INVOCATION:
    # Dry-run with inline names (default)
    MONGO_URI=... MONGO_DB_NAME=... TENANT_ID=... \\
        python backend/scripts/deactivate_ghost_employees.py \\
            --names "Anthony Sotelo,Brian Beckman,Carlos Rivera"

    # Dry-run with names from a JSON file
    python backend/scripts/deactivate_ghost_employees.py \\
            --names-file ghosts.json

    # Real run — must pass --apply AND type ``yes`` at stdin
    MONGO_URI=... MONGO_DB_NAME=... TENANT_ID=... \\
        python backend/scripts/deactivate_ghost_employees.py \\
            --names "..." --apply

    # Safest path — explicit IDs instead of fuzzy name match
    MONGO_URI=... MONGO_DB_NAME=... TENANT_ID=... \\
        python backend/scripts/deactivate_ghost_employees.py \\
            --ids "id1,id2,id3" --apply

    # Hard-delete (destructive, OFF by default)
    MONGO_URI=... MONGO_DB_NAME=... TENANT_ID=... \\
        python backend/scripts/deactivate_ghost_employees.py \\
            --names "..." --apply --hard-delete \\
            --i-know-this-is-destructive

GUARANTEES:
  * No ``--apply`` call writes to the DB without a typed ``yes``
    confirmation on stdin.
  * Every real write is preceded by a full ``$doc`` snapshot into
    ``ghost_employees_backup_<tenant>_<timestamp>.json``.
  * Multi-match names cause a HARD STOP with non-zero exit code —
    the operator must switch to ``--ids`` to disambiguate.
  * ``--hard-delete`` requires BOTH ``--apply`` AND
    ``--i-know-this-is-destructive`` AND a second typed ``yes``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient


DEFAULT_REASON = "ghost_timecard_cleanup"
DEFAULT_BY = "operator_script"
_NAME_FIELDS = ("name", "full_name")


# ─────────────────────────────────────────────────────────────────
# Logging — stdout + timestamped log file.
# ─────────────────────────────────────────────────────────────────
def _setup_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("deactivate_ghost_employees")
    logger.setLevel(logging.INFO)
    # Avoid duplicate handlers on re-import under pytest.
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(str(log_path))
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


# ─────────────────────────────────────────────────────────────────
# Config — env-var resolution.
# ─────────────────────────────────────────────────────────────────
def _load_config() -> Dict[str, Optional[str]]:
    """Load required env vars.  Never defaults — missing values
    surface as ``None`` so the caller fails fast with a clear
    error message rather than writing to the wrong DB."""
    return {
        "mongo_uri": os.environ.get("MONGO_URI")
                     or os.environ.get("MONGO_URL"),
        "mongo_db_name": os.environ.get("MONGO_DB_NAME")
                         or os.environ.get("DB_NAME"),
        "tenant_id": os.environ.get("TENANT_ID"),
    }


# ─────────────────────────────────────────────────────────────────
# Name-match + ID-match helpers.
# ─────────────────────────────────────────────────────────────────
def _case_insensitive_exact(name: str) -> re.Pattern:
    """Exact-match pattern (anchored) with case-insensitive flag.
    Avoids false positives like matching "Carlos Rivera" inside
    "Carlos Rivera-Perez"."""
    return re.compile(f"^{re.escape(name.strip())}$", re.IGNORECASE)


def _find_by_names(
    coll, *, tenant_id: str, names: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return {name: [matched docs]}. Empty list means no match."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        pat = _case_insensitive_exact(name)
        q = {
            "tenant_id": tenant_id,
            "$or": [{f: pat} for f in _NAME_FIELDS],
        }
        matches = list(coll.find(
            q,
            {"_id": 0, "id": 1, "name": 1, "full_name": 1,
             "role": 1, "active": 1, "tenant_id": 1},
        ))
        out[name] = matches
    return out


def _find_by_ids(
    coll, *, tenant_id: str, ids: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """ID-based path — safer than fuzzy name match. Each ID returns
    0 or 1 doc (ID is tenant-scoped unique in this schema)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for raw in ids:
        uid = raw.strip()
        if not uid:
            continue
        matches = list(coll.find(
            {"tenant_id": tenant_id, "id": uid},
            {"_id": 0, "id": 1, "name": 1, "full_name": 1,
             "role": 1, "active": 1, "tenant_id": 1},
        ))
        out[uid] = matches
    return out


# ─────────────────────────────────────────────────────────────────
# Backup — snapshot full docs BEFORE any mutation.
# ─────────────────────────────────────────────────────────────────
def _snapshot_backup(
    coll, *, ids: List[str], tenant_id: str, out_path: Path,
) -> int:
    """Dump the full ``$doc`` for every ID to a JSON file. Returns
    the row count written. The file is the rollback artifact —
    without this, a mistaken deactivation is non-trivially
    recoverable."""
    rows = list(coll.find(
        {"tenant_id": tenant_id, "id": {"$in": ids}},
        {"_id": 0},
    ))
    out_path.write_text(json.dumps(rows, default=str, indent=2))
    return len(rows)


# ─────────────────────────────────────────────────────────────────
# Core operations.
# ─────────────────────────────────────────────────────────────────
def _deactivate(
    coll, *, ids: List[str], tenant_id: str,
    now_iso: str,
) -> Dict[str, int]:
    r = coll.update_many(
        {"tenant_id": tenant_id, "id": {"$in": ids}},
        {"$set": {
            "active": False,
            "deactivated_at": now_iso,
            "deactivated_reason": DEFAULT_REASON,
            "deactivated_by": DEFAULT_BY,
        }},
    )
    return {"matched": r.matched_count, "modified": r.modified_count}


def _hard_delete(
    coll, *, ids: List[str], tenant_id: str,
) -> Dict[str, int]:
    r = coll.delete_many(
        {"tenant_id": tenant_id, "id": {"$in": ids}},
    )
    return {"deleted": r.deleted_count}


# ─────────────────────────────────────────────────────────────────
# CLI entry point — testable via main(argv=..., stdin=..., ...).
# ─────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Deactivate (default) or hard-delete (destructive) a "
            "set of ghost employee user docs in a specific tenant. "
            "Dry-run by default; writes require --apply AND a "
            "typed 'yes' confirmation."
        ),
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--names",
        help=(
            "Comma-separated full names. Case-insensitive exact "
            "match on 'name' / 'full_name' fields."
        ),
    )
    g.add_argument(
        "--names-file",
        help=(
            "Path to a JSON file with a list of full names. "
            "Example: [\"Alice Smith\", \"Bob Jones\"]"
        ),
    )
    g.add_argument(
        "--ids",
        help=(
            "Comma-separated user IDs — SAFEST path. Bypasses the "
            "name-match flow entirely. Required if any name has "
            "multi-match (the script forces this path by refusing "
            "to apply on multi-match)."
        ),
    )
    p.add_argument(
        "--apply", action="store_true",
        help=(
            "Actually write. Without this, the script runs in "
            "dry-run mode and prints what WOULD change."
        ),
    )
    p.add_argument(
        "--hard-delete", action="store_true",
        help=(
            "DESTRUCTIVE: hard-delete the rows instead of "
            "deactivating. Requires --apply AND "
            "--i-know-this-is-destructive AND a typed 'yes'."
        ),
    )
    p.add_argument(
        "--i-know-this-is-destructive", action="store_true",
        help="Required alongside --hard-delete.",
    )
    p.add_argument(
        "--log-dir", default=".",
        help="Directory for the timestamped log + backup files.",
    )
    return p


def _resolve_names(args) -> List[str]:
    if args.names:
        return [n for n in (args.names or "").split(",") if n.strip()]
    if args.names_file:
        raw = Path(args.names_file).read_text()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise SystemExit(
                "--names-file must contain a JSON array of names",
            )
        return [str(n).strip() for n in data if str(n).strip()]
    return []


def _resolve_ids(args) -> List[str]:
    if not args.ids:
        return []
    return [i for i in (args.ids or "").split(",") if i.strip()]


def main(
    argv: Optional[List[str]] = None,
    *,
    stdin=None,
    stdout=None,
    coll_override=None,
) -> int:
    """Returns a process exit code (0 on success, non-zero on
    STOP). Dependency injection on ``stdin`` + ``coll_override``
    is for pytest coverage.
    """
    out = stdout or sys.stdout
    args = _build_parser().parse_args(argv)
    cfg = _load_config()

    # Guard — hard-delete needs the extra flag + apply.
    if args.hard_delete and not args.i_know_this_is_destructive:
        print(
            "ERROR: --hard-delete requires "
            "--i-know-this-is-destructive",
            file=out,
        )
        return 2
    if args.hard_delete and not args.apply:
        print(
            "ERROR: --hard-delete requires --apply (dry-run has "
            "no destructive mode)",
            file=out,
        )
        return 2

    # Guard — missing env.
    if not cfg["mongo_uri"] or not cfg["mongo_db_name"]:
        print(
            "ERROR: MONGO_URI + MONGO_DB_NAME env vars are "
            "required",
            file=out,
        )
        return 2
    if args.apply and not cfg["tenant_id"]:
        print(
            "ERROR: TENANT_ID env var is REQUIRED with --apply. "
            "Refusing to run cross-tenant deactivation.",
            file=out,
        )
        return 2
    # Dry-run still needs tenant_id so the operator sees the
    # right scope; soft-fail with a warning if missing instead
    # of refusing (lets the operator preview before setting the
    # env var).
    if not cfg["tenant_id"]:
        print(
            "WARN: TENANT_ID not set — dry-run will show NO "
            "results (tenant scoping is mandatory).",
            file=out,
        )

    # Set up log file.
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tenant_slug = (cfg["tenant_id"] or "notenant").replace(
        "/", "_",
    )
    log_path = log_dir / f"deactivate_ghost_log_{tenant_slug}_{ts}.log"
    logger = _setup_logging(log_path)

    # Connect.
    if coll_override is not None:
        coll = coll_override
    else:
        client = MongoClient(cfg["mongo_uri"])
        coll = client[cfg["mongo_db_name"]].users

    logger.info(
        "config: mongo_db=%s tenant_id=%s mode=%s log=%s",
        cfg["mongo_db_name"], cfg["tenant_id"],
        "apply" if args.apply else "dry-run",
        log_path,
    )

    # Resolve target IDs.
    using_ids = bool(args.ids)
    if using_ids:
        ids = _resolve_ids(args)
        logger.info("ID path · %d ids", len(ids))
        matches = _find_by_ids(
            coll, tenant_id=cfg["tenant_id"] or "", ids=ids,
        )
    else:
        names = _resolve_names(args)
        logger.info("Name path · %d names", len(names))
        matches = _find_by_names(
            coll, tenant_id=cfg["tenant_id"] or "", names=names,
        )

    # Print per-input summary. Flag multi-matches + zero-matches.
    all_target_ids: List[str] = []
    multi_match_keys: List[str] = []
    zero_match_keys: List[str] = []
    for key, docs in matches.items():
        logger.info("  '%s' → %d match(es)", key, len(docs))
        for d in docs:
            logger.info(
                "    - id=%s name=%r active=%s role=%s",
                d.get("id"), d.get("name") or d.get("full_name"),
                d.get("active"), d.get("role"),
            )
        if len(docs) == 0:
            zero_match_keys.append(key)
        elif len(docs) == 1:
            all_target_ids.append(docs[0]["id"])
        else:
            multi_match_keys.append(key)

    # HARD STOP on multi-match (names path only — ID path can't
    # multi-match by definition).
    if multi_match_keys:
        logger.error(
            "STOP: %d name(s) with multiple matches: %s. Switch "
            "to --ids with explicit IDs to disambiguate.",
            len(multi_match_keys), multi_match_keys,
        )
        return 3

    # Zero-match surface — informational, not blocking (operator
    # may want to proceed with the found subset).
    if zero_match_keys:
        logger.warning(
            "%d input(s) with NO match: %s. These will be ignored.",
            len(zero_match_keys), zero_match_keys,
        )

    if not all_target_ids:
        logger.info("Nothing to do — zero targets resolved.")
        return 0

    logger.info("Resolved %d target(s): %s",
                len(all_target_ids), all_target_ids)

    if not args.apply:
        logger.info("Dry-run only. Re-run with --apply to write.")
        return 0

    # Confirmation prompt — typed 'yes'.
    stdin_src = stdin or sys.stdin
    verb = "HARD-DELETE" if args.hard_delete else "deactivate"
    prompt = (
        f"\nAbout to {verb} {len(all_target_ids)} user(s) in "
        f"tenant {cfg['tenant_id']}.\n"
        f"Type 'yes' to proceed, anything else to abort: "
    )
    print(prompt, file=out, end="")
    out.flush()
    reply = stdin_src.readline().strip().lower()
    if reply != "yes":
        logger.info("Aborted by operator (reply=%r).", reply)
        return 4

    # Hard-delete gets a SECOND typed-yes confirmation.
    if args.hard_delete:
        print(
            "\nSECOND CONFIRMATION — hard-delete is irreversible. "
            "Type 'yes' AGAIN: ", file=out, end="",
        )
        out.flush()
        reply2 = stdin_src.readline().strip().lower()
        if reply2 != "yes":
            logger.info(
                "Aborted at second confirmation (reply=%r).",
                reply2,
            )
            return 4

    # Snapshot BEFORE any mutation. This is the rollback artifact.
    backup_path = log_dir / (
        f"ghost_employees_backup_{tenant_slug}_{ts}.json"
    )
    n_backed = _snapshot_backup(
        coll, ids=all_target_ids,
        tenant_id=cfg["tenant_id"], out_path=backup_path,
    )
    logger.info("Snapshot: %d row(s) → %s", n_backed, backup_path)

    # Mutate.
    now_iso = datetime.now(timezone.utc).isoformat()
    if args.hard_delete:
        res = _hard_delete(
            coll, ids=all_target_ids,
            tenant_id=cfg["tenant_id"],
        )
        logger.info(
            "HARD-DELETE complete: deleted=%d. Backup at %s",
            res["deleted"], backup_path,
        )
    else:
        res = _deactivate(
            coll, ids=all_target_ids,
            tenant_id=cfg["tenant_id"],
            now_iso=now_iso,
        )
        logger.info(
            "Deactivate complete: matched=%d modified=%d. "
            "Backup at %s",
            res["matched"], res["modified"], backup_path,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
