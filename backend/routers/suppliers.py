"""Phase 54a · Feb-2026 — Wholesale supplier pricebook import (skeleton).

Six endpoints under ``/api/suppliers/*``:

    GET    /suppliers                          — list (auto-seeds on first read)
    GET    /suppliers/{slug}/credentials       — has_credentials + updated_at
    POST   /suppliers/{slug}/credentials       — save encrypted (never plaintext)
    DELETE /suppliers/{slug}/credentials       — remove
    POST   /suppliers/{slug}/sync              — kick manual sync (501 in 54a)
    GET    /suppliers/{slug}/sync-jobs         — audit log

Role gate: super_admin + admin only on every endpoint (write + read).
Manager / tech / customer → 403. Rationale: supplier credentials +
pricing intel are admin-only per user's locked scope.

No supplier network calls anywhere in this file. The sync endpoint
returns 501 with a pointer to the phase that owns the connector.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from services.suppliers.connector import CONNECTORS, SUPPLIER_SEED
from services.suppliers.crypto import decrypt, encrypt
from utils import get_current_user

router = APIRouter()

_EDITOR_ROLES = frozenset({"admin", "super_admin"})
_VALID_SLUGS = frozenset(s["slug"] for s in SUPPLIER_SEED)
_INDEXES_ENSURED = False


def _require_admin(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _EDITOR_ROLES:
        raise HTTPException(status_code=403, detail={"error": "forbidden"})


def _require_tenant(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


def _require_slug(slug: str) -> None:
    if slug not in _VALID_SLUGS:
        raise HTTPException(404, {"error": "unknown_supplier",
                                    "known": sorted(_VALID_SLUGS)})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_indexes() -> None:
    global _INDEXES_ENSURED
    if _INDEXES_ENSURED:
        return
    try:
        await db.suppliers.create_index(
            [("tenant_id", 1), ("slug", 1)],
            name="suppliers_tenant_slug_uniq", unique=True)
        await db.supplier_credentials.create_index(
            [("tenant_id", 1), ("supplier_id", 1)],
            name="suppcred_tenant_supplier_uniq", unique=True)
        await db.supplier_sync_jobs.create_index(
            [("tenant_id", 1), ("supplier_id", 1), ("started_at", -1)],
            name="suppsync_tenant_supplier_started_desc")
        # Phase 54a — pricebook items get two supplier-aware indexes.
        await db.items.create_index(
            [("tenant_id", 1), ("supplier_id", 1)],
            name="items_tenant_supplier")
        await db.items.create_index(
            [("tenant_id", 1), ("external_sku", 1)],
            name="items_tenant_external_sku",
            sparse=True)
    except Exception as e:  # pragma: no cover
        logger.info(f"[suppliers] index create noop: {e}")
    _INDEXES_ENSURED = True


async def _auto_seed(tenant_id: str) -> None:
    """Idempotent per-tenant seed of the 5 supplier rows. Called on
    the first ``GET /suppliers`` — no bootstrap step needed at server
    startup because a fresh tenant might not exist yet then."""
    for row in SUPPLIER_SEED:
        existing = await db.suppliers.find_one(
            {"tenant_id": tenant_id, "slug": row["slug"]},
            {"_id": 0, "id": 1},
        )
        if existing:
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "slug": row["slug"],
            "display_name": row["display_name"],
            "active": False,
            "sync_frequency": "daily",
            "last_sync_at": None,
            "last_sync_status": None,
            "last_sync_item_count": 0,
            "created_at": _now_iso(),
        }
        try:
            await db.suppliers.insert_one(doc)
        except Exception as e:  # pragma: no cover — concurrent insert race
            logger.info(f"[suppliers] auto-seed race for {row['slug']}: {e}")


# ═══════════════════════════════════════════════════════════════════
# 1. GET /suppliers — list + auto-seed
# ═══════════════════════════════════════════════════════════════════
@router.get("/suppliers")
async def list_suppliers(user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    await _ensure_indexes()
    await _auto_seed(tenant_id)
    rows = await db.suppliers.find(
        {"tenant_id": tenant_id},
        {"_id": 0},
    ).to_list(50)
    # Preserve the SUPPLIER_SEED order for stable UI sort.
    order = {s["slug"]: i for i, s in enumerate(SUPPLIER_SEED)}
    rows.sort(key=lambda r: order.get(r.get("slug"), 999))
    return rows


async def _get_supplier_or_404(tenant_id: str, slug: str) -> Dict[str, Any]:
    _require_slug(slug)
    # ensure the row exists (auto-seed catches first-touch)
    await _auto_seed(tenant_id)
    row = await db.suppliers.find_one(
        {"tenant_id": tenant_id, "slug": slug},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, {"error": "supplier_row_missing"})
    return row


# ═══════════════════════════════════════════════════════════════════
# 2. GET /suppliers/{slug}/credentials — existence check only
# ═══════════════════════════════════════════════════════════════════
@router.get("/suppliers/{slug}/credentials")
async def get_credentials(
    slug: str, user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)
    cred = await db.supplier_credentials.find_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
        {"_id": 0, "updated_at": 1, "notes": 1},
    )
    return {
        "supplier_slug": slug,
        "has_credentials": bool(cred),
        "updated_at": (cred or {}).get("updated_at"),
        "notes": (cred or {}).get("notes", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# 3. POST /suppliers/{slug}/credentials — save encrypted
# ═══════════════════════════════════════════════════════════════════
class CredentialBody(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    notes: Optional[str] = ""


@router.post("/suppliers/{slug}/credentials")
async def save_credentials(
    slug: str, body: CredentialBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "supplier_id": supplier["id"],
        "encrypted_username": encrypt(body.username),
        "encrypted_password": encrypt(body.password),
        "encrypted_api_key": encrypt(body.api_key),
        "notes": body.notes or "",
        "updated_at": _now_iso(),
    }
    await db.supplier_credentials.update_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
        {"$set": doc},
        upsert=True,
    )
    logger.info(f"[suppliers] credentials saved · tenant={tenant_id[:8]} · slug={slug}")
    return {"ok": True, "supplier_slug": slug, "updated_at": doc["updated_at"]}


# ═══════════════════════════════════════════════════════════════════
# 4. DELETE /suppliers/{slug}/credentials
# ═══════════════════════════════════════════════════════════════════
@router.delete("/suppliers/{slug}/credentials")
async def delete_credentials(
    slug: str, user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)
    res = await db.supplier_credentials.delete_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
    )
    return {"ok": True, "supplier_slug": slug, "deleted_count": res.deleted_count}


# ═══════════════════════════════════════════════════════════════════
# 5. POST /suppliers/{slug}/sync — Phase 54b: poolcorp is LIVE.
#    Phase 54c: siteone is LIVE. Ewing / Heritage / ePoolSupply
#    still return 501.
# ═══════════════════════════════════════════════════════════════════
_WIRED_SYNC_SLUGS = frozenset({"poolcorp", "siteone"})


def _wired_sync_runner(slug: str):
    """Return the ``async def run_*_sync`` callable for a wired slug,
    or ``None`` if the slug hasn't been wired yet."""
    if slug == "poolcorp":
        from services.suppliers.sync import run_poolcorp_sync
        return run_poolcorp_sync
    if slug == "siteone":
        from services.suppliers.sync import run_siteone_sync
        return run_siteone_sync
    return None


@router.post("/suppliers/{slug}/sync")
async def sync_supplier(
    slug: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)
    connector = CONNECTORS.get(slug)

    if slug not in _WIRED_SYNC_SLUGS:
        planned = connector.planned_phase if connector else "TBD"
        raise HTTPException(
            status_code=501,
            detail=f"connector not implemented yet, coming in phase {planned}",
        )

    # Phase 54b / 54c — wired sync path. Runs in a background task so
    # the HTTP call returns 202 within a few ms; operator polls
    # ``GET /suppliers/{slug}/sync-jobs`` for status.
    cred_row = await db.supplier_credentials.find_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
        {"_id": 0},
    )
    if not cred_row:
        raise HTTPException(
            status_code=400,
            detail={"error": "no_credentials",
                     "message": f"Save {supplier['display_name']} credentials "
                                 f"before running sync."},
        )
    credentials = {
        "username": decrypt(cred_row.get("encrypted_username")),
        "password": decrypt(cred_row.get("encrypted_password")),
        "api_key":  decrypt(cred_row.get("encrypted_api_key")),
    }
    runner = _wired_sync_runner(slug)
    from services.suppliers.sync import start_sync_job
    job = await start_sync_job(tenant_id, supplier)
    background_tasks.add_task(
        runner, tenant_id, supplier, credentials, job["id"],
    )
    logger.info(f"[suppliers] sync started · tenant={tenant_id[:8]} · slug={slug} · job={job['id']}")
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={"job_id": job["id"], "status": "running",
                  "supplier_slug": slug},
    )


# ═══════════════════════════════════════════════════════════════════
# 5b. POST /suppliers/{slug}/test-connection — Phase 54c.
# Runs ``authenticate()`` only (no catalog walk). Bounded to 15 s so
# a stuck login page doesn't tie up the request. Same role gate as
# sync (super_admin + admin). Same no_credentials 400 shape.
# ═══════════════════════════════════════════════════════════════════
TEST_CONNECTION_TIMEOUT_S = 15.0


@router.post("/suppliers/{slug}/test-connection")
async def test_supplier_connection(
    slug: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)

    if slug not in _WIRED_SYNC_SLUGS:
        connector = CONNECTORS.get(slug)
        planned = connector.planned_phase if connector else "TBD"
        raise HTTPException(
            status_code=501,
            detail=f"connector not implemented yet, coming in phase {planned}",
        )

    cred_row = await db.supplier_credentials.find_one(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
        {"_id": 0},
    )
    if not cred_row:
        raise HTTPException(
            status_code=400,
            detail={"error": "no_credentials",
                     "message": f"Save {supplier['display_name']} credentials "
                                 f"before testing the connection."},
        )
    credentials = {
        "username": decrypt(cred_row.get("encrypted_username")),
        "password": decrypt(cred_row.get("encrypted_password")),
        "api_key":  decrypt(cred_row.get("encrypted_api_key")),
    }

    connector = CONNECTORS[slug]  # wired instance
    import asyncio as _asyncio
    from services.suppliers.poolcorp import (
        LoginFailedError, LayoutChangedError,
    )

    async def _do_auth():
        return await connector.authenticate(credentials)

    try:
        await _asyncio.wait_for(_do_auth(), timeout=TEST_CONNECTION_TIMEOUT_S)
    except _asyncio.TimeoutError:
        return {"ok": False, "error": "timeout", "supplier_slug": slug}
    except LoginFailedError as e:
        return {"ok": False, "error": "login_failed",
                "message": str(e), "supplier_slug": slug}
    except LayoutChangedError as e:
        # ``authenticate`` doesn't normally raise this — kept for
        # completeness; a login-page redesign could surface here.
        return {"ok": False, "error": "unknown",
                "message": str(e), "supplier_slug": slug}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        # Best-effort rate-limit classification. Playwright surfaces
        # 429/503s inside its Response objects; if the connector
        # raises with the digits in the message, treat as rate limit.
        low = msg.lower()
        if "429" in low or "503" in low or "rate" in low or "throttle" in low:
            return {"ok": False, "error": "rate_limited",
                    "message": msg, "supplier_slug": slug}
        return {"ok": False, "error": "unknown",
                "message": msg, "supplier_slug": slug}

    return {"ok": True, "supplier_slug": slug}


# ═══════════════════════════════════════════════════════════════════
# 6. GET /suppliers/{slug}/sync-jobs — audit log
# ═══════════════════════════════════════════════════════════════════
@router.get("/suppliers/{slug}/sync-jobs")
async def list_sync_jobs(
    slug: str, limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)
    rows = await db.supplier_sync_jobs.find(
        {"tenant_id": tenant_id, "supplier_id": supplier["id"]},
        {"_id": 0},
    ).sort("started_at", -1).to_list(limit)
    return {"supplier_slug": slug, "jobs": rows, "count": len(rows)}
