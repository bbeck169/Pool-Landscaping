/**
 * Phase K75 · Step B · Feb-2026 — pin picker registry.
 *
 * Flattens the role-appropriate route sources into the shape the
 * ``AddPinModal`` renders (searchable tree grouped by category).
 * For each entry, we emit ``{ to, label, iconKey, group }`` — the
 * ``iconKey`` is derived by reverse-looking-up the entry's lucide
 * component in ``ICON_MAP``. Icons outside the K75 whitelist fall
 * back to ``external_link`` so the picker never renders a blank
 * slot; the backend PUT validator still forces the persisted pin
 * to a whitelisted key, so the fallback is UI-only.
 *
 * Sources:
 *   • admin / super_admin / manager → ADMIN_NAV_V2 (six category
 *     groups) + ADMIN_TOP_NAV (7 fixed items surfaced as their own
 *     "Primary" group at the top).
 *   • technician → TECH_TOP_NAV + a curated list of extra
 *     tech-visible routes.
 *   • customer → returns [] — the customer portal mounts its own
 *     rail via <UniversalMenu>.
 */
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { ADMIN_TOP_NAV, TECH_TOP_NAV } from "@/nav/topNavRegistry";
import { ICON_MAP } from "@/nav/lucideIcons";


// Component → iconKey reverse map. Only covers the K75-whitelisted
// icons; every other lucide component falls back to
// ``external_link`` (see ``iconKeyFor``).
const _COMPONENT_TO_KEY = new Map();
for (const [key, Comp] of Object.entries(ICON_MAP)) {
  _COMPONENT_TO_KEY.set(Comp, key);
}


export function iconKeyFor(Comp) {
  return _COMPONENT_TO_KEY.get(Comp) || "external_link";
}


function _topNavToGroup(items, groupLabel) {
  return {
    key: `primary`,
    label: groupLabel,
    entries: items.map((it) => ({
      to: it.to,
      label: it.label,
      iconKey: iconKeyFor(it.Icon),
    })),
  };
}


function _adminNavToGroups() {
  return ADMIN_NAV_V2.map((g) => ({
    key: g.key,
    label: g.label,
    entries: g.entries.map((e) => ({
      to: e.to,
      label: e.subsection ? `${e.subsection} · ${e.label}` : e.label,
      iconKey: iconKeyFor(e.icon),
    })),
  }));
}


// A handful of tech-visible routes NOT already in ``TECH_TOP_NAV``.
// Feeds the picker so techs can pin things like their own timesheet
// or a favorite customer list view.
const _TECH_EXTRAS = [
  { to: "/tech/timesheet",     label: "Timesheet",         iconKey: "clock" },
  { to: "/tech/messages",      label: "Messages",          iconKey: "message_square" },
  { to: "/tech/announcements", label: "Announcements",     iconKey: "bell" },
  { to: "/customers",          label: "Customers",         iconKey: "users" },
  { to: "/estimates",          label: "Estimates",         iconKey: "file_text" },
];


export function pinPickerForRole(role) {
  if (["admin", "super_admin", "manager"].includes(role)) {
    const raw = [
      _topNavToGroup(ADMIN_TOP_NAV, "Primary"),
      ..._adminNavToGroups(),
    ];
    return _dedupeAcrossGroups(raw);
  }
  if (role === "technician") {
    const raw = [
      _topNavToGroup(TECH_TOP_NAV, "Primary"),
      { key: "extras", label: "More tech routes", entries: _TECH_EXTRAS },
    ];
    return _dedupeAcrossGroups(raw);
  }
  return [];
}


// Drop any entry whose ``to`` has already appeared earlier in the
// picker (higher-priority group wins). This keeps the picker
// duplicate-free — e.g. ``/invoices`` shows up in both the Primary
// group AND the Finance group by design; dedupe keeps the first
// (Primary) so the picker rows carry unique testids AND the user
// doesn't hunt for the same route in two places.
function _dedupeAcrossGroups(groups) {
  const seen = new Set();
  return groups
    .map((g) => ({
      ...g,
      entries: g.entries.filter((e) => {
        if (seen.has(e.to)) return false;
        seen.add(e.to);
        return true;
      }),
    }))
    .filter((g) => g.entries.length > 0);
}
