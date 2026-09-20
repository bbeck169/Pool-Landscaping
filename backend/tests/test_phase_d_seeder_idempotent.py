"""Phase D1 · Feb 2026 — seeder idempotency + row-count coverage.

Guards two properties:

* Running :func:`run_phase_d1_industry_template_seed` twice does
  NOT duplicate rows (the ``industry_checklist_templates``
  collection collapses to exactly one default doc per canonical
  industry regardless of how many times the migration executes).
* Each of the 16 new Phase-D1 industries + the expanded
  ``pest_control`` template carries ≥ 5 items post-seed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
from tests._phase34_asyncio import batch_safe_run as _run


PHASE_D_NEW_SLUGS = [
    "plumbing", "electrical", "roofing", "painting",
    "garage_door", "appliance_repair", "locksmith",
    "chimney_sweep", "gutter", "window_cleaning",
    "carpet_cleaning", "pressure_washing", "tree_service",
    "snow_removal", "fencing", "irrigation",
]


def test_seeder_is_idempotent_no_duplicate_rows():
    """Wipe → seed → seed. Second run must NOT create duplicates
    (exactly one default row per canonical industry post-second)."""
    from routers.industry_checklists import INDUSTRY_SLUGS
    from services.migrations.seed_phase_d_industry_templates import (
        MIGRATION_ID, run_phase_d1_industry_template_seed,
    )
    # Fresh state — clear the sentinel + collection so we exercise
    # the full insertion path deterministically.
    _sync.migrations.delete_many({"id": MIGRATION_ID})
    _sync.industry_checklist_templates.delete_many({"is_default": True})

    first = _run(run_phase_d1_industry_template_seed())
    assert first["upserted"] == len(INDUSTRY_SLUGS), (
        f"first run expected to upsert {len(INDUSTRY_SLUGS)} rows, "
        f"got {first['upserted']}"
    )
    assert first["sentinel_stamped"] is True

    # Second run — sentinel present → short-circuit; NO writes.
    second = _run(run_phase_d1_industry_template_seed())
    assert second.get("skipped") is True
    assert second["upserted"] == 0

    # Sanity: exactly ONE default doc per canonical slug.
    for slug in INDUSTRY_SLUGS:
        rows = _run(_sync_find_all(slug))
        assert len(rows) == 1, (
            f"industry={slug} → expected 1 default row, got {len(rows)}"
        )

    # Third run — force=True path. Should re-upsert every row
    # without changing the row count (the (industry, is_default)
    # key collapses to a single doc even under upsert-force).
    third = _run(run_phase_d1_industry_template_seed(force=True))
    assert third["upserted"] + third["matched"] == len(INDUSTRY_SLUGS)
    for slug in INDUSTRY_SLUGS:
        rows = _run(_sync_find_all(slug))
        assert len(rows) == 1


async def _sync_find_all(slug):
    from config import db as _db
    cursor = _db.industry_checklist_templates.find(
        {"industry": slug, "is_default": True}, {"_id": 0, "id": 1},
    )
    return await cursor.to_list(20)


@pytest.mark.parametrize("slug", PHASE_D_NEW_SLUGS + ["pest_control"])
def test_each_industry_has_at_least_five_items(slug: str):
    """Post-seed, every industry that D1 owns must ship ≥ 5 items
    (the brief min). ``pest_control`` was flagged as under-seeded
    pre-D1 — the two legally-critical additions (EPA reg # + amount,
    re-entry time) push it well over five."""
    from services.migrations.seed_phase_d_industry_templates import (
        run_phase_d1_industry_template_seed,
    )
    # Best-effort re-seed in case an earlier test in the module
    # wiped state. ``force=True`` guarantees the row exists in
    # its authoritative shape.
    _run(run_phase_d1_industry_template_seed(force=True))
    row = _sync.industry_checklist_templates.find_one(
        {"industry": slug, "is_default": True}, {"_id": 0, "items": 1},
    )
    assert row is not None, f"industry={slug} default row missing"
    assert len(row["items"]) >= 5, (
        f"industry={slug} shipped {len(row['items'])} items — "
        f"expected at least 5"
    )
