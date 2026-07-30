"""Phase 5a · Feb-2026 — AEO endpoints (JSON-LD + LLMs.txt).

Admin / Super Admin / Manager only, tenant-scoped. AEO Auditor is
folded into the existing ``/api/seo/scans`` endpoint by editing the
scanner; this router only carries the two generators.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from services.aeo_generators import generate_jsonld, generate_llms_txt
from utils import get_current_user

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager"}


def _require_mod(user: Dict[str, Any]) -> None:
    if (user.get("role") or "").lower() not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


async def _tenant_row(tenant_id: str) -> Dict[str, Any]:
    row = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    return row


# ─── JSON-LD generator ────────────────────────────────────────────

class JsonldBody(BaseModel):
    types: List[str] = Field(default_factory=list)
    business_profile: Dict[str, Any] = Field(default_factory=dict)
    faqs: Optional[List[Dict[str, str]]] = None
    howto: Optional[Dict[str, Any]] = None
    services: Optional[List[Dict[str, Any]]] = None


@router.post("/aeo/jsonld/generate",
              operation_id="aeo.generateJsonld", tags=["aeo"])
async def api_generate_jsonld(body: JsonldBody,
                                caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)

    # Auto-fill missing fields from the tenant row.
    profile = dict(body.business_profile or {})
    tenant = await _tenant_row(tenant_id)
    for k_prof, k_tenant in [("name", "name"),
                                ("url", "url"),
                                ("phone", "phone"),
                                ("email", "email"),
                                ("address", "address"),
                                ("service_areas", "service_areas"),
                                ("services", "services"),
                                ("hours", "hours"),
                                ("same_as", "same_as")]:
        if not profile.get(k_prof) and tenant.get(k_tenant):
            profile[k_prof] = tenant[k_tenant]
    # Some tenants use `business_name`.
    if not profile.get("name") and tenant.get("business_name"):
        profile["name"] = tenant["business_name"]

    if not body.types:
        raise HTTPException(400, {"error": "types_required"})
    try:
        out = generate_jsonld(
            types=body.types, business_profile=profile,
            faqs=body.faqs, howto=body.howto, services=body.services,
        )
    except ValueError as e:
        raise HTTPException(422, {"error": "invalid_jsonld",
                                    "detail": str(e)[:200]})
    return {**out, "resolved_profile_keys": sorted(list(profile.keys()))}


# ─── LLMs.txt generator ───────────────────────────────────────────

class LlmsTxtBody(BaseModel):
    style: str = Field("concise", pattern=r"^(concise|full)$")
    include_faqs: bool = False


@router.post("/aeo/llms-txt/generate",
              operation_id="aeo.generateLlmsTxt", tags=["aeo"])
async def api_generate_llms_txt(body: LlmsTxtBody,
                                  caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    tenant = await _tenant_row(tenant_id)
    if not tenant:
        raise HTTPException(404, {"error": "tenant_not_found"})

    # Pull last 5 published check-ins for the "Recent work" section
    # (best-effort — not fatal if the collection doesn't exist).
    recent: List[Dict[str, Any]] = []
    try:
        cursor = db.checkins.find(
            {"tenant_id": tenant_id, "published": True},
            {"_id": 0, "title": 1, "summary": 1, "notes": 1,
              "created_at": 1},
        ).sort("created_at", -1).limit(5)
        async for c in cursor:
            recent.append(c)
    except Exception:
        recent = []

    out = generate_llms_txt(tenant=tenant, style=body.style,
                              include_faqs=body.include_faqs,
                              recent_checkins=recent)
    return out
