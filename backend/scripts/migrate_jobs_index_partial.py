"""Feb-2026 · P0 · Migrate db.jobs recurring-template index.

Drops the legacy ``recurring_template_id_1_scheduled_date_1`` index
(created with ``unique=True, sparse=True``) and recreates it as a
partial unique index that only covers documents where
``recurring_template_id`` is present and non-null.

Root cause: sparse on a compound index still indexes documents that
have any of the indexed keys. Because every job has ``scheduled_date``,
every non-recurring job (``recurring_template_id: null``) was indexed
under a synthetic null bucket. A second non-recurring job on the same
date collided with the unique constraint → 500 with ``E11000``.

Idempotent: safe to re-run. If the index is already partial, nothing
happens.

Usage::

    cd /app/backend && python -m scripts.migrate_jobs_index_partial

or from any Python shell::

    from scripts.migrate_jobs_index_partial import run
    await run()
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict

# Allow ``python scripts/migrate_jobs_index_partial.py`` from repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from config import db, logger  # noqa: E402

INDEX_NAME = "recurring_template_id_1_scheduled_date_1"
# MongoDB `partialFilterExpression` only supports equality, `$exists: true`,
# `$gt/$gte/$lt/$lte`, `$type`, `$and`, `$or`. `$ne` / `$not` are rejected
# with ``CannotCreateIndex``. Since `recurring_template_id` is always a
# string uuid when set, `$type: "string"` cleanly excludes both null and
# missing values.
PARTIAL_FILTER = {"recurring_template_id": {"$type": "string"}}


async def run() -> Dict[str, Any]:
    info = await db.jobs.index_information()
    existing = info.get(INDEX_NAME)
    dropped = False
    created = False
    already_partial = False
    if existing is not None and existing.get("partialFilterExpression"):
        already_partial = True
    else:
        if existing is not None:
            try:
                await db.jobs.drop_index(INDEX_NAME)
                dropped = True
                logger.info(
                    "[migrate_jobs_index_partial] dropped legacy "
                    f"sparse-unique index {INDEX_NAME}"
                )
            except Exception as e:
                logger.warning(
                    f"[migrate_jobs_index_partial] drop failed: {e}"
                )
        await db.jobs.create_index(
            [("recurring_template_id", 1), ("scheduled_date", 1)],
            unique=True,
            partialFilterExpression=PARTIAL_FILTER,
            name=INDEX_NAME,
        )
        created = True
        logger.info(
            "[migrate_jobs_index_partial] created partial-unique "
            f"{INDEX_NAME} filter={PARTIAL_FILTER}"
        )
    result = {
        "index_name": INDEX_NAME,
        "already_partial": already_partial,
        "dropped_legacy": dropped,
        "created_partial": created,
    }
    print(result)
    return result


if __name__ == "__main__":
    asyncio.run(run())
