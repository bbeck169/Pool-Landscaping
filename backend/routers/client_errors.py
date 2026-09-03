"""Feb-2026 · Client-side error ingest + admin browser.

Two endpoints:

* ``POST /api/client-errors`` — accepts a browser-side error report from
  a mounted React Error Boundary. Auth is OPTIONAL because errors can
  occur BEFORE the auth state hydrates. When a valid bearer token is
  present, ``user_id`` and ``tenant_id`` are captured on the row.

  Body::
    {
      "message":    str,   # required (truncated to 500 chars)
      "stack":      str,   # optional (truncated to 8000 chars)
      "url":        str,   # optional (window.location.href)
      "user_agent": str,   # optional (navigator.userAgent)
      "component":  str,   # optional short tag: "DispatchBoard", "Map", ...
      "extra":      dict,  # optional JSON blob (truncated after serialize)
    }

  Response: ``{ ok: true, id: <error_id> }``.

* ``GET /api/admin/client-errors`` — admin+ / super_admin only. Returns
  the newest ``limit`` (default 100, cap 500) errors for the caller's
  tenant, most recent first. Filter with ``?component=...``.

The persisted row shape::

    {
      "id": str,
      "tenant_id": str | None,
      "user_id":   str | None,
      "user_email": str | None,
      "user_role": str | None,
      "url":       str | None,
      "user_agent": str | None,
      "message":   str,
      "stack":     str | None,
      "component": str | None,
      "extra":     dict | None,
      "ts":        ISO datetime,
      "created_at": ISO datetime,
    }

Kept intentionally small — the goal is to see WHAT is failing on the
end user's phone when we can't reproduce locally. No PII rules beyond
best-effort length caps; the caller (browser) already scrubs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter(tags=["Client Errors"])

_MSG_CAP = 500
_STACK_CAP = 8000
_URL_CAP = 500
_UA_CAP = 500
_COMPONENT_CAP = 80


def _clip(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[:n]


class ClientErrorIn(BaseModel):
    message: str = Field(..., min_length=1)
    stack: Optional[str] = None
    url: Optional[str] = None
    user_agent: Optional[str] = None
    component: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    # K37 · optional top-level fields so client-error rows can be
    # filtered by platform (web/mobile) + originating route without
    # having to hunt inside ``extra``.
    platform: Optional[str] = None
    route: Optional[str] = None


async def _optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """Return the decoded user if a bearer token is attached and valid;
    otherwise return None. Never raises 401 — client-error ingest must
    accept anonymous reports so we still capture pre-auth crashes."""
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=auth.split(" ", 1)[1].strip(),
    )
    try:
        return await get_current_user(creds)  # type: ignore[arg-type]
    except Exception:
        return None


@router.post("/client-errors", operation_id="clientErrors.ingest")
async def ingest_client_error(
    body: ClientErrorIn,
    request: Request,
):
    """Accept a single browser-side error report. Anonymous OK."""
    user = await _optional_user(request)
    row = {
        "id": new_id(),
        "tenant_id": (user or {}).get("tenant_id"),
        "user_id": (user or {}).get("id"),
        "user_email": (user or {}).get("email"),
        "user_role": (user or {}).get("role"),
        "url": _clip(body.url, _URL_CAP),
        "user_agent": _clip(body.user_agent, _UA_CAP),
        "message": _clip(body.message, _MSG_CAP) or "",
        "stack": _clip(body.stack, _STACK_CAP),
        "component": _clip(body.component, _COMPONENT_CAP),
        "extra": body.extra,
        # K37 · top-level filter keys.
        "platform": _clip(body.platform, 20),
        "route": _clip(body.route, _URL_CAP),
        "ts": now_iso(),
        "created_at": now_iso(),
    }
    try:
        await db.client_errors.insert_one(row)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning(f"client_error ingest failed: {e}")
        raise HTTPException(500, "Failed to record error")
    return {"ok": True, "id": row["id"]}


@router.get("/admin/client-errors", operation_id="clientErrors.list")
async def list_client_errors(
    limit: int = 100,
    component: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin+ browse. Scoped to the caller's tenant. super_admin sees
    everything if the tenant_id happens to be null on a row (anonymous
    ingest before login) — those rows show up in every tenant view
    tagged as ``tenant_id: null``, but only super_admin will typically
    care to inspect them."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin only")
    limit = max(1, min(500, int(limit)))
    tenant_id = user.get("tenant_id")
    q: Dict[str, Any] = {}
    if user.get("role") == "admin":
        # Regular admins scoped to their tenant only.
        q["tenant_id"] = tenant_id
    else:
        # super_admin sees their tenant PLUS anonymous (tenant_id=None)
        # so pre-login crashes aren't lost.
        q["$or"] = [{"tenant_id": tenant_id}, {"tenant_id": None}]
    if component:
        q["component"] = component
    rows = []
    async for r in db.client_errors.find(q, {"_id": 0}) \
                                   .sort("created_at", -1) \
                                   .limit(limit):
        rows.append(r)
    return {"errors": rows, "count": len(rows)}
