"""Feb-2026 · Phase 1b — Inactive-customers importer.

Idempotent, resumable, rate-limited bulk importer for Homeworks
customers in ``status IN (INACTIVE, WRITTEN_OFF)`` AND ``isDeleted =
false``. Skips (never overwrites) any customer whose Homeworks
``id`` (as ``original_id``) already exists in AquaTerra's customers
collection.

Checkpointing: every 10 processed customers OR every 60 s (whichever
comes first) the importer flushes counters + resume cursor + timestamp
to ``db.homeworks_import_runs``. On process restart, ``run_full``
resumes from ``resume_cursor``.

Cancel: the driver checks ``homeworks_import_runs.status`` before each
customer fetch; ``cancelling`` → exit clean; ``paused_needs_attention``
→ set by the cascade auto-stop after 5 consecutive customer failures.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import db
from services.homeworks_mcp import queries
from services.homeworks_mcp.client import gql_query, MCPError, MCPToolError

logger = logging.getLogger("homeworks_mcp.importer")


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
    inactive_customer_count: int = 0
    existing_in_aquaterra_by_original_id: int = 0
    sample_customer_names: List[str] = field(default_factory=list)
    sample_avg_latency_ms: int = 0
    estimated_duration_minutes: int = 0
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
    photos_imported: int = 0
    notes_imported: int = 0
    tags_imported: int = 0


# ── Helpers ──────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _RateLimiter:
    """Simple token bucket-ish limiter for the MCP client."""
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
    """Idempotency check — has this Homeworks customer already landed?"""
    row = await db.customers.find_one(
        {"tenant_id": tenant_id, "original_id": str(homeworks_id),
         "imported_from": "homeworks"},
        {"_id": 1},
    )
    return row is not None


# ── Dry-run ──────────────────────────────────────────────────────────
async def dry_run(tenant_id: str, *, user_id: Optional[str] = None) -> DryRunReport:
    report = DryRunReport()
    try:
        # Count via id-only paginated scan (Homeworks lacks a scalar
        # customerCount). Cap at 20 pages of 1000 = 20 000 to avoid
        # runaway if the dataset is unexpectedly huge.
        total = 0
        _COUNT_CAP_PAGES = 20
        _COUNT_PAGE = 1000
        for pg in range(_COUNT_CAP_PAGES):
            count_data = await gql_query(
                tenant_id=tenant_id,
                query=queries.COUNT_PAGE_QUERY,
                variables={"skip": pg * _COUNT_PAGE, "take": _COUNT_PAGE},
                user_id=user_id,
            )
            rows = (count_data or {}).get("customers") or []
            total += len(rows)
            if len(rows) < _COUNT_PAGE:
                break
        report.inactive_customer_count = total

        # Sample latency + names.
        latencies: List[float] = []
        # We need actual data for the sample — fetch first page (skip 0).
        page = await gql_query(
            tenant_id=tenant_id,
            query=queries.CUSTOMER_PAGE_QUERY,
            variables={"skip": 0, "take": DRY_RUN_SAMPLE_SIZE},
            user_id=user_id,
        )
        page_rows = (page or {}).get("customers") or []
        for c in page_rows:
            report.sample_customer_names.append(c.get("fullName") or "")

        # Time the per-customer child fetches on ONE sample.
        if page_rows:
            first_id = page_rows[0].get("id")
            t0 = time.monotonic()
            await asyncio.gather(
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_EVENTS_QUERY,
                          variables={"customerId": first_id}, user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_INVOICES_QUERY,
                          variables={"customerId": first_id}, user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_PAYMENTS_QUERY,
                          variables={"customerId": first_id}, user_id=user_id),
                gql_query(tenant_id=tenant_id,
                          query=queries.CUSTOMER_ESTIMATES_QUERY,
                          variables={"customerId": first_id}, user_id=user_id),
                return_exceptions=False,
            )
            latencies.append((time.monotonic() - t0) * 1000)

        # Existing-in-aquaterra count. Since we no longer have the full
        # id list from COUNT_QUERY (it's just a scalar total), we
        # short-circuit against the AquaTerra side directly — count
        # every imported-from-homeworks customer that we already own.
        # This over-estimates when the source pool contains other
        # statuses too, but for the dry-run sanity gate ("skip if >90%
        # already exist") it's a safe upper bound.
        existing = await db.customers.count_documents(
            {"tenant_id": tenant_id,
             "imported_from": "homeworks"},
        )
        report.existing_in_aquaterra_by_original_id = int(existing)

        report.sample_avg_latency_ms = int(
            sum(latencies) / len(latencies)) if latencies else 0
        # Duration estimate: per-customer avg × total.
        per_customer_secs = max(
            (report.sample_avg_latency_ms / 1000.0),
            1.0 / RATE_LIMIT_QPS * 5,  # min gate: 4 child + 1 page share
        )
        report.estimated_duration_minutes = int(
            (report.inactive_customer_count
             - report.existing_in_aquaterra_by_original_id)
            * per_customer_secs / 60,
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
    # Homeworks returns Location as {name, latitude, longitude}. Coerce
    # to our internal {lat, lng} shape so downstream code doesn't care.
    location_mapped: Optional[Dict[str, Any]] = None
    if loc and (loc.get("latitude") is not None or loc.get("longitude") is not None):
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
        "status": "inactive",
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
        "description": c.get("description") or "",
        "tags": list(c.get("tags") or []),
        "avatar_url_source": c.get("pic") or None,
        # Financial rollups — read-only snapshot for reporting.
        "homeworks_outstanding": c.get("outstanding"),
        "homeworks_lifetime_paid": c.get("lifetimePaid"),
    }


async def _download_avatar(url: Optional[str]) -> Optional[bytes]:
    if not url or not url.startswith("http"):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as h:
            r = await h.get(url)
            if r.status_code == 200:
                return r.content
    except httpx.HTTPError:
        return None
    return None


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
        counters.customers_skipped += 1
        return

    # Insert core customer first so child insert failures don't orphan
    # the transaction. AquaTerra doesn't have Mongo transactions here,
    # so we accept a small window where a customer has partial children
    # on a mid-flight crash — the resume run will `_customer_exists`
    # short-circuit AND we skip re-fetching children. See idempotency
    # note in the module docstring.
    at_customer = _map_customer(customer, tenant_id)
    await db.customers.insert_one(at_customer)
    aqua_customer_id = at_customer["id"]
    counters.customers_imported += 1
    counters.tags_imported += len(at_customer["tags"])
    if at_customer.get("description"):
        counters.notes_imported += 1  # Customer.description counted as one note

    # Best-effort avatar download → object storage. If it fails we just
    # skip; the URL stays on the doc for later retry.
    pic_url = customer.get("pic")
    if pic_url:
        try:
            from services.object_storage import put_bytes  # type: ignore
            _bytes = await _download_avatar(pic_url)
            if _bytes:
                key = f"customers/{tenant_id}/{aqua_customer_id}/avatar.jpg"
                url = await put_bytes(key, _bytes, content_type="image/jpeg")
                await db.customers.update_one(
                    {"id": aqua_customer_id},
                    {"$set": {"avatar_url": url}},
                )
                counters.photos_imported += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[importer] avatar failed customer=%s: %s", hw_id, exc,
            )

    # Fetch and insert children — 4 parallel queries.
    await limiter.wait()
    events, invoices, payments, estimates = await asyncio.gather(
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_EVENTS_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_INVOICES_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_PAYMENTS_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        gql_query(tenant_id=tenant_id, query=queries.CUSTOMER_ESTIMATES_QUERY,
                   variables={"customerId": hw_id}, user_id=user_id),
        return_exceptions=False,
    )

    def _envelope(entities: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
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

    job_rows = _envelope((events or {}).get("events") or [], "job")
    if job_rows:
        await db.jobs.insert_many(job_rows)
        counters.jobs_imported += len(job_rows)
        counters.notes_imported += sum(len(j.get("dispatchNotes") or []) for j in job_rows)

    inv_rows = _envelope((invoices or {}).get("invoices") or [], "invoice")
    if inv_rows:
        await db.invoices.insert_many(inv_rows)
        counters.invoices_imported += len(inv_rows)

    pay_rows = _envelope((payments or {}).get("payments") or [], "payment")
    if pay_rows:
        await db.payments.insert_many(pay_rows)
        counters.payments_imported += len(pay_rows)

    est_rows = _envelope((estimates or {}).get("estimates") or [], "quote")
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
    # Only promote to `running` if we haven't already been told to
    # cancel — otherwise we'd clobber the caller's kill switch on our
    # very first checkpoint call.
    if doc.get("status") == "queued":
        await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                           status="running")

    while True:
        if await _cancel_flag_set(run_id):
            await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                               status="cancelled", finished_at=_now_iso())
            return counters

        await limiter.wait()
        # Retry the page fetch up to 3× with exponential backoff to
        # ride out transient upstream 5xx / Prisma engine panics.
        # If all 3 retries fail at the current PAGE_SIZE, HALVE the
        # take repeatedly (down to 1) — Homeworks has a known bug
        # where certain (skip, take) combinations panic their Prisma
        # engine but a smaller take at the same skip succeeds. Only
        # pause the whole run if even take=1 fails.
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
                        query=queries.CUSTOMER_PAGE_QUERY,
                        variables={"skip": skip, "take": effective_take},
                        user_id=user_id,
                    )
                    last_page_exc = None
                    break
                except (MCPError, MCPToolError) as exc:
                    last_page_exc = exc
                    if retry < _PAGE_RETRIES - 1:
                        backoff = 2.0 * (2 ** retry)  # 2s, 4s
                        logger.warning(
                            "[importer] page fetch skip=%d take=%d "
                            "retry=%d/%d err=%s — backing off %.1fs",
                            skip, effective_take, retry + 1,
                            _PAGE_RETRIES, str(exc)[:120], backoff,
                        )
                        await asyncio.sleep(backoff)
            if last_page_exc is None:
                break
            # All retries failed at this take. Halve and try again.
            if effective_take == 1:
                break
            effective_take = max(1, effective_take // 2)
            logger.warning(
                "[importer] halving page size skip=%d → take=%d",
                skip, effective_take,
            )
        if last_page_exc is not None:
            # Even take=1 failed — this is a "poison pill" row on the
            # Homeworks side. Log it, advance past it, and keep going.
            # Better to skip one bad row than to halt the whole run.
            logger.error(
                "[importer] poison-pill row at skip=%d take=1 err=%s "
                "— skipping row and advancing",
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
            # Periodic checkpoint.
            n_since = counters.customers_scanned % CHECKPOINT_EVERY_N
            if n_since == 0 or (time.monotonic() - last_ckpt_t) >= CHECKPOINT_EVERY_S:
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
            # last page (fewer rows returned than requested)
            await _checkpoint(run_id, counters=counters, resume_cursor=skip,
                               status="succeeded", finished_at=_now_iso())
            return counters
