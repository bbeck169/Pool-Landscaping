/**
 * Phase K75 · Step B · Feb-2026 — default (seed) quick-pins per role.
 *
 * Mirrors the pre-K75 hard-coded ``QUICK_NAV_RAIL`` in
 * ``AppLayout.jsx`` — every user gets these pins on first-run
 * (until they add / remove / reorder their own set).
 *
 * ``iconKey`` values MUST resolve through ``ICON_MAP`` in
 * ``nav/lucideIcons.js`` — enforced by the backend's PUT
 * validator and the K75 vitest CRUD.
 *
 * Emitted shape (post-``resolveIcon``):
 *   ``{ key, to, label, iconKey, Icon, end? }``
 * — where ``Icon`` is the resolved lucide component. Persisted
 * shape (post-``PUT``) only carries ``{ to, label, iconKey }``
 * because those three fields fully round-trip through JSON.
 */
import { resolveIcon } from "@/nav/lucideIcons";


const ADMIN_DEFAULTS_RAW = [
  { key: "dashboard",   to: "/",                          label: "Dashboard",   iconKey: "layout_dashboard", end: true },
  { key: "workstream",  to: "/workstream",                label: "Workstream",  iconKey: "wrench" },
  { key: "schedule",    to: "/schedule",                  label: "Schedule",    iconKey: "calendar_days" },
  { key: "invoices",    to: "/invoices",                  label: "Invoices",    iconKey: "receipt" },
  { key: "payments",    to: "/payments",                  label: "Payments",    iconKey: "credit_card" },
  { key: "customers",   to: "/customers",                 label: "Customers",   iconKey: "users" },
  { key: "leads",       to: "/leads",                     label: "Leads",       iconKey: "user_plus" },
  { key: "estimates",   to: "/estimates",                 label: "Estimates",   iconKey: "file_text" },
  { key: "pool-report", to: "/admin/reports/pool-service", label: "Pool Report", iconKey: "waves" },
  { key: "time-clock",  to: "/landscape/time-clock",      label: "Time Clock",  iconKey: "clock" },
  { key: "job-timers",  to: "/job-timers?t=avgtime",      label: "Job Timers",  iconKey: "timer" },
];


const TECH_DEFAULTS_RAW = [
  { key: "dashboard", to: "/",         label: "Dashboard", iconKey: "layout_dashboard", end: true },
  { key: "schedule",  to: "/schedule", label: "Schedule",  iconKey: "calendar_days" },
];


function _hydrate(list) {
  // Attach the resolved lucide component so consumers don't have to
  // ``resolveIcon`` at render time. Persisted shape is the raw list
  // above; the hydrated shape is what the rail actually renders.
  return list.map((p) => ({ ...p, Icon: resolveIcon(p.iconKey) }));
}


/** Return the K75 SEED pin list for the given role. Used by:
 *   • the frontend rail when the backend GET returns [] (first-run)
 *   • the K75 pytest contract test to seed a fresh-user snapshot
 *   • the pin picker to know which routes are "default" so the
 *     "Reset to defaults" future action stays honest.
 */
export function defaultQuickPinsForRole(role) {
  if (["admin", "super_admin", "manager"].includes(role)) return _hydrate(ADMIN_DEFAULTS_RAW);
  if (role === "technician") return _hydrate(TECH_DEFAULTS_RAW);
  return [];
}


/** Hard cap enforced by the backend PUT + surfaced by the UI. */
export const QUICK_PINS_CAP = 15;
