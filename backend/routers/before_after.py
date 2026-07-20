"""QuoteIQ Phase Q3-A · Before/After AI Generator.

Deterministic path: fetch the two source photos, composite them with
Pillow (side_by_side / stacked / slider-preview), overlay a branded
footer strip (tenant name + service_type + city), upload the resulting
PNG to Emergent Object Storage, and return the public URL. This is the
primary path — reliable, testable, works even if no image-gen model is
wired up.

If a nano-banana / Gemini image-gen adapter shows up later, drop it in
behind ``_ai_enhance()`` and it'll be picked up automatically.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import hashlib
import io
import os
import secrets
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, require_admin, new_id, now_iso
from routers.tenants import get_current_tenant
from services.ai_credits import debit_credits


router = APIRouter(tags=["Before/After"])
STYLES = {"side_by_side", "stacked", "slider"}
# Credit cost per generation / regeneration. Constant here so the number
# is trivial to tune without touching request handlers.
CARD_COST = 5


def _mint_share_token() -> str:
    """Opaque URL-safe token for the public share link. 24 bytes →
    32 char base64url. No tenant/pair leak — the token is the only key."""
    return secrets.token_urlsafe(24)


class GenerateIn(BaseModel):
    before_photo_url: str = Field(..., min_length=8)
    after_photo_url: str = Field(..., min_length=8)
    job_id: Optional[str] = None
    customer_id: Optional[str] = None
    style: str = "side_by_side"
    caption: Optional[str] = None
    service_type: Optional[str] = None
    include_branding: bool = True


class RegenerateIn(BaseModel):
    style: Optional[str] = None
    caption: Optional[str] = None
    include_branding: Optional[bool] = None


def _fetch_image_bytes(url: str) -> bytes:
    """Fetch an image URL — tolerates local dev preview URLs and inline
    ``data:image/...;base64,...`` URIs (used by tests + client-side
    paste-uploads)."""
    if url.startswith("data:"):
        try:
            header, b64 = url.split(",", 1)
        except ValueError as exc:
            raise ValueError("malformed data URI") from exc
        try:
            return base64.b64decode(b64, validate=False)
        except binascii.Error as exc:
            raise ValueError(f"bad base64 in data URI: {exc}") from exc
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.content


def _load_pil(data: bytes):
    from PIL import Image
    return Image.open(io.BytesIO(data)).convert("RGB")


def _compose_card(before: bytes, after: bytes, *,
                    style: str, caption: str, brand_line: str,
                    include_branding: bool) -> bytes:
    """Return PNG bytes for the composited card.

    ``style`` in {side_by_side, stacked, slider}. Slider is rendered as
    a static preview (before | vertical divider | after with a small
    handle glyph) — good enough for share cards; the actual interactive
    slider lives client-side."""
    from PIL import Image, ImageDraw, ImageFont
    bimg = _load_pil(before)
    aimg = _load_pil(after)
    # Normalize both to the same short-side aspect so composites don't wobble.
    target_h = 720
    def _resize_to_h(im, h):
        ratio = h / im.height
        return im.resize((int(im.width * ratio), h))
    bimg = _resize_to_h(bimg, target_h)
    aimg = _resize_to_h(aimg, target_h)
    footer_h = 90 if include_branding else 0
    if style == "stacked":
        canvas_w = max(bimg.width, aimg.width)
        canvas_h = target_h * 2 + footer_h
        canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        canvas.paste(bimg, ((canvas_w - bimg.width) // 2, 0))
        canvas.paste(aimg, ((canvas_w - aimg.width) // 2, target_h))
    else:
        canvas_w = bimg.width + aimg.width
        canvas_h = target_h + footer_h
        canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        canvas.paste(bimg, (0, 0))
        canvas.paste(aimg, (bimg.width, 0))
        draw = ImageDraw.Draw(canvas)
        if style == "slider":
            x = bimg.width
            draw.line([(x, 0), (x, target_h)], fill=(255, 255, 255), width=6)
            draw.ellipse([(x - 22, target_h // 2 - 22),
                            (x + 22, target_h // 2 + 22)],
                          outline=(255, 255, 255), width=4, fill=(14, 165, 233))
    # BEFORE / AFTER text badges (top-left / top-right).
    draw = ImageDraw.Draw(canvas)
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    def _badge(x, y, text, color):
        pad = 12
        w = draw.textlength(text, font=font_lg)
        draw.rectangle([(x, y), (x + w + pad * 2, y + 44)], fill=color)
        draw.text((x + pad, y + 4), text, font=font_lg, fill=(255, 255, 255))

    _badge(24, 24, "BEFORE", (17, 24, 39))
    right_start = bimg.width + 24 if style != "stacked" else 24
    _badge(right_start,
             24 if style != "stacked" else target_h + 24,
             "AFTER", (5, 150, 105))

    if include_branding:
        y0 = target_h * (2 if style == "stacked" else 1)
        draw.rectangle([(0, y0), (canvas_w, y0 + footer_h)], fill=(15, 23, 42))
        draw.text((24, y0 + 14), brand_line, font=font_lg, fill=(255, 255, 255))
        if caption:
            draw.text((24, y0 + 52), caption[:120], font=font_sm, fill=(226, 232, 240))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def _upload_card(tenant_id: str, pair_id: str, png_bytes: bytes) -> str:
    """Persist card PNG. Prefers Emergent Object Storage; falls back to
    the media-serving path for local dev."""
    from services import object_storage as os_
    if os_.is_ready():
        path = os_.build_path(tenant_id, "before_after", pair_id,
                                f"{pair_id}.png")
        r = os_.put_object(path, png_bytes, "image/png")
        return r.get("url") or r.get("public_url") or path
    # Local fallback — write into /app/backend/uploads/before_after/.
    local_dir = "/app/backend/uploads/before_after"
    os.makedirs(local_dir, exist_ok=True)
    fp = f"{local_dir}/{pair_id}.png"
    with open(fp, "wb") as f:
        f.write(png_bytes)
    return f"/api/media/before-after/{pair_id}.png"


@router.get("/media/before-after/{filename}")
async def serve_local_card(filename: str):
    """Local dev serving. Returns 404 in production where Object
    Storage handles it."""
    from fastapi.responses import FileResponse
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "bad filename")
    fp = f"/app/backend/uploads/before_after/{filename}"
    if not os.path.exists(fp):
        raise HTTPException(404, "not found")
    return FileResponse(fp, media_type="image/png")


async def _do_compose(*, tenant: Dict[str, Any], pair_id: str,
                        body_style: str, before_url: str,
                        after_url: str, caption: str,
                        service_type: str,
                        include_branding: bool) -> Dict[str, Any]:
    if body_style not in STYLES:
        raise HTTPException(422, f"style must be one of {sorted(STYLES)}")
    try:
        b_bytes = _fetch_image_bytes(before_url)
        a_bytes = _fetch_image_bytes(after_url)
    except Exception as e:
        return {"status": "error", "error": f"fetch_failed: {e}"}
    tenant_name = tenant.get("name") or ""
    city = (tenant.get("hq_city") or tenant.get("address_city") or "").strip()
    brand_parts = [tenant_name]
    if service_type:
        brand_parts.append(service_type)
    if city:
        brand_parts.append(city)
    brand_line = " · ".join([p for p in brand_parts if p]) or "Service Result"
    try:
        png = _compose_card(b_bytes, a_bytes,
                             style=body_style, caption=caption or "",
                             brand_line=brand_line,
                             include_branding=include_branding)
    except Exception as e:
        logger.warning(f"[before_after] compose failed: {e}")
        return {"status": "error", "error": f"compose_failed: {e}"}
    try:
        url = await _upload_card(tenant["id"], pair_id, png)
    except Exception as e:
        return {"status": "error", "error": f"upload_failed: {e}"}
    return {"status": "complete", "url": url, "brand_line": brand_line}


@router.post("/before-after/generate", status_code=201)
async def generate(body: GenerateIn,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    pair_id = new_id()
    share_token = _mint_share_token()
    debit = await debit_credits(
        tenant["id"], CARD_COST, feature="before_after",
        ref_id=pair_id, ref_type="before_after_pair",
        reason="before_after_generate", actor_user_id=user.get("id"),
    )
    result = await _do_compose(
        tenant=tenant, pair_id=pair_id,
        body_style=body.style,
        before_url=body.before_photo_url,
        after_url=body.after_photo_url,
        caption=body.caption or "",
        service_type=body.service_type or "",
        include_branding=body.include_branding,
    )
    doc = {
        "id": pair_id, "tenant_id": tenant["id"],
        "share_token": share_token,
        "job_id": body.job_id, "customer_id": body.customer_id,
        "before_photo_url": body.before_photo_url,
        "after_photo_url": body.after_photo_url,
        "style": body.style,
        "caption": body.caption or "",
        "service_type": body.service_type or "",
        "include_branding": body.include_branding,
        "generated_card_url": result.get("url"),
        "generated_variants": [
            {"style": body.style, "url": result.get("url")}
        ] if result.get("url") else [],
        "tags": [], "credits_debited": CARD_COST,
        "generated_by": user.get("id"),
        "credit_warning": bool(debit.get("warning")),
        "status": result.get("status"),
        "error": result.get("error"),
        "model": "pillow-composite-v1",
        "created_at": now_iso(),
    }
    await db.before_after_pairs.insert_one(doc)
    doc.pop("_id", None)
    return {"pair": doc, "credits_balance_after": debit.get("balance_after")}


@router.get("/before-after/pairs")
async def list_pairs(user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant),
                       job_id: Optional[str] = Query(None),
                       customer_id: Optional[str] = Query(None),
                       limit: int = Query(50, ge=1, le=200),
                       cursor: Optional[str] = Query(None)):
    # RBAC: admins can list all. Techs need a scope filter (job_id or
    # customer_id) — they can see pairs on jobs/customers they operate
    # against but no unfiltered dumps. Everyone else 403.
    role = (user or {}).get("role")
    if role not in ("admin", "super_admin"):
        if role != "technician":
            raise HTTPException(403, "Access denied")
        if not (job_id or customer_id):
            raise HTTPException(
                403,
                "Technicians must filter by job_id or customer_id",
            )
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if job_id:
        q["job_id"] = job_id
    if customer_id:
        q["customer_id"] = customer_id
    if cursor:
        q["created_at"] = {"$lt": cursor}
    rows = await db.before_after_pairs.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    return {"count": len(rows), "pairs": rows,
            "next_cursor": rows[-1]["created_at"] if len(rows) == limit else None}


@router.get("/before-after/pairs/{pid}")
async def get_pair(pid: str,
                     user: dict = Depends(require_admin),
                     tenant: dict = Depends(get_current_tenant)):
    row = await db.before_after_pairs.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "pair not found")
    return row


@router.get("/before-after/pairs/{pid}/stats")
async def pair_stats(pid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    """Return counter surface for a single pair. CTR = clicks / impressions
    (0 when impressions=0). Kept as its own endpoint so admin dashboards
    can cheap-poll without pulling the full pair doc."""
    row = await db.before_after_pairs.find_one(
        {"id": pid, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "impressions_count": 1, "click_count": 1,
          "last_impression_at": 1, "last_click_at": 1})
    if row is None:
        raise HTTPException(404, "pair not found")
    imp = int(row.get("impressions_count") or 0)
    clk = int(row.get("click_count") or 0)
    ctr = round((clk / imp) * 100, 2) if imp > 0 else 0.0
    return {
        "impressions_count": imp,
        "click_count": clk,
        "ctr_pct": ctr,
        "last_impression_at": row.get("last_impression_at"),
        "last_click_at": row.get("last_click_at"),
    }


@router.delete("/before-after/pairs/{pid}", status_code=204)
async def delete_pair(pid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    r = await db.before_after_pairs.delete_one(
        {"id": pid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "pair not found")
    return None


@router.post("/before-after/pairs/{pid}/regenerate")
async def regenerate(pid: str, body: RegenerateIn,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    row = await db.before_after_pairs.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "pair not found")
    style = body.style or row.get("style") or "side_by_side"
    caption = body.caption if body.caption is not None else row.get("caption") or ""
    include_branding = row.get("include_branding") if body.include_branding is None else body.include_branding
    debit = await debit_credits(
        tenant["id"], CARD_COST, feature="before_after",
        ref_id=pid, ref_type="before_after_pair",
        reason="before_after_regenerate", actor_user_id=user.get("id"),
    )
    result = await _do_compose(
        tenant=tenant, pair_id=pid, body_style=style,
        before_url=row["before_photo_url"],
        after_url=row["after_photo_url"],
        caption=caption or "",
        service_type=row.get("service_type") or "",
        include_branding=bool(include_branding),
    )
    variants = row.get("generated_variants") or []
    if result.get("url"):
        variants.append({"style": style, "url": result["url"]})
    upd = {
        "style": style, "caption": caption,
        "include_branding": bool(include_branding),
        "generated_card_url": result.get("url") or row.get("generated_card_url"),
        "generated_variants": variants,
        "status": result.get("status"), "error": result.get("error"),
        "credits_debited": int(row.get("credits_debited") or 0) + CARD_COST,
        "updated_at": now_iso(),
    }
    await db.before_after_pairs.update_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"$set": upd})
    fresh = await db.before_after_pairs.find_one(
        {"id": pid, "tenant_id": tenant["id"]}, {"_id": 0})
    return {"pair": fresh, "credits_balance_after": debit.get("balance_after")}


@router.get("/before-after/public/{share_token}")
async def public_share(share_token: str):
    """Unauthenticated public share endpoint. Keyed by opaque token —
    no tenant/customer/job details ever leak. Returns ONLY the card
    URL and non-sensitive metadata.

    On each fetch we atomically ``$inc: impressions_count`` and refresh
    ``last_impression_at`` — no PII, no IP, no user-agent stored. The
    impression counter powers the admin gallery + stats endpoint.
    """
    if not share_token or len(share_token) < 16:
        raise HTTPException(404, "not found")
    row = await db.before_after_pairs.find_one(
        {"share_token": share_token}, {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")
    if row.get("status") != "complete":
        raise HTTPException(404, "not ready")
    # Atomic impression counter — bump on every serve. Never blocks the
    # response on failure.
    try:
        await db.before_after_pairs.update_one(
            {"share_token": share_token},
            {"$inc": {"impressions_count": 1},
              "$set": {"last_impression_at": now_iso()}})
    except Exception as _e:
        logger.warning(f"[before_after] impression inc failed: {_e}")
    return {
        "card_url": row.get("generated_card_url"),
        "style": row.get("style"),
        "caption": row.get("caption") or "",
        "service_type": row.get("service_type") or "",
        "created_at": row.get("created_at"),
    }


@router.post("/before-after/public/{share_token}/click")
async def public_share_click(share_token: str):
    """Client-side beacon fired when a viewer opens the share link (or
    clicks the CTA within it). Silent 200 on unknown tokens so scanners
    can't enumerate valid tokens by watching the response codes.

    Route lives under ``/before-after/public/*`` so it can be dropped
    on the same public prefix as the fetch endpoint above — no auth.
    """
    if not share_token or len(share_token) < 16:
        return {"ok": True}
    try:
        await db.before_after_pairs.update_one(
            {"share_token": share_token},
            {"$inc": {"click_count": 1},
              "$set": {"last_click_at": now_iso()}})
    except Exception as _e:
        logger.warning(f"[before_after] click inc failed: {_e}")
    return {"ok": True}
