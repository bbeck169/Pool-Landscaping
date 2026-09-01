"""Phase 17 · Feb-2026 — QuickBooks Online read-sync router.

All endpoints under ``/api/qbo/*``. Role guards: Admin / Manager /
Super Admin only (Tech + Customer receive 403). Read-only against
Intuit — nothing writes to QBO.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from config import db
from routers.tenants import get_current_tenant
from services.qbo import match as qbo_match
from services.qbo import oauth as qbo_oauth
from services.qbo import sync as qbo_sync
from utils import get_current_user

logger = logging.getLogger("qbo.router")

router = APIRouter(prefix="/qbo", tags=["qbo"])

_ADMIN_ROLES = ("admin", "manager", "super_admin")


def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


def _require_configured() -> None:
    if not qbo_oauth.is_configured():
        raise HTTPException(400, "qbo_not_configured")


# ─── OAuth ─────────────────────────────────────────────────────────
@router.get("/oauth/connect-url")
async def get_connect_url(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    _require_configured()
    try:
        return qbo_oauth.build_auth_url(tenant["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...), realmId: str = Query(...),
    state: str = Query(...),
):
    """Intuit redirects here. Verifies state, exchanges code, persists.
    Redirects the browser back to the admin UI."""
    try:
        result = await qbo_oauth.handle_callback(
            code=code, realm_id=realmId, state=state,
            user_id="oauth_callback",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    redirect = f"/admin/integrations/qbo?connected=1&realm={result['qbo_realm_id']}"
    return RedirectResponse(redirect, status_code=302)


@router.get("/connections")
async def list_connections(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.qbo_connections.find(
        {"tenant_id": tenant["id"], "status": "active"},
        {"_id": 0, "encrypted_access_token": 0, "encrypted_refresh_token": 0},
    ).sort("connected_at", -1).to_list(50)
    return {"connections": rows, "configured": qbo_oauth.is_configured()}


@router.delete("/connections/{qbo_connection_id}")
async def revoke(
    qbo_connection_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    row = await db.qbo_connections.find_one(
        {"qbo_connection_id": qbo_connection_id, "tenant_id": tenant["id"]},
        {"_id": 0, "qbo_connection_id": 1},
    )
    if not row:
        raise HTTPException(404, "connection not found")
    ok = await qbo_oauth.revoke_connection(
        qbo_connection_id, user_id=user.get("id"),
    )
    return {"ok": ok}


# ─── Sync ───────────────────────────────────────────────────────────
class SyncNowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qbo_connection_id: str
    force_full: bool = False


@router.post("/sync/run-now")
async def sync_run_now(
    body: SyncNowBody, bg: BackgroundTasks,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    conn = await db.qbo_connections.find_one(
        {"qbo_connection_id": body.qbo_connection_id,
         "tenant_id": tenant["id"], "status": "active"},
        {"_id": 0, "qbo_connection_id": 1},
    )
    if not conn:
        raise HTTPException(404, "connection not found")

    # Concurrency guard — surface any in-flight run.
    in_flight = await db.qbo_sync_runs.find_one(
        {"tenant_id": tenant["id"],
         "qbo_connection_id": body.qbo_connection_id, "status": "running"},
        {"_id": 0, "run_id": 1, "started_at": 1},
    )
    if in_flight:
        return {"run_id": in_flight["run_id"], "status": "running",
                "already_running": True}

    # Fire-and-forget — the sync helper records to db.qbo_sync_runs.
    async def _go():
        try:
            await qbo_sync.sync_tenant(
                tenant_id=tenant["id"],
                qbo_connection_id=body.qbo_connection_id,
                force_full=body.force_full,
                triggered_by="manual",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[qbo.sync] background task crashed: %s", exc)

    bg.add_task(_go)
    # Phase H2 · Feb-2026 (F5 Wave 2) — audit every manual sync
    # kickoff, distinguishing force_full from delta. force_full is
    # catastrophic (API-budget burn + double-invoice risk); delta is
    # cheap and boring, but we log both so ops has full coverage.
    try:
        await db.audit_events.insert_one({
            "id": str(__import__("uuid").uuid4()),
            "event_type": ("qb_force_sync" if body.force_full
                            else "qb_delta_sync"),
            "tenant_id": tenant["id"],
            "qbo_connection_id": body.qbo_connection_id,
            "actor_user_id": (user or {}).get("id"),
            "actor_email": (user or {}).get("email"),
            "force_full": bool(body.force_full),
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc,
            ).isoformat(),
        })
    except Exception as _ae:
        logger.warning(f"[h2] qb_force_sync audit failed: {_ae}")
    return {"status": "started", "connection_id": body.qbo_connection_id}


@router.get("/sync/runs")
async def sync_runs(
    limit: int = Query(20, ge=1, le=200),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    rows = await db.qbo_sync_runs.find(
        {"tenant_id": tenant["id"]},
        {"_id": 0, "errors": 0},
    ).sort("started_at", -1).to_list(limit)
    return {"runs": rows}


@router.get("/sync/runs/{run_id}")
async def sync_run_detail(
    run_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    row = await db.qbo_sync_runs.find_one(
        {"run_id": run_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "run not found")
    return row


# ─── Read ───────────────────────────────────────────────────────────
_ENTITY_COLL = {
    "customers": "qbo_customers",
    "vendors": "qbo_vendors",
    "invoices": "qbo_invoices",
    "payments": "qbo_payments",
    "accounts": "qbo_accounts",
    "journal-entries": "qbo_journal_entries",
    "bills": "qbo_bills",
}


def _search_expr(search: str) -> Dict[str, Any]:
    from re import escape
    r = {"$regex": escape(search), "$options": "i"}
    return {
        "$or": [
            {"extracted.display_name": r},
            {"extracted.customer_name": r},
            {"extracted.vendor_name": r},
            {"extracted.doc_number": r},
            {"extracted.name": r},
            {"qbo_id": r},
        ]
    }


def _list_endpoint(entity: str, coll: str):
    async def handler(
        limit: int = Query(50, ge=1, le=500),
        cursor: Optional[str] = None,
        search: Optional[str] = None,
        user: dict = Depends(get_current_user),
        tenant: dict = Depends(get_current_tenant),
    ):
        _require_admin(user)
        q: Dict[str, Any] = {"tenant_id": tenant["id"]}
        if cursor:
            q["last_synced_at"] = {"$lt": cursor}
        if search:
            q.update(_search_expr(search))
        rows = await db[coll].find(q, {"_id": 0}).sort(
            "last_synced_at", -1
        ).limit(limit + 1).to_list(limit + 1)
        next_cursor = None
        if len(rows) > limit:
            next_cursor = rows[limit - 1]["last_synced_at"]
            rows = rows[:limit]
        return {"items": rows, "count": len(rows), "next_cursor": next_cursor}
    handler.__name__ = f"qbo_{entity.replace('-', '_')}_list"
    return handler


def _detail_endpoint(entity: str, coll: str):
    async def handler(
        qbo_id: str,
        user: dict = Depends(get_current_user),
        tenant: dict = Depends(get_current_tenant),
    ):
        _require_admin(user)
        row = await db[coll].find_one(
            {"tenant_id": tenant["id"], "qbo_id": qbo_id}, {"_id": 0},
        )
        if not row:
            raise HTTPException(404, "not found")
        return row
    handler.__name__ = f"qbo_{entity.replace('-', '_')}_detail"
    return handler


for _entity, _coll in _ENTITY_COLL.items():
    router.add_api_route(
        f"/{_entity}", _list_endpoint(_entity, _coll),
        methods=["GET"], name=f"qbo_{_entity}_list",
    )
    router.add_api_route(
        f"/{_entity}/{{qbo_id}}", _detail_endpoint(_entity, _coll),
        methods=["GET"], name=f"qbo_{_entity}_detail",
    )


# ─── Match links ─────────────────────────────────────────────────────
class MatchLinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qbo_entity_type: str
    qbo_id: str
    crm_entity_type: str
    crm_id: str


def _entity_coll_for_type(kind: str) -> Optional[str]:
    return {
        "customer": "qbo_customers",
        "invoice": "qbo_invoices",
        "vendor": "qbo_vendors",
        "payment": "qbo_payments",
        "account": "qbo_accounts",
        "journal_entry": "qbo_journal_entries",
        "bill": "qbo_bills",
    }.get(kind)


@router.post("/match-link")
async def match_link(
    body: MatchLinkBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    coll = _entity_coll_for_type(body.qbo_entity_type)
    if not coll:
        raise HTTPException(400, "unknown qbo_entity_type")
    row = await db[coll].find_one(
        {"tenant_id": tenant["id"], "qbo_id": body.qbo_id}, {"_id": 0, "id": 1},
    )
    if not row:
        raise HTTPException(404, "qbo entity not found")
    now = datetime.now(timezone.utc).isoformat()
    await db[coll].update_one(
        {"tenant_id": tenant["id"], "qbo_id": body.qbo_id},
        {"$set": {
            "linked_crm_id": body.crm_id,
            "linked_crm_entity_type": body.crm_entity_type,
            "linked_at": now,
            "linked_by": user.get("id"),
        }},
    )
    return {"ok": True, "linked_at": now}


@router.delete("/match-link/{qbo_entity_type}/{qbo_id}")
async def match_unlink(
    qbo_entity_type: str, qbo_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    coll = _entity_coll_for_type(qbo_entity_type)
    if not coll:
        raise HTTPException(400, "unknown qbo_entity_type")
    r = await db[coll].update_one(
        {"tenant_id": tenant["id"], "qbo_id": qbo_id},
        {"$unset": {"linked_crm_id": "", "linked_crm_entity_type": "",
                     "linked_at": "", "linked_by": ""}},
    )
    return {"ok": True, "modified": r.modified_count}


@router.get("/match-suggestions/{qbo_entity_type}/{qbo_id}")
async def match_suggestions(
    qbo_entity_type: str, qbo_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    hits = await qbo_match.suggest(
        tenant_id=tenant["id"],
        qbo_entity_type=qbo_entity_type,
        qbo_id=qbo_id,
    )
    return {"suggestions": hits, "count": len(hits)}


# ─── Boot log + index registration ───────────────────────────────────
def log_boot() -> None:
    e = qbo_oauth._env()
    logger.info(
        "[qbo] environment=%s, oauth_client=%s",
        e["environment"],
        "configured" if e["client_id"] else "missing",
    )


async def ensure_indexes(db_client=None) -> None:
    """Phase 17 · idempotent index creation for QBO mirror collections."""
    from pymongo.errors import OperationFailure
    target = db_client if db_client is not None else db
    async def _mk(coll: str, spec, name, **kw):
        try:
            await target[coll].create_index(spec, name=name, **kw)
        except OperationFailure as exc:
            if "already exists" not in str(exc).lower():
                raise
    for entity_coll in _ENTITY_COLL.values():
        await _mk(entity_coll, [("tenant_id", 1), ("qbo_realm_id", 1), ("qbo_id", 1)],
                   "tenant_realm_qbo_id_unique", unique=True)
        await _mk(entity_coll, [("tenant_id", 1), ("last_synced_at", -1)],
                   "tenant_last_synced_desc")
        await _mk(entity_coll, [("tenant_id", 1), ("linked_crm_id", 1)],
                   "tenant_linked_crm")
    await _mk("qbo_connections",
              [("tenant_id", 1), ("qbo_realm_id", 1), ("status", 1)],
              "tenant_realm_status")
    await _mk("qbo_sync_runs",
              [("tenant_id", 1), ("started_at", -1)],
              "tenant_started_desc")
