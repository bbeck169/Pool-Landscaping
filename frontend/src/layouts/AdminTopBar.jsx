/**
 * Phase K75 · Feb-2026 — Web top navigation bar.
 *
 * Reshelled from the Phase 44 category-dropdowns-row layout. The
 * top bar now renders a role-appropriate FIXED item set (see
 * ``nav/topNavRegistry.js``) plus, for admin / super_admin /
 * manager, a single "More" dropdown that houses the six
 * ``ADMIN_NAV_V2`` categories so deep pages remain reachable in
 * ≤ 2 clicks.
 *
 * Shell contract preserved (locked by ``header-cleanup-bell-cluster``
 * and friends):
 *   • Three DOM branches — ``admin-topbar-tech-wrap`` (no fixed
 *     items → customer / no-role only), ``admin-topbar-narrow-wrap``
 *     (<768px viewport), ``admin-topbar-wide-wrap`` (default).
 *   • Each branch ends with the right cluster in this order:
 *     AddCustomerButton · CreditsBudgetChip · SettingsSprocket ·
 *     SignOutButton · UniversalMenu (variant='inline'). Sign-out
 *     sits to the LEFT of the bell + hamburger cluster.
 *   • Root bar carries ``colors.nav.bg`` (K50 navy chrome).
 *   • Active + hover state on every top-nav chip renders
 *     ``colors.nav.bgActiveNavy`` (K64 canonical). No brandGradient.
 *   • No BrandLogo — the side-rail crown in ``AppLayout`` is the
 *     single source of truth for the desktop brand mark.
 */
import React, { useMemo } from "react";
import { NavLink, Link, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, MenuIcon, LogOut, Plus as PlusIcon } from "lucide-react";
import { ADMIN_NAV_V2 } from "@/nav/adminNav";
import { topNavForRole, showMoreDropdownForRole } from "@/nav/topNavRegistry";
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
 * K75 · Feb-2026 — same ``ADMIN_NAV_V2`` filter that used to drive
 * the six inline dropdowns. Retained verbatim (RBAC / feature-flag /
 * hard-rule semantics) because the "More" dropdown still surfaces
 * these categories.
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
 * K75 · fixed top-nav chip. Renders a NavLink with the K64 active +
 * hover treatment (both = ``colors.nav.bgActiveNavy``) so the top
 * bar's visual language matches the left rail and the sub-nav
 * pills sitewide.
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
 * K75 · "More" dropdown — houses the six ``ADMIN_NAV_V2`` categories
 * under a single trigger so the top nav's 7 fixed items don't
 * amputate reach to the ~130 deep admin pages. Panel matches the
 * K52 Slice B navy popover styling (see ``CategoryDropdown`` in
 * pre-K75 history — this is the same treatment, wider panel).
 */
function MoreDropdown({ visible }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="group inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap transition-all duration-200 ease-out will-change-transform hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02]"
        style={{ color: colors.nav.fg, background: "transparent" }}
        onMouseEnter={(e) => { e.currentTarget.style.background = colors.nav.bgActiveNavy; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        data-testid="top-nav-more-trigger"
      >
        <span>More</span>
        <ChevronDown size={14} className="opacity-70 transition-transform duration-200 group-hover:translate-y-[1px]" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[320px] max-h-[70vh] overflow-y-auto p-1 border-0 shadow-xl [&_[role=menuitem]]:text-white [&_[role=menuitem]]:cursor-pointer [&_[role=menuitem]:focus]:bg-[#2A2F7A] [&_[role=menuitem]:focus]:text-white [&_[role=menuitem]:hover]:bg-[#2A2F7A] [&_[role=menuitem]:hover]:text-white [&_[data-radix-menu-label]]:text-white/72 [&_[role=separator]]:bg-white/10"
        style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg }}
        data-testid="top-nav-more-menu"
        data-k52-navy-popover="true"
      >
        {visible.map((g, i, arr) => {
          const CatIcon = g.icon;
          return (
            <React.Fragment key={g.key}>
              <DropdownMenuLabel
                className="text-[11px] uppercase tracking-wider flex items-center gap-1.5"
                style={{ color: colors.nav.fgMuted }}
              >
                {CatIcon ? <CatIcon size={12} className="opacity-80" /> : null}
                {g.label}
              </DropdownMenuLabel>
              {g.noSub.map((e) => <EntryItem key={e.to} e={e} />)}
              {g.noSub.length > 0 && Object.keys(g.bySub).length > 0 ? (
                <DropdownMenuSeparator />
              ) : null}
              {Object.entries(g.bySub).map(([sub, entries], j, subArr) => (
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
              {i < arr.length - 1 ? <DropdownMenuSeparator /> : null}
            </React.Fragment>
          );
        })}
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
      data-testid={`top-nav-more-link-${e.to.replace(/^\/+/, "").replace(/\//g, "-") || "root"}`}
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
 * Narrow-viewport "Menu" trigger — flattens the K75 fixed items +
 * the six ADMIN_NAV_V2 categories into a single dropdown so the
 * <768px shell reaches every page in one tap. Mirrors the pre-K75
 * mobile menu behaviour byte-for-byte.
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
            {visible.length > 0 ? <DropdownMenuSeparator /> : null}
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
  const _auth = useAuth();
  const { effectiveRole } = usePermissions();
  const _role = effectiveRole || _auth?.user?.role || "";

  // K75 · Feb-2026 — fixed items sourced from the role registry.
  const fixedItems = topNavForRole(_role);
  const showMore = showMoreDropdownForRole(_role) && visible.length > 0;

  // Phase 44 · Fix A (attempt 3) — bulletproof responsive gate.
  const [vw, setVw] = React.useState(() =>
    typeof window !== "undefined" ? window.innerWidth : 1024);
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const on = () => setVw(window.innerWidth);
    on();
    window.addEventListener("resize", on);
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

  if (!_role) return null;

  return (
    <div
      className="sticky top-0 z-30 w-full border-b backdrop-blur-[2px]"
      style={{
        backgroundColor: colors.nav.bg,
        borderColor: colors.nav.border,
      }}
      data-testid="admin-topbar"
      data-vw={vw}
      data-narrow={isNarrow ? "1" : "0"}
    >
      {fixedItems.length === 0 ? (
        // No fixed items for this role (customer / customer_portal /
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
      ) : isNarrow ? (
        <div
          className="px-4 h-11 flex items-center justify-between"
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
      ) : (
        <div
          className="flex items-center gap-1 px-4 h-11 overflow-x-auto"
          data-testid="admin-topbar-wide-wrap"
        >
          {fixedItems.map((it) => <TopNavChip key={it.key} item={it} />)}
          {showMore ? <MoreDropdown visible={visible} /> : null}
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
