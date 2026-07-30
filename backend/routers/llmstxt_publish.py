"""Phase 9 · Feb-2026 — LLMs.txt publish endpoints.

Six endpoints, admin/super_admin/manager only (Tech + Customer → 403).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db  # noqa: F401
from services import llmstxt_publish as svc
from services.aeo_generators import generate_llms_txt
from utils import get_current_user


router = APIRouter()
_MOD = {"admin", "super_admin", "manager"}


def _require_mod(u: Dict[str, Any]) -> None:
    if (u.get("role") or "").lower() not in _MOD:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(u: Dict[str, Any]) -> str:
    tid = u.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


def _guard_provider(p: str) -> None:
    if not svc.is_supported(p):
        raise HTTPException(400, {"error": "unsupported_provider",
                                    "supported": list(svc.SUPPORTED)})


# ── 1. GET providers ──────────────────────────────────────────────
@router.get("/aeo/llms-txt/publish/providers",
             operation_id="llmstxtPublish.list", tags=["aeo"])
async def api_list(caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    return {"items": await svc.get_configs_masked(tid),
            "supported": list(svc.SUPPORTED)}


# ── 2. POST config ─────────────────────────────────────────────────
class ConfigBody(BaseModel):
    provider: str
    api_token: Optional[str] = None
    site_id: Optional[str] = None
    site_url: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    account_id: Optional[str] = None
    enabled: Optional[bool] = None
    auto_publish_on_generate: Optional[bool] = None


@router.post("/aeo/llms-txt/publish/config",
              operation_id="llmstxtPublish.saveConfig", tags=["aeo"])
async def api_save_config(body: ConfigBody,
                             caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    _guard_provider(body.provider)
    try:
        return await svc.save_config(tid, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, {"error": str(e)})


# ── 3. DELETE config ───────────────────────────────────────────────
@router.delete("/aeo/llms-txt/publish/config/{provider}",
                operation_id="llmstxtPublish.deleteConfig", tags=["aeo"])
async def api_delete_config(provider: str,
                               caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    _guard_provider(provider)
    return await svc.delete_config(tid, provider)


# ── 4. POST test connection ────────────────────────────────────────
@router.post("/aeo/llms-txt/publish/test/{provider}",
              operation_id="llmstxtPublish.test", tags=["aeo"])
async def api_test(provider: str,
                      caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    _guard_provider(provider)
    r = await svc.test_connection(tid, provider)
    return r


# ── 5. POST publish ────────────────────────────────────────────────
class PublishBody(BaseModel):
    style: str = Field("concise", pattern=r"^(concise|full)$")
    include_faqs: bool = False


@router.post("/aeo/llms-txt/publish/{provider}",
              operation_id="llmstxtPublish.publish", tags=["aeo"])
async def api_publish(provider: str, body: PublishBody,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    _guard_provider(provider)
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    if not tenant:
        raise HTTPException(404, {"error": "tenant_not_found"})
    # Recent check-ins for "full" style parity with Phase 5a.
    recent: List[Dict[str, Any]] = []
    try:
        async for c in db.checkins.find(
                {"tenant_id": tid, "published": True},
                {"_id": 0, "title": 1, "summary": 1, "notes": 1,
                  "created_at": 1}).sort("created_at", -1).limit(5):
            recent.append(c)
    except Exception:
        recent = []
    gen = generate_llms_txt(tenant=tenant, style=body.style,
                               include_faqs=body.include_faqs,
                               recent_checkins=recent)
    content = gen["content"].encode("utf-8")
    r = await svc.publish(tid, provider, filename=gen["filename"],
                             content=content,
                             requested_by=caller.get("id") or caller.get("email") or "")
    if r.get("http_status_hint") == 400:
        raise HTTPException(400, {"error": r.get("error_message") or "not_configured",
                                    "publish_id": r.get("publish_id")})
    if r.get("http_status_hint") == 502:
        raise HTTPException(502, {"error": "upstream_error",
                                    "publish_id": r.get("publish_id"),
                                    "detail": r.get("error_message")})
    return {"publish_id": r["publish_id"], "status": r["status"],
            "provider_deploy_id": r.get("provider_deploy_id") or "",
            "provider_url": r.get("provider_url") or "",
            "filename": gen["filename"], "size_bytes": len(content)}


# ── 6. GET history ────────────────────────────────────────────────
@router.get("/aeo/llms-txt/publish/history",
             operation_id="llmstxtPublish.history", tags=["aeo"])
async def api_history(provider: Optional[str] = None, limit: int = 20,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant_or_400(caller)
    items = await svc.history(tid, provider=provider, limit=limit)
    return {"items": items, "count": len(items)}
