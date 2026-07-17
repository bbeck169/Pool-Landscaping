/**
 * Phase 44 · Universal top-right menu — per-role navigation definitions.
 *
 * The admin/super_admin surface already has `ADMIN_NAV_V2` (the Phase 35
 * 6-category IA). This file adds parallel section lists for the tech
 * and customer roles so the universal top-right hamburger renders a
 * role-appropriate menu for every login.
 *
 * The `UniversalMenu` component reads from `navForRole()` at render time
 * and applies existing RBAC via `usePermissions().can()` on entries
 * that carry a `feature` marker. Entries without a `feature` are always
 * visible to the role that owns the section (they're pages the role's
 * primary UI already exposes anyway).
 */
import {
  LayoutDashboard, CalendarDays, Users, FileText, Camera, MessageSquare,
  Home, Wallet, Shield, User, ClipboardList, Wrench, MapPin, Truck,
  Package, Boxes, Trophy, IdCard,
  Briefcase, Coins, TrendingUp, ScrollText, BarChart3,
} from "lucide-react";
import { ADMIN_NAV_V2 } from "./adminNav";

export const TECH_NAV = [
  {
    key: "tech-daily",
    label: "Daily Work",
    icon: CalendarDays,
    entries: [
      { to: "/schedule", label: "Schedule", icon: CalendarDays },
      { to: "/dispatch/board", label: "Dispatch Board", icon: MapPin },
      { to: "/inbox", label: "Inbox", icon: MessageSquare },
      { to: "/time-clock", label: "Time Clock", icon: ClipboardList },
    ],
  },
  {
    key: "tech-job",
    label: "On the Job",
    icon: Wrench,
    entries: [
      { to: "/estimator", label: "Field Estimator", icon: Wrench },
      { to: "/calculators", label: "Pool Calculators", icon: Wrench },
      { to: "/property-lookup", label: "Property Lookup", icon: Home },
      { to: "/inventory", label: "Inventory", icon: Boxes },
      { to: "/assets", label: "My Equipment", icon: Package },
    ],
  },
  {
    key: "tech-records",
    label: "Records",
    icon: FileText,
    entries: [
      // Phase 49.4 + 49.5 — Customers, Quotes & Invoices removed from
      // tech nav. Techs shouldn't be reading customer billing docs.
      // Routes remain gated at the App.js level for defense-in-depth.
      { to: "/d2d/leaderboard", label: "D2D Leaderboard", icon: Trophy },
      { to: "/card", label: "Business Card", icon: IdCard },
    ],
  },
  {
    key: "tech-account",
    label: "Account",
    icon: User,
    entries: [
      { to: "/settings/auto-clockin", label: "Auto Clock-In", icon: MapPin },
    ],
  },
];

// Phase 57 — Department-gated tech navs. `TECH_NAV` above stays as the
// legacy default (used when department is unset). The pool + landscape
// variants filter On-the-Job entries to remove tools the other team
// doesn't need. `navForRoleAndDept(role, dept)` returns the right one.
const _stripEntries = (nav, remove) => nav.map((section) => ({
  ...section,
  entries: section.entries.filter((e) => !remove.includes(e.to)),
}));

// Pool techs — keep chem calculators, pool checklist, hide landscape stuff.
export const TECH_POOL_NAV = _stripEntries(TECH_NAV, [
  // (landscape-only entries would be listed here — currently none in TECH_NAV)
]).concat();

// Landscape techs — hide the pool calculators; the landscape checklist +
// clock widget mount on the home/profile pages, not the top nav.
export const TECH_LANDSCAPE_NAV = _stripEntries(TECH_NAV, [
  "/calculators",  // pool-only chemistry calcs
]);

export const CUSTOMER_NAV = [
  {
    key: "cust-home",
    label: "Home",
    icon: Home,
    entries: [
      { to: "/portal/home", label: "Dashboard", icon: LayoutDashboard },
      { to: "/portal/book", label: "Book Service", icon: CalendarDays },
      { to: "/portal/request-service", label: "Request Service", icon: MessageSquare },
    ],
  },
  {
    key: "cust-services",
    label: "Services",
    icon: Truck,
    entries: [
      { to: "/portal/services", label: "Service History", icon: Truck },
      { to: "/portal/photos", label: "Photos", icon: Camera },
      { to: "/portal/warranties", label: "Warranties", icon: Shield },
    ],
  },
  {
    key: "cust-billing",
    label: "Billing",
    icon: Wallet,
    entries: [
      { to: "/portal/invoices", label: "Invoices", icon: FileText },
      { to: "/portal/estimates", label: "Estimates", icon: ScrollText },
      { to: "/portal/payments", label: "Payments", icon: Wallet },
      { to: "/portal/payment-method", label: "Payment Method", icon: Wallet },
    ],
  },
  {
    key: "cust-messages",
    label: "Messages",
    icon: MessageSquare,
    entries: [
      { to: "/portal/messages", label: "Messages", icon: MessageSquare },
      { to: "/portal/chats", label: "Chats", icon: MessageSquare },
    ],
  },
  {
    key: "cust-docs",
    label: "Documents",
    icon: FileText,
    entries: [
      { to: "/portal/documents", label: "Documents", icon: FileText },
    ],
  },
  {
    key: "cust-account",
    label: "Account",
    icon: User,
    entries: [
      { to: "/portal/profile", label: "Profile", icon: User },
      { to: "/portal/terms", label: "Terms", icon: ScrollText },
    ],
  },
];

/** Return the section list appropriate for the current role. */
export function navForRole(role) {
  if (role === "admin" || role === "super_admin") {
    // Reuse the Phase 35 6-category admin IA verbatim — the universal
    // menu treats each ADMIN_NAV_V2 group as a section with its own
    // entries list. The category chip in the universal menu maps to
    // `group.key`.
    return ADMIN_NAV_V2;
  }
  if (role === "technician") return TECH_NAV;
  if (role === "customer") return CUSTOMER_NAV;
  return [];
}


/**
 * Phase 57 · department-aware variant used everywhere `department`
 * is available on the current user. Falls back to `navForRole` for
 * roles that don't have a department concept.
 *
 * Pool techs → TECH_POOL_NAV (default).
 * Landscape techs → TECH_LANDSCAPE_NAV (hides pool-only chem calcs).
 * Unassigned techs → the same TECH_POOL_NAV with the pool tools intact
 *   (the department banner on the home page nudges the admin to
 *   assign them). Pool = safe default.
 */
export function navForRoleAndDept(role, department) {
  if (role === "technician") {
    const dept = (department || "").toLowerCase();
    if (dept === "landscaping") return TECH_LANDSCAPE_NAV;
    // Phase 56.3.B — "both" = union of pool + landscape entries. Since
    // TECH_POOL_NAV is derived from TECH_NAV with no removals AND
    // TECH_LANDSCAPE_NAV strips only `/calculators`, the union is
    // effectively the un-stripped TECH_NAV. Using TECH_NAV directly
    // guarantees any future entry added to either variant surfaces
    // automatically for `both` techs.
    if (dept === "both") return TECH_NAV;
    // Both "pool" and unassigned fall back to the pool nav — pool is the
    // safe default so admins see the full tool surface until they
    // deliberately switch a tech's department.
    return TECH_POOL_NAV;
  }
  return navForRole(role);
}
