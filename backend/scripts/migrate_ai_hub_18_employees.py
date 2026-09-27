"""AI Hub · Feb-2026 — one-shot 18-employee tenant migration.

Idempotent — safe to run repeatedly.  For each tenant + each
row in ``services.ai_hub.employee_registry.EMPLOYEES``:

* NOT present  → INSERT with registry defaults +
                 ``authorized_for_public_use=False`` +
                 ``action_limit_monthly=60000``.
* Present      → PATCH only the missing new fields
                 (``human_name``, ``codename``, ``role_title``,
                 ``org_department``, ``hierarchy_order``,
                 ``manager_key``, ``avatar_url``,
                 ``authorized_for_public_use``,
                 ``action_limit_monthly``, ``is_legacy=false``).
                 NEVER overwrites existing tenant customisations.

Legacy rows (10 pre-existing personas in
``routers.ai_employees.DEFAULT_EMPLOYEES``) are also touched
per spec § "Migration ai_hub_18_workforce_v1.py" — their
``codename`` is stamped as ``key.upper()``, ``role_title`` is
copied from ``role`` when unset, and ``is_legacy`` is set to
``True``.  Their existing ``name`` + ``system_prompt`` +
avatar are preserved verbatim.

Boot-time execution
───────────────────
This module also exposes ``async def run(db) -> dict`` for
``server.py`` to invoke on startup when
``AI_HUB_AUTO_MIGRATE=true``.  When the env is unset or any
other value the boot hook no-ops silently.

Manual execution
────────────────
    cd /app/backend && python -m scripts.migrate_ai_hub_18_employees

Prints a per-tenant summary + a totals block.  Exit code 0 on
success, non-zero on unhandled exception.
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List

# Add /app/backend to sys.path when run as a script.
if __name__ == "__main__":
    _here = os.path.dirname(os.path.abspath(__file__))
    _backend = os.path.dirname(_here)
    if _backend not in sys.path:
        sys.path.insert(0, _backend)


AUTO_MIGRATE_ENV = "AI_HUB_AUTO_MIGRATE"


# ═══════════════════════════════════════════════════════════════════
# Core migration
# ═══════════════════════════════════════════════════════════════════

async def _migrate_one_tenant(db, tenant_id: str) -> Dict[str, int]:
    """Return per-tenant counters.  Does NOT log — the caller
    aggregates + logs a single roll-up line."""
    from services.ai_hub.employee_registry import EMPLOYEES, to_seed_doc
    from utils import new_id, now_iso

    inserted = 0
    patched = 0
    untouched = 0

    for spec in EMPLOYEES:
        seed_doc = to_seed_doc(spec)
        existing = await db.ai_employees.find_one(
            {"tenant_id": tenant_id, "key": spec.key},
            {"_id": 0},
        )
        if existing is None:
            # Fresh insert — full row.
            doc = {
                "id": new_id(),
                "tenant_id": tenant_id,
                **seed_doc,
                "active": True,
                "read_access_scope": "customer_scoped",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            await db.ai_employees.insert_one(doc)
            inserted += 1
            continue

        # Present — patch only fields that are ABSENT from the
        # existing row.  NEVER overwrite a value the user has set,
        # and NEVER re-stamp fields already written (even when the
        # existing value is ``None`` — e.g. executive-tier employees
        # legitimately carry ``manager_key=None``).  Key-membership
        # is the correct idempotency invariant here.
        patch: Dict[str, Any] = {}
        for k, v in seed_doc.items():
            if k in existing:
                continue
            patch[k] = v

        if patch:
            patch["updated_at"] = now_iso()
            await db.ai_employees.update_one(
                {"id": existing["id"]},
                {"$set": patch},
            )
            patched += 1
        else:
            untouched += 1

    return {
        "employees_inserted": inserted,
        "employees_patched": patched,
        "employees_untouched": untouched,
    }


async def run(db) -> Dict[str, Any]:
    """Full sweep — every tenant × every registry row.
    Returns the aggregate roll-up dict."""
    tenants_scanned = 0
    totals = {
        "employees_inserted": 0,
        "employees_patched": 0,
        "employees_untouched": 0,
    }
    per_tenant: List[Dict[str, Any]] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1, "name": 1}):
        tid = t.get("id")
        if not tid:
            continue
        counts = await _migrate_one_tenant(db, tid)
        tenants_scanned += 1
        for k in totals:
            totals[k] += counts[k]
        per_tenant.append({
            "tenant_id": tid,
            "tenant_name": t.get("name"),
            **counts,
        })
    return {
        "ok": True,
        "tenants_scanned": tenants_scanned,
        **totals,
        "per_tenant": per_tenant,
    }


async def run_if_env_enabled(db) -> Dict[str, Any]:
    """Boot-hook wrapper.  Only runs when
    ``AI_HUB_AUTO_MIGRATE=true`` — otherwise no-ops.
    Never raises: on failure returns a shape indicating skip."""
    value = (os.environ.get(AUTO_MIGRATE_ENV) or "").strip().lower()
    if value != "true":
        return {"ok": True, "skipped": True, "reason": "env_disabled"}
    try:
        return await run(db)
    except Exception as exc:  # pragma: no cover — defensive
        from config import logger
        logger.warning(
            "[ai-hub] migrate_ai_hub_18_employees crashed: %s", exc,
        )
        return {"ok": False, "skipped": False, "error": str(exc)}


# ═══════════════════════════════════════════════════════════════════
# Manual entry point
# ═══════════════════════════════════════════════════════════════════

async def _main():
    from config import db, logger
    logger.info("[ai-hub] migrate_ai_hub_18_employees — starting")
    result = await run(db)
    logger.info(
        "[ai-hub] migrate_ai_hub_18_employees — done "
        f"tenants={result['tenants_scanned']} "
        f"inserted={result['employees_inserted']} "
        f"patched={result['employees_patched']} "
        f"untouched={result['employees_untouched']}"
    )
    for row in result["per_tenant"]:
        logger.info(f"[ai-hub]   {row}")
    return result


if __name__ == "__main__":
    asyncio.run(_main())
