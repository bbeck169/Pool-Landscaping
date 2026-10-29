#!/usr/bin/env python3
"""Standalone Homeworks job delete script — OPERATOR-RUN ONLY.

Deletes jobs from ``db.jobs`` whose discriminator field matches
the Homeworks-import marker, for a specific tenant.  Designed to
be run from the OPERATOR'S machine against their production
MongoDB — the builder pod cannot reach prod.

USAGE
-----

Dry-run (default — reports counts + sample, does NOT delete)::

    export MONGO_URI="mongodb+srv://..."
    export MONGO_DB_NAME="pool_crm_prod"
    export TENANT_ID="t-abc123"
    python backend/scripts/delete_homeworks_jobs.py

Apply (destructive — snapshots to JSON file, then deletes)::

    python backend/scripts/delete_homeworks_jobs.py --apply

Overrides (if prod schema uses a different discriminator)::

    python backend/scripts/delete_homeworks_jobs.py \\
        --filter-key source --value homeworks --apply

Large sweeps (safety rail refuses > 10,000 without this flag)::

    python backend/scripts/delete_homeworks_jobs.py \\
        --apply --force-large

SAFETY
------

* Dry-run by default.  Must pass ``--apply`` to delete.
* Refuses to run with ``--apply`` if ``TENANT_ID`` is unset.
* Refuses to delete > 10,000 docs without ``--force-large``.
* ``--apply`` requires an interactive ``yes`` typed at stdin
  before any delete is executed.
* Backs up every matching doc to a timestamped JSON file on
  disk BEFORE deleting.  File path is printed in the final
  summary — the ONLY recovery path if an operator fat-fingers.
* Writes every action to stdout AND a timestamped log file.

NON-SCOPE
---------

This script connects FROM the operator's machine TO their prod
Mongo.  It never phones home, never calls the builder pod, and
has no backend-app imports.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import pprint
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_DEFAULT_FILTER_KEY = "imported_from"
_DEFAULT_VALUE = "homeworks"
_LARGE_DELETE_THRESHOLD = 10_000
_SAMPLE_SIZE = 10


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _truncate_doc(doc: Dict[str, Any], max_len: int = 160) -> Dict[str, Any]:
    """Shallow-truncate long string fields for the operator's
    sanity-check printout.  Non-destructive — returns a NEW dict,
    never mutates the live Mongo doc."""
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if isinstance(v, str) and len(v) > max_len:
            out[k] = v[:max_len] + f"…[+{len(v) - max_len} chars]"
        else:
            out[k] = v
    return out


def _build_logger(stamp: str) -> logging.Logger:
    log_path = Path.cwd() / f"delete_homeworks_jobs_{stamp}.log"
    logger = logging.getLogger("delete_homeworks_jobs")
    logger.setLevel(logging.INFO)
    # Clear handlers so repeated main() calls in tests don't
    # accumulate.
    logger.handlers.clear()
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    fh = logging.FileHandler(log_path)
    fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
    logger.addHandler(sh)
    logger.addHandler(fh)
    logger.propagate = False
    logger._log_path = log_path  # type: ignore[attr-defined]
    return logger


def _resolve_env(logger: logging.Logger) -> Dict[str, str]:
    missing: List[str] = []
    env: Dict[str, str] = {}
    for key in ("MONGO_URI", "MONGO_DB_NAME", "TENANT_ID"):
        v = (os.environ.get(key) or "").strip()
        if not v:
            missing.append(key)
        env[key] = v
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        logger.error(
            "Set them before running — this script refuses a "
            "global sweep.  See the module docstring for an "
            "example invocation.",
        )
        sys.exit(2)
    return env


def _confirm_interactive(logger: logging.Logger, stdin=sys.stdin) -> bool:
    """Operator must type the literal word ``yes`` to proceed."""
    logger.info(
        "Type exactly ``yes`` (no quotes) to confirm the delete "
        "or anything else to abort:",
    )
    try:
        reply = stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        reply = ""
    if reply != "yes":
        logger.warning(
            "Confirmation not received (got %r). Aborting.", reply,
        )
        return False
    logger.info("Confirmation accepted.")
    return True


def _snapshot_rows(rows: List[Dict[str, Any]], stamp: str,
                     tenant_id: str, logger: logging.Logger) -> Path:
    out = Path.cwd() / f"homeworks_backup_{tenant_id}_{stamp}.json"
    # BSON ObjectId / datetime are not natively JSON-serializable
    # on the operator's machine; stringify unknown types via
    # ``default=str`` to keep the backup lossless-at-string-level.
    with out.open("w", encoding="utf-8") as f:
        json.dump(rows, f, default=str, indent=2)
    logger.info("Snapshot written: %s (%d rows)", out, len(rows))
    return out


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Delete Homeworks-imported jobs for a single tenant. "
            "Dry-run by default."
        ),
    )
    p.add_argument(
        "--apply", action="store_true",
        help=("Actually delete.  Without this flag the script "
              "only reports counts + sample (dry-run)."),
    )
    p.add_argument(
        "--filter-key", default=_DEFAULT_FILTER_KEY,
        help=(f"Mongo field whose value marks a Homeworks "
              f"import.  Default: {_DEFAULT_FILTER_KEY!r}."),
    )
    p.add_argument(
        "--value", default=_DEFAULT_VALUE,
        help=(f"Expected value on --filter-key for a Homeworks "
              f"row.  Default: {_DEFAULT_VALUE!r}."),
    )
    p.add_argument(
        "--force-large", action="store_true",
        help=(f"Allow a delete larger than "
              f"{_LARGE_DELETE_THRESHOLD:,} docs.  Refused "
              f"otherwise."),
    )
    p.add_argument(
        "--collection", default="jobs",
        help="Mongo collection name.  Default: 'jobs'.",
    )
    return p


def main(argv: Optional[List[str]] = None,
          *, mongo_client_factory=None, stdin=None) -> int:
    """Entry point — returns a POSIX exit code.

    Parameters
    ----------
    argv : list[str] | None
        CLI argv override (test seams).  Falls back to
        ``sys.argv[1:]``.
    mongo_client_factory : callable | None
        Returns a configured ``pymongo.MongoClient`` for the
        passed URI.  Test seam — the production invocation uses
        the real ``pymongo.MongoClient`` via a late import so
        this module stays importable without pymongo installed.
    stdin : file-like | None
        Interactive-confirm stdin override.  Falls back to
        ``sys.stdin``.
    """
    args = _build_arg_parser().parse_args(argv)
    stamp = _now_stamp()
    logger = _build_logger(stamp)

    logger.info("=" * 60)
    logger.info("Homeworks job delete script · stamp=%s", stamp)
    logger.info("=" * 60)

    env = _resolve_env(logger)
    tenant_id = env["TENANT_ID"]

    if args.apply and not tenant_id:
        # Defensive — _resolve_env already exits on empty, but
        # make the invariant explicit at the apply gate.
        logger.error("Cannot --apply without TENANT_ID.  Aborting.")
        return 2

    filt = {"tenant_id": tenant_id, args.filter_key: args.value}
    logger.info("Resolved config:")
    logger.info("  MONGO_DB_NAME : %s", env["MONGO_DB_NAME"])
    logger.info("  TENANT_ID     : %s", tenant_id)
    logger.info("  collection    : %s", args.collection)
    logger.info("  filter        : %s", filt)
    logger.info("  mode          : %s",
                 "APPLY (destructive)" if args.apply else "dry-run")

    # Late import so this module stays unit-testable without
    # pymongo installed on the test host.
    if mongo_client_factory is None:
        try:
            from pymongo import MongoClient
        except ImportError:
            logger.error(
                "pymongo is required.  Install with: "
                "pip install pymongo",
            )
            return 2
        client = MongoClient(env["MONGO_URI"])
    else:
        client = mongo_client_factory(env["MONGO_URI"])

    try:
        db = client[env["MONGO_DB_NAME"]]
        coll = db[args.collection]

        count = coll.count_documents(filt)
        logger.info("Matching document count: %d", count)
        if count == 0:
            logger.info("Nothing to do.  Exiting.")
            return 0

        sample = list(coll.find(filt).limit(_SAMPLE_SIZE))
        logger.info("Sample (first %d rows):", min(_SAMPLE_SIZE, count))
        for row in sample:
            logger.info(pprint.pformat(_truncate_doc(row)))

        if not args.apply:
            logger.info("Dry-run complete.  Re-run with --apply "
                         "to execute the delete.")
            return 0

        # Apply path from here.
        if count > _LARGE_DELETE_THRESHOLD and not args.force_large:
            logger.error(
                "Refusing to delete %d docs (threshold %d) "
                "without --force-large.",
                count, _LARGE_DELETE_THRESHOLD,
            )
            return 3

        if not _confirm_interactive(logger, stdin=stdin or sys.stdin):
            return 1

        # Full snapshot BEFORE delete — the only recovery path.
        all_rows = list(coll.find(filt))
        backup_path = _snapshot_rows(all_rows, stamp, tenant_id, logger)

        logger.info("Executing delete_many…")
        res = coll.delete_many(filt)
        logger.info("delete_many deleted_count = %d", res.deleted_count)

        logger.info("=" * 60)
        logger.info("Summary")
        logger.info("  filter         : %s", filt)
        logger.info("  count removed  : %d", res.deleted_count)
        logger.info("  backup file    : %s", backup_path)
        logger.info("  log file       : %s",
                     getattr(logger, "_log_path", "<stdout>"))
        logger.info("=" * 60)
        return 0
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
