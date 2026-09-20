"""Phase 9 · pytest — LLMs.txt Auto-Publish (Netlify / Vercel / CF Pages).

Provider HTTP is stubbed via a DB-side `_mock_publish_response` /
`_mock_test_response` shortcut inside each adapter — no real network in CI,
and no cross-process shared state required to stub.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
from services import llmstxt_publish as _svc  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_svc.db = _FRESH[_ENV["DB_NAME"]]


def _run(c):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    return _LOOP.run_until_complete(c)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": "password123"},
                      timeout=10)
    return r.json()["access_token"]


def _tid() -> str:
    return _sync.users.find_one(
        {"email": "manager@aquaterra.com"})["tenant_id"]


def _mock_factory(handler):
    def _factory():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                   timeout=5)
    return _factory


# ── 1. Adapter selection — provider slug drives the correct URL ───
def test_adapter_selection_per_provider():
    calls = {"urls": []}

    def handler(req: httpx.Request):
        calls["urls"].append(str(req.url))
        return httpx.Response(200, json={"id": "d1"})

    _svc._http_client_factory = _mock_factory(handler)
    try:
        _run(_svc._ADAPTERS["netlify"]["publish"](
            {"api_token": "n_tok", "site_id": "site1"},
            "llms.txt", b"hi"))
        _run(_svc._ADAPTERS["vercel"]["publish"](
            {"api_token": "v_tok", "project_id": "proj1"},
            "llms.txt", b"hi"))
        _run(_svc._ADAPTERS["cloudflare_pages"]["publish"](
            {"api_token": "c_tok", "account_id": "acc1",
              "project_name": "proj1"}, "llms.txt", b"hi"))
    finally:
        _svc._http_client_factory = None
    assert any("api.netlify.com/api/v1/sites/site1/files/llms.txt" in u
                 for u in calls["urls"])
    assert any("api.vercel.com/v13/deployments" in u for u in calls["urls"])
    assert any(
        "api.cloudflare.com/client/v4/accounts/acc1/pages/projects/proj1/deployments" in u
        for u in calls["urls"])


# ── 2. Not-configured → 400 ───────────────────────────────────────
def test_publish_when_not_configured_returns_400():
    tid = f"tenant_p9_{uuid.uuid4().hex[:6]}"
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid})
    r = _run(_svc.publish(tid, "netlify", filename="llms.txt",
                              content=b"hi", requested_by="u1"))
    assert r["status"] == "failed"
    assert r["error_message"] == "not_configured"
    assert r["http_status_hint"] == 400


# ── 3. Publish success → history status=success ───────────────────
def test_publish_success_writes_success_history():
    tid = f"tenant_p9s_{uuid.uuid4().hex[:6]}"
    _sync.llmstxt_publish_configs.insert_one({
        "tenant_id": tid, "provider": "netlify",
        "api_token": "nfy_abcdef123456", "site_id": "s1",
        "site_url": "https://acme.netlify.app",
        "enabled": True,
        "_mock_publish_response": {"ok": True, "deploy_id": "d123",
                                      "url": "https://acme.netlify.app/llms.txt"}})
    r = _run(_svc.publish(tid, "netlify", filename="llms.txt",
                              content=b"hi", requested_by="u1"))
    assert r["status"] == "success"
    assert r["provider_deploy_id"] == "d123"
    assert "acme.netlify.app/llms.txt" in r["provider_url"]
    row = _sync.llmstxt_publish_history.find_one(
        {"tenant_id": tid, "publish_id": r["publish_id"]})
    assert row and row["status"] == "success"
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid})
    _sync.llmstxt_publish_history.delete_many({"tenant_id": tid})


# ── 4. Publish failure → 502 + history failed ─────────────────────
def test_publish_failure_writes_failed_history():
    tid = f"tenant_p9f_{uuid.uuid4().hex[:6]}"
    _sync.llmstxt_publish_configs.insert_one({
        "tenant_id": tid, "provider": "netlify",
        "api_token": "nfy_bad", "site_id": "s1", "enabled": True,
        "_mock_publish_response": {"ok": False, "error": "http_401",
                                      "detail": "unauthorized"}})
    r = _run(_svc.publish(tid, "netlify", filename="llms.txt",
                              content=b"hi", requested_by="u1"))
    assert r["status"] == "failed"
    assert r["http_status_hint"] == 502
    assert "http_401" in (r.get("error_message") or "")
    row = _sync.llmstxt_publish_history.find_one(
        {"tenant_id": tid, "publish_id": r["publish_id"]})
    assert row and row["status"] == "failed"
    assert "http_401" in row.get("error_message", "")
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid})
    _sync.llmstxt_publish_history.delete_many({"tenant_id": tid})


# ── 5. Token masking on GET providers ─────────────────────────────
def test_get_providers_masks_token():
    tok = _login("manager@aquaterra.com")
    tid = _tid()
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid,
                                                  "provider": "netlify"})
    r = requests.post(f"{API}/aeo/llms-txt/publish/config",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"provider": "netlify",
                              "api_token": "nfy_pat_ABCDEF123456",
                              "site_id": "site_masked",
                              "enabled": True}, timeout=10)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert "api_token" not in saved
    assert saved["api_token_masked"].endswith("123456")

    r = requests.get(f"{API}/aeo/llms-txt/publish/providers",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    row = next(x for x in items if x["provider"] == "netlify")
    assert "api_token" not in row
    assert row["api_token_masked"].endswith("123456")

    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid,
                                                  "provider": "netlify"})


# ── 6. Auto-publish hook via /generate ────────────────────────────
def test_auto_publish_on_generate_triggers_history():
    tok = _login("manager@aquaterra.com")
    tid = _tid()
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid})
    _sync.llmstxt_publish_history.delete_many({"tenant_id": tid})
    _sync.llmstxt_publish_configs.insert_one({
        "tenant_id": tid, "provider": "netlify",
        "api_token": "nfy_auto", "site_id": "s_auto",
        "site_url": "https://auto.netlify.app",
        "enabled": True, "auto_publish_on_generate": True,
        "_mock_publish_response": {"ok": True, "deploy_id": "auto_dep_1",
                                      "url": "https://auto.netlify.app/llms.txt"}})
    r = requests.post(f"{API}/aeo/llms-txt/generate",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"style": "concise", "include_faqs": False},
                       timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["publish_triggered"] is True
    assert any(x["provider"] == "netlify" and x["status"] == "success"
                 for x in (data.get("publish_results") or []))
    hist = list(_sync.llmstxt_publish_history.find({"tenant_id": tid}))
    assert len(hist) >= 1
    assert hist[0]["status"] == "success"
    assert hist[0]["provider_deploy_id"] == "auto_dep_1"

    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid})
    _sync.llmstxt_publish_history.delete_many({"tenant_id": tid})


# ── 7. Role guard × 6 endpoints × 2 non-mod accounts ──────────────
def test_role_guard_all_endpoints():
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        h = {"Authorization": f"Bearer {tok}"}
        assert requests.get(f"{API}/aeo/llms-txt/publish/providers",
                             headers=h, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/llms-txt/publish/config",
                              headers=h, json={"provider": "netlify"},
                              timeout=10).status_code == 403
        assert requests.delete(f"{API}/aeo/llms-txt/publish/config/netlify",
                                headers=h, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/llms-txt/publish/test/netlify",
                              headers=h, json={}, timeout=10).status_code == 403
        assert requests.post(f"{API}/aeo/llms-txt/publish/netlify",
                              headers=h, json={"style": "concise"},
                              timeout=10).status_code == 403
        assert requests.get(f"{API}/aeo/llms-txt/publish/history",
                             headers=h, timeout=10).status_code == 403


# ── 8. Tenant isolation ───────────────────────────────────────────
def test_cross_tenant_lookup_returns_empty_not_500():
    other_tid = f"other_{uuid.uuid4().hex[:8]}"
    items = _run(_svc.get_configs_masked(other_tid))
    assert items == []
    hist = _run(_svc.history(other_tid))
    assert hist == []


# ── 9. Test-connection endpoint (Netlify 200 via mocked adapter) ──
def test_test_connection_endpoint_ok():
    tok = _login("manager@aquaterra.com")
    tid = _tid()
    _sync.llmstxt_publish_configs.update_one(
        {"tenant_id": tid, "provider": "netlify"},
        {"$set": {"tenant_id": tid, "provider": "netlify",
                    "api_token": "nfy_test_conn", "site_id": "s_test",
                    "enabled": True,
                    "_mock_test_response": {"ok": True,
                        "account_info": {"site_name": "MySite",
                                          "url": "https://mysite.netlify.app",
                                          "admin_url": "https://app.netlify.com/sites/mysite"}}}},
        upsert=True)
    r = requests.post(f"{API}/aeo/llms-txt/publish/test/netlify",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["account_info"]["site_name"] == "MySite"
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid,
                                                  "provider": "netlify"})


# ── 10. Publish endpoint via live route + mocked adapter ──────────
def test_publish_endpoint_live_route_success():
    tok = _login("manager@aquaterra.com")
    tid = _tid()
    _sync.llmstxt_publish_configs.update_one(
        {"tenant_id": tid, "provider": "cloudflare_pages"},
        {"$set": {"tenant_id": tid, "provider": "cloudflare_pages",
                    "api_token": "cf_live_pat", "account_id": "acc_live",
                    "project_name": "proj_live", "enabled": True,
                    "_mock_publish_response": {"ok": True,
                        "deploy_id": "cf_deploy_1",
                        "url": "https://proj_live.pages.dev/llms.txt"}}},
        upsert=True)
    r = requests.post(f"{API}/aeo/llms-txt/publish/cloudflare_pages",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"style": "concise"}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "success"
    assert d["provider_deploy_id"] == "cf_deploy_1"
    assert d["filename"] == "llms.txt"
    _sync.llmstxt_publish_configs.delete_many({"tenant_id": tid,
                                                  "provider": "cloudflare_pages"})
    _sync.llmstxt_publish_history.delete_many({"tenant_id": tid})
