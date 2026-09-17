"""Feb 2026 · Invoice Email CTA Label ticket — Dunning stage CTA backfill.

Background
----------
The 6 canonical dunning stages defined in
:data:`backend.routers.dunning.DEFAULT_STAGES` had their email-body
CTA renamed from ``"Pay online: <url>"`` to ``"View invoice: <url>"``
as part of the Feb 2026 Invoice Email CTA Label ticket.

The catch: those defaults are copied into
``db.dunning_settings.stages`` **only** at first ``_get_settings``
call (lazy seed) OR when an admin explicitly hits
``POST /dunning/settings/reset-defaults``. Tenants that already had a
persisted ``dunning_settings`` document keep the pre-rename body copy
and continue sending emails with the legacy ``"Pay online:"`` prefix.

This migration
--------------
Iterates every persisted ``dunning_settings`` document. For each
stage whose ``body_template`` still contains the literal
``"Pay online: "`` prefix, rewrites that prefix to
``"View invoice: "`` in place. Tenants without persisted stages are
ignored. Custom-authored stage bodies that don't contain the old
literal are untouched (idempotency guarantee).

Audit stamp
-----------
Every migrated document also records a ``dunning_stage_cta_migrated``
entry inside a small audit list on the settings doc so ops can
verify which tenants have been backfilled without diffing the
before/after body copy.

Manual run — NOT auto-run at boot
---------------------------------
Callers are expected to invoke this migration from a shell (or the
admin ops runner) once per environment. Same pattern as
``recurring_templates_is_active_backfill`` and
``recurring_templates_active_customer_idx``.

Dry-run
-------
``run_backfill(dry_run=True)`` reports the affected count + the
per-tenant + per-stage diff without writing anything. Safe default
for exploration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from config import db


logger = logging.getLogger("dunning_stages_view_invoice_backfill")


# Literal prefix + its Feb 2026 replacement. Kept as module-level
# constants so callers (and tests) can assert against the exact
# strings without hard-coding them at every site.
LEGACY_PREFIX = "Pay online: "
NEW_PREFIX = "View invoice: "

# Audit-log entry key stamped on every migrated tenant's settings doc.
AUDIT_KEY = "dunning_stage_cta_migrated"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rewrite_stage_body(body: str) -> Tuple[str, bool]:
    """Return ``(new_body, changed)`` for a single stage body_template.

    * ``changed=True`` when the legacy prefix appeared anywhere and
      was rewritten.
    * ``changed=False`` when the body was already migrated or was
      custom-authored (doesn't contain the legacy prefix at all).

    The rewrite is a substring replacement — matches every occurrence
    within the body_template (some future stage could conceivably
    reference the CTA twice; the loop handles that correctly without
    a re.sub call).
    """
    if not body or LEGACY_PREFIX not in body:
        return body, False
    return body.replace(LEGACY_PREFIX, NEW_PREFIX), True


def _rewrite_stages(stages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]],
                                                             List[Dict[str, str]]]:
    """Return ``(new_stages, diffs)`` for a stages array.

    ``diffs`` is a list of ``{"stage_id", "before", "after"}`` maps —
    one per stage that actually changed. Empty when no stage in the
    tenant needed a rewrite.
    """
    new_stages: List[Dict[str, Any]] = []
    diffs: List[Dict[str, str]] = []
    for stage in stages or []:
        stage_copy = dict(stage)
        body = stage_copy.get("body_template") or ""
        new_body, changed = _rewrite_stage_body(body)
        if changed:
            stage_copy["body_template"] = new_body
            diffs.append({
                "stage_id": stage_copy.get("id") or "",
                "before": body,
                "after": new_body,
            })
        new_stages.append(stage_copy)
    return new_stages, diffs


async def run_backfill(dry_run: bool = True) -> Dict[str, Any]:
    """Migrate every persisted ``dunning_settings`` document.

    Parameters
    ----------
    dry_run
        When ``True`` (default), the function returns the diff report
        without mutating the DB. When ``False``, updates each affected
        tenant's ``stages`` array + appends a
        ``dunning_stage_cta_migrated`` audit entry.

    Returns
    -------
    dict::

        {
            "dry_run": bool,
            "tenants_scanned": int,
            "tenants_affected": int,
            "stages_rewritten": int,
            "audit_stamped": int,      # tenants where the audit line
                                        # was appended (real-run only)
            "per_tenant": [
                {
                    "tenant_id": str,
                    "stages_rewritten": int,
                    "diffs": [{"stage_id", "before", "after"}, ...],
                },
                ...
            ],
        }
    """
    tenants_scanned = 0
    tenants_affected = 0
    stages_rewritten = 0
    audit_stamped = 0
    per_tenant: List[Dict[str, Any]] = []

    cursor = db.dunning_settings.find({}, {"_id": 0, "tenant_id": 1, "stages": 1})
    async for doc in cursor:
        tenants_scanned += 1
        tenant_id = doc.get("tenant_id")
        stages = doc.get("stages") or []
        if not stages:
            # Tenant has a settings doc but no persisted stages —
            # skip. Their next _get_settings call will hydrate from
            # the freshly-renamed DEFAULT_STAGES anyway.
            continue
        new_stages, diffs = _rewrite_stages(stages)
        if not diffs:
            continue
        tenants_affected += 1
        stages_rewritten += len(diffs)
        per_tenant.append({
            "tenant_id": tenant_id,
            "stages_rewritten": len(diffs),
            "diffs": diffs,
        })
        if dry_run:
            continue
        # Real run — write the migrated stages + append audit entry.
        # The audit list is created on the fly if missing so tenants
        # that have never been touched by an ops-tool still get the
        # marker stamped cleanly.
        audit_entry = {
            "key": AUDIT_KEY,
            "at": _now_iso(),
            "stages_rewritten": len(diffs),
            "stage_ids": [d["stage_id"] for d in diffs],
        }
        await db.dunning_settings.update_one(
            {"tenant_id": tenant_id},
            {
                "$set": {
                    "stages": new_stages,
                    "updated_at": _now_iso(),
                },
                "$push": {"audit_log": audit_entry},
            },
        )
        audit_stamped += 1
        logger.info(
            "[dunning_stages_cta_backfill] tenant=%s rewrote %d stage(s)",
            tenant_id, len(diffs),
        )

    return {
        "dry_run": dry_run,
        "tenants_scanned": tenants_scanned,
        "tenants_affected": tenants_affected,
        "stages_rewritten": stages_rewritten,
        "audit_stamped": audit_stamped,
        "per_tenant": per_tenant,
    }


if __name__ == "__main__":
    import argparse
    import asyncio
    import json

    parser = argparse.ArgumentParser(
        description="Backfill dunning stage CTA copy (Pay online → View invoice).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write the migration. Default is dry-run.",
    )
    args = parser.parse_args()

    result = asyncio.run(run_backfill(dry_run=not args.commit))
    print(json.dumps(result, indent=2, default=str))
