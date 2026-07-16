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
import { Link, useLocation } from "react-router-dom";
import { ChevronDown, MenuIcon, Users, FileText, ClipboardList, CalendarDays, ListChecks, Phone } from "lucide-react";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { usePermissions } from "@/hooks/usePermissions";
import NotificationBell from "@/components/NotificationBell";
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
    return ADMIN_NAV_V2
      .map((g) => ({
        ...g,
        entries: g.entries.filter((e) => {
          if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
          if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
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
        className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap transition"
        style={{
          color: active ? colors.brand : colors.onSurface,
          backgroundColor: active ? colors.brandTertiary : "transparent",
        }}
        data-testid={`admin-topbar-${group.key}`}
      >
        <CatIcon size={16} />
        <span>{group.label}</span>
        <ChevronDown size={14} className="opacity-70" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[280px] max-h-[70vh] overflow-y-auto"
        data-testid={`admin-topbar-${group.key}-menu`}
      >
        {group.noSub.map((e) => (
          <EntryItem key={e.to} e={e} />
        ))}
        {group.noSub.length > 0 && Object.keys(group.bySub).length > 0 ? (
          <DropdownMenuSeparator />
        ) : null}
        {Object.entries(group.bySub).map(([sub, entries], i, arr) => (
          <React.Fragment key={sub}>
            <DropdownMenuLabel className="text-[10px] uppercase tracking-wider opacity-60">
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
  const Icon = e.icon;
  return (
    <DropdownMenuItem asChild data-testid={`admin-topbar-link-${e.to.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}>
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
          color: colors.onSurface,
          borderColor: colors.border,
          backgroundColor: colors.surface,
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
 *  strip is suppressed (no empty container). */
function QuickAccessRow() {
  const { effectiveRole } = usePermissions();
  const items = [
    { to: "/customers",                     label: "Customers",   icon: Users,        roles: ["admin", "super_admin"] },
    { to: "/invoices",                       label: "Invoices",    icon: FileText,     roles: ["admin", "super_admin"] },
    { to: "/quotes",                         label: "Estimates",   icon: ClipboardList, roles: ["admin", "super_admin"] },
    { to: "/schedule/calendar",              label: "Schedule",    icon: CalendarDays, roles: ["admin", "super_admin", "technician"] },
    { to: "/jobs",                            label: "Workstream",  icon: ListChecks,   roles: ["admin", "super_admin", "technician", "customer"] },
    { to: "/admin/settings/ringcentral",      label: "RingCentral", icon: Phone,        roles: ["admin", "super_admin"] },
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


export default function AdminTopBar() {
  const visible = useVisibleGroups();
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

  if (visible.length === 0) return null;
  return (
    <div
      className="sticky top-0 z-30 w-full border-b"
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
      }}
      data-testid="admin-topbar"
      data-vw={vw}
      data-narrow={isNarrow ? "1" : "0"}
    >
      {/* Phase 55 — pinned Quick Access strip. Rendered above the
          6-category dropdowns / mobile menu so it stays reachable
          in one tap without changing existing behavior. */}
      <QuickAccessRow />
      {isNarrow ? (
        <div
          className="px-4 h-11 flex items-center justify-between"
          data-testid="admin-topbar-narrow-wrap"
        >
          <MobileMenu visible={visible} />
          <NotificationBell variant="inline" />
        </div>
      ) : (
        <div
          className="flex items-center gap-1 px-4 h-11 overflow-x-auto"
          data-testid="admin-topbar-wide-wrap"
        >
          {visible.map((g) => (
            <CategoryDropdown key={g.key} group={g} />
          ))}
          <div className="ml-auto shrink-0">
            <NotificationBell variant="inline" />
          </div>
        </div>
      )}
    </div>
  );
}
