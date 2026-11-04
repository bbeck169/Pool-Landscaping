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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
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


# Phase 54h-a · Aug-2026 — Turnstile handoff session role gate is
# LOOSER than the credentials role gate: admin + super_admin +
# manager. Managers routinely trigger the daily sync and are the
# operators who'll paste cookies through the Phase 54h-b bookmarklet.
_SESSION_ROLES = frozenset({"admin", "super_admin", "manager"})


def _require_session_role(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _SESSION_ROLES:
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
# 4b. PATCH /suppliers/{slug} — update sync_frequency / active
#     Phase 54e — introduces per-tenant per-supplier scheduling.
# ═══════════════════════════════════════════════════════════════════
class SupplierPatchBody(BaseModel):
    sync_frequency: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/suppliers/{slug}")
async def patch_supplier(
    slug: str, body: SupplierPatchBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)
    supplier = await _get_supplier_or_404(tenant_id, slug)

    update: Dict[str, Any] = {}
    if body.sync_frequency is not None:
        if body.sync_frequency not in _VALID_SYNC_FREQ:
            raise HTTPException(
                400, {"error": "invalid_sync_frequency",
                       "allowed": sorted(_VALID_SYNC_FREQ)})
        update["sync_frequency"] = body.sync_frequency
    if body.active is not None:
        update["active"] = bool(body.active)
    if not update:
        raise HTTPException(400, {"error": "empty_patch"})

    await db.suppliers.update_one(
        {"tenant_id": tenant_id, "slug": slug},
        {"$set": update},
    )
    row = await db.suppliers.find_one(
        {"tenant_id": tenant_id, "slug": slug}, {"_id": 0})
    return row or {}


# ═══════════════════════════════════════════════════════════════════
# 5. POST /suppliers/{slug}/sync — Phase 54b: poolcorp is LIVE.
#    Phase 54c: siteone is LIVE. Ewing / Heritage / ePoolSupply
#    still return 501.
# ═══════════════════════════════════════════════════════════════════
_WIRED_SYNC_SLUGS = frozenset({"poolcorp", "siteone", "ewing", "heritage", "epoolsupply"})
_VALID_SYNC_FREQ = frozenset({"hourly", "daily", "weekly", "manual"})


def _wired_sync_runner(slug: str):
    """Return the ``async def run_*_sync`` callable for a wired slug,
    or ``None`` if the slug hasn't been wired yet."""
    if slug == "poolcorp":
        from services.suppliers.sync import run_poolcorp_sync
        return run_poolcorp_sync
    if slug == "siteone":
        from services.suppliers.sync import run_siteone_sync
        return run_siteone_sync
    if slug == "ewing":
        from services.suppliers.sync import run_ewing_sync
        return run_ewing_sync
    if slug == "heritage":
        from services.suppliers.sync import run_heritage_sync
        return run_heritage_sync
    if slug == "epoolsupply":
        from services.suppliers.sync import run_epoolsupply_sync
        return run_epoolsupply_sync
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
# Runs ``authenticate()`` only (no catalog walk). Bounded to 45 s so
# a stuck login page doesn't tie up the request. Same role gate as
# sync (super_admin + admin). Same no_credentials 400 shape.
#
# Aug-2026 · Fix B-1 — bumped from 15 s → 45 s. Cloudflare-fronted
# supplier logins (Pool360, Heritage) routinely take 20-35 s just to
# render past the JS challenge; 15 s was inducing spurious timeouts
# on healthy accounts. Client-side abort remains 60 s downstream so
# the browser waits slightly past the server budget.
# ═══════════════════════════════════════════════════════════════════
TEST_CONNECTION_TIMEOUT_S = 45.0


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

    # Phase 54h-a · Aug-2026 — cookie-jar rehydration. When a valid
    # (unexpired) session exists for this tenant+supplier, hand its
    # cookies to the connector so it can skip scripted login + the
    # Turnstile challenge. Falls through to scripted flow if the
    # session is stale or missing.
    from services.suppliers.sessions import get_active_session
    _session_cookies = await get_active_session(tenant_id, slug)
    if _session_cookies:
        credentials["_session_cookies"] = _session_cookies

    connector = CONNECTORS[slug]  # wired instance
    import asyncio as _asyncio
    from services.suppliers.poolcorp import (
        LoginFailedError, LayoutChangedError,
    )
    from services.suppliers.challenge import SupplierChallengeRequired

    async def _do_auth():
        return await connector.authenticate(credentials)

    try:
        await _asyncio.wait_for(_do_auth(), timeout=TEST_CONNECTION_TIMEOUT_S)
    except _asyncio.TimeoutError:
        return {"ok": False, "error": "timeout", "supplier_slug": slug}
    except SupplierChallengeRequired as e:
        # Phase 54h-a — map to the friendly shape the frontend needs
        # (Phase 54h-b modal picks this up + opens the bookmarklet UX).
        return {
            "ok": False,
            "challenge_required": True,
            "challenge_id": e.challenge_id,
            "supplier_slug": slug,
            "ttl_hint_minutes": 30,
        }
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
# 5c. Phase 54h-a · Aug-2026 — Cloudflare Turnstile session handoff.
#     POST   /suppliers/{slug}/sessions          — upload cookies
#     GET    /suppliers/{slug}/sessions/status   — banner countdown
#     DELETE /suppliers/{slug}/sessions          — force re-challenge
#
# Role gate is looser than the credentials CRUD — admin + super_admin
# + manager (managers routinely trigger daily sync). Handoff-opt-in
# is enforced per-connector via ``SUPPORTS_CHALLENGE_HANDOFF``;
# non-opt-in suppliers (Ewing, ePoolSupply) return 400 on POST with
# ``supplier_does_not_support_handoff``.
#
# Phase 54h-b · Aug-2026 — bookmarklet auth. The
# ``POST /suppliers/{slug}/sessions`` endpoint additionally accepts
# an ``?import_token=`` query param (5-min JWT with ``purpose:
# supplier_session_import`` claim) so the bookmarklet — which runs
# in the SUPPLIER'S tab, not the CRM's — can post cookies without
# needing the operator's full-strength Authorization header.
# ═══════════════════════════════════════════════════════════════════
IMPORT_TOKEN_TTL_MINUTES = 5
IMPORT_TOKEN_PURPOSE = "supplier_session_import"


def _issue_import_token(user: Dict[str, Any]) -> Dict[str, Any]:
    """Mint a 5-min JWT scoped to POST /suppliers/*/sessions only.
    Reuses the app's JWT_SECRET/JWT_ALGO — no key sprawl."""
    import jwt as _jwt
    from datetime import datetime, timedelta, timezone
    from config import JWT_SECRET, JWT_ALGO
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=IMPORT_TOKEN_TTL_MINUTES)
    payload = {
        "purpose": IMPORT_TOKEN_PURPOSE,
        "sub": user["id"],
        "tenant_id": user.get("tenant_id"),
        "role": user.get("role"),
        "email": user.get("email"),
        "exp": exp,
    }
    token = _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return {"token": token, "expires_at": exp.isoformat()}


def _decode_import_token(token: str) -> Optional[Dict[str, Any]]:
    """Return the JWT payload iff purpose claim matches. None on
    any failure so the caller can treat it uniformly as ``invalid``."""
    if not token:
        return None
    import jwt as _jwt
    from config import JWT_SECRET, JWT_ALGO
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except _jwt.PyJWTError:
        return None
    if payload.get("purpose") != IMPORT_TOKEN_PURPOSE:
        return None
    return payload


class _SessionCookieIn(BaseModel):
    name: str
    value: str
    domain: Optional[str] = None
    path: Optional[str] = None
    expires: Optional[float] = None
    secure: Optional[bool] = None
    httpOnly: Optional[bool] = None
    sameSite: Optional[str] = None


class _SessionUpsertIn(BaseModel):
    cookies: List[_SessionCookieIn]


def _assert_handoff_supported(slug: str) -> None:
    # TD-homeworks-connection-remove-audit · Feb-2026 — the Phase
    # 55-b "homeworks" whitelist branch was removed as part of the
    # K55 integration sunset follow-up.  The importer that used
    # this plumbing was removed in K55.b; the slug now falls
    # through to the standard unknown-supplier path and returns
    # 404, which is correct post-sunset behavior.
    connector = CONNECTORS.get(slug)
    if connector is None:
        raise HTTPException(404, {"error": "unknown_supplier",
                                    "supplier_slug": slug})
    if not getattr(connector, "SUPPORTS_CHALLENGE_HANDOFF", False):
        raise HTTPException(400, {
            "error": "supplier_does_not_support_handoff",
            "supplier_slug": slug,
            "message": (
                f"{getattr(connector, 'display_name', slug)} uses the "
                "scripted-login flow only — no manual cookie import."
            ),
        })


@router.post("/suppliers/{slug}/sessions")
async def upsert_supplier_session(
    slug: str,
    body: _SessionUpsertIn,
    import_token: Optional[str] = Query(None),
    request: Request = None,       # type: ignore[assignment]
) -> Dict[str, Any]:
    # Phase 54h-b · Aug-2026 — bookmarklet path.
    # Priority: Authorization header (via ``get_current_user``) first.
    # If absent OR bearer decode fails, fall back to ``?import_token=``.
    # This lets the bookmarklet — which runs in the supplier's tab
    # and can't easily forward the operator's session cookie — POST
    # cookies with a narrowly-scoped 5-min JWT instead.
    user: Optional[Dict[str, Any]] = None
    auth_hdr = ""
    if request is not None:
        auth_hdr = request.headers.get("Authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        raw = auth_hdr.split(" ", 1)[1].strip()
        import jwt as _jwt
        from config import JWT_SECRET, JWT_ALGO
        try:
            payload = _jwt.decode(raw, JWT_SECRET,
                                    algorithms=[JWT_ALGO])
            if payload.get("purpose") is None:  # standard user JWT
                user = await db.users.find_one(
                    {"id": payload.get("sub")},
                    {"_id": 0, "password_hash": 0},
                )
        except _jwt.PyJWTError:
            user = None
    if user is None and import_token:
        claims = _decode_import_token(import_token)
        if claims is None:
            raise HTTPException(403, {"error": "invalid_import_token"})
        user = {"id": claims.get("sub"),
                 "email": claims.get("email"),
                 "role": claims.get("role"),
                 "tenant_id": claims.get("tenant_id")}
    if user is None:
        raise HTTPException(401, {"error": "unauthenticated"})

    _require_session_role(user)
    tenant_id = _require_tenant(user)
    _assert_handoff_supported(slug)
    # TD-homeworks-connection-remove-audit · Feb-2026 — the Phase
    # 55-b ``slug != "homeworks"`` escape hatch was removed with the
    # K55 integration sunset follow-up.  _assert_handoff_supported()
    # now rejects "homeworks" with 404 before we reach here, so the
    # supplier lookup runs unconditionally.
    await _get_supplier_or_404(tenant_id, slug)

    normalized: List[Dict[str, Any]] = []
    for c in body.cookies:
        row = {k: v for k, v in c.model_dump().items() if v is not None}
        normalized.append(row)

    from services.suppliers.sessions import upsert_session
    result = await upsert_session(
        tenant_id=tenant_id, supplier_slug=slug,
        cookies=normalized, user_id=(user or {}).get("id"),
    )
    return {"ok": True, "supplier_slug": slug, **result}


@router.post("/suppliers/sessions/import-token")
async def issue_supplier_session_import_token(
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Phase 54h-b · Aug-2026 — Mint a 5-min JWT the bookmarklet
    embeds in its ``fetch`` URL. Role gate mirrors the session
    endpoints (admin + super_admin + manager)."""
    _require_session_role(user)
    _require_tenant(user)
    return _issue_import_token(user)


@router.get("/suppliers/{slug}/sessions/status")
async def get_supplier_session_status(
    slug: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_session_role(user)
    tenant_id = _require_tenant(user)
    await _get_supplier_or_404(tenant_id, slug)
    from services.suppliers.sessions import session_status
    status = await session_status(tenant_id, slug)
    return {"supplier_slug": slug, **status}


@router.delete("/suppliers/{slug}/sessions")
async def delete_supplier_session(
    slug: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_session_role(user)
    tenant_id = _require_tenant(user)
    await _get_supplier_or_404(tenant_id, slug)
    from services.suppliers.sessions import delete_session
    deleted = await delete_session(tenant_id, slug)
    return {"ok": True, "supplier_slug": slug, "deleted": deleted}


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


# ═══════════════════════════════════════════════════════════════════
# 7. GET /suppliers/analytics — Phase 54g.
# Aggregate view over ``supplier_sync_jobs`` with a per-supplier
# health signal + 30-day trend. Read-only.
# ═══════════════════════════════════════════════════════════════════
# ``datetime`` / ``timezone`` / ``timedelta`` already imported at
# module top for the sync-history endpoints — no re-import here.


def _health_signal(row):
    """Compute (signal, rationale) from an aggregated supplier row.
    Thresholds match the scope-locked heuristic:
      * critical — success_rate<0.6  OR  3+ consecutive errors  OR  last success >3 days ago
      * warning  — success_rate 0.6-0.9  OR  items dropped >50% vs prior week
      * healthy  — success_rate>=0.9 AND avg_items>0 in last 7 days
    """
    total = row["total_runs"]
    if total == 0:
        return "healthy", "no runs in range"
    sr = row["success_rate"]
    consec_err = row.get("consecutive_errors", 0)
    days_since_success = row.get("days_since_last_success")
    if sr < 0.6:
        return "critical", f"success rate {sr:.0%} (<60%)"
    if consec_err >= 3:
        return "critical", f"{consec_err} consecutive errors"
    if days_since_success is not None and days_since_success > 3:
        return "critical", f"no success in {days_since_success} days"
    items_recent = row.get("avg_items_recent_7d", 0)
    items_prior = row.get("avg_items_prior_7d", 0)
    if items_prior > 20 and items_recent < items_prior * 0.5:
        return "warning", f"items dropped {int((1 - items_recent/items_prior)*100)}% vs prior week"
    if sr < 0.9:
        return "warning", f"success rate {sr:.0%} (60-90%)"
    if row.get("avg_items_added", 0) + row.get("avg_items_updated", 0) == 0 and total >= 3:
        return "warning", "no items added or updated across recent runs"
    return "healthy", f"success rate {sr:.0%}"


@router.get("/suppliers/analytics")
async def supplier_analytics(
    days: int = 30, user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_admin(user)
    tenant_id = _require_tenant(user)

    # Clamp per scope: 1..90.
    days = max(1, min(days, 90))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    week_cutoff = (now - timedelta(days=7)).isoformat()
    two_week_cutoff = (now - timedelta(days=14)).isoformat()

    suppliers = await db.suppliers.find(
        {"tenant_id": tenant_id}, {"_id": 0}).to_list(50)

    out = []
    for supp in suppliers:
        jobs = await db.supplier_sync_jobs.find(
            {"tenant_id": tenant_id, "supplier_id": supp["id"],
             "started_at": {"$gte": cutoff_iso}},
            {"_id": 0},
        ).sort("started_at", 1).to_list(1000)

        total = len(jobs)
        success = [j for j in jobs if j.get("status") == "success"]
        errors = [j for j in jobs if j.get("status") == "error"]
        sr = (len(success) / total) if total else 1.0

        def _avg(field, subset=jobs):
            vals = [int(j.get(field, 0) or 0) for j in subset]
            return round(sum(vals) / len(vals), 1) if vals else 0

        # Consecutive-error tail count (from newest backwards until we
        # hit a success — order jobs desc for this).
        consec_err = 0
        for j in sorted(jobs, key=lambda x: x.get("started_at", ""), reverse=True):
            if j.get("status") == "error":
                consec_err += 1
            else:
                break

        last_success = max((j for j in success),
                           key=lambda x: x.get("finished_at") or x.get("started_at", ""),
                           default=None)
        last_err = max((j for j in errors),
                       key=lambda x: x.get("finished_at") or x.get("started_at", ""),
                       default=None)
        days_since_success = None
        if last_success:
            ls = last_success.get("finished_at") or last_success.get("started_at")
            try:
                lsdt = datetime.fromisoformat(str(ls).replace("Z", "+00:00"))
                if lsdt.tzinfo is None:
                    lsdt = lsdt.replace(tzinfo=timezone.utc)
                days_since_success = (now - lsdt).days
            except Exception:
                pass

        # Sparkline: bucket jobs by ISO date.
        buckets: Dict[str, Dict[str, int]] = {}
        for j in jobs:
            date = str(j.get("started_at", ""))[:10]
            if not date:
                continue
            b = buckets.setdefault(date, {"runs": 0, "success": 0, "error": 0,
                                          "items_added": 0, "items_updated": 0})
            b["runs"] += 1
            if j.get("status") == "success":
                b["success"] += 1
            elif j.get("status") == "error":
                b["error"] += 1
            b["items_added"] += int(j.get("items_added", 0) or 0)
            b["items_updated"] += int(j.get("items_updated", 0) or 0)
        trend_daily = [{"date": d, **b} for d, b in sorted(buckets.items())]

        recent_success = [j for j in success
                          if str(j.get("started_at", "")) >= week_cutoff]
        prior_success = [j for j in success
                         if two_week_cutoff <= str(j.get("started_at", "")) < week_cutoff]
        avg_items_recent_7d = _avg("items_added", recent_success) + _avg("items_updated", recent_success)
        avg_items_prior_7d  = _avg("items_added", prior_success)  + _avg("items_updated", prior_success)

        row = {
            "slug": supp["slug"],
            "display_name": supp["display_name"],
            "total_runs": total,
            "success_count": len(success),
            "error_count": len(errors),
            "success_rate": round(sr, 3),
            "avg_items_added": _avg("items_added"),
            "avg_items_updated": _avg("items_updated"),
            "avg_items_removed": _avg("items_removed"),
            "avg_items_recent_7d": avg_items_recent_7d,
            "avg_items_prior_7d": avg_items_prior_7d,
            "consecutive_errors": consec_err,
            "days_since_last_success": days_since_success,
            "last_success_at": (last_success or {}).get("finished_at")
                               or (last_success or {}).get("started_at"),
            "last_error_at": (last_err or {}).get("finished_at")
                             or (last_err or {}).get("started_at"),
            "last_error_message": (last_err or {}).get("error_message"),
            "trend_daily": trend_daily,
        }
        signal, rationale = _health_signal(row)
        row["health_signal"] = signal
        row["health_rationale"] = rationale
        out.append(row)

    # Sort so critical suppliers surface first.
    order = {"critical": 0, "warning": 1, "healthy": 2}
    out.sort(key=lambda r: (order.get(r["health_signal"], 3), r["slug"]))

    return {
        "range_days": days,
        "generated_at": now.isoformat(),
        "suppliers": out,
    }
