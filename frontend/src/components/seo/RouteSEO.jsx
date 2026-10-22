/**
 * TD-seo-phase2 · Oct-2026 — client-side SEO meta/OG/Twitter + JSON-LD
 * emitter for the 5 React-rendered public routes.
 *
 * Props:
 *   - ``tenant_slug`` (string, required) — resolves tenant SEO via
 *     ``GET /api/public/portal-seo/{tenant_slug}``.
 *   - ``route_kind`` (string, required) — one of ``business_card`` /
 *     ``reviews`` / ``lead_form`` / ``estimate`` / ``public_leads``.
 *     Determines the JSON-LD shape. (``checkins`` is BE-rendered via
 *     ``public_widget.py:524-536`` and NOT handled here.)
 *   - ``page_specific_overrides`` (object, optional) — per-page
 *     title / description / canonical overrides composable on top of
 *     the tenant-wide SEO sub-doc (e.g., estimate page may override
 *     title with the quote number).
 *
 * Behavior:
 *   - Fetch SEO sub-doc on mount with a module-level dedupe cache
 *     keyed by ``tenant_slug`` (short TTL — SEO content is low-
 *     frequency admin edits, no reactive refetch needed).
 *   - Emit ``<title>``, ``<meta name="description">``,
 *     ``<meta property="og:*">``, ``<meta name="twitter:*">``,
 *     ``<link rel="canonical">``, and a single
 *     ``<script type="application/ld+json">`` block per route_kind.
 *   - On fetch 404 / network error: render minimal ``<title>`` only;
 *     NO OG tags, NO JSON-LD (fail-safe fallback — never block the
 *     page from rendering because of SEO fetch issues).
 */
import React from "react";
import { Helmet } from "react-helmet-async";
import { api } from "@/api";


// Module-level dedupe cache. Short TTL (5 min) matches BE Cache-Control
// semantics; SEO sub-doc is low-frequency admin-edited.
const _CACHE = new Map();   // tenant_slug → { data, fetched_at }
const _INFLIGHT = new Map(); // tenant_slug → Promise
const _TTL_MS = 5 * 60 * 1000;


async function _fetchSeoDoc(tenant_slug) {
  if (!tenant_slug) return null;
  const cached = _CACHE.get(tenant_slug);
  if (cached && (Date.now() - cached.fetched_at) < _TTL_MS) {
    return cached.data;
  }
  if (_INFLIGHT.has(tenant_slug)) {
    return _INFLIGHT.get(tenant_slug);
  }
  const p = api.get(`/public/portal-seo/${encodeURIComponent(tenant_slug)}`)
    .then((data) => {
      _CACHE.set(tenant_slug, { data, fetched_at: Date.now() });
      _INFLIGHT.delete(tenant_slug);
      return data;
    })
    .catch(() => {
      // 404 / network error — fail-safe cache so repeat renders
      // don't thrash.
      _CACHE.set(tenant_slug, { data: null, fetched_at: Date.now() });
      _INFLIGHT.delete(tenant_slug);
      return null;
    });
  _INFLIGHT.set(tenant_slug, p);
  return p;
}


function _canonicalBase(seo) {
  if (seo?.canonical_base_url) {
    return String(seo.canonical_base_url).replace(/\/$/, "");
  }
  // Fallback — use current origin at runtime (SSR-safe).
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "https://app.plofv.com";
}


function _canonicalPath(route_kind, tenant_slug) {
  switch (route_kind) {
    case "business_card": return `/public/card/${tenant_slug}`;
    case "reviews":       return `/reviews/${tenant_slug}`;
    case "lead_form":     return `/f/${tenant_slug}`;
    case "estimate":      return `/e/estimate`;
    case "public_leads":  return `/public/leads`;
    default:              return "/";
  }
}


function _buildJsonLd(route_kind, seo) {
  if (!seo) return null;
  const base = _canonicalBase(seo);
  const org = {
    "@context": "https://schema.org",
    "@type":    "Organization",
    "name":     seo.company_name || seo.og_title || "",
    "url":      base,
    "logo":     seo.og_image_url || "",
  };
  if (seo.phone) org.telephone = seo.phone;
  if (seo.email) org.email = seo.email;

  const localBusiness = {
    ...org,
    "@type":       "LocalBusiness",
    "description": seo.og_description || "",
    "areaServed":  seo.service_areas || [],
  };
  if (seo.service_area) localBusiness.address = seo.service_area;

  const contactPoint = seo.phone
    ? { "@type": "ContactPoint", telephone: seo.phone,
        contactType: "customer service" }
    : null;

  let payload = null;
  switch (route_kind) {
    case "business_card":
      payload = {
        "@context": "https://schema.org",
        "@graph": [
          localBusiness,
          { ...org,
            "contactPoint": contactPoint ? [contactPoint] : [] },
        ],
      };
      break;
    case "reviews":
      payload = { ...localBusiness };
      break;
    case "lead_form":
    case "public_leads":
      payload = {
        "@context": "https://schema.org",
        "@graph": [
          org,
          { "@context": "https://schema.org", "@type": "Service",
            "provider": { "@type": "Organization",
                             "name": org.name, "url": org.url },
            "name":        org.name,
            "description": seo.og_description || "",
            "areaServed":  seo.service_areas || [] },
        ],
      };
      break;
    case "estimate":
      // Per-user quote — never surface pricing/customer in JSON-LD.
      payload = org;
      break;
    default:
      return null;
  }
  // Shallow merge of per-tenant overrides on top.
  if (seo.json_ld_overrides && typeof seo.json_ld_overrides === "object") {
    payload = { ...payload, ...seo.json_ld_overrides };
  }
  return payload;
}


export default function RouteSEO({
  tenant_slug,
  route_kind,
  page_specific_overrides,
}) {
  const [seo, setSeo] = React.useState(null);
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    _fetchSeoDoc(tenant_slug).then((data) => {
      if (cancelled) return;
      setSeo(data);
      setLoaded(true);
    });
    return () => { cancelled = true; };
  }, [tenant_slug]);

  // Render minimal fallback title until SEO loads OR on 404.
  if (!loaded) {
    return <Helmet>
      <title data-testid="route-seo-title-fallback">Loading…</title>
    </Helmet>;
  }
  if (!seo) {
    return <Helmet>
      <title data-testid="route-seo-title-fallback">
        Pool &amp; Landscaping of Vistancia
      </title>
    </Helmet>;
  }

  const ov = page_specific_overrides || {};
  const title = ov.title || seo.og_title || seo.company_name || "";
  const description = ov.description
    || seo.meta_description_override || seo.og_description || "";
  const base = _canonicalBase(seo);
  const canonical = ov.canonical
    || `${base}${_canonicalPath(route_kind, tenant_slug)}`;
  const image = ov.og_image_url || seo.og_image_url || "";
  const twitterCard = seo.twitter_card || "summary_large_image";
  const twitterSite = seo.twitter_site;

  const jsonld = _buildJsonLd(route_kind, seo);

  return (
    <Helmet>
      <title data-testid="route-seo-title">{title}</title>
      <meta name="description" content={description}
            data-testid="route-seo-meta-description" />
      <link rel="canonical" href={canonical}
            data-testid="route-seo-canonical" />
      <meta property="og:type"        content="website" />
      <meta property="og:title"       content={title}
            data-testid="route-seo-og-title" />
      <meta property="og:description" content={description}
            data-testid="route-seo-og-description" />
      <meta property="og:url"         content={canonical}
            data-testid="route-seo-og-url" />
      {image ? (
        <meta property="og:image" content={image}
              data-testid="route-seo-og-image" />
      ) : null}
      <meta name="twitter:card"        content={twitterCard}
            data-testid="route-seo-twitter-card" />
      <meta name="twitter:title"       content={title} />
      <meta name="twitter:description" content={description} />
      {twitterSite ? (
        <meta name="twitter:site" content={twitterSite} />
      ) : null}
      {image ? <meta name="twitter:image" content={image} /> : null}
      {jsonld ? (
        <script type="application/ld+json"
                data-testid="route-seo-jsonld">
          {JSON.stringify(jsonld)}
        </script>
      ) : null}
    </Helmet>
  );
}


// Named export for tests + per-route reuse.
export { _buildJsonLd, _canonicalBase, _canonicalPath,
         _fetchSeoDoc as __fetchSeoDocForTests,
         _CACHE as __cacheForTests };


/**
 * TD-seo-phase2 · Oct-2026 — React-Router-aware adapter that pulls
 * the slug from URL params + a child element renderer. Avoids
 * modifying each public page component's internals.
 *
 * Usage in App.js:
 *   <Route path="/public/card/:slug"
 *          element={<RouteSEOScope paramName="slug"
 *                                    route_kind="business_card">
 *                     <PublicCard />
 *                   </RouteSEOScope>} />
 */
import { useParams } from "react-router-dom";

export function RouteSEOScope({ paramName, route_kind,
                                   page_specific_overrides,
                                   children }) {
  const params = useParams();
  const tenant_slug = params?.[paramName] || "";
  return (
    <>
      <RouteSEO tenant_slug={tenant_slug}
                 route_kind={route_kind}
                 page_specific_overrides={page_specific_overrides} />
      {children}
    </>
  );
}
