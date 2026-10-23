"""TD-offline-bundle-quotes-index · Feb-2026 — ``quotes.(tenant_id, doc_type, updated_at DESC)`` compound index.

Phase 0 recon (``memory/td_offline_bundle_perf_recon.md`` section 3)
identified this index as missing.  The ``GET /api/mobile/offline-bundle``
handler issues two ``db.quotes.find(filter).sort("updated_at", -1).limit(N)``
queries — one for ``doc_type=invoice`` capped at 500 rows, one for
``doc_type=quote`` capped at 200.  Without a covering compound on
``(tenant_id, doc_type, updated_at DESC)``, Mongo falls back to a
``tenant_id`` IXSCAN followed by an in-memory sort stage.  On a mature
tenant with tens of thousands of historical invoices this is the
secondary wedge (~15-20 %) in the slow-request budget after Lane A's
``asyncio.gather`` land.

Index shape rationale:

* ``tenant_id`` ASC first — all offline-bundle queries filter by tenant.
* ``doc_type`` ASC second — distinguishes the invoice and quote slices.
* ``updated_at`` DESC third — matches the sort order so Mongo can walk
  the index backwards and short-circuit at ``limit(N)``.

**Operator requested overnight run window.  Deploy during low-traffic
hours** so the background build doesn't contend with peak read load.
The ``background=True`` kwarg below keeps the collection online during
the build, but on very large tenants the build can still consume
cluster CPU and page-cache budget.

Idempotent — ``create_index`` on an existing identical spec is a safe
Mongo no-op; the sentinel row in ``_migrations`` tracks the rollout
date per deployment.  The companion test suite
(``backend/tests/test_td_offline_bundle_quotes_index.py``) proves this
by invoking ``run()`` twice against a test-local DB and asserting the
index exists exactly once + the sentinel is stamped.

Lane B tracker:
    memory/TECH_DEBT.md TD-offline-bundle-quotes-index
Phase 0 recon:
    memory/td_offline_bundle_perf_recon.md section 3 + 6 Lane B
Companion ship:
    Lane A (``asyncio.gather`` of 9 post-jobs queries) — BE 4f7892489
    Lane D (120 s per-tenant TTL cache) — ships this cycle under
            TD-offline-bundle-tenant-cache
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from config import db


_SENTINEL_ID = "quotes_tenant_doctype_updated_at_desc_index_v1"
_INDEX_NAME = "tenant_doctype_updated_at_desc"
_INDEX_SPEC = [("tenant_id", 1), ("doc_type", 1), ("updated_at", -1)]
logger = logging.getLogger(_SENTINEL_ID)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _already_ran() -> bool:
    row = await db["_migrations"].find_one({"id": _SENTINEL_ID})
    return bool(row and row.get("completed_at"))


async def _mark_complete(stats: Dict[str, Any]) -> None:
    await db["_migrations"].update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": _iso_now(),
            "stats": stats,
        }},
        upsert=True,
    )


async def run(*, force: bool = False, _db: Any = None) -> Dict[str, Any]:
    """Create the compound index on
    ``quotes.(tenant_id, doc_type, updated_at DESC)`` with
    ``background=True`` and stamp the ``_migrations`` sentinel.

    * ``force=True`` re-stamps the sentinel but does NOT drop + recreate
      the index — ``create_index`` on an already-identical spec is a safe
      no-op in Mongo so re-running is cheap.
    * ``_db`` injection point for pytest; defaults to the module-level
      ``config.db`` handle.
    * Return shape: ``{"created": True|False, "sentinel":
      "stamped"|"present", "name": <index name>, "background": True}``.
    """
    target_db = _db if _db is not None else db

    if not force and await target_db["_migrations"].find_one(
            {"id": _SENTINEL_ID}) and \
            (await target_db["_migrations"].find_one(
                {"id": _SENTINEL_ID})).get("completed_at"):
        return {"created": False, "sentinel": "present",
                "name": _INDEX_NAME, "background": True}

    try:
        await target_db.quotes.create_index(
            _INDEX_SPEC,
            name=_INDEX_NAME,
            background=True,
        )
        created = True
    except Exception as exc:    # noqa: BLE001
        logger.warning(
            "[migration] %s create_index failed (likely spec mismatch "
            "on existing name): %s", _SENTINEL_ID, exc,
        )
        created = False

    await target_db["_migrations"].update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": _iso_now(),
            "stats": {"index_name": _INDEX_NAME, "created": created,
                      "background": True},
        }},
        upsert=True,
    )
    return {"created": created, "sentinel": "stamped",
            "name": _INDEX_NAME, "background": True}
