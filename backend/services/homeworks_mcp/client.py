"""Feb-2026 · Phase 1b — Homeworks MCP client wrapper.

Async wrapper around ``https://api.home.works/mcp`` speaking the
2025-06-18 Streamable-HTTP transport. One instance per tenant per
request; session ids are cached in-process keyed on
``(tenant_id, access_token_prefix)``.

Public API::

    async with HomeworksMCPClient(tenant_id="t1") as mcp:
        tools = await mcp.list_tools()
        result = await mcp.call_tool("Execute GraphQL Query", {"query": "..."})
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from config import db
from services.homeworks_mcp import token_refresh

logger = logging.getLogger("homeworks_mcp.client")

MCP_URL = os.environ.get("HOMEWORKS_MCP_URL", "https://api.home.works/mcp")
MCP_PROTOCOL_VERSION = "2025-06-18"
_HTTP_TIMEOUT = 30.0
_MAX_5XX_RETRIES = 3
_MAX_401_RETRIES = 1  # one refresh + retry cycle per call
_SESSION_TTL_SECS = 30 * 60


# ── Feb-2026 · P7 — defensive non-2xx logging ──────────────────────
# Redact PII-ish top-level variable keys before logging outgoing
# GraphQL variables. Deeper-nested values are already bounded by the
# 500-char cap on the log line so they can't bleed a full payload.
_REDACT_VARIABLE_KEYS = frozenset({
    "email", "cc_email", "ccEmail", "phone", "cell", "fax", "password",
    "token", "access_token", "refresh_token", "authorization",
})

import re as _re  # local alias — one-line greppable dep


def _extract_op_name(query: str) -> str:
    """Parse ``query <Name>`` / ``mutation <Name>`` from a GraphQL
    string. Returns ``""`` when the query is anonymous."""
    if not query:
        return ""
    m = _re.search(r"(?:query|mutation)\s+(\w+)", query)
    return m.group(1) if m else ""


def _redact_variables(variables: Any) -> Any:
    """Return a shallow-redacted copy of ``variables`` — sensitive
    top-level values become ``"***"``. Non-dict inputs pass through so
    numeric ids / null still render usefully in the log line."""
    if not isinstance(variables, dict):
        return variables
    out: Dict[str, Any] = {}
    for k, v in variables.items():
        if k in _REDACT_VARIABLE_KEYS and v is not None:
            out[k] = "***"
        else:
            out[k] = v
    return out


def _log_non_2xx_defensive(
    *, status: int, body: str, method: str,
    params: Optional[Dict[str, Any]], tenant_id: str,
) -> None:
    """Emit a structured WARNING when Homeworks MCP returns a non-2xx.

    Captures the outgoing GraphQL query prefix + redacted variables so
    ops can distinguish a truly stale query (e.g. a re-introduced
    ``Customer.discount`` selection) from a transient Homeworks-side
    issue.  Bearer / refresh tokens are NEVER logged — headers stay
    out of the payload by construction.
    """
    query_text = ""
    op_name = method
    variables_redacted: Any = None
    if method == "tools/call":
        args = (params or {}).get("arguments") or {}
        query_text = str(args.get("query") or "")
        op_name = str(
            args.get("operationName") or _extract_op_name(query_text) or method
        )
        variables_redacted = _redact_variables(args.get("variables"))
    logger.warning(
        "[homeworks_mcp] non_2xx status=%s tenant=%s method=%s op=%s "
        "query_prefix=%r variables=%s response_body=%r",
        status, tenant_id, method, op_name,
        query_text[:500], variables_redacted, (body or "")[:500],
    )



class MCPError(RuntimeError):
    """Any structural / transport / auth error from the MCP endpoint."""


class MCPToolError(RuntimeError):
    """A tool call returned a JSON-RPC ``error`` object."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


# Session cache: (tenant_id, access_prefix) -> (session_id, cached_at_epoch)
_session_cache: Dict[Tuple[str, str], Tuple[str, float]] = {}


def _cache_key(tenant_id: str, access_token: str) -> Tuple[str, str]:
    return (tenant_id, access_token[:8])


def _cached_session_id(key: Tuple[str, str]) -> Optional[str]:
    ent = _session_cache.get(key)
    if not ent:
        return None
    session_id, cached_at = ent
    if (time.time() - cached_at) > _SESSION_TTL_SECS:
        _session_cache.pop(key, None)
        return None
    return session_id


def _cache_session(key: Tuple[str, str], session_id: str) -> None:
    _session_cache[key] = (session_id, time.time())


def _invalidate_session(key: Tuple[str, str]) -> None:
    _session_cache.pop(key, None)


def _parse_json_or_sse(body: str) -> Dict[str, Any]:
    """MCP responses are either ``application/json`` bodies or
    ``text/event-stream`` bodies. For streaming, we accumulate ``data:``
    lines and return the LAST parseable JSON-RPC response (the one
    matching our id) — intermediate ``notification`` events are
    ignored because Phase 1b doesn't need per-token streaming yet.
    """
    body = body.strip()
    if not body:
        raise MCPError("empty_response_body")
    # Fast path — plain JSON.
    if body.startswith("{") or body.startswith("["):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise MCPError(f"bad_json:{exc}") from exc
    # SSE path — take the LAST ``data:`` payload that parses as
    # ``jsonrpc`` (result or error). Ignore progress notifications.
    last_response: Optional[Dict[str, Any]] = None
    for chunk in body.split("\n\n"):
        for line in chunk.splitlines():
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            if not payload_str:
                continue
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and (
                "result" in payload or "error" in payload
            ):
                last_response = payload
    if last_response is None:
        raise MCPError("sse_no_final_response")
    return last_response


class HomeworksMCPClient:
    """Async MCP client. One instance per tenant per logical operation."""

    def __init__(
        self,
        *,
        tenant_id: str,
        user_id: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._own_client = http_client is None
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
        )
        self._access_token: Optional[str] = None
        self._session_id: Optional[str] = None
        self._id_counter = 0

    async def __aenter__(self) -> "HomeworksMCPClient":
        return self

    async def __aexit__(self, *exc) -> None:
        if self._own_client:
            await self._http.aclose()

    def _next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    async def _ensure_token(self, force_refresh: bool = False) -> str:
        """Guarantee we have a plaintext access token."""
        if force_refresh:
            self._access_token = None
            self._session_id = None
        if not self._access_token:
            tok = await token_refresh.get_valid_access_token(self.tenant_id)
            if not tok:
                raise MCPError("no_access_token_for_tenant")
            self._access_token = tok
        return self._access_token

    async def _initialize(self, access_token: str) -> str:
        """Do the JSON-RPC ``initialize`` handshake — returns session id.

        MCP servers hand the session id back via the ``Mcp-Session-Id``
        response header. We cache it per (tenant, token-prefix) so a
        page of tool calls doesn't re-handshake N times.
        """
        cache_key = _cache_key(self.tenant_id, access_token)
        cached = _cached_session_id(cache_key)
        if cached:
            self._session_id = cached
            return cached

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "aquaterra-crm",
                    "version": "1b.0",
                },
            },
        }
        r = await self._http.post(
            MCP_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            },
        )
        if r.status_code == 401:
            raise MCPError("initialize_unauthorized")
        if r.status_code >= 400:
            _log_non_2xx_defensive(
                status=r.status_code, body=r.text,
                method="initialize", params=None, tenant_id=self.tenant_id,
            )
            raise MCPError(
                f"initialize_http_{r.status_code}:{r.text[:200]}"
            )
        session_id = r.headers.get("mcp-session-id") or r.headers.get(
            "Mcp-Session-Id",
        ) or ""
        if not session_id:
            # Some servers omit the header on protocols that don't need
            # stateful sessions. Synthesise one so subsequent request
            # semantics work but don't cache — avoid poisoning others.
            session_id = f"stateless-{uuid.uuid4().hex[:12]}"
        else:
            _cache_session(cache_key, session_id)
        self._session_id = session_id
        return session_id

    async def _rpc(self, method: str,
                    params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC request, with auth-refresh + 5xx-backoff."""
        access_token = await self._ensure_token()
        session_id = self._session_id or await self._initialize(access_token)

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        started = time.monotonic()

        for attempt in range(_MAX_5XX_RETRIES):
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Mcp-Session-Id": session_id,
            }
            try:
                r = await self._http.post(
                    MCP_URL, json=payload, headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == _MAX_5XX_RETRIES - 1:
                    raise MCPError(f"transport_failed:{exc}") from exc
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue

            if r.status_code == 401:
                # Bad access token — refresh + retry ONCE.
                access_token = await self._ensure_token(force_refresh=True)
                # Session might also be tied to old token; re-init.
                _invalidate_session(_cache_key(self.tenant_id, access_token))
                session_id = await self._initialize(access_token)
                continue

            if 500 <= r.status_code < 600:
                if attempt == _MAX_5XX_RETRIES - 1:
                    raise MCPError(
                        f"mcp_5xx_after_{_MAX_5XX_RETRIES}_retries:"
                        f"{r.status_code}:{r.text[:200]}",
                    )
                retry_after = float(
                    r.headers.get("retry-after") or (0.5 * (2 ** attempt)),
                )
                await asyncio.sleep(min(retry_after, 8.0))
                continue

            if r.status_code >= 400:
                _log_non_2xx_defensive(
                    status=r.status_code, body=r.text,
                    method=method, params=payload.get("params"),
                    tenant_id=self.tenant_id,
                )
                raise MCPError(
                    f"mcp_http_{r.status_code}:{r.text[:200]}",
                )

            resp = _parse_json_or_sse(r.text)
            if "error" in resp:
                err = resp["error"] or {}
                raise MCPToolError(
                    int(err.get("code") or -1),
                    str(err.get("message") or "unknown"),
                    err.get("data"),
                )
            latency_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "[mcp] tenant=%s method=%s latency_ms=%d",
                self.tenant_id, method, latency_ms,
            )
            return resp.get("result") or {}
        # Unreachable, satisfies the type-checker.
        raise MCPError("mcp_unreachable")

    # ── Public helpers ────────────────────────────────────────────
    async def list_tools(self) -> List[Dict[str, Any]]:
        result = await self._rpc("tools/list")
        return list(result.get("tools") or [])

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        arguments = arguments or {}
        started = time.monotonic()
        status = "ok"
        try:
            return await self._rpc("tools/call", {
                "name": name, "arguments": arguments,
            })
        except MCPToolError as exc:
            status = f"tool_error_{exc.code}"
            raise
        except MCPError as exc:
            status = f"mcp_error"
            raise
        finally:
            latency_ms = int((time.monotonic() - started) * 1000)
            # Audit — arg KEYS only (privacy: no values, no plaintext).
            try:
                await db.audit_logs.insert_one({
                    "kind": "homeworks_mcp_tool_call",
                    "tenant_id": self.tenant_id,
                    "user_id": self.user_id,
                    "tool": name,
                    "arg_keys": sorted(list(arguments.keys())),
                    "status": status,
                    "latency_ms": latency_ms,
                    "at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("[mcp] audit insert failed: %s", exc)


async def gql_query(
    *,
    tenant_id: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    operation_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: fire a raw GraphQL query through the
    ``Execute GraphQL Query`` MCP tool.

    Returns the ``data`` object from the GraphQL response. Raises
    :class:`MCPError` on GraphQL ``errors`` in the response.
    """
    args: Dict[str, Any] = {"query": query}
    if variables:
        args["variables"] = variables
    if operation_name:
        args["operationName"] = operation_name
    async with HomeworksMCPClient(
        tenant_id=tenant_id, user_id=user_id,
    ) as mcp:
        # Feb-2026 · Homeworks MCP exposes ``query-graphql`` (read-only)
        # and ``mutate-graphql`` (writes). The old ``execute-graphql``
        # tool is DEPRECATED. Phase 1a/1b uses reads only, so we always
        # hit ``query-graphql``.
        raw = await mcp.call_tool("query-graphql", args)
    # MCP tool results are shaped as
    # {"content": [{"type": "text", "text": "<json>"}], "isError": bool}
    # per the 2025-06-18 spec. Some servers also return {"structuredContent": ...}.
    payload: Any = raw
    if isinstance(raw, dict):
        if raw.get("isError"):
            raise MCPError(f"tool_returned_isError:{raw}")
        struct = raw.get("structuredContent")
        if struct is not None:
            payload = struct
        else:
            content = raw.get("content") or []
            if content and isinstance(content, list):
                first = content[0] or {}
                text = first.get("text") or ""
                if text:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"raw_text": text}
    if isinstance(payload, dict) and payload.get("errors"):
        raise MCPError(f"gql_errors:{payload['errors']}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"] or {}
    return payload  # type: ignore[return-value]
