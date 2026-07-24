/**
 * useBreadcrumbs — derives breadcrumb trail from the current expo-router pathname.
 *
 * Returns an array of { label, route? } items. The last item (current page)
 * has no route. Root-level screens return [] so the Breadcrumbs component
 * renders nothing.
 */
import { usePathname } from "expo-router";
import { useAuth } from "@/src/auth";

export type BreadcrumbItem = {
  label: string;
  route?: string;
};

/* ── Friendly labels for known route segments ────────────────────── */
const LABELS: Record<string, string> = {
  // Tabs / primary
  index: "Dashboard",
  customers: "Customers",
  schedule: "Schedule",
  calendar: "Calendar",
  jobs: "Jobs",
  quotes: "Quotes",
  more: "More",
  tools: "Tools",
  huddle: "Huddle",
  assets: "Equipment",
  today: "Today",
  calculators: "Calculators",
  "before-after": "Before & After",
  "property-lookup": "Property Lookup",
  "ai-estimator": "AI Estimator",
  "new-lead": "New Lead",
  onboarding: "Onboarding",
  "onboarding-checklist": "Onboarding Checklist",
  chat: "Chat",
  d2d: "Door-to-Door",
  directories: "Directories",
  instaquote: "InstaQuote",
  instaschedule: "InstaSchedule",

  // Dispatch
  dispatch: "Dispatch",
  board: "Board",
  weather: "Weather",

  // Payroll
  payroll: "Payroll",
  batch: "Batch",

  // Comms
  comms: "Communications",
  templates: "Templates",
  sends: "Sends",
  automations: "Automations",
  "test-send": "Test Send",

  // Reviews
  reviews: "Reviews",
  requests: "Requests",
  leaderboard: "Leaderboard",
  platforms: "Platforms",
  widget: "Widget",
  recent: "Recent",

  // Credits / Deals
  credits: "AI Credits",
  deals: "Deals",
  new: "New",

  // Time clock
  "time-clock": "Time Clock",
  "landscape-time-clock": "Landscape Clock",

  // Settings
  settings: "Settings",
  "auto-clockin": "Auto Clock-In",
  lidar: "LiDAR",
  widgets: "Widgets",
  "promo-codes": "Promo Codes",
  tenant: "Tenant Settings",

  // Admin
  admin: "Admin",
  referrals: "Referrals",
  seo: "SEO",
  atlas: "Atlas",
  audits: "Audits",
  "content-scorer": "Content Scorer",
  "llm-visibility": "LLM Visibility",
  otto: "Otto",
  "rank-heatmap": "Rank Heatmap",
  reports: "Reports",
  studio: "Studio",
  "topical-map": "Topical Map",

  // Team
  team: "Team",
  technician: "Technician",
  technicians: "Technicians",

  // Marketing
  marketing: "Marketing",
  analytics: "Analytics",
  "review-requests": "Review Requests",
  segments: "Segments",
  sequences: "Sequences",
  suppressions: "Suppressions",

  // Detail screens
  customer: "Customer",
  job: "Job",
  invoice: "Invoice",
  quote: "Quote",
  "estimate-view": "Estimate",
  checklist: "Checklist",
  communication: "Communication",
  communications: "Communications",
  "service-report": "Service Report",
  "ai-chat": "AI Chat",
  estimator: "Estimator",
  handbook: "Handbook",
  tests: "Tests",
  quiz: "Quiz",
  leads: "Leads",
  cfo: "CFO",
  cad: "CAD",
  editor: "Editor",
  gbp: "Google Business",
  tracking: "Tracking",
  workstream: "Workstream",
  "work-stream": "Work Stream",
  dunning: "Dunning",
  queue: "Queue",
  inventory: "Inventory",
  "avg-job-time": "Avg Job Time",
  "business-reports": "Business Reports",
  "income-by-category": "Income by Category",
  "income-categories": "Income Categories",
  "job-timers": "Job Timers",
  "log-history": "Log History",
  "access-history": "Access History",
  "access-settings": "Access Settings",
  "auto-billing": "Auto Billing",
  campaigns: "Campaigns",
  card: "Card",
  checkins: "Check-ins",
  coverage: "Coverage",
  equipment: "Equipment",
  forms: "Forms",
  maintenance: "Maintenance",
  "pool-service": "Pool Service",
  notifications: "Notifications",
  payments: "Payments",
  "payment-complete": "Payment Complete",
  "price-book": "Price Book",
  "rank-grid": "Rank Grid",
  "request-service": "Request Service",
  social: "Social",
  timesheets: "Timesheets",
  "virtual-bid": "Virtual Bid",
  landscape: "Landscape",
  measure: "Measure",
  invoices: "Invoices",
  "ai-employees": "AI Employees",

  // Portal
  portal: "Portal",
  home: "Home",
  estimates: "Estimates",
  messages: "Messages",
  profile: "Profile",
  "payment-method": "Payment Method",
  services: "Services",
  book: "Book Service",
  appointments: "Appointments",
  "add-card": "Add Card",
  chats: "Chats",
  documents: "Documents",
  photos: "Photos",
  videos: "Videos",
};

/** True if a segment looks like a dynamic ID (UUID, mongo-id, or pure digits). */
function isDynamicSegment(s: string): boolean {
  if (/^[0-9a-f]{8}-[0-9a-f]{4}/.test(s)) return true; // UUID
  if (/^[0-9a-f]{24}$/.test(s)) return true;             // Mongo ObjectId
  if (/^\d+$/.test(s)) return true;                       // Numeric
  if (s.length > 20 && /^[a-z0-9-]+$/.test(s)) return true; // Long slug
  return false;
}

function humanize(s: string): string {
  return s
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ── Root screens (no breadcrumbs) ───────────────────────────────── */
const ROOT_PATHS = new Set([
  "/",
  "/index",
  "/portal/home",
  "/schedule/calendar",
  "/jobs",
  "/more",
  "/tools",
  "/customers",
  "/quotes",
  "/today",
  "/login",
  "/signup",
]);

function isRootScreen(pathname: string): boolean {
  // Strip the (app) group prefix for comparison
  const clean = pathname.replace(/\/\(app\)/g, "");
  return ROOT_PATHS.has(clean) || clean === "";
}

/* ── Build route string from segments ────────────────────────────── */
function buildRoute(segments: string[], upTo: number, isPortal: boolean): string {
  if (upTo === 0) return isPortal ? "/portal/home" : "/(app)";
  const path = segments.slice(0, upTo + 1).join("/");
  // For portal routes, prefix with /portal
  if (isPortal) return "/portal/" + path;
  // For routes that live outside (app) group
  const outsideApp = [
    "customer", "job", "invoice", "quote", "team", "technician",
    "settings", "admin", "marketing", "leads", "estimator",
    "estimate-view", "communication", "d2d", "seo", "workstream",
    "tracking", "cad", "gbp", "handbook",
  ];
  if (outsideApp.includes(segments[0])) return "/" + path;
  // Default: inside (app) group
  return "/(app)/" + path;
}

export function useBreadcrumbs(currentTitle?: string): BreadcrumbItem[] {
  const pathname = usePathname();
  const { user } = useAuth();

  if (!pathname || isRootScreen(pathname)) return [];

  const role = String((user as any)?.role || "");
  const isCustomer = role === "customer";

  // Strip leading slash, group names like (app)
  const raw = pathname.replace(/^\//g, "").replace(/\(app\)\/?/g, "");
  const segments = raw.split("/").filter(Boolean);

  if (segments.length === 0) return [];

  // Determine if this is a portal route
  const isPortal = segments[0] === "portal";
  const workSegments = isPortal ? segments.slice(1) : segments;

  if (workSegments.length === 0) return [];

  // Build the trail
  const items: BreadcrumbItem[] = [];

  // Root crumb
  if (isPortal || isCustomer) {
    items.push({ label: "Home", route: "/portal/home" });
  } else {
    const techRoot = role === "technician";
    items.push({
      label: techRoot ? "Schedule" : "Dashboard",
      route: techRoot ? "/(app)/schedule/calendar" : "/(app)",
    });
  }

  // Intermediate segments
  for (let i = 0; i < workSegments.length - 1; i++) {
    const seg = workSegments[i];
    if (isDynamicSegment(seg)) continue; // skip IDs in the middle
    const label = LABELS[seg] || humanize(seg);
    const route = buildRoute(workSegments, i, isPortal);
    items.push({ label, route });
  }

  // Current segment (no route — it's the current page)
  const lastSeg = workSegments[workSegments.length - 1];
  const lastLabel = isDynamicSegment(lastSeg)
    ? currentTitle || LABELS[workSegments[workSegments.length - 2]] || "Detail"
    : currentTitle || LABELS[lastSeg] || humanize(lastSeg);
  items.push({ label: lastLabel });

  // Deduplicate adjacent items with the same label
  const deduped: BreadcrumbItem[] = [items[0]];
  for (let i = 1; i < items.length; i++) {
    if (items[i].label !== items[i - 1].label) deduped.push(items[i]);
  }

  // If only 1 item (just the root label repeated), return empty
  if (deduped.length <= 1) return [];

  return deduped;
}
