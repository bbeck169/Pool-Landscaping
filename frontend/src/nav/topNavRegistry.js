/**
 * Phase K76 · Feb-2026 — role-scoped top-nav registry.
 *
 * K76 walks back the K75 fixed-strip for admin / super_admin /
 * manager: the top nav renders the six ``ADMIN_NAV_V2`` category
 * dropdowns directly (Finance / AI Employees / Marketing /
 * Operations / Customers / Reports / Communications / Reviews) —
 * matching the pre-K75 ``AdminTopBar`` layout. The left Quick
 * Access rail (K75 Step B) already covers the seven high-frequency
 * shortcuts (Dashboard / Schedule / Customers / Estimates /
 * Invoices / Reports / Settings), so a separate fixed strip is
 * redundant.
 *
 * Role scoping:
 *   • admin / super_admin / manager  → category dropdowns via
 *     ``useVisibleGroups()`` in ``AdminTopBar`` (no fixed strip,
 *     no "More" dropdown — every category is directly visible).
 *   • technician                     → 6 fixed items (Schedule,
 *     D2D, Time Clock, Tools, Training, Profile). ``TECH_TOP_NAV``
 *     stays byte-for-byte from K75.
 *   • customer / customer_portal     → EMPTY — the customer
 *     portal mounts its own ``<UniversalMenu>`` instead.
 *
 * Design tokens: every rendered chip / category trigger uses
 * ``colors.nav.fg`` on the K50 navy chrome and
 * ``colors.nav.bgActiveNavy`` (K64 canonical) for BOTH active
 * and hover states. NO ``brandGradient`` reintroduction on the
 * top nav surfaces — see K76 spec.
 */
import {
  CalendarDays,
  DoorOpen,
  Clock,
  LayoutGrid,
  GraduationCap,
  UserCircle,
  LayoutDashboard,
  Users,
  FileText,
  Receipt,
  BarChart3,
  Settings as SettingsIcon,
} from "lucide-react";


/**
 * K76 · legacy admin "Primary" bundle — retained ONLY for the
 * K75 Step B ``pinRegistry.js`` which surfaces these 7 high-
 * frequency shortcuts as the pin picker's top group. K76 walked
 * back their rendering as a fixed top-nav strip, but the pin
 * picker still uses them as an ordered "Primary" collection so
 * users have a curated set to pin quickly.
 */
export const ADMIN_TOP_NAV = [
  { key: "dashboard", to: "/",          label: "Dashboard",  Icon: LayoutDashboard,  end: true },
  { key: "schedule",  to: "/schedule",  label: "Schedule",   Icon: CalendarDays },
  { key: "customers", to: "/customers", label: "Customers",  Icon: Users },
  { key: "estimates", to: "/estimates", label: "Estimates",  Icon: FileText },
  { key: "invoices",  to: "/invoices",  label: "Invoices",   Icon: Receipt },
  { key: "reports",   to: "/reports",   label: "Reports",    Icon: BarChart3 },
  { key: "settings",  to: "/settings",  label: "Settings",   Icon: SettingsIcon },
];


// K76 · technician — 6 fixed items (unchanged from K75).
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


/**
 * Return the K76 fixed top-nav item list for the given role.
 *
 * For admin / super_admin / manager this returns an empty array —
 * the top bar renders the ``ADMIN_NAV_V2`` category dropdowns
 * directly via ``useVisibleGroups()`` in ``AdminTopBar`` instead
 * of a static fixed set. Kept as a function (not a constant) so
 * consumers can branch on role without importing ``ADMIN_NAV_V2``.
 */
export function topNavForRole(role) {
  if (role === "technician") return TECH_TOP_NAV;
  return [];
}
