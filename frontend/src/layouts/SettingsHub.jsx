/**
 * SettingsHub · Feb-2026 · Consolidated Settings.
 *
 * Sidebar-nav layout that wraps every /settings/* sub-route in a
 * consistent shell so admins have one entry point instead of the
 * 36+ scattered pages the app grew organically.
 *
 * The individual settings pages remain at their existing URLs; this
 * hub just adds a shared frame (sidebar + right-hand `<Outlet />`)
 * so navigation between them is coherent.
 *
 * Auth: every child route is wrapped in <AdminOnly> at the router
 * level, so mounting this layout implies admin/super_admin already.
 * Tech / customer roles won't reach the layout at all.
 */
import React from "react";
import { NavLink, Outlet, useLocation, Link } from "react-router-dom";
import { colors } from "@/theme";
import {
  Settings as SettingsIcon,
  ImageIcon,
  Palette,
  Plug,
  Share2,
  ChevronRight,
} from "lucide-react";

// Hub-level sections (headline links). Feb 2026 · Migration / Team
// were dropped per user feedback — no dead sidebar entries. If a
// future request adds real pages for those, re-introduce with real
// routes at the same time.
const SECTIONS = [
  {
    key: "general",
    to: "/settings/general",
    label: "General",
    Icon: SettingsIcon,
    hint: "Tenant name, timezone, business card, terms",
  },
  {
    key: "branding",
    to: "/settings/branding",
    label: "Branding",
    Icon: ImageIcon,
    hint: "Logo upload, brand colours",
  },
  {
    key: "theme",
    to: "/settings/theme",
    label: "Theme",
    Icon: Palette,
    hint: "Palette editor + presets · Phase I1.5",
  },
  {
    key: "integrations",
    to: "/settings/integrations",
    label: "Integrations",
    Icon: Plug,
    hint: "Stripe, QBO, Mapbox, Resend, Google Business Profile",
  },
  {
    key: "social",
    to: "/settings/social",
    label: "Social",
    Icon: Share2,
    hint: "8-platform connect grid (Facebook, Instagram, LinkedIn…)",
  },
];

export default function SettingsHub() {
  const loc = useLocation();
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
          data-testid="settings-hub">
      <div className="mb-4 flex items-center gap-2">
        <SettingsIcon size={20} style={{ color: colors.brand }} />
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
             style={{ color: colors.onSurface }}
             data-testid="settings-hub-title">
          Settings
        </h1>
      </div>

      <div className="grid grid-cols-12 gap-4">
        {/* Sidebar nav — subtle brand tint matches the app-shell polish. */}
        <aside
          className="col-span-12 md:col-span-3 rounded-2xl p-2"
          style={{
            background:
              "linear-gradient(180deg, rgba(2,132,199,0.06) 0%, rgba(2,132,199,0.02) 100%)",
            border: `1px solid ${colors.border}`,
          }}
          data-testid="settings-hub-sidebar"
        >
          <nav className="flex flex-col gap-1" aria-label="Settings sections">
            {SECTIONS.map(({ key, to, label, Icon, hint }) => {
              // Active if the current path starts with the section path.
              // Also treat /settings and /settings/general as active for
              // the General row so the landing state highlights something.
              const isActive =
                loc.pathname === to
                || loc.pathname.startsWith(`${to}/`)
                || (key === "general" && loc.pathname === "/settings");
              return (
                <NavLink
                  key={key}
                  to={to}
                  className={[
                    "group flex items-start gap-2 px-3 py-2 rounded-lg",
                    "transition-all duration-200 ease-out",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:scale-[1.01]",
                    "hover:scale-[1.02]",
                    isActive
                      ? "shadow-[0_1px_2px_rgba(2,132,199,0.08)]"
                      : "hover:bg-sky-50/60 hover:text-sky-600",
                  ].join(" ")}
                  style={{
                    backgroundColor: isActive ? colors.brandTertiary : "transparent",
                    color: isActive ? colors.brand : colors.onSurface,
                    border: `1px solid ${isActive ? colors.brand : "transparent"}`,
                  }}
                  data-testid={`settings-tab-${key}`}
                  data-active={isActive ? "1" : "0"}
                >
                  <Icon size={16} className="mt-0.5 transition-colors duration-200 group-hover:text-sky-600" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold leading-tight">
                      {label}
                    </div>
                    <div className="text-[11px] leading-snug mt-0.5"
                          style={{ color: colors.muted }}>
                      {hint}
                    </div>
                  </div>
                  <ChevronRight size={12} className="mt-1 opacity-40" />
                </NavLink>
              );
            })}
          </nav>
        </aside>

        {/* Active-tab content */}
        <section className="col-span-12 md:col-span-9"
                 data-testid="settings-hub-content">
          <Outlet />
        </section>
      </div>
    </div>
  );
}

/** Landing tab — General. Small placeholder with quick links to the
 *  legacy detail pages that live at /settings/business-card,
 *  /settings/terms, /settings/tenant etc. */
export function SettingsGeneral() {
  const quickLinks = [
    { to: "/settings/tenant",         label: "Tenant name & brand colours" },
    { to: "/settings/business-card",  label: "Business card" },
    { to: "/settings/terms",          label: "Default terms & conditions" },
    { to: "/settings/late-fees",      label: "Late fees" },
    { to: "/settings/legal",          label: "Legal documents" },
    { to: "/settings/notifications",  label: "Notification preferences" },
  ];
  return (
    <div className="rounded-2xl p-5 space-y-3"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="settings-general-card">
      <h2 className="text-lg font-semibold"
           style={{ color: colors.onSurface }}>
        General
      </h2>
      <p className="text-sm" style={{ color: colors.muted }}>
        Core tenant configuration — pick a card to jump straight in.
        Every deep-link stays at its historical URL so bookmarks
        remain valid.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2">
        {quickLinks.map(({ to, label }) => (
          <Link
            key={to}
            to={to}
            className="flex items-center justify-between px-3 py-2 rounded-lg text-sm font-semibold transition hover:brightness-95"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface }}
            data-testid={`settings-general-link-${to.split("/").pop()}`}
          >
            <span>{label}</span>
            <ChevronRight size={14} className="opacity-50" />
          </Link>
        ))}
      </div>
    </div>
  );
}
