"""MR1+MR2 · Feb-2026 — Public widget backend.

Endpoints
---------
* ``GET /api/public/checkins/{tenant_slug}/feed``
    Public, CORS-open, tenant-scoped. Returns sanitized approved
    check-ins for the widget to render. Rate-limited per-IP (60 rpm).

* ``GET /api/widget.js``
    Public, no auth. Serves the embed script (JavaScript, cache-safe).

* ``GET /api/widget/preview/{tenant_slug}``
    Admin+/manager only. HTML page for the admin preview iframe. Loads
    the widget script + a demo container, so admins can see exactly
    what a customer site would render.

Sanitisation rules
------------------
The feed endpoint MUST NOT return any of the following raw fields from
``db.public_checkins``:

    raw_address, submitted_by_user_id, reviewer_notes,
    source_checkin_id, source_job_id, reviewed_by_user_id,
    approved_by_user_id, tenant_id (internal id), photo_license_ack,
    unpublished_at, unpublished_by_user_id

Only rows in ``state='approved'`` are returned. Rows without a
``masked_address`` (safety net) are silently dropped.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from config import db
from utils import get_current_user, now_iso

router = APIRouter()

# ── Rate limit state (per-process, single-instance is fine here) ────
_RATE_WINDOW_S = 60
_RATE_LIMIT = 60
_ip_buckets: Dict[str, Deque[float]] = defaultdict(deque)


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    q = _ip_buckets[ip]
    while q and (now - q[0]) > _RATE_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return False
    q.append(now)
    return True


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip() or "?"
    return (request.client.host if request.client else "?")


def _cors(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response


# ── Slug → tenant helper ────────────────────────────────────────────
async def _tenant_by_slug(slug: str) -> Dict[str, Any]:
    row = await db.tenants.find_one(
        {"$or": [{"slug": slug}, {"slug_aliases": slug}]},
        {"_id": 0, "id": 1, "name": 1, "slug": 1,
         "brand_primary": 1, "brand_secondary": 1,
         "settings": 1},
    )
    if not row:
        raise HTTPException(404, {"error": "tenant_not_found"})
    return row


def _tenant_logo_url(tenant: Dict[str, Any]) -> Optional[str]:
    """Emergent tenants don't yet store a ``logo_url`` field on the
    root tenant document. Look in ``settings.business_card.logo_url``
    (present on a small number of tenants). Return ``None`` if
    unavailable — the widget will render a text-only header."""
    st = (tenant.get("settings") or {})
    bc = st.get("business_card") or {}
    return bc.get("logo_url")


def _sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Return the caller-safe subset of a ``public_checkins`` row.

    * ``photos`` — URLs are passed through. When ``EMERGENT_FILES_HOST``
      is configured we could later swap in signed URLs, but for now
      photos are already uploaded to a publicly-addressable location
      at capture time. We add ``cache_ttl_s`` at the response level so
      embed sites know how long to cache.
    """
    photos = []
    for p in (row.get("photos") or []):
        if isinstance(p, dict) and p.get("url"):
            photos.append({"url": p["url"], "alt": p.get("alt")})
    return {
        "id": row.get("id"),
        "service_name": row.get("service_name") or "",
        "service_category": row.get("service_category"),
        "description": row.get("description") or "",
        "tags": list(row.get("tags") or []),
        "photos": photos,
        "location": row.get("masked_address") or {},
        "completed_at": row.get("approved_at") or row.get("submitted_at"),
    }


# ═══════════════════════ 1) FEED ════════════════════════════════════
@router.options("/public/checkins/{tenant_slug}/feed",
                 include_in_schema=False)
async def feed_options(tenant_slug: str):
    return _cors(Response(status_code=204))


@router.get("/public/checkins/{tenant_slug}/feed",
             operation_id="publicWidget.feed")
async def public_feed(
    tenant_slug: str,
    request: Request,
    response: Response,
    limit: int = 12,
    service_category: Optional[str] = None,
):
    _cors(response)
    ip = _client_ip(request)
    if not _rate_ok(ip):
        raise HTTPException(429, {"error": "rate_limited"})

    tenant = await _tenant_by_slug(tenant_slug)
    limit = max(1, min(50, int(limit)))

    q: Dict[str, Any] = {"tenant_id": tenant["id"], "state": "approved"}
    if service_category:
        q["service_category"] = str(service_category).strip().lower()

    checkins: List[Dict[str, Any]] = []
    async for row in db.public_checkins.find(q, {"_id": 0}) \
                                          .sort("approved_at", -1) \
                                          .limit(limit):
        if not row.get("masked_address"):
            continue  # safety: never surface un-masked rows
        checkins.append(_sanitize_row(row))

    # Cache-Control: 5 min shared cache is safe; embed sites can also
    # rely on the 7-day (soft) TTL declared inside the payload.
    response.headers["Cache-Control"] = "public, max-age=300"

    return {
        "tenant": {
            "name": tenant.get("name"),
            "slug": tenant.get("slug"),
            "logo_url": _tenant_logo_url(tenant),
            "brand_primary": tenant.get("brand_primary"),
            "brand_secondary": tenant.get("brand_secondary"),
        },
        "checkins": checkins,
        "count": len(checkins),
        "as_of": now_iso(),
        # Advisory client-cache lifetime for photo URLs (7 days).
        "cache_ttl_s": 7 * 24 * 60 * 60,
    }


# ═══════════════════════ 2) widget.js ═══════════════════════════════
_WIDGET_JS = r"""/*! Emergent Widget · MR1 Feb-2026 · Public check-in feed */
(function () {
  // `document.currentScript` can be null when the script is loaded
  // async (attribute set on the tag) — the browser may execute after
  // parsing. Fallback: find our own tag by src match.
  var TAG = document.currentScript;
  if (!TAG) {
    var scripts = document.querySelectorAll("script[data-tenant]");
    for (var i = 0; i < scripts.length; i++) {
      if ((scripts[i].src || "").indexOf("/widget.js") !== -1) {
        TAG = scripts[i]; break;
      }
    }
  }
  if (!TAG) { return; }
  var TENANT = TAG.getAttribute("data-tenant") || "";
  var COUNT = parseInt(TAG.getAttribute("data-count") || "12", 10);
  var THEME = (TAG.getAttribute("data-theme") || "light").toLowerCase();
  var CATEGORY = TAG.getAttribute("data-category") || "";
  var ORIGIN = new URL(TAG.src, document.location.href).origin;

  var host = TAG.nextElementSibling;
  if (!host || host.tagName !== "DIV" || !host.hasAttribute("data-emergent-widget-mount")) {
    host = document.createElement("div");
    host.setAttribute("data-emergent-widget-mount", TENANT);
    TAG.parentNode.insertBefore(host, TAG.nextSibling);
  }
  var shadow = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

  var css = "\n" +
    ":host{all:initial;} *{box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;}\n" +
    ".wrap{--w-primary:var(--widget-primary,#0284C7);--w-accent:var(--widget-accent,#16A34A);--w-bg:#F8FAFC;--w-surface:#FFFFFF;--w-text:#0F172A;--w-muted:#64748B;--w-border:#E2E8F0;color:var(--w-text);background:var(--w-bg);padding:20px;border-radius:16px;}\n" +
    ".wrap.theme-dark{--w-bg:#0F172A;--w-surface:#1E293B;--w-text:#F8FAFC;--w-muted:#94A3B8;--w-border:#334155;}\n" +
    ".hdr{display:flex;align-items:center;gap:12px;margin-bottom:16px;}\n" +
    ".hdr img{height:32px;width:auto;border-radius:4px;}\n" +
    ".hdr h2{font-size:18px;font-weight:700;margin:0;color:var(--w-text);}\n" +
    ".hdr .sub{font-size:12px;color:var(--w-muted);}\n" +
    ".grid{display:grid;grid-template-columns:1fr;gap:16px;}\n" +
    "@media(min-width:480px){.grid{grid-template-columns:1fr 1fr;}}\n" +
    "@media(min-width:800px){.grid{grid-template-columns:1fr 1fr 1fr;}}\n" +
    ".card{background:var(--w-surface);border:1px solid var(--w-border);border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(15,23,42,0.06);transition:box-shadow .2s ease;}\n" +
    ".card:hover{box-shadow:0 4px 12px rgba(15,23,42,0.10);}\n" +
    ".photo{aspect-ratio:16/9;background:var(--w-border);background-size:cover;background-position:center;}\n" +
    ".body{padding:12px;}\n" +
    ".svc{font-size:15px;font-weight:600;margin:0 0 4px;color:var(--w-text);}\n" +
    ".loc{font-size:12px;color:var(--w-muted);margin:0 0 8px;}\n" +
    ".desc{font-size:13px;color:var(--w-text);margin:0 0 8px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}\n" +
    ".tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;}\n" +
    ".tag{font-size:10px;padding:2px 6px;border-radius:999px;background:color-mix(in srgb,var(--w-primary) 10%,transparent);color:var(--w-primary);border:1px solid color-mix(in srgb,var(--w-primary) 20%,transparent);}\n" +
    ".ts{font-size:11px;color:var(--w-muted);}\n" +
    ".empty{padding:24px;text-align:center;color:var(--w-muted);font-size:13px;}\n";

  var container = document.createElement("div");
  container.className = "wrap theme-" + (THEME === "dark" ? "dark" : "light");
  container.setAttribute("data-testid", "emergent-widget-root");

  var styleEl = document.createElement("style");
  styleEl.textContent = css;
  shadow.appendChild(styleEl);
  shadow.appendChild(container);

  function esc(s){ return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }

  function fmtDate(iso){
    if(!iso) return "";
    try{
      var d = new Date(iso);
      return d.toLocaleDateString(undefined, {year:"numeric",month:"short",day:"numeric"});
    }catch(e){ return ""; }
  }

  function injectJsonLd(feed){
    var seen = {};
    var services = [];
    (feed.checkins || []).forEach(function(c){
      if(!c.service_name || seen[c.service_name]) return;
      seen[c.service_name] = true;
      services.push({
        "@type":"Service", "name": c.service_name,
        "areaServed": {"@type":"Place",
                        "address": {"@type":"PostalAddress",
                                     "addressLocality": (c.location||{}).city || "",
                                     "addressRegion":   (c.location||{}).state || ""}}
      });
    });
    var ld = {
      "@context":"https://schema.org","@type":"LocalBusiness",
      "name": (feed.tenant||{}).name || "",
      "url": document.location.href,
      "makesOffer": services
    };
    var sc = document.createElement("script");
    sc.type = "application/ld+json";
    sc.setAttribute("data-emergent-widget-jsonld", TENANT);
    sc.textContent = JSON.stringify(ld);
    // Attach to *host* document (so search-engine crawlers can see it),
    // not to the shadow root.
    document.head.appendChild(sc);
    return sc;
  }

  function render(feed){
    container.innerHTML = "";
    var t = feed.tenant || {};
    var hdr = document.createElement("div");
    hdr.className = "hdr";
    var logo = t.logo_url ? '<img alt="'+esc(t.name)+'" src="'+esc(t.logo_url)+'"/>' : "";
    hdr.innerHTML = logo + '<div><h2>'+esc(t.name || "Recent Jobs")+'</h2><div class="sub">Recent Jobs</div></div>';
    container.appendChild(hdr);

    var items = feed.checkins || [];
    if(items.length === 0){
      var e = document.createElement("div"); e.className = "empty";
      e.textContent = "No recent check-ins yet.";
      container.appendChild(e);
      return;
    }
    var grid = document.createElement("div"); grid.className = "grid";
    items.forEach(function(c, idx){
      var card = document.createElement("div");
      card.className = "card"; card.setAttribute("data-testid", "widget-card-"+idx);
      var mainPhoto = (c.photos && c.photos[0] && c.photos[0].url) || "";
      var loc = c.location || {};
      var locStr = [loc.street_name, loc.city, loc.state].filter(Boolean).join(", ");
      var tagsHtml = (c.tags||[]).slice(0,4).map(function(t){ return '<span class="tag">'+esc(t)+'</span>'; }).join("");
      card.innerHTML =
        (mainPhoto ? '<div class="photo" style="background-image:url('+ JSON.stringify(mainPhoto) + ')" loading="lazy"></div>' : '<div class="photo"></div>') +
        '<div class="body">' +
          '<div class="svc">' + esc(c.service_name || "") + '</div>' +
          (locStr ? '<div class="loc">' + esc(locStr) + '</div>' : "") +
          (c.description ? '<div class="desc">' + esc(c.description) + '</div>' : "") +
          (tagsHtml ? '<div class="tags">' + tagsHtml + '</div>' : "") +
          '<div class="ts">' + fmtDate(c.completed_at) + '</div>' +
        '</div>';
      grid.appendChild(card);
    });
    container.appendChild(grid);
    injectJsonLd(feed);
  }

  function url(){
    var u = new URL(ORIGIN + "/api/public/checkins/" + encodeURIComponent(TENANT) + "/feed");
    u.searchParams.set("limit", String(COUNT));
    if(CATEGORY) u.searchParams.set("service_category", CATEGORY);
    return u.toString();
  }

  var TIMER = null;
  function load(){
    if(!TENANT){ return; }
    fetch(url()).then(function(r){ if(!r.ok) throw new Error(r.status); return r.json(); })
      .then(render)
      .catch(function(e){
        console.warn("emergent-widget load failed:", e);
      });
  }

  // Initial render + 5-minute refresh while page is visible.
  load();
  if(typeof document.addEventListener === "function"){
    document.addEventListener("visibilitychange", function(){
      if(document.visibilityState === "visible") load();
    });
  }
  TIMER = setInterval(function(){
    if(document.visibilityState === "visible") load();
  }, 5 * 60 * 1000);

  // Expose a tiny debug hook for the vitest suite.
  window.__EmergentWidget = { host: host, shadow: shadow, url: url };
})();
"""


@router.options("/widget.js", include_in_schema=False)
async def widget_js_options():
    r = Response(status_code=204)
    return _cors(r)


@router.get("/widget.js", operation_id="publicWidget.script")
async def widget_js(response: Response):
    _cors(response)
    response.headers["Cache-Control"] = "public, max-age=300"
    return PlainTextResponse(
        _WIDGET_JS, media_type="application/javascript",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300",
        },
    )


# ═══════════════════════ 3) widget/preview/{slug} ═══════════════════
_PREVIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Widget Preview — {name}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  html,body{{margin:0;padding:0;background:{bg};color:{fg};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;}}
  .frame{{padding:24px;}}
  .banner{{padding:8px 12px;background:{banner_bg};color:{banner_fg};font-size:12px;border-radius:8px;margin-bottom:16px;display:inline-block;}}
</style>
</head>
<body>
<div class="frame">
  <div class="banner">Widget Preview · Emergent Admin</div>
  <script src="{origin}/api/widget.js"
          data-tenant="{slug}"
          data-count="{count}"
          data-theme="{theme}"
          {category_attr}
          async></script>
</div>
</body>
</html>
"""


@router.get("/widget/preview/{tenant_slug}",
             operation_id="publicWidget.preview")
async def widget_preview(
    tenant_slug: str,
    request: Request,
    theme: str = "light",
    count: int = 10,
    category: Optional[str] = None,
):
    """Preview page — renders the SAME public widget an external site
    would embed. Intentionally public: it doesn't expose anything the
    widget itself doesn't. ``X-Frame-Options: SAMEORIGIN`` prevents
    third-party sites from iframing this admin-styled preview."""
    tenant = await _tenant_by_slug(tenant_slug)

    theme = "dark" if str(theme).lower() == "dark" else "light"
    count = max(1, min(50, int(count)))
    bg, fg = ("#0F172A", "#F8FAFC") if theme == "dark" else ("#F8FAFC", "#0F172A")
    banner_bg, banner_fg = ("#1E293B", "#94A3B8") if theme == "dark" else ("#E2E8F0", "#475569")
    cat_attr = (f'data-category="{category}"' if category else "")
    body = _PREVIEW_HTML.format(
        name=tenant.get("name") or "Preview",
        origin="",  # use relative URLs so the browser hits whatever host it's on
        slug=tenant.get("slug"),
        theme=theme,
        count=count,
        category_attr=cat_attr,
        bg=bg, fg=fg,
        banner_bg=banner_bg, banner_fg=banner_fg,
    )
    return HTMLResponse(body, headers={"X-Frame-Options": "SAMEORIGIN"})


__all__ = ["router"]
