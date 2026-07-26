"""Feb-2026 · Phase B · Image generation — pytest.

Fully mocks the Supercool MCP tool call so we never spend live credits.

Covers:
* Provider selection: Supercool when tenant is connected, fallback when
  not.
* ``image_generate`` happy path — image is downloaded to disk +
  persisted in ``generated_media`` + quota incremented.
* ``image_edit`` passes ``image_url`` through as ``image_url`` to
  Supercool.
* ``image_search`` returns a non-empty result set (mocked).
* ``remove_background`` currently surfaces the file_id-only limitation
  as a clear error.
* Rate limit: (N+1)th call returns 429 with ``daily_limit_reached``.
* Unauthenticated → 401.
* Library list + soft-delete round-trip.
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

TINY_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG).decode()


def _run_async(coro, *, patch_modules=()):
    from motor.motor_asyncio import AsyncIOMotorClient
    import config
    try:
        prev = asyncio.get_event_loop()
    except RuntimeError:
        prev = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        client = AsyncIOMotorClient(_MONGO_URL, io_loop=loop)
        new_db = client[_DB_NAME]
        prev_c, prev_d = config.client, config.db
        config.client, config.db = client, new_db
        saved = [(m, getattr(m, "db", None)) for m in patch_modules]
        for m in patch_modules:
            m.db = new_db
        try:
            return loop.run_until_complete(coro)
        finally:
            for m, prev_v in saved:
                m.db = prev_v
            config.client, config.db = prev_c, prev_d
            client.close()
    finally:
        loop.close()
        try:
            asyncio.set_event_loop(prev if prev and not prev.is_closed()
                                     else asyncio.new_event_loop())
        except Exception:
            asyncio.set_event_loop(asyncio.new_event_loop())


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _admin_tenant_id() -> str:
    return _sync.users.find_one({"email": "admin@aquaterra.com"},
                                   {"_id": 0, "tenant_id": 1})["tenant_id"]


@pytest.fixture
def _clean_media():
    tid = _admin_tenant_id()
    _sync.generated_media.delete_many({"tenant_id": tid})
    _sync.media_gen_quotas.delete_many({"tenant_id": tid})
    yield
    _sync.generated_media.delete_many({"tenant_id": tid})
    _sync.media_gen_quotas.delete_many({"tenant_id": tid})


# ─────────────────────────────────────────────────────────────────────
# Provider selection
# ─────────────────────────────────────────────────────────────────────
def test_pick_provider_returns_fallback_when_not_connected():
    from services import media_provider as mp
    tid = f"pytest-not-connected-{uuid.uuid4().hex[:6]}"
    prov = _run_async(mp.pick_provider(tid))
    assert isinstance(prov, mp.EmergentFallbackProvider)


def test_pick_provider_returns_supercool_when_connected():
    from services import media_provider as mp
    tid = f"pytest-connected-{uuid.uuid4().hex[:6]}"
    _sync.mcp_connections.insert_one({
        "tenant_id": tid,
        "server_url": mp.SUPERCOOL_URL,
        "access_token_enc": "gAAAAAdummy",  # non-null triggers the check
    })
    try:
        prov = _run_async(mp.pick_provider(tid))
        assert isinstance(prov, mp.SupercoolProvider)
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


# ─────────────────────────────────────────────────────────────────────
# HTTP endpoint round-trips — mock MCP + persist_image
# ─────────────────────────────────────────────────────────────────────
def _install_supercool_mock(monkeypatch, image_response=None,
                                search_response=None,
                                remove_bg_response=None):
    """Patch ``mcp_oauth_client.call_mcp_tool`` + ``_persist_image`` +
    tenant connection so the HTTP endpoint routes through Supercool
    with deterministic responses."""
    from services import media_provider as mp
    from services import mcp_oauth_client as mcp_client

    async def _fake_call_tool(tenant_id, server_url, tool_name, arguments):
        if tool_name == "image_generate":
            return image_response or {
                "content": [
                    {"type": "resource",
                      "resource": {"uri": "https://example.com/fake.png",
                                     "mimeType": "image/png"}},
                    {"type": "text", "text": "generation ok"},
                ]
            }
        if tool_name == "image_search":
            return search_response or {
                "content": [
                    {"type": "resource",
                      "resource": {"uri": "https://images.unsplash.com/photo-1.jpg",
                                     "thumbnail_url": "https://images.unsplash.com/photo-1-thumb.jpg",
                                     "source": "unsplash",
                                     "attribution": "Jane Doe / Unsplash"}},
                    {"type": "resource",
                      "resource": {"uri": "https://images.pexels.com/photo-2.jpg",
                                     "source": "pexels"}},
                ]
            }
        return {}

    monkeypatch.setattr(mcp_client, "call_mcp_tool", _fake_call_tool)

    async def _fake_persist(url_or_datauri):
        image_id = uuid.uuid4().hex
        # Write a token file so downstream code can see it if it looks.
        path = mp.UPLOAD_ROOT / f"{image_id}.png"
        path.write_bytes(TINY_PNG)
        return image_id, f"/uploads/generated/{image_id}.png"

    monkeypatch.setattr(mp, "_persist_image", _fake_persist)


def test_generate_endpoint_happy_path(_clean_media, monkeypatch):
    """Invoke the router handler in-process so monkeypatches on
    ``mcp_oauth_client`` + ``media_provider`` reach the code path."""
    from routers import media_gen as media_router
    from services import media_provider as mp
    from services import mcp_oauth_client as mcp_client

    async def _fake_call_tool(tenant_id, server_url, tool_name, arguments):
        return {"content": [
            {"type": "resource",
              "resource": {"uri": "https://example.com/fake.png",
                             "mimeType": "image/png"}},
            {"type": "text", "text": "generation ok"},
        ]}
    monkeypatch.setattr(mcp_client, "call_mcp_tool", _fake_call_tool)

    async def _fake_persist(url_or_datauri):
        image_id = uuid.uuid4().hex
        (mp.UPLOAD_ROOT / f"{image_id}.png").write_bytes(TINY_PNG)
        return image_id, f"/uploads/generated/{image_id}.png"
    monkeypatch.setattr(mp, "_persist_image", _fake_persist)

    tid = _admin_tenant_id()
    admin = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "id": 1, "role": 1, "tenant_id": 1, "email": 1})
    admin["role"] = "admin"  # ensure gate passes
    _sync.mcp_connections.insert_one({
        "tenant_id": tid, "server_url": "https://mcp.supercool.com/mcp",
        "access_token_enc": "gAAAAAdummy"})
    try:
        body = media_router.GenerateIn(
            prompt="Aqua-blue pool at sunset with palms",
            aspect_ratio="16:9", surface="marketing")
        resp = _run_async(
            media_router.image_generate(body=body, user=admin),
            patch_modules=[media_router, mp])
        assert resp["provider"] == "supercool"
        assert resp["tool_used"] == "image_generate"
        assert resp["url"].startswith("/uploads/generated/")
        assert resp["quota"]["used"] == 1
        row = _sync.generated_media.find_one({"id": resp["image_id"]})
        assert row and row["surface"] == "marketing"
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


def test_edit_endpoint_passes_image_url_to_supercool(_clean_media, monkeypatch):
    from routers import media_gen as media_router
    from services import media_provider as mp
    from services import mcp_oauth_client as mcp_client
    captured = {}

    async def _capture(tenant_id, server_url, tool_name, arguments):
        captured.update({"tool": tool_name, "args": arguments})
        return {"content": [
            {"type": "resource",
              "resource": {"uri": "https://example.com/edited.png",
                             "mimeType": "image/png"}}]}
    monkeypatch.setattr(mcp_client, "call_mcp_tool", _capture)

    async def _fake_persist(_):
        return uuid.uuid4().hex, "/uploads/generated/x.png"
    monkeypatch.setattr(mp, "_persist_image", _fake_persist)

    tid = _admin_tenant_id()
    admin = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "id": 1, "role": 1, "tenant_id": 1})
    admin["role"] = "admin"
    _sync.mcp_connections.insert_one({
        "tenant_id": tid, "server_url": "https://mcp.supercool.com/mcp",
        "access_token_enc": "gAAAAAdummy"})
    try:
        body = media_router.EditIn(
            prompt="clean crystal-clear water",
            source_image_url="https://cust.example/pool_before.jpg")
        _run_async(media_router.image_edit(body=body, user=admin),
                     patch_modules=[media_router, mp])
        assert captured["tool"] == "image_generate"
        assert captured["args"]["image_url"] == "https://cust.example/pool_before.jpg"
        assert captured["args"]["fresh"] is False
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


def test_search_endpoint_returns_results(_clean_media, monkeypatch):
    from routers import media_gen as media_router
    from services import mcp_oauth_client as mcp_client

    async def _fake_call_tool(tenant_id, server_url, tool_name, arguments):
        return {"content": [
            {"type": "resource",
              "resource": {"uri": "https://images.unsplash.com/photo-1.jpg",
                             "thumbnail_url": "https://images.unsplash.com/photo-1-thumb.jpg",
                             "source": "unsplash",
                             "attribution": "Jane Doe / Unsplash"}},
            {"type": "resource",
              "resource": {"uri": "https://images.pexels.com/photo-2.jpg",
                             "source": "pexels"}},
        ]}
    monkeypatch.setattr(mcp_client, "call_mcp_tool", _fake_call_tool)

    tid = _admin_tenant_id()
    admin = _sync.users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "id": 1, "role": 1, "tenant_id": 1})
    admin["role"] = "admin"
    _sync.mcp_connections.insert_one({
        "tenant_id": tid, "server_url": "https://mcp.supercool.com/mcp",
        "access_token_enc": "gAAAAAdummy"})
    try:
        body = media_router.SearchIn(query="pool cleaning arizona", count=4)
        resp = _run_async(
            media_router.image_search(body=body, user=admin),
            patch_modules=[media_router])
        assert resp["provider"] == "supercool"
        assert len(resp["results"]) >= 1
        assert resp["results"][0]["url"].startswith("http")
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


def test_remove_background_surfaces_file_id_limitation(monkeypatch):
    tid = _admin_tenant_id()
    _sync.mcp_connections.insert_one({
        "tenant_id": tid, "server_url": "https://mcp.supercool.com/mcp",
        "access_token_enc": "gAAAAAdummy"})
    try:
        r = requests.post(f"{API}/media/image/remove-background",
                             headers=_admin_headers(),
                             json={"source_image_url": "https://ex/a.png"},
                             timeout=15)
        # 502 with a clear message pointing to the file_id workflow.
        assert r.status_code == 502, r.text
        assert "file_id" in r.text.lower()
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


def test_rate_limit_fires_after_daily_limit(_clean_media, monkeypatch):
    """Seed 100 quota rows for the tenant → the 101st call returns 429."""
    from datetime import datetime, timezone
    tid = _admin_tenant_id()
    ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _sync.media_gen_quotas.insert_one(
        {"tenant_id": tid, "ymd": ymd, "count": 100})
    _install_supercool_mock(monkeypatch)
    _sync.mcp_connections.insert_one({
        "tenant_id": tid, "server_url": "https://mcp.supercool.com/mcp",
        "access_token_enc": "gAAAAAdummy"})
    try:
        r = requests.post(f"{API}/media/image/generate",
                             headers=_admin_headers(),
                             json={"prompt": "test"},
                             timeout=15)
        assert r.status_code == 429, r.text
        assert "daily_limit_reached" in r.text
    finally:
        _sync.mcp_connections.delete_one({"tenant_id": tid})


def test_generate_endpoint_requires_auth():
    r = requests.post(f"{API}/media/image/generate",
                        json={"prompt": "test"}, timeout=15)
    assert r.status_code in (401, 403), r.text


def test_library_list_and_soft_delete(_clean_media):
    """Seed 3 rows, GET /library, DELETE one, verify total drops."""
    tid = _admin_tenant_id()
    now = "2026-02-01T00:00:00Z"
    seeded = []
    for i in range(3):
        iid = f"pytest-img-{i}-{uuid.uuid4().hex[:6]}"
        seeded.append(iid)
        _sync.generated_media.insert_one({
            "id": iid, "tenant_id": tid,
            "media_type": "image", "url": f"/uploads/generated/{iid}.png",
            "prompt": f"seed {i}", "provider": "supercool",
            "tool_used": "image_generate", "surface": "library",
            "created_by_user_id": "?", "created_at": now,
            "deleted_at": None,
        })
    try:
        r = requests.get(f"{API}/media/library", headers=_admin_headers(),
                            timeout=15)
        assert r.status_code == 200
        assert r.json()["total"] >= 3
        # Delete one.
        r_del = requests.delete(f"{API}/media/library/{seeded[0]}",
                                   headers=_admin_headers(), timeout=15)
        assert r_del.status_code == 200
        # Confirm soft-delete: total decreases by 1 for non-deleted.
        r2 = requests.get(f"{API}/media/library", headers=_admin_headers(),
                            timeout=15)
        assert r2.json()["total"] == r.json()["total"] - 1
        # Underlying row still present with deleted_at set.
        row = _sync.generated_media.find_one({"id": seeded[0]})
        assert row["deleted_at"] is not None
    finally:
        for iid in seeded:
            _sync.generated_media.delete_one({"id": iid})
