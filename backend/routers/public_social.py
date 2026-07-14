"""Phase 18A.1 · Public short-link redirect.

Mounted at app root (no `/api` prefix). Anyone with the alias can follow it —
click stats are recorded server-side. No auth on this endpoint.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, PlainTextResponse

from config import db
from utils import new_id, now_iso

router = APIRouter()


@router.get("/r/{alias}")
async def follow_short_link(alias: str, request: Request):
    link = await db.short_links.find_one({"alias": alias}, {"_id": 0})
    if not link:
        return PlainTextResponse("Link not found", status_code=404)
    now = now_iso()
    hit = {
        "id": new_id(),
        "link_id": link["id"],
        "tenant_id": link.get("tenant_id"),
        "ts": now,
        "ts_dt": datetime.now(timezone.utc),
        "ip": (request.client.host if request.client else None),
        "ua": request.headers.get("user-agent"),
        "referrer": request.headers.get("referer"),
    }
    # Fire-and-forget: never block the redirect on stats persistence errors.
    try:
        await db.short_link_hits.insert_one(hit)
        await db.short_links.update_one({"id": link["id"]}, {"$inc": {"clicks_total": 1}})
    except Exception:
        pass
    return RedirectResponse(link["target_url"], status_code=302)
