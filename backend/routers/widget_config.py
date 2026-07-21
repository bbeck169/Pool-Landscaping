"""Feb-2026 · Slice GH0 — Public widget key + domain whitelist.

Precursor to Slice G (chat widget) and Slice H (form widget).  Every
public widget endpoint depends on :func:`require_widget_auth` — the
same helper both slices import.

Design notes
------------
* ``public_widget_key`` behaves like a Stripe publishable key — public
  knowledge, cannot mutate anything on its own, only *identifies* which
  tenant the widget belongs to.
* ``widget_allowed_domains`` defaults to ``[]`` so a leaked key does
  nothing until a super-admin explicitly whitelists domains.
* Domain match is exact host (no scheme, no port, no wildcards) for v1
  — matches the spec.  Origin header takes precedence over Referer.
"""
from __future__ import annotations

import re, secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, get_current_user
from routers.tenants import require_super_admin

router = APIRouter()

_KEY_PREFIX = "pk_"
_KEY_ENTROPY_BYTES = 24        # → base64 32-char string after prefix
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$",
)


def _new_widget_key() -> str:
    return _KEY_PREFIX + secrets.token_urlsafe(_KEY_ENTROPY_BYTES)


def _norm_domain(v: str) -> str:
    v = (v or "").strip().lower()
    if not v:
        raise HTTPException(422, "domain cannot be empty")
    # Strip scheme + trailing slashes if the user pasted a URL.
    if "://" in v:
        v = urlparse(v).netloc or v
    v = v.rstrip("/").split("/")[0]
    # Drop :port.
    if ":" in v:
        v = v.split(":")[0]
    if not _DOMAIN_RE.match(v):
        raise HTTPException(422, f"'{v}' is not a valid domain")
    return v


# ── Admin/super — read config ────────────────────────────────────────
@router.get("/tenants/mine/widget-config")
async def get_widget_config(user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    t = await db.tenants.find_one(
        {"id": tid},
        {"_id": 0, "public_widget_key": 1, "widget_allowed_domains": 1},
    ) or {}
    key = t.get("public_widget_key")
    if not key:
        # Lazy-generate on first read so the tenant always has one to
        # show in the settings card.
        key = _new_widget_key()
        await db.tenants.update_one(
            {"id": tid},
            {"$set": {"public_widget_key": key, "updated_at": now_iso()}},
        )
    return {
        "public_widget_key": key,
        "widget_allowed_domains": t.get("widget_allowed_domains") or [],
    }


# ── Super-admin — regenerate key ────────────────────────────────────
@router.post("/tenants/mine/widget-config/regenerate-key")
async def regenerate_widget_key(user: dict = Depends(require_super_admin)):
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    new_key = _new_widget_key()
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {"public_widget_key": new_key, "updated_at": now_iso()}},
    )
    logger.info("[gh0] widget key rotated for tenant=%s by=%s", tid, user["id"])
    return {"public_widget_key": new_key}


# ── Super-admin — replace allowed domains ───────────────────────────
class DomainsPatch(BaseModel):
    widget_allowed_domains: List[str] = Field(default_factory=list)


@router.patch("/tenants/mine/widget-config/domains")
async def patch_widget_domains(body: DomainsPatch,
                               user: dict = Depends(require_super_admin)):
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    # Normalize + dedupe (preserve order).
    seen = set()
    cleaned: List[str] = []
    for d in body.widget_allowed_domains:
        norm = _norm_domain(d)
        if norm not in seen:
            seen.add(norm)
            cleaned.append(norm)
    await db.tenants.update_one(
        {"id": tid},
        {"$set": {"widget_allowed_domains": cleaned,
                    "updated_at": now_iso()}},
    )
    return {"widget_allowed_domains": cleaned}


# ═══════════════════════════════════════════════════════════════════════
# Shared widget-auth dependency (imported by Slice G + H)
# ═══════════════════════════════════════════════════════════════════════
def _host_from_header(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    try:
        u = urlparse(v)
        return (u.netloc or v).split(":")[0].lower() or None
    except Exception:
        return None


async def require_widget_auth(
    request: Request,
    x_widget_key: Optional[str] = Header(None, alias="X-Widget-Key"),
) -> Dict[str, Any]:
    """Validates ``X-Widget-Key`` against the tenant's public key AND
    the incoming ``Origin``/``Referer`` host against
    ``widget_allowed_domains``.  Returns the tenant document (minus
    ``_id``) so downstream endpoints have full context."""
    if not x_widget_key:
        raise HTTPException(401, "Missing X-Widget-Key header")
    tenant = await db.tenants.find_one(
        {"public_widget_key": x_widget_key}, {"_id": 0},
    )
    if not tenant:
        raise HTTPException(401, "Invalid widget key")
    allowed = tenant.get("widget_allowed_domains") or []
    if not allowed:
        raise HTTPException(401, "Widget not enabled for any domain yet")
    origin = _host_from_header(request.headers.get("origin"))
    referer = _host_from_header(request.headers.get("referer"))
    host = origin or referer
    if not host:
        raise HTTPException(401, "Missing Origin or Referer header")
    if host not in allowed:
        raise HTTPException(401, f"Origin '{host}' is not on the widget allowlist")
    return tenant
