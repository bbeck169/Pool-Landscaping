"""Phase 8 · Feb-2026 — AEO Digest endpoints (5)."""
from __future__ import annotations

from base64 import b64decode
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from config import db
from services.aeo_digest import (
    build_snapshot, run_digest, get_settings, save_settings,
    sign_pdf_url, verify_pdf_signature, render_pdf,
)
from utils import get_current_user

router = APIRouter()
_MOD = {"admin", "super_admin", "manager"}


def _require_mod(u):
    if (u.get("role") or "").lower() not in _MOD:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant(u):
    t = u.get("tenant_id") or ""
    if not t: raise HTTPException(400, {"error": "missing_tenant"})
    return t


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


class PreviewBody(BaseModel):
    period_end: Optional[str] = None


@router.post("/aeo/digest/preview",
              operation_id="aeoDigest.preview", tags=["aeo"])
async def api_preview(body: PreviewBody,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant(caller)
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tenant = {"id": tid, **t}
    r = await run_digest(tenant, period_end=_parse_date(body.period_end),
                            deliver=False, persist=True,
                            generated_by=caller.get("id", ""))
    return {"digest_id": r["digest_id"],
            "metrics_snapshot": r["snapshot"],
            "pdf_url": r["pdf_url"], "pdf_size_bytes": r["pdf_size_bytes"]}


class RunNowBody(BaseModel):
    period_end: Optional[str] = None
    deliver: bool = True


@router.post("/aeo/digest/run-now",
              operation_id="aeoDigest.runNow", tags=["aeo"])
async def api_run_now(body: RunNowBody,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant(caller)
    t = await db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    tenant = {"id": tid, **t}
    return await run_digest(tenant, period_end=_parse_date(body.period_end),
                               deliver=body.deliver, persist=True,
                               generated_by=caller.get("id", ""))


@router.get("/aeo/digest/history",
             operation_id="aeoDigest.history", tags=["aeo"])
async def api_history(limit: int = 20,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant(caller)
    items = []
    async for r in db.aeo_digest_runs.find({"tenant_id": tid},
                                              {"_id": 0}).sort("generated_at", -1).limit(limit):
        r["pdf_url"] = sign_pdf_url(tid, r["digest_id"])
        items.append(r)
    return {"items": items, "count": len(items)}


class SettingsBody(BaseModel):
    enabled: Optional[bool] = None
    recipient_emails: Optional[List[str]] = None
    day_of_week: Optional[int] = None
    hour_utc: Optional[int] = None
    include_negative_snippets: Optional[bool] = None


@router.post("/aeo/digest/settings",
              operation_id="aeoDigest.saveSettings", tags=["aeo"])
async def api_save_settings(body: SettingsBody,
                              caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant(caller)
    return await save_settings(tid, body.model_dump(exclude_none=True))


@router.get("/aeo/digest/settings",
             operation_id="aeoDigest.getSettings", tags=["aeo"])
async def api_get_settings(caller: Dict[str, Any] = Depends(get_current_user)):
    _require_mod(caller); tid = _tenant(caller)
    return await get_settings(tid)


# Signed public PDF download (no auth required — HMAC + expiry).
@router.get("/aeo/digest/pdf/{digest_id}",
             include_in_schema=False)
async def api_pdf_download(digest_id: str, tid: str, exp: int, sig: str):
    if not verify_pdf_signature(tid, digest_id, exp, sig):
        raise HTTPException(403, {"error": "invalid_or_expired_signature"})
    row = await db.aeo_digest_pdfs.find_one({"tenant_id": tid,
                                                "digest_id": digest_id},
                                               {"_id": 0, "body_b64": 1})
    if not row:
        raise HTTPException(404, {"error": "pdf_not_found"})
    return Response(content=b64decode(row["body_b64"]),
                     media_type="application/pdf",
                     headers={"Content-Disposition": f'inline; filename="{digest_id}.pdf"'})
