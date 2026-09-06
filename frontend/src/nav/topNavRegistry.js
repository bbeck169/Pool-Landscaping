/**
 * Phase K75 · Feb-2026 — role-scoped top-nav registry.
 *
 * The Feb-2026 sidebar-pivot moved the 7 primary IA links to a
 * horizontal top bar. K75 restores a role-appropriate FIXED item
 * set on the top nav so operators reach the highest-frequency
 * pages in one tap regardless of what they've pinned to the left
 * rail:
 *
 *   • admin / super_admin / manager  → 7 items (Dashboard,
 *     Schedule, Customers, Estimates, Invoices, Reports, Settings)
 *     PLUS a "More" dropdown that houses the six ``ADMIN_NAV_V2``
 *     categories (Directory / Financial / Marketing / AI Tools /
 *     D2D / Finance) so deep pages remain reachable.
 *   • technician                     → 6 items (Schedule, D2D,
 *     Time Clock, Tools, Training, Profile). No "More" dropdown.
 *   • customer / customer_portal     → EMPTY — the customer portal
 *     mounts its own <UniversalMenu> instead. Return `[]` so
 *     ``<AdminTopBar>`` short-circuits to the tech-wrap branch
 *     (right-cluster only).
 *
 * Consumers:
 *   - ``layouts/AdminTopBar.jsx``   — renders ``fixedItems`` inline.
 *   - ``test/k75-top-nav.test.jsx`` — grep-locks the registry shape.
 *
 * Design tokens: every rendered chip uses ``colors.nav.fg`` on the
 * K50 navy chrome, ``colors.nav.bgActiveNavy`` for both active and
 * hover (K64 canonical). NO brandGradient — see K64 spec.
 */
import {
  LayoutDashboard,
  CalendarDays,
  Users,
  FileText,
  Receipt,
  BarChart3,
  Settings as SettingsIcon,
  DoorOpen,
  Clock,
  LayoutGrid,
  GraduationCap,
  UserCircle,
} from "lucide-react";


// K75 · admin / super_admin / manager — 7 fixed items.
// Route notes:
//   - ``/`` is the admin dashboard (App.js: ``<Route index element={<AdminDashboard/>} />``).
//   - ``/estimates`` exists as a real route that redirects to
//     ``/quotes`` (label stays "Estimates" per K75 spec).
//   - ``/settings`` is the consolidated Settings Hub — the same
//     surface the sprocket button in the right cluster links to.
export const ADMIN_TOP_NAV = [
  { key: "dashboard", to: "/",          label: "Dashboard", Icon: LayoutDashboard, end: true },
  { key: "schedule",  to: "/schedule",  label: "Schedule",  Icon: CalendarDays },
  { key: "customers", to: "/customers", label: "Customers", Icon: Users },
  { key: "estimates", to: "/estimates", label: "Estimates", Icon: FileText },
  { key: "invoices",  to: "/invoices",  label: "Invoices",  Icon: Receipt },
  { key: "reports",   to: "/reports",   label: "Reports",   Icon: BarChart3 },
  { key: "settings",  to: "/settings",  label: "Settings",  Icon: SettingsIcon },
];


// K75 · technician — 6 fixed items.
// Route notes (mirrors the pre-K75 ``TECH_NAV`` in ``AppLayout.jsx``):
//   - ``/schedule``          — tech home / today's route.
//   - ``/d2d``               — door-to-door canvassing dashboard.
//   - ``/tech/time-clock``   — tech-scoped time clock (App.js gate).
//   - ``/tech/tools``        — "All My Tools" hub (Phase 29).
//   - ``/tests``             — training modules (label "Training" per
//                              Feb-2026 Tech-Nav-Fix).
//   - ``/portal/profile``    — tech profile settings (App.js gate).
export const TECH_TOP_NAV = [
  { key: "schedule",   to: "/schedule",         label: "Schedule",   Icon: CalendarDays, end: true },
  { key: "d2d",        to: "/d2d",              label: "D2D",        Icon: DoorOpen },
  { key: "time-clock", to: "/tech/time-clock",  label: "Time Clock", Icon: Clock },
  { key: "tools",      to: "/tech/tools",       label: "Tools",      Icon: LayoutGrid },
  { key: "training",   to: "/tests",            label: "Training",   Icon: GraduationCap },
  { key: "profile",    to: "/portal/profile",   label: "Profile",    Icon: UserCircle },
];


/** Return the K75 fixed top-nav item list for the given role. */
export function topNavForRole(role) {
  if (["admin", "super_admin", "manager"].includes(role)) return ADMIN_TOP_NAV;
  if (role === "technician") return TECH_TOP_NAV;
  return [];
}


/**
 * Only admin / super_admin / manager see the "More" dropdown — it
 * exposes the six ``ADMIN_NAV_V2`` categories so deep pages remain
 * reachable in ≤ 2 clicks. Technicians rely on ``/tech/tools`` for
 * their long-tail routes; customers use ``UniversalMenu``.
 */
export function showMoreDropdownForRole(role) {
  return ["admin", "super_admin", "manager"].includes(role);
}
