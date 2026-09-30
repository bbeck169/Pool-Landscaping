"""Feb-2026 · delete_duplicate_jobs.py — SOFT-DELETE cleanup workflow.

The mutation half of the duplicate-jobs dedup workflow.  Reads a
CSV produced by ``preview_duplicate_jobs.py`` (same dir), verifies
the safety rails, then either DRY-RUNs the plan or applies deletes.

Workflow (spec):
  1. Operator runs ``preview_duplicate_jobs.py`` → CSV.
  2. Operator prunes the CSV to the rows they want deleted (leaves
     the ``action=CANDIDATE_DELETE`` rows they approve, drops the
     KEEP rows + any CANDIDATE they want to spare).
  3. Operator runs THIS script against the pruned CSV.  Without
     ``--confirm`` the script prints a DRY-RUN plan and exits 0.
     With ``--confirm`` it applies the delete (soft by default,
     hard when ``--hard`` is also passed).

Safety rails (spec):
  * ``deleted_at`` already-set rows in input → skipped with warning.
  * Any ``action=KEEP`` row in input → refuse to run.
  * >100 candidates in input → refuse to run.
  * Masked ``MONGO_URL`` (host + db only, no creds) printed on
    startup so the operator sees WHICH environment they're hitting.
  * Groups deletes by ``tenant_id`` for per-tenant audit trails.

Safe usage
----------
  # DRY-RUN — mandatory first pass
  python -m scripts.delete_duplicate_jobs \\
    --input ./tmp/prod_dedup_preview.csv

  # Actually apply (soft-delete by default)
  python -m scripts.delete_duplicate_jobs \\
    --input ./tmp/prod_dedup_preview.csv \\
    --confirm

  # Actually apply (hard-delete — use only when a full audit is
  # separately captured)
  python -m scripts.delete_duplicate_jobs \\
    --input ./tmp/prod_dedup_preview.csv \\
    --confirm --hard
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


MAX_DELETES_PER_INVOCATION = 100
DELETED_BY = "cleanup_script"


# ═════════════════════════════════════════════════════════════════
# Environment mask — never leak credentials
# ═════════════════════════════════════════════════════════════════
_CREDS_RX = re.compile(r"://([^:@/]+)(:([^@/]+))?@")


def mask_mongo_url(url: Optional[str]) -> str:
    """Strip the ``user:pass@`` block from a Mongo connection
    string.  Leaves scheme, host, port, and db intact so the
    operator can visually confirm which cluster they're hitting."""
    if not url:
        return "<no MONGO_URL set>"
    return _CREDS_RX.sub("://***:***@", url)


# ═════════════════════════════════════════════════════════════════
# CSV loading + safety validation
# ═════════════════════════════════════════════════════════════════
def load_candidates(csv_path: str) -> List[Dict[str, str]]:
    """Load rows from the preview CSV.  No filtering — caller
    validates safety after."""
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


class SafetyError(RuntimeError):
    """Raised when the input CSV fails a hard safety check.  The
    CLI catches this and prints the message before exiting 2 —
    never let the operator run past a violation."""


def validate_input(rows: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]],
                                                          List[Dict[str, str]]]:
    """Split rows into ``(to_delete, skipped_already_deleted)``.
    Raises ``SafetyError`` if the input contains KEEP rows or too
    many candidates.  Rows with a non-empty ``deleted_at`` value
    are silently pulled into ``skipped_already_deleted`` and the
    caller logs a warning per row."""
    keep_rows = [r for r in rows if (r.get("action") or "").strip() == "KEEP"]
    if keep_rows:
        raise SafetyError(
            f"Input contains {len(keep_rows)} row(s) with action=KEEP.  "
            "Filter the CSV to CANDIDATE_DELETE rows only before running."
        )

    candidates = [
        r for r in rows
        if (r.get("action") or "").strip() == "CANDIDATE_DELETE"
    ]
    if len(candidates) > MAX_DELETES_PER_INVOCATION:
        raise SafetyError(
            f"Input contains {len(candidates)} candidate deletes; "
            f"cap is {MAX_DELETES_PER_INVOCATION} per invocation.  "
            "Split the CSV into smaller batches before running."
        )

    to_delete: List[Dict[str, str]] = []
    already_deleted: List[Dict[str, str]] = []
    for r in candidates:
        if (r.get("deleted_at") or "").strip():
            already_deleted.append(r)
        else:
            to_delete.append(r)
    return to_delete, already_deleted


# ═════════════════════════════════════════════════════════════════
# Delete execution — injectable ``db`` for tests
# ═════════════════════════════════════════════════════════════════
def apply_deletes(db, rows: List[Dict[str, str]], *, hard: bool,
                  now: Optional[datetime] = None,
                  ) -> Dict[str, Any]:
    """Apply the delete to every row.  Groups the summary by
    ``tenant_id`` for a per-tenant audit line.  Returns:

        {
          "successes":  int,
          "failures":   int,
          "per_tenant": {tenant_id: {"success": int, "failure": int}},
          "failure_details": [{job_id, tenant_id, error}, …],
        }
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    per_tenant: Dict[str, Dict[str, int]] = {}
    failure_details: List[Dict[str, str]] = []
    successes = 0
    failures = 0

    for r in rows:
        job_id = (r.get("job_id") or "").strip()
        tenant_id = (r.get("tenant_id") or "").strip()
        bucket = per_tenant.setdefault(tenant_id, {"success": 0, "failure": 0})
        if not job_id:
            failures += 1
            bucket["failure"] += 1
            failure_details.append({
                "job_id": "", "tenant_id": tenant_id,
                "error": "empty job_id in CSV row",
            })
            continue
        try:
            filt = {"id": job_id}
            if tenant_id:
                # Tenant-scope the delete so a copy-paste to the
                # wrong environment can't nuke a matching job_id
                # in an unrelated tenant.
                filt["tenant_id"] = tenant_id
            if hard:
                res = db.jobs.delete_one(filt)
                ok = getattr(res, "deleted_count", 0) >= 1
            else:
                res = db.jobs.update_one(filt, {"$set": {
                    "deleted_at": ts, "deleted_by": DELETED_BY,
                }})
                ok = getattr(res, "matched_count", 0) >= 1
            if ok:
                successes += 1
                bucket["success"] += 1
            else:
                failures += 1
                bucket["failure"] += 1
                failure_details.append({
                    "job_id": job_id, "tenant_id": tenant_id,
                    "error": "no matching document",
                })
        except Exception as e:  # noqa: BLE001 — Mongo can raise anything
            failures += 1
            bucket["failure"] += 1
            failure_details.append({
                "job_id": job_id, "tenant_id": tenant_id,
                "error": f"{type(e).__name__}: {e}",
            })
    return {
        "successes":       successes,
        "failures":        failures,
        "per_tenant":      per_tenant,
        "failure_details": failure_details,
    }


# ═════════════════════════════════════════════════════════════════
# Reporting
# ═════════════════════════════════════════════════════════════════
def _print_plan(rows: List[Dict[str, str]], skipped: List[Dict[str, str]],
                *, out=None) -> None:
    # Resolve ``sys.stdout`` at call time so pytest's ``capsys``
    # (which swaps ``sys.stdout`` after import) captures the output.
    if out is None:
        out = sys.stdout
    for r in rows:
        out.write(
            f"  · [{r.get('tenant_id') or '<no tenant>'}] "
            f"job={r.get('job_id')} · sched={r.get('scheduled_date')} · "
            f"title={r.get('title')!r} · customer={r.get('customer_name')}\n"
        )
    for r in skipped:
        out.write(
            f"  · SKIP (already deleted_at={r.get('deleted_at')}): "
            f"job={r.get('job_id')} · customer={r.get('customer_name')}\n"
        )


def _print_summary(result: Dict[str, Any], *, out=None) -> None:
    if out is None:
        out = sys.stdout
    out.write("\nPer-tenant summary\n")
    for tenant_id, counts in sorted(result["per_tenant"].items()):
        out.write(
            f"  · tenant={tenant_id or '<none>'} · "
            f"success={counts['success']} · failure={counts['failure']}\n"
        )
    out.write(
        f"\nTotal: {result['successes']} deleted, {result['failures']} failed.\n"
    )
    for fd in result["failure_details"]:
        out.write(
            f"  ! FAILED job={fd['job_id']} tenant={fd['tenant_id']}: "
            f"{fd['error']}\n"
        )


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="delete_duplicate_jobs",
        description=(
            "Apply duplicate-jobs deletes from a preview CSV.  "
            "Mandatory --confirm flag; --hard optional (default "
            "soft-delete via deleted_at + deleted_by)."
        ),
    )
    p.add_argument("--input", required=True, help="Path to preview CSV.")
    p.add_argument("--confirm", action="store_true",
                   help="Actually apply the delete.  Without this "
                        "flag the script exits after printing the plan.")
    p.add_argument("--hard", action="store_true",
                   help="Hard-delete via delete_one().  Default is "
                        "soft-delete (deleted_at timestamp + "
                        f"deleted_by={DELETED_BY!r}).")
    return p


def main(argv: Optional[List[str]] = None, *, db=None,
         mongo_url_env: Optional[str] = None) -> int:
    args = _build_argparser().parse_args(argv)
    print(f"Env target : {mask_mongo_url(mongo_url_env or os.environ.get('MONGO_URL'))}")
    print(f"Db         : {os.environ.get('DB_NAME') or '<no DB_NAME set>'}")
    print(f"Input CSV  : {args.input}")
    print(f"Mode       : {'HARD-DELETE' if args.hard else 'SOFT-DELETE'}"
          f" · confirm={'YES' if args.confirm else 'NO (dry-run)'}")

    try:
        rows = load_candidates(args.input)
    except FileNotFoundError:
        print(f"ERROR: Input CSV not found: {args.input}", file=sys.stderr)
        return 2

    try:
        to_delete, skipped = validate_input(rows)
    except SafetyError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    print(f"\nPlan: {len(to_delete)} delete candidate(s), "
          f"{len(skipped)} skipped (already deleted).\n")
    _print_plan(to_delete, skipped)

    if not args.confirm:
        print("\nDRY RUN — pass --confirm to actually apply.")
        return 0

    if db is None:  # pragma: no cover — real Mongo path exercised by ops
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if not mongo_url or not db_name:
            print("ERROR: MONGO_URL and DB_NAME env vars required.", file=sys.stderr)
            return 2
        db = MongoClient(mongo_url)[db_name]

    result = apply_deletes(db, to_delete, hard=args.hard)
    _print_summary(result)
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
