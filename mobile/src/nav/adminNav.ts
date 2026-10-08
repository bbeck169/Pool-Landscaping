/**
 * Phase (Feb-2026) — mobile admin navigation single-source-of-truth.
 *
 * Mirrors ``frontend/src/nav/adminNav.js`` (web ADMIN_NAV_V2) by
 * STRUCTURE — the mobile route paths are different from web paths in
 * a few places (e.g., ``/settings/integrations`` on web ↔ a nested
 * layout on mobile) so this file is hand-maintained, NOT derived at
 * runtime.
 *
 * Contract:
 *   { key, label, entries: [{ label, route, icon, tier, roles?,
 *                             webOnly?: boolean, testID }] }
 *
 * Tier meanings (Phase-B scope):
 *   "t1" — mobile screen exists at ``route`` → tap navigates directly.
 *   "t2" — no mobile screen yet → tap navigates to a shared
 *          ``ComingSoonPage`` stub carrying the ``route`` and
 *          ``label`` (title + copy pulled from search params).
 *   "t3" — web-only surface, deferred to future phases → tap opens
 *          the web URL via an in-app ``WebOnlyPage`` fallback.
 *
 * Every entry has an admin-like default role gate; individual entries
 * that require ``super_admin`` set ``roles: ["super_admin"]``.
 */

export type NavTier = "t1" | "t2" | "t3";
export type NavRole = "super_admin" | "admin" | "manager";

export type NavEntry = {
  label: string;
  route: string;         // route to push on tap (mobile route for t1/t2, web absolute path for t3)
  icon: string;          // Ionicons name
  tier: NavTier;
  roles?: NavRole[];     // if omitted → all three admin-like roles
  industry?: string;     // Phase D — if set, entry requires this industry in tenant.industries[]
  testID: string;
};

export type NavGroup = {
  key: string;
  label: string;
  entries: NavEntry[];
};

const A_ROLES: NavRole[] = ["super_admin", "admin", "manager"];
export function canSeeEntry(role: string | undefined, entry: NavEntry): boolean {
  const allowed = entry.roles ?? A_ROLES;
  return allowed.includes(role as NavRole);
}

// ── Quick-Access shortcut group (user request Feb-2026) ─────
//
// High-frequency admin actions promoted to the very top of the
// drawer. These entries INTENTIONALLY duplicate the same routes
// that appear in their canonical Operations group below — the
// double-listing is a UX shortcut, not a data bug.
export const QUICK_ACCESS: NavGroup = {
  key: "quick_access",
  label: "Quick Access",
  entries: [
    { label: "Schedule",  route: "/schedule",  icon: "calendar-outline",       tier: "t1", testID: "drawer-nav-quick-schedule" },
    { label: "Dispatch",  route: "/dispatch",  icon: "car-outline",            tier: "t1", testID: "drawer-nav-quick-dispatch" },
    { label: "Team",      route: "/team",      icon: "people-outline",         tier: "t1", testID: "drawer-nav-quick-team" },
  ],
};

// ── Canonical 8-group tree (mirrors web ADMIN_NAV_V2 order) ──

export const ADMIN_NAV: NavGroup[] = [
  {
    key: "finance",
    label: "Finance",
    entries: [
      { label: "AI CFO",              route: "/cfo",                          icon: "trending-up-outline",     tier: "t1", testID: "drawer-nav-cfo" },
      { label: "Income by Category",  route: "/income-by-category",           icon: "pie-chart-outline",       tier: "t1", testID: "drawer-nav-income-by-category" },
      { label: "Invoices",            route: "/invoices",                     icon: "receipt-outline",         tier: "t1", testID: "drawer-nav-invoices" },
      { label: "Payments",            route: "/payments",                     icon: "card-outline",            tier: "t1", testID: "drawer-nav-payments" },
      { label: "Auto-billing",        route: "/auto-billing",                 icon: "repeat-outline",          tier: "t1", testID: "drawer-nav-auto-billing" },
      { label: "Recurring Jobs",      route: "/finance/recurring-jobs",       icon: "calendar-outline",        tier: "t1", testID: "drawer-nav-recurring-jobs" },
      { label: "Autobilling Runs",    route: "/finance/autobilling-runs",     icon: "sync-outline",            tier: "t1", testID: "drawer-nav-autobilling-runs" },
      { label: "Master Invoices",     route: "/finance/master-invoices",      icon: "albums-outline",          tier: "t1", testID: "drawer-nav-master-invoices" },
      { label: "Vendor Bills",        route: "/finance/vendor-bills",         icon: "cash-outline",            tier: "t1", testID: "drawer-nav-vendor-bills" },
      { label: "Income Categories",   route: "/settings/income-categories",   icon: "pricetag-outline",        tier: "t2", testID: "drawer-nav-income-categories" },
      { label: "Service Categories",  route: "/settings/service-categories",  icon: "layers-outline",          tier: "t2", testID: "drawer-nav-service-categories" },
      { label: "Check Writer",            route: "/admin/checks",                 icon: "print-outline",      tier: "t3", testID: "drawer-nav-t3-checks" },
      { label: "Dunning Queue",           route: "/admin/dunning/queue",          icon: "hourglass-outline",  tier: "t3", testID: "drawer-nav-t3-dunning" },
      { label: "Warranty Plans",          route: "/admin/warranties/plans",       icon: "shield-outline",     tier: "t3", testID: "drawer-nav-t3-warranties" },
    ],
  },
  {
    key: "ai_employees",
    label: "AI Employees",
    entries: [
      { label: "AI Employees Hub",   route: "/ai-employees",         icon: "sparkles-outline",   tier: "t1", testID: "drawer-nav-ai-employees" },
      { label: "AI Brain",           route: "/settings/ai-brain",    icon: "hardware-chip-outline", tier: "t1", testID: "drawer-nav-ai-brain" },
      { label: "Soshie Hub",         route: "/soshie",               icon: "megaphone-outline",  tier: "t1", testID: "drawer-nav-soshie" },
      { label: "Atlas SEO Agent",    route: "/admin/seo/atlas",      icon: "compass-outline",    tier: "t1", testID: "drawer-nav-atlas" },
      { label: "Communications",     route: "/communications",       icon: "mail-outline",       tier: "t1", testID: "drawer-nav-communications" },
    ],
  },
  {
    key: "marketing",
    label: "Marketing",
    entries: [
      { label: "Studio",             route: "/marketing",                       icon: "megaphone-outline",    tier: "t1", testID: "drawer-nav-marketing" },
      { label: "Templates",          route: "/marketing/templates",             icon: "file-tray-full-outline", tier: "t1", testID: "drawer-nav-marketing-templates" },
      { label: "Notifications",      route: "/notifications",                   icon: "notifications-outline",tier: "t1", testID: "drawer-nav-notifications" },
      { label: "Forms",              route: "/forms",                           icon: "clipboard-outline",    tier: "t1", testID: "drawer-nav-forms" },
      { label: "SEO Hub",            route: "/seo",                             icon: "search-outline",       tier: "t1", testID: "drawer-nav-seo" },
      { label: "Site Auditor",       route: "/admin/seo/audits",                icon: "shield-checkmark-outline", tier: "t1", testID: "drawer-nav-seo-audits" },
      { label: "Content Scorer",     route: "/admin/seo/content-scorer",        icon: "podium-outline",       tier: "t1", testID: "drawer-nav-content-scorer" },
      { label: "Rank Heatmap",       route: "/admin/seo/rank-heatmap",          icon: "grid-outline",         tier: "t1", testID: "drawer-nav-rank-heatmap" },
      { label: "Topical Map",        route: "/admin/seo/topical-map",           icon: "git-branch-outline",   tier: "t1", testID: "drawer-nav-topical-map" },
      { label: "LLM Visibility",     route: "/admin/seo/llm-visibility",        icon: "eye-outline",          tier: "t1", testID: "drawer-nav-llm-visibility" },
      { label: "Website Studio",     route: "/admin/seo/studio",                icon: "brush-outline",        tier: "t1", testID: "drawer-nav-seo-studio" },
      { label: "White-Label Reports",route: "/admin/seo/reports",               icon: "document-text-outline",tier: "t1", testID: "drawer-nav-seo-reports" },
      { label: "GBP Hub",            route: "/gbp",                             icon: "business-outline",     tier: "t1", testID: "drawer-nav-gbp" },
      { label: "Notification Prefs", route: "/settings/notifications",          icon: "options-outline",      tier: "t2", testID: "drawer-nav-notification-prefs" },
      { label: "Referral Analytics", route: "/admin/referrals/analytics",       icon: "share-social-outline", tier: "t2", testID: "drawer-nav-referral-analytics" },
      { label: "Referral Tiers",     route: "/admin/referrals/settings",        icon: "trophy-outline",       tier: "t2", testID: "drawer-nav-referral-tiers" },
      { label: "Marketing Campaigns", route: "/marketing/campaigns",            icon: "flag-outline",         tier: "t3", testID: "drawer-nav-t3-campaigns" },
      { label: "Social Composer",     route: "/social/composer",                icon: "chatbubbles-outline",  tier: "t3", testID: "drawer-nav-t3-social" },
      { label: "SEO Articles",        route: "/seo/articles",                   icon: "reader-outline",       tier: "t3", testID: "drawer-nav-t3-seo-articles" },
      // NAV-REORG — legacy standalone group folded into marketing.
      { label: "Reviews Dashboard",  route: "/admin/reviews",            icon: "star-outline",     tier: "t2", testID: "drawer-nav-reviews" },
      { label: "Review Requests",    route: "/admin/reviews/requests",   icon: "send-outline",     tier: "t2", testID: "drawer-nav-reviews-requests" },
      { label: "Review Platforms",   route: "/admin/reviews/platforms",  icon: "logo-google",      tier: "t2", testID: "drawer-nav-reviews-platforms" },
      { label: "Review Widget",      route: "/admin/reviews/widget",     icon: "cube-outline",     tier: "t2", testID: "drawer-nav-reviews-widget" },
    ],
  },
  {
    key: "operations",
    label: "Operations",
    entries: [
      { label: "Operations Hub",     route: "/operations",           icon: "grid-outline",         tier: "t1", testID: "drawer-nav-operations" },
      { label: "Schedule",           route: "/schedule",             icon: "calendar-outline",     tier: "t1", testID: "drawer-nav-schedule" },
      { label: "Dispatch Board",     route: "/dispatch",             icon: "car-outline",          tier: "t1", testID: "drawer-nav-dispatch" },
      { label: "Workstream",         route: "/workstream",           icon: "pulse-outline",        tier: "t1", testID: "drawer-nav-workstream" },
      { label: "Team",               route: "/team",                 icon: "people-outline",       tier: "t1", testID: "drawer-nav-team" },
      { label: "Crews",              route: "/crews",                icon: "people-circle-outline",tier: "t2", testID: "drawer-nav-crews" },
      { label: "Timesheets",         route: "/timesheets",           icon: "clipboard-outline",    tier: "t1", testID: "drawer-nav-timesheets" },
      { label: "Time Clock",         route: "/time-clock",           icon: "time-outline",         tier: "t1", testID: "drawer-nav-time-clock" },
      { label: "Coverage",           route: "/coverage",             icon: "map-outline",          tier: "t1", testID: "drawer-nav-coverage" },
      { label: "Check-ins",          route: "/checkins",             icon: "location-outline",     tier: "t1", testID: "drawer-nav-checkins" },
      { label: "Job Timers",         route: "/job-timers",           icon: "stopwatch-outline",    tier: "t1", testID: "drawer-nav-job-timers" },
      { label: "Avg Job Time",       route: "/avg-job-time",         icon: "bar-chart-outline",    tier: "t1", testID: "drawer-nav-avg-job-time" },
      { label: "Log History",        route: "/log-history",          icon: "list-outline",         tier: "t1", testID: "drawer-nav-log-history" },
      { label: "Maintenance",        route: "/maintenance",          icon: "construct-outline",    tier: "t1", testID: "drawer-nav-maintenance" },
      { label: "Pool Service",       route: "/pool-service",         icon: "water-outline",        tier: "t1", industry: "pools", testID: "drawer-nav-pool-service" },
      { label: "Equipment",          route: "/equipment",            icon: "hammer-outline",       tier: "t1", testID: "drawer-nav-equipment" },
      { label: "Price Book",         route: "/price-book",           icon: "pricetags-outline",    tier: "t1", testID: "drawer-nav-price-book" },
      { label: "Handbook",           route: "/handbook",             icon: "book-outline",         tier: "t1", testID: "drawer-nav-handbook" },
      { label: "Time Off",           route: "/time-off",             icon: "leaf-outline",         tier: "t1", testID: "drawer-nav-time-off" },
      { label: "Time Off Approvals", route: "/admin/time-off",       icon: "checkmark-done-outline", tier: "t2", testID: "drawer-nav-time-off-admin" },
      { label: "Landscape AI",       route: "/landscape",            icon: "leaf-outline",         tier: "t1", industry: "landscaping", testID: "drawer-nav-landscape" },
      { label: "CAD Studio",         route: "/cad",                  icon: "cube-outline",         tier: "t1", testID: "drawer-nav-cad" },
      { label: "Satellite Measure",  route: "/measure",              icon: "resize-outline",       tier: "t1", testID: "drawer-nav-measure" },
      { label: "Virtual Bid",        route: "/virtual-bid",          icon: "cash-outline",         tier: "t1", testID: "drawer-nav-virtual-bid" },
      { label: "Weather",            route: "/weather",              icon: "partly-sunny-outline", tier: "t2", testID: "drawer-nav-weather" },
      { label: "Tenant Brand",       route: "/settings/tenant",      icon: "color-palette-outline",tier: "t1", testID: "drawer-nav-tenant-brand" },
      { label: "Access Settings",    route: "/access-settings",      icon: "shield-outline",       tier: "t1", testID: "drawer-nav-access-settings" },
      { label: "Business Card",      route: "/settings/business-card", icon: "card-outline",       tier: "t1", testID: "drawer-nav-business-card" },
      { label: "Website SEO",        route: "/settings/website-seo", icon: "globe-outline",        tier: "t1", testID: "drawer-nav-website-seo" },
      // Feb-2026 · K55.a — Homeworks importer nav entry removed as
      // part of the SuperCool + HomeWorks integration sunset.
      { label: "Local SEO",          route: "/settings/local-seo",   icon: "location-outline",     tier: "t1", testID: "drawer-nav-local-seo" },
      { label: "Terms",              route: "/settings/terms",       icon: "document-outline",     tier: "t2", testID: "drawer-nav-terms" },
      { label: "Legal Docs",         route: "/settings/legal",       icon: "document-text-outline",tier: "t2", testID: "drawer-nav-legal-docs" },
      { label: "Maps",               route: "/settings/maps",        icon: "navigate-outline",     tier: "t2", testID: "drawer-nav-maps-settings" },
      { label: "RingCentral",        route: "/settings/ringcentral", icon: "call-outline",         tier: "t2", testID: "drawer-nav-ringcentral" },
      { label: "Chemical Products",  route: "/admin/chemicals",      icon: "flask-outline",        tier: "t2", testID: "drawer-nav-chemicals" },
      { label: "Appointments",       route: "/admin/appointments",   icon: "calendar-number-outline", tier: "t2", testID: "drawer-nav-appointments" },
      { label: "Auto-Dispatch",      route: "/admin/dispatch",       icon: "flash-outline",        tier: "t3", testID: "drawer-nav-t3-auto-dispatch" },
      { label: "Routes",             route: "/routes",               icon: "trail-sign-outline",   tier: "t3", testID: "drawer-nav-t3-routes" },
      { label: "Inventory",          route: "/admin/inventory",      icon: "cube-outline",         tier: "t3", testID: "drawer-nav-t3-inventory" },
      { label: "Business OS",        route: "/os/dashboard",         icon: "grid-outline",         tier: "t3", testID: "drawer-nav-t3-business-os" },
      { label: "Tenants (super)",    route: "/tenants",              icon: "server-outline",       tier: "t2", roles: ["super_admin"], testID: "drawer-nav-tenants" },
    ],
  },
  {
    key: "customers",
    label: "Customers",
    entries: [
      { label: "Customers",          route: "/customers",            icon: "people-outline",       tier: "t1", testID: "drawer-nav-customers" },
      { label: "Leads",              route: "/leads",                icon: "flag-outline",         tier: "t1", testID: "drawer-nav-leads" },
      { label: "Deals (Kanban)",     route: "/deals",                icon: "trending-up-outline",  tier: "t1", testID: "drawer-nav-deals" },
      { label: "AI Estimator",       route: "/ai-estimator",         icon: "calculator-outline",   tier: "t1", testID: "drawer-nav-ai-estimator" },
      { label: "Quotes",             route: "/quotes",               icon: "document-attach-outline", tier: "t1", testID: "drawer-nav-quotes" },
      { label: "Estimator",          route: "/estimator",            icon: "calculator-outline",   tier: "t1", testID: "drawer-nav-estimator" },
      { label: "D2D Canvassing",     route: "/d2d",                  icon: "walk-outline",         tier: "t1", testID: "drawer-nav-d2d" },
      { label: "Digital Card",       route: "/card",                 icon: "card-outline",         tier: "t1", testID: "drawer-nav-card" },
      { label: "Customer Tags",      route: "/admin/tags",           icon: "pricetag-outline",     tier: "t2", testID: "drawer-nav-tags" },
      { label: "Service Reports",    route: "/admin/service-reports", icon: "document-text-outline",tier: "t2", testID: "drawer-nav-service-reports" },
    ],
  },
  {
    key: "reports",
    label: "Reports",
    entries: [
      { label: "Dashboard",          route: "/",                     icon: "speedometer-outline",  tier: "t1", testID: "drawer-nav-dashboard" },
      { label: "Reports Hub",        route: "/reports",              icon: "bar-chart-outline",    tier: "t1", testID: "drawer-nav-reports" },
      { label: "Forecast",           route: "/reports/forecast",     icon: "trending-up-outline",  tier: "t1", testID: "drawer-nav-forecast" },
      { label: "Revenue by Service", route: "/reports/revenue-by-service", icon: "podium-outline", tier: "t1", testID: "drawer-nav-revenue-by-service" },
      { label: "Access History",     route: "/access-history",       icon: "time-outline",         tier: "t1", testID: "drawer-nav-access-history" },
      // Phase 36 · Feb-2026 — CFO deep-dive parity (P1.2). Each hits
      // a distinct /api/cfo/* endpoint; they're grouped here because
      // finance ops is already busy after Phase 35.
      { label: "CFO · AP Aging",     route: "/cfo/ap-aging",         icon: "wallet-outline",       tier: "t1", testID: "drawer-nav-cfo-ap-aging" },
      { label: "CFO · Cash Forecast",route: "/cfo/forecast",         icon: "trending-up-outline",  tier: "t1", testID: "drawer-nav-cfo-forecast" },
      { label: "CFO · Anomalies",    route: "/cfo/anomalies",        icon: "pulse-outline",        tier: "t1", testID: "drawer-nav-cfo-anomalies" },
      { label: "CFO · Payroll",      route: "/cfo/payroll",          icon: "people-outline",       tier: "t1", testID: "drawer-nav-cfo-payroll" },
      { label: "CFO · Price Increase",route:"/cfo/price-increase",   icon: "arrow-up-circle-outline",tier: "t1", testID: "drawer-nav-cfo-price-increase" },
      { label: "Check-in Moderation", route: "/admin/moderation/checkins", icon: "checkmark-done-outline", tier: "t2", testID: "drawer-nav-moderation-checkins" },
      { label: "Client Errors",       route: "/admin/diagnostics/errors",  icon: "alert-circle-outline",   tier: "t2", testID: "drawer-nav-diagnostics-errors" },
      { label: "Business Summary",   route: "/reports/business-summary", icon: "stats-chart-outline",  tier: "t3", testID: "drawer-nav-t3-business-summary" },
      // Phase 54g-B · Feb-2026 — Supplier Syncs analytics.
      // Points at the dedicated mobile screen at
      // ``app/reports/supplier-syncs.tsx`` (parity with the web
      // ``/reports/supplier-syncs`` dashboard). Role gate omitted →
      // default admin-like roles (super_admin + admin + manager),
      // matching the web ``AdminOrManagerForSuppliers`` guard.
      { label: "Supplier Syncs",     route: "/reports/supplier-syncs",   icon: "refresh-circle-outline", tier: "t1", testID: "drawer-nav-supplier-syncs" },
      // Phase 54h · Aug-2026 — Wholesale Suppliers credentials page.
      // Sibling of the Supplier Syncs analytics row above — this one
      // opens the credentials + connection-test surface. Native mobile
      // screen already exists at ``mobile/app/settings/suppliers.tsx``
      // so this is a t1 entry (direct native navigation, not a
      // ComingSoon stub). Default admin-like role gate (super_admin +
      // admin + manager) matches the web ``AdminOrManagerForSuppliers``
      // route guard.
      { label: "Wholesale Suppliers", route: "/settings/suppliers",      icon: "cube-outline",           tier: "t1", testID: "drawer-nav-wholesale-suppliers" },
      // Phase 56-a.5 · Aug-2026 — Pricebook Suppliers admin drawer stub.
      // ComingSoon (t2) — native mobile screen is a TODO for
      // Phase 56-mobile-B; web-side lands the full CRUD at
      // ``/settings/pricebook-suppliers``. Role gate is tighter than
      // Wholesale Suppliers — ``super_admin + admin`` only per
      // preflight §3 (no manager).
      // TODO(Phase 56-mobile-B): swap to a t1 native screen.
      { label: "Pricebook Suppliers", route: "/settings/pricebook-suppliers", icon: "storefront-outline",     tier: "t2", roles: ["super_admin", "admin"], testID: "drawer-nav-pricebook-suppliers" },
      // Phase 56-c · Aug-2026 — Pricebook Cost Comparison report stub.
      // TODO(Phase 56c-mobile-B): swap to a native t1 screen.
      { label: "Cost Comparison",     route: "/admin/reports/pricebook-cost-comparison", icon: "analytics-outline",     tier: "t2", testID: "drawer-nav-pricebook-cost-comparison" },
      // Phase 56-d · Aug-2026 — Supplier spend + margin stub.
      // TODO(Phase 56d-mobile-B): swap to a native t1 screen.
      { label: "Supplier Spend & Margin", route: "/admin/reports/supplier-spend", icon: "trending-up-outline", tier: "t2", roles: ["super_admin", "admin"], testID: "drawer-nav-supplier-spend" },
    ],
  },
  {
    key: "communications",
    label: "Communications",
    entries: [
      { label: "Email Builder",      route: "/admin/comms/email",       icon: "mail-open-outline",  tier: "t2", testID: "drawer-nav-comms-email" },
      { label: "SMS Builder",        route: "/admin/comms/sms",         icon: "chatbubble-outline", tier: "t2", testID: "drawer-nav-comms-sms" },
      { label: "Templates",          route: "/admin/comms/templates",   icon: "file-tray-outline",  tier: "t2", testID: "drawer-nav-comms-templates" },
      { label: "Automations",        route: "/admin/comms/automations", icon: "flash-outline",      tier: "t2", testID: "drawer-nav-comms-automations" },
      { label: "Sends History",      route: "/admin/comms/sends",       icon: "paper-plane-outline",tier: "t2", testID: "drawer-nav-comms-sends" },
    ],
  },
  // Phase 37 · Feb-2026 — Business OS parity (P1.3). New top-level
  // group; mirrors the web `/os/*` surfaces.
  {
    key: "business_os",
    label: "Business OS",
    entries: [
      { label: "OS Hub",       route: "/os",              icon: "apps-outline",           tier: "t1", testID: "drawer-nav-os-hub" },
      { label: "SOPs",         route: "/os/sops",         icon: "document-text-outline",  tier: "t1", testID: "drawer-nav-os-sops" },
      { label: "Roles",        route: "/os/roles",        icon: "people-outline",         tier: "t1", testID: "drawer-nav-os-roles" },
      { label: "Scorecards",   route: "/os/scorecards",   icon: "trophy-outline",         tier: "t1", testID: "drawer-nav-os-scorecards" },
      { label: "Huddle",       route: "/huddle",          icon: "chatbubbles-outline",    tier: "t1", testID: "drawer-nav-os-huddle" },
      { label: "Lean Boards",  route: "/os/leanboards",   icon: "grid-outline",           tier: "t1", testID: "drawer-nav-os-leanboards" },
      { label: "Sprints",      route: "/os/sprints",      icon: "flag-outline",           tier: "t1", testID: "drawer-nav-os-sprints" },
      { label: "Lana AI",      route: "/os/lana",         icon: "sparkles-outline",       tier: "t1", testID: "drawer-nav-os-lana" },
      { label: "Templates Library", route: "/(app)/templates", icon: "library-outline",  tier: "t1", testID: "drawer-nav-os-templates-library" },
    ],
  },
];

// ── Phase D — Industry gate helper ─────────────────────────────────
//
// Mirrors ``frontend/src/nav/adminNav.js::filterNavByIndustries``.
// Entries with an ``industry`` tag are hidden unless the tenant's
// ``industries[]`` includes that slug.
//
// Fail-open: if ``industries`` is empty or non-array, all entries pass
// (prevents a blank drawer during migration rollout).
export function filterNavByIndustries(
  entries: NavEntry[],
  industries: string[],
): NavEntry[] {
  if (!Array.isArray(industries) || industries.length === 0) return entries;
  return entries.filter((e) => !e.industry || industries.includes(e.industry));
}

// Convenience — flat list for validation/tests.
export const FLAT_ENTRIES: NavEntry[] = [
  ...QUICK_ACCESS.entries,
  ...ADMIN_NAV.flatMap((g) => g.entries),
];
