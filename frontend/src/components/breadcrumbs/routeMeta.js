/**
 * Slice P · Route metadata for the shared <Breadcrumbs> component.
 *
 * Phase K2 · Feb-2026 — expanded coverage (schedule, quotes,
 * analytics, admin/*, every portal route + a few tech routes) and
 * added ``routeIsDynamic`` so the AppBreadcrumbs shell can render
 * a "..." skeleton while the page loads the entity behind
 * ``/customers/:id`` etc.
 *
 * Static crumbs are keyed by URL path (with ``:param`` placeholders
 * where relevant).  Dynamic segments — customer name on a customer
 * detail page, invoice number on an invoice detail page — are
 * resolved at render time via ``useSetDynamicCrumb`` in the
 * page that owns the entity.
 *
 * Coverage:
 *   • ``/``, ``/dashboard``, ``/portal``, ``/portal/home``, and
 *     ``/tech/dashboard`` are LANDING pages — no crumbs rendered.
 *   • Auth pages (``/login``, ``/verify-magic``) — no crumbs.
 *   • Anywhere else, the resolver walks up the ``parent`` chain to
 *     build ``Home > Section > Subsection > Current``.
 *
 * Add new entries here whenever a new deep page ships — the
 * sensible default (fallback derived from URL slug) still works
 * while the entry is being added.
 */

// Landing paths that should NOT render breadcrumbs.
// Phase K2 · Feb-2026 — added the actual landing routes for the
// admin (``/dashboard``), portal (``/portal/home``), and tech
// (``/tech/dashboard``) shells; the pre-K2 set only had the raw
// ``/portal`` string (which the app rewrites to ``/portal/home``
// via a ``<Navigate>`` redirect).
export const CRUMB_SKIP = new Set([
  "/", "/portal", "/portal/", "/portal/home",
  "/dashboard", "/tech/dashboard",
  "/login", "/verify-magic",
  "/logout", "/forgot", "/reset-password",
]);

// Explicit metadata map. Keys are literal paths OR the resolver falls
// back to slug-derived labels when a path is not listed here.
export const ROUTE_META = {
  // ── Admin surfaces ────────────────────────────────
  "/dashboard":         { label: "Home", parent: null },
  "/workstream":        { label: "Workstream", parent: "/dashboard" },
  "/schedule":          { label: "Schedule", parent: "/dashboard" },
  "/customers":         { label: "Customers", parent: "/dashboard" },
  "/customers/:id":     { label: "Customer", parent: "/customers",
                              dynamic: "customer" },
  "/jobs":              { label: "Jobs", parent: "/dashboard" },
  "/jobs/new":          { label: "New Job", parent: "/jobs" },
  "/jobs/:id":          { label: "Job Details", parent: "/jobs",
                              dynamic: "job" },
  "/leads":             { label: "Leads", parent: "/dashboard" },
  "/leads/:id":         { label: "Lead", parent: "/leads",
                              dynamic: "lead" },
  "/quotes":            { label: "Quotes", parent: "/dashboard" },
  "/quotes/:id":        { label: "Quote", parent: "/quotes",
                              dynamic: "quote" },
  "/estimates":         { label: "Estimates", parent: "/dashboard" },
  "/estimates/:id":     { label: "Estimate", parent: "/estimates",
                              dynamic: "estimate" },
  "/invoices":          { label: "Invoices", parent: "/dashboard" },
  "/invoices/:id":      { label: "Invoice", parent: "/invoices",
                              dynamic: "invoice" },
  "/payments":          { label: "Payments", parent: "/dashboard" },
  "/analytics":         { label: "Analytics", parent: "/dashboard" },
  "/reports":           { label: "Reports", parent: "/dashboard" },
  "/reviews":           { label: "Reviews", parent: "/dashboard" },
  "/reviews/:id":       { label: "Review", parent: "/reviews",
                              dynamic: "review" },
  "/marketing":         { label: "Marketing", parent: "/dashboard" },
  "/marketing/sequences":         { label: "Sequences", parent: "/marketing" },
  "/marketing/sequences/:id":     { label: "Sequence", parent: "/marketing/sequences",
                                            dynamic: "sequence" },
  "/marketing/sequences/:id/enrolments": {
    label: "Enrolments", parent: "/marketing/sequences/:id",
  },
  "/marketing/review-requests":   { label: "Review Requests", parent: "/marketing" },
  "/marketing/campaigns":         { label: "Campaigns", parent: "/marketing" },
  "/marketing/analytics":         { label: "Analytics", parent: "/marketing" },

  // Admin nested surfaces (analytics, ops, integrations, etc.)
  "/admin":                       { label: "Admin", parent: "/dashboard" },
  "/admin/analytics":             { label: "Analytics", parent: "/admin" },
  "/admin/analytics-monthly":     { label: "Analytics · Monthly", parent: "/admin" },
  "/admin/ops":                   { label: "Ops", parent: "/admin" },
  "/admin/audit-events":          { label: "Audit Events", parent: "/admin" },
  "/admin/integrations":          { label: "Integrations", parent: "/admin" },
  "/admin/tenants":               { label: "Tenants", parent: "/admin" },
  "/admin/users":                 { label: "Users", parent: "/admin" },
  "/admin/health-check":          { label: "Health Check", parent: "/admin" },
  "/admin/soshie":                { label: "Soshie", parent: "/admin" },
  "/admin/queue":                 { label: "Queue", parent: "/admin" },

  "/settings":                    { label: "Settings", parent: "/dashboard" },
  "/settings/tenant":             { label: "Tenant", parent: "/settings" },
  "/settings/tenant/hq":          { label: "HQ Location", parent: "/settings/tenant" },
  "/settings/billing":            { label: "Billing", parent: "/settings" },
  "/settings/notifications":      { label: "Notifications", parent: "/settings" },

  // ── Customer portal ───────────────────────────────
  "/portal/home":           { label: "Portal", parent: null },
  "/portal/services":       { label: "Services", parent: "/portal/home" },
  "/portal/services/:id":   { label: "Service", parent: "/portal/services",
                                    dynamic: "service" },
  "/portal/service-reports":     { label: "Service Reports", parent: "/portal/home" },
  "/portal/service-reports/:id": { label: "Service Report",
                                            parent: "/portal/service-reports",
                                            dynamic: "serviceReport" },
  "/portal/request-service":     { label: "Request Service", parent: "/portal/home" },
  "/portal/invoices":       { label: "Invoices", parent: "/portal/home" },
  "/portal/invoices/:id":   { label: "Invoice", parent: "/portal/invoices",
                                    dynamic: "invoice" },
  "/portal/estimates":      { label: "Estimates", parent: "/portal/home" },
  "/portal/estimates/:id":  { label: "Estimate", parent: "/portal/estimates",
                                    dynamic: "estimate" },
  "/portal/payments":       { label: "Payments", parent: "/portal/home" },
  "/portal/payment-method": { label: "Payment Method", parent: "/portal/home" },
  "/portal/payment-methods":{ label: "Payment Methods", parent: "/portal/home" },
  "/portal/documents":      { label: "Documents", parent: "/portal/home" },
  "/portal/messages":       { label: "Messages", parent: "/portal/home" },
  "/portal/chats":          { label: "Chat Threads", parent: "/portal/home" },
  "/portal/photos":         { label: "Photos", parent: "/portal/home" },
  "/portal/videos":         { label: "Videos", parent: "/portal/home" },
  "/portal/profile":        { label: "Profile", parent: "/portal/home" },
  "/portal/reviews":        { label: "Reviews", parent: "/portal/home" },
  "/portal/preferences":    { label: "Preferences", parent: "/portal/home" },
  "/portal/warranties":     { label: "Warranties", parent: "/portal/home" },
  "/portal/terms":          { label: "Terms of Service", parent: "/portal/home" },
  "/portal/referrals":      { label: "Referrals", parent: "/portal/home" },

  // ── Tech surfaces ─────────────────────────────────
  "/tech/dashboard":  { label: "Dashboard", parent: null },
  "/tech/schedule":   { label: "Schedule", parent: "/tech/dashboard" },
  "/tech/jobs":       { label: "Jobs", parent: "/tech/dashboard" },
  "/tech/jobs/:id":   { label: "Job", parent: "/tech/jobs",
                              dynamic: "job" },
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

/** True when the matched route key contains any dynamic segment
 *  (``:id``, ``:token``, ...).  AppBreadcrumbs uses this to know
 *  whether it should render the "..." skeleton until the page
 *  registers a resolved label via ``useSetDynamicCrumb``.
 *  Phase K2 · Feb-2026 */
export function routeIsDynamic(routeKey) {
  return typeof routeKey === "string" && routeKey.includes("/:");
}

/** Given the current pathname, walk up the parent chain and return
 *  [{label, path?, dynamic?}]. The last crumb has no path
 *  (current page). ``dynamic`` is the string handle from
 *  ROUTE_META that pages register against via
 *  ``useSetDynamicCrumb(handle, label)``. */
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
    // Override label from dynamic map if provided.  Two lookup
    // strategies to keep back-compat with the pre-K2 caller shape:
    //   1. Explicit route-key match: ``dynamic["/customers/:id"]``
    //   2. Handle match:              ``dynamic[meta.dynamic]``
    if (meta && dynamic[cur]) {
      label = dynamic[cur];
    } else if (meta && meta.dynamic && dynamic[meta.dynamic]) {
      label = dynamic[meta.dynamic];
    }
    chain.push({
      label,
      path: materialised,
      dynamic: meta ? meta.dynamic || null : null,
      routeKey: cur,
    });
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
