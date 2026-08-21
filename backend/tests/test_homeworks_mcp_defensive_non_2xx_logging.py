"""Feb-2026 · P7 — Defensive non-2xx logging on the Homeworks MCP adapter.

Pins the WARN emitted by ``_log_non_2xx_defensive`` when the transport
returns a non-2xx.  Ops uses this line to distinguish a truly stale
outgoing query (e.g. a re-introduced ``Customer.discount`` selection)
from a transient Homeworks-side issue.

Guards:
  1. On httpx 400 during ``tools/call``, WARN fires with:
       - status=400
       - tenant id
       - method='tools/call'
       - op name parsed from the query
       - first 500 chars of the outgoing query text
       - redacted variables
       - first 500 chars of the response body
  2. On httpx 200 (happy path), WARN does NOT fire.
  3. Redaction: ``variables.email`` becomes ``"***"`` in the log line.
     Bearer / refresh / access tokens are NEVER logged (they only ever
     live in headers, which are not part of the payload we log).
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from services.homeworks_mcp import client as _c


def _fake_response(*, status: int, text: str = "", headers=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.headers = headers or {"mcp-session-id": "sess_test_123"}
    return r


def test_defensive_log_fires_on_400_during_tools_call(caplog):
    """400 during ``tools/call`` → structured WARN with query prefix +
    redacted variables + response body prefix. Bearer never appears."""
    init_ok = _fake_response(status=200)
    call_400 = _fake_response(
        status=400,
        text=(
            '{"errors":[{"message":"Cannot query field \\"discount\\" '
            'on type \\"Customer\\"."}]}'
        ),
    )

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=[init_ok, call_400])
    fake_http.aclose = AsyncMock()

    query_str = (
        "query InactiveCustomerPage($skip: SafeInt!, $take: SafeInt!) {\n"
        "  customers(where: {status: {in: [INACTIVE]}}) { id email discount }\n"
        "}"
    )

    async def _run():
        async with _c.HomeworksMCPClient(
            tenant_id="tenant_P7_test", http_client=fake_http,
        ) as mcp:
            await mcp.call_tool("query-graphql", {
                "query": query_str,
                "variables": {
                    "skip": 0, "take": 100,
                    "email": "leaky@example.com",
                },
            })

    raised = None
    with patch.object(_c.token_refresh, "get_valid_access_token",
                        AsyncMock(return_value="TOKEN_SECRET_DO_NOT_LOG")):
        with caplog.at_level(logging.WARNING, logger="homeworks_mcp.client"):
            try:
                asyncio.get_event_loop().run_until_complete(_run())
            except _c.MCPError as exc:
                raised = exc

    # Raise chain intact so the dispatcher UI banner still fires.
    assert raised is not None, "expected MCPError to bubble on 400"
    assert str(raised).startswith("mcp_http_400:"), str(raised)

    # Locate the defensive WARN.
    warn_lines = [rec for rec in caplog.records
                   if rec.levelno == logging.WARNING
                   and "non_2xx" in rec.getMessage()]
    assert len(warn_lines) == 1, (
        f"expected exactly one non_2xx WARN, got {len(warn_lines)}: "
        f"{[r.getMessage() for r in warn_lines]}"
    )
    msg = warn_lines[0].getMessage()
    # Structured fields present.
    assert "status=400" in msg
    assert "tenant=tenant_P7_test" in msg
    assert "method=tools/call" in msg
    # Op name parsed from ``query <Name>`` in the outgoing GraphQL text.
    assert "op=InactiveCustomerPage" in msg
    # Outgoing query prefix leaked into the log so ops can eyeball drift.
    assert "InactiveCustomerPage" in msg
    assert "discount" in msg  # the smoking gun that made it out
    # Response body prefix leaked so ops see the Homeworks error text.
    assert "Cannot query field" in msg
    # PII redacted — top-level ``email`` variable never logged verbatim.
    assert "leaky@example.com" not in msg
    assert "'email': '***'" in msg
    # Bearer token NEVER appears in the log payload.
    assert "TOKEN_SECRET_DO_NOT_LOG" not in msg


def test_defensive_log_silent_on_200(caplog):
    """Happy path (200) → zero non_2xx WARNs."""
    # Clear the module-level session cache so this test's initialize
    # actually runs (otherwise a cache hit from the sibling test would
    # short-circuit and reroute our tools/call mock into the init slot).
    _c._session_cache.clear()

    init_ok = _fake_response(status=200)
    call_ok = _fake_response(
        status=200,
        text=(
            '{"jsonrpc":"2.0","id":2,"result":{"content":['
            '{"type":"text","text":"{\\"data\\":{\\"customers\\":[]}}"}],'
            '"isError":false}}'
        ),
    )

    fake_http = MagicMock()
    fake_http.post = AsyncMock(side_effect=[init_ok, call_ok])
    fake_http.aclose = AsyncMock()

    async def _run():
        async with _c.HomeworksMCPClient(
            tenant_id="tenant_P7_test", http_client=fake_http,
        ) as mcp:
            return await mcp.call_tool("query-graphql", {
                "query": "query Q { customers { id } }",
            })

    with patch.object(_c.token_refresh, "get_valid_access_token",
                        AsyncMock(return_value="TOKEN_SECRET_DO_NOT_LOG")):
        with caplog.at_level(logging.WARNING, logger="homeworks_mcp.client"):
            res = asyncio.get_event_loop().run_until_complete(_run())

    assert isinstance(res, dict)
    warn_lines = [rec for rec in caplog.records
                   if rec.levelno == logging.WARNING
                   and "non_2xx" in rec.getMessage()]
    assert warn_lines == [], (
        f"expected zero non_2xx WARNs on happy path, got "
        f"{[r.getMessage() for r in warn_lines]}"
    )
