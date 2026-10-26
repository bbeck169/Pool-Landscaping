"""Ticket JJ · Feb-2026 — backfill migration tests.

The migration touches the live Motor-backed ``db`` (quotes, items,
migrations collections).  Motor binds to the first event loop it
sees; running N tests × N asyncio.run calls dies on the second
test with ``RuntimeError: Event loop is closed``.  Pattern used
here: ONE orchestrator async def that walks the 4 scenarios in
sequence inside a single event loop.  This matches how other
live-DB migration tests in this repo handle isolation.
"""
import asyncio

from config import db
from services.migrations.jj_strip_html_line_item_fields_v1 import (
    _SENTINEL_ID,
    run_strip_html_backfill,
)


_QUOTE_DIRTY = "jj-test-quote-dirty"
_QUOTE_CLEAN = "jj-test-quote-clean"
_ITEM_DIRTY = "jj-test-item-dirty"
_ITEM_CLEAN = "jj-test-item-clean"


async def _reset() -> None:
    await db.migrations.delete_one({"id": _SENTINEL_ID})
    await db.quotes.delete_many({"id": {"$in": [_QUOTE_DIRTY, _QUOTE_CLEAN]}})
    await db.items.delete_many({"id": {"$in": [_ITEM_DIRTY, _ITEM_CLEAN]}})


async def _seed() -> None:
    await db.quotes.insert_one({
        "id": _QUOTE_DIRTY,
        "tenant_id": "jj-test-tenant",
        "doc_type": "invoice",
        "line_items": [
            {"description": "<p>Weekly service &amp; chemicals</p>",
             "item_name": "<b>Pool Clean</b>",
             "unit_price": 120.0},
            {"description": "Plain, already clean",
             "unit_price": 50.0},
        ],
    })
    await db.quotes.insert_one({
        "id": _QUOTE_CLEAN,
        "tenant_id": "jj-test-tenant",
        "doc_type": "invoice",
        "line_items": [{"description": "Plain only", "unit_price": 1.0}],
    })
    await db.items.insert_one({
        "id": _ITEM_DIRTY,
        "name": "<p>Chlorine shock</p>",
        "description": "Weekly &amp; monthly",
        "category": "Chemical",
    })
    await db.items.insert_one({
        "id": _ITEM_CLEAN,
        "name": "Clean item",
        "description": "No tags here",
        "category": "Service",
    })


# ─── SCENARIOS ─────────────────────────────────────────────────────
async def _scenario_dry_run() -> None:
    await _reset()
    await _seed()
    r = await run_strip_html_backfill(dry_run=True)
    assert r["skipped"] is False, r
    assert r["dry_run"] is True
    assert r["quotes_touched"] >= 1, r
    assert r["items_touched"] >= 1, r
    assert r["line_fields_stripped"] >= 2, r
    assert r["item_fields_stripped"] >= 2, r
    # DB unchanged.
    doc = await db.quotes.find_one({"id": _QUOTE_DIRTY})
    assert "<p>" in doc["line_items"][0]["description"]
    item = await db.items.find_one({"id": _ITEM_DIRTY})
    assert "<p>" in item["name"]
    sent = await db.migrations.find_one({"id": _SENTINEL_ID})
    assert sent is None


async def _scenario_live_run() -> None:
    await _reset()
    await _seed()
    r = await run_strip_html_backfill(dry_run=False)
    assert r["skipped"] is False, r
    assert r["dry_run"] is False
    doc = await db.quotes.find_one({"id": _QUOTE_DIRTY})
    li0 = doc["line_items"][0]
    assert "<p>" not in li0["description"]
    assert "&amp;" not in li0["description"]
    assert li0["description"] == "Weekly service & chemicals"
    assert li0["item_name"] == "Pool Clean"
    # Already-clean line untouched.
    assert doc["line_items"][1]["description"] == "Plain, already clean"
    item = await db.items.find_one({"id": _ITEM_DIRTY})
    assert item["name"] == "Chlorine shock"
    assert item["description"] == "Weekly & monthly"
    clean = await db.items.find_one({"id": _ITEM_CLEAN})
    assert clean["name"] == "Clean item"
    sent = await db.migrations.find_one({"id": _SENTINEL_ID})
    assert sent is not None
    assert sent["id"] == _SENTINEL_ID
    assert "ran_at" in sent
    assert "stats" in sent


async def _scenario_idempotent() -> None:
    # Sentinel already set from the previous scenario — a bare
    # re-run short-circuits.
    r2 = await run_strip_html_backfill(dry_run=False)
    assert r2["skipped"] is True, r2
    assert r2["reason"] == "already-run"
    assert r2["sentinel_id"] == _SENTINEL_ID


async def _scenario_force() -> None:
    # ``force=True`` bypasses the sentinel; the data is already
    # clean, so nothing new is stripped.
    r2 = await run_strip_html_backfill(dry_run=False, force=True)
    assert r2["skipped"] is False, r2
    assert r2["line_fields_stripped"] == 0, r2
    assert r2["item_fields_stripped"] == 0, r2


# ─── ORCHESTRATOR ──────────────────────────────────────────────────
def test_jj_strip_html_backfill_all_scenarios() -> None:
    async def _run():
        try:
            await _scenario_dry_run()
            await _scenario_live_run()
            await _scenario_idempotent()
            await _scenario_force()
        finally:
            await _reset()
    asyncio.run(_run())
