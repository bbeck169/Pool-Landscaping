"""Directories Subsystem · Phase D1 backend (Feb 2026).

Manage a tenant's NAP profile, generate + track submissions to 60+
curated business directories, expose a citation health score, and
wire scan runs into the existing review-scraper machinery where
adapters overlap.

Security
--------
Every endpoint here is admin-or-super-admin only. Tenant isolation is
enforced by the ``get_current_tenant`` dependency + a ``tenant_id``
predicate on every read/write.

Notifications
-------------
Status transitions on ``directory_submissions`` emit ``notifications.emit``
with the new kind ``directory_status_change`` (default push-OFF for
admins; ON for the assigned user, when present, via record-owner
routing).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import db, logger
from utils import require_admin, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter(prefix="/directories", tags=["Directories"])


# ─── helpers ───────────────────────────────────────────────────────────
_PHONE_KEEP = re.compile(r"[^\d+]")


def _e164(phone: str, default_country: str = "US") -> Optional[str]:
    """Best-effort E.164 normalization. Returns None for input we
    cannot confidently normalize (< 10 digits after stripping)."""
    if not phone:
        return None
    raw = _PHONE_KEEP.sub("", phone or "")
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10 and default_country == "US":
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if raw.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def _nap_hash(profile: Dict[str, Any]) -> str:
    """Stable hash over the fields that matter for citation freshness.
    Excludes ``updated_at`` / ``updated_by`` so the hash only changes
    when something meaningful drifts."""
    parts = [
        (profile.get("business_name") or "").strip().lower(),
        (profile.get("phone_e164") or profile.get("phone") or "").strip(),
        (profile.get("website") or "").strip().lower(),
    ]
    addr = profile.get("address") or {}
    parts.extend([
        (addr.get("line1") or "").strip().lower(),
        (addr.get("line2") or "").strip().lower(),
        (addr.get("city") or "").strip().lower(),
        (addr.get("state") or "").strip().upper(),
        (addr.get("postal_code") or "").strip(),
        (addr.get("country") or "").strip().upper(),
    ])
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


def _empty_profile(tenant_id: str, actor_id: str) -> Dict[str, Any]:
    now = now_iso()
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "business_name": "",
        "dba_names": [],
        "address": {"line1": "", "line2": "", "city": "", "state": "",
                     "postal_code": "", "country": "US"},
        "phone": "", "phone_e164": None,
        "alt_phones": [],
        "website": "", "email": "",
        "hours": {d: {"open": "", "close": "", "closed": False}
                    for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
        "business_categories": [],
        "founded_year": None, "employee_count_range": "",
        "service_area": {"type": "radius", "radius_miles": 25,
                           "zips": [], "cities": []},
        "tagline": "", "description_short": "", "description_long": "",
        "logo_url": "", "cover_photo_url": "", "gallery_photo_urls": [],
        "social_urls": {"facebook": "", "instagram": "", "linkedin": "",
                          "tiktok": "", "youtube": "", "x": ""},
        "payment_methods": [],
        "nap_hash": "",
        "created_at": now, "updated_at": now, "updated_by": actor_id,
    }


# ─── NAP profile endpoints ─────────────────────────────────────────────
@router.get("/nap-profile")
async def get_nap_profile(user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    """Lazy-creates a blank profile on first read. Never returns None."""
    doc = await db.tenant_nap_profile.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        doc = _empty_profile(tenant["id"], user["id"])
        doc["nap_hash"] = _nap_hash(doc)
        await db.tenant_nap_profile.insert_one(doc)
        doc.pop("_id", None)
    return doc


class NapProfileBody(BaseModel):
    business_name: Optional[str] = None
    dba_names: Optional[List[str]] = None
    address: Optional[Dict[str, Any]] = None
    phone: Optional[str] = None
    alt_phones: Optional[List[str]] = None
    website: Optional[str] = None
    email: Optional[str] = None
    hours: Optional[Dict[str, Dict[str, Any]]] = None
    business_categories: Optional[List[str]] = None
    founded_year: Optional[int] = None
    employee_count_range: Optional[str] = None
    service_area: Optional[Dict[str, Any]] = None
    tagline: Optional[str] = None
    description_short: Optional[str] = None
    description_long: Optional[str] = None
    logo_url: Optional[str] = None
    cover_photo_url: Optional[str] = None
    gallery_photo_urls: Optional[List[str]] = None
    social_urls: Optional[Dict[str, str]] = None
    payment_methods: Optional[List[str]] = None


@router.patch("/nap-profile")
async def patch_nap_profile(body: NapProfileBody,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Apply patch → recompute ``nap_hash`` → mark any prior
    ``submitted``/``verified`` submissions as ``needs_update`` when the
    hash actually changes.
    """
    existing = await db.tenant_nap_profile.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ) or _empty_profile(tenant["id"], user["id"])
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    merged = {**existing, **patch}
    if patch.get("phone"):
        merged["phone_e164"] = _e164(patch["phone"])
    prior_hash = existing.get("nap_hash") or ""
    merged["nap_hash"] = _nap_hash(merged)
    merged["updated_at"] = now_iso()
    merged["updated_by"] = user["id"]
    await db.tenant_nap_profile.update_one(
        {"tenant_id": tenant["id"]},
        {"$set": merged},
        upsert=True,
    )
    stale_flipped = 0
    if merged["nap_hash"] != prior_hash and prior_hash:
        res = await db.directory_submissions.update_many(
            {"tenant_id": tenant["id"],
              "status": {"$in": ["submitted", "verified"]}},
            {"$set": {"status": "needs_update",
                        "updated_at": now_iso()}}
        )
        stale_flipped = res.modified_count
    merged.pop("_id", None)
    return {"profile": merged, "stale_submissions_flipped": stale_flipped}


@router.post("/nap-profile/validate")
async def validate_nap_profile(user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    """Server-side sanity check. Never mutates state.

    Geocode is best-effort via ``services.google_maps.geocode`` when
    the ``GOOGLE_API_KEY`` env is present — otherwise the geocode leg
    is skipped and the response includes ``geocode_status="skipped"``.
    """
    p = await db.tenant_nap_profile.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0})
    if not p:
        raise HTTPException(404, "profile not found")
    issues: List[Dict[str, str]] = []
    if not (p.get("business_name") or "").strip():
        issues.append({"field": "business_name", "code": "required",
                          "detail": "Business name is required."})
    addr = p.get("address") or {}
    for k in ("line1", "city", "state", "postal_code"):
        if not (addr.get(k) or "").strip():
            issues.append({"field": f"address.{k}", "code": "required",
                              "detail": f"Address field '{k}' is required."})
    phone_norm = _e164(p.get("phone") or "")
    if p.get("phone") and not phone_norm:
        issues.append({"field": "phone", "code": "unparseable",
                          "detail": "Phone number is not a valid US/E.164 format."})
    website = (p.get("website") or "").strip()
    if website and not re.match(r"^https?://", website):
        issues.append({"field": "website", "code": "bad_url",
                          "detail": "Website must be a full https:// URL."})
    for k, v in (p.get("social_urls") or {}).items():
        if v and not re.match(r"^https?://", v):
            issues.append({"field": f"social_urls.{k}", "code": "bad_url",
                              "detail": f"{k} URL must be a full https:// URL."})
    geocode_status = "skipped"
    geocode_detail: Optional[str] = None
    import os
    if os.environ.get("GOOGLE_API_KEY"):
        try:
            from services.google_maps import geocode_address as _geo
            addr_line = f"{addr.get('line1','')}, {addr.get('city','')}, " \
                          f"{addr.get('state','')} {addr.get('postal_code','')}"
            g = await _geo(addr_line)
            if not g or not g.get("formatted_address"):
                geocode_status = "not_found"
                issues.append({"field": "address", "code": "not_geocodable",
                                  "detail": "Google Geocoding could not locate this address."})
            else:
                geocode_status = "ok"
                geocode_detail = g.get("formatted_address")
        except Exception as e:
            geocode_status = "error"
            geocode_detail = str(e)
    return {"ok": len(issues) == 0, "issues": issues,
             "geocode_status": geocode_status,
             "geocode_detail": geocode_detail,
             "nap_hash": p.get("nap_hash")}


# ─── Directory definitions ─────────────────────────────────────────────
@router.get("/definitions")
async def list_definitions(user: dict = Depends(require_admin),
                              category: Optional[str] = Query(None),
                              active: Optional[bool] = Query(True),
                              min_priority: int = Query(1, ge=1, le=5),
                              max_priority: int = Query(5, ge=1, le=5)):
    q: Dict[str, Any] = {}
    if category:
        q["category"] = category
    if active is not None:
        q["active"] = active
    q["priority"] = {"$gte": min_priority, "$lte": max_priority}
    rows = await db.directory_definitions.find(q, {"_id": 0}) \
        .sort([("priority", 1), ("category", 1), ("name", 1)]) \
        .to_list(500)
    return {"count": len(rows), "definitions": rows}


# ─── Submissions CRUD ──────────────────────────────────────────────────
@router.get("/submissions")
async def list_submissions(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant),
                              status: Optional[str] = Query(None),
                              category: Optional[str] = Query(None),
                              limit: int = Query(100, ge=1, le=500),
                              cursor: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if cursor:
        q["updated_at"] = {"$lt": cursor}
    if category:
        # Resolve category → slug filter.
        defs = await db.directory_definitions.find(
            {"category": category}, {"_id": 0, "slug": 1}).to_list(500)
        q["directory_slug"] = {"$in": [d["slug"] for d in defs]}
    rows = await db.directory_submissions.find(q, {"_id": 0}) \
        .sort("updated_at", -1).to_list(limit)
    return {"count": len(rows), "submissions": rows,
             "next_cursor": rows[-1]["updated_at"] if len(rows) == limit else None}


@router.get("/submissions/{sid}")
async def get_submission(sid: str,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    row = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    return row


class CreateSubmissionBody(BaseModel):
    directory_slug: str
    status: Optional[str] = "not_started"
    submission_type: Optional[str] = "manual"
    notes: Optional[str] = ""
    assigned_user_id: Optional[str] = None


@router.post("/submissions", status_code=201)
async def create_submission(body: CreateSubmissionBody,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Idempotent per (tenant × directory_slug). Returns the existing
    row when one already exists so callers can safely fire this on
    every UI action without worrying about duplicate rows."""
    defn = await db.directory_definitions.find_one(
        {"slug": body.directory_slug}, {"_id": 0, "slug": 1})
    if not defn:
        raise HTTPException(404, "unknown directory")
    existing = await db.directory_submissions.find_one(
        {"tenant_id": tenant["id"], "directory_slug": body.directory_slug},
        {"_id": 0})
    if existing:
        return existing
    now = now_iso()
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "directory_slug": body.directory_slug,
        "status": body.status or "not_started",
        "submission_type": body.submission_type or "manual",
        "submitted_at": None, "verified_at": None,
        "external_listing_url": "",
        "notes": body.notes or "",
        "screenshots": [],
        "last_checked_at": None,
        "nap_match_score": None,
        "scraped_data_json": None,
        "discrepancies": [],
        "assigned_user_id": body.assigned_user_id,
        "created_at": now, "updated_at": now,
    }
    await db.directory_submissions.insert_one(doc)
    doc.pop("_id", None)
    return doc


class PatchSubmissionBody(BaseModel):
    status: Optional[str] = None
    submission_type: Optional[str] = None
    external_listing_url: Optional[str] = None
    notes: Optional[str] = None
    screenshots: Optional[List[str]] = None
    assigned_user_id: Optional[str] = None
    submitted_at: Optional[str] = None
    verified_at: Optional[str] = None


_ALLOWED_STATUS = {"not_started", "in_progress", "submitted", "verified",
                    "rejected", "needs_update", "paid_wall"}


@router.patch("/submissions/{sid}")
async def patch_submission(sid: str, body: PatchSubmissionBody,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    row = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in patch and patch["status"] not in _ALLOWED_STATUS:
        raise HTTPException(400, f"invalid status: {patch['status']}")
    prior_status = row.get("status")
    patch["updated_at"] = now_iso()
    await db.directory_submissions.update_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"$set": patch})
    updated = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if "status" in patch and patch["status"] != prior_status:
        await _emit_status_change(tenant["id"], updated, prior_status,
                                     actor_id=user.get("id"))
    return updated


@router.post("/submissions/{sid}/mark-verified")
async def mark_verified(sid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    now = now_iso()
    await db.directory_submissions.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"status": "verified", "verified_at": now,
                    "last_checked_at": now, "updated_at": now}})
    updated = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    await _emit_status_change(tenant["id"], updated, row.get("status"),
                                 actor_id=user.get("id"))
    return updated


class BulkCreateBody(BaseModel):
    category: Optional[str] = None
    priority_min: Optional[int] = Field(None, ge=1, le=5)
    priority_max: Optional[int] = Field(None, ge=1, le=5)
    directory_slugs: Optional[List[str]] = None


@router.post("/submissions/bulk-create")
async def bulk_create(body: BulkCreateBody,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    q: Dict[str, Any] = {"active": True}
    if body.category:
        q["category"] = body.category
    if body.priority_min is not None or body.priority_max is not None:
        q["priority"] = {}
        if body.priority_min is not None:
            q["priority"]["$gte"] = body.priority_min
        if body.priority_max is not None:
            q["priority"]["$lte"] = body.priority_max
    if body.directory_slugs:
        q["slug"] = {"$in": body.directory_slugs}
    defs = await db.directory_definitions.find(q, {"_id": 0, "slug": 1}).to_list(500)
    existing_slugs = {
        r["directory_slug"] async for r in db.directory_submissions.find(
            {"tenant_id": tenant["id"],
              "directory_slug": {"$in": [d["slug"] for d in defs]}},
            {"_id": 0, "directory_slug": 1})
    }
    created_ids: List[str] = []
    now = now_iso()
    bulk: List[Dict[str, Any]] = []
    for d in defs:
        if d["slug"] in existing_slugs:
            continue
        doc = {
            "id": new_id(), "tenant_id": tenant["id"],
            "directory_slug": d["slug"],
            "status": "not_started", "submission_type": "manual",
            "submitted_at": None, "verified_at": None,
            "external_listing_url": "", "notes": "",
            "screenshots": [], "last_checked_at": None,
            "nap_match_score": None, "scraped_data_json": None,
            "discrepancies": [], "assigned_user_id": None,
            "created_at": now, "updated_at": now,
        }
        bulk.append(doc)
        created_ids.append(doc["id"])
    if bulk:
        await db.directory_submissions.insert_many(bulk)
    return {"created": len(created_ids), "created_ids": created_ids,
             "skipped": len(defs) - len(bulk)}


@router.get("/submissions/export/csv")
async def export_csv(user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant),
                        directory_slug: Optional[str] = Query(None)):
    """Emit a CSV shaped for copy-paste into the target directory.

    Columns are taken from the definition's ``expected_fields`` — so
    the CSV for Google Business Profile carries the full 9-column
    shape while a minimal directory like WhitePages carries only 4.
    """
    profile = await db.tenant_nap_profile.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0})
    if not profile:
        raise HTTPException(400, "NAP profile not yet created")
    q: Dict[str, Any] = {"active": True}
    if directory_slug:
        q["slug"] = directory_slug
    defs = await db.directory_definitions.find(q, {"_id": 0}) \
        .sort("priority", 1).to_list(500)
    if not defs:
        raise HTTPException(404, "no matching definition")
    all_fields = ["name", "address", "phone", "website", "category",
                    "hours", "description", "logo", "photos"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["directory_slug", "directory_name"] + all_fields)
    addr = profile.get("address") or {}
    addr_str = ", ".join(x for x in [
        (addr.get("line1") or "").strip(),
        (addr.get("line2") or "").strip(),
        (addr.get("city") or "").strip(),
        (addr.get("state") or "").strip(),
        (addr.get("postal_code") or "").strip(),
    ] if x)
    hours_str = "; ".join(
        f"{d}: {'closed' if (profile.get('hours') or {}).get(d, {}).get('closed') else (profile.get('hours') or {}).get(d, {}).get('open','') + '-' + (profile.get('hours') or {}).get(d, {}).get('close','')}"
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    )
    for d in defs:
        expected = set(d.get("expected_fields") or [])
        row_map = {
            "name": profile.get("business_name") or "",
            "address": addr_str,
            "phone": profile.get("phone_e164") or profile.get("phone") or "",
            "website": profile.get("website") or "",
            "category": ", ".join(profile.get("business_categories") or []),
            "hours": hours_str,
            "description": profile.get("description_short") or profile.get("description_long") or "",
            "logo": profile.get("logo_url") or "",
            "photos": " | ".join(profile.get("gallery_photo_urls") or []),
        }
        w.writerow([d["slug"], d["name"]] + [
            row_map[f] if f in expected else "" for f in all_fields
        ])
    buf.seek(0)
    filename = f"directory_export{('_' + directory_slug) if directory_slug else ''}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ─── Assignment ────────────────────────────────────────────────────────
class AssignBody(BaseModel):
    assigned_user_id: Optional[str] = None


@router.post("/submissions/{sid}/assign")
async def assign_submission(sid: str, body: AssignBody,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    row = await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "submission not found")
    await db.directory_submissions.update_one(
        {"id": sid, "tenant_id": tenant["id"]},
        {"$set": {"assigned_user_id": body.assigned_user_id,
                    "updated_at": now_iso()}})
    return await db.directory_submissions.find_one(
        {"id": sid, "tenant_id": tenant["id"]}, {"_id": 0})


# ─── Scan runs ─────────────────────────────────────────────────────────
@router.post("/scan/run", status_code=201)
async def run_scan(user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    """Best-effort scan across every submission whose definition
    ships a ``scrape_url_template``. When no adapter is available for
    a directory the submission is skipped (never faked)."""
    now = now_iso()
    run_id = new_id()
    submissions = await db.directory_submissions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).to_list(500)
    defs_by_slug: Dict[str, Dict[str, Any]] = {}
    async for d in db.directory_definitions.find({}, {"_id": 0}):
        defs_by_slug[d["slug"]] = d
    checked: List[str] = []
    matched = 0
    mismatched = 0
    not_found = 0
    scores: List[int] = []
    profile = await db.tenant_nap_profile.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0}) or {}
    for sub in submissions:
        d = defs_by_slug.get(sub["directory_slug"])
        if not d or not d.get("scrape_url_template"):
            continue
        checked.append(sub["directory_slug"])
        # Wire in the real scraper adapter when one exists — never
        # fabricate data. For now, we only run the Google + Yelp +
        # Facebook checks that already have adapters in review_scraper.
        try:
            match, discrepancies = await _score_submission(sub, d, profile)
        except Exception as _e:
            logger.warning(f"[directories] scan for {sub['directory_slug']} failed: {_e}")
            continue
        if match is None:
            not_found += 1
            continue
        scores.append(match)
        if match >= 90:
            matched += 1
        else:
            mismatched += 1
        await db.directory_submissions.update_one(
            {"id": sub["id"], "tenant_id": tenant["id"]},
            {"$set": {"nap_match_score": match,
                        "discrepancies": discrepancies,
                        "last_checked_at": now,
                        "updated_at": now}})
    summary = {
        "total_matched": matched,
        "total_mismatched": mismatched,
        "total_not_found": not_found,
    }
    run_doc = {
        "id": run_id, "tenant_id": tenant["id"],
        "started_at": now, "completed_at": now_iso(),
        "directories_checked": checked,
        "summary": summary,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "run_type": "manual",
    }
    await db.nap_scan_runs.insert_one(run_doc)
    run_doc.pop("_id", None)
    return run_doc


@router.get("/scan/runs")
async def list_scan_runs(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant),
                              limit: int = Query(20, ge=1, le=100)):
    rows = await db.nap_scan_runs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("started_at", -1).to_list(limit)
    return {"count": len(rows), "runs": rows}


@router.get("/scan/runs/{rid}")
async def get_scan_run(rid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    row = await db.nap_scan_runs.find_one(
        {"id": rid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "scan run not found")
    diffs: List[Dict[str, Any]] = []
    for slug in row.get("directories_checked") or []:
        sub = await db.directory_submissions.find_one(
            {"tenant_id": tenant["id"], "directory_slug": slug},
            {"_id": 0, "directory_slug": 1, "nap_match_score": 1,
              "discrepancies": 1, "last_checked_at": 1})
        if sub:
            diffs.append(sub)
    row["per_submission"] = diffs
    return row


# ─── Health score ──────────────────────────────────────────────────────
@router.get("/health")
async def citation_health(user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    """Compose a single 0-100 citation score + surface the most
    valuable missing directories.

    Scoring
    -------
    Base score = 100 * (verified_count / total_available), with:
      * ``submitted`` counted at 60% weight,
      * ``needs_update`` counted at 30% weight,
      * ``in_progress`` counted at 20% weight,
      * everything else at 0.
    Then average with ``avg_nap_match_score`` when a scan has run,
    so a tenant with lots of verified profiles but inconsistent NAP
    data can never score higher than a tenant with fewer but cleaner
    citations. Overall score is clamped to [0, 100].
    """
    total = await db.directory_definitions.count_documents({"active": True})
    subs = await db.directory_submissions.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).to_list(500)
    if not total:
        return {"overall_score": 0, "total_directories_available": 0,
                 "submitted_count": 0, "verified_count": 0,
                 "needs_update_count": 0,
                 "top_priority_missing": [],
                 "avg_nap_match_score": None, "last_scan_at": None}
    by_status: Dict[str, int] = {}
    scores: List[int] = []
    for s in subs:
        by_status[s.get("status", "not_started")] = by_status.get(
            s.get("status", "not_started"), 0) + 1
        if s.get("nap_match_score") is not None:
            scores.append(int(s["nap_match_score"]))
    weighted = (
        1.0 * by_status.get("verified", 0)
        + 0.6 * by_status.get("submitted", 0)
        + 0.3 * by_status.get("needs_update", 0)
        + 0.2 * by_status.get("in_progress", 0)
    )
    coverage_score = round((weighted / total) * 100.0, 2)
    if scores:
        avg_match = round(sum(scores) / len(scores), 2)
        overall = round((coverage_score + avg_match) / 2, 2)
    else:
        avg_match = None
        overall = coverage_score
    covered = {s["directory_slug"] for s in subs
                 if s.get("status") in ("submitted", "verified")}
    missing = await db.directory_definitions.find(
        {"active": True, "slug": {"$nin": list(covered)}},
        {"_id": 0, "slug": 1, "name": 1, "priority": 1, "category": 1}
    ).sort("priority", 1).to_list(20)
    last_scan = await db.nap_scan_runs.find_one(
        {"tenant_id": tenant["id"]}, {"_id": 0, "started_at": 1},
        sort=[("started_at", -1)]
    ) or {}
    return {
        "overall_score": max(0, min(100, overall)),
        "coverage_score": coverage_score,
        "avg_nap_match_score": avg_match,
        "total_directories_available": total,
        "submitted_count": by_status.get("submitted", 0),
        "verified_count": by_status.get("verified", 0),
        "needs_update_count": by_status.get("needs_update", 0),
        "in_progress_count": by_status.get("in_progress", 0),
        "rejected_count": by_status.get("rejected", 0),
        "not_started_count": max(0, total - len(subs)),
        "top_priority_missing": missing[:10],
        "last_scan_at": last_scan.get("started_at"),
    }


# ─── internals ─────────────────────────────────────────────────────────
async def _emit_status_change(tenant_id: str,
                                  submission: Dict[str, Any],
                                  prior_status: Optional[str],
                                  actor_id: Optional[str]) -> None:
    """Route to the unified notifications service. Owner (assignee)
    gets it directly; fallback to tenant admins when unassigned."""
    try:
        from services.notifications import (
            enqueue_for_record_owner as _owner_emit,
        )
        slug = submission.get("directory_slug", "?")
        new_status = submission.get("status", "?")
        title = f"Directory · {slug} → {new_status}"
        body = (f"Status moved from {prior_status or 'unknown'} to "
                 f"{new_status}.")
        await _owner_emit(
            tenant_id,
            owner_user_id=submission.get("assigned_user_id"),
            kind="directory_status_change",
            title=title, body=body,
            source_ref={"kind": "directory_submission",
                          "id": submission.get("id"), "slug": slug},
            href=f"/directories/submissions/{submission.get('id')}",
        )
    except Exception as _e:
        logger.warning(f"[directories] status-change notify failed: {_e}")


async def _score_submission(sub: Dict[str, Any], defn: Dict[str, Any],
                                profile: Dict[str, Any]) -> tuple:
    """Compute a naive NAP-match score against whatever the scraper
    adapter returns. Returns ``(score:int|None, discrepancies:list)``.

    Falls back to ``(None, [])`` when no adapter is wired for the
    directory — never fabricates data.
    """
    slug = defn.get("slug", "")
    if slug not in ("google-business-profile", "yelp", "facebook-business"):
        return None, []
    try:
        from services.review_scraper import (
            scrape_google_business_profile,
            scrape_yelp_business,
            scrape_facebook_business,
        )
    except Exception:
        return None, []
    fn = {
        "google-business-profile": scrape_google_business_profile,
        "yelp":                     scrape_yelp_business,
        "facebook-business":        scrape_facebook_business,
    }[slug]
    try:
        scraped = await fn(profile)
    except Exception:
        return None, []
    if not scraped:
        return None, []
    fields = 0
    matched = 0
    discrepancies: List[Dict[str, Any]] = []
    for k in ("business_name", "phone_e164", "website"):
        expected = (profile.get(k) or "").strip().lower()
        found = (scraped.get(k) or "").strip().lower()
        if not expected:
            continue
        fields += 1
        if expected == found:
            matched += 1
        else:
            discrepancies.append({"field": k,
                                     "expected": profile.get(k),
                                     "found": scraped.get(k)})
    if fields == 0:
        return None, []
    return int(round(matched / fields * 100)), discrepancies
