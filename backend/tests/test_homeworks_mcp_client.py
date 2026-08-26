"""Phase 0 POC · Feb-2026 — Homeworks MCP client unit tests.

The repo standard is ``asyncio.get_event_loop().run_until_complete``
rather than pytest-asyncio, because pytest-asyncio isn't installed in
the pinned dev image. This file mirrors that convention.

Covers:
  * Authorize URL construction (params, scopes joined, empty state guards).
  * Token exchange body shape + response parsing.
  * Refresh flow updates in-memory config.
  * 401 → refresh → retry cycle.
  * MCP JSON-RPC tools/list + tools/call payload shape.
  * ``fetch_sample_customer`` graceful fallback when list_customers is
    absent.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

os.environ.setdefault(
    "FERNET_KEY",
    "f2DlHrLPFFiF2HxLFglFEegS2pvke90APrHBSU_YGus=",
)

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.homeworks_mcp_client import (  # noqa: E402
    HomeworksMCPClient,
    HomeworksMCPClientError,
)


_BASE_CONFIG = {
    "tenant_id": "t-poc",
    "client_id": "cli-abc",
    "client_secret": "sec-xyz",
    "authorize_url": "https://home.works/oauth/authorize",
    "token_url": "https://home.works/oauth/token",
    "redirect_uri": "https://crm.example.com/admin/integrations/homeworks/oauth/callback",
    "scopes": ["read:customers", "read:jobs"],
    "mcp_server_url": "https://www.home.works/connect/mcp",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_client(handler, cfg=None):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, timeout=5.0)
    return HomeworksMCPClient(cfg or _BASE_CONFIG, http_client=http), http


# ─────────────────────────────────────────────────────────────────────
# Authorize URL
# ─────────────────────────────────────────────────────────────────────
def test_authorize_url_includes_all_params_and_scopes():
    client, http = _make_client(lambda req: httpx.Response(200))
    try:
        url = client.authorize_url("st-123")
    finally:
        _run(http.aclose())
    assert url.startswith("https://home.works/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=cli-abc" in url
    assert "state=st-123" in url
    assert "scope=read%3Acustomers+read%3Ajobs" in url
    assert (
        "redirect_uri=https%3A%2F%2Fcrm.example.com%2Fadmin%2F"
        "integrations%2Fhomeworks%2Foauth%2Fcallback"
    ) in url


def test_authorize_url_raises_when_missing_fields():
    cfg = {**_BASE_CONFIG, "client_id": ""}
    client, http = _make_client(lambda req: httpx.Response(200), cfg=cfg)
    try:
        with pytest.raises(HomeworksMCPClientError):
            client.authorize_url("st-1")
    finally:
        _run(http.aclose())


# ─────────────────────────────────────────────────────────────────────
# Token exchange
# ─────────────────────────────────────────────────────────────────────
def test_exchange_code_posts_correct_body_and_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        captured["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 3600,
            "token_type": "Bearer",
        })

    client, http = _make_client(handler)
    try:
        body = _run(client.exchange_code("code-xyz"))
    finally:
        _run(http.aclose())

    assert body["access_token"] == "at-1"
    assert body["refresh_token"] == "rt-1"
    assert captured["url"] == "https://home.works/oauth/token"
    assert "application/x-www-form-urlencoded" in captured["content_type"]
    from urllib.parse import parse_qs
    parsed = parse_qs(captured["body"])
    assert parsed["grant_type"] == ["authorization_code"]
    assert parsed["code"] == ["code-xyz"]
    assert parsed["client_id"] == ["cli-abc"]
    assert parsed["client_secret"] == ["sec-xyz"]
    assert parsed["redirect_uri"][0].endswith("/oauth/callback")


def test_exchange_code_raises_on_http_error():
    def handler(request):
        return httpx.Response(401, text="bad_client")

    client, http = _make_client(handler)
    try:
        with pytest.raises(HomeworksMCPClientError) as exc:
            _run(client.exchange_code("code-xyz"))
    finally:
        _run(http.aclose())
    assert "token_http_401" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# Refresh
# ─────────────────────────────────────────────────────────────────────
def test_refresh_token_updates_in_memory_config():
    def handler(request):
        return httpx.Response(200, json={
            "access_token": "at-2",
            "refresh_token": "rt-2",
            "expires_in": 3600,
        })

    cfg = {**_BASE_CONFIG, "refresh_token": "rt-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        body = _run(client.refresh_token())
    finally:
        _run(http.aclose())

    assert body["access_token"] == "at-2"
    assert client.config["access_token"] == "at-2"
    assert client.config["refresh_token"] == "rt-2"


def test_refresh_requires_refresh_token_in_config():
    client, http = _make_client(lambda req: httpx.Response(200))
    try:
        with pytest.raises(HomeworksMCPClientError) as exc:
            _run(client.refresh_token())
    finally:
        _run(http.aclose())
    assert "missing_refresh_token" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# MCP tools/list + tools/call
# ─────────────────────────────────────────────────────────────────────
def test_list_tools_posts_json_rpc_payload():
    captured = {}

    def handler(request):
        import json
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": captured["body"]["id"],
            "result": {"tools": [{"name": "list_customers"}]},
        })

    cfg = {**_BASE_CONFIG, "access_token": "at-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        tools = _run(client.list_tools())
    finally:
        _run(http.aclose())

    assert tools == [{"name": "list_customers"}]
    assert captured["url"] == _BASE_CONFIG["mcp_server_url"]
    assert captured["auth"] == "Bearer at-1"
    assert captured["content_type"] == "application/json"
    assert captured["body"]["jsonrpc"] == "2.0"
    assert captured["body"]["method"] == "tools/list"
    assert captured["body"]["params"] == {}


def test_call_tool_sends_name_and_arguments():
    captured = {}

    def handler(request):
        import json
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": captured["body"]["id"],
            "result": {"content": [{"type": "text", "text": "{\"ok\":true}"}]},
        })

    cfg = {**_BASE_CONFIG, "access_token": "at-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        result = _run(client.call_tool("list_customers", {"limit": 1}))
    finally:
        _run(http.aclose())

    assert captured["body"]["method"] == "tools/call"
    assert captured["body"]["params"] == {
        "name": "list_customers", "arguments": {"limit": 1},
    }
    assert result["content"][0]["text"] == '{"ok":true}'


def test_rpc_401_triggers_refresh_and_retry_once():
    calls = {"tools_list": 0, "token": 0}

    def handler(request):
        if "/token" in str(request.url):
            calls["token"] += 1
            return httpx.Response(200, json={
                "access_token": "at-refreshed",
                "expires_in": 3600,
            })
        calls["tools_list"] += 1
        auth = request.headers.get("authorization") or ""
        if calls["tools_list"] == 1:
            assert auth == "Bearer at-stale"
            return httpx.Response(401, text="expired")
        assert auth == "Bearer at-refreshed"
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": 1, "result": {"tools": []},
        })

    cfg = {**_BASE_CONFIG,
           "access_token": "at-stale", "refresh_token": "rt-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        tools = _run(client.list_tools())
    finally:
        _run(http.aclose())

    assert tools == []
    assert calls["token"] == 1
    assert calls["tools_list"] == 2
    assert client.config["access_token"] == "at-refreshed"


# ─────────────────────────────────────────────────────────────────────
# fetch_sample_customer fallback
# ─────────────────────────────────────────────────────────────────────
def test_fetch_sample_customer_falls_back_when_list_customers_missing():
    def handler(request):
        import json
        body = json.loads(request.content.decode("utf-8"))
        method = body["method"]
        params = body.get("params") or {}
        if method == "tools/call" and params.get("name") == "list_customers":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32601, "message": "unknown_tool"},
            })
        if method == "tools/list":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"tools": [{"name": "customers_search"}]},
            })
        if method == "tools/call" and params.get("name") == "customers_search":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "result": {
                    "structuredContent": {
                        "customers": [{"id": "c-1", "name": "Jane Doe"}],
                    },
                },
            })
        return httpx.Response(500, text="unexpected")

    cfg = {**_BASE_CONFIG, "access_token": "at-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        result = _run(client.fetch_sample_customer())
    finally:
        _run(http.aclose())

    assert result["tool"] == "customers_search"
    assert result["sample_customer"] == {"id": "c-1", "name": "Jane Doe"}
    assert "fallback" in result["hint"]


def test_fetch_sample_customer_returns_none_when_no_candidate_found():
    def handler(request):
        import json
        body = json.loads(request.content.decode("utf-8"))
        method = body["method"]
        if method == "tools/call":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32601, "message": "unknown_tool"},
            })
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"tools": [{"name": "list_invoices"}]},
        })

    cfg = {**_BASE_CONFIG, "access_token": "at-1"}
    client, http = _make_client(handler, cfg=cfg)
    try:
        result = _run(client.fetch_sample_customer())
    finally:
        _run(http.aclose())

    assert result["sample_customer"] is None
    assert result["tool"] is None
    assert "no customer-like tool" in result["hint"]
