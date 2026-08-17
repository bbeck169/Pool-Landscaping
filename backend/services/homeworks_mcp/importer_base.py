"""Task 3 · Feb-2026 — Homeworks importer base primitives.

Extracts the shared runtime concerns that used to be duplicated
across ``active_customers_importer.py``, ``inactive_customers_importer.py``
and ``pricebook_importer.py``. Each subclass module continues to
own its domain-specific logic (mapping, dedup, sanity gates,
child-entity fanout, counters). This module provides:

  * ``PagedDriverConfig`` — dataclass describing everything the
    generic driver needs to know about a single importer.
  * ``run_paged_driver`` — reusable driver loop: rate-limit-aware
    paging, retry-with-halving-take fallback, poison-pill tolerance,
    cascade auto-stop, cancel-flag polling, resume-cursor honouring,
    time-based checkpointing.
  * Shared helpers: ``_now_iso``, ``_norm``, ``RateLimiter``,
    ``load_run``, ``checkpoint``, ``cancel_flag_set``.

Contract:
  * The generic driver never touches business state beyond the
    ``run_doc`` (``homeworks_import_runs`` collection). The subclass
    owns all mapping, insertion, and cross-collection writes.
  * The driver's ``import_one_fn`` returns ``None`` on success or a
    dict to push onto ``error_log`` (soft skip). Raising propagates
    the row to the driver's ``items_failed`` bookkeeping.

Migration plan:
  1. Pricebook importer — MIGRATED (see ``pricebook_importer.py``).
  2. Active/inactive customer importers — kept on their own
     drivers for now; they need a deeper refactor to fit the
     generic ``import_one_fn`` shape because their child-entity
     fanout (jobs / invoices / payments / quotes) shares a page
     boundary with the parent. Documented as follow-up in PRD.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("homeworks_mcp.importer_base")


# ── Shared helpers ───────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: Optional[str]) -> str:
    """Trim + collapse whitespace + lower-case. Used by every
    dedup / fuzzy-match path in the tree."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


class RateLimiter:
    """Simple ``qps``-bounded coroutine gate. Not thread-safe by
    design — each importer runs in a single event loop."""

    def __init__(self, qps: int):
        self.min_gap = 1.0 / max(qps, 1)
        self._last = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        gap = now - self._last
        if gap < self.min_gap:
            await asyncio.sleep(self.min_gap - gap)
        self._last = time.monotonic()


# ── Run-doc IO ───────────────────────────────────────────────────────
async def load_run(db, run_id: str) -> Optional[Dict[str, Any]]:
    return await db.homeworks_import_runs.find_one(
        {"run_id": run_id}, {"_id": 0},
    )


async def checkpoint(db, run_id: str, *,
                       counters: Any, resume_cursor: int,
                       status: Optional[str] = None,
                       error: Optional[Dict[str, Any]] = None,
                       finished_at: Optional[str] = None) -> None:
    """Serialise counters (dataclass or dict) + push an optional
    error_log entry. Idempotent."""
    if hasattr(counters, "__dataclass_fields__"):
        counters_d = asdict(counters)
    else:
        counters_d = dict(counters or {})
    upd: Dict[str, Any] = {
        "counters": counters_d,
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


async def cancel_flag_set(db, run_id: str) -> bool:
    doc = await db.homeworks_import_runs.find_one(
        {"run_id": run_id}, {"status": 1},
    )
    return bool(doc) and doc.get("status") in {
        "cancelling", "cancelled", "paused_needs_attention",
    }


# ── Paged driver ─────────────────────────────────────────────────────
@dataclass
class PagedDriverConfig:
    """Everything the generic driver needs to know about a specific
    importer. Every field is required so an accidentally-missing
    subclass field trips at import time, not at run time."""
    kind: str
    page_query: str
    page_key: str            # response key holding the row array
    page_size: int
    rate_limit_qps: int
    checkpoint_every_s: int
    cascade_stop_after: int
    page_retries: int
    # Bookkeeping field names on the subclass's ``Counters`` dataclass.
    counter_scanned: str
    counter_failed: str


async def run_paged_driver(
    *,
    db,
    gql_query,  # awaitable: gql_query(tenant_id, query, variables, user_id)
    tenant_id: str,
    user_id: Optional[str],
    run_id: str,
    config: PagedDriverConfig,
    counters,                                       # subclass Counters
    import_one_fn: Callable[[Dict[str, Any], Any],
                              Awaitable[Optional[Dict[str, Any]]]],
    exceptions=(),                                  # MCPError-like tuple
) -> Any:
    """Generic paged import loop. See module docstring for contract.
    Returns the mutated ``counters`` dataclass so the caller can
    surface it back to the router."""
    limiter = RateLimiter(config.rate_limit_qps)
    last_ckpt_t = time.monotonic()

    doc = await load_run(db, run_id)
    if not doc:
        raise RuntimeError(f"run_not_found:{run_id}")
    # Hydrate counters from the previous run doc if we're resuming.
    if doc.get("counters"):
        for k, v in (doc["counters"] or {}).items():
            if hasattr(counters, k):
                setattr(counters, k, v)
    skip = int(doc.get("resume_cursor") or 0)
    if doc.get("status") == "queued":
        await checkpoint(db, run_id, counters=counters,
                           resume_cursor=skip, status="running")

    consecutive_fails = 0

    while True:
        if await cancel_flag_set(db, run_id):
            await checkpoint(db, run_id, counters=counters,
                               resume_cursor=skip, status="cancelled",
                               finished_at=_now_iso())
            return counters

        await limiter.wait()

        # Page fetch with retries + halving-take fallback.
        page = None
        effective_take = config.page_size
        last_page_exc: Optional[Exception] = None
        while effective_take >= 1:
            last_page_exc = None
            for retry in range(config.page_retries):
                try:
                    page = await gql_query(
                        tenant_id=tenant_id,
                        query=config.page_query,
                        variables={"skip": skip, "take": effective_take},
                        user_id=user_id,
                    )
                    last_page_exc = None
                    break
                except exceptions as exc:  # noqa: BLE001
                    last_page_exc = exc
                    if retry < config.page_retries - 1:
                        backoff = 2.0 * (2 ** retry)
                        logger.warning(
                            "[%s] page fetch skip=%d take=%d "
                            "retry=%d/%d err=%s — backing off %.1fs",
                            config.kind, skip, effective_take,
                            retry + 1, config.page_retries,
                            str(exc)[:120], backoff,
                        )
                        await asyncio.sleep(backoff)
            if last_page_exc is None:
                break
            if effective_take == 1:
                break
            effective_take = max(1, effective_take // 2)
            logger.warning(
                "[%s] halving page size skip=%d → take=%d",
                config.kind, skip, effective_take,
            )

        if last_page_exc is not None:
            # Poison-pill row at take=1.
            setattr(counters, config.counter_scanned,
                       getattr(counters, config.counter_scanned) + 1)
            setattr(counters, config.counter_failed,
                       getattr(counters, config.counter_failed) + 1)
            await checkpoint(
                db, run_id, counters=counters, resume_cursor=skip + 1,
                error={"stage": "poison_pill_page",
                       "skip": skip, "take": 1,
                       "error": str(last_page_exc)[:500],
                       "at": _now_iso()},
            )
            consecutive_fails += 1
            if consecutive_fails >= config.cascade_stop_after:
                await checkpoint(
                    db, run_id, counters=counters, resume_cursor=skip + 1,
                    status="paused_needs_attention",
                    error={"stage": "cascade_stop",
                           "reason": f"{config.cascade_stop_after}+ consecutive page failures",
                           "at": _now_iso()},
                )
                return counters
            skip += 1
            continue
        consecutive_fails = 0

        rows: List[Dict[str, Any]] = (page or {}).get(config.page_key) or []
        if not rows:
            await checkpoint(
                db, run_id, counters=counters, resume_cursor=skip,
                status="completed", finished_at=_now_iso(),
            )
            return counters

        for row in rows:
            setattr(counters, config.counter_scanned,
                       getattr(counters, config.counter_scanned) + 1)
            try:
                err = await import_one_fn(row, counters)
                if err:
                    await checkpoint(
                        db, run_id, counters=counters,
                        resume_cursor=skip + rows.index(row) + 1,
                        error=err,
                    )
            except Exception as exc:  # noqa: BLE001
                setattr(counters, config.counter_failed,
                           getattr(counters, config.counter_failed) + 1)
                await checkpoint(
                    db, run_id, counters=counters,
                    resume_cursor=skip + rows.index(row) + 1,
                    error={"stage": "import_row",
                           "row_id": str(row.get("id")),
                           "error": str(exc)[:500],
                           "at": _now_iso()},
                )

        skip += len(rows)
        if (time.monotonic() - last_ckpt_t) >= config.checkpoint_every_s:
            await checkpoint(db, run_id, counters=counters,
                                resume_cursor=skip)
            last_ckpt_t = time.monotonic()

        if len(rows) < effective_take:
            await checkpoint(
                db, run_id, counters=counters, resume_cursor=skip,
                status="completed", finished_at=_now_iso(),
            )
            return counters
