"""TD-seo-phase1 · Oct-2026 — public sitemap + robots.txt endpoints.

Serves per-tenant ``/sitemap.xml`` and ``/robots.txt`` content for the
CRM's own public pages (Track A — the gap identified in the Phase 0
scoping doc at ``memory/td_seo_phase0_scoping.md``).

Mount path note (DEPLOYMENT FLAG for operator):
  The spec called for ``/sitemap.xml`` + ``/robots.txt`` at the HTTP
  host root so search engines discover them without a redirect. The
  current Kubernetes ingress routes everything with the ``/api``
  prefix to the backend; non-``/api`` paths go to the frontend
  static server. These endpoints are therefore mounted at
  ``/api/public/sitemap.xml`` + ``/api/public/robots.txt`` so they
  are reachable *immediately* from the backend. To make them
  discoverable at the canonical paths, operator will need to
  either:
    (a) Add ingress aliases that rewrite
        ``/sitemap.xml`` → ``/api/public/sitemap.xml`` and
        ``/robots.txt`` → ``/api/public/robots.txt`` on the public
        domain, OR
    (b) Add a Vite build-time plugin that serves the two files from
        the FE static origin by proxying ``/api/public/*``.
  Decision deferred to a dedicated deployment ticket after Phase 1
  code lands. Phase 2 FE Helmet work is unaffected.

Environment flag:
  ``SEO_PUBLIC_INDEXABLE`` (default: ``false`` on preview). When
  ``false`` the robots.txt serves ``User-agent: *\\nDisallow: /``
  so preview-environment URLs never get indexed. Operator sets this
  to ``true`` only in production env config.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from config import db


router = APIRouter(tags=["public-seo"])


# ─── Indexable public routes (per Phase 0 scoping §1.3) ─────────────
# Each entry: (path_template, changefreq, priority, lastmod_source).
# Path templates may contain ``{tenant_slug}`` to be substituted at
# render time with the resolved tenant's slug.
_INDEXABLE_ROUTES = [
    # Tenant business card landing (branded).
    ("/public/card/{tenant_slug}",
     "monthly", "0.8"),
    # Public reviews widget page.
    ("/reviews/{tenant_slug}",
     "weekly",  "0.9"),
    # Public lead-intake generic page.
    ("/public/leads",
     "weekly",  "0.7"),
    # Public estimate landing.
    ("/e/estimate",
     "monthly", "0.6"),
    # Note: ``/public/checkins/{slug}/feed.html`` is DELIBERATELY NOT
    # listed — it already carries BE-rendered JSON-LD via
    # ``public_widget.py:524-536`` and is reachable from the Business
    # Card page. Including it here would create duplicate-link bloat
    # without SEO benefit.
    # Note: ``/f/:slug`` (public form) is per-template, excluded from
    # per-tenant sitemap because the slug set is dynamic + ephemeral.
]


def _env_indexable() -> bool:
    """Phase 1 env-flag gate — defaults ``false`` on preview per
    operator decision #5 to prevent duplicate-content indexing."""
    return (os.environ.get("SEO_PUBLIC_INDEXABLE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def _resolve_tenant_from_request(request: Request) -> Optional[dict]:
    """Lightweight no-auth tenant resolver for public endpoints.

    Resolution order:
      1. ``?tenant=<slug>`` query parameter.
      2. ``Host`` header → ``tenants.custom_domain`` match.
      3. ``Host`` header → leftmost subdomain → ``tenants.slug`` match.
      4. ``X-Tenant-Slug`` header fallback.
      5. Default tenant (first active).
    Returns ``None`` only when the DB has zero active tenants.
    """
    # 1. Explicit query param (test + impersonation).
    slug_q = request.query_params.get("tenant") or ""
    if slug_q:
        t = await db.tenants.find_one(
            {"slug": slug_q.strip().lower(), "active": True}, {"_id": 0})
        if t:
            return t
    host = (request.headers.get("host") or "").split(":")[0].lower()
    # 2. Custom domain match.
    if host:
        t = await db.tenants.find_one(
            {"custom_domain": host, "active": True}, {"_id": 0})
        if t:
            return t
    # 3. Leftmost subdomain.
    if host and host.count(".") >= 2:
        subdomain = host.split(".", 1)[0]
        if subdomain and subdomain not in ("www", "app"):
            t = await db.tenants.find_one(
                {"slug": subdomain, "active": True}, {"_id": 0})
            if t:
                return t
    # 4. Header fallback.
    hdr = (request.headers.get("x-tenant-slug") or "").strip().lower()
    if hdr:
        t = await db.tenants.find_one(
            {"slug": hdr, "active": True}, {"_id": 0})
        if t:
            return t
    # 5. Default — first active tenant.
    return await db.tenants.find_one({"active": True}, {"_id": 0})


def _canonical_base(tenant: dict) -> str:
    """Base URL for links emitted inside sitemap entries.

    Prefers ``settings.business_card.seo.canonical_base_url`` → tenant
    ``custom_domain`` → fallback to request-less default
    (``https://app.plofv.com``).
    """
    seo = (((tenant or {}).get("settings") or {})
           .get("business_card") or {}).get("seo") or {}
    override = (seo.get("canonical_base_url") or "").strip().rstrip("/")
    if override:
        return override
    cd = ((tenant or {}).get("custom_domain") or "").strip().rstrip("/")
    if cd:
        return f"https://{cd}"
    return "https://app.plofv.com"


@router.get("/public/sitemap.xml",
             operation_id="publicSeo.sitemap",
             include_in_schema=False)
async def sitemap_xml(request: Request):
    """Per-tenant sitemap. Honours ``SEO_PUBLIC_INDEXABLE`` env flag —
    emits an empty but valid urlset when flag is off (preview env)."""
    tenant = await _resolve_tenant_from_request(request)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = _canonical_base(tenant) if tenant else "https://app.plofv.com"
    slug = (tenant or {}).get("slug") or ""

    rows = []
    if _env_indexable() and tenant and slug:
        for (tpl, cf, pri) in _INDEXABLE_ROUTES:
            path = tpl.replace("{tenant_slug}", slug)
            loc = xml_escape(f"{base}{path}")
            rows.append(
                "  <url>\n"
                f"    <loc>{loc}</loc>\n"
                f"    <lastmod>{now_iso}</lastmod>\n"
                f"    <changefreq>{cf}</changefreq>\n"
                f"    <priority>{pri}</priority>\n"
                "  </url>"
            )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows)
        + ("\n" if rows else "")
        + "</urlset>\n"
    )
    headers = {"Cache-Control": "public, max-age=3600"}
    return Response(content=xml, media_type="application/xml",
                    headers=headers)


@router.get("/public/robots.txt",
             operation_id="publicSeo.robots",
             include_in_schema=False)
async def robots_txt(request: Request):
    """Per-env robots.txt. Preview env (flag off) → disallow all;
    production (flag on) → allow public routes + disallow admin/API."""
    tenant = await _resolve_tenant_from_request(request)
    base = _canonical_base(tenant) if tenant else "https://app.plofv.com"

    if not _env_indexable():
        # Preview / unflagged env — hard disallow everything.
        body = "User-agent: *\nDisallow: /\n"
    else:
        # Production — allow public, disallow admin/API/portal/authed.
        lines = [
            "User-agent: *",
            "Allow: /public/",
            "Allow: /reviews/",
            "Allow: /e/estimate",
            "Allow: /f/",
            "Disallow: /api/",
            "Disallow: /portal/",
            "Disallow: /customer-portal/",
            "Disallow: /dev/",
            "Disallow: /settings/",
            "Disallow: /jobs/",
            "Disallow: /invoices/",
            "Disallow: /schedule/",
            "Disallow: /leads/",
            "Disallow: /customers/",
            "Disallow: /dashboard",
            "Disallow: /login",
            "Disallow: /signup",
            "Disallow: /business-signup/",
            "Disallow: /onboarding-wizard",
            "Disallow: /tenant-picker",
            "Disallow: /forgot-password",
            "Disallow: /reset-password",
            "",
            f"Sitemap: {base}/api/public/sitemap.xml",
            "",
        ]
        body = "\n".join(lines)
    headers = {"Cache-Control": "public, max-age=3600"}
    return PlainTextResponse(content=body, headers=headers)
