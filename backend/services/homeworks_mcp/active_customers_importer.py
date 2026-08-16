"""Feb-2026 · Phase 1b-B — Active-customers importer.

Sister module to ``inactive_customers_importer``. Same execution
mechanics (idempotent, resumable, rate-limited, cascade-safe, poison-
pill tolerant) but with three key differences:

1. **Filter**: ``CustomerStatus IN (ACTIVE, PENDING_APPROVAL)`` (not
   ``INACTIVE + WRITTEN_OFF``). Homeworks does not expose ``LEAD`` or
   ``PROSPECT`` as enum values — those live in ``CustomerSource`` /
   ``CustomerType`` tables, not the status enum. See dispatch report.
2. **Output status**: writes ``status = "active"`` to AquaTerra (was
   ``"inactive"``).
3. **Skipped children**: does NOT fetch or store notes, tags, or
   avatar photos. Only quotes, invoices, jobs, payments.

Idempotency contract: match by ``original_id`` on customers. On skip,
the child entities (quotes/invoices/jobs/payments) are ALSO skipped
so we can't double-import child data under an already-imported
customer. Tracked in ``customers_skipped`` +
``child_entities_skipped_due_to_parent_skip`` counters.

Written as a copy-paste of ``inactive_customers_importer`` rather
than a parameterization refactor — the inactive importer was locked
down in production 20 min ago and consolidating both into a single
config-driven module is a P2 backlog item, tracked separately.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.homeworks_mcp import queries
from services.homeworks_mcp.client import gql_query, MCPError, MCPToolError

logger = logging.getLogger("homeworks_mcp.active_importer")


# ── Config ───────────────────────────────────────────────────────────
PAGE_SIZE = 25
RATE_LIMIT_QPS = 5
CHECKPOINT_EVERY_N = 10
CHECKPOINT_EVERY_S = 60
CASCADE_STOP_AFTER_CONSECUTIVE_FAILS = 5
DRY_RUN_SAMPLE_SIZE = 5


# ── Report / progress models ─────────────────────────────────────────
@dataclass
class DryRunReport:
    inactive_customer_count: int = 0  # naming preserved for API parity
    existing_in_aquaterra_by_original_id: int = 0
    sample_customer_names: List[str] = field(default_factory=list)
    sample_avg_latency_ms: int = 0
    estimated_duration_minutes: int = 0
    status_filter: List[str] = field(
        default_factory=lambda: list(queries.ACTIVE_STATUS_VALUES),
    )
    output_status: str = "active"
    fatal_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Counters:
    customers_scanned: int = 0
    customers_imported: int = 0
    customers_skipped: int = 0
    customers_failed: int = 0
    jobs_imported: int = 0
    invoices_imported: int = 0
    payments_imported: int = 0
    quotes_imported: int = 0
    # Tracks children (jobs/invoices/quotes/payments) skipped because
    # their parent customer already existed. See idempotency contract
    # in module docstring.
    child_entities_skipped_due_to_parent_skip: int = 0


# ── Helpers ──────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


async def _customer_exists(tenant_id: str, homeworks_id: int) -> bool:
    row = await db.customers.find_one(
        {"tenant_id": tenant_id, "original_id": str(homeworks_id),
         "imported_from": "homeworks"},
        {"_id": 1},
    )
    return row is not None


# ── Dry-run ──────────────────────────────────────────────────────────
async def dry_run(tenant_id: str, *,
                   user_id: Optional[str] = None) -> DryRunReport:
    report = DryRunReport()
    try:
        # Count via id-only paginated scan. Cap at 50 pages of 1000 =
        # 50 000 to allow much larger active-customer datasets than
        # the inactive cohort.
        total = 0
        _COUNT_CAP_PAGES = 50
        _COUNT_PAGE = 1000
        for pg in range(_COUNT_CAP_PAGES):
            count_data = await gql_query(
                tenant_id=tenant_id,
                query=queries.ACTIVE_COUNT_PAGE_QUERY,
                variables={"skip": pg * _COUNT_PAGE, "take": _COUNT_PAGE},
                user_id=user_id,
            )
            rows = (count_data or {}).get("customers") or []
            total += len(rows)
            if len(rows) < _COUNT_PAGE:
                break
        report.inactive_customer_count = total

        latencies: List[float] = []
        page = await gql_query(
            tenant_id=tenant_id,
            query=queries.ACTIVE_CUSTOMER_PAGE_QUERY,
            variables={"skip": 0, "take": DRY_RUN_SAMPLE_SIZE},
            user_id=user_id,
        )
        page_rows = (page or {}).get("customers") or []
        for c in page_rows:
            report.sample_customer_names.append(c.get("fullName") or "")

        if page_rows:
            first_id = page_rows[0].get("id")
            t0 = time.monotonic()
            await asyncio.gather(
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_EVENTS_QUERY,
                          variables={"customerId": first_id},
                          user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_INVOICES_QUERY,
                          variables={"customerId": first_id},
                          user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_PAYMENTS_QUERY,
                          variables={"customerId": first_id},
                          user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_ESTIMATES_QUERY,
                          variables={"customerId": first_id},
                          user_id=user_id),
                return_exceptions=False,
            )
            latencies.append((time.monotonic() - t0) * 1000)

        # Existing-in-aquaterra count. Since the prior inactive import
        # already landed 1315 customers, this will be a positive
        # baseline. The sanity gate compares against the ACTIVE cohort
        # size, not this baseline, so it doesn't false-trigger.
        existing = await db.customers.count_documents(
            {"tenant_id": tenant_id,
             "imported_from": "homeworks"},
        )
        report.existing_in_aquaterra_by_original_id = int(existing)

        report.sample_avg_latency_ms = int(
            sum(latencies) / len(latencies)) if latencies else 0
        per_customer_secs = max(
            (report.sample_avg_latency_ms / 1000.0),
            1.0 / RATE_LIMIT_QPS * 5,
        )
        report.estimated_duration_minutes = int(
            report.inactive_customer_count * per_customer_secs / 60,
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
        "kind": "active_customers",  # distinguish from inactive runs
        "status_filter": list(queries.ACTIVE_STATUS_VALUES),
        "output_status": "active",
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


# ── Import — per customer ────────────────────────────────────────────
def _map_customer(c: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    now = _now_iso()
    addr = c.get("address") or {}
    loc = c.get("location") or None
    location_mapped: Optional[Dict[str, Any]] = None
    if loc and (loc.get("latitude") is not None
                 or loc.get("longitude") is not None):
        location_mapped = {
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
        }
    street_parts = [addr.get("street1") or "", addr.get("street2") or ""]
    street_joined = " ".join(p for p in street_parts if p).strip()
    return {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "imported_from": "homeworks",
        "original_id": str(c.get("id")),
        "imported_at": now,
        "created_at": now,
        "updated_at": now,
        "status": "active",  # Phase 1b-B: active-cohort default
        "homeworks_status": c.get("status"),
        "email": (c.get("email") or "").strip() or None,
        "first_name": c.get("firstName") or "",
        "last_name": c.get("lastName") or "",
        "name": c.get("fullName") or "",
        "phone": c.get("phone") or "",
        "cell": c.get("cell") or "",
        "address": street_joined,
        "city": addr.get("city") or "",
        "state": addr.get("state") or "",
        "zip": addr.get("zip") or "",
        "country": addr.get("country") or "",
        "location": location_mapped,
        # NOTE: description is intentionally NOT copied — user asked
        # to skip notes. If we later want to hydrate descriptions,
        # add a P2 migration to fill them from Homeworks by
        # original_id.
        # NOTE: tags intentionally omitted per user dispatch.
        # NOTE: pic / avatar_url_source intentionally omitted — user
        # said skip photos.
        # Financial rollups — read-only snapshot for reporting.
        "homeworks_outstanding": c.get("outstanding"),
        "homeworks_lifetime_paid": c.get("lifetimePaid"),
    }


async def _import_one_customer(
    *,
    tenant_id: str,
    user_id: Optional[str],
    customer: Dict[str, Any],
    limiter: _RateLimiter,
    counters: Counters,
) -> None:
    hw_id = customer.get("id")
    if hw_id is None:
        counters.customers_failed += 1
        raise RuntimeError("customer_missing_id")

    if await _customer_exists(tenant_id, hw_id):
        # Per user's idempotency contract Q3(a): "strict skip on
        # original_id match. Never overwrite. If a customer was
        # imported as inactive in the prior run and is now active in
        # Homeworks, leave them inactive in AquaTerra." We ALSO skip
        # all child entities under this parent so we can't double-
        # import quotes / invoices / jobs / payments under an already-
        # imported customer via a different code path.
        counters.customers_skipped += 1
        # Increment "would-have-imported-children" by 0 here — we
        # don't fetch them at all, so we can't count them. The
        # counter name reflects the semantic ("we skipped fetching
        # children because parent was already there").
        counters.child_entities_skipped_due_to_parent_skip += 1
        return

    at_customer = _map_customer(customer, tenant_id)
    await db.customers.insert_one(at_customer)
    aqua_customer_id = at_customer["id"]
    counters.customers_imported += 1

    # Fetch and insert children — 4 parallel queries. NO notes / tags
    # / avatar fetches per user dispatch.
    await limiter.wait()
    events, invoices, payments, estimates = await asyncio.gather(
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_EVENTS_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_INVOICES_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_PAYMENTS_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id,
                   query=queries.CUSTOMER_ESTIMATES_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        return_exceptions=False,
    )

    def _envelope(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for e in entities or []:
            out.append({
                **e,
                "id": uuid.uuid4().hex,
                "tenant_id": tenant_id,
                "customer_id": aqua_customer_id,
                "imported_from": "homeworks",
                "original_id": str(e.get("id")),
                "homeworks_customer_original_id": str(hw_id),
                "imported_at": _now_iso(),
                "created_at": _now_iso(),
            })
        return out

    job_rows = _envelope((events or {}).get("events") or [])
    if job_rows:
        # Strip dispatchNotes to honor "skip notes" — keep job rows
        # themselves though (that's the schedule).
        for j in job_rows:
            j.pop("dispatchNotes", None)
        await db.jobs.insert_many(job_rows)
        counters.jobs_imported += len(job_rows)

    inv_rows = _envelope((invoices or {}).get("invoices") or [])
    if inv_rows:
        await db.invoices.insert_many(inv_rows)
        counters.invoices_imported += len(inv_rows)

    pay_rows = _envelope((payments or {}).get("payments") or [])
    if pay_rows:
        await db.payments.insert_many(pay_rows)
        counters.payments_imported += len(pay_rows)

    est_rows = _envelope((estimates or {}).get("estimates") or [])
    if est_rows:
        await db.quotes.insert_many(est_rows)
        counters.quotes_imported += len(est_rows)


# ── Run driver ───────────────────────────────────────────────────────
async def run_full(*, tenant_id: str, user_id: Optional[str],
                    run_id: str) -> Counters:
    limiter = _RateLimiter(RATE_LIMIT_QPS)
    counters = Counters()
    consecutive_fails = 0
    last_ckpt_t = time.monotonic()

    doc = await _load_run(run_id)
    if not doc:
        raise RuntimeError(f"run_not_found:{run_id}")
    counters = Counters(**(doc.get("counters") or {}))
    skip = int(doc.get("resume_cursor") or 0)
    if doc.get("status") == "queued":
        await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                           status="running")

    while True:
        if await _cancel_flag_set(run_id):
            await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                               status="cancelled", finished_at=_now_iso())
            return counters

        await limiter.wait()
        page = None
        _PAGE_RETRIES = 3
        effective_take = PAGE_SIZE
        last_page_exc: Optional[Exception] = None
        while effective_take >= 1:
            last_page_exc = None
            for retry in range(_PAGE_RETRIES):
                try:
                    page = await gql_query(
                        tenant_id=tenant_id,
                        query=queries.ACTIVE_CUSTOMER_PAGE_QUERY,
                        variables={"skip": skip, "take": effective_take},
                        user_id=user_id,
                    )
                    last_page_exc = None
                    break
                except (MCPError, MCPToolError) as exc:
                    last_page_exc = exc
                    if retry < _PAGE_RETRIES - 1:
                        backoff = 2.0 * (2 ** retry)
                        logger.warning(
                            "[active-importer] page fetch skip=%d take=%d "
                            "retry=%d/%d err=%s — backing off %.1fs",
                            skip, effective_take, retry + 1,
                            _PAGE_RETRIES, str(exc)[:120], backoff,
                        )
                        await asyncio.sleep(backoff)
            if last_page_exc is None:
                break
            if effective_take == 1:
                break
            effective_take = max(1, effective_take // 2)
            logger.warning(
                "[active-importer] halving page size skip=%d → take=%d",
                skip, effective_take,
            )
        if last_page_exc is not None:
            logger.error(
                "[active-importer] poison-pill row at skip=%d take=1 "
                "err=%s — skipping row and advancing",
                skip, str(last_page_exc)[:200],
            )
            counters.customers_scanned += 1
            counters.customers_failed += 1
            await _checkpoint(
                run_id, counters=counters, resume_cursor=skip + 1,
                error={"stage": "poison_pill_page",
                       "skip": skip, "take": 1,
                       "error": str(last_page_exc)[:500],
                       "at": _now_iso()},
            )
            skip += 1
            continue

        rows = (page or {}).get("customers") or []
        if not rows:
            await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                               status="succeeded", finished_at=_now_iso())
            return counters

        for c in rows:
            counters.customers_scanned += 1
            try:
                await _import_one_customer(
                    tenant_id=tenant_id, user_id=user_id,
                    customer=c, limiter=limiter, counters=counters,
                )
                consecutive_fails = 0
            except Exception as exc:  # noqa: BLE001
                counters.customers_failed += 1
                consecutive_fails += 1
                await _checkpoint(
                    run_id, counters=counters, resume_cursor=skip,
                    error={"customer_original_id": str(c.get("id")),
                           "error": str(exc), "at": _now_iso()},
                )
                if consecutive_fails >= CASCADE_STOP_AFTER_CONSECUTIVE_FAILS:
                    await _checkpoint(
                        run_id, counters=counters, resume_cursor=skip,
                        status="paused_needs_attention",
                        finished_at=_now_iso(),
                    )
                    return counters
            n_since = counters.customers_scanned % CHECKPOINT_EVERY_N
            if (n_since == 0 or
                (time.monotonic() - last_ckpt_t) >= CHECKPOINT_EVERY_S):
                await _checkpoint(
                    run_id, counters=counters, resume_cursor=skip,
                )
                last_ckpt_t = time.monotonic()

            if await _cancel_flag_set(run_id):
                await _checkpoint(
                    run_id, counters=counters, resume_cursor=skip,
                    status="cancelled", finished_at=_now_iso(),
                )
                return counters

        skip += len(rows)
        if len(rows) < effective_take:
            await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                               status="succeeded", finished_at=_now_iso())
            return counters
