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

import os, re, secrets
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

# ── Dev-mode host trust pattern ──────────────────────────────────────
# Emergent's preview ingress rewrites the ``Origin`` header on cross-
# origin XHRs so the backend actually sees the internal cluster host
# (e.g. ``poolscape-audit.cluster-12.preview.emergentcf.cloud``) even
# when the browser was at ``…preview.emergentagent.com``. In non-prod
# environments we trust any host matching this pattern in addition to
# the tenant's ``widget_allowed_domains`` list — same guardrail as the
# GH-Fix dev-domain seed (gated on APP_ENV != "production" +
# WIDGET_DEV_DOMAIN_SEED != "0" so prod tenants NEVER get an implicit
# pass).
_DEV_CLUSTER_HOST_RE = re.compile(
    r".+\.cluster-\d+\.preview\.emergentcf\.cloud$"
)


def _dev_mode_enabled() -> bool:
    env = os.environ.get("APP_ENV", "preview").lower()
    toggle = os.environ.get("WIDGET_DEV_DOMAIN_SEED", "1").strip()
    if env == "production":
        return False
    if toggle in ("0", "false", "no", ""):
        return False
    return True


def _dev_seed_hosts() -> List[str]:
    """The canonical list of hosts the dev boot seed pins onto the
    aquaterra tenant. Includes ``WIDGET_DEV_DOMAIN`` override,
    ``APP_PUBLIC_URL`` host, ``INTERNAL_CLUSTER_HOST`` override, and
    the historical default preview host."""
    seen: set = set()
    out: List[str] = []

    def _add(v: Optional[str]) -> None:
        if not v:
            return
        v = v.strip().lower()
        # Peel scheme/port if the env value is a full URL.
        if "://" in v:
            try:
                v = urlparse(v).netloc or v
            except Exception:
                pass
        v = v.split(":")[0].strip("/") or ""
        if v and v not in seen:
            seen.add(v)
            out.append(v)

    _add(os.environ.get("WIDGET_DEV_DOMAIN"))
    _add(os.environ.get("APP_PUBLIC_URL"))
    _add(os.environ.get("INTERNAL_CLUSTER_HOST"))
    _add("poolscape-audit.preview.emergentagent.com")
    return out


async def seed_dev_widget_domains_for_aquaterra() -> Dict[str, Any]:
    """Idempotently union the dev seed hosts into aquaterra's
    ``widget_allowed_domains``. Gated on ``APP_ENV != "production"``
    + ``WIDGET_DEV_DOMAIN_SEED`` toggle. Returns a small summary the
    boot pipeline can log."""
    if not _dev_mode_enabled():
        return {"skipped": True,
                "reason": "APP_ENV=production or WIDGET_DEV_DOMAIN_SEED=0"}
    hosts = _dev_seed_hosts()
    aqua = await db.tenants.find_one(
        {"slug": "aquaterra"},
        {"_id": 0, "id": 1, "widget_allowed_domains": 1},
    )
    if not aqua:
        return {"skipped": True, "reason": "aquaterra tenant not found yet"}
    current = list(aqua.get("widget_allowed_domains") or [])
    to_add = [h for h in hosts if h and h not in current]
    if to_add:
        await db.tenants.update_one(
            {"id": aqua["id"]},
            {"$addToSet": {"widget_allowed_domains": {"$each": to_add}},
              "$set": {"updated_at": now_iso()}},
        )
        logger.info(
            "[gh0-seed] appended %d host(s) to aquaterra widget_allowed_domains: %s",
            len(to_add), to_add,
        )
    return {"skipped": False, "added": to_add, "already_present": [
        h for h in hosts if h in current
    ]}



# ═══════════════════════════════════════════════════════════════════════
# GH-Fix v3 · Slice G3 — denied-requests ring buffer (in-memory)
# ═══════════════════════════════════════════════════════════════════════
# Tenant-scoped rolling record of the last N rejections.  Slice L.c
# migrated this from an in-memory deque to a Mongo-backed row so the
# admin UI survives process restarts + horizontal scale.  Retention is
# enforced by:
#   1. A 7-day TTL index on ``created_at`` (see boot migration).
#   2. Per-tenant trim on every write, keeping only the newest
#      ``_DENIED_RING_MAX`` rows.

from collections import deque
from threading import Lock

_DENIED_RING_MAX = 500          # Slice L.c cap per tenant
_denied_lock = Lock()           # process-local trim guard


async def _ensure_denied_indexes() -> None:
    """Idempotently create the TTL + per-tenant read indexes.  Called
    from ``server.startup`` best-effort; failure is logged, not fatal."""
    try:
        await db.widget_denied_requests.create_index(
            "created_at", expireAfterSeconds=7 * 24 * 3600,
            name="widget_denied_ttl_7d",
        )
        await db.widget_denied_requests.create_index(
            [("tenant_id", 1), ("created_at", -1)],
            name="widget_denied_tenant_time",
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[l.c] widget_denied index create failed: %s", exc)


async def _record_denied_async(tenant_id: Optional[str], *,
                                 reason: str, path: str,
                                 origin_hdr: Optional[str],
                                 referer_hdr: Optional[str],
                                 x_forwarded_origin_hdr: Optional[str]) -> None:
    key = tenant_id or "__unknown__"
    row = {
        "id": secrets.token_urlsafe(8),
        "tenant_id": key,
        "reason": reason,
        "path": (path or "")[:120],
        "origin": (origin_hdr or "")[:200] or None,
        "referer": (referer_hdr or "")[:200] or None,
        "x_forwarded_origin": (x_forwarded_origin_hdr or "")[:200] or None,
        "created_at": now_iso(),
    }
    try:
        await db.widget_denied_requests.insert_one(row)
    except Exception as exc:  # pragma: no cover
        logger.warning("[l.c] widget_denied insert failed: %s", exc)
        return
    # Trim per-tenant rings to _DENIED_RING_MAX rows (opportunistic).
    try:
        cnt = await db.widget_denied_requests.count_documents({"tenant_id": key})
        if cnt > _DENIED_RING_MAX:
            excess = cnt - _DENIED_RING_MAX
            # Delete the oldest ``excess`` rows for this tenant.
            oldest = await db.widget_denied_requests.find(
                {"tenant_id": key}, {"_id": 0, "id": 1},
            ).sort("created_at", 1).limit(excess).to_list(excess)
            if oldest:
                await db.widget_denied_requests.delete_many(
                    {"id": {"$in": [r["id"] for r in oldest]}},
                )
    except Exception as exc:  # pragma: no cover
        logger.warning("[l.c] widget_denied trim failed: %s", exc)


def _record_denied(tenant_id: Optional[str], *,
                    reason: str, path: str,
                    origin_hdr: Optional[str],
                    referer_hdr: Optional[str],
                    x_forwarded_origin_hdr: Optional[str]) -> None:
    """Sync wrapper for legacy call sites (middleware).  Schedules the
    insert on the running loop when available, falls back to a no-op
    when called outside a loop context.

    Feb-2026 · Uses ``asyncio.get_running_loop()`` instead of the
    deprecated ``get_event_loop()`` — the former raises ``RuntimeError``
    cleanly when no loop is running (swallowed by the outer ``except``)
    and never emits Python 3.12 deprecation warnings.
    """
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        loop.create_task(_record_denied_async(
            tenant_id, reason=reason, path=path,
            origin_hdr=origin_hdr, referer_hdr=referer_hdr,
            x_forwarded_origin_hdr=x_forwarded_origin_hdr,
        ))
    except Exception:  # pragma: no cover — best-effort middleware
        pass


async def get_denied_ring(tenant_id: str) -> List[Dict[str, Any]]:
    """Async read for the admin UI.  Returns the newest ``_DENIED_RING_MAX``
    rows for the tenant."""
    try:
        rows = await db.widget_denied_requests.find(
            {"tenant_id": tenant_id}, {"_id": 0},
        ).sort("created_at", -1).limit(_DENIED_RING_MAX).to_list(_DENIED_RING_MAX)
        # Preserve the legacy ``at`` field consumed by the admin UI.
        for r in rows:
            r["at"] = r.get("created_at")
        return rows
    except Exception as exc:  # pragma: no cover
        logger.warning("[l.c] widget_denied read failed: %s", exc)
        return []



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
# Post-GH0 fix (Feb-2026): accept BOTH ``domains`` and
# ``widget_allowed_domains`` as aliases so the widget UI, the admin
# API SDK, and the tester spec can all speak the same endpoint.  Neither
# key present ⇒ 422 with a helpful message.
@router.patch("/tenants/mine/widget-config/domains")
async def patch_widget_domains(request: Request,
                               user: dict = Depends(require_super_admin)):
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")

    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(422, "Request body must be a JSON object")

    # Accept either alias; ``widget_allowed_domains`` wins when both are
    # present (matches the getter's response shape).
    raw = body.get("widget_allowed_domains")
    if raw is None:
        raw = body.get("domains")
    if raw is None:
        raise HTTPException(
            422, "Missing 'domains' (or 'widget_allowed_domains') in body"
        )
    if not isinstance(raw, list):
        raise HTTPException(
            422, "'domains'/'widget_allowed_domains' must be a list of strings"
        )

    # Normalize + dedupe (preserve order).
    seen = set()
    cleaned: List[str] = []
    for d in raw:
        if not isinstance(d, str):
            raise HTTPException(422, "each domain must be a string")
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
    at least ONE client-facing host header against the allowlist.

    Header candidates evaluated (in order):
      1. ``Origin``
      2. ``X-Forwarded-Origin`` — set by some ingresses that also
         rewrite ``Origin``.
      3. ``Referer`` — final fallback. Browsers set this on cross-
         origin XHRs and it survives most ingress rewrites intact,
         so an ingress that rewrites ``Origin`` to an internal host
         still lets us verify the REAL calling page.

    GH-Fix v3 (security hardening): we now require at least ONE
    candidate to POSITIVELY match ``widget_allowed_domains``. There is
    NO regex-based passthrough for cluster-shaped hostnames — that
    was a security hole because Emergent's Cloudflare/GCLB ingress
    can rewrite ``Origin`` to the internal cluster host, which would
    let a foreign attacker's request masquerade as a legitimate
    ingress-rewritten request.

    Instead, legitimate ingress-rewrite calls still pass because:
      * The browser's ``Referer`` header is preserved by the ingress,
        so ``Referer`` will match the tenant's allowlisted public URL.
      * If the tenant's cluster host is known (``INTERNAL_CLUSTER_HOST``
        env in non-prod), it's seeded into the allowlist directly so
        ``Origin`` matches literally.

    Empty allowlist == deny-by-default. No matching candidate → 401.
    """
    def _req_path() -> str:
        try:
            return str(request.url.path)
        except Exception:
            return "?"

    if not x_widget_key:
        _record_denied(None, reason="missing_key",
                        path=_req_path(),
                        origin_hdr=request.headers.get("origin"),
                        referer_hdr=request.headers.get("referer"),
                        x_forwarded_origin_hdr=request.headers.get("x-forwarded-origin"))
        raise HTTPException(401, "Missing X-Widget-Key header")
    tenant = await db.tenants.find_one(
        {"public_widget_key": x_widget_key}, {"_id": 0},
    )
    if not tenant:
        _record_denied(None, reason="invalid_key",
                        path=_req_path(),
                        origin_hdr=request.headers.get("origin"),
                        referer_hdr=request.headers.get("referer"),
                        x_forwarded_origin_hdr=request.headers.get("x-forwarded-origin"))
        raise HTTPException(401, "Invalid widget key")
    allowed = list(tenant.get("widget_allowed_domains") or [])
    if not allowed:
        _record_denied(tenant.get("id"), reason="empty_allowlist",
                        path=_req_path(),
                        origin_hdr=request.headers.get("origin"),
                        referer_hdr=request.headers.get("referer"),
                        x_forwarded_origin_hdr=request.headers.get("x-forwarded-origin"))
        raise HTTPException(401, "Widget not enabled for any domain yet")

    candidates: List[str] = []
    for raw in (
        request.headers.get("origin"),
        request.headers.get("x-forwarded-origin"),
        request.headers.get("referer"),
    ):
        v = _host_from_header(raw)
        if v and v not in candidates:
            candidates.append(v)
    if not candidates:
        _record_denied(tenant.get("id"), reason="no_origin",
                        path=_req_path(),
                        origin_hdr=request.headers.get("origin"),
                        referer_hdr=request.headers.get("referer"),
                        x_forwarded_origin_hdr=request.headers.get("x-forwarded-origin"))
        raise HTTPException(401, "Missing Origin or Referer header")

    for host in candidates:
        if host in allowed:
            return tenant

    _record_denied(tenant.get("id"), reason="foreign_origin",
                    path=_req_path(),
                    origin_hdr=request.headers.get("origin"),
                    referer_hdr=request.headers.get("referer"),
                    x_forwarded_origin_hdr=request.headers.get("x-forwarded-origin"))
    raise HTTPException(
        401,
        f"Origin '{candidates[0]}' is not on the widget allowlist"
        + (f" (checked {len(candidates)} header candidate(s))" if len(candidates) > 1 else ""),
    )


# ═══════════════════════════════════════════════════════════════════════
# Slice G2 · Public widget config — read-only, widget-auth
# ═══════════════════════════════════════════════════════════════════════
@router.get("/widget/config")
async def get_widget_public_config(
    tenant: Dict[str, Any] = Depends(require_widget_auth),
):
    """Public config surface consumed by the widget JS bundle at load
    time. Returns branding + welcome copy + Turnstile site key when
    configured. Widget-auth enforced (X-Widget-Key + Origin allowlist)."""
    branding = tenant.get("branding") or {}
    return {
        "tenant_name": tenant.get("name") or tenant.get("slug") or "",
        "tenant_slug": tenant.get("slug"),
        "brand_color": branding.get("brand_color") or tenant.get("brand_color") or "#0EA5E9",
        "logo_url": branding.get("logo_url") or tenant.get("logo_url") or None,
        "welcome_message": (
            tenant.get("widget_welcome_message")
            or "Hi! How can I help you today?"
        ),
        "turnstile_site_key": (os.environ.get("TURNSTILE_SITE_KEY") or "").strip() or None,
    }


# ═══════════════════════════════════════════════════════════════════════
# Slice G3 · Admin — denied-requests ring buffer read
# ═══════════════════════════════════════════════════════════════════════
@router.get("/tenants/mine/widget-config/denied-requests")
async def get_widget_denied_requests(user: dict = Depends(get_current_user)):
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(400, "User has no tenant")
    return {"denied": await get_denied_ring(tid)}

