/**
 * Phase 42 · Tools Hub / Phase 43 · Global Menu — shared section IA.
 *
 * Single source of truth for the 6-category admin IA (Phase 35) and the
 * 4-section tech IA. Both the Tools tab and the global dropdown sheet
 * import from here so a future re-shuffle doesn't drift between the two
 * surfaces.
 *
 * DO NOT re-order or re-assign tools without updating this file's
 * doc-comment — it's the source of truth for Phase 35's frozen IA.
 */
import type { ToolCardTile } from "./ToolCard";

export type ToolSection = {
  key: string;
  title: string;
  tiles: ToolCardTile[];
};

export const TECH_SECTIONS: ToolSection[] = [
  {
    key: "daily",
    title: "Daily Work",
    tiles: [
      { key: "workstream", icon: "briefcase-outline", label: "Workstream", desc: "My jobs · pill status · photos", route: "/(app)/jobs" },
      { key: "schedule", icon: "today-outline", label: "Schedule", desc: "Day / Week / Month calendar", route: "/(app)/schedule/calendar" },
      { key: "d2d", icon: "footsteps-outline", label: "D2D Canvassing", desc: "Log knocks & book leads", route: "/(app)/d2d" },
      { key: "time-clock", icon: "time-outline", label: "Time Clock", desc: "Clock in / out, breaks, mileage", route: "/(app)/time-clock" },
      { key: "landscape-time-clock", icon: "leaf-outline", label: "Landscape Time Clock", desc: "GPS clock for landscape crew", route: "/(app)/landscape-time-clock" },
      { key: "huddle", icon: "chatbubbles-outline", label: "Daily Huddle", desc: "Post yesterday / today / blockers", route: "/(app)/huddle" },
    ],
  },
  {
    key: "job",
    title: "On the Job",
    tiles: [
      { key: "calculators", icon: "flask-outline", label: "Pool Calculators", desc: "Dosing · Volume · Salt · LSI", route: "/(app)/calculators" },
      { key: "inventory", icon: "layers-outline", label: "Inventory", desc: "Truck stock & re-order alerts", route: "/(app)/inventory" },
      { key: "equipment", icon: "cube-outline", label: "My Equipment", desc: "Assets assigned to me", route: "/(app)/assets" },
      { key: "new-lead", icon: "magnet-outline", label: "New Lead", desc: "Log a walk-in or referral", route: "/(app)/new-lead" },
      { key: "before-after", icon: "images-outline", label: "Before / After", desc: "Share the wow shot", route: "/(app)/before-after" as any },
      { key: "chat", icon: "chatbubbles-outline", label: "Team Chat", desc: "DMs + channels", route: "/(app)/chat" as any },
    ],
  },
  {
    key: "records",
    title: "My Records",
    tiles: [
      { key: "onboarding", icon: "clipboard-outline", label: "My Onboarding", desc: "Checklist steps assigned to me", route: "/(app)/onboarding/mine" },
      { key: "tests", icon: "school-outline", label: "Tests", desc: "Training modules & CPO prep", route: "/(app)/tests" },
      { key: "templates", icon: "library-outline", label: "Templates", desc: "Fill-in-the-blank forms & docs", route: "/(app)/templates" },
      { key: "d2d-leaderboard", icon: "trophy-outline", label: "D2D Leaderboard", desc: "See where your knocks rank", route: "/d2d/leaderboard" },
      { key: "card", icon: "id-card-outline", label: "Business Card", desc: "Share your digital card", route: "/card" },
      { key: "service-tracking", icon: "filter-outline", label: "Service Tracking", desc: "Filter & salt cell trackers", route: "/tracking" as any },
    ],
  },
  {
    key: "account",
    title: "Account",
    tiles: [
      { key: "profile", icon: "person-outline", label: "Profile", desc: "Name, email, sign out", route: "/(app)/more" },
      { key: "auto-clockin", icon: "location-outline", label: "Auto Clock-In", desc: "Geofence settings", route: "/(app)/settings/auto-clockin" },
    ],
  },
];

export const ADMIN_SECTIONS: ToolSection[] = [
  {
    key: "adm-finance",
    title: "Finance",
    tiles: [
      { key: "cfo", icon: "trending-up-outline", label: "AI CFO", desc: "Revenue · expenses · cash · AR", route: "/(app)/cfo" },
      { key: "checks", icon: "document-text-outline", label: "Check Register", desc: "Write checks, batch payroll", route: "/(app)/checks/register" },
      { key: "payroll-batch", icon: "cash-outline", label: "Payroll Batch + CSV", desc: "Batch checks & payroll import", route: "/(app)/payroll/batch" },
      { key: "dunning", icon: "mail-open-outline", label: "Dunning Queue", desc: "Overdue invoices workflow", route: "/(app)/dunning/queue" },
    ],
  },
  {
    key: "adm-ai-employees",
    title: "AI Employees",
    tiles: [
      { key: "ai-cfo-qna", icon: "chatbubbles-outline", label: "AI CFO Q&A", desc: "Ask the CFO — natural language", route: "/(app)/cfo" },
    ],
  },
  {
    key: "adm-marketing",
    title: "Marketing",
    tiles: [
      { key: "marketing-studio", icon: "megaphone-outline", label: "Marketing Studio", desc: "Campaigns, sequences, reviews", route: "/marketing" as any },
      { key: "comms", icon: "mail-outline", label: "Communications", desc: "Templates, automations, sends", route: "/(app)/comms" },
      { key: "reviews", icon: "star-outline", label: "Reviews", desc: "Requests, ratings, widget & sync", route: "/(app)/reviews" as any },
      { key: "ai-credits", icon: "sparkles-outline", label: "AI Credits", desc: "Balance & transactions", route: "/(app)/credits" as any },
      { key: "deals", icon: "git-branch-outline", label: "Deals", desc: "Pipeline · stages · won/lost", route: "/(app)/deals" as any },
      { key: "ai-estimator", icon: "bulb-outline", label: "AI Estimator", desc: "Generate estimates from photos + description", route: "/(app)/ai-estimator" as any },
      { key: "before-after", icon: "images-outline", label: "Before / After", desc: "AI-composed share cards", route: "/(app)/before-after" as any },
      { key: "instaquote", icon: "storefront-outline", label: "InstaQuote", desc: "Public self-quote submissions", route: "/(app)/instaquote" as any },
      { key: "instaschedule", icon: "calendar-outline", label: "InstaSchedule", desc: "Public self-book bookings", route: "/(app)/instaschedule" as any },
      { key: "directories", icon: "list-outline", label: "Directories", desc: "NAP + citation status feed", route: "/(app)/directories" as any },
    ],
  },
  {
    key: "adm-operations",
    title: "Operations",
    tiles: [
      { key: "schedule", icon: "calendar-outline", label: "Schedule", desc: "Day/Week/Month/Custom", route: "/(app)/schedule/calendar" },
      { key: "dispatch-board", icon: "git-network-outline", label: "Dispatch Board", desc: "Auto-route unassigned jobs", route: "/(app)/dispatch/board" },
      { key: "dispatch-weather", icon: "cloud-outline", label: "Weather Reschedule", desc: "Move outdoor jobs on bad weather", route: "/(app)/dispatch/weather" },
      { key: "estimator", icon: "calculator-outline", label: "Field Estimator", desc: "Build a quote on-site", route: "/(app)/estimator" },
      { key: "calculators", icon: "flask-outline", label: "Pool Calculators", desc: "Dosing · Volume · Salt · LSI", route: "/(app)/calculators" },
      { key: "inventory", icon: "layers-outline", label: "Inventory", desc: "Stock & purchase orders", route: "/(app)/inventory" },
    ],
  },
  {
    key: "adm-customers",
    title: "Customers",
    tiles: [
      { key: "customers", icon: "people-outline", label: "Customers", desc: "Full customer directory", route: "/(app)/customers" },
      { key: "leads", icon: "magnet-outline", label: "Leads", desc: "Lead pipeline · convert · close", route: "/leads" as any },
      { key: "quotes", icon: "document-text-outline", label: "Quotes & Invoices", desc: "Send, sign, collect", route: "/(app)/quotes" },
      { key: "property-lookup", icon: "home-outline", label: "Property Lookup", desc: "Owner + lot size search", route: "/(app)/property-lookup" },
      { key: "business-card", icon: "id-card-outline", label: "Business Card", desc: "NFC-ready digital card & .vcf", route: "/card" },
      { key: "service-tracking", icon: "filter-outline", label: "Service Tracking", desc: "Filter & salt cell trackers", route: "/tracking" as any },
    ],
  },
  {
    key: "adm-operations-2",
    title: "Documents",
    tiles: [
      { key: "templates", icon: "library-outline", label: "Templates Library", desc: "Fill-in-the-blank forms & docs", route: "/(app)/templates" },
    ],
  },
  {
    key: "adm-reports",
    title: "Reports",
    tiles: [
      { key: "reports-hub", icon: "bar-chart-outline", label: "Reports Hub", desc: "Business summary & analytics", route: "/(app)/reports" as any },
    ],
  },
];

/**
 * Pick the section list for the current role. Returns `[]` for customer
 * — the customer portal has its own nav and the global dropdown menu
 * is suppressed for them anyway (see `GlobalMenu.tsx`).
 */
export function sectionsForRole(role: string | undefined): ToolSection[] {
  if (role === "admin" || role === "super_admin") return ADMIN_SECTIONS;
  if (role === "technician") return TECH_SECTIONS;
  return [];
}
