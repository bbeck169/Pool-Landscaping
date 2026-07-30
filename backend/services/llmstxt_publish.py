"""Phase 9 · Feb-2026 — LLMs.txt Auto-Publish to static hosts.

One-click push of the tenant's generated `llms.txt` / `llms-full.txt` to
Netlify, Vercel or Cloudflare Pages using a Personal Access Token (PAT).
No OAuth. Reuses the Phase 5a generator (`services.aeo_generators`).

Token storage: raw in `llmstxt_publish_configs`, NEVER surfaced back —
`get_configs_masked()` only emits `api_token_masked` (last 6 chars). Same
pattern as Phase 7's slack webhook masking.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from config import db, logger


SUPPORTED = ("netlify", "vercel", "cloudflare_pages")


# Test override — replace with a factory that returns an httpx.AsyncClient
# with a MockTransport. When None, a fresh real client is created.
_http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None


def _client() -> httpx.AsyncClient:
    if _http_client_factory is not None:
        return _http_client_factory()
    return httpx.AsyncClient(timeout=20)


def _mask(t: str) -> str:
    if not t:
        return ""
    if len(t) <= 6:
        return "***"
    return f"…{t[-6:]}"


# ── Provider adapters ─────────────────────────────────────────────
async def _netlify_test(config: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(config.get("_mock_test_response"), dict):
        return dict(config["_mock_test_response"])
    tok = config.get("api_token") or ""
    site_id = config.get("site_id") or ""
    if not tok or not site_id:
        return {"ok": False, "error": "not_configured"}
    try:
        async with _client() as c:
            r = await c.get(f"https://api.netlify.com/api/v1/sites/{site_id}",
                            headers={"Authorization": f"Bearer {tok}"})
        if 200 <= r.status_code < 300:
            data = r.json() if r.content else {}
            return {"ok": True,
                    "account_info": {"site_name": data.get("name"),
                                     "url": data.get("url"),
                                     "admin_url": data.get("admin_url")}}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


async def _netlify_publish(config: Dict[str, Any], filename: str,
                              content: bytes) -> Dict[str, Any]:
    if isinstance(config.get("_mock_publish_response"), dict):
        return dict(config["_mock_publish_response"])
    tok = config.get("api_token") or ""
    site_id = config.get("site_id") or ""
    if not tok or not site_id:
        return {"ok": False, "error": "not_configured"}
    try:
        async with _client() as c:
            r = await c.post(
                f"https://api.netlify.com/api/v1/sites/{site_id}/files/{filename}",
                headers={"Authorization": f"Bearer {tok}",
                         "Content-Type": "application/octet-stream"},
                content=content)
        if 200 <= r.status_code < 300:
            d = r.json() if r.content else {}
            return {"ok": True,
                    "deploy_id": d.get("id") or d.get("sha"),
                    "url": (config.get("site_url") or "").rstrip("/") + "/" + filename}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:400]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


async def _vercel_test(config: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(config.get("_mock_test_response"), dict):
        return dict(config["_mock_test_response"])
    tok = config.get("api_token") or ""
    project_id = config.get("project_id") or ""
    if not tok or not project_id:
        return {"ok": False, "error": "not_configured"}
    try:
        async with _client() as c:
            r = await c.get(f"https://api.vercel.com/v9/projects/{project_id}",
                            headers={"Authorization": f"Bearer {tok}"})
        if 200 <= r.status_code < 300:
            d = r.json() if r.content else {}
            return {"ok": True,
                    "account_info": {"project_name": d.get("name"),
                                     "framework": d.get("framework")}}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


async def _vercel_publish(config: Dict[str, Any], filename: str,
                             content: bytes) -> Dict[str, Any]:
    """Vercel has no live single-file upload; we create a *new* deployment
    containing only `llms.txt`. This counts as a full redeploy of the project
    with just that file — the intended use is a project which has git-linked
    production and simply overlays this file via a manual deploy. Documented
    as a follow-up: for git-integrated projects prefer opening a commit PR."""
    if isinstance(config.get("_mock_publish_response"), dict):
        return dict(config["_mock_publish_response"])
    tok = config.get("api_token") or ""
    project_id = config.get("project_id") or ""
    if not tok or not project_id:
        return {"ok": False, "error": "not_configured"}
    try:
        # Vercel v13 deployments — inline file payload.
        body = {"name": project_id, "project": project_id,
                 "target": "production",
                 "files": [{"file": filename,
                             "data": content.decode("utf-8", errors="replace")}]}
        async with _client() as c:
            r = await c.post("https://api.vercel.com/v13/deployments",
                              headers={"Authorization": f"Bearer {tok}",
                                        "Content-Type": "application/json"},
                              json=body)
        if 200 <= r.status_code < 300:
            d = r.json() if r.content else {}
            return {"ok": True, "deploy_id": d.get("id") or d.get("uid"),
                    "url": d.get("url") or ""}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:400]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


async def _cf_test(config: Dict[str, Any]) -> Dict[str, Any]:
    tok = config.get("api_token") or ""
    acc = config.get("account_id") or ""
    proj = config.get("project_name") or ""
    if not tok or not acc or not proj:
        return {"ok": False, "error": "not_configured"}
    try:
        async with _client() as c:
            r = await c.get(
                f"https://api.cloudflare.com/client/v4/accounts/{acc}/pages/projects/{proj}",
                headers={"Authorization": f"Bearer {tok}"})
        if 200 <= r.status_code < 300:
            d = (r.json() if r.content else {}).get("result") or {}
            return {"ok": True,
                    "account_info": {"project_name": d.get("name"),
                                     "subdomain": d.get("subdomain"),
                                     "domains": d.get("domains") or []}}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


async def _cf_publish(config: Dict[str, Any], filename: str,
                         content: bytes) -> Dict[str, Any]:
    if isinstance(config.get("_mock_publish_response"), dict):
        return dict(config["_mock_publish_response"])
    tok = config.get("api_token") or ""
    acc = config.get("account_id") or ""
    proj = config.get("project_name") or ""
    if not tok or not acc or not proj:
        return {"ok": False, "error": "not_configured"}
    try:
        # CF Pages Direct Upload — multipart with `file` field.
        async with _client() as c:
            r = await c.post(
                f"https://api.cloudflare.com/client/v4/accounts/{acc}/pages/projects/{proj}/deployments",
                headers={"Authorization": f"Bearer {tok}"},
                files={filename: (filename, content, "text/plain")})
        if 200 <= r.status_code < 300:
            d = (r.json() if r.content else {}).get("result") or {}
            return {"ok": True, "deploy_id": d.get("id"),
                    "url": d.get("url") or ""}
        return {"ok": False, "error": f"http_{r.status_code}",
                "detail": r.text[:400]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "network_error", "detail": str(e)[:200]}


_ADAPTERS = {
    "netlify": {"test": _netlify_test, "publish": _netlify_publish},
    "vercel": {"test": _vercel_test, "publish": _vercel_publish},
    "cloudflare_pages": {"test": _cf_test, "publish": _cf_publish},
}


def is_supported(provider: str) -> bool:
    return provider in SUPPORTED


# ── Config CRUD ───────────────────────────────────────────────────
async def get_config(tenant_id: str, provider: str) -> Dict[str, Any]:
    row = await db.llmstxt_publish_configs.find_one(
        {"tenant_id": tenant_id, "provider": provider}, {"_id": 0}) or {}
    return row


async def get_configs_masked(tenant_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    async for r in db.llmstxt_publish_configs.find(
            {"tenant_id": tenant_id}, {"_id": 0}):
        r["api_token_masked"] = _mask(r.get("api_token") or "")
        r.pop("api_token", None)
        out.append(r)
    return out


async def save_config(tenant_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    provider = patch.get("provider") or ""
    if provider not in SUPPORTED:
        raise ValueError("unsupported_provider")
    existing = await get_config(tenant_id, provider)
    merged: Dict[str, Any] = dict(existing)
    merged["tenant_id"] = tenant_id
    merged["provider"] = provider
    for k in ("api_token", "site_id", "site_url", "project_id",
              "project_name", "account_id"):
        if k in patch and patch[k] is not None:
            merged[k] = patch[k]
    for k in ("enabled", "auto_publish_on_generate"):
        if k in patch and patch[k] is not None:
            merged[k] = bool(patch[k])
    merged["enabled"] = bool(merged.get("enabled", False))
    merged["auto_publish_on_generate"] = bool(merged.get("auto_publish_on_generate", False))
    now = datetime.now(timezone.utc).isoformat()
    if "created_at" not in merged:
        merged["created_at"] = now
    merged["updated_at"] = now
    await db.llmstxt_publish_configs.update_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"$set": merged}, upsert=True)
    m = dict(merged)
    m["api_token_masked"] = _mask(m.get("api_token") or "")
    m.pop("api_token", None)
    return m


async def delete_config(tenant_id: str, provider: str) -> Dict[str, Any]:
    r = await db.llmstxt_publish_configs.delete_one(
        {"tenant_id": tenant_id, "provider": provider})
    return {"deleted": r.deleted_count}


# ── Publish orchestrator + history ────────────────────────────────
async def test_connection(tenant_id: str,
                             provider: str) -> Dict[str, Any]:
    if provider not in SUPPORTED:
        return {"ok": False, "error": "unsupported_provider"}
    cfg = await get_config(tenant_id, provider)
    if not cfg:
        return {"ok": False, "error": "not_configured"}
    return await _ADAPTERS[provider]["test"](cfg)


async def publish(tenant_id: str, provider: str, *, filename: str,
                     content: bytes, requested_by: str = "") -> Dict[str, Any]:
    """Persist a pending history row, call provider, update history.

    Returns `{publish_id, status, provider_deploy_id?, provider_url?,
              error_message?, http_status_hint}`.
    """
    if provider not in SUPPORTED:
        return {"publish_id": "", "status": "failed",
                "error_message": "unsupported_provider",
                "http_status_hint": 400}
    cfg = await get_config(tenant_id, provider)
    if not cfg:
        return {"publish_id": "", "status": "failed",
                "error_message": "not_configured",
                "http_status_hint": 400}
    publish_id = f"lp_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    row = {"tenant_id": tenant_id, "publish_id": publish_id,
            "provider": provider, "filename": filename,
            "content_bytes_hash": hashlib.sha256(content).hexdigest()[:32],
            "size_bytes": len(content),
            "requested_at": now, "requested_by": requested_by or "unknown",
            "status": "pending"}
    await db.llmstxt_publish_history.insert_one({**row})
    try:
        r = await _ADAPTERS[provider]["publish"](cfg, filename, content)
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "error": "unhandled",
              "detail": str(e)[:400]}
    completed = datetime.now(timezone.utc).isoformat()
    status = "success" if r.get("ok") else "failed"
    update: Dict[str, Any] = {"status": status, "completed_at": completed}
    if r.get("deploy_id"):
        update["provider_deploy_id"] = r["deploy_id"]
    if r.get("url"):
        update["provider_url"] = r["url"]
    if not r.get("ok"):
        update["error_message"] = r.get("error", "") + (
            (": " + r.get("detail", "")) if r.get("detail") else "")
    await db.llmstxt_publish_history.update_one(
        {"tenant_id": tenant_id, "publish_id": publish_id},
        {"$set": update})
    await db.llmstxt_publish_configs.update_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"$set": {"last_publish_at": completed,
                    "last_publish_status": status}})
    out: Dict[str, Any] = {"publish_id": publish_id, "status": status,
                            "provider_deploy_id": r.get("deploy_id") or "",
                            "provider_url": r.get("url") or "",
                            "http_status_hint": 200 if r.get("ok") else 502}
    if not r.get("ok"):
        out["error_message"] = update.get("error_message", "")
    return out


async def history(tenant_id: str, provider: Optional[str] = None,
                     limit: int = 20) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if provider:
        q["provider"] = provider
    cur = db.llmstxt_publish_history.find(q, {"_id": 0}).sort(
        "requested_at", -1).limit(int(limit))
    out: List[Dict[str, Any]] = []
    async for r in cur:
        out.append(r)
    return out


# ── Auto-publish hook (Phase 5a integration) ──────────────────────
async def auto_publish_on_generate(tenant_id: str, filename: str,
                                        content: bytes,
                                        requested_by: str = "") -> Dict[str, Any]:
    """Called from POST /aeo/llms-txt/generate. Publishes to every enabled
    provider that has `auto_publish_on_generate=true`. Returns
    `{triggered: bool, results: [...]}`. Failures do NOT raise."""
    triggered = 0
    results: List[Dict[str, Any]] = []
    async for cfg in db.llmstxt_publish_configs.find(
            {"tenant_id": tenant_id, "enabled": True,
              "auto_publish_on_generate": True}, {"_id": 0}):
        provider = cfg.get("provider") or ""
        if provider not in SUPPORTED:
            continue
        try:
            r = await publish(tenant_id, provider, filename=filename,
                                 content=content, requested_by=requested_by or "auto")
            triggered += 1
            results.append({"provider": provider, "status": r["status"],
                             "publish_id": r.get("publish_id"),
                             "error_message": r.get("error_message")})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[llmstxt_publish] auto-publish {provider} failed: {e}")
            results.append({"provider": provider, "status": "failed",
                             "error_message": str(e)[:200]})
    return {"triggered": triggered > 0, "results": results}
