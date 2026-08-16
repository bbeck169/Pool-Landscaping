"""Feb-2026 · Homeworks (MCP) OAuth router.

Mounted under ``/api/integrations/homeworks``. Phase 1a scope — token
lifecycle only. MCP ``tools/list`` / ``tools/call`` land in Phase 1b.

Route summary:
  * ``GET  /oauth/start``      · auth · returns ``{authorize_url}``
  * ``GET  /oauth/callback``   · public · exchanges code, 302s to
    ``/settings/integrations?homeworks=…``
  * ``GET  /status``           · auth · connection view
  * ``DELETE /disconnect``     · admin · nukes the token doc
  * ``POST /oauth/debug/refresh``  · super_admin · force-refreshes the
    access token; returns the new ``expires_at`` (debug UX only)

Rate-limit: ``/oauth/start`` — 3 hits per user per 60 s (in-process,
process-local; sufficient for a single-node deploy). Callback + status
are unauthenticated / benign and left ungated.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from config import db
from services.homeworks_mcp import (
    oauth_metadata, pkce, state_store, token_store, token_refresh,
)
from utils import get_current_user

logger = logging.getLogger("homeworks_mcp.router")

router = APIRouter(
    prefix="/integrations/homeworks",
    tags=["Integrations · Homeworks"],
)

# ── Config helpers ───────────────────────────────────────────────────
_HOMEWORKS_SCOPE = "openid company"
_HTTP_TIMEOUT = 15.0


def _client_id() -> str:
    return (os.environ.get("HOMEWORKS_CLIENT_ID") or "").strip()


def _prod_host() -> str:
    return (
        os.environ.get("HOMEWORKS_PROD_HOST") or "app.plofv.com"
    ).strip()


def _preview_backend_url() -> str:
    """Read the frontend's preview URL from ``/app/frontend/.env`` so a
    fork with a different preview host picks it up without a code
    change. Falls back to an empty string when the file is absent (e.g.
    tests).
    """
    # Kept in a helper for testability. NOT cached — .env can change
    # between forks in this environment.
    try:
        with open("/app/frontend/.env", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _redirect_uri_from_request(request: Request) -> str:
    """Compute the ``redirect_uri`` for THIS running host.

    We MUST send back the same URI on both the /authorize and /token
    calls — otherwise the AS will reject the exchange. The URI is
    derived from the incoming request's forwarded-host, which matches
    what the browser will see when it lands on ``/oauth/callback``.
    """
    # `Request.url` already reflects the X-Forwarded-* headers when
    # trust_forwarded_headers is set (default in this pod's uvicorn
    # config). We drop the path + query and hard-code the callback.
    u = request.url
    scheme = request.headers.get("x-forwarded-proto") or u.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host") or u.netloc
    return f"{scheme}://{host}/api/integrations/homeworks/oauth/callback"


# ── Role gates ───────────────────────────────────────────────────────
def _require_admin(user: dict) -> None:
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "admin_only")


def _require_super_admin(user: dict) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


# ── Audit helper ─────────────────────────────────────────────────────
async def _audit(event: str, *, tenant_id: str, user_id: Optional[str],
                 state: Optional[str] = None, extra: Optional[Dict[str, Any]] = None
                 ) -> None:
    doc: Dict[str, Any] = {
        "kind": "homeworks_oauth",
        "event": event,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if state:
        # Redact everything but the last 6 chars — enough to correlate a
        # given start / callback pair in the log without leaking the nonce.
        doc["state_suffix"] = state[-6:]
    if extra:
        doc.update(extra)
    try:
        await db.audit_logs.insert_one(doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[homeworks_oauth] audit insert failed: %s", exc)


# ── Rate limiter ─────────────────────────────────────────────────────
_START_RATE_LIMIT_MAX = 3
_START_RATE_LIMIT_WINDOW = 60.0
_start_hits: Dict[str, list] = {}  # {user_id: [t1, t2, t3]}


def _rate_limit_start(user_id: str) -> None:
    now = time.time()
    hits = _start_hits.setdefault(user_id, [])
    # Drop hits outside the window.
    while hits and (now - hits[0]) > _START_RATE_LIMIT_WINDOW:
        hits.pop(0)
    if len(hits) >= _START_RATE_LIMIT_MAX:
        raise HTTPException(
            429,
            f"rate_limit_exceeded_start_max_{_START_RATE_LIMIT_MAX}_per_{int(_START_RATE_LIMIT_WINDOW)}s",
        )
    hits.append(now)


# ═══════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════

@router.get("/oauth/start", operation_id="integrations.homeworks.oauth.start")
async def oauth_start(request: Request,
                      user: Dict[str, Any] = Depends(get_current_user)):
    """Return ``{authorize_url}``. Frontend does the redirect itself."""
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    user_id = user.get("id")
    if not tenant_id or not user_id:
        raise HTTPException(400, "missing_tenant_or_user")
    _rate_limit_start(user_id)

    client_id = _client_id()
    if not client_id:
        raise HTTPException(
            503,
            "homeworks_client_id_not_configured — "
            "run backend/scripts/homeworks_register_client.py",
        )

    try:
        md = await oauth_metadata.fetch_metadata()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    verifier = pkce.generate_verifier()
    challenge = pkce.challenge_from_verifier(verifier)
    state_nonce = state_store.generate_state_nonce()
    redirect_uri = _redirect_uri_from_request(request)

    await state_store.create(
        state_nonce=state_nonce,
        code_verifier=verifier,
        tenant_id=tenant_id,
        user_id=user_id,
        redirect_uri=redirect_uri,
    )

    qs = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": _HOMEWORKS_SCOPE,
        "state": state_nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    authorize_url = f"{md['authorization_endpoint']}?{qs}"

    await _audit(
        "start", tenant_id=tenant_id, user_id=user_id, state=state_nonce,
        extra={"redirect_uri": redirect_uri},
    )
    return {
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "scope": _HOMEWORKS_SCOPE,
    }


def _frontend_landing(request: Request, status: str,
                       reason: Optional[str] = None) -> str:
    """Build the ``/settings/integrations?homeworks=<status>`` URL that
    the browser lands on after we finish (or fail) the callback."""
    # Prefer the frontend origin the request was forwarded from. We can't
    # rely on request.url because that's the backend host; instead use
    # the Referer header when present, or fall back to the same host.
    referer = request.headers.get("referer") or ""
    origin = ""
    if referer:
        # Extract scheme+host from the referer.
        from urllib.parse import urlparse as _u
        p = _u(referer)
        if p.scheme and p.netloc:
            origin = f"{p.scheme}://{p.netloc}"
    if not origin:
        scheme = request.headers.get("x-forwarded-proto") or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get(
            "host", "")
        origin = f"{scheme}://{host}"
    base = f"{origin}/settings/integrations?homeworks={status}"
    if reason:
        base += f"&reason={reason}"
    return base


@router.get("/oauth/callback",
             operation_id="integrations.homeworks.oauth.callback")
async def oauth_callback(request: Request,
                          code: Optional[str] = Query(None),
                          state: Optional[str] = Query(None),
                          error: Optional[str] = Query(None),
                          error_description: Optional[str] = Query(None)):
    """Public endpoint hit by the user's browser after authorize.

    We deliberately DO NOT require an auth cookie here — the browser
    round-trip through the AS strips our own auth. Instead we bind
    trust to the ``state`` nonce we generated at ``/start``, which is
    unique + one-shot + short-TTL.
    """
    # Surface AS-side errors first so we don't touch the state store
    # for a doomed exchange.
    if error:
        await _audit(
            "callback_as_error", tenant_id="", user_id=None, state=state,
            extra={"error": error, "error_description": error_description},
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason=error), status_code=302,
        )
    if not code or not state:
        await _audit(
            "callback_missing_params", tenant_id="", user_id=None, state=state,
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="missing_params"),
            status_code=302,
        )

    state_doc = await state_store.pop(state)
    if not state_doc:
        await _audit(
            "callback_invalid_state", tenant_id="", user_id=None, state=state,
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="invalid_state"),
            status_code=302,
        )

    client_id = _client_id()
    if not client_id:
        await _audit(
            "callback_missing_client_id",
            tenant_id=state_doc["tenant_id"],
            user_id=state_doc.get("user_id"),
            state=state,
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="client_not_registered"),
            status_code=302,
        )

    try:
        md = await oauth_metadata.fetch_metadata()
    except RuntimeError as exc:
        await _audit(
            "callback_metadata_failed",
            tenant_id=state_doc["tenant_id"],
            user_id=state_doc.get("user_id"),
            state=state, extra={"error": str(exc)},
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="as_metadata_failed"),
            status_code=302,
        )

    payload: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as http:
            r = await http.post(
                md["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": state_doc["code_verifier"],
                    "client_id": client_id,
                    "redirect_uri": state_doc["redirect_uri"],
                },
                headers={"Accept": "application/json"},
            )
        if r.status_code >= 400:
            await _audit(
                "callback_token_exchange_failed",
                tenant_id=state_doc["tenant_id"],
                user_id=state_doc.get("user_id"),
                state=state,
                extra={"status": r.status_code,
                       "body_preview": r.text[:200]},
            )
            return RedirectResponse(
                _frontend_landing(
                    request, "error",
                    reason=f"token_http_{r.status_code}",
                ),
                status_code=302,
            )
        payload = r.json()
    except httpx.HTTPError as exc:
        await _audit(
            "callback_token_transport_error",
            tenant_id=state_doc["tenant_id"],
            user_id=state_doc.get("user_id"),
            state=state, extra={"error": str(exc)},
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="token_transport_error"),
            status_code=302,
        )
    except ValueError:
        await _audit(
            "callback_token_bad_json",
            tenant_id=state_doc["tenant_id"],
            user_id=state_doc.get("user_id"),
            state=state,
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="token_bad_json"),
            status_code=302,
        )

    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = int(payload.get("expires_in") or 3600)
    scope = payload.get("scope") or _HOMEWORKS_SCOPE
    if not access or not refresh:
        await _audit(
            "callback_token_missing_fields",
            tenant_id=state_doc["tenant_id"],
            user_id=state_doc.get("user_id"),
            state=state,
        )
        return RedirectResponse(
            _frontend_landing(request, "error", reason="token_missing_fields"),
            status_code=302,
        )

    # Look up the actor's email for the status card. Best-effort.
    user_email: Optional[str] = None
    try:
        u = await db.users.find_one(
            {"id": state_doc["user_id"]},
            {"_id": 0, "email": 1},
        )
        user_email = (u or {}).get("email")
    except Exception:  # noqa: BLE001
        user_email = None

    await token_store.upsert_tokens(
        tenant_id=state_doc["tenant_id"],
        access_token=access,
        refresh_token=refresh,
        expires_in_secs=expires_in,
        scope=scope,
        user_id=state_doc["user_id"],
        user_email=user_email,
    )
    await _audit(
        "callback_success",
        tenant_id=state_doc["tenant_id"],
        user_id=state_doc.get("user_id"),
        state=state, extra={"scope": scope, "expires_in": expires_in},
    )
    return RedirectResponse(
        _frontend_landing(request, "connected"), status_code=302,
    )


@router.get("/status", operation_id="integrations.homeworks.status")
async def status_route(user: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    doc = await token_store.get_by_tenant(tenant_id)
    return token_store.status_view(doc)


@router.delete("/disconnect",
                operation_id="integrations.homeworks.disconnect")
async def disconnect(user: Dict[str, Any] = Depends(get_current_user)):
    _require_admin(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    n = await token_store.delete_by_tenant(tenant_id)
    await _audit(
        "disconnect", tenant_id=tenant_id, user_id=user.get("id"),
        extra={"deleted": n},
    )
    return {"ok": True, "deleted": n}


@router.post("/oauth/debug/refresh",
              operation_id="integrations.homeworks.debug.refresh")
async def debug_refresh(user: Dict[str, Any] = Depends(get_current_user)):
    """Super-admin debug tool — force a refresh regardless of the 60s
    skew. Returns the new ``expires_at`` for the Integrations card."""
    _require_super_admin(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "missing_tenant")
    doc = await token_store.get_by_tenant(tenant_id)
    if not doc:
        raise HTTPException(404, "not_connected")

    # Bypass the skew check by setting a moment in the past and calling
    # the same code path the automatic refresh uses.
    from services.homeworks_mcp.token_refresh import _refresh
    try:
        refresh_plain = token_store.decrypt(doc["encrypted_refresh_token"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(500, f"refresh_token_unreadable:{exc}") from exc
    new_access = await _refresh(tenant_id, refresh_plain)
    if not new_access:
        raise HTTPException(502, "refresh_failed")
    fresh_doc = await token_store.get_by_tenant(tenant_id)
    await _audit(
        "refresh_manual", tenant_id=tenant_id, user_id=user.get("id"),
    )
    return {
        "ok": True,
        "expires_at": token_store.status_view(fresh_doc).get("expires_at"),
    }
