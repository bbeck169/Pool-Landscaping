"""Phase 0 POC · Feb-2026 — Homeworks MCP BYO-creds client wrapper.

Per-tenant client speaking:
  * OAuth 2.0 (authorization_code + refresh_token) against tenant-
    supplied ``authorize_url`` + ``token_url`` — no `.well-known`
    discovery, no dynamic client registration. This is intentional
    for the POC: we don't have real docs for home.works yet, so we
    make everything user-editable.
  * MCP JSON-RPC 2.0 over HTTP (POST, ``Content-Type: application/json``,
    ``Authorization: Bearer <access_token>``). Methods used:
    ``tools/list`` and ``tools/call``.

State store
-----------
OAuth CSRF ``state`` values live in ``db.homeworks_byo_oauth_states``
with a 10-minute TTL (index created lazily on first use).

Encryption at rest
------------------
``FERNET_KEY`` env var — generated + documented in
``backend/.env`` on first boot. Rotating it invalidates every stored
refresh token; document the rollover in the runbook.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from config import db
from homeworks_integration_models import (
    CONNECTION_STATUSES,
    DEFAULT_MCP_SERVER_URL,
    HomeworksIntegrationConfig,
)


logger = logging.getLogger("homeworks_byo_mcp")

COLLECTION = "homeworks_byo_integrations"
STATE_COLLECTION = "homeworks_byo_oauth_states"
STATE_TTL_SECONDS = 600
HTTP_TIMEOUT_SECS = 30.0
REFRESH_SKEW_SECONDS = 60


# ─────────────────────────────────────────────────────────────────────
# Encryption
# ─────────────────────────────────────────────────────────────────────
_FERNET: Optional[Fernet] = None


def _fernet() -> Fernet:
    """Load Fernet from ``FERNET_KEY`` env. Fails fast if unset — the
    router refuses to save creds until an operator sets one, so this
    should never be hit in a normal flow.
    """
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    key = (os.environ.get("FERNET_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "FERNET_KEY not set — generate with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'` and add to backend/.env"
        )
    _FERNET = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    return _FERNET


def encrypt(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(cipher: Optional[str]) -> Optional[str]:
    if not cipher:
        return None
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        logger.warning("[homeworks_byo] decrypt failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────
# Redaction helpers
# ─────────────────────────────────────────────────────────────────────
def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.isoformat()
    return v if isinstance(v, str) and v else None


def redact_config(doc: Optional[Dict[str, Any]], tenant_id: str) -> Dict[str, Any]:
    """Return a JSON-safe redacted view of the persisted config.

    Never returns cipher text. Booleans replace the secret fields so
    the UI can render "Set / not set" chips.
    """
    doc = doc or {}
    return {
        "tenant_id": tenant_id,
        "client_id": doc.get("client_id") or "",
        "has_client_secret": bool(doc.get("client_secret_encrypted")),
        "authorize_url": doc.get("authorize_url") or "",
        "token_url": doc.get("token_url") or "",
        "redirect_uri": doc.get("redirect_uri") or "",
        "scopes": list(doc.get("scopes") or []),
        "mcp_server_url": doc.get("mcp_server_url") or DEFAULT_MCP_SERVER_URL,
        "connection_status": doc.get("connection_status") or "disconnected",
        "last_error": doc.get("last_error"),
        "last_connected_at": _iso(doc.get("last_connected_at")),
        "token_expires_at": _iso(doc.get("token_expires_at")),
        "has_access_token": bool(doc.get("access_token_encrypted")),
        "has_refresh_token": bool(doc.get("refresh_token_encrypted")),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }


# ─────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────
async def get_config(tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db[COLLECTION].find_one({"tenant_id": tenant_id}, {"_id": 0})


async def save_creds(tenant_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert credential fields. ``patch`` only contains fields the
    caller wants to change. Missing keys are left alone."""
    now = datetime.now(timezone.utc)
    existing = await get_config(tenant_id) or {}
    merged: Dict[str, Any] = {**existing}
    for k, v in patch.items():
        merged[k] = v
    merged["tenant_id"] = tenant_id
    merged.setdefault("connection_status", "disconnected")
    merged.setdefault("created_at", now)
    merged["updated_at"] = now
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id}, {"$set": merged}, upsert=True,
    )
    return merged


async def clear_tokens(tenant_id: str) -> int:
    now = datetime.now(timezone.utc)
    r = await db[COLLECTION].update_one(
        {"tenant_id": tenant_id},
        {"$set": {
            "access_token_encrypted": None,
            "refresh_token_encrypted": None,
            "token_expires_at": None,
            "connection_status": "disconnected",
            "last_error": None,
            "updated_at": now,
        }},
    )
    return int(getattr(r, "modified_count", 0) or 0)


async def _ensure_state_index() -> None:
    try:
        await db[STATE_COLLECTION].create_index(
            "created_at", expireAfterSeconds=STATE_TTL_SECONDS,
        )
    except Exception as exc:  # pragma: no cover — index re-creation is fine
        logger.info("[homeworks_byo] state index noop: %s", exc)


async def create_state(tenant_id: str, user_id: str) -> str:
    await _ensure_state_index()
    state = secrets.token_urlsafe(32)
    await db[STATE_COLLECTION].insert_one({
        "state": state,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc),
    })
    return state


async def consume_state(state: str) -> Optional[Dict[str, Any]]:
    doc = await db[STATE_COLLECTION].find_one_and_delete({"state": state})
    if not doc:
        return None
    created = doc.get("created_at")
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - created > timedelta(seconds=STATE_TTL_SECONDS):
            return None
    return doc


# ─────────────────────────────────────────────────────────────────────
# HomeworksMCPClient
# ─────────────────────────────────────────────────────────────────────
class HomeworksMCPClientError(RuntimeError):
    """Any transport / auth / MCP error surfaced to the router."""


class HomeworksMCPClient:
    """Thin async wrapper. One instance per operation; no session cache
    (Phase 0 POC is single-shot smoke tests). Handles 401 → refresh →
    retry once transparently.

    Config dict schema (all plaintext except tokens which come from
    ``decrypt(...)``):

        {
          "tenant_id":    str,
          "client_id":    str,
          "client_secret": Optional[str],
          "authorize_url": str,
          "token_url":     str,
          "redirect_uri":  str,
          "scopes":        list[str],
          "mcp_server_url": str,
          "access_token":  Optional[str],
          "refresh_token": Optional[str],
        }
    """

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.config = dict(config)
        self._own_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS)
        self._rpc_id = 0

    async def aclose(self) -> None:
        if self._own_client:
            await self._http.aclose()

    async def __aenter__(self) -> "HomeworksMCPClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # ── OAuth ────────────────────────────────────────────────────────
    def authorize_url(self, state: str) -> str:
        """Build the authorization URL the browser hits at ``/connect``."""
        cfg = self.config
        base = (cfg.get("authorize_url") or "").strip()
        if not base:
            raise HomeworksMCPClientError("missing_authorize_url")
        if not cfg.get("client_id"):
            raise HomeworksMCPClientError("missing_client_id")
        if not cfg.get("redirect_uri"):
            raise HomeworksMCPClientError("missing_redirect_uri")
        params = {
            "response_type": "code",
            "client_id": cfg["client_id"],
            "redirect_uri": cfg["redirect_uri"],
            "state": state,
        }
        scopes = cfg.get("scopes") or []
        if scopes:
            params["scope"] = " ".join(scopes)
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{urlencode(params)}"

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """POST to ``token_url`` with ``grant_type=authorization_code``.
        Returns the raw token response body on success. Raises
        :class:`HomeworksMCPClientError` on any HTTP / parsing failure.
        """
        cfg = self.config
        if not cfg.get("token_url"):
            raise HomeworksMCPClientError("missing_token_url")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": cfg.get("client_id") or "",
            "redirect_uri": cfg.get("redirect_uri") or "",
        }
        if cfg.get("client_secret"):
            data["client_secret"] = cfg["client_secret"]
        return await self._post_token(data)

    async def refresh_token(self) -> Dict[str, Any]:
        """POST to ``token_url`` with ``grant_type=refresh_token``.
        Requires ``refresh_token`` to be present in the config.
        """
        cfg = self.config
        if not cfg.get("token_url"):
            raise HomeworksMCPClientError("missing_token_url")
        if not cfg.get("refresh_token"):
            raise HomeworksMCPClientError("missing_refresh_token")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "client_id": cfg.get("client_id") or "",
        }
        if cfg.get("client_secret"):
            data["client_secret"] = cfg["client_secret"]
        body = await self._post_token(data)
        # Update in-memory config with the new access token so the
        # in-flight retry sees it. Callers persist to DB separately.
        if body.get("access_token"):
            self.config["access_token"] = body["access_token"]
        if body.get("refresh_token"):
            self.config["refresh_token"] = body["refresh_token"]
        return body

    async def _post_token(self, data: Dict[str, str]) -> Dict[str, Any]:
        try:
            r = await self._http.post(
                self.config["token_url"], data=data,
                headers={"Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise HomeworksMCPClientError(
                f"token_transport:{exc.__class__.__name__}",
            ) from exc
        if r.status_code >= 400:
            raise HomeworksMCPClientError(
                f"token_http_{r.status_code}:{(r.text or '')[:200]}",
            )
        try:
            body = r.json() or {}
        except (ValueError, TypeError) as exc:
            raise HomeworksMCPClientError(f"token_bad_json:{exc}") from exc
        if not body.get("access_token"):
            raise HomeworksMCPClientError("token_missing_access_token")
        return body

    # ── MCP JSON-RPC ─────────────────────────────────────────────────
    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    async def list_tools(self) -> List[Dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        return list(result.get("tools") or [])

    async def call_tool(self, name: str,
                        arguments: Optional[Dict[str, Any]] = None,
                        ) -> Dict[str, Any]:
        return await self._rpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

    async def fetch_sample_customer(self) -> Dict[str, Any]:
        """Best-effort sample-customer probe.

        Tries ``list_customers`` with ``{limit: 1}`` first (our best
        guess for the Homeworks tool name). If that raises, falls
        back to the first ``tools/list`` entry whose name matches
        ``/customer/i``. Returns
        ``{"sample_customer": {...} | None, "hint": str, "tool": str | None}``.
        """
        try:
            result = await self.call_tool("list_customers", {"limit": 1})
            return {
                "sample_customer": _first_from_tool_result(result),
                "hint": "used list_customers(limit=1)",
                "tool": "list_customers",
            }
        except HomeworksMCPClientError as exc1:
            first_error = str(exc1)
        # Fallback: discover a candidate via tools/list.
        try:
            tools = await self.list_tools()
        except HomeworksMCPClientError as exc2:
            return {
                "sample_customer": None,
                "hint": (
                    f"list_customers failed: {first_error}; "
                    f"tools/list also failed: {exc2}"
                ),
                "tool": None,
            }
        candidate: Optional[str] = None
        for t in tools:
            n = str(t.get("name") or "")
            if "customer" in n.lower():
                candidate = n
                break
        if not candidate:
            return {
                "sample_customer": None,
                "hint": (
                    f"list_customers failed: {first_error}; "
                    "no customer-like tool in catalog"
                ),
                "tool": None,
            }
        try:
            result = await self.call_tool(candidate, {"limit": 1})
        except HomeworksMCPClientError as exc3:
            return {
                "sample_customer": None,
                "hint": f"fallback tool {candidate} failed: {exc3}",
                "tool": candidate,
            }
        return {
            "sample_customer": _first_from_tool_result(result),
            "hint": f"used fallback tool {candidate}",
            "tool": candidate,
        }

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """JSON-RPC 2.0 POST. On 401 refresh once + retry."""
        cfg = self.config
        mcp_url = cfg.get("mcp_server_url") or DEFAULT_MCP_SERVER_URL
        access_token = cfg.get("access_token")
        if not access_token:
            raise HomeworksMCPClientError("not_connected")
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            r = await self._http.post(mcp_url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise HomeworksMCPClientError(
                f"mcp_transport:{exc.__class__.__name__}",
            ) from exc

        if r.status_code == 401 and cfg.get("refresh_token"):
            # Refresh once + retry.
            await self.refresh_token()
            access_token = self.config.get("access_token")
            headers["Authorization"] = f"Bearer {access_token}"
            try:
                r = await self._http.post(mcp_url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise HomeworksMCPClientError(
                    f"mcp_transport_after_refresh:{exc.__class__.__name__}",
                ) from exc

        if r.status_code >= 400:
            raise HomeworksMCPClientError(
                f"mcp_http_{r.status_code}:{(r.text or '')[:200]}",
            )
        try:
            payload = r.json() or {}
        except (ValueError, TypeError) as exc:
            raise HomeworksMCPClientError(f"mcp_bad_json:{exc}") from exc
        if payload.get("error"):
            err = payload["error"] or {}
            raise HomeworksMCPClientError(f"mcp_rpc_error:{err}")
        return payload.get("result") or {}


def _first_from_tool_result(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract the first customer-like object from an MCP tool result.
    MCP results typically come back as either ``structuredContent`` or
    ``content: [{type, text}]``. We accept both, plus the raw list.
    """
    if not isinstance(result, dict):
        return None
    # 1. structuredContent — preferred per MCP 2025-06-18 spec.
    struct = result.get("structuredContent")
    if isinstance(struct, dict):
        for k in ("customers", "items", "data", "results"):
            v = struct.get(k)
            if isinstance(v, list) and v:
                return v[0] if isinstance(v[0], dict) else {"value": v[0]}
        # Otherwise return the structuredContent verbatim.
        return struct
    if isinstance(struct, list) and struct:
        return struct[0] if isinstance(struct[0], dict) else {"value": struct[0]}
    # 2. content[0].text → JSON.
    content = result.get("content") or []
    if isinstance(content, list) and content:
        first = content[0] or {}
        text = first.get("text") if isinstance(first, dict) else None
        if isinstance(text, str) and text:
            try:
                import json as _json
                parsed = _json.loads(text)
                if isinstance(parsed, list) and parsed:
                    return parsed[0] if isinstance(parsed[0], dict) else {"value": parsed[0]}
                if isinstance(parsed, dict):
                    for k in ("customers", "items", "data", "results"):
                        v = parsed.get(k)
                        if isinstance(v, list) and v:
                            return v[0] if isinstance(v[0], dict) else {"value": v[0]}
                    return parsed
            except (ValueError, TypeError):
                return {"raw_text": text[:500]}
    # 3. Fallback — return the raw result envelope for the UI to render.
    return None


# ─────────────────────────────────────────────────────────────────────
# Convenience — plaintext config assembler
# ─────────────────────────────────────────────────────────────────────
def assemble_plaintext_config(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Build the plaintext config dict a ``HomeworksMCPClient`` expects
    from a Mongo doc. Decrypts secrets. Never logs plaintext."""
    return {
        "tenant_id": doc.get("tenant_id"),
        "client_id": doc.get("client_id") or "",
        "client_secret": decrypt(doc.get("client_secret_encrypted")),
        "authorize_url": doc.get("authorize_url") or "",
        "token_url": doc.get("token_url") or "",
        "redirect_uri": doc.get("redirect_uri") or "",
        "scopes": list(doc.get("scopes") or []),
        "mcp_server_url": doc.get("mcp_server_url") or DEFAULT_MCP_SERVER_URL,
        "access_token": decrypt(doc.get("access_token_encrypted")),
        "refresh_token": decrypt(doc.get("refresh_token_encrypted")),
    }


async def persist_tokens_from_response(tenant_id: str,
                                       body: Dict[str, Any]) -> None:
    """Persist encrypted tokens + connection_status after successful
    exchange/refresh. Called by the router right after receipt so the
    client dict passed to ``HomeworksMCPClient`` doesn't need to know
    about Mongo layout.
    """
    now = datetime.now(timezone.utc)
    updates: Dict[str, Any] = {
        "access_token_encrypted": encrypt(body.get("access_token")),
        "connection_status": "connected",
        "last_error": None,
        "last_connected_at": now,
        "updated_at": now,
    }
    if body.get("refresh_token"):
        updates["refresh_token_encrypted"] = encrypt(body["refresh_token"])
    expires_in = body.get("expires_in")
    if expires_in is not None:
        try:
            updates["token_expires_at"] = now + timedelta(
                seconds=int(expires_in),
            )
        except (TypeError, ValueError):
            pass
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id}, {"$set": updates}, upsert=True,
    )


async def mark_error(tenant_id: str, message: str) -> None:
    """Flip ``connection_status`` to ``error`` + record redacted reason.

    Message is truncated + secret-scrubbed by the caller — we trust
    the router not to pass a stack trace with tokens in it.
    """
    if message and len(message) > 400:
        message = message[:400] + "…"
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id},
        {"$set": {
            "connection_status": "error",
            "last_error": message or "unknown_error",
            "updated_at": datetime.now(timezone.utc),
        }},
    )


__all__ = [
    "CONNECTION_STATUSES",
    "COLLECTION",
    "STATE_COLLECTION",
    "HomeworksMCPClient",
    "HomeworksMCPClientError",
    "assemble_plaintext_config",
    "clear_tokens",
    "consume_state",
    "create_state",
    "decrypt",
    "encrypt",
    "get_config",
    "mark_error",
    "persist_tokens_from_response",
    "redact_config",
    "save_creds",
]
