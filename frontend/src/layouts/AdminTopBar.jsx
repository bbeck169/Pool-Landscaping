/**
 * Phase K76 · Feb-2026 — Web top navigation bar.
 *
 * Walks back the K75 7-fixed-items + "More" dropdown shape. The
 * top bar now renders the ``ADMIN_NAV_V2`` category dropdowns
 * directly (Finance / AI Employees / Marketing / Operations /
 * Customers / Reports / Communications / Reviews) for admin /
 * super_admin / manager — matching the pre-K75 AdminTopBar
 * layout. The left Quick Access rail (K75 Step B) already covers
 * the seven high-frequency shortcuts that K75's fixed strip
 * duplicated, so a separate fixed strip is redundant.
 *
 * Role scoping:
 *   • admin / super_admin / manager  → ``CategoryDropdown`` per
 *     visible group. No fixed items, no "More" dropdown.
 *   • technician                     → 6 fixed chips from
 *     ``TECH_TOP_NAV``.
 *   • customer / customer_portal     → right-cluster only (mounts
 *     its own ``<UniversalMenu>`` via ``<AppLayout>``).
 *
 * Shell contract preserved (locked by ``k75-top-nav`` + friends):
 *   • Three DOM branches — ``admin-topbar-tech-wrap`` (no fixed
 *     items → customer / no-role only), ``admin-topbar-narrow-wrap``
 *     (<768px viewport), ``admin-topbar-wide-wrap`` (default).
 *   • Each branch ends with the right cluster in this order:
 *     AddCustomerButton · CreditsBudgetChip · SettingsSprocket ·
 *     SignOutButton · UniversalMenu (variant='inline'). Sign-out
 *     sits to the LEFT of the bell + hamburger cluster.
 *   • Root bar carries ``colors.nav.bg`` (K50 navy chrome, K74
 *     solid ``#1B1F5C``).
 *   • Active + hover state on every top-nav chip / category
 *     trigger renders ``colors.nav.bgActiveNavy`` (K64 canonical).
 *     No ``brandGradient`` on top nav surfaces.
 *   • No BrandLogo — the side-rail crown in ``AppLayout`` is the
 *     single source of truth for the desktop brand mark.
 */
import React, { useMemo } from "react";
import { NavLink, Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, MenuIcon, LogOut, Plus as PlusIcon } from "lucide-react";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { topNavForRole } from "@/nav/topNavRegistry";
import { usePermissions } from "@/hooks/usePermissions";
import { useAuth } from "@/auth";
import { colors, gradients } from "@/theme";
import UniversalMenu from "@/layouts/UniversalMenu";
import CreditsBudgetChip from "@/components/AIDock/CreditsBudgetChip";
import { Settings as SettingsIcon } from "lucide-react";
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


/**
 * K76 · Feb-2026 — same ``ADMIN_NAV_V2`` filter used by the pre-K75
 * top bar (retained byte-for-byte from K75 for RBAC / feature-flag /
 * hard-rule parity). Returns [] for non-admin roles so the tech +
 * customer branches short-circuit.
 */
function useVisibleGroups() {
  const { can, effectiveRole } = usePermissions();
  return useMemo(() => {
    if (!["admin", "super_admin", "manager"].includes(effectiveRole)) {
      return [];
    }
    return ADMIN_NAV_V2
      .map((g) => ({
        ...g,
        entries: g.entries.filter((e) => {
          if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
          if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
          if (e.hard_rule === "manager_only") {
            return ["super_admin", "admin", "manager"].includes(effectiveRole);
          }
          return can(e.feature || "dashboard", "read") || effectiveRole === "admin";
        }),
      }))
      .filter((g) => g.entries.length > 0)
      .map((g) => {
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


/**
 * K76 · fixed top-nav chip. Renders a NavLink with the K64 active +
 * hover treatment (both = ``colors.nav.bgActiveNavy``). Used for
 * the technician's 6-item fixed strip.
 */
function TopNavChip({ item }) {
  const { key, to, label, Icon, end } = item;
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        [
          "group inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap",
          "transition-all duration-200 ease-out will-change-transform",
          "hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02]",
          isActive ? "shadow-[0_1px_2px_rgba(0,0,0,0.15)]" : "",
        ].join(" ")
      }
      style={({ isActive }) => ({
        color: colors.nav.fg,
        background: isActive ? colors.nav.bgActiveNavy : "transparent",
      })}
      onMouseEnter={(e) => { e.currentTarget.style.background = colors.nav.bgActiveNavy; }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background =
          e.currentTarget.getAttribute("aria-current") === "page"
            ? colors.nav.bgActiveNavy
            : "transparent";
      }}
      data-testid={`top-nav-${key}`}
      aria-label={label}
      title={label}
    >
      {Icon ? <Icon size={16} className="transition-colors duration-200" /> : null}
      <span className="transition-colors duration-200">{label}</span>
    </NavLink>
  );
}


/**
 * K76 · category dropdown trigger. One per ``ADMIN_NAV_V2`` group.
 * Renders the group label with a chevron; opening the trigger
 * surfaces a K52-canonical navy popover (the ``data-k52-navy-popover``
 * marker is preserved for the popover-styling grep-lock).
 *
 * Hover / open state = solid ``colors.nav.bgActiveNavy`` (K64
 * canonical). NO ``brandGradient`` and NO green-tinted pill.
 */
function CategoryDropdown({ group }) {
  const CatIcon = group.icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="group inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap transition-all duration-200 ease-out will-change-transform hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02] data-[state=open]:!bg-[color:var(--nav-bg-active-navy)]"
        style={{
          color: colors.nav.fg,
          background: "transparent",
          // Expose the K64 canonical as a CSS var so the
          // ``data-[state=open]`` selector can lock it in without a
          // JS handler racing the Radix state.
          "--nav-bg-active-navy": colors.nav.bgActiveNavy,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = colors.nav.bgActiveNavy; }}
        onMouseLeave={(e) => {
          if (e.currentTarget.getAttribute("data-state") !== "open") {
            e.currentTarget.style.background = "transparent";
          }
        }}
        data-testid={`admin-topbar-${group.key}`}
        aria-label={group.label}
      >
        {CatIcon ? <CatIcon size={16} className="opacity-90" /> : null}
        <span>{group.label}</span>
        <ChevronDown size={14} className="opacity-70 transition-transform duration-200 group-hover:translate-y-[1px]" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[280px] max-h-[70vh] overflow-y-auto p-1 border-0 shadow-xl [&_[role=menuitem]]:text-white [&_[role=menuitem]]:cursor-pointer [&_[role=menuitem]:focus]:bg-[#2A2F7A] [&_[role=menuitem]:focus]:text-white [&_[role=menuitem]:hover]:bg-[#2A2F7A] [&_[role=menuitem]:hover]:text-white [&_[data-radix-menu-label]]:text-white/72 [&_[role=separator]]:bg-white/10"
        style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg }}
        data-testid={`admin-topbar-${group.key}-menu`}
        data-k52-navy-popover="true"
      >
        {group.noSub.map((e) => <EntryItem key={e.to} e={e} />)}
        {group.noSub.length > 0 && Object.keys(group.bySub).length > 0 ? (
          <DropdownMenuSeparator />
        ) : null}
        {Object.entries(group.bySub).map(([sub, entries], j, subArr) => (
          <React.Fragment key={sub}>
            <DropdownMenuLabel
              className="text-[10px] uppercase tracking-wider pl-4"
              style={{ color: colors.nav.fgMuted }}
            >
              {sub}
            </DropdownMenuLabel>
            {entries.map((e) => <EntryItem key={e.to} e={e} />)}
            {j < subArr.length - 1 ? <DropdownMenuSeparator /> : null}
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
      data-testid={`top-nav-cat-link-${e.to.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}
      data-active={active ? "true" : "false"}
      style={active ? {
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


/**
 * Narrow-viewport "Menu" trigger — flattens the admin category
 * dropdowns OR the technician's fixed strip into a single
 * dropdown so the <768px shell reaches every page in one tap.
 *
 * For admin/manager/super_admin: ``visible.length > 0`` and
 * ``fixedItems.length === 0``, so this renders the categories only.
 *
 * For technician: ``visible.length === 0`` and
 * ``fixedItems.length > 0``, so this renders the fixed strip only.
 */
function MobileMenu({ visible, fixedItems }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold border"
        style={{
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
        {fixedItems.length > 0 ? (
          <>
            <DropdownMenuLabel className="text-[10px] uppercase tracking-wider opacity-60">
              Primary
            </DropdownMenuLabel>
            {fixedItems.map((it) => {
              const ItIcon = it.Icon;
              return (
                <DropdownMenuItem asChild key={it.to}
                  data-testid={`admin-topbar-mobile-primary-${it.key}`}
                >
                  <Link to={it.to} className="flex items-center gap-2 cursor-pointer">
                    {ItIcon ? <ItIcon size={14} className="opacity-80 shrink-0" /> : null}
                    <span className="truncate">{it.label}</span>
                  </Link>
                </DropdownMenuItem>
              );
            })}
          </>
        ) : null}
        {visible.map((g) => {
          const CatIcon = g.icon;
          return (
            <DropdownMenuSub key={g.key}>
              <DropdownMenuSubTrigger
                data-testid={`admin-topbar-mobile-${g.key}`}
                className="flex items-center gap-2"
              >
                {CatIcon ? <CatIcon size={14} className="opacity-80" /> : null}
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
  const _auth = useAuth();
  const { effectiveRole } = usePermissions();
  const _role = effectiveRole || _auth?.user?.role || "";

  // K76 · Feb-2026 — fixed items ONLY populate for the technician
  // role now. Admin/manager/super_admin render category dropdowns
  // via ``visible`` instead.
  const fixedItems = topNavForRole(_role);

  // K76.1 · Feb-2026 — mobile-web breakpoint collapse regression fix.
  // The prior JS ``resize``-listener approach was unreliable in some
  // mobile browsers (Mobile Safari fires ``resize`` only on orientation
  // change; embedded WebViews sometimes never fire it at all), which
  // left the desktop wide-wrap rendered below 768px. Switching to a
  // pure CSS media-query gate via Tailwind's ``md:`` breakpoint (768px
  // threshold) — both branches are always in the DOM, CSS decides
  // which one is visible. No hydration timing, no event-listener race,
  // works in every real browser + jsdom (where the width is exposed
  // via ``matchMedia``).  A ``useSyncExternalStore`` mirror on
  // ``matchMedia("(max-width: 767.98px)")`` is retained so vitest
  // snapshots can still assert the branch selection deterministically.
  const isNarrow = React.useSyncExternalStore(
    (cb) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mq = window.matchMedia("(max-width: 767.98px)");
      if (mq.addEventListener) mq.addEventListener("change", cb);
      else mq.addListener(cb);
      return () => {
        if (mq.removeEventListener) mq.removeEventListener("change", cb);
        else mq.removeListener(cb);
      };
    },
    () => (typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia("(max-width: 767.98px)").matches
      : false),
    () => false,
  );

  if (!_role) return null;

  // Admin surface = category dropdowns; tech surface = fixed strip.
  const hasAdminNav = visible.length > 0;
  const hasTechNav = fixedItems.length > 0;
  const hasAnyNav = hasAdminNav || hasTechNav;

  return (
    <div
      className="sticky top-0 z-30 w-full border-b backdrop-blur-[2px]"
      style={{
        backgroundColor: colors.nav.bg,
        borderColor: colors.nav.border,
      }}
      data-testid="admin-topbar"
      data-narrow={isNarrow ? "1" : "0"}
    >
      {!hasAnyNav ? (
        // No nav for this role (customer / customer_portal /
        // unknown). Right-cluster only — the customer portal mounts
        // its own <UniversalMenu> via <AppLayout>, so this branch
        // rarely renders in production but is kept for defensive
        // parity with pre-K75 behaviour.
        <div
          className="px-4 h-11 flex items-center justify-end gap-2"
          data-testid="admin-topbar-tech-wrap"
        >
          <SettingsSprocket />
          <SignOutButton />
          <UniversalMenu variant="inline" />
        </div>
      ) : (
        <>
          {/* Narrow (<768px) — hamburger + right cluster. CSS-gated so */}
          {/* mobile browsers that don't fire resize still see it. */}
          <div
            className="md:hidden px-4 h-11 flex items-center justify-between"
            data-testid="admin-topbar-narrow-wrap"
          >
            <MobileMenu visible={visible} fixedItems={fixedItems} />
            <div className="flex items-center gap-2">
              <AddCustomerButton />
              <CreditsBudgetChip />
              <SettingsSprocket />
              <SignOutButton />
              <UniversalMenu variant="inline" />
            </div>
          </div>
          {/* Wide (>=768px) — inline categories or fixed strip. */}
          <div
            className="hidden md:flex items-center gap-1 px-4 h-11 overflow-x-auto"
            data-testid="admin-topbar-wide-wrap"
          >
            {hasAdminNav
              ? visible.map((g) => <CategoryDropdown key={g.key} group={g} />)
              : fixedItems.map((it) => <TopNavChip key={it.key} item={it} />)}
            <div className="ml-auto shrink-0 flex items-center gap-2">
              <AddCustomerButton />
              <CreditsBudgetChip />
              <SettingsSprocket />
              <SignOutButton />
              <UniversalMenu variant="inline" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}


// Phase 21 · Feb 2026 — "+ Add Customer" quick-action, admin+ only.
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
      style={{ background: gradients.navyToGreen.css }}
      data-testid="topbar-add-customer-btn"
      aria-label="Add customer"
    >
      <PlusIcon size={14} /> Add Customer
    </button>
  );
}


// Feb-2026 · Settings Hub sprocket — admin+ only.
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


// Feb-2026 · Sign-out — shared handler; matches the shadcn destructive
// variant spec (K54 canonical red).
function SignOutButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  if (!auth?.user) return null;
  const onLogout = () => {
    try { auth.logout && auth.logout(); } finally {
      navigate("/login", { replace: true });
    }
  };
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
