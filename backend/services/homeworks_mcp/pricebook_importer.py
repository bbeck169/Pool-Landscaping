"""Queue Item 5b · Feb-2026 — Pricebook (income items) importer.

Sister to the customer importers. Mirrors their execution mechanics
(idempotent, resumable, rate-limited, checkpointed, cascade-safe,
poison-pill tolerant) applied to the Homeworks ``items`` query.

Filter contract (from user brief):
  * Only ACTIVE income items — Homeworks ``isDeleted:false`` (the
    schema default on ``ItemFilter``; we send it explicitly).
  * Skip on duplicate ``homeworks_original_id`` on AquaTerra.
  * Skip on **name collision** with any non-Homeworks-imported item
    on the same tenant (case-insensitive, trimmed). Logged as
    ``name_collision_with_existing_item`` on ``error_log`` so an
    operator can review and merge later.

Category mapping:
  * Case-insensitive + trim-whitespace match against
    ``db.service_categories`` on the same tenant.
  * Unknown categories fall to a catch-all ``Homeworks (unmapped)``
    service category created once per run (idempotent per tenant).

Data landed on ``db.items``:
  * ``unit_price``          — Homeworks ``price`` (Decimal → float)
  * ``wholesale_price``     — ``wholesaleCost`` if > 0 else ``materialCost``
  * ``tax_rate``            — Homeworks ``tax1`` (Decimal → float)
  * ``taxable``             — Homeworks ``isTaxable``
  * ``description``         — ``description`` (trimmed)
  * ``unit``                — ``unit``
  * ``category``            — human-readable string mirror (existing
                              ``items`` schema keeps it as a display
                              alias; the FK is ``service_category_id``)
  * ``service_category_id`` — mapped or catch-all
  * ``homeworks_original_id`` — string of Homeworks ``id``
  * ``homeworks_type``      — SERVICE | ITEM | LABOR | OTHER
  * ``homeworks_costs``     — full cost breakdown blob so nothing is
                              lost between import and later admin edit
  * ``supplier_prices``     — INTENTIONALLY LEFT EMPTY. The existing
                              multi-supplier validator requires a
                              ``pricebook_suppliers`` row + matching
                              ``income_category_id``. Both are
                              tenant-configured, so we don't force
                              them; admins can add supplier prices
                              post-import via the pricebook UI.
  * ``active``              — True
  * ``imported_from``       — "homeworks"
  * timestamps + tenant_id
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.homeworks_mcp import queries
from services.homeworks_mcp.client import gql_query, MCPError, MCPToolError
from services.homeworks_mcp import importer_base

logger = logging.getLogger("homeworks_mcp.pricebook_importer")


# ── Config ───────────────────────────────────────────────────────────
PAGE_SIZE = 100
RATE_LIMIT_QPS = 5
CHECKPOINT_EVERY_N = 50
CHECKPOINT_EVERY_S = 30
CASCADE_STOP_AFTER_CONSECUTIVE_FAILS = 5
DRY_RUN_SAMPLE_SIZE = 5
CATCH_ALL_CATEGORY_NAME = "Homeworks (unmapped)"

# Sanity gates (user brief) — enforced in the caller (router) but
# constants exported here so tests can lock them.
GATE_MIN_COUNT = 1
GATE_MAX_COUNT = 20_000
GATE_MAX_SAMPLE_LATENCY_MS = 2_000
GATE_MAX_NAME_COLLISION_PCT = 0.95


# ── Report / progress models ─────────────────────────────────────────
@dataclass
class DryRunReport:
    total_item_count: int = 0
    existing_in_aquaterra_by_original_id: int = 0
    name_collisions_estimated: int = 0
    name_collision_pct: float = 0.0
    sample_item_names: List[str] = field(default_factory=list)
    sample_avg_latency_ms: int = 0
    estimated_duration_minutes: int = 0
    item_types_seen: List[str] = field(default_factory=list)
    fatal_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Counters:
    items_scanned: int = 0
    items_imported: int = 0
    items_skipped_by_original_id: int = 0
    items_skipped_by_name_collision: int = 0
    items_failed: int = 0
    categories_created: int = 0


# ── Helpers ──────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


class _RateLimiter:
    def __init__(self, qps: int):
        self.min_gap = 1.0 / max(qps, 1)
        self._last = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < self.min_gap:
            await asyncio.sleep(self.min_gap - gap)
        self._last = time.monotonic()


async def _load_service_categories(tenant_id: str) -> Dict[str, str]:
    """Return {normalized_name: id} for every non-deleted category on
    the tenant. Used for fuzzy-match against Homeworks category names.
    """
    out: Dict[str, str] = {}
    async for row in db.service_categories.find(
        {"tenant_id": tenant_id,
         "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1},
    ):
        n = _norm(row.get("name"))
        if n:
            out[n] = row["id"]
    return out


async def _ensure_catch_all_category(tenant_id: str,
                                        cache: Dict[str, str]) -> str:
    """Idempotently seed ``Homeworks (unmapped)`` for this tenant.
    Cached inside ``cache`` so a single dry-run/run doesn't hit the
    DB twice for the same lookup."""
    key = _norm(CATCH_ALL_CATEGORY_NAME)
    if key in cache:
        return cache[key]
    existing = await db.service_categories.find_one(
        {"tenant_id": tenant_id, "name": CATCH_ALL_CATEGORY_NAME},
        {"_id": 0, "id": 1},
    )
    if existing:
        cache[key] = existing["id"]
        return existing["id"]
    new_id = uuid.uuid4().hex
    await db.service_categories.insert_one({
        "id": new_id,
        "tenant_id": tenant_id,
        "name": CATCH_ALL_CATEGORY_NAME,
        "description": "Auto-created by the Homeworks pricebook importer for items whose Homeworks category didn't match any AquaTerra service category. Rename or reassign anytime.",
        "created_at": _now_iso(),
        "created_by": "homeworks_pricebook_importer",
    })
    cache[key] = new_id
    return new_id


# ── Dry-run ──────────────────────────────────────────────────────────
async def dry_run(tenant_id: str, *,
                    user_id: Optional[str] = None) -> DryRunReport:
    report = DryRunReport()
    try:
        # Count via id-only paginated scan. Cap at 40 pages of 500 =
        # 20 000, which matches GATE_MAX_COUNT.
        total = 0
        _COUNT_CAP_PAGES = 40
        _COUNT_PAGE = 500
        for pg in range(_COUNT_CAP_PAGES):
            count_data = await gql_query(
                tenant_id=tenant_id,
                query=queries.ITEM_COUNT_PAGE_QUERY,
                variables={"skip": pg * _COUNT_PAGE, "take": _COUNT_PAGE},
                user_id=user_id,
            )
            rows = (count_data or {}).get("items") or []
            total += len(rows)
            if len(rows) < _COUNT_PAGE:
                break
        report.total_item_count = total

        # Sample fetch — measure per-page latency + surface a few names.
        latencies: List[float] = []
        types_seen: set = set()
        t0 = time.monotonic()
        page = await gql_query(
            tenant_id=tenant_id,
            query=queries.ITEM_PAGE_QUERY,
            variables={"skip": 0, "take": DRY_RUN_SAMPLE_SIZE},
            user_id=user_id,
        )
        latencies.append((time.monotonic() - t0) * 1000)
        sample_rows = (page or {}).get("items") or []
        for it in sample_rows:
            if it.get("name"):
                report.sample_item_names.append(it["name"])
            if it.get("type"):
                types_seen.add(it["type"])
        report.item_types_seen = sorted(types_seen)

        # Existing count on AquaTerra by original_id — filter also
        # ensures soft-deleted rows aren't counted.
        existing = await db.items.count_documents({
            "tenant_id": tenant_id,
            "imported_from": "homeworks",
            "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
        })
        report.existing_in_aquaterra_by_original_id = int(existing)

        # Name-collision estimate — pull all sample names and check
        # against non-Homeworks items on the tenant.
        if sample_rows:
            sample_names = [_norm(it.get("name")) for it in sample_rows
                              if it.get("name")]
            collisions = 0
            for n in sample_names:
                dup = await db.items.find_one({
                    "tenant_id": tenant_id,
                    "name": {"$regex": f"^{re.escape(n)}$",
                                "$options": "i"},
                    "$or": [
                        {"imported_from": {"$exists": False}},
                        {"imported_from": {"$ne": "homeworks"}},
                    ],
                    "$and": [{"$or": [{"deleted_at": None},
                                        {"deleted_at": {"$exists": False}}]}],
                }, {"_id": 0, "id": 1})
                if dup:
                    collisions += 1
            # Scale sample-rate estimate up to the full population.
            if sample_names:
                report.name_collision_pct = collisions / len(sample_names)
                report.name_collisions_estimated = int(
                    round(report.name_collision_pct * total))

        report.sample_avg_latency_ms = int(
            sum(latencies) / len(latencies)) if latencies else 0
        # Rough duration: one GQL page every 1/QPS seconds, plus ~10ms
        # per item for the local insert.
        per_item_secs = max(
            (report.sample_avg_latency_ms / 1000.0) / max(1, len(sample_rows)),
            1.0 / RATE_LIMIT_QPS,
        )
        report.estimated_duration_minutes = int(
            report.total_item_count * per_item_secs / 60,
        )
    except MCPError as exc:
        report.fatal_error = f"mcp:{exc}"
    except MCPToolError as exc:
        report.fatal_error = f"mcp_tool:{exc}"
    return report


# ── Run persistence ──────────────────────────────────────────────────
async def create_run(*, tenant_id: str, user_id: Optional[str],
                      dry_run_report: Optional[DryRunReport],
                      status: str = "queued") -> str:
    run_id = uuid.uuid4().hex
    doc = {
        "run_id": run_id,
        "tenant_id": tenant_id,
        "started_at": _now_iso(),
        "finished_at": None,
        "status": status,
        "kind": "pricebook",
        "dry_run_report": dry_run_report.to_dict() if dry_run_report else None,
        "counters": asdict(Counters()),
        "resume_cursor": 0,
        "error_log": [],
        "started_by_user_id": user_id,
        "updated_at": _now_iso(),
    }
    await db.homeworks_import_runs.insert_one(doc)
    return run_id


async def _load_run(run_id: str) -> Optional[Dict[str, Any]]:
    return await db.homeworks_import_runs.find_one(
        {"run_id": run_id}, {"_id": 0},
    )


async def _checkpoint(run_id: str, *,
                       counters: Counters, resume_cursor: int,
                       status: Optional[str] = None,
                       error: Optional[Dict[str, Any]] = None,
                       finished_at: Optional[str] = None) -> None:
    upd: Dict[str, Any] = {
        "counters": asdict(counters),
        "resume_cursor": resume_cursor,
        "updated_at": _now_iso(),
    }
    if status:
        upd["status"] = status
    if finished_at:
        upd["finished_at"] = finished_at
    ops: Dict[str, Any] = {"$set": upd}
    if error:
        ops["$push"] = {"error_log": error}
    await db.homeworks_import_runs.update_one({"run_id": run_id}, ops)


async def _cancel_flag_set(run_id: str) -> bool:
    doc = await db.homeworks_import_runs.find_one(
        {"run_id": run_id}, {"status": 1},
    )
    return bool(doc) and doc.get("status") in {
        "cancelling", "cancelled", "paused_needs_attention",
    }


# ── Mapping ──────────────────────────────────────────────────────────
def _to_float(x: Any, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _map_item(it: Dict[str, Any], tenant_id: str,
                service_category_id: str) -> Dict[str, Any]:
    now = _now_iso()
    price = _to_float(it.get("price"))
    wholesale = _to_float(it.get("wholesaleCost"))
    if wholesale <= 0:
        wholesale = _to_float(it.get("materialCost"))
    return {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "imported_from": "homeworks",
        "homeworks_original_id": str(it.get("id")),
        "homeworks_type": it.get("type"),
        "imported_at": now,
        "created_at": now,
        "updated_at": now,
        "active": True,
        "name": (it.get("name") or "").strip(),
        "description": (it.get("description") or "").strip(),
        "unit": (it.get("unit") or "").strip() or "each",
        "unit_price": price,
        "wholesale_price": wholesale,
        "tax_rate": _to_float(it.get("tax1")),
        "taxable": bool(it.get("isTaxable")),
        "category": ((it.get("category") or {}).get("name") or "").strip(),
        "service_category_id": service_category_id,
        # supplier_prices intentionally left empty — see module docstring.
        "supplier_prices": [],
        "homeworks_costs": {
            "materialCost": _to_float(it.get("materialCost")),
            "equipmentCost": _to_float(it.get("equipmentCost")),
            "subcontractCost": _to_float(it.get("subcontractCost")),
            "wholesaleCost": _to_float(it.get("wholesaleCost")),
            "markup": _to_float(it.get("markup")),
            "markupType": it.get("markupType"),
            "tax1": _to_float(it.get("tax1")),
            "tax2": _to_float(it.get("tax2")),
        },
    }


async def _import_one_item(
    *,
    tenant_id: str,
    item: Dict[str, Any],
    counters: Counters,
    cat_lookup: Dict[str, str],
    cat_cache: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Returns an error dict (for error_log push) when the row was
    skipped due to a name collision, else None. Failures raise."""
    hw_id = item.get("id")
    if hw_id is None:
        counters.items_failed += 1
        raise RuntimeError("item_missing_id")

    # Idempotency: skip if we've already imported this Homeworks item.
    dup_by_original = await db.items.find_one({
        "tenant_id": tenant_id,
        "imported_from": "homeworks",
        "homeworks_original_id": str(hw_id),
    }, {"_id": 0, "id": 1})
    if dup_by_original:
        counters.items_skipped_by_original_id += 1
        return None

    name = (item.get("name") or "").strip()
    if not name:
        counters.items_failed += 1
        raise RuntimeError("item_missing_name")

    # Name collision: skip if a non-Homeworks item on the tenant
    # carries the same normalized name.
    dup_by_name = await db.items.find_one({
        "tenant_id": tenant_id,
        "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        "$or": [
            {"imported_from": {"$exists": False}},
            {"imported_from": {"$ne": "homeworks"}},
        ],
        "$and": [{"$or": [{"deleted_at": None},
                            {"deleted_at": {"$exists": False}}]}],
    }, {"_id": 0, "id": 1})
    if dup_by_name:
        counters.items_skipped_by_name_collision += 1
        return {
            "reason": "name_collision_with_existing_item",
            "homeworks_original_id": str(hw_id),
            "homeworks_name": name,
            "existing_item_id": dup_by_name["id"],
            "at": _now_iso(),
        }

    # Map category → service_category_id.
    hw_cat_name = _norm((item.get("category") or {}).get("name"))
    cat_id = cat_lookup.get(hw_cat_name) if hw_cat_name else None
    if not cat_id:
        cat_id = await _ensure_catch_all_category(tenant_id, cat_cache)
        counters.categories_created += (
            1 if cat_cache.get("__signalled__") is None else 0)
        # Signal once so we don't over-count — the seed itself is
        # idempotent so ``_ensure_catch_all_category`` returns without
        # inserting after the first call.
        cat_cache["__signalled__"] = True

    doc = _map_item(item, tenant_id, cat_id)
    await db.items.insert_one(doc)
    counters.items_imported += 1
    return None


# ── Driver ───────────────────────────────────────────────────────────
# Task 3 · Feb-2026 — Pricebook uses the shared paged-driver from
# ``importer_base``. The subclass-specific glue (mapping, dedup,
# category resolution) lives entirely in ``_import_one_item``.
_PRICEBOOK_DRIVER_CONFIG = importer_base.PagedDriverConfig(
    kind="pricebook",
    page_query=queries.ITEM_PAGE_QUERY,
    page_key="items",
    page_size=PAGE_SIZE,
    rate_limit_qps=RATE_LIMIT_QPS,
    checkpoint_every_s=CHECKPOINT_EVERY_S,
    cascade_stop_after=CASCADE_STOP_AFTER_CONSECUTIVE_FAILS,
    page_retries=3,
    counter_scanned="items_scanned",
    counter_failed="items_failed",
)


async def run_full(*, tenant_id: str, user_id: Optional[str],
                    run_id: str) -> Counters:
    counters = Counters()
    cat_lookup = await _load_service_categories(tenant_id)
    cat_cache: Dict[str, str] = {}

    async def _import_one(row: Dict[str, Any], ctrs: Counters):
        # Refresh the category lookup lazily when the catch-all was
        # freshly seeded in the last iteration.
        nonlocal cat_lookup
        if cat_cache.get("__signalled__"):
            cat_lookup = await _load_service_categories(tenant_id)
            cat_cache.pop("__signalled__", None)
        return await _import_one_item(
            tenant_id=tenant_id, item=row, counters=ctrs,
            cat_lookup=cat_lookup, cat_cache=cat_cache,
        )

    return await importer_base.run_paged_driver(
        db=db, gql_query=gql_query,
        tenant_id=tenant_id, user_id=user_id, run_id=run_id,
        config=_PRICEBOOK_DRIVER_CONFIG,
        counters=counters,
        import_one_fn=_import_one,
        exceptions=(MCPError, MCPToolError),
    )
