/**
 * Slice P · Route metadata for the shared <Breadcrumbs> component.
 *
 * Static crumbs are keyed by URL path (with ``:param`` placeholders
 * where relevant).  Dynamic segments — customer name on a customer
 * detail page, invoice number on an invoice detail page — are
 * resolved at render time via the ``useDynamicCrumb`` hook by pages
 * that opt in.
 *
 * Coverage:
 *   • ``/`` and ``/portal`` are LANDING pages — no crumbs rendered.
 *   • Auth pages (``/login``, ``/verify-magic``) — no crumbs rendered.
 *   • Anywhere else, the resolver walks up the ``parent`` chain to
 *     build ``Home > Section > Subsection > Current``.
 *
 * Add new entries here whenever a new deep page ships — the sensible
 * default (fallback derived from URL slug) still works while the
 * entry is being added.
 */

// Landing paths that should NOT render breadcrumbs.
export const CRUMB_SKIP = new Set([
  "/", "/portal", "/portal/", "/login", "/verify-magic",
  "/logout", "/forgot", "/reset-password",
]);

// Explicit metadata map. Keys are literal paths OR the resolver falls
// back to slug-derived labels when a path is not listed here.
export const ROUTE_META = {
  // ── Admin surfaces ────────────────────────────────
  "/dashboard":         { label: "Home", parent: null },
  "/workstream":        { label: "Workstream", parent: "/dashboard" },
  "/customers":         { label: "Customers", parent: "/dashboard" },
  "/customers/:id":     { label: "Customer", parent: "/customers" },
  "/jobs":              { label: "Jobs", parent: "/dashboard" },
  "/jobs/new":          { label: "New Job", parent: "/jobs" },
  "/jobs/:id":          { label: "Job Details", parent: "/jobs" },
  "/leads":             { label: "Leads", parent: "/dashboard" },
  "/estimates":         { label: "Estimates", parent: "/dashboard" },
  "/estimates/:id":     { label: "Estimate", parent: "/estimates" },
  "/invoices":          { label: "Invoices", parent: "/dashboard" },
  "/invoices/:id":      { label: "Invoice", parent: "/invoices" },
  "/reviews":           { label: "Reviews", parent: "/dashboard" },
  "/reviews/:id":       { label: "Review", parent: "/reviews" },
  "/marketing":         { label: "Marketing", parent: "/dashboard" },
  "/marketing/sequences":         { label: "Sequences", parent: "/marketing" },
  "/marketing/sequences/:id":     { label: "Sequence", parent: "/marketing/sequences" },
  "/marketing/sequences/:id/enrolments": {
    label: "Enrolments", parent: "/marketing/sequences/:id",
  },
  "/marketing/review-requests":   { label: "Review Requests", parent: "/marketing" },
  "/marketing/campaigns":         { label: "Campaigns", parent: "/marketing" },
  "/marketing/analytics":         { label: "Analytics", parent: "/marketing" },
  "/settings":                    { label: "Settings", parent: "/dashboard" },
  "/settings/tenant":             { label: "Tenant", parent: "/settings" },
  "/settings/tenant/hq":          { label: "HQ Location", parent: "/settings/tenant" },
  "/settings/billing":            { label: "Billing", parent: "/settings" },
  "/settings/notifications":      { label: "Notifications", parent: "/settings" },

  // ── Customer portal ───────────────────────────────
  "/portal/home":           { label: "Portal", parent: null },
  "/portal/invoices":       { label: "Invoices", parent: "/portal/home" },
  "/portal/invoices/:id":   { label: "Invoice", parent: "/portal/invoices" },
  "/portal/estimates":      { label: "Estimates", parent: "/portal/home" },
  "/portal/estimates/:id":  { label: "Estimate", parent: "/portal/estimates" },
  "/portal/payment-methods":{ label: "Payment Methods", parent: "/portal/home" },
  "/portal/reviews":        { label: "Reviews", parent: "/portal/home" },
  "/portal/preferences":    { label: "Preferences", parent: "/portal/home" },
  "/portal/service-reports":{ label: "Service Reports", parent: "/portal/home" },

  // ── Tech surfaces ─────────────────────────────────
  "/tech/dashboard":  { label: "Dashboard", parent: null },
  "/tech/schedule":   { label: "Schedule", parent: "/tech/dashboard" },
};

/** Match a live pathname to a ROUTE_META key, replacing dynamic
 *  segments with ``:id`` placeholders. Returns the matched key or
 *  the raw path if no match. */
export function matchRouteKey(pathname) {
  if (ROUTE_META[pathname]) return pathname;
  const parts = pathname.split("/").filter(Boolean);
  for (const key of Object.keys(ROUTE_META)) {
    const keyParts = key.split("/").filter(Boolean);
    if (keyParts.length !== parts.length) continue;
    let ok = true;
    for (let i = 0; i < keyParts.length; i++) {
      if (keyParts[i].startsWith(":")) continue;
      if (keyParts[i] !== parts[i]) { ok = false; break; }
    }
    if (ok) return key;
  }
  return pathname;
}

/** Slug-derived label fallback ("marketing-analytics" → "Marketing Analytics"). */
export function fallbackLabel(segment) {
  return segment.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Given the current pathname, walk up the parent chain and return
 *  [{label, path?}]. The last crumb has no path (current page). */
export function buildCrumbs(pathname, dynamic = {}) {
  if (CRUMB_SKIP.has(pathname)) return [];
  const chain = [];
  let cur = matchRouteKey(pathname);
  const seen = new Set();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const meta = ROUTE_META[cur];
    let label;
    if (meta) {
      label = meta.label;
    } else {
      const segs = cur.split("/").filter(Boolean);
      label = fallbackLabel(segs[segs.length - 1] || cur);
    }
    // Materialise dynamic id segments to the live pathname so the
    // link back to the parent is correct.
    let materialised = cur;
    if (materialised.includes(":")) {
      const keyParts = cur.split("/");
      const liveParts = pathname.split("/");
      materialised = keyParts.map((p, i) =>
        p.startsWith(":") ? (liveParts[i] || p) : p,
      ).join("/");
    }
    // Override label from dynamic map if provided (e.g. "Job #A1B2").
    if (meta && dynamic[cur]) label = dynamic[cur];
    chain.push({ label, path: materialised });
    cur = meta ? meta.parent : null;
  }
  const crumbs = chain.reverse();
  // Current page — no link.
  if (crumbs.length) {
    crumbs[crumbs.length - 1] = {
      ...crumbs[crumbs.length - 1],
      path: null,
    };
  }
  return crumbs;
}
