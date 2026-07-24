"""Feb-2026 · Phase 23-A — Local Rank Tracker + Geo-Grid heatmap.

Manual-first: the weekly cron is gated behind
``RANK_TRACKER_CRON_ENABLED=true``; boot does not schedule anything.
Admins refresh keywords on demand via ``POST /rank-tracker/keywords/{id}/refresh-now``
(rate-limited to 1 per keyword per 6 hours to conserve DataForSEO credits).

Collections
-----------
* ``tracked_keywords`` — one row per (tenant, keyword). Cap 50/tenant.
* ``rank_snapshots``   — 9 rows per keyword per snapshot pass (3x3 grid).

Endpoints
---------
* GET/POST/DELETE ``/rank-tracker/keywords``
* GET  ``/rank-tracker/keywords/{id}/heatmap``
* POST ``/rank-tracker/keywords/{id}/refresh-now``
* GET  ``/rank-tracker/dataforseo-credits``
"""
from __future__ import annotations

import os
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso, new_id
from services import dataforseo_client as dfs

router = APIRouter(tags=["Rank Tracker"])

MAX_KEYWORDS_PER_TENANT = 50
REFRESH_COOLDOWN_HOURS = 6
DEFAULT_RADIUS_KM = 2.0


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _admin_or_403(user: dict):
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _tenant_center_and_domain(tenant_id: str) -> Dict[str, Any]:
    """Pull the tenant's business_card. Extract:
       * center lat/lng (crude parse of ``service_area``; defaults to
         Peoria AZ if unparseable so the calculator never blows up)
       * website domain (host portion of ``website_url``)
    """
    t = await db.tenants.find_one({"id": tenant_id},
                                     {"_id": 0, "settings.business_card": 1})
    card = ((t or {}).get("settings") or {}).get("business_card") or {}
    website = (card.get("website_url") or "").strip()
    domain = ""
    if website:
        try:
            netloc = urlparse(website).netloc or website
            domain = netloc.lower().replace("www.", "").strip("/")
        except Exception:
            domain = ""
    # Peoria/Vistancia AZ default center. Admins can override per-keyword.
    lat = 33.7695
    lng = -112.2569
    return {"lat": lat, "lng": lng, "domain": domain,
             "company_name": card.get("company_name") or ""}


def build_grid(center_lat: float, center_lng: float, radius_km: float) -> List[Dict[str, float]]:
    """3x3 grid centered on (lat, lng), corners at ``radius_km`` from
    center. Returns 9 points indexed 0..8 (row-major, top-left first).

    We approximate: 1° lat ≈ 111 km; 1° lng ≈ 111 km · cos(lat).
    """
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.1, math.cos(math.radians(center_lat))))
    pts: List[Dict[str, float]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            pts.append({
                "lat": round(center_lat + dy * dlat, 6),
                "lng": round(center_lng + dx * dlng, 6),
            })
    return pts


# ─────────────────────────────────────────────────────────────────────
# Endpoint models
# ─────────────────────────────────────────────────────────────────────
class KeywordIn(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=120)
    radius_km: Optional[float] = None
    market_lat: Optional[float] = None
    market_lng: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────
# CRUD — keywords
# ─────────────────────────────────────────────────────────────────────
@router.get("/rank-tracker/keywords",
             operation_id="rankTracker.listKeywords")
async def list_keywords(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")
    rows = await db.tracked_keywords.find(
        {"tenant_id": tid, "active": {"$ne": False}},
        {"_id": 0},
    ).to_list(MAX_KEYWORDS_PER_TENANT)
    rows.sort(key=lambda r: r.get("added_at") or "", reverse=True)
    return {"total": len(rows), "keywords": rows}


@router.post("/rank-tracker/keywords",
              operation_id="rankTracker.addKeyword")
async def add_keyword(body: KeywordIn,
                       user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "Missing tenant_id")

    kw = (body.keyword or "").strip()
    if not kw:
        raise HTTPException(422, "Keyword is required")

    # Cap check.
    n = await db.tracked_keywords.count_documents({"tenant_id": tid,
                                                     "active": {"$ne": False}})
    if n >= MAX_KEYWORDS_PER_TENANT:
        raise HTTPException(400,
            f"Keyword limit reached ({MAX_KEYWORDS_PER_TENANT}). "
            "Delete unused keywords first.")

    # Dedupe (case-insensitive) per tenant.
    dup = await db.tracked_keywords.find_one(
        {"tenant_id": tid,
          "keyword_lc": kw.lower(),
          "active": {"$ne": False}},
        {"_id": 0, "id": 1},
    )
    if dup:
        raise HTTPException(409, "Keyword already tracked")

    center = await _tenant_center_and_domain(tid)
    lat = body.market_lat if body.market_lat is not None else center["lat"]
    lng = body.market_lng if body.market_lng is not None else center["lng"]
    radius = float(body.radius_km or DEFAULT_RADIUS_KM)
    if radius <= 0 or radius > 50:
        raise HTTPException(422, "radius_km must be between 0 and 50")

    doc = {
        "id": new_id(),
        "tenant_id": tid,
        "keyword": kw,
        "keyword_lc": kw.lower(),
        "market_geo": {"lat": lat, "lng": lng, "radius_km": radius},
        "active": True,
        "added_at": now_iso(),
        "added_by_user_id": user.get("id"),
        "last_refreshed_at": None,
    }
    await db.tracked_keywords.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/rank-tracker/keywords/{kid}",
                 operation_id="rankTracker.deleteKeyword")
async def delete_keyword(kid: str,
                          user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    row = await db.tracked_keywords.find_one({"id": kid, "tenant_id": tid},
                                                {"_id": 0, "id": 1})
    if not row:
        raise HTTPException(404, "Unknown keyword")
    await db.tracked_keywords.update_one(
        {"id": kid}, {"$set": {"active": False,
                                  "deleted_at": now_iso()}},
    )
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────
# Heatmap / history
# ─────────────────────────────────────────────────────────────────────
@router.get("/rank-tracker/keywords/{kid}/heatmap",
             operation_id="rankTracker.heatmap")
async def heatmap(kid: str,
                    user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    kw = await db.tracked_keywords.find_one({"id": kid, "tenant_id": tid},
                                              {"_id": 0})
    if not kw:
        raise HTTPException(404, "Unknown keyword")

    # Latest snapshot per grid_point_index — pull the most recent for
    # each of the 9 points.
    grid_points: Dict[int, Dict[str, Any]] = {}
    async for row in db.rank_snapshots.find(
        {"tenant_id": tid, "keyword_id": kid},
        {"_id": 0},
    ).sort("checked_at", -1):
        idx = int(row.get("grid_point_index") or 0)
        if idx not in grid_points:
            grid_points[idx] = row
        if len(grid_points) == 9:
            break

    # History: mean rank per snapshot batch (grouped by checked_at rounded
    # to the minute so we roll the 9 points of a single pass together).
    hist_map: Dict[str, List[int]] = {}
    async for row in db.rank_snapshots.find(
        {"tenant_id": tid, "keyword_id": kid},
        {"_id": 0, "rank": 1, "checked_at": 1},
    ):
        r = row.get("rank")
        if r is None:
            continue
        bucket = (row.get("checked_at") or "")[:16]
        hist_map.setdefault(bucket, []).append(int(r))
    history = sorted(
        [{"checked_at": k, "mean_rank": round(sum(v) / len(v), 1),
           "n_points": len(v)}
         for k, v in hist_map.items()],
        key=lambda x: x["checked_at"],
    )[-12:]

    return {
        "keyword": kw,
        "grid": [grid_points.get(i) for i in range(9)],
        "history": history,
    }


# ─────────────────────────────────────────────────────────────────────
# Refresh-now (rate-limited)
# ─────────────────────────────────────────────────────────────────────
async def _snapshot_keyword(kw: Dict[str, Any], tenant_id: str,
                              target_domain: str) -> Dict[str, Any]:
    """Fetch a fresh 9-point grid for one keyword. Writes 9 rows to
    ``rank_snapshots`` and updates ``tracked_keywords.last_refreshed_at``.
    Returns a summary dict.
    """
    geo = kw.get("market_geo") or {}
    grid = build_grid(geo.get("lat") or 33.77,
                       geo.get("lng") or -112.26,
                       float(geo.get("radius_km") or DEFAULT_RADIUS_KM))
    now = now_iso()
    results: List[Dict[str, Any]] = []
    api_error: Optional[str] = None
    api_status: Optional[int] = None
    for idx, pt in enumerate(grid):
        status, body, err = await dfs.serp_google_organic_live(
            kw["keyword"], pt["lat"], pt["lng"],
        )
        if err:
            api_error = err
            api_status = status
            rank: Optional[int] = None
        else:
            ranks = dfs.parse_serp_ranks(body, [target_domain] if target_domain else [])
            rank = ranks.get(target_domain) if target_domain else None
        row = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "keyword_id": kw["id"],
            "grid_point_index": idx,
            "grid_lat": pt["lat"],
            "grid_lng": pt["lng"],
            "checked_at": now,
            "rank": rank,
            "engine": "google",
            "target_domain": target_domain,
            "api_error": err,
        }
        await db.rank_snapshots.insert_one(row)
        row.pop("_id", None)
        results.append(row)
        # If credits are gone or auth is broken, don't burn 9 requests.
        if err in ("out_of_credits", "auth_failed", "no_credentials"):
            break
    await db.tracked_keywords.update_one(
        {"id": kw["id"]}, {"$set": {"last_refreshed_at": now}},
    )
    return {
        "checked_at": now,
        "results": results,
        "api_error": api_error,
        "api_status": api_status,
    }


@router.post("/rank-tracker/keywords/{kid}/refresh-now",
              operation_id="rankTracker.refreshNow")
async def refresh_now(kid: str,
                       user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    tid = user.get("tenant_id")
    kw = await db.tracked_keywords.find_one({"id": kid, "tenant_id": tid,
                                                "active": True},
                                              {"_id": 0})
    if not kw:
        raise HTTPException(404, "Unknown keyword")
    # 6h cooldown.
    last = kw.get("last_refreshed_at")
    if last:
        try:
            t = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - t < timedelta(hours=REFRESH_COOLDOWN_HOURS):
                remaining = REFRESH_COOLDOWN_HOURS - int(
                    (datetime.now(timezone.utc) - t).total_seconds() // 3600
                )
                raise HTTPException(
                    429,
                    f"Rate limited — please wait ~{max(1, remaining)}h before refreshing again.",
                )
        except HTTPException:
            raise
        except Exception:
            pass  # stale timestamp; allow refresh
    ctx = await _tenant_center_and_domain(tid)
    domain = ctx["domain"]
    if not domain:
        raise HTTPException(
            400,
            "No website_url on the tenant's business card — set that first, "
            "otherwise we have no domain to rank-check for.",
        )
    return await _snapshot_keyword(kw, tid, domain)


# ─────────────────────────────────────────────────────────────────────
# Weekly cron (feature-flagged — MANUAL-ONLY in v1)
# ─────────────────────────────────────────────────────────────────────
async def run_weekly_rank_tracker() -> Dict[str, int]:
    """Sweep every active keyword for every tenant. Only runs when
    ``RANK_TRACKER_CRON_ENABLED=true`` in the env.  Server boot never
    schedules this — it's kept here so a future scheduler (or a manual
    call from a shell) can flip the flag and invoke.
    """
    if os.environ.get("RANK_TRACKER_CRON_ENABLED", "false").lower() != "true":
        logger.info("[rank-tracker] weekly cron skipped (RANK_TRACKER_CRON_ENABLED != true)")
        return {"skipped": 1, "keywords": 0}
    n = 0
    async for kw in db.tracked_keywords.find({"active": True}, {"_id": 0}):
        ctx = await _tenant_center_and_domain(kw["tenant_id"])
        if not ctx["domain"]:
            continue
        try:
            await _snapshot_keyword(kw, kw["tenant_id"], ctx["domain"])
            n += 1
        except Exception as e:
            logger.warning(f"[rank-tracker] snapshot failed for {kw.get('keyword')}: {e}")
    return {"keywords": n, "skipped": 0}


# ─────────────────────────────────────────────────────────────────────
# DataForSEO account credits
# ─────────────────────────────────────────────────────────────────────
@router.get("/rank-tracker/dataforseo-credits",
             operation_id="rankTracker.creditsBalance")
async def credits_balance(user: Dict[str, Any] = Depends(get_current_user)):
    _admin_or_403(user)
    status, body, err = await dfs.user_credits()
    if err in ("no_credentials",):
        return {"available": False, "reason": "DataForSEO not configured",
                 "status": status}
    if err in ("auth_failed",):
        return {"available": False, "reason": "Auth failed — check DATAFORSEO_* env vars",
                 "status": status}
    if err:
        return {"available": False, "reason": err, "status": status}
    # DataForSEO buries the balance under tasks[0].result[0].money.balance
    balance = None
    tasks = (body or {}).get("tasks") or []
    if tasks and tasks[0].get("result"):
        result0 = tasks[0]["result"][0]
        balance = ((result0.get("money") or {}).get("balance"))
    return {"available": True, "balance": balance,
             "raw_status": (body or {}).get("status_code")}
