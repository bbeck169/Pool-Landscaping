"""Phase 26b · Feb-2026 — Category deactivation fan-out.

When an admin archives an income or service category we walk every
tenant-scoped document that referenced the category and null the
reference while stamping each affected row with::

    category_auto_mapped: True
    original_category_id:   <archived cat id>
    original_category_name: <archived cat name>

Collections touched:
    * ``db.items``   (pricebook) — direct FK on
                       ``service_category_id`` / ``income_category_id``
                       + the legacy ``category`` name string.
    * ``db.quotes``  (invoices + quotes/estimates share this
                       collection via ``doc_type``) — nested
                       ``line_items[].*`` references, same three
                       fields.

Null-out semantics (per Phase 26b spec, locked with human):
``is_archived`` on the category stays flipped to ``True`` as before
— we do NOT create a sentinel "Uncategorized" row.  The archived
reference becomes empty-string so it falls into the existing
"uncategorized" bucket surfaced by the dashboard banner at
``/reports/uncategorized-count`` and the admin report at
``/reports/uncategorized-items``.  The stamping fields let the UI
render an amber "Previously: {original}" chip without needing a
second round-trip for the archived cat's name.

Restore semantics:  calling ``POST /{axis}-categories/{id}/restore``
on a previously-archived category does NOT re-hydrate the null'd
line items.  The stamping stays until the operator manually re-
assigns a category via the inline editor.  This is intentional —
the user explicitly deactivated the category and the operator
should affirmatively re-pick.  Documented in the ``restore_category``
handlers of both routers.

Save-time symmetric helper (``soft_pass_archived_ref_in_line_item``)
is called by both category validators (K71 strict + legacy loose)
when they encounter a line pointing at an archived cat — mutates
the line dict in-place so the write path lands the null'd fields +
stamps alongside the rest of the user's edit.

Transaction integrity:  Mongo multi-document transactions require a
replica set.  We don't assume one, so the archive handler calls
``rollback_archive`` on fan-out failure to flip ``is_archived`` back
to ``False`` — leaving the system in a consistent "not archived +
line items untouched" state.
"""
from __future__ import annotations

import re
from typing import Any, Dict

import config
from config import logger


def _db():
    """Re-read ``config.db`` each call so test fixtures that rebind
    the module-level handle (``tests/_f7_loop_fixture.py``) land on
    a loop-consistent Motor client."""
    return config.db


_AXIS = {
    "income": {
        "line_id_field":     "income_category_id",
        "line_name_field":   "income_category_name",
        "legacy_field":      "category",        # legacy name string
        "legacy_name_field": "category_name",
        "item_field":        "income_category_id",
    },
    "service": {
        "line_id_field":     "service_category_id",
        "line_name_field":   "service_category_name",
        "legacy_field":      None,              # svc has no legacy string field
        "legacy_name_field": None,
        "item_field":        "service_category_id",
    },
}


async def fan_out_archive(
    *, axis: str, tenant_id: str, cat_id: str, cat_name: str,
) -> Dict[str, Any]:
    """Null-out ``cat_id`` across tenant line items + pricebook items.

    Returns ``{"pricebook_items_updated": int,
                "quotes_updated_by_id": int,
                "quotes_updated_by_legacy_name": int}``.
    """
    if axis not in _AXIS:
        raise ValueError(f"Unknown axis: {axis!r}")
    cfg = _AXIS[axis]
    line_id_field = cfg["line_id_field"]
    item_field = cfg["item_field"]

    # ── Pricebook items (db.items) — flat FK, single $set ──
    item_set: Dict[str, Any] = {
        item_field: "",
        "category_auto_mapped": True,
        "original_category_id": cat_id,
        "original_category_name": cat_name,
    }
    item_result = await _db().items.update_many(
        {"tenant_id": tenant_id, item_field: cat_id},
        {"$set": item_set},
    )

    # ── Quote line items referenced by id ───────────────────
    # arrayFilters touches every matching element in each doc.
    # Phase 26b · Feb-2026 — for income axis, also null the legacy
    # ``category`` + ``category_name`` fields on any element whose
    # income_category_id matches (common shape: the K71 write path
    # stamps both ``income_category_id`` and the legacy ``category``
    # with the SAME value — so an id-based match should null both).
    set_payload: Dict[str, Any] = {
        f"line_items.$[elem].{line_id_field}": "",
        f"line_items.$[elem].{cfg['line_name_field']}": "",
        "line_items.$[elem].category_auto_mapped": True,
        "line_items.$[elem].original_category_id": cat_id,
        "line_items.$[elem].original_category_name": cat_name,
    }
    if cfg.get("legacy_field"):
        set_payload[f"line_items.$[elem].{cfg['legacy_field']}"] = ""
    if cfg.get("legacy_name_field"):
        set_payload[f"line_items.$[elem].{cfg['legacy_name_field']}"] = ""
    id_update = {"$set": set_payload}
    id_result = await _db().quotes.update_many(
        {"tenant_id": tenant_id, f"line_items.{line_id_field}": cat_id},
        id_update,
        array_filters=[{f"elem.{line_id_field}": cat_id}],
    )
    affected_by_id = int(id_result.modified_count)

    # ── Quote line items referenced by legacy name (income axis only) ──
    affected_by_legacy = 0
    legacy_field = cfg.get("legacy_field")
    legacy_name_field = cfg.get("legacy_name_field")
    if legacy_field and cat_name:
        name_regex = {"$regex": f"^{re.escape(cat_name)}$", "$options": "i"}
        legacy_update = {
            "$set": {
                f"line_items.$[elem].{legacy_field}": "",
                f"line_items.$[elem].{legacy_name_field}": "",
                "line_items.$[elem].category_auto_mapped": True,
                "line_items.$[elem].original_category_id": cat_id,
                "line_items.$[elem].original_category_name": cat_name,
            },
        }
        legacy_result = await _db().quotes.update_many(
            {
                "tenant_id": tenant_id,
                "line_items": {"$elemMatch": {
                    legacy_field: name_regex,
                }},
            },
            legacy_update,
            array_filters=[{f"elem.{legacy_field}": name_regex}],
        )
        affected_by_legacy = int(legacy_result.modified_count)

    logger.info(
        "[phase26b.fan_out_archive] axis=%s tenant=%s cat=%s "
        "items=%d quotes_by_id=%d quotes_by_legacy_name=%d",
        axis, tenant_id, cat_id, item_result.modified_count,
        affected_by_id, affected_by_legacy,
    )
    return {
        "axis": axis,
        "category_id": cat_id,
        "category_name": cat_name,
        "pricebook_items_updated": int(item_result.modified_count),
        "quotes_updated_by_id": affected_by_id,
        "quotes_updated_by_legacy_name": affected_by_legacy,
    }


async def rollback_archive(
    *, axis: str, tenant_id: str, cat_id: str,
) -> None:
    """Compensating un-archive on fan-out failure. Never raises —
    rollback failures are logged for manual recovery.
    """
    coll = {"income": _db().income_categories,
            "service": _db().service_categories}[axis]
    try:
        await coll.update_one(
            {"id": cat_id, "tenant_id": tenant_id},
            {"$set": {"is_archived": False}},
        )
        logger.warning(
            "[phase26b.rollback_archive] un-archived axis=%s cat=%s tenant=%s "
            "after fan-out failure",
            axis, cat_id, tenant_id,
        )
    except Exception:                                               # noqa: BLE001
        logger.exception(
            "[phase26b.rollback_archive] rollback itself failed; "
            "manual recovery needed for axis=%s cat=%s tenant=%s",
            axis, cat_id, tenant_id,
        )


def soft_pass_archived_ref_in_line_item(
    *, li: Dict[str, Any], archived_cat: Dict[str, Any], axis: str,
) -> None:
    """Save-time symmetric helper.  Mutates ``li`` in-place so the
    write path lands the null'd fields + auto-map stamps alongside
    the rest of the operator's edit — avoids an HTTP 400 bounce
    when the operator's open editor still had a stale snapshot of
    the (now-archived) category.
    """
    cfg = _AXIS[axis]
    li[cfg["line_id_field"]] = ""
    name_field = cfg.get("line_name_field")
    if name_field:
        li[name_field] = ""
    legacy = cfg.get("legacy_field")
    if legacy and li.get(legacy):
        li[legacy] = ""
    legacy_name = cfg.get("legacy_name_field")
    if legacy_name and li.get(legacy_name):
        li[legacy_name] = ""
    li["category_auto_mapped"] = True
    li["original_category_id"] = archived_cat.get("id")
    li["original_category_name"] = archived_cat.get("name")
