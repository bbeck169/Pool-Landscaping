"""P1 PERF-HOTFIX · Feb-2026 — Customer-profile mount index safety net.

Boot-time, idempotent, sentinel-guarded migration that pins the 8
critical indexes consumed by the admin customer-profile page
(``frontend/src/pages/customers/CustomerDetail.jsx``) mount. The
audit (ref: PERF-HOTFIX audit, Feb-2026) confirmed every target
is already present on the preview DB — this migration exists
purely as a prod safety net: if any shard / replica is missing a
compound, a boot creates it in the background; if all 8 are
present (the preview case + the expected prod case), the sentinel
row is written and future boots short-circuit.

Pattern mirrors ``services/migrations/k65_service_reports_indexes.py``
— same ``index_information`` scan, same "already covered by prefix"
detection, same sentinel key under ``db.migrations``.

Target index catalogue (collection → key spec → fallback name)
-------------------------------------------------------------
  jobs            [(tenant_id,1),(customer_id,1),(scheduled_date,-1)]
                  pcpm_jobs_tenant_customer_sched_desc
  jobs            [(tenant_id,1),(customer_id,1),(created_at,-1)]
                  pcpm_jobs_tenant_customer_created_desc
  quotes          [(tenant_id,1),(customer_id,1),(doc_type,1),
                   (created_at,-1)]
                  pcpm_quotes_tenant_customer_doctype_created_desc
  quotes          [(tenant_id,1),(customer_id,1),(status,1)]
                  pcpm_quotes_tenant_customer_status
  properties      [(tenant_id,1),(customer_id,1)]
                  pcpm_properties_tenant_customer
  service_reports [(tenant_id,1),(customer_id,1),(submitted_at,-1)]
                  pcpm_service_reports_tenant_customer_submitted_desc
  messages        [(tenant_id,1),(customer_id,1),(sender,1),
                   (read_by_staff,1)]
                  pcpm_messages_tenant_customer_sender_read
  customers       [(tenant_id,1),(id,1)]
                  pcpm_customers_tenant_id

"Already covered" semantics
---------------------------
For each target shape, the migration counts an existing index as
covering IFF the existing index's key list STARTS WITH the target
key list in order. Direction mismatch on a sort-field counts as
NOT covered — MongoDB can walk an index backwards for a single-
field sort reversal, but compound sorts need the directions to
align, so we treat direction-mismatch as a conservative miss.
Any name/direction match is accepted — a direct target-name
match is reported as ``already_present``.

Sentinel: ``pcpm_customer_profile_mount_v1`` under ``db.migrations``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db


logger = logging.getLogger("perf_customer_profile_mount_migration")

_SENTINEL_ID = "pcpm_customer_profile_mount_v1"


# Each entry: (collection, fallback_name, key_spec).
# Order within the list is stable so the log output is deterministic.
_TARGETS: List[Tuple[str, str, List[Tuple[str, int]]]] = [
    ("jobs",
     "pcpm_jobs_tenant_customer_sched_desc",
     [("tenant_id", 1), ("customer_id", 1), ("scheduled_date", -1)]),
    ("jobs",
     "pcpm_jobs_tenant_customer_created_desc",
     [("tenant_id", 1), ("customer_id", 1), ("created_at", -1)]),
    ("quotes",
     "pcpm_quotes_tenant_customer_doctype_created_desc",
     [("tenant_id", 1), ("customer_id", 1),
      ("doc_type", 1), ("created_at", -1)]),
    ("quotes",
     "pcpm_quotes_tenant_customer_status",
     [("tenant_id", 1), ("customer_id", 1), ("status", 1)]),
    ("properties",
     "pcpm_properties_tenant_customer",
     [("tenant_id", 1), ("customer_id", 1)]),
    ("service_reports",
     "pcpm_service_reports_tenant_customer_submitted_desc",
     [("tenant_id", 1), ("customer_id", 1), ("submitted_at", -1)]),
    ("messages",
     "pcpm_messages_tenant_customer_sender_read",
     [("tenant_id", 1), ("customer_id", 1),
      ("sender", 1), ("read_by_staff", 1)]),
    ("customers",
     "pcpm_customers_tenant_id",
     [("tenant_id", 1), ("id", 1)]),
]


async def _sentinel_row() -> Optional[Dict[str, Any]]:
    return await db.migrations.find_one(
        {"id": _SENTINEL_ID}, {"_id": 0},
    )


async def _write_sentinel(summary: Dict[str, Any]) -> None:
    await db.migrations.update_one(
        {"id": _SENTINEL_ID},
        {"$set": {
            "id": _SENTINEL_ID,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
        }},
        upsert=True,
    )


def _prefix_covers(
    existing_key: List[Tuple[str, int]],
    target_key: List[Tuple[str, int]],
) -> bool:
    """True when ``existing_key`` starts with ``target_key`` in
    order with matching directions.  Conservative on direction
    mismatch — compound sorts need directions to align with the
    index.
    """
    if not existing_key or len(existing_key) < len(target_key):
        return False
    for i, (field, direction) in enumerate(target_key):
        try:
            ex_field, ex_dir = existing_key[i][0], int(existing_key[i][1])
        except (IndexError, TypeError, ValueError):
            return False
        if ex_field != field or ex_dir != int(direction):
            return False
    return True


async def run_perf_customer_profile_mount_migration(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Create the 8 customer-profile mount indexes unless an
    existing index already covers each shape.

    Returns::

        {"status": "ok" | "skipped",
         "summary": {
             "created": <int>,
             "already_present": <int>,
             "already_covered_by_prefix": <int>,
             "errors": [...],
             "targets": [{"collection", "index", "status",
                          "covered_by"?}],
         }}
    """
    if not force:
        sentinel = await _sentinel_row()
        if sentinel:
            return {
                "status": "skipped",
                "reason": "sentinel_present",
                "sentinel": sentinel,
            }

    summary: Dict[str, Any] = {
        "created": 0,
        "already_present": 0,
        "already_covered_by_prefix": 0,
        "errors": [],
        "targets": [],
    }

    # Cache per-collection ``index_information`` so we don't hit
    # ``listIndexes`` multiple times for repeat-target collections
    # (jobs + quotes each have two targets).
    info_cache: Dict[str, Dict[str, List[Tuple[str, int]]]] = {}

    async def _info(coll_name: str) -> Dict[str, List[Tuple[str, int]]]:
        if coll_name in info_cache:
            return info_cache[coll_name]
        try:
            raw = await db[coll_name].index_information()
            parsed: Dict[str, List[Tuple[str, int]]] = {}
            for n, meta in raw.items():
                parsed[n] = list(meta.get("key") or [])
            info_cache[coll_name] = parsed
            return parsed
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(
                {"stage": "list_indexes",
                 "collection": coll_name, "error": str(exc)},
            )
            logger.warning(
                "[pcpm] index_information(%s) failed: %s",
                coll_name, exc,
            )
            info_cache[coll_name] = {}
            return info_cache[coll_name]

    for coll_name, idx_name, keys in _TARGETS:
        target_result: Dict[str, Any] = {
            "collection": coll_name, "index": idx_name,
        }
        try:
            existing = await _info(coll_name)
            # Direct target-name match → already present.
            if idx_name in existing:
                target_result["status"] = "already_present"
                summary["already_present"] += 1
            else:
                # Scan for a prefix-covering compound under a
                # different name.
                covered_by: Optional[str] = None
                for ex_name, ex_keys in existing.items():
                    if _prefix_covers(ex_keys, keys):
                        covered_by = ex_name
                        break
                if covered_by is not None:
                    target_result["status"] = "already_covered_by_prefix"
                    target_result["covered_by"] = covered_by
                    summary["already_covered_by_prefix"] += 1
                    logger.info(
                        "[pcpm] %s.%s skipped — covered by prefix of %s",
                        coll_name, idx_name, covered_by,
                    )
                else:
                    await db[coll_name].create_index(
                        keys, name=idx_name, background=True,
                    )
                    target_result["status"] = "created"
                    summary["created"] += 1
                    logger.info(
                        "[pcpm] created %s.%s %s",
                        coll_name, idx_name, keys,
                    )
        except Exception as exc:  # noqa: BLE001
            target_result["status"] = "error"
            target_result["error"] = str(exc)
            summary["errors"].append(target_result)
            logger.warning(
                "[pcpm] %s.%s create_index failed: %s",
                coll_name, idx_name, exc,
            )
        summary["targets"].append(target_result)

    if not summary["errors"]:
        await _write_sentinel(summary)

    logger.info(
        "[pcpm] created=%s already_present=%s "
        "already_covered_by_prefix=%s errors=%s",
        summary["created"], summary["already_present"],
        summary["already_covered_by_prefix"], len(summary["errors"]),
    )
    return {"status": "ok", "summary": summary}
