"""Phase P36 · Feb-2026 — Global Unlock (Non-Pool Checklist `required:False`).

Extends the P29 landscape-unlock pattern to every non-pool template.
Rationale: pool is the only industry whose checklist rows carry a
compliance gate the ops team wants enforced on job close. Every
other template softens to advisory (`required: False`) so techs can
close jobs with an empty checklist across the field.

Scope
-----
Handles the two persistence layers that outlive the in-memory
``DEFAULT_TEMPLATES`` change (same shape as P29):

  1. **Template docs** — ``db.industry_checklist_templates`` for
     every non-pool industry (excluding ``landscaping`` — P29 owns
     it). Re-seeds ``items`` from the fresh in-memory template.
  2. **Tenant override docs** — ``db.tenant_checklist_overrides``
     for every non-pool, non-landscaping industry belonging to the
     tenant ``P36_TARGET_TENANT_ID``. Flips ``required`` to False
     on every item via an atomic ``$[]`` positional update.

Scope guardrails
----------------
* ``industry != "pool"`` — pool template + pool overrides NEVER
  touched (compliance gate preserved).
* ``industry != "landscaping"`` — P29 owns it; P36 stays out of
  landscape's lane to keep migration ownership clean.
* Tenant-scoped for override cleanup: only the plofv target tenant.
* Idempotent — second run finds ``required=False`` everywhere and
  reports zero mutations.
* Best-effort — wired into the P21 structural boot block with
  ``must_succeed=False`` so a Mongo hiccup never blocks bind.

Follow-ups (NOT P36)
--------------------
* If any additional tenant wants the global unlock, expand
  ``P36_TARGET_TENANT_ID`` to a set / re-parameterise. The current
  scope is deliberately single-tenant to match the launch-republish
  ask.
* Pool template stays gated. Any future "unlock pool" ask must
  ship a separate, explicit migration.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db, logger


MIGRATION_NAME = "p36_clear_nonpool_required_overrides"
P36_TARGET_TENANT_ID = "67752881-7a80-4a2c-a03e-5d1aff4861a4"
POOL_INDUSTRY = "pool"
LANDSCAPE_INDUSTRY = "landscaping"  # owned by P29 — stay clear


def _rows_all_not_required(items: List[Dict[str, Any]]) -> bool:
    """True when every row's ``required`` is falsy — fast-path
    idempotency check so a fully-cleared doc is a no-op."""
    return all(not (it or {}).get("required") for it in (items or ()))


async def run() -> Dict[str, Any]:
    """Idempotent pass over every non-pool, non-landscape template
    doc + this tenant's non-pool, non-landscape override docs.

    Returns a summary dict for the P21 structural-migration logger.
    """
    from routers.industry_checklists import (
        DEFAULT_TEMPLATES, INDUSTRY_SLUGS,
    )
    from utils import now_iso

    target_industries = [
        ind for ind in INDUSTRY_SLUGS
        if ind not in (POOL_INDUSTRY, LANDSCAPE_INDUSTRY)
    ]

    # ── 1) Template docs ─────────────────────────────────────────
    #
    # Re-seed every non-pool, non-landscape default template so the
    # persisted ``required`` flags mirror the in-memory
    # ``DEFAULT_TEMPLATES`` values (all ``False`` after the P36
    # code edits). Idempotent: ``find_one_and_update`` with
    # ``$set`` is a no-op when the items list is already identical.
    templates_updated: Dict[str, bool] = {}
    templates_missing: List[str] = []
    for ind in target_industries:
        fresh_items = DEFAULT_TEMPLATES.get(ind) or []
        if not fresh_items:
            # Should be impossible — every INDUSTRY_SLUG has an entry
            # in DEFAULT_TEMPLATES today — but skip cleanly instead
            # of crashing boot if someone reshapes the constant.
            templates_missing.append(ind)
            continue
        res = await db.industry_checklist_templates.find_one_and_update(
            {"industry": ind, "is_default": True},
            {"$set": {"items": fresh_items, "updated_at": now_iso()}},
            return_document=False,
        )
        templates_updated[ind] = res is not None

    # ── 2) Tenant override docs ──────────────────────────────────
    #
    # Single-tenant scope (P36_TARGET_TENANT_ID). ``industry`` is
    # restricted to the target list — pool + landscape stay
    # untouched. Use the ``$[]`` positional operator so every row
    # in ``items`` is flipped atomically in one write per doc
    # (matches the P29 rewrite but doesn't need a Python loop).
    overrides_updated: Dict[str, int] = {ind: 0 for ind in target_industries}
    overrides_skipped_already_clear = 0
    overrides_items_flipped: Dict[str, int] = {ind: 0 for ind in target_industries}

    cursor = db.tenant_checklist_overrides.find(
        {"tenant_id": P36_TARGET_TENANT_ID,
         "industry": {"$in": target_industries}},
        {"_id": 0, "id": 1, "tenant_id": 1, "industry": 1, "items": 1},
    )
    async for doc in cursor:
        ind = doc.get("industry")
        items = doc.get("items") or []
        if _rows_all_not_required(items):
            overrides_skipped_already_clear += 1
            continue
        # Count how many items are about to flip (audit-log
        # friendly) — for reporting; the write itself is
        # atomic-positional so we don't need the Python loop.
        flipped_this_doc = sum(
            1 for it in items
            if isinstance(it, dict) and it.get("required")
        )
        await db.tenant_checklist_overrides.update_one(
            {"tenant_id": P36_TARGET_TENANT_ID, "industry": ind},
            {"$set": {"items.$[].required": False,
                       "updated_at": now_iso()}},
        )
        overrides_updated[ind] = overrides_updated.get(ind, 0) + 1
        overrides_items_flipped[ind] = (
            overrides_items_flipped.get(ind, 0) + flipped_this_doc
        )
        logger.info(
            "[p36] cleared %s required flags on tenant=%s industry=%s "
            "override",
            flipped_this_doc, P36_TARGET_TENANT_ID, ind,
        )

    total_overrides_updated = sum(overrides_updated.values())
    total_items_flipped = sum(overrides_items_flipped.values())
    logger.info(
        "[p36] non-pool unlock complete: templates_updated=%s "
        "overrides_updated=%s items_flipped=%s "
        "overrides_skipped_already_clear=%s",
        sum(1 for v in templates_updated.values() if v),
        total_overrides_updated,
        total_items_flipped,
        overrides_skipped_already_clear,
    )
    return {
        "target_tenant_id": P36_TARGET_TENANT_ID,
        "target_industries": target_industries,
        "templates_updated": templates_updated,
        "templates_missing": templates_missing,
        "overrides_updated_per_industry": overrides_updated,
        "overrides_items_flipped_per_industry": overrides_items_flipped,
        "overrides_updated_total": total_overrides_updated,
        "overrides_items_flipped_total": total_items_flipped,
        "overrides_skipped_already_clear": overrides_skipped_already_clear,
    }
