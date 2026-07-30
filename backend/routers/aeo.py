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
from services.aeo_visibility import (
    run_probes, dashboard_for_tenant, history_for_tenant,
    DUPLICATE_HOURS, MONTHLY_COST_CAP_USD,
)
from services.aeo_fixes import generate_fixes as _gen_fixes
from services.aeo_visibility import check_fix_rate_limit
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

# ─── Phase 5b · AI Visibility Tracker ─────────────────────────────

class VisibilityRunBody(BaseModel):
    query_templates: Optional[List[str]] = None
    providers: Optional[List[Dict[str, str]]] = None


@router.post("/aeo/visibility/run-now",
              operation_id="aeo.visibilityRunNow", tags=["aeo"])
async def api_visibility_run_now(body: VisibilityRunBody,
                                   caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    tenant = await _tenant_row(tenant_id)
    if not tenant:
        raise HTTPException(404, {"error": "tenant_not_found"})
    tenant = {"id": tenant_id, **tenant}
    from datetime import datetime, timedelta, timezone
    dup_cutoff = (datetime.now(timezone.utc)
                    - timedelta(hours=DUPLICATE_HOURS)).isoformat()
    recent = await db.aeo_visibility_probes.find_one(
        {"tenant_id": tenant_id, "ran_at": {"$gte": dup_cutoff}},
        {"_id": 0, "probe_id": 1, "ran_at": 1})
    if recent:
        return {"probes": [], "summary": {"total": 0, "mentions": 0,
                                             "avg_score": 0},
                "cost_capped": False, "skipped_reason": "cooldown",
                "next_available_after_hours": DUPLICATE_HOURS,
                "last_ran_at": recent.get("ran_at")}
    out = await run_probes(tenant, templates=body.query_templates,
                              providers=body.providers)
    return out


@router.get("/aeo/visibility/history",
             operation_id="aeo.visibilityHistory", tags=["aeo"])
async def api_visibility_history(range: str = "30d",
                                    caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    return await history_for_tenant(tenant_id, range_key=range)


@router.get("/aeo/visibility/dashboard",
             operation_id="aeo.visibilityDashboard", tags=["aeo"])
async def api_visibility_dashboard(caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    return await dashboard_for_tenant(tenant_id)


# ─── Phase 5b · LLM fix recommendations ───────────────────────────

class FixesGenerateBody(BaseModel):
    scan_id: str = Field(..., min_length=1)
    sub_signals: Optional[List[str]] = None


@router.post("/aeo/fixes/generate",
              operation_id="aeo.fixesGenerate", tags=["aeo"])
async def api_fixes_generate(body: FixesGenerateBody,
                               caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    retry = check_fix_rate_limit(tenant_id)
    if retry is not None:
        raise HTTPException(429, headers={"Retry-After": str(retry)},
                              detail={"error": "rate_limited",
                                        "retry_after_sec": retry})
    tenant = await _tenant_row(tenant_id)
    tenant = {"id": tenant_id, **(tenant or {})}
    # Cross-tenant scan protection.
    scan = await db.seo_scans.find_one(
        {"id": body.scan_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1})
    if not scan:
        raise HTTPException(404, {"error": "scan_not_found"})
    out = await _gen_fixes(body.scan_id, tenant,
                              requested_signals=body.sub_signals)
    return out


class FixApplyBody(BaseModel):
    applied: bool = True


@router.post("/aeo/fixes/{fix_id}/apply",
              operation_id="aeo.fixesApply", tags=["aeo"])
async def api_fix_apply(fix_id: str, body: FixApplyBody,
                         caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    from bson import ObjectId
    from datetime import datetime, timezone
    try:
        oid = ObjectId(fix_id)
    except Exception:
        raise HTTPException(400, {"error": "invalid_fix_id"})
    r = await db.aeo_fixes.update_one(
        {"_id": oid, "tenant_id": tenant_id},
        {"$set": {"applied": body.applied,
                   "applied_at": datetime.now(timezone.utc).isoformat()
                     if body.applied else None,
                   "applied_by": caller["id"] if body.applied else None}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, {"error": "fix_not_found"})
    return {"ok": True, "applied": body.applied}


@router.get("/aeo/fixes/pending",
             operation_id="aeo.fixesPending", tags=["aeo"])
async def api_fixes_pending(scan_id: Optional[str] = None,
                              caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    q = {"tenant_id": tenant_id, "applied": False,
         "superseded": {"$in": [False, None]}}
    if scan_id:
        q["scan_id"] = scan_id
    items: List[Dict[str, Any]] = []
    async for row in db.aeo_fixes.find(q).sort("generated_at", -1).limit(50):
        row["_id"] = str(row["_id"])
        items.append(row)
    return {"items": items, "count": len(items)}

