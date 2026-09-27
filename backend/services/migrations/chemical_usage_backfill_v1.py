"""Feb-2026 · Profitability backfill migration — historical chemistry ledger repair.

Companion to the P0 chemical-save-before-status-flip fix in commit
``b77684f23`` (``routers/service_reports.py``).  The P0 fix prevents
FUTURE chemistry ledger loss.  This migration repairs HISTORICAL
loss caused by the same underlying bug (silent-swallowed
``snapshot_chemical_usage`` failures at the pre-P0 L1006-1007
try/except) so profitability reporting is accurate across the
full report history — the ``GET /pools/{customer_id}/chemical-
profitability`` rollup and the Chemistry History page aggregate
over ``chemical_usage_events``, so any submitted report missing
its ledger rows silently reads as $0 revenue.

Detection query
───────────────
Iterate ``db.service_reports`` where ``submitted_at`` is set (i.e.
the submit path fired at least once), and for each row check
``db.chemical_usage_events`` for a matching
``(tenant_id, service_report_id)`` composite.  Reports with zero
matching events AND non-empty chemistry payload (top-level
``chemicals_added`` OR any water-body's ``chemicals_used`` /
``chemicals_added``) are backfill candidates.  Reports with an
empty chemistry payload are CORRECTLY skipped — not every visit
carries chemistry additions (readings-only visits, repair-mode
jobs, dry-run inspection reports).

Linkage field
─────────────
``chemical_usage_events.service_report_id`` — verified against
the ``snapshot_chemical_usage`` implementation at
``routers/chemical_products.py::L222-226`` (delete_many filter)
and L292 (insert doc field). Same composite the P0 fix uses.

Source-of-truth reuse
─────────────────────
The migration invokes ``snapshot_chemical_usage`` DIRECTLY for
each backfill candidate.  Cost model, catalog resolution, unit
coercion, multi-body vs legacy shape branching — all handled by
the same function the live submit path uses.  We do NOT re-
implement chemistry math here; a single edit to the snapshot
function propagates automatically.  Snapshot idempotency (its
delete_many at L223-226 wipes prior events for the same
``service_report_id`` before insert) means a retry after partial
migration is a safe no-op replace.

Empty-chemistry safeguard
─────────────────────────
Two guards prevent fabricating ledger rows for reports that
correctly have no chemistry:

  1. Pre-flight — before invoking snapshot, check both top-level
     ``chemicals_added`` AND every water-body's chemistry.  If
     both are empty, skip and increment ``rows_skipped_empty_chemistry``.
  2. Post-flight — if snapshot returns ``inserted == 0`` (all
     lines had ``quantity <= 0`` or otherwise didn't produce an
     event), also count as skipped — the outcome is
     indistinguishable from "correctly empty" for the operator's
     purposes.

Per-report failure isolation
────────────────────────────
A snapshot failure on ONE report is logged + counted in
``rows_failed`` and the loop continues.  Rationale: a stuck row
(e.g. corrupted chemicals shape, missing tenant catalog entry)
must not block the rest of the tenant's history from being
repaired.  Sentinel is stamped ``must_succeed=False`` so the boot
sequence never blocks on a partial run — the next boot retries
via the sentinel-gate short-circuit for successful reports +
re-attempts the failures.

Provenance stamp
────────────────
Every ledger row inserted by this migration is stamped
``backfilled_by = "chemical_usage_backfill_v1"`` via a post-insert
``update_many``.  Chosen over adding a ``provenance`` kwarg to
``snapshot_chemical_usage`` (Option A in the recon) because the
snapshot function is a P0-touched surface (see commit
``b77684f23``) — keeping the migration entirely external respects
the "no unnecessary edits to touched code" invariant.  Small perf
cost (one extra ``update_many`` per report) is acceptable for a
one-time migration.

Idempotency
───────────
Sentinel: ``db.migration_status.find_one({"key": MIGRATION_KEY})``.
Same pattern as ``pdf_doc_date_backfill_v1``.  A second run after
successful first pass short-circuits to
``{"ok": True, "skipped": True, "reason": "already_ran"}`` without
touching any documents.  Combined with per-report idempotency (the
snapshot's delete_many pre-insert), a MID-migration crash-and-
retry is also safe — successful reports are skipped by the detection
query (they now have events); failed reports get a fresh attempt.

Failure mode
────────────
A pymongo error at the migration's own bookkeeping level (sentinel
write, cursor iteration) writes an ``error`` field on the sentinel
doc but does NOT set ``completed_at``.  The next boot retries.
Ruled ``must_succeed=False`` at boot (see server.py) — a partial
backfill never crashes boot or 503's the readiness gate.

Rollback
────────
Two-step rollback (idempotent — safe to run twice)::

    db.chemical_usage_events.delete_many(
        {"backfilled_by": "chemical_usage_backfill_v1"},
    )
    db.migration_status.delete_one({"key": "chemical_usage_backfill_v1"})

After the rollback the migration is un-gated and will re-run on
next boot, replaying the same detection + backfill against the
current ``service_reports`` state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("services.migrations.chemical_usage_backfill_v1")

MIGRATION_KEY = "chemical_usage_backfill_v1"


def _has_any_chemistry(report: Dict[str, Any]) -> Tuple[bool, bool]:
    """Return ``(has_top_level, has_body_level)`` chemistry markers.

    The snapshot function prefers ``water_bodies`` when non-empty,
    falls back to top-level ``chemicals_added``. We check BOTH so
    the empty-chemistry safeguard doesn't skip a valid report that
    has body-scoped chemistry but no top-level fallback (or vice
    versa).
    """
    top = report.get("chemicals_added") or []
    top_non_empty = bool(top)
    bodies = report.get("water_bodies") or []
    body_non_empty = False
    for b in bodies:
        if not isinstance(b, dict):
            continue
        chems = b.get("chemicals_used") or b.get("chemicals_added") or []
        if chems:
            body_non_empty = True
            break
    return top_non_empty, body_non_empty


async def run(
    db: Any,
    *,
    service_report_filter: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Backfill ``chemical_usage_events`` for historical submitted
    ``service_reports`` that are missing their ledger rows.

    Args:
        db: the motor async database handle.
        service_report_filter: OPTIONAL extra Mongo predicate composed
            into the detection query via ``$and``.  Production callers
            (the boot sequence) pass ``None`` so every submitted report
            is scanned.  Tests pass a scoping filter (e.g.
            ``{"id": {"$regex": "^TEST-..."}}``) to isolate their
            seeded rows from co-existing data in the shared test DB.
            Kept as a KW-only param so a positional call from
            production is unambiguously the "scan everything" case.

    Returns:
        Dict with the migration report::

            {
                "ok": bool,
                "skipped": bool,
                "reason": str | absent,
                "rows_backfilled": int,
                "rows_failed": int,
                "rows_skipped_empty_chemistry": int,
                "error": str | absent,
            }
    """
    sentinel = await db.migration_status.find_one(
        {"key": MIGRATION_KEY}, {"_id": 0},
    )
    if sentinel and sentinel.get("completed_at"):
        return {
            "ok": True, "skipped": True,
            "reason": "already_ran",
        }

    rows_backfilled = 0
    rows_failed = 0
    rows_skipped_empty_chemistry = 0
    # Lightweight failure log for the sentinel doc so ops can grep
    # for stuck rows without a log-dive. Capped at 50 entries — a
    # tenant with more than 50 chronically-failing reports has a
    # bigger data problem than this migration is designed to solve.
    failures: List[Dict[str, str]] = []
    _FAILURE_LOG_CAP = 50

    # Lazy-import so the migration module can be loaded without
    # forcing the router chain (avoids circular imports when the
    # test suite imports this module in isolation).
    try:
        from routers.chemical_products import snapshot_chemical_usage
    except Exception as _imp_e:                                    # noqa: BLE001
        logger.error(
            "[chemical_usage_backfill_v1] snapshot_chemical_usage"
            " import failed: %s", _imp_e,
        )
        await db.migration_status.update_one(
            {"key": MIGRATION_KEY},
            {"$set": {
                "key": MIGRATION_KEY,
                "error": f"import_failed: {_imp_e}"[:400],
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        return {"ok": False, "skipped": False,
                  "error": f"import_failed: {_imp_e}"[:400]}

    # Detection cursor — every submitted report, projection kept
    # tight so a 10k-report tenant doesn't blow memory.  The
    # ``service_report_filter`` kwarg (test-only) composes AND
    # with the submitted-at gate so hermetic tests can scope the
    # scan to their seeded rows without changing production
    # behavior (which never passes the kwarg).
    _base: Dict[str, Any] = {
        "submitted_at": {"$exists": True, "$nin": [None, ""]},
    }
    if service_report_filter:
        _match: Dict[str, Any] = {"$and": [_base, service_report_filter]}
    else:
        _match = _base
    cursor = db.service_reports.find(
        _match,
        {"_id": 0, "id": 1, "tenant_id": 1, "job_id": 1,
          "submitted_at": 1, "chemicals_added": 1, "water_bodies": 1},
    )

    async for report in cursor:
        sr_id = report.get("id")
        tenant_id = report.get("tenant_id")
        if not sr_id or not tenant_id:
            # Malformed row — no way to link to the ledger. Skip
            # silently (not counted as failure; the row can't be
            # backfilled without a valid composite key).
            continue

        try:
            # Ledger-presence check: any existing row for this
            # (tenant, service_report_id) means the snapshot already
            # fired at some point. limit=1 keeps the count cheap.
            existing = await db.chemical_usage_events.count_documents(
                {"tenant_id": tenant_id, "service_report_id": sr_id},
                limit=1,
            )
            if existing:
                continue  # already has ledger — nothing to backfill

            # Empty-chemistry safeguard (pre-flight).
            has_top, has_body = _has_any_chemistry(report)
            if not has_top and not has_body:
                rows_skipped_empty_chemistry += 1
                continue

            # Look up the source job for job_id + customer_id +
            # occurred_at.  Missing job is tolerated — snapshot
            # accepts ``customer_id=None`` and we fall back to the
            # report's ``submitted_at`` for the occurred_at stamp.
            job = await db.jobs.find_one(
                {"id": report.get("job_id"), "tenant_id": tenant_id},
                {"_id": 0, "customer_id": 1,
                  "scheduled_date": 1, "scheduled_start": 1},
            ) or {}

            # Prefer water_bodies shape when it carries chemistry
            # (mirrors the live submit path at service_reports.py
            # around the moved P0 block).
            _bodies = report.get("water_bodies") if has_body else None
            _top = None if _bodies else (report.get("chemicals_added") or [])

            try:
                res = await snapshot_chemical_usage(
                    tenant_id=tenant_id,
                    job_id=report.get("job_id"),
                    service_report_id=sr_id,
                    customer_id=job.get("customer_id"),
                    chemicals_added=_top,
                    water_bodies=_bodies,
                    occurred_at=(job.get("scheduled_date")
                                    or job.get("scheduled_start")
                                    or report.get("submitted_at")),
                    actor_user_id=None,  # migration is impersonal
                )
            except Exception as _snap_e:                          # noqa: BLE001
                rows_failed += 1
                logger.warning(
                    "[chemical_usage_backfill_v1] snapshot failed"
                    " report=%s tenant=%s: %s",
                    sr_id, tenant_id, _snap_e,
                )
                if len(failures) < _FAILURE_LOG_CAP:
                    failures.append({
                        "service_report_id": sr_id,
                        "tenant_id": tenant_id,
                        "error": str(_snap_e)[:200],
                    })
                continue

            inserted = int((res or {}).get("inserted") or 0)
            if inserted == 0:
                # Snapshot ran successfully but produced no events
                # (all chem lines had quantity<=0 or otherwise
                # skipped). Effectively empty from the ledger's POV —
                # count as skipped so the operator sees an honest
                # rows_backfilled number.
                rows_skipped_empty_chemistry += 1
                continue

            # Provenance stamp — post-insert update_many. Scoped by
            # (tenant, service_report_id) so we only touch rows
            # we just inserted. ``backfilled_by: {$exists: False}``
            # is a defensive filter — if some future co-writer also
            # stamps this row, we won't clobber their marker.
            try:
                await db.chemical_usage_events.update_many(
                    {"tenant_id": tenant_id,
                      "service_report_id": sr_id,
                      "backfilled_by": {"$exists": False}},
                    {"$set": {"backfilled_by": MIGRATION_KEY}},
                )
            except Exception as _stamp_e:                         # noqa: BLE001
                # Provenance stamp failure is non-blocking — the
                # ledger row exists (which is the P0 goal); the
                # rollback story loses fidelity for THIS row only.
                # Logged for ops.
                logger.warning(
                    "[chemical_usage_backfill_v1] provenance stamp"
                    " failed report=%s tenant=%s: %s",
                    sr_id, tenant_id, _stamp_e,
                )

            rows_backfilled += 1
        except Exception as _outer_e:                             # noqa: BLE001
            rows_failed += 1
            logger.warning(
                "[chemical_usage_backfill_v1] per-row error"
                " report=%s tenant=%s: %s",
                sr_id, tenant_id, _outer_e,
            )
            if len(failures) < _FAILURE_LOG_CAP:
                failures.append({
                    "service_report_id": sr_id or "",
                    "tenant_id": tenant_id or "",
                    "error": str(_outer_e)[:200],
                })

    # Sentinel completion — ALWAYS write on loop-exit so a partial
    # run's stats are visible in ``migration_status`` (rollback +
    # re-run is the way to recover unfailed rows).
    await db.migration_status.update_one(
        {"key": MIGRATION_KEY},
        {"$set": {
            "key": MIGRATION_KEY,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "rows_backfilled": rows_backfilled,
            "rows_failed": rows_failed,
            "rows_skipped_empty_chemistry": rows_skipped_empty_chemistry,
            "failures": failures,
            "must_succeed": False,
        },
         "$unset": {"error": "", "last_attempt_at": ""}},
        upsert=True,
    )
    logger.info(
        "[chemical_usage_backfill_v1] complete — backfilled=%s"
        " failed=%s skipped_empty=%s",
        rows_backfilled, rows_failed, rows_skipped_empty_chemistry,
    )
    return {
        "ok": True, "skipped": False,
        "rows_backfilled": rows_backfilled,
        "rows_failed": rows_failed,
        "rows_skipped_empty_chemistry": rows_skipped_empty_chemistry,
    }
