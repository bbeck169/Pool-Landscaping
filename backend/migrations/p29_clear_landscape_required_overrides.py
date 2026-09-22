"""Phase P29 · Feb-2026 — Unlock the landscape checklist.

The MI1 seeder (``routers.industry_checklists.seed_industry_checklist_templates``)
persists ``DEFAULT_TEMPLATES["landscaping"]`` into
``db.industry_checklist_templates`` on first boot then **skips** on
subsequent boots (``if existing: kept += 1; continue``). This means a
tenant whose template was seeded BEFORE the P29 code change still
carries the old ``required=True`` values on four rows, and the
checklist-close gate refuses to close a landscape job without them.

This migration handles the two persistence layers that outlive the
in-memory ``DEFAULT_TEMPLATES`` change:

  1. **Template doc** — ``db.industry_checklist_templates`` where
     ``industry == "landscaping"`` and ``is_default == True``. Re-seed
     ``items`` from the fresh ``DEFAULT_TEMPLATES["landscaping"]``.
  2. **Tenant override docs** — ``db.tenant_checklist_overrides``
     where ``industry == "landscaping"``. Rewrite each doc's ``items``
     list with ``required = False`` on every row (label / key / group
     preserved so admins keep their custom rows visible).

Scope guardrails:

* ``industry == "landscaping"`` on BOTH collections. Other
  industries (pool, hvac, ...) are NEVER touched.
* Idempotent — a second run finds ``required=False`` everywhere and
  no-ops.
* Best-effort — wired into the P21 structural boot block with
  ``must_succeed=False`` so a Mongo hiccup on this migration never
  blocks bind. The InitState still stamps ERROR so ops sees the
  failure on ``/api/health``.

Standing rule: this migration is scoped to the ``landscaping``
industry. Do NOT extend to pool / hvac / etc. — they carry
compliance gates (EPA docs, HVAC startup cycle, etc.) that would be
unsafe to soften without a phase spec.
"""
from __future__ import annotations

from typing import Any, Dict, List

from config import db, logger


MIGRATION_NAME = "p29_clear_landscape_required_overrides"
INDUSTRY = "landscaping"


def _rows_all_not_required(items: List[Dict[str, Any]]) -> bool:
    """True when every row's ``required`` is falsy — used for the
    fast-path idempotency check so a fully-cleared doc is a no-op."""
    return all(not (it or {}).get("required") for it in (items or ()))


async def run() -> Dict[str, Any]:
    """Idempotent update pass over the landscape template + all
    tenant landscape overrides.

    Returns a summary dict for the P21 structural-migration logger.
    """
    # ── 1) Template row ──────────────────────────────────────────
    #
    # ``routers.industry_checklists.DEFAULT_TEMPLATES["landscaping"]``
    # is the single source of truth. We import here (not at module
    # top) so this file remains importable during test collection
    # even if the router hasn't wired ``db`` for the current loop.
    from routers.industry_checklists import DEFAULT_TEMPLATES
    from utils import now_iso

    fresh_items = DEFAULT_TEMPLATES.get(INDUSTRY) or []
    if not fresh_items:
        # Nothing to do — the router doesn't ship a landscaping
        # default. This shouldn't happen in production (INDUSTRY_SLUGS
        # includes ``landscaping``) but avoid crashing boot if
        # someone reshapes the constant.
        logger.warning(
            "[p29] no in-memory landscaping template — skipping "
            "template refresh + override cleanup"
        )
        return {"template_updated": False, "overrides_updated": 0,
                "reason": "no_in_memory_template"}

    template_result = await db.industry_checklist_templates.find_one_and_update(
        {"industry": INDUSTRY, "is_default": True},
        {"$set": {"items": fresh_items, "updated_at": now_iso()}},
        return_document=False,   # match-first, no upsert
    )
    template_updated = template_result is not None
    if not template_updated:
        # Boot seeder hasn't run yet (fresh install) — the seeder
        # will write the P29 items on its first pass. Nothing to
        # patch here.
        logger.info(
            "[p29] landscape template doc absent — seeder will "
            "insert the P29 items on next call"
        )

    # ── 2) Tenant override docs ──────────────────────────────────
    #
    # Read one at a time so a ~10k-tenant install doesn't hydrate the
    # whole set into RAM. Each override doc is small (10-15 items)
    # so per-doc rewrite is cheap.
    overrides_updated = 0
    overrides_skipped_already_clear = 0
    per_tenant_counts: Dict[str, int] = {}

    async for doc in db.tenant_checklist_overrides.find(
        {"industry": INDUSTRY},
        {"_id": 0, "id": 1, "tenant_id": 1, "items": 1},
    ):
        items = doc.get("items") or []
        if _rows_all_not_required(items):
            overrides_skipped_already_clear += 1
            continue
        # Rewrite in-place — preserve every row's key / label /
        # group and every field the caller might have persisted
        # beyond the canonical schema (label_i18n, etc.). Only the
        # ``required`` flag flips to ``False``.
        rewritten: List[Dict[str, Any]] = []
        mutated_rows = 0
        for it in items:
            if not isinstance(it, dict):
                # Malformed row — drop, matching ``_sanitize_items``
                # behavior in the router.
                continue
            new_row = dict(it)
            if new_row.get("required"):
                mutated_rows += 1
                new_row["required"] = False
            rewritten.append(new_row)
        await db.tenant_checklist_overrides.update_one(
            {"tenant_id": doc["tenant_id"], "industry": INDUSTRY},
            {"$set": {"items": rewritten, "updated_at": now_iso()}},
        )
        overrides_updated += 1
        per_tenant_counts[doc["tenant_id"]] = mutated_rows
        logger.info(
            "[p29] cleared %s required flags on tenant=%s "
            "landscape override",
            mutated_rows, doc["tenant_id"],
        )

    logger.info(
        "[p29] landscape checklist unlock complete: "
        "template_updated=%s overrides_updated=%s overrides_skipped=%s",
        template_updated, overrides_updated,
        overrides_skipped_already_clear,
    )
    return {
        "template_updated": template_updated,
        "overrides_updated": overrides_updated,
        "overrides_skipped_already_clear": overrides_skipped_already_clear,
        "per_tenant_counts": per_tenant_counts,
    }
