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
import { ChevronDown, MenuIcon } from "lucide-react";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { usePermissions } from "@/hooks/usePermissions";
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

export default function AdminTopBar() {
  const visible = useVisibleGroups();
  // Phase 44 · Fix 1 — some Tailwind builds don't reliably purge/JIT the
  // `hidden md:flex` / `md:hidden` combo in ad-hoc layouts (verified in
  // the e1_tester report where <md viewport still rendered the wide row).
  // Use an explicit `matchMedia` gate instead of relying on Tailwind
  // responsive utilities. `768px` mirrors Tailwind's default `md`.
  const [isNarrow, setIsNarrow] = React.useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia && window.matchMedia("(max-width: 767px)").matches;
  });
  React.useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(max-width: 767px)");
    const on = (e) => setIsNarrow(e.matches);
    // `addEventListener` is the modern API; `addListener` is the
    // Safari-<14 fallback. Both are exposed by every browser we
    // support today.
    if (mq.addEventListener) mq.addEventListener("change", on);
    else mq.addListener(on);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", on);
      else mq.removeListener(on);
    };
  }, []);

  if (visible.length === 0) return null;
  return (
    <div
      className="sticky top-0 z-30 w-full border-b"
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
      }}
      data-testid="admin-topbar"
    >
      {isNarrow ? (
        <div
          className="px-4 h-11 flex items-center"
          data-testid="admin-topbar-narrow-wrap"
        >
          <MobileMenu visible={visible} />
        </div>
      ) : (
        <div
          className="flex items-center gap-1 px-4 h-11 overflow-x-auto"
          data-testid="admin-topbar-wide-wrap"
        >
          {visible.map((g) => (
            <CategoryDropdown key={g.key} group={g} />
          ))}
        </div>
      )}
    </div>
  );
}
