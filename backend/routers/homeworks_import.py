"""Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.

Endpoints (all under ``/api/imports/homeworks/*``, admin + super_admin
gated):
  * POST   /batches                        — create pending batch
  * GET    /batches                        — list tenant batches
  * GET    /batches/{id}                   — detail + latest 100 staging rows
  * POST   /batches/{id}/rollback          — purge all import_batch_id rows

Also:
  * POST   /credentials                    — upsert Fernet-encrypted email+password
  * GET    /credentials                    — presence check (no plaintext)

Scaffold only — no scraping logic. Batches stay in ``pending`` state
until Phase 55-b lands the customer scraper. Rollback is safe to
call on empty or half-filled batches — it's a per-collection
``delete_many({import_batch_id: id})`` sweep + a state flip.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from config import db, logger
from routers.tenants import get_current_tenant
from services.suppliers.crypto import decrypt, encrypt
from utils import get_current_user, require_admin


router = APIRouter()

VALID_ENTITY_TYPES = frozenset({
    "customers", "properties", "jobs", "recurring_schedules",
    "invoices", "payments", "quotes", "attachments",
})
_COLLECTIONS_WITH_BATCH_ID = (
    "customers", "properties", "customer_locations", "jobs",
    "recurring_schedules", "invoices", "payments", "quotes",
    "customer_notes", "job_notes", "homeworks_staging",
)

# Phase 55-f · Commit engine.
#
# Entity → target collection map. ``attachments`` is intentionally
# absent because photo/media handoff is Phase 55-e, not 55-f.
_ENTITY_TO_COLLECTION: Dict[str, str] = {
    "customers": "customers",
    "properties": "properties",
    "jobs": "jobs",
    "recurring_schedules": "recurring_schedules",
    "invoices": "invoices",
    "payments": "payments",
    "quotes": "quotes",
}

# FK-safe processing order. Customers come first because every other
# entity references them; jobs come before invoices because invoice
# lines can reference completed jobs; payments come last because they
# reference invoices.
_ENTITY_ORDER: List[str] = [
    "customers", "properties", "recurring_schedules",
    "jobs", "quotes", "invoices", "payments",
]

# Customer merge policy — spec-locked in Phase 55 design doc §4.1:
# "MERGE (extend tags, append notes, DO NOT overwrite first/last name
# or address unless empty)." These fields are protected from
# destructive overwrites when ``dedupe_status == matched``.
_PROTECTED_CUSTOMER_FIELDS = frozenset({
    "first_name", "last_name", "name", "email", "phone",
    "billing_address", "address",
})


def _customer_merge_update(existing: Dict[str, Any],
                            mapped: Dict[str, Any]) -> Dict[str, Any]:
    """Return the $set patch to merge ``mapped`` onto ``existing``
    without overwriting protected non-null fields. Tags dedupe-merge,
    notes append."""
    upd: Dict[str, Any] = {}
    for k, v in (mapped or {}).items():
        if k in _PROTECTED_CUSTOMER_FIELDS:
            if v and not existing.get(k):
                upd[k] = v
            continue
        if k == "tags":
            merged = sorted({*(existing.get("tags") or []),
                              *(v or [])})
            upd["tags"] = merged
            continue
        if k == "notes":
            existing_notes = existing.get("notes") or ""
            if v and v not in existing_notes:
                combined = (f"{existing_notes}\n{v}".strip()
                              if existing_notes else v)
                upd["notes"] = combined
            continue
        if v is not None:
            upd[k] = v
    return upd


def _generic_merge_update(existing: Dict[str, Any],
                           mapped: Dict[str, Any]) -> Dict[str, Any]:
    """Conservative merge for non-customer entities — only fill blanks."""
    upd: Dict[str, Any] = {}
    for k, v in (mapped or {}).items():
        if v is not None and not existing.get(k):
            upd[k] = v
    return upd


async def _process_staging_row(
    row: Dict[str, Any], tenant_id: str, batch_id: str,
) -> Dict[str, Any]:
    """Apply one staging row to its target collection.

    Returns ``{"ok": bool, "err": Optional[str], "outcome": str}``.
    * ``ok == True``, ``err == None``  → clean success (new/matched).
    * ``ok == True``, ``err == str``   → intentional skip (conflict,
      unknown entity type, matched-but-missing target). Row is marked
      as ``imported_at``; ``commit_error`` records the reason. Resume
      will NOT retry.
    * ``ok == False``                  → unexpected exception; row is
      NOT marked ``imported_at``. Resume WILL retry.
    """
    et = row.get("entity_type") or ""
    coll_name = _ENTITY_TO_COLLECTION.get(et)
    if not coll_name:
        return {"ok": True, "err": "unknown_entity_type",
                 "outcome": "skipped"}
    ds = row.get("dedupe_status") or "new"
    if ds == "conflict":
        return {"ok": True, "err": "conflict_skipped",
                 "outcome": "skipped"}
    mapped = row.get("mapped_payload") or {}
    coll = db[coll_name]
    try:
        if ds == "matched":
            target_id = row.get("matched_target_id")
            if not target_id:
                return {"ok": True, "err": "matched_but_no_target_id",
                         "outcome": "skipped"}
            existing = await coll.find_one(
                {"tenant_id": tenant_id, "id": target_id},
                {"_id": 0},
            )
            if not existing:
                return {"ok": True, "err": "matched_target_missing",
                         "outcome": "skipped"}
            merge = (_customer_merge_update(existing, mapped)
                      if et == "customers"
                      else _generic_merge_update(existing, mapped))
            if merge:
                merge["import_batch_id"] = batch_id
                await coll.update_one(
                    {"tenant_id": tenant_id, "id": target_id},
                    {"$set": merge},
                )
            return {"ok": True, "err": None, "outcome": "merged"}
        # Default → dedupe_status == "new" → insert.
        doc = dict(mapped)
        doc["tenant_id"] = tenant_id
        doc["import_batch_id"] = batch_id
        doc.setdefault("id", uuid.uuid4().hex)
        await coll.insert_one(doc)
        return {"ok": True, "err": None, "outcome": "inserted"}
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "err": str(e)[:200], "outcome": "error"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _NewBatchIn(BaseModel):
    entity_types_planned: List[str] = list(VALID_ENTITY_TYPES)


class _CredsIn(BaseModel):
    email: EmailStr
    password: str


# ─── Batches ────────────────────────────────────────────────────────────
@router.post("/imports/homeworks/batches")
async def create_batch(
    body: _NewBatchIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    bad = [t for t in body.entity_types_planned if t not in VALID_ENTITY_TYPES]
    if bad:
        raise HTTPException(400, {"error": "invalid_entity_types",
                                    "unknown": bad})
    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant["id"],
        "source": "copilot_crm",
        "state": "pending",
        "entity_types_planned": list(body.entity_types_planned),
        "entity_counts": {t: 0 for t in body.entity_types_planned},
        "started_at": None,
        "completed_at": None,
        "created_at": _now_iso(),
        "created_by_user_id": user.get("id"),
    }
    await db.import_batches.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/imports/homeworks/batches")
async def list_batches(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    cursor = db.import_batches.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0},
    ).sort("created_at", -1)
    async for d in cursor:
        rows.append(d)
    return {"batches": rows}


@router.get("/imports/homeworks/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, {"error": "batch_not_found"})
    # Latest 100 staging rows for the batch — powers the detail drawer.
    staging: List[Dict[str, Any]] = []
    cursor = db.homeworks_staging.find(
        {"tenant_id": tenant["id"], "batch_id": batch_id},
        {"_id": 0, "raw_payload": 0},   # drop payload for list view
    ).sort("imported_at", -1)
    async for s in cursor:
        staging.append(s)
        if len(staging) >= 100:
            break
    return {**row, "staging_latest": staging}


@router.post("/imports/homeworks/batches/{batch_id}/rollback")
async def rollback_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0, "id": 1, "state": 1},
    )
    if not row:
        raise HTTPException(404, {"error": "batch_not_found"})
    # Idempotent — rollback of an already-rolled batch is a no-op.
    if row.get("state") == "rolled_back":
        return {"ok": True, "batch_id": batch_id,
                 "already_rolled_back": True, "purged_counts": {}}

    purged: Dict[str, int] = {}
    for coll_name in _COLLECTIONS_WITH_BATCH_ID:
        # Staging rows carry ``batch_id`` (they're OWNED by the batch);
        # every other collection carries the ``import_batch_id`` FK
        # (added in Phase 55-a).
        fk_key = "batch_id" if coll_name == "homeworks_staging" \
            else "import_batch_id"
        try:
            r = await db[coll_name].delete_many(
                {"tenant_id": tenant["id"], fk_key: batch_id},
            )
            purged[coll_name] = int(getattr(r, "deleted_count", 0) or 0)
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"[homeworks rollback] {coll_name}: {e}")
            purged[coll_name] = 0

    await db.import_batches.update_one(
        {"id": batch_id, "tenant_id": tenant["id"]},
        {"$set": {"state": "rolled_back",
                    "rolled_back_at": _now_iso(),
                    "rolled_back_by_user_id": user.get("id"),
                    "purged_counts": purged}},
    )
    return {"ok": True, "batch_id": batch_id, "purged_counts": purged}


# ─── Dry-run + Commit + Progress (Phase 55-f) ──────────────────────────
@router.get("/imports/homeworks/batches/{batch_id}/dryrun")
async def dryrun_report(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Aggregate staging rows for the batch by ``entity_type`` ×
    ``dedupe_status`` and surface warnings (prior commit errors,
    matched-but-missing targets)."""
    batch = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not batch:
        raise HTTPException(404, {"error": "batch_not_found"})
    counts: Dict[str, Dict[str, int]] = {}
    warnings: List[Dict[str, Any]] = []
    cursor = db.homeworks_staging.find(
        {"tenant_id": tenant["id"], "batch_id": batch_id},
        {"_id": 0},
    )
    async for row in cursor:
        et = row.get("entity_type") or "unknown"
        ds = row.get("dedupe_status") or "new"
        bucket = counts.setdefault(et, {
            "new": 0, "matched": 0, "conflict": 0, "total": 0,
        })
        if ds in bucket:
            bucket[ds] += 1
        else:
            bucket[ds] = bucket.get(ds, 0) + 1
        bucket["total"] += 1
        if row.get("commit_error"):
            warnings.append({
                "type": "prior_commit_error",
                "staging_id": row.get("id"),
                "entity_type": et,
                "error": row.get("commit_error"),
            })
    return {
        "batch_id": batch_id, "state": batch.get("state"),
        "entity_counts": counts, "warnings": warnings,
        "error_count": batch.get("error_count") or 0,
    }


@router.post("/imports/homeworks/batches/{batch_id}/commit")
async def commit_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Iterate staging rows, apply ``mapped_payload`` to the target
    collections. Only valid from ``paused`` state, or from
    ``committed`` state when unprocessed rows exist (resume path)."""
    batch = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not batch:
        raise HTTPException(404, {"error": "batch_not_found"})
    state = batch.get("state") or "pending"
    if state not in ("paused", "committed"):
        raise HTTPException(400, {"error": "not_committable",
                                    "state": state})

    now_start = _now_iso()
    if not batch.get("started_at"):
        await db.import_batches.update_one(
            {"tenant_id": tenant["id"], "id": batch_id},
            {"$set": {"started_at": now_start}},
        )

    completed = dict(batch.get("entity_counts_completed") or {})
    error_count = int(batch.get("error_count") or 0)

    # Process in FK-safe order per entity type. Only rows without
    # ``imported_at`` are pulled → resume-safe.
    for et in _ENTITY_ORDER:
        cursor = db.homeworks_staging.find(
            {"tenant_id": tenant["id"], "batch_id": batch_id,
              "entity_type": et, "imported_at": None},
            {"_id": 0},
        )
        et_done = int(completed.get(et, 0))
        rows_in_et: List[Dict[str, Any]] = []
        async for row in cursor:
            rows_in_et.append(row)
        for idx, row in enumerate(rows_in_et):
            result = await _process_staging_row(row, tenant["id"], batch_id)
            update_row: Dict[str, Any] = {}
            if result["ok"]:
                update_row["imported_at"] = _now_iso()
                if result.get("err"):
                    update_row["commit_error"] = result["err"]
                et_done += 1
            else:
                update_row["commit_error"] = result.get("err") \
                    or "unknown_error"
                error_count += 1
            await db.homeworks_staging.update_one(
                {"tenant_id": tenant["id"], "id": row["id"]},
                {"$set": update_row},
            )
            completed[et] = et_done
            # Cheap 50-row heartbeat back onto the batch doc — powers
            # the ``/progress`` poll on the client.
            if (idx + 1) % 50 == 0:
                await db.import_batches.update_one(
                    {"tenant_id": tenant["id"], "id": batch_id},
                    {"$set": {
                        "entity_counts_completed": completed,
                        "current_entity_type": et,
                        "error_count": error_count,
                    }},
                )
        # End-of-entity heartbeat.
        await db.import_batches.update_one(
            {"tenant_id": tenant["id"], "id": batch_id},
            {"$set": {
                "entity_counts_completed": completed,
                "current_entity_type": et,
                "error_count": error_count,
            }},
        )

    now_end = _now_iso()
    await db.import_batches.update_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"$set": {
            "state": "committed",
            "completed_at": now_end,
            "entity_counts_completed": completed,
            "error_count": error_count,
        }},
    )
    return {
        "ok": True, "batch_id": batch_id, "state": "committed",
        "entity_counts_completed": completed, "error_count": error_count,
    }


@router.get("/imports/homeworks/batches/{batch_id}/progress")
async def batch_progress(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Cheap poll target. Frontend hits this every 2s while state is
    still ``paused`` (mid-commit) and stops once ``state == committed``
    or ``rolled_back``."""
    row = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, {"error": "batch_not_found"})
    return {
        "batch_id": batch_id,
        "state": row.get("state"),
        "entity_counts_completed": row.get("entity_counts_completed") or {},
        "entity_counts_total": row.get("entity_counts_total") or {},
        "entity_counts_scraped": row.get("entity_counts_scraped") or {},
        "current_entity_type": row.get("current_entity_type"),
        "error_count": row.get("error_count") or 0,
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "challenge_required": row.get("state") == "paused_challenge",
    }


# ─── Scrape orchestrator (Phase 55-b) ──────────────────────────────────
async def _resolve_credentials(
    tenant_id: str,
) -> Optional[Dict[str, str]]:
    """Load Fernet-encrypted Copilot CRM credentials from
    ``homeworks_credentials`` and return the decrypted pair."""
    row = await db.homeworks_credentials.find_one(
        {"tenant_id": tenant_id},
        {"_id": 0, "encrypted_email": 1, "encrypted_password": 1},
    )
    if not row:
        return None
    email = decrypt(row.get("encrypted_email"))
    password = decrypt(row.get("encrypted_password"))
    if not email or not password:
        return None
    return {"email": email, "password": password}


async def _run_scrape(  # pragma: no cover — exercised via injected fake
    batch_id: str, tenant_id: str, scraper: Any,
) -> Dict[str, Any]:
    """Iterate the scraper + persist staging rows + apply dedupe.

    Kept as a standalone function so tests can inject a fake scraper
    object (see ``test_homeworks_scraper.py``) — no Playwright runtime
    is required for the unit tests.
    """
    from services.homeworks.dedupe import dedupe_customer

    from playwright.async_api import async_playwright   # type: ignore
    scraped: Dict[str, int] = {"customers": 0, "properties": 0}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent="AquaTerra-HomeworksImport/1.0")
            if scraper.session_cookies:
                try:
                    await context.add_cookies(scraper.session_cookies)
                except Exception:                                    # noqa: BLE001
                    pass
            page = await context.new_page()
            await scraper.authenticate(page)
            async for raw, mapped in scraper.iter_customers(page):
                await _persist_customer_row(
                    tenant_id, batch_id, raw, mapped, dedupe_customer)
                scraped["customers"] += 1
            async for raw, mapped in scraper.iter_properties(page):
                await _persist_property_row(
                    tenant_id, batch_id, raw, mapped)
                scraped["properties"] += 1
        finally:
            await browser.close()
    return scraped


async def _persist_customer_row(
    tenant_id: str, batch_id: str,
    raw: Dict[str, Any], mapped: Dict[str, Any],
    dedupe_fn: Any,
) -> None:
    """Insert a customer staging row + resolve dedupe. Pre-assigns a
    UUID on ``new`` rows so downstream property rows can FK-link
    before the commit engine runs."""
    ds, matched = await dedupe_fn(tenant_id, mapped, db)
    # Pre-assign the future customer id on ``new`` rows so property
    # staging rows can reference it BEFORE the commit engine inserts.
    if ds == "new" and not mapped.get("id"):
        mapped["id"] = uuid.uuid4().hex
    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "entity_type": "customers",
        "homeworks_id": raw.get("id"),
        "raw_payload": raw,
        "mapped_payload": mapped,
        "dedupe_status": ds,
        "matched_target_id": matched,
        "imported_at": None,
        "commit_error": None,
    }
    await db.homeworks_staging.insert_one(doc)


async def _persist_property_row(
    tenant_id: str, batch_id: str,
    raw: Dict[str, Any], mapped: Dict[str, Any],
) -> None:
    """Insert a property staging row with parent-customer FK resolved
    via lookup into the same batch's customer staging rows. Dedupe:
    ``homeworks_id`` in ``(tenant_id, batch_id)`` scope — properties
    NEVER dedupe by address."""
    hw_id = raw.get("id")
    existing = await db.homeworks_staging.find_one(
        {"tenant_id": tenant_id, "batch_id": batch_id,
          "entity_type": "properties", "homeworks_id": hw_id},
    )
    if existing:
        return  # duplicate scrape

    parent_hw_id = raw.get("customer_homeworks_id")
    parent_target_id: Optional[str] = None
    if parent_hw_id:
        parent = await db.homeworks_staging.find_one(
            {"tenant_id": tenant_id, "batch_id": batch_id,
              "entity_type": "customers",
              "homeworks_id": parent_hw_id},
            {"_id": 0, "matched_target_id": 1, "mapped_payload": 1,
              "dedupe_status": 1},
        )
        if parent:
            if parent.get("dedupe_status") == "matched":
                parent_target_id = parent.get("matched_target_id")
            elif parent.get("dedupe_status") == "new":
                parent_target_id = (parent.get("mapped_payload") or {}).get("id")
    mapped["customer_id"] = parent_target_id

    doc = {
        "id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "batch_id": batch_id,
        "entity_type": "properties",
        "homeworks_id": hw_id,
        "raw_payload": raw,
        "mapped_payload": mapped,
        "dedupe_status": "new",
        "matched_target_id": None,
        "imported_at": None,
        "commit_error": None,
    }
    await db.homeworks_staging.insert_one(doc)


@router.post("/imports/homeworks/batches/{batch_id}/scrape")
async def scrape_batch(
    batch_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Fire the Copilot CRM scraper for ``customers + properties``.

    State transitions:
      * ``pending`` → ``running`` at entry, → ``paused`` on success.
      * ``paused_challenge`` → ``running`` at entry (retry after
        operator solves the challenge via bookmarklet), → ``paused``
        on success.
      * ``running`` → 409 (concurrent scrape).
      * Any other → 400 ``not_scrapable``.

    On ``SupplierChallengeRequired`` the batch flips to
    ``paused_challenge`` and the response body carries
    ``{challenge_required: true, challenge_id, ttl_hint_minutes: 30}``
    so the frontend can open the Phase 54h-b handoff modal
    targeting the ``homeworks`` slug.
    """
    from services.homeworks.copilot_scraper import CopilotCRMScraper
    from services.suppliers.sessions import get_active_session
    from services.suppliers.challenge import SupplierChallengeRequired

    batch = await db.import_batches.find_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"_id": 0},
    )
    if not batch:
        raise HTTPException(404, {"error": "batch_not_found"})
    state = batch.get("state") or "pending"
    if state == "running":
        raise HTTPException(409, {"error": "scrape_in_progress"})
    if state not in ("pending", "paused_challenge"):
        raise HTTPException(400, {"error": "not_scrapable",
                                    "state": state})

    creds = await _resolve_credentials(tenant["id"])
    if not creds:
        raise HTTPException(400, {"error": "no_credentials",
                                    "message": (
                                        "Save your Copilot CRM login "
                                        "before scraping.")})

    session_cookies = await get_active_session(
        tenant["id"], "homeworks") or []
    scraper = CopilotCRMScraper(
        tenant_id=tenant["id"],
        email=creds["email"], password=creds["password"],
        session_cookies=session_cookies,
    )

    now = _now_iso()
    await db.import_batches.update_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"$set": {"state": "running",
                    "started_at": batch.get("started_at") or now}},
    )

    try:
        scraped = await _run_scrape(batch_id, tenant["id"], scraper)
    except SupplierChallengeRequired as e:
        await db.import_batches.update_one(
            {"tenant_id": tenant["id"], "id": batch_id},
            {"$set": {"state": "paused_challenge"}},
        )
        return {
            "ok": False,
            "challenge_required": True,
            "challenge_id": e.challenge_id,
            "slug": "homeworks",
            "supplier_slug": "homeworks",
            "batch_id": batch_id,
            "ttl_hint_minutes": 30,
        }
    except Exception as e:                                          # noqa: BLE001
        logger.warning(f"[homeworks scrape] {batch_id}: {e}")
        await db.import_batches.update_one(
            {"tenant_id": tenant["id"], "id": batch_id},
            {"$set": {"state": "pending",
                        "last_scrape_error": str(e)[:400]}},
        )
        raise HTTPException(500, {"error": "scrape_failed",
                                    "message": str(e)[:200]})

    # Success — build entity_counts_total from staging + flip to paused.
    counts_total: Dict[str, int] = {"customers": 0, "properties": 0}
    async for _row in db.homeworks_staging.find(
        {"tenant_id": tenant["id"], "batch_id": batch_id},
        {"_id": 0, "entity_type": 1},
    ):
        et = _row.get("entity_type")
        if et in counts_total:
            counts_total[et] = counts_total.get(et, 0) + 1

    await db.import_batches.update_one(
        {"tenant_id": tenant["id"], "id": batch_id},
        {"$set": {"state": "paused",
                    "entity_counts_scraped": scraped,
                    "entity_counts_total": counts_total}},
    )
    return {
        "ok": True, "batch_id": batch_id, "state": "paused",
        "entity_counts_scraped": scraped,
        "entity_counts_total": counts_total,
    }


# ─── Credentials (Fernet-encrypted) ─────────────────────────────────────
@router.post("/imports/homeworks/credentials")
async def upsert_credentials(
    body: _CredsIn,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    now = _now_iso()
    doc = {
        "tenant_id": tenant["id"],
        "source": "copilot_crm",
        "encrypted_email": encrypt(str(body.email)),
        "encrypted_password": encrypt(body.password),
        "updated_at": now,
        "updated_by_user_id": user.get("id"),
    }
    existing = await db.homeworks_credentials.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0, "id": 1, "created_at": 1},
    )
    if existing:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or now
        await db.homeworks_credentials.update_one(
            {"tenant_id": tenant["id"]}, {"$set": doc})
    else:
        doc["id"] = uuid.uuid4().hex
        doc["created_at"] = now
        await db.homeworks_credentials.insert_one(doc)
    return {"ok": True, "updated_at": now}


@router.get("/imports/homeworks/credentials")
async def get_credentials(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    row = await db.homeworks_credentials.find_one(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "encrypted_email": 1, "updated_at": 1},
    )
    if not row:
        return {"has_credentials": False,
                 "email": None, "updated_at": None}
    # Return the decrypted email so admin can see WHICH account is
    # cached; password is never surfaced.
    email = decrypt(row.get("encrypted_email")) or ""
    return {"has_credentials": True, "email": email,
              "updated_at": row.get("updated_at")}
