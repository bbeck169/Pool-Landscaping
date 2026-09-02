"""Phase K15 · Feb-2026 — one-shot Mongo-index seed for ``db.jobs``.

Creates the two indexes identified by the K15 RCA of the mobile
Schedule screen latency:

  1. ``k15_jobs_tech_schedule_status``
     — ``(tenant_id ASC, technician_id ASC, scheduled_date ASC, status ASC)``
     — covers the admin/tech schedule list queries filtered by tech
       + date-range + status (the dominant mobile Schedule read).
  2. ``k15_jobs_crew_schedule``
     — ``(tenant_id ASC, crew_id ASC, scheduled_date ASC)``
     — covers the crew-filter schedule reads introduced in Feb-2026
       Crew Phase A.

Design notes:
  * Dry-run by default.  ``--apply`` performs the writes.  Follows
    the same pattern as K9 (``k9_seed_aquaterra_admin_sms.py``) and
    K8 (``k8_backfill_chat_sender_names.py``): idempotent, standalone,
    NOT wired into any boot pipeline.
  * ``pymongo.create_index(..., background=True)`` is idempotent: if
    an index with the exact keys+options already exists it is a no-op.
    We check ``list_indexes()`` first so we can report a clean
    ``already_present`` in the output rather than a silent skip.
  * ``--tenant-id`` is accepted for parity with other seed scripts
    but is a no-op — Mongo indexes are collection-global, and the
    ``tenant_id`` prefix in each key already scopes reads.
  * ``--verify`` lists every current index on ``db.jobs`` and
    highlights whether the two K15 indexes are present.

Invocation:

    # Dry-run (default) — no writes:
    python -m scripts.k15_seed_jobs_indexes

    # Apply on prod (ops):
    python -m scripts.k15_seed_jobs_indexes --apply

    # Post-apply verification:
    python -m scripts.k15_seed_jobs_indexes --verify
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple

from dotenv import load_dotenv


# Ordered so the dry-run + apply output is stable.
_K15_INDEXES: List[Tuple[str, List[Tuple[str, int]]]] = [
    (
        "k15_jobs_tech_schedule_status",
        [("tenant_id", 1), ("technician_id", 1),
         ("scheduled_date", 1), ("status", 1)],
    ),
    (
        "k15_jobs_crew_schedule",
        [("tenant_id", 1), ("crew_id", 1), ("scheduled_date", 1)],
    ),
]


def _env_db():
    """Load ``.env`` and return a synchronous pymongo ``db`` handle.

    Kept sync (pymongo) — this script is invoked ad-hoc by ops, not
    inside the FastAPI event loop.  Motor's async surface would add
    zero value here and force an extra ``asyncio.run`` boundary.
    """
    load_dotenv("/app/backend/.env")
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


def _existing_index_names(db) -> set[str]:
    """Return the set of existing index NAMES on ``db.jobs``.

    Keyed on name (not on the key spec) because ``create_index`` is
    the sole path here and it always names the index explicitly, so
    a name collision is a strict equivalent to "same index exists".
    """
    return {idx["name"] for idx in db.jobs.list_indexes()}


def _run_seed(db, *, apply: bool) -> int:
    """Emit ``[k15] <name> — <status>`` lines for each K15 index.

    Status semantics:
      * ``would_create`` — dry-run, index missing.
      * ``already_present`` — index name already on the collection
        (both dry-run and apply).
      * ``created`` — apply path, index name absent before, present
        after.
    """
    existing = _existing_index_names(db)
    exit_code = 0
    for name, keys in _K15_INDEXES:
        if name in existing:
            print(f"[k15] {name} — already_present")
            continue
        if not apply:
            print(f"[k15] {name} — would_create")
            continue
        # Apply path — ``create_index`` is idempotent, we already
        # know the name is missing so we always expect ``created``.
        try:
            db.jobs.create_index(keys, name=name, background=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[k15] {name} — error: {type(exc).__name__}: {exc}")
            exit_code = 2
            continue
        print(f"[k15] {name} — created")
    return exit_code


def _run_verify(db) -> int:
    """List every index on ``db.jobs`` with a visual marker for the
    two K15 indexes.  Exit non-zero when either K15 index is missing
    so ops runbooks can fail-fast in CI."""
    existing = list(db.jobs.list_indexes())
    k15_names = {name for name, _ in _K15_INDEXES}
    print("[k15-verify] current indexes on db.jobs:")
    for idx in existing:
        name = idx["name"]
        marker = "  "
        if name in k15_names:
            marker = "✅"
        keys = list(idx.get("key", {}).items())
        print(f"[k15-verify] {marker} {name} — {keys}")
    missing = k15_names - {idx["name"] for idx in existing}
    if missing:
        for name in sorted(missing):
            print(f"[k15-verify] ❌ MISSING — {name}")
        return 1
    print("[k15-verify] all K15 indexes present.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase K15 · Feb-2026 — seed the two Mongo indexes required "
            "for the mobile Schedule screen fast-path. Dry-run by default."
        ),
    )
    parser.add_argument("--apply", action="store_true",
                         help="Persist. Default is a dry-run.")
    parser.add_argument("--tenant-id", default=None,
                         help=("Accepted for parity with other seed scripts;"
                               " indexes are collection-global so this is a"
                               " no-op."))
    parser.add_argument("--verify", action="store_true",
                         help=("List every current index on db.jobs and"
                               " highlight whether the K15 indexes are"
                               " present. Exits 1 if any K15 index is"
                               " missing."))
    args = parser.parse_args(argv)

    db = _env_db()
    if args.verify:
        return _run_verify(db)
    return _run_seed(db, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
