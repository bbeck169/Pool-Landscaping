"""Ticket JJ · Feb-2026 — one-shot backfill: strip HTML off invoice
line_items + pricebook item name / description.

AA-pattern sentinel in ``db.migrations``.  Idempotent — safe to re-
run; a persisted sentinel short-circuits unless ``force=True``.
Dry-run flag emits counts without mutating.

Field coverage (operator-locked JJ brief §3):
  * db.quotes.line_items[*] — strips ``title`` + ``description`` +
    ``name`` + ``item_name`` on each line.  Doc_type-agnostic
    (covers quotes, estimates, invoices — all live in db.quotes).
  * db.items.{name, description, category} — pricebook rows.  The
    preview schema has no ``title``; ``category`` is a short label
    historically free-text so include defensively.

Non-string values (None, numbers) are left untouched.  Strings that
already contain no HTML tags AND no entities are no-ops at the
per-field level (string equality check skips the write).  The doc
is only written back when at least one field changed.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from config import db
from services.text.html_to_plain import html_to_plain

logger = logging.getLogger(__name__)

_SENTINEL_ID = "jj_strip_html_line_item_fields_v1"

_LINE_ITEM_FIELDS = ("title", "description", "name", "item_name")
_PRICEBOOK_FIELDS = ("name", "description", "category")


def _needs_strip(value: Any) -> bool:
    """Fast check — bail if the string carries no HTML tags AND no
    entities.  Avoids a doc write when the field is already clean.
    """
    if not isinstance(value, str) or not value:
        return False
    return ("<" in value and ">" in value) or "&" in value


def _strip_field(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if not _needs_strip(value):
        return value
    return html_to_plain(value)


async def _strip_quotes_batch(stats: Dict[str, int], *, dry_run: bool) -> None:
    """Walk every doc in db.quotes and strip HTML off line_items[*]."""
    cursor = db.quotes.find(
        {"line_items": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "line_items": 1},
    )
    async for doc in cursor:
        stats["quotes_scanned"] += 1
        items = doc.get("line_items") or []
        new_items = []
        doc_touched = False
        for li in items:
            if not isinstance(li, dict):
                new_items.append(li)
                continue
            new_li = dict(li)
            line_touched = False
            for field in _LINE_ITEM_FIELDS:
                raw = new_li.get(field)
                if _needs_strip(raw):
                    cleaned = _strip_field(raw)
                    if cleaned != raw:
                        new_li[field] = cleaned
                        stats["line_fields_stripped"] += 1
                        line_touched = True
            if line_touched:
                stats["line_items_touched"] += 1
                doc_touched = True
            new_items.append(new_li)
        if doc_touched:
            stats["quotes_touched"] += 1
            if not dry_run:
                await db.quotes.update_one(
                    {"id": doc["id"]},
                    {"$set": {"line_items": new_items}},
                )


async def _strip_items_batch(stats: Dict[str, int], *, dry_run: bool) -> None:
    """Walk every pricebook item in db.items and strip HTML off the
    text columns."""
    cursor = db.items.find({}, {"_id": 0, "id": 1, **{f: 1 for f in _PRICEBOOK_FIELDS}})
    async for doc in cursor:
        stats["items_scanned"] += 1
        update: Dict[str, Any] = {}
        for field in _PRICEBOOK_FIELDS:
            raw = doc.get(field)
            if _needs_strip(raw):
                cleaned = _strip_field(raw)
                if cleaned != raw:
                    update[field] = cleaned
                    stats["item_fields_stripped"] += 1
        if update:
            stats["items_touched"] += 1
            if not dry_run:
                await db.items.update_one({"id": doc["id"]}, {"$set": update})


async def run_strip_html_backfill(
    *, force: bool = False, dry_run: bool = False,
) -> Dict[str, Any]:
    """Idempotent one-shot HTML strip across quote line_items +
    pricebook items.

    Returns ``{"skipped": True, "reason": "sentinel"}`` if the
    sentinel is already set and ``force`` is False.  Otherwise
    returns the full stat block.
    """
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel and not force:
        return {
            "sentinel_id": _SENTINEL_ID,
            "skipped": True,
            "reason": "already-run",
            "ran_at": sentinel.get("ran_at"),
        }

    stats = {
        "quotes_scanned": 0,
        "quotes_touched": 0,
        "line_items_touched": 0,
        "line_fields_stripped": 0,
        "items_scanned": 0,
        "items_touched": 0,
        "item_fields_stripped": 0,
    }
    t0 = time.monotonic()
    await _strip_quotes_batch(stats, dry_run=dry_run)
    await _strip_items_batch(stats, dry_run=dry_run)
    duration_ms = int((time.monotonic() - t0) * 1000)

    result = {
        "sentinel_id": _SENTINEL_ID,
        "skipped": False,
        "dry_run": dry_run,
        "duration_ms": duration_ms,
        **stats,
    }

    if not dry_run:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.migrations.update_one(
            {"id": _SENTINEL_ID},
            {"$set": {
                "id": _SENTINEL_ID,
                "ran_at": now_iso,
                "stats": stats,
                "duration_ms": duration_ms,
            }},
            upsert=True,
        )

    logger.info(
        "jj_strip_html_backfill scanned_q=%d touched_q=%d "
        "stripped_lf=%d scanned_i=%d touched_i=%d stripped_if=%d "
        "duration_ms=%d dry_run=%s",
        stats["quotes_scanned"], stats["quotes_touched"],
        stats["line_fields_stripped"],
        stats["items_scanned"], stats["items_touched"],
        stats["item_fields_stripped"],
        duration_ms, dry_run,
    )
    return result
