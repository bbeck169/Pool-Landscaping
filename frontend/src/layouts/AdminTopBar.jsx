/**
 * Phase 44 · Web Admin — persistent top navigation bar.
 *
 * The Phase 35 sidebar (AdminSidebar.jsx) is the canonical IA — this
 * top bar is ADDITIVE. It flattens every entry in the 6-category
 * `ADMIN_NAV_V2` source into a single row of Radix `DropdownMenu`
 * triggers so power users can hit any admin page in ≤2 clicks without
 * scrolling the sidebar.
 *
 * Contract preserved:
 *   • Same RBAC filter as the sidebar (feature + hard_rule flags via
 *     `usePermissions().can`).
 *   • Same `NavLink` rendering + active-state semantics as elsewhere.
 *   • No `feature` gate removed, no page added or hidden.
 *
 * Responsive behavior:
 *   • ≥md — six dropdowns inline.
 *   • <md — one "Menu" dropdown that expands to sub-menus per
 *     category, giving mobile web the same 100% coverage.
 */
import React, { useMemo } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, MenuIcon, Users, FileText, ClipboardList, CalendarDays, ListChecks, Phone, GraduationCap, Plus as PlusIcon, LogOut } from "lucide-react";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuth } from "@/auth";
import { brandGradientCss } from "@/theme";
import UniversalMenu from "@/layouts/UniversalMenu";
import CreditsBudgetChip from "@/components/AIDock/CreditsBudgetChip";
// Feb-2026 · Consolidated Settings Hub — sprocket in header for admins.
import { Settings as SettingsIcon } from "lucide-react";
// Feb-2026 UI Polish Addendum — BrandLogo import was pulled after the
// duplicate-logo dedupe: the top-nav no longer mounts the brand mark
// (the side-rail crown in <AppLayout> is the single source of truth).
// Kept the plumbing (BrandLogo, useTenantBrand, backend logo_url) so
// future surfaces can drop it in without wiring cost.
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
  DropdownMenuPortal,
} from "@/components/ui/dropdown-menu";
import { colors } from "@/theme";

/** Filter entries by RBAC and group them by `subsection` when present. */
function useVisibleGroups() {
  const { can, effectiveRole } = usePermissions();
  return useMemo(() => {
    // Feb-2026 · sidebar-removal follow-up — `ADMIN_NAV_V2` is the
    // admin IA surface. Technicians / customers now share the same
    // AdminTopBar host (so the QuickNavRow reaches them), but they
    // must NOT see the admin category dropdowns. Short-circuit here
    // so downstream mapping cost is zero for those roles.
    if (!["admin", "super_admin", "manager"].includes(effectiveRole)) {
      return [];
    }
    return ADMIN_NAV_V2
      .map((g) => ({
        ...g,
        entries: g.entries.filter((e) => {
          if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
          if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
          // Feb 2026 · Task A hotfix — ``manager_only`` is authoritative.
          // See ``AdminSidebar.jsx`` for the full rationale; short
          // version is the backend permission matrix doesn't seed
          // ``manager`` so ``can("scheduling","read")`` would silently
          // hide the entry from real manager accounts. When the hard
          // rule matches, grant access directly without falling to
          // the feature gate.
          if (e.hard_rule === "manager_only") {
            return ["super_admin", "admin", "manager"].includes(effectiveRole);
          }
          return can(e.feature || "dashboard", "read") || effectiveRole === "admin";
        }),
      }))
      .filter((g) => g.entries.length > 0)
      .map((g) => {
        // Group entries by subsection for readable dropdown sections.
        const bySub = {};
        const noSub = [];
        for (const e of g.entries) {
          if (e.subsection) {
            (bySub[e.subsection] = bySub[e.subsection] || []).push(e);
          } else {
            noSub.push(e);
          }
        }
        return { ...g, noSub, bySub };
      });
  }, [can, effectiveRole]);
}

function CategoryDropdown({ group }) {
  const location = useLocation();
  const CatIcon = group.icon;
  const active = group.entries.some((e) => location.pathname === e.to);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="group inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap transition-all duration-200 ease-out will-change-transform hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02]"
        style={{
          // Phase K64 · Feb-2026 — active + hover both render as
          // ``colors.nav.bgActiveNavy`` (lighter-navy solid) instead
          // of the K52 mint gradient. Idle state keeps
          // ``colors.nav.bg``. Hover state is applied inline in the
          // mouse handlers below (unified with active); the
          // ``hover:bg-white/10`` Tailwind class was dropped because
          // it was fighting the new solid.
          color: colors.nav.fg,
          background: active ? colors.nav.bgActiveNavy : undefined,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = colors.nav.bgActiveNavy;
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = active ? colors.nav.bgActiveNavy : "";
        }}
        data-testid={`admin-topbar-${group.key}`}
        data-active={active ? "true" : "false"}
      >
        <CatIcon size={16} className="transition-colors duration-200" />
        <span className="transition-colors duration-200">{group.label}</span>
        <ChevronDown size={14} className="opacity-70 transition-transform duration-200 group-hover:translate-y-[1px]" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[280px] max-h-[70vh] overflow-y-auto p-1 border-0 shadow-xl [&_[role=menuitem]]:text-white [&_[role=menuitem]]:cursor-pointer [&_[role=menuitem]:focus]:bg-[#2A2F7A] [&_[role=menuitem]:focus]:text-white [&_[role=menuitem]:hover]:bg-[#2A2F7A] [&_[role=menuitem]:hover]:text-white [&_[data-radix-menu-label]]:text-white/72 [&_[role=separator]]:bg-white/10"
          // Phase K52 Slice B · Feb-2026 — navy popover panel.  The
          // shadcn ``DropdownMenuContent`` primitive is not modified
          // globally — instead we scope the navy chrome to this one
          // top-nav consumer via ``className`` overrides + inline
          // ``style`` so unrelated ``DropdownMenu`` usages
          // (row-action menus, kebab menus) keep their default
          // light theme.  Items, labels, and separators are
          // re-tinted for legibility on navy.
        style={{
          backgroundColor: colors.nav.bg,
          color: colors.nav.fg,
        }}
        data-testid={`admin-topbar-${group.key}-menu`}
        data-k52-navy-popover="true"
      >
        {group.noSub.map((e) => (
          <EntryItem key={e.to} e={e} />
        ))}
        {group.noSub.length > 0 && Object.keys(group.bySub).length > 0 ? (
          <DropdownMenuSeparator />
        ) : null}
        {Object.entries(group.bySub).map(([sub, entries], i, arr) => (
          <React.Fragment key={sub}>
            <DropdownMenuLabel
              className="text-[10px] uppercase tracking-wider"
              style={{ color: colors.nav.fgMuted }}
            >
              {sub}
            </DropdownMenuLabel>
            {entries.map((e) => <EntryItem key={e.to} e={e} />)}
            {i < arr.length - 1 ? <DropdownMenuSeparator /> : null}
          </React.Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function EntryItem({ e }) {
  const location = useLocation();
  const Icon = e.icon;
  const active = location.pathname === e.to;
  return (
    <DropdownMenuItem
      asChild
      data-testid={`admin-topbar-link-${e.to.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}
      data-active={active ? "true" : "false"}
      style={active ? {
        // Phase K52 Slice B · Feb-2026 — active row inside the navy
        // popover renders as a white pill with navy text.  This is
        // the K50 active affordance (kept here — the K52 gradient
        // is reserved for the NAV surfaces themselves per Slice D).
        backgroundColor: colors.nav.bgActive,
        color: colors.nav.fgActive,
      } : undefined}
    >
      <Link to={e.to} className="flex items-center gap-2 cursor-pointer">
        {Icon ? <Icon size={14} className="opacity-80 shrink-0" /> : null}
        <span className="truncate">{e.label}</span>
      </Link>
    </DropdownMenuItem>
  );
}

/** Compact single-dropdown variant for narrow viewports. */
function MobileMenu({ visible }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold border"
        style={{
          // Phase K50 · Feb-2026 — narrow-viewport "Menu" trigger
          // sits inside the navy top bar; render as a white-on-navy
          // outlined pill so it reads against the navy backdrop.
          color: colors.nav.fg,
          borderColor: colors.nav.border,
          backgroundColor: "transparent",
        }}
        data-testid="admin-topbar-mobile-trigger"
      >
        <MenuIcon size={16} />
        <span>Menu</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[240px] max-h-[80vh] overflow-y-auto"
        data-testid="admin-topbar-mobile-menu"
      >
        {visible.map((g) => {
          const CatIcon = g.icon;
          return (
            <DropdownMenuSub key={g.key}>
              <DropdownMenuSubTrigger
                data-testid={`admin-topbar-mobile-${g.key}`}
                className="flex items-center gap-2"
              >
                <CatIcon size={14} className="opacity-80" />
                <span>{g.label}</span>
              </DropdownMenuSubTrigger>
              <DropdownMenuPortal>
                <DropdownMenuSubContent className="min-w-[240px] max-h-[70vh] overflow-y-auto">
                  {g.noSub.map((e) => <EntryItem key={e.to} e={e} />)}
                  {Object.entries(g.bySub).map(([sub, entries]) => (
                    <React.Fragment key={sub}>
                      <DropdownMenuLabel className="text-[10px] uppercase tracking-wider opacity-60">
                        {sub}
                      </DropdownMenuLabel>
                      {entries.map((e) => <EntryItem key={e.to} e={e} />)}
                    </React.Fragment>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Phase 55 · Quick-Access row — pinned shortcut chips at the very
 *  top of the top bar. RBAC-gated per entry using the same
 *  `effectiveRole` semantics as the category dropdowns. Renders as
 *  filled pills so they're visually distinct from the outlined
 *  category dropdowns. If a role has zero visible items, the entire
 *  strip is suppressed (no empty container).
 *
 *  Deprecated Feb-2026 for admin / super_admin per user request —
 *  the strip duplicated the 6-category dropdowns and cluttered the
 *  top of every admin page. Non-admin roles (technician, customer)
 *  still see it if any of their entries remain, so the component
 *  is kept intact rather than deleted. Safe to remove entirely if
 *  no future consumer resurrects it.
 */
function QuickAccessRow() {
  const { effectiveRole } = usePermissions();
  // Feb-2026 · Admin / super_admin no longer see the pinned Quick
  // Access strip. The 6-category dropdowns below cover the same
  // navigation surface without the duplicate row.
  if (effectiveRole === "admin" || effectiveRole === "super_admin") {
    return null;
  }
  const items = [
    { to: "/customers",                     label: "Customers",   icon: Users,        roles: [] },
    { to: "/invoices",                       label: "Invoices",    icon: FileText,     roles: [] },
    { to: "/quotes",                         label: "Estimates",   icon: ClipboardList, roles: [] },
    { to: "/schedule/calendar",              label: "Schedule",    icon: CalendarDays, roles: ["technician"] },
    { to: "/tests",                            label: "Tests",       icon: GraduationCap, roles: ["technician"] },
    { to: "/jobs",                            label: "Workstream",  icon: ListChecks,   roles: ["technician", "customer"] },
    { to: "/admin/settings/ringcentral",      label: "RingCentral", icon: Phone,        roles: [] },
  ];
  const visible = items.filter((it) => it.roles.includes(effectiveRole));
  if (visible.length === 0) return null;
  return (
    <div
      className="w-full border-b flex items-center gap-2 px-4 py-2 overflow-x-auto"
      style={{ backgroundColor: colors.surfaceSecondary, borderColor: colors.border }}
      data-testid="admin-topbar-quick-access"
    >
      <span
        className="text-[10px] font-bold uppercase tracking-wider mr-1 shrink-0"
        style={{ color: colors.muted }}
      >
        Quick Access
      </span>
      {visible.map((it) => {
        const Icon = it.icon;
        return (
          <Link
            key={it.to}
            to={it.to}
            className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full whitespace-nowrap"
            style={{ background: colors.brand, color: "#fff" }}
            data-testid={`quick-access-${it.label.toLowerCase()}`}
          >
            <Icon size={13} />
            {it.label}
          </Link>
        );
      })}
    </div>
  );
}


// Feb-2026 · Sidebar-pivot follow-up — the flat horizontal
// QuickNavRow (and its QUICK_NAV table) that briefly lived here has
// been retired. The 7 quick-access items are now rendered as a
// vertical rail in <AppLayout>. This file no longer owns any
// primary-nav surface; only the QuickAccessRow (pinned pill strip)
// and the ADMIN_NAV_V2 category dropdowns remain.



export default function AdminTopBar() {
  const visible = useVisibleGroups();
  const _auth = useAuth();
  const _role = _auth?.user?.role || "";
  // Phase 44 · Fix A (attempt 3) — bulletproof responsive gate.
  //
  // Previous attempts using Tailwind `hidden md:flex` / `md:hidden` and
  // then `matchMedia` alone both failed to flip at ~600px in the tester
  // report. Belt-and-braces this by:
  //   1. Reading `window.innerWidth` directly on every render.
  //   2. Subscribing to BOTH `resize` events (always available) and
  //      matchMedia change (for browsers that suppress `resize` events
  //      while in DevTools responsive mode).
  //   3. Exposing the computed width as a `data-vw` attribute so a QA
  //      driver can inspect the actual gate state without guessing.
  const [vw, setVw] = React.useState(() =>
    typeof window !== "undefined" ? window.innerWidth : 1024);
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const on = () => setVw(window.innerWidth);
    // Immediate read on mount in case SSR seeded with the fallback 1024.
    on();
    window.addEventListener("resize", on);
    // Also subscribe to a matchMedia listener because DevTools' device
    // toolbar sometimes doesn't fire real `resize` events on iframe
    // hosts.
    let mq;
    if (window.matchMedia) {
      mq = window.matchMedia("(max-width: 767.98px)");
      if (mq.addEventListener) mq.addEventListener("change", on);
      else mq.addListener(on);
    }
    return () => {
      window.removeEventListener("resize", on);
      if (mq) {
        if (mq.removeEventListener) mq.removeEventListener("change", on);
        else mq.removeListener(on);
      }
    };
  }, []);
  const isNarrow = vw < 768;

  // Feb-2026 · Sidebar-pivot follow-up — hooks run first (rules-of-
  // hooks); this defensive null-guard now sits below every hook
  // call to keep the invocation order stable across renders.
  if (!_role) return null;

  return (
    <div
      className="sticky top-0 z-30 w-full border-b backdrop-blur-[2px]"
      style={{
        // Phase K50 · Feb-2026 — Pipedrive-inspired navy chrome.
        // Matches the desktop sidebar (``colors.nav.bg`` = #1B1F5C).
        // The right-side cluster (SignOut / Sprocket / etc.) keeps
        // its light-chip styling — the pills read cleanly on navy
        // without extra work.
        backgroundColor: colors.nav.bg,
        borderColor: colors.nav.border,
      }}
      data-testid="admin-topbar"
      data-vw={vw}
      data-narrow={isNarrow ? "1" : "0"}
    >
      {/* Feb-2026 · Pivot — the 7 quick-access items are now
          rendered as a vertical rail in <AppLayout> (left column).
          The horizontal QuickNavRow that lived here has been
          retired; the category dropdowns below remain as the
          "…More" surface for deep admin routes. */}
      {/* Phase 55 — pinned Quick Access strip. Rendered above the
          6-category dropdowns / mobile menu so it stays reachable
          in one tap without changing existing behavior. */}
      <QuickAccessRow />
      {visible.length === 0 ? (
        // Feb-2026 · Technician (no admin categories) still needs
        // the right-side actions cluster — render just the actions,
        // no empty dropdown row above. Sign Out sits to the LEFT of
        // the bell + hamburger cluster per header-cleanup spec.
        <div
          className="px-4 h-11 flex items-center justify-end gap-2"
          data-testid="admin-topbar-tech-wrap"
        >
          <SettingsSprocket />
          <SignOutButton />
          <UniversalMenu variant="inline" />
        </div>
      ) : isNarrow ? (
        <div
          className="px-4 h-11 flex items-center justify-between"
          data-testid="admin-topbar-narrow-wrap"
        >
          <MobileMenu visible={visible} />
          {/* Feb-2026 · Header cleanup — single bell (rendered by
              inline UniversalMenu below), Sign Out visible to its
              LEFT, everything sits on the header baseline. */}
          <div className="flex items-center gap-2">
            <AddCustomerButton />
            <CreditsBudgetChip />
            <SettingsSprocket />
            <SignOutButton />
            <UniversalMenu variant="inline" />
          </div>
        </div>
      ) : (
        <div
          className="flex items-center gap-1 px-4 h-11 overflow-x-auto"
          data-testid="admin-topbar-wide-wrap"
        >
          {visible.map((g) => (
            <CategoryDropdown key={g.key} group={g} />
          ))}
          {/* Feb-2026 · Header cleanup — right-side cluster ordering
              per user spec (left → right): Add Customer · 500c ·
              Sign Out · 🔔 Bell · ☰ Menu. The bell + hamburger are
              rendered by <UniversalMenu variant="inline"> so there
              is exactly ONE bell in the top bar (was duplicated
              between the inline top-bar bell and the fixed
              UniversalMenu floating bell). */}
          <div className="ml-auto shrink-0 flex items-center gap-2">
            <AddCustomerButton />
            <CreditsBudgetChip />
            <SettingsSprocket />
            <SignOutButton />
            <UniversalMenu variant="inline" />
          </div>
        </div>
      )}
    </div>
  );
}

// Phase 21 · Feb 2026 · Addition D — "+ Add Customer" quick-action in
// the admin top bar. Admin + super_admin only. Routes to the existing
// customers-list new-customer surface (`/customers/new`) which reuses
// the shipped ``CustomerForm`` — no duplicated validation.
function AddCustomerButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  const role = auth?.user?.role;
  if (role !== "admin" && role !== "super_admin") return null;
  return (
    <button
      type="button"
      onClick={() => navigate("/customers/new")}
      className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-semibold text-white shadow-sm hover:brightness-95"
      style={{ background: brandGradientCss }}
      data-testid="topbar-add-customer-btn"
      aria-label="Add customer"
    >
      <PlusIcon size={14} /> Add Customer
    </button>
  );
}


// Feb-2026 · Sign-out moved from the sidebar footer up to the
// AdminTopBar per user request. Reuses the exact ``useAuth().logout``
// handler that used to live in ``AppLayout``. Same visible role
// scope as the rest of the topbar (any signed-in user reaches this
// component because the sidebar mounts it for every role).
// Feb-2026 · Consolidated Settings Hub — sprocket icon that sits
// immediately left of the Sign Out button. Visible for admin +
// super_admin only (tech / customer / manager do NOT see it —
// their role has no access to the consolidated settings surface
// gated by <AdminOnly> upstream). Click routes to /settings; hover
// / focus-visible motion matches the app-shell polish.
function SettingsSprocket() {
  const auth = useAuth();
  const { effectiveRole } = usePermissions();
  const role = effectiveRole || auth?.user?.role;
  if (role !== "admin" && role !== "super_admin") return null;
  return (
    <Link
      to="/settings"
      title="Settings"
      aria-label="Settings"
      data-testid="header-settings-sprocket"
      className={[
        "inline-flex items-center justify-center h-8 w-8 rounded-lg shadow-sm",
        "transition-all duration-150 ease-out will-change-transform",
        "hover:scale-[1.02] hover:text-sky-600",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:scale-[1.02]",
      ].join(" ")}
      style={{
        backgroundColor: colors.surfaceSecondary,
        color: colors.onSurface,
        border: `1px solid ${colors.border}`,
      }}
    >
      <SettingsIcon size={16} />
    </Link>
  );
}


function SignOutButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  if (!auth?.user) return null;
  const onLogout = () => {
    try { auth.logout && auth.logout(); } finally {
      navigate("/login", { replace: true });
    }
  };
  // Phase K54 · Feb-2026 — solid destructive red per
  // ``colors.destructive`` in ``theme.js``. #DC2626 bg / white text /
  // #B91C1C hover / #EF4444 focus ring / 0.55 disabled opacity —
  // matches the shadcn ``Button variant="destructive"`` spec so
  // every Sign-out entry point in the app reads identically.
  return (
    <button
      type="button"
      onClick={onLogout}
      className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-semibold shadow-sm text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55"
      data-testid="header-signout"
      aria-label="Sign out"
    >
      <LogOut size={14} /> Sign out
    </button>
  );
}
