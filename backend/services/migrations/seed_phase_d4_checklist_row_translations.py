"""Phase D4 · Feb 2026 — fold `label_i18n.{es,fr}` onto every row
of every seeded default checklist template.

Idempotency
-----------
* Sentinel doc ``phase_d4_row_translations_v1`` in ``db.migrations``.
* Per-row rule: only WRITES a translation when the target locale
  entry is missing OR the existing value is an empty string. Never
  overwrites a non-empty translator-edited value.
* Safe to run before D1 has seeded the base rows: rows with no
  translation in the static matrix are skipped silently and a warn
  logged.

Consumed by
===========
Ops / startup — mirrors the D1 migration invocation pattern.
"""
from __future__ import annotations

from typing import Dict

from config import db, logger
from services.checklist_row_translations import ROW_TRANSLATIONS
from utils import now_iso


MIGRATION_ID = "phase_d4_row_translations_v1"


async def run_phase_d4_row_translation_seed(*, force: bool = False) -> Dict[str, int]:
    """Update every ``industry_checklist_templates`` default doc so
    each row carries ``label_i18n.es`` and ``label_i18n.fr``.

    Returns ``{"docs_touched": int, "rows_updated": int,
    "rows_skipped": int, "docs_missing_translations": [str]}``.
    """
    if not force:
        sentinel = await db.migrations.find_one(
            {"id": MIGRATION_ID}, {"_id": 0, "id": 1},
        )
        if sentinel:
            logger.info(
                f"[phase-d4] sentinel {MIGRATION_ID} present — skipping"
            )
            return {"docs_touched": 0, "rows_updated": 0,
                     "rows_skipped": 0, "skipped": True,
                     "docs_missing_translations": []}

    docs_touched = 0
    rows_updated = 0
    rows_skipped = 0
    missing: list = []

    cursor = db.industry_checklist_templates.find(
        {"is_default": True}, {"_id": 0, "id": 1, "industry": 1, "items": 1},
    )
    async for doc in cursor:
        industry = doc.get("industry")
        items = doc.get("items") or []
        if not industry or not items:
            continue
        changed = False
        for row in items:
            key = row.get("key")
            if not key:
                continue
            translations = ROW_TRANSLATIONS.get((industry, key)) or {}
            if not translations:
                rows_skipped += 1
                if industry not in missing:
                    missing.append(industry)
                continue
            i18n = row.get("label_i18n") or {}
            if not isinstance(i18n, dict):
                i18n = {}
            row_changed = False
            for loc, value in translations.items():
                existing = i18n.get(loc)
                # Only WRITE when target is missing / empty — never
                # clobber a translator-edited non-empty value.
                if not (isinstance(existing, str) and existing.strip()):
                    i18n[loc] = value
                    row_changed = True
            if row_changed:
                row["label_i18n"] = i18n
                rows_updated += 1
                changed = True
        if changed:
            await db.industry_checklist_templates.update_one(
                {"industry": industry, "is_default": True},
                {"$set": {"items": items, "updated_at": now_iso()}},
            )
            docs_touched += 1

    try:
        await db.migrations.update_one(
            {"id": MIGRATION_ID},
            {"$set": {"id": MIGRATION_ID, "completed_at": now_iso(),
                        "docs_touched": docs_touched,
                        "rows_updated": rows_updated,
                        "rows_skipped": rows_skipped}},
            upsert=True,
        )
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"[phase-d4] sentinel stamp failed: {e}")

    logger.info(
        f"[phase-d4] row-translations: docs_touched={docs_touched} "
        f"rows_updated={rows_updated} rows_skipped={rows_skipped}"
    )
    return {"docs_touched": docs_touched, "rows_updated": rows_updated,
             "rows_skipped": rows_skipped,
             "docs_missing_translations": missing}
