"""Phase 26 · Feb-2026 · Generic MCP OAuth 2.1 client (PKCE + DCR).

Reusable across future MCP servers. Feature-tested against Supercool
(`https://mcp.supercool.com/mcp`). Everything here is transport-agnostic
past the JSON-RPC layer; the Supercool router just points this at a
specific ``server_url``.

Design contract
---------------
* **RFC 8414** — discovers `authorization_server` metadata at
  ``<server-origin>/.well-known/oauth-authorization-server``. If missing,
  falls back to sensible defaults so we can still attempt auth flows.
* **RFC 7591** — dynamic client registration. Stored once per tenant
  (keyed on ``tenant_id + server_url``) and reused for subsequent
  connects.
* **PKCE (S256)** — ``code_verifier`` (64 URL-safe chars) →
  ``code_challenge`` = ``BASE64URL(SHA256(code_verifier))`` (no padding).
* **CSRF** — ``state`` (32-byte URL-safe token) is stored in Mongo
  bound to ``tenant_id`` + ``user_id`` + ``code_verifier`` + ``server_url``
  with a 10-minute TTL. Callback validates + deletes on use.
* **Encryption at rest** — every token stored in Mongo is Fernet-encrypted
  with ``MCP_TOKEN_ENCRYPTION_KEY``. On first boot without the key we
  auto-generate one, log a warning and persist to
  ``memory/mcp_encryption.key`` so the same key survives restarts. Prod
  operators are expected to set the env var explicitly.
* **Refresh** — ``get_valid_access_token`` auto-refreshes when the cached
  access token is within 60s of expiry.
* **Transport** — MCP JSON-RPC 2.0 over HTTP POST with
  ``Authorization: Bearer <access_token>``. We send
  ``Accept: application/json, text/event-stream`` per MCP spec and
  handle both plain JSON and SSE responses on the read path.

Public API used by ``routers.integrations_supercool``::

    build_authorize_url(tenant_id, user_id, server_url) -> str
    exchange_code(state, code) -> dict            # returns saved connection doc
    revoke_connection(tenant_id, server_url) -> None
    get_valid_access_token(tenant_id, server_url) -> str
    list_mcp_tools(tenant_id, server_url) -> list[dict]
    call_mcp_tool(tenant_id, server_url, tool_name, arguments) -> dict
    connection_status(tenant_id, server_url) -> dict
    cached_catalog(tenant_id, server_url) -> dict | None
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

import config as _cfg
from utils import new_id, now_iso


logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────
STATE_TTL_SECONDS = 600           # 10 min per spec.
REFRESH_SKEW_SECONDS = 60         # refresh if <60s before expiry.
DEFAULT_SCOPE: Optional[str] = None  # let the AS decide when unspecified.
CLIENT_NAME = "Pool & Landscaping of Vistancia CRM"
GRANT_TYPES = ["authorization_code", "refresh_token"]
TOKEN_ENDPOINT_AUTH_METHOD = "none"   # PKCE → public client
HTTP_TIMEOUT = 30.0

_KEY_FILE = Path("/app/memory/mcp_encryption.key")


# ─────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────
def _db():
    return _cfg.db


# ─────────────────────────────────────────────────────────────────────
# Encryption
# ─────────────────────────────────────────────────────────────────────
def _load_or_create_fernet_key() -> bytes:
    """Return the Fernet key bytes. Priority:
    1. ``MCP_TOKEN_ENCRYPTION_KEY`` env var (production path).
    2. ``/app/memory/mcp_encryption.key`` file (dev/preview auto-generated).
    3. Generate a fresh key, persist to the file, warn in logs.
    """
    env_key = os.environ.get("MCP_TOKEN_ENCRYPTION_KEY", "").strip()
    if env_key:
        return env_key.encode()
    if _KEY_FILE.is_file():
        return _KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        logger.warning(
            "[mcp_oauth] MCP_TOKEN_ENCRYPTION_KEY not set — generated a new "
            "Fernet key and persisted to %s. Set the env var in production.",
            _KEY_FILE,
        )
    except Exception as e:  # pragma: no cover — filesystem edge case
        logger.error("[mcp_oauth] could not persist Fernet key: %s", e)
    return key


_FERNET: Optional[Fernet] = None


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        _FERNET = Fernet(_load_or_create_fernet_key())
    return _FERNET


def encrypt(text: Optional[str]) -> Optional[str]:
    if text is None or text == "":
        return None
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(cipher: Optional[str]) -> Optional[str]:
    if not cipher:
        return None
    try:
        return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        logger.error("[mcp_oauth] decrypt failed: %s", e)
        raise


# ─────────────────────────────────────────────────────────────────────
# PKCE + state helpers
# ─────────────────────────────────────────────────────────────────────
def generate_code_verifier(length: int = 64) -> str:
    """RFC 7636 code_verifier: URL-safe, 43..128 chars."""
    if length < 43 or length > 128:
        raise ValueError("code_verifier length must be between 43 and 128")
    return secrets.token_urlsafe(length)[:length]


def code_challenge_s256(code_verifier: str) -> str:
    """S256 challenge — BASE64URL(SHA256(verifier)) without padding."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_state() -> str:
    """32-byte URL-safe random state."""
    return secrets.token_urlsafe(32)


# ─────────────────────────────────────────────────────────────────────
# Base URL / redirect resolution
# ─────────────────────────────────────────────────────────────────────
def app_base_url() -> str:
    """Public-facing base URL used to build the OAuth redirect_uri."""
    base = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if base:
        return base
    fallback = (os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if fallback:
        return fallback
    # Last-ditch dev fallback — never used in a live browser flow.
    return "http://localhost:8001"


def redirect_uri() -> str:
    return f"{app_base_url()}/api/integrations/supercool/callback"


# ─────────────────────────────────────────────────────────────────────
# Discovery (RFC 8414) + Dynamic Client Registration (RFC 7591)
# ─────────────────────────────────────────────────────────────────────
def _authorization_server_origin(server_url: str) -> str:
    u = urlparse(server_url)
    return f"{u.scheme}://{u.netloc}"


def _default_endpoints(server_url: str) -> Dict[str, str]:
    origin = _authorization_server_origin(server_url)
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/authorize",
        "token_endpoint": f"{origin}/token",
        "registration_endpoint": f"{origin}/register",
        "revocation_endpoint": f"{origin}/revoke",
    }


async def discover_metadata(server_url: str) -> Dict[str, Any]:
    """RFC 8414 — try `<origin>/.well-known/oauth-authorization-server`
    then `<origin>/.well-known/openid-configuration`. Merges the response
    over sensible defaults so callers always get a usable metadata dict.
    """
    defaults = _default_endpoints(server_url)
    origin = _authorization_server_origin(server_url)
    urls = [
        f"{origin}/.well-known/oauth-authorization-server",
        f"{origin}/.well-known/openid-configuration",
    ]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        for url in urls:
            try:
                r = await c.get(url)
            except Exception as e:
                logger.info("[mcp_oauth] discovery %s failed: %s", url, e)
                continue
            if r.status_code == 200 and "application/json" in (
                r.headers.get("content-type") or ""
            ).lower():
                try:
                    body = r.json()
                    return {**defaults, **(body or {}),
                            "_discovery_source": url}
                except Exception:
                    continue
    return {**defaults, "_discovery_source": "defaults"}


async def register_client(server_url: str,
                            metadata: Dict[str, Any]) -> Dict[str, Any]:
    """RFC 7591 — POST to the registration_endpoint. Returns the raw
    body from the AS. When registration is not supported / returns an
    error we surface ``{"error": "..."}`` and callers fall through to
    the unregistered flow (some MCP servers accept a public client with
    a caller-chosen client_id).
    """
    reg_url = metadata.get("registration_endpoint")
    if not reg_url:
        return {"error": "no_registration_endpoint"}
    payload = {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri()],
        "grant_types": GRANT_TYPES,
        "response_types": ["code"],
        "token_endpoint_auth_method": TOKEN_ENDPOINT_AUTH_METHOD,
        "application_type": "web",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(reg_url, json=payload,
                                headers={"Accept": "application/json"})
    except Exception as e:
        logger.warning("[mcp_oauth] DCR request failed: %s", e)
        return {"error": f"dcr_request_failed: {e}"}
    if r.status_code >= 400:
        return {"error": "dcr_http_error",
                 "status": r.status_code, "body": r.text[:500]}
    try:
        return r.json()
    except Exception as e:
        return {"error": f"dcr_bad_response: {e}", "raw": r.text[:500]}


async def _ensure_client_registration(tenant_id: str, server_url: str
                                         ) -> Tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """Return ``(client_id, client_secret, metadata)`` — reusing an
    existing registration when present. First-time callers hit DCR;
    subsequent connects skip it. The ``metadata`` dict is always
    populated (discovery may hit cached defaults).
    """
    existing = await _db().mcp_connections.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0},
    )
    metadata = await discover_metadata(server_url)
    if existing and existing.get("client_id"):
        client_id = existing.get("client_id")
        client_secret = decrypt(existing.get("client_secret_enc"))
        return client_id, client_secret, metadata
    reg = await register_client(server_url, metadata)
    if reg.get("error"):
        logger.warning("[mcp_oauth] DCR failed for %s: %s", server_url, reg)
        return None, None, metadata
    client_id = reg.get("client_id")
    client_secret = reg.get("client_secret")  # may be absent — public client
    if not client_id:
        return None, None, metadata
    # Persist the client registration immediately so re-connects reuse it.
    doc = {
        "tenant_id": tenant_id,
        "server_url": server_url,
        "client_id": client_id,
        "client_secret_enc": encrypt(client_secret) if client_secret else None,
        "registration_metadata": {k: reg.get(k) for k in (
            "client_id_issued_at", "client_secret_expires_at",
            "registration_access_token", "registration_client_uri",
        ) if reg.get(k) is not None},
        "connected_at": None,
        "access_token_enc": None,
        "refresh_token_enc": None,
        "expires_at": None,
    }
    await _db().mcp_connections.update_one(
        {"tenant_id": tenant_id, "server_url": server_url},
        {"$setOnInsert": doc},
        upsert=True,
    )
    return client_id, client_secret, metadata


# ─────────────────────────────────────────────────────────────────────
# Authorize URL + code exchange
# ─────────────────────────────────────────────────────────────────────
async def build_authorize_url(tenant_id: str, user_id: str,
                                 server_url: str,
                                 scope: Optional[str] = None
                                 ) -> Dict[str, Any]:
    """Return ``{"authorize_url": str, "state": str, "client_id": str}``.
    Persists an ``mcp_oauth_states`` row with the ``code_verifier`` so
    the callback can complete PKCE.
    """
    client_id, _, metadata = await _ensure_client_registration(
        tenant_id, server_url)
    if not client_id:
        return {"error": "registration_failed",
                 "reason": "Dynamic client registration failed; check "
                             "server metadata + logs."}
    verifier = generate_code_verifier()
    challenge = code_challenge_s256(verifier)
    state = generate_state()
    await _db().mcp_oauth_states.insert_one({
        "state": state,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "server_url": server_url,
        "code_verifier": verifier,
        "client_id": client_id,
        "created_at": datetime.now(timezone.utc),
    })
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    scope = scope or DEFAULT_SCOPE
    if scope:
        params["scope"] = scope
    authorize_url = f"{metadata['authorization_endpoint']}?{urlencode(params)}"
    return {"authorize_url": authorize_url, "state": state,
            "client_id": client_id,
            "discovery_source": metadata.get("_discovery_source")}


async def _consume_state(state: str) -> Optional[Dict[str, Any]]:
    row = await _db().mcp_oauth_states.find_one_and_delete({"state": state})
    if not row:
        return None
    created_at = row.get("created_at")
    if isinstance(created_at, datetime):
        age = datetime.now(timezone.utc) - created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else datetime.now(timezone.utc) - created_at
        if age > timedelta(seconds=STATE_TTL_SECONDS):
            return None
    return row


async def exchange_code(state: str, code: str) -> Dict[str, Any]:
    """Complete the OAuth code exchange. Returns the persisted
    connection doc (sans encrypted fields) on success or
    ``{"error": "..."}`` otherwise. Deletes the state row on both
    success and failure to prevent replays.
    """
    st = await _consume_state(state)
    if not st:
        return {"error": "invalid_or_expired_state"}
    tenant_id = st["tenant_id"]
    server_url = st["server_url"]
    verifier = st["code_verifier"]
    client_id = st["client_id"]

    metadata = await discover_metadata(server_url)
    conn = await _db().mcp_connections.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0})
    client_secret = decrypt((conn or {}).get("client_secret_enc"))

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
    }
    if client_secret:
        # Only include if the AS issued one during DCR.
        data["client_secret"] = client_secret
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(metadata["token_endpoint"], data=data,
                                headers={"Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    except Exception as e:
        return {"error": "token_request_failed", "reason": str(e)[:200]}
    if r.status_code != 200:
        return {"error": "token_http_error",
                 "status": r.status_code, "body": r.text[:500]}
    body = {}
    try:
        body = r.json()
    except Exception:
        return {"error": "token_bad_response", "body": r.text[:500]}

    access_token = body.get("access_token")
    if not access_token:
        return {"error": "no_access_token", "body": body}
    refresh_token = body.get("refresh_token")
    expires_in = int(body.get("expires_in") or 3600)
    expires_at = (datetime.now(timezone.utc)
                    + timedelta(seconds=expires_in)).isoformat()
    scope = body.get("scope")

    updates = {
        "tenant_id": tenant_id,
        "server_url": server_url,
        "client_id": client_id,
        "access_token_enc": encrypt(access_token),
        "refresh_token_enc": encrypt(refresh_token) if refresh_token else None,
        "expires_at": expires_at,
        "scope": scope,
        "token_type": body.get("token_type", "Bearer"),
        "connected_at": now_iso(),
        "connected_by_user_id": st["user_id"],
        "last_error": None,
    }
    await _db().mcp_connections.update_one(
        {"tenant_id": tenant_id, "server_url": server_url},
        {"$set": updates},
        upsert=True,
    )
    return {"ok": True, "tenant_id": tenant_id, "server_url": server_url,
            "connected_at": updates["connected_at"], "scope": scope,
            "expires_at": expires_at}


# ─────────────────────────────────────────────────────────────────────
# Refresh + status
# ─────────────────────────────────────────────────────────────────────
async def _refresh_access_token(conn: Dict[str, Any]) -> Dict[str, Any]:
    server_url = conn["server_url"]
    metadata = await discover_metadata(server_url)
    refresh = decrypt(conn.get("refresh_token_enc"))
    if not refresh:
        return {"error": "no_refresh_token"}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": conn.get("client_id") or "",
    }
    client_secret = decrypt(conn.get("client_secret_enc"))
    if client_secret:
        data["client_secret"] = client_secret
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post(metadata["token_endpoint"], data=data,
                                headers={"Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    except Exception as e:
        return {"error": "refresh_request_failed", "reason": str(e)[:200]}
    if r.status_code != 200:
        return {"error": "refresh_http_error",
                 "status": r.status_code, "body": r.text[:500]}
    body = r.json() if r.content else {}
    access_token = body.get("access_token")
    if not access_token:
        return {"error": "refresh_no_access_token", "body": body}
    new_refresh = body.get("refresh_token") or refresh
    expires_in = int(body.get("expires_in") or 3600)
    expires_at = (datetime.now(timezone.utc)
                    + timedelta(seconds=expires_in)).isoformat()
    await _db().mcp_connections.update_one(
        {"tenant_id": conn["tenant_id"], "server_url": server_url},
        {"$set": {
            "access_token_enc": encrypt(access_token),
            "refresh_token_enc": encrypt(new_refresh),
            "expires_at": expires_at,
            "last_error": None,
        }},
    )
    return {"ok": True, "access_token": access_token,
            "expires_at": expires_at}


async def get_valid_access_token(tenant_id: str, server_url: str
                                    ) -> Optional[str]:
    conn = await _db().mcp_connections.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0})
    if not conn or not conn.get("access_token_enc"):
        return None
    expires_at = conn.get("expires_at")
    needs_refresh = False
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= exp - timedelta(seconds=REFRESH_SKEW_SECONDS):
                needs_refresh = True
        except Exception:
            needs_refresh = True
    if needs_refresh:
        r = await _refresh_access_token(conn)
        if r.get("error"):
            await _db().mcp_connections.update_one(
                {"tenant_id": tenant_id, "server_url": server_url},
                {"$set": {"last_error": f"refresh_failed:{r.get('error')}"}},
            )
            return None
        return r["access_token"]
    return decrypt(conn.get("access_token_enc"))


async def revoke_connection(tenant_id: str, server_url: str) -> None:
    """Clear the tokens but keep the DCR client_id so a re-connect
    doesn't need to re-register."""
    await _db().mcp_connections.update_one(
        {"tenant_id": tenant_id, "server_url": server_url},
        {"$set": {
            "access_token_enc": None,
            "refresh_token_enc": None,
            "expires_at": None,
            "connected_at": None,
            "connected_by_user_id": None,
            "last_error": None,
        }},
    )
    await _db().mcp_tool_catalog.delete_many(
        {"tenant_id": tenant_id, "server_url": server_url})


async def connection_status(tenant_id: str, server_url: str) -> Dict[str, Any]:
    conn = await _db().mcp_connections.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0})
    catalog = await _db().mcp_tool_catalog.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0})
    connected = bool(conn and conn.get("access_token_enc"))
    return {
        "connected": connected,
        "server_url": server_url,
        "connected_at": (conn or {}).get("connected_at"),
        "expires_at": (conn or {}).get("expires_at"),
        "scope": (conn or {}).get("scope"),
        "tool_count": len((catalog or {}).get("tools") or []),
        "last_error": (conn or {}).get("last_error"),
        "catalog_fetched_at": (catalog or {}).get("fetched_at"),
    }


async def cached_catalog(tenant_id: str, server_url: str) -> Optional[Dict[str, Any]]:
    return await _db().mcp_tool_catalog.find_one(
        {"tenant_id": tenant_id, "server_url": server_url}, {"_id": 0})


# ─────────────────────────────────────────────────────────────────────
# JSON-RPC over MCP transport
# ─────────────────────────────────────────────────────────────────────
async def _post_json_rpc(server_url: str, token: str, method: str,
                            params: Dict[str, Any]) -> Dict[str, Any]:
    """POST a single JSON-RPC 2.0 request. Handles both
    ``application/json`` and ``text/event-stream`` responses.
    Returns the ``result`` object on success or raises RuntimeError."""
    body = {"jsonrpc": "2.0", "id": new_id()[:12],
            "method": method, "params": params}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(server_url, json=body, headers=headers)
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code >= 400:
        raise RuntimeError(f"mcp_http_{r.status_code}: {r.text[:400]}")
    if "text/event-stream" in ct:
        # Parse SSE frames: read ``data:`` lines and concatenate.
        payload = _parse_sse_body(r.text)
    else:
        try:
            payload = r.json()
        except Exception as e:
            raise RuntimeError(f"mcp_bad_response: {e}: {r.text[:400]}")
    if isinstance(payload, list):
        # Some servers return an array; unwrap the first response with a
        # matching id.
        for p in payload:
            if isinstance(p, dict) and p.get("id") == body["id"]:
                payload = p
                break
        else:
            payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"mcp_unexpected_payload: {payload!r}")
    if payload.get("error"):
        err = payload["error"]
        raise RuntimeError(f"mcp_rpc_error: {err}")
    return payload.get("result") or {}


def _parse_sse_body(text: str) -> Any:
    """Concatenate ``data:`` lines from an SSE frame, JSON-decode the
    result. Falls back to the raw text if no data lines are present."""
    data_lines: List[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        try:
            return json.loads(text)
        except Exception:
            return {}
    joined = "\n".join(data_lines).strip()
    try:
        return json.loads(joined)
    except Exception:
        # Try each line individually and pick the last JSON-parseable one.
        parsed = None
        for line in data_lines:
            try:
                parsed = json.loads(line)
            except Exception:
                continue
        return parsed or {}


async def list_mcp_tools(tenant_id: str, server_url: str
                            ) -> List[Dict[str, Any]]:
    """JSON-RPC ``tools/list``. Caches the result in ``mcp_tool_catalog``.
    Raises RuntimeError when not connected."""
    token = await get_valid_access_token(tenant_id, server_url)
    if not token:
        raise RuntimeError("not_connected")
    result = await _post_json_rpc(server_url, token, "tools/list", {})
    tools = result.get("tools") or []
    await _db().mcp_tool_catalog.update_one(
        {"tenant_id": tenant_id, "server_url": server_url},
        {"$set": {
            "tenant_id": tenant_id,
            "server_url": server_url,
            "tools": tools,
            "fetched_at": now_iso(),
        }},
        upsert=True,
    )
    return tools


async def call_mcp_tool(tenant_id: str, server_url: str,
                          tool_name: str,
                          arguments: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:
    """JSON-RPC ``tools/call``. Returns the raw ``result`` block."""
    token = await get_valid_access_token(tenant_id, server_url)
    if not token:
        raise RuntimeError("not_connected")
    return await _post_json_rpc(server_url, token, "tools/call", {
        "name": tool_name,
        "arguments": arguments or {},
    })


# ─────────────────────────────────────────────────────────────────────
# One-time TTL index for the state collection
# ─────────────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    try:
        await _db().mcp_oauth_states.create_index(
            "created_at", expireAfterSeconds=STATE_TTL_SECONDS)
        await _db().mcp_connections.create_index(
            [("tenant_id", 1), ("server_url", 1)], unique=True)
        await _db().mcp_tool_catalog.create_index(
            [("tenant_id", 1), ("server_url", 1)], unique=True)
    except Exception as e:  # pragma: no cover — index re-creation is fine
        logger.info("[mcp_oauth] ensure_indexes noop: %s", e)
