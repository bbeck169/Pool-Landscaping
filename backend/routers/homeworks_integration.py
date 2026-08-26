"""Phase 0 POC · Feb-2026 — Homeworks BYO-creds integration router.

Mounted under ``/api/admin/integrations/homeworks``. All routes are
super_admin gated. Every route treats "no creds saved" as a first-
class case that returns a 400 with a clear ``not_connected`` /
``missing_credentials`` error — never crashes.

Endpoints
---------
    GET    /admin/integrations/homeworks
        Return redacted current config + connection status.

    PUT    /admin/integrations/homeworks
        Save/update user-supplied credentials.

    POST   /admin/integrations/homeworks/connect
        Build the OAuth authorize URL + one-shot CSRF state.

    GET    /admin/integrations/homeworks/oauth/callback?code=&state=
        Complete the handshake. Non-super_admin OK here (browser hop
        strips our own cookie); trust is bound to ``state``.

    POST   /admin/integrations/homeworks/disconnect
        Clear stored tokens (keeps client creds).

    POST   /admin/integrations/homeworks/test
        Run ``tools/list`` + ``fetch_sample_customer`` — read-only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from services import homeworks_mcp_client as hw
from homeworks_integration_models import (
    HomeworksIntegrationCredsInput,
)
from utils import get_current_user


logger = logging.getLogger("homeworks_byo_router")

router = APIRouter(
    prefix="/admin/integrations/homeworks",
    tags=["Integrations · Homeworks POC"],
)


# ─────────────────────────────────────────────────────────────────────
# Auth gate
# ─────────────────────────────────────────────────────────────────────
def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


def _tenant_of(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id")
    if not tid:
        raise HTTPException(400, "missing_tenant")
    return str(tid)


# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────
@router.get("", operation_id="admin.integrations.homeworks.get")
async def get_integration(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super_admin(user)
    tenant_id = _tenant_of(user)
    doc = await hw.get_config(tenant_id)
    return hw.redact_config(doc, tenant_id)


@router.put("", operation_id="admin.integrations.homeworks.save")
async def save_integration(
    body: HomeworksIntegrationCredsInput,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(user)
    tenant_id = _tenant_of(user)

    # Verify Fernet is configured BEFORE we accept any secret.
    try:
        hw._fernet()
    except RuntimeError as exc:
        raise HTTPException(503, f"encryption_unavailable:{exc}")

    patch: Dict[str, Any] = {}
    if body.client_id is not None:
        patch["client_id"] = body.client_id.strip()
    if body.client_secret is not None:
        # Special-case empty string → keep existing.
        if body.client_secret == "":
            pass  # no change
        else:
            patch["client_secret_encrypted"] = hw.encrypt(body.client_secret)
    if body.authorize_url is not None:
        patch["authorize_url"] = body.authorize_url.strip()
    if body.token_url is not None:
        patch["token_url"] = body.token_url.strip()
    if body.redirect_uri is not None:
        patch["redirect_uri"] = body.redirect_uri.strip()
    if body.scopes is not None:
        patch["scopes"] = [s.strip() for s in body.scopes if s and s.strip()]
    if body.mcp_server_url is not None:
        patch["mcp_server_url"] = body.mcp_server_url.strip() or None

    if not patch:
        # No-op save — just return the current view.
        doc = await hw.get_config(tenant_id)
        return hw.redact_config(doc, tenant_id)

    merged = await hw.save_creds(tenant_id, patch)
    return hw.redact_config(merged, tenant_id)


@router.post("/connect", operation_id="admin.integrations.homeworks.connect")
async def connect(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super_admin(user)
    tenant_id = _tenant_of(user)
    doc = await hw.get_config(tenant_id)
    if not doc:
        raise HTTPException(400, "missing_credentials — save Client ID + URLs first")

    missing: list = []
    for field in ("client_id", "authorize_url", "token_url", "redirect_uri"):
        if not doc.get(field):
            missing.append(field)
    if missing:
        raise HTTPException(
            400,
            f"missing_credentials — required fields: {', '.join(missing)}",
        )

    state = await hw.create_state(tenant_id, str(user.get("id") or ""))
    try:
        client = hw.HomeworksMCPClient(hw.assemble_plaintext_config(doc))
        try:
            url = client.authorize_url(state)
        finally:
            await client.aclose()
    except hw.HomeworksMCPClientError as exc:
        raise HTTPException(400, str(exc))

    return {
        "authorize_url": url,
        "state": state,
        "redirect_uri": doc.get("redirect_uri"),
    }


@router.get("/oauth/callback",
             operation_id="admin.integrations.homeworks.callback")
async def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """Complete the OAuth handshake. Public endpoint — trust is bound
    to ``state`` (one-shot, 10-min TTL, deleted on consume). Returns
    JSON so the frontend callback route can render the status page."""
    if error:
        return {
            "ok": False,
            "status": "error",
            "reason": error,
            "detail": error_description,
        }
    if not code or not state:
        return {"ok": False, "status": "error", "reason": "missing_params"}
    state_doc = await hw.consume_state(state)
    if not state_doc:
        return {"ok": False, "status": "error", "reason": "invalid_state"}
    tenant_id = state_doc["tenant_id"]

    doc = await hw.get_config(tenant_id)
    if not doc:
        return {"ok": False, "status": "error",
                "reason": "credentials_missing_after_state"}

    try:
        cfg = hw.assemble_plaintext_config(doc)
        async with hw.HomeworksMCPClient(cfg) as client:
            body = await client.exchange_code(code)
    except hw.HomeworksMCPClientError as exc:
        # Redact obvious token-y substrings before persisting. httpx
        # never puts our creds in the error body, only the AS's — so
        # this is defence in depth.
        msg = str(exc)
        await hw.mark_error(tenant_id, msg)
        return {"ok": False, "status": "error", "reason": msg}

    try:
        await hw.persist_tokens_from_response(tenant_id, body)
    except Exception as exc:  # noqa: BLE001 — persistence bug should not crash callback
        logger.warning("[homeworks_byo] persist_tokens failed: %s", exc)
        await hw.mark_error(tenant_id, "token_persist_failed")
        return {"ok": False, "status": "error",
                "reason": "token_persist_failed"}

    return {"ok": True, "status": "connected", "tenant_id": tenant_id}


@router.post("/disconnect",
              operation_id="admin.integrations.homeworks.disconnect")
async def disconnect(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super_admin(user)
    tenant_id = _tenant_of(user)
    n = await hw.clear_tokens(tenant_id)
    return {"ok": True, "cleared": n}


@router.post("/test", operation_id="admin.integrations.homeworks.test")
async def smoke_test(user: Dict[str, Any] = Depends(get_current_user)):
    _require_super_admin(user)
    tenant_id = _tenant_of(user)
    doc = await hw.get_config(tenant_id)
    if not doc:
        raise HTTPException(400, "not_connected")
    if not doc.get("access_token_encrypted"):
        raise HTTPException(400, "not_connected")

    cfg = hw.assemble_plaintext_config(doc)
    try:
        async with hw.HomeworksMCPClient(cfg) as client:
            tools = await client.list_tools()
            sample = await client.fetch_sample_customer()
            # Persist any token rotation the client picked up during
            # a mid-flight refresh.
            if client.config.get("access_token") != cfg.get("access_token"):
                await hw.persist_tokens_from_response(tenant_id, {
                    "access_token": client.config.get("access_token"),
                    "refresh_token": client.config.get("refresh_token"),
                })
    except hw.HomeworksMCPClientError as exc:
        await hw.mark_error(tenant_id, str(exc))
        raise HTTPException(502, f"smoke_test_failed:{exc}")

    return {
        "connected": True,
        "tools": tools,
        "sample_customer": sample.get("sample_customer"),
        "hint": sample.get("hint"),
        "used_tool": sample.get("tool"),
    }
