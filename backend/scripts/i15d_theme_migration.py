#!/usr/bin/env python3
"""Phase I1.5.d · Feb-2026 — Backward-compat tenant theme migration.

Purpose
-------
Since ``GET /api/tenants/me/theme`` already falls back to the
``default`` preset when ``tenant.theme`` is absent, tenants that
never set a theme continue to render pixel-identically to the
pre-I1.5 shell without any DB write. This script is the belt-and-
suspenders companion: it materializes the default preset into
every unset tenant document so future serializer changes / API
consumers that touch ``tenant.theme`` directly (not through the
router) always see a fully-expanded shape.

Contract
--------
* Absent ``tenant.theme`` → write the full expanded ``default``
  preset + ``theme_preset = "default"`` marker + timestamp.
* Present ``tenant.theme`` → **left untouched** (both partial and
  full themes — the operator's persisted work is authoritative).
* Idempotent: a second run touches zero new tenants.
* Every run appends an audit doc to the ``migration_runs``
  collection with ``{run_id, script, started_at, finished_at,
  tenants_scanned, tenants_migrated, tenants_skipped_had_theme,
  errors, dry_run}``.
* ``--dry-run`` flag (or ``DRY_RUN=1`` env var) prints the report
  without mutating any tenant document (still logs an audit doc
  with ``dry_run=True`` for record-keeping — set ``NO_AUDIT=1`` to
  also skip the audit write).

Usage::

    # Report-only:
    cd /app/backend && python3 -m scripts.i15d_theme_migration --dry-run

    # Live:
    cd /app/backend && python3 -m scripts.i15d_theme_migration

Prints a JSON report of the audit doc for CI capture.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv


# Load env before anything imports config (which reads MONGO_URL /
# DB_NAME at import time).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


SCRIPT_NAME = "i15d_theme_migration"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(*, dry_run: bool, write_audit: bool,
                 db=None) -> Dict[str, Any]:
    """Iterate every tenant. For unset ``tenant.theme``, write the
    expanded default preset (unless ``dry_run``). Returns the audit
    doc — the caller decides whether to also persist it into the
    ``migration_runs`` collection.

    ``db`` — Optional motor collection namespace. Defaults to the
    process-wide ``config.db``. Tests inject a per-event-loop
    handle to avoid motor's "attached to a different loop" trap.
    """
    # Late imports so ``load_dotenv`` above runs first.
    if db is None:
        from config import db as _db  # type: ignore[import-not-found]
        db = _db
    from services.theme.presets import get_preset  # type: ignore[import-not-found]

    run_id = uuid.uuid4().hex
    started_at = _now_iso()

    default_theme = get_preset("default")
    # Include the ``preset`` marker on the theme doc itself so
    # consumers can tell "I was auto-migrated" apart from "operator
    # picked default on purpose".
    default_theme["preset"] = "default"

    scanned = 0
    migrated: List[str] = []
    skipped_had_theme = 0
    errors: List[Dict[str, Any]] = []

    async for tenant in db.tenants.find({}, {"id": 1, "theme": 1}):
        scanned += 1
        tid = tenant.get("id")
        if not tid:
            errors.append({
                "code": "TENANT_MISSING_ID",
                "message": f"tenants._id={tenant.get('_id')!r} has no 'id' field.",
            })
            continue
        existing = tenant.get("theme")
        if isinstance(existing, dict) and existing:
            skipped_had_theme += 1
            continue
        if dry_run:
            migrated.append(tid)
            continue
        try:
            await db.tenants.update_one(
                {"id": tid},
                {"$set": {
                    "theme": default_theme,
                    "theme_preset": "default",
                    "theme_migrated_at": _now_iso(),
                    "theme_migrated_by": SCRIPT_NAME,
                }},
            )
            migrated.append(tid)
        except Exception as exc:  # pragma: no cover — defensive
            errors.append({
                "code": "UPDATE_FAILED",
                "tenant_id": tid,
                "message": str(exc),
            })

    finished_at = _now_iso()
    audit: Dict[str, Any] = {
        "run_id": run_id,
        "script": SCRIPT_NAME,
        "started_at": started_at,
        "finished_at": finished_at,
        "tenants_scanned": scanned,
        "tenants_migrated": len(migrated),
        "tenants_skipped_had_theme": skipped_had_theme,
        "migrated_tenant_ids": migrated,
        "errors": errors,
        "dry_run": bool(dry_run),
    }
    if write_audit:
        try:
            # Prevent duplicate-key collisions across parallel runs
            # by keying the audit doc on ``run_id``.
            audit_doc = {**audit, "id": run_id}
            await db.migration_runs.insert_one(audit_doc)
        except Exception as exc:  # pragma: no cover — defensive
            errors.append({
                "code": "AUDIT_WRITE_FAILED",
                "message": str(exc),
            })
    return audit


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                     help="Report only — do not mutate any tenant document.")
    p.add_argument("--no-audit", action="store_true",
                     help="Skip appending an audit doc to migration_runs.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    dry_run = bool(args.dry_run) or os.environ.get("DRY_RUN") == "1"
    write_audit = not (bool(args.no_audit) or os.environ.get("NO_AUDIT") == "1")
    report = asyncio.run(_run(dry_run=dry_run, write_audit=write_audit))
    print(json.dumps(report, indent=2, default=str))
    return 1 if report.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
