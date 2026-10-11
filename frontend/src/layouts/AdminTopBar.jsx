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
 *     AddCustomerButton · … · SettingsSprocket · NotificationBell ·
 *     SignOutButton (Feb-2026 AdminTopBar cleanup — CreditsBudgetChip
 *     and QuickAddButton dropped; the ``inline`` UniversalMenu was
 *     replaced by a standalone ``NotificationBell``; Sign-out is
 *     the far-right element).
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
// Phase P52 · Feb 2026 — LanguageSelector removed from the topbar.
// Tenant-scoped default locale is now driven by Global Settings
// (see routers/finances.patch_tenant_settings + auth.jsx
// hydration of localStorage.tenant_default_locale).  Personal user
// pref still lives in ``localStorage.lang`` (Phase D3) and can be
// changed from a settings surface — the top-bar globe is gone.
import { ADMIN_NAV_V2, filterNavByIndustries } from "@/nav/adminNav";
import { topNavForRole } from "@/nav/topNavRegistry";
import { usePermissions } from "@/hooks/usePermissions";
import { useIndustries } from "@/hooks/useIndustries";
import { useAuth } from "@/auth";
import { useIsNarrow } from "@/hooks/useIsNarrow";
import { colors, gradients } from "@/theme";
// Feb-2026 · AdminTopBar cleanup — standalone NotificationBell now
// mounted directly in the right-cluster (was previously routed
// through ``UniversalMenu``, which also brought a hamburger trigger
// AdminTopBar no longer needs).  UniversalMenu itself is unchanged
// and remains in use by the customer-portal ``AppLayout`` header.
import NotificationBell from "@/components/NotificationBell";
// Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — unified ⌘K palette.
// Mounted once at the top bar so the shortcut works from every
// admin route without every ``<PageHeader>`` shipping its own
// listener. Self-gates its rendering (returns null when closed).
import GlobalSearch from "@/components/GlobalSearch";
// Feb-2026 · Restore visible universal search — primary quick-find
// entry point, always mounted app-wide.  The ⌘K palette (above)
// remains as the modal shortcut alongside it; both consume the
// same ``useGlobalSearchResults`` hook so the shape drift between
// entry points can never diverge.
// Feb-2026 · Mobile Nav Duplicate Fix — mount RolePreviewSwitcher in
// the narrow-branch right-cluster so super_admin keep one-tap "Test
// as" access on mobile after Row 1 (the legacy AppLayout mobile
// <header>) was gated off for AdminTopBar-mounting roles. Component
// self-gates via ``canPreview`` so it's a no-op for non-super_admin.
import RolePreviewSwitcher from "@/components/RolePreviewSwitcher";
import { Settings as SettingsIcon } from "lucide-react";
// Phase T1.5 · Feb-2026 — multi-tenant switcher (auto-hidden for
// single-tenant users). Sits next to the "your world" controls
// on the wide-branch cluster.
import TenantSwitcher from "@/components/topbar/TenantSwitcher";
// Phase 8 · Feb-2026 — Marco wake-word arm-on-click toggle.  Mounted
// on the right cluster so admin / super_admin / manager / owner can
// explicitly arm the mic (no auto-start).  The button self-gates on
// role + SpeechRecognition support and returns null everywhere
// Marco wake isn't available, so we don't widen the role surface.
import { MicToggleButton } from "@/components/marco/MarcoMicController";
// Phase A1 · Feb-2026 — Proactive Intelligence alert bell. The
// component itself is self-gated to admin/super_admin (fail-closed
// on loading auth state); ``AdminBellSlot`` below adds a second
// belt-and-braces gate at the AdminTopBar level so we never even
// mount the component tree for tech / customer / manager /
// dispatcher / marketer / sales sessions, matching the backend
// ``insufficient_role_for_alerts`` contract exactly.
import AlertBell from "@/components/nav/AlertBell";
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
  // Phase Feb-2026 · Multi-industry Phase C — same filter applied
  // in AdminSidebar; keeps the two nav surfaces in sync so a
  // pool-only tenant never sees a "Landscape AI" chip in the top
  // bar while it's hidden from the sidebar.
  const { industries } = useIndustries();
  return useMemo(() => {
    if (!["admin", "super_admin", "manager"].includes(effectiveRole)) {
      return [];
    }
    return ADMIN_NAV_V2
      .map((g) => ({
        ...g,
        entries: filterNavByIndustries(g.entries, industries).filter((e) => {
          if (e.hard_rule === "admin_only" && effectiveRole !== "admin") return false;
          if (e.hard_rule === "super_admin_only" && effectiveRole !== "super_admin") return false;
          // Phase A1 · Feb-2026 — Proactive Intelligence.
          // Mirrors the backend ``insufficient_role_for_alerts`` gate
          // exactly (admin + super_admin, no manager, no technician).
          if (e.hard_rule === "admin_or_super_admin") {
            return ["admin", "super_admin"].includes(effectiveRole);
          }
          if (e.hard_rule === "manager_only") {
            return ["super_admin", "admin", "manager"].includes(effectiveRole);
          }
          return can(e.feature || "dashboard", "read") || effectiveRole === "admin";
        }),
      }))
      .filter((g) => g.entries.length > 0)
      .map((g) => {
        // TOP-NAV-RESTRUCTURE · Feb-2026 — build an ORDERED list
        // of ``sections`` so the dropdown can emit nested
        // submenus (``kind: "nested"``), classic flat subsection
        // headers (``kind: "subsection"``), or raw rows
        // (``kind: "flat"``) in the exact author-ordered sequence
        // they appear in ``ADMIN_NAV_V2``.  Each run of
        // consecutive entries sharing the same
        // ``(nested, subsection)`` tuple collapses into one
        // section.  ``noSub`` + ``bySub`` are retained for
        // legacy call sites (none remain in-tree but keeps the
        // shape forward-compatible for the Expo specialist's
        // mobile parity brief).
        const sections = [];
        const bySub = {};
        const noSub = [];
        let cur = null;
        for (const e of g.entries) {
          const nested = e.nested || null;
          const subsection = e.subsection || null;
          const kind = nested ? "nested" : (subsection ? "subsection" : "flat");
          const label = nested || subsection || null;
          if (!cur || cur.kind !== kind || cur.label !== label) {
            cur = { kind, label, entries: [] };
            sections.push(cur);
          }
          cur.entries.push(e);
          // Legacy mirrors (preserved for backwards-compat).
          if (subsection) {
            (bySub[subsection] = bySub[subsection] || []).push(e);
          } else if (!nested) {
            noSub.push(e);
          }
        }
        return { ...g, sections, noSub, bySub };
      });
  }, [can, effectiveRole, industries]);
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
      onMouseEnter={(e) => {
        e.currentTarget.style.background = colors.nav.bgActiveNavy;
        // NAV-restyle · Feb-2026 — layer the blue hover glow on
        // top of the K64 navy hover-bg + K75 scale. Suppressed on
        // active items (``aria-current="page"``) so the active
        // pill stays static and the idle/hover distinction is
        // crisp. Ruling R11 · Option A.
        if (e.currentTarget.getAttribute("aria-current") !== "page") {
          e.currentTarget.style.boxShadow = colors.nav.hoverGlow;
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background =
          e.currentTarget.getAttribute("aria-current") === "page"
            ? colors.nav.bgActiveNavy
            : "transparent";
        e.currentTarget.style.boxShadow = "";
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
  const location = useLocation();
  // TOP-NAV-RESTRUCTURE · Feb-2026 — active-state propagation.
  // Any entry across every section (flat / subsection / nested)
  // whose ``to`` matches the current pathname lights up the
  // top-level trigger pill.  Also builds a per-nested-label
  // "has active child" map so the nested ``SubTrigger`` can
  // match (Operations → AI Operations row glows when a child
  // route like ``/admin/copilot`` is active).
  const nestedActive = {};
  let anyActive = false;
  for (const s of (group.sections || [])) {
    for (const e of s.entries) {
      if (location.pathname === e.to) {
        anyActive = true;
        if (s.kind === "nested") nestedActive[s.label] = true;
      }
    }
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="group inline-flex items-center gap-1.5 px-3 h-9 rounded-md text-sm font-semibold whitespace-nowrap transition-all duration-200 ease-out will-change-transform hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02] data-[state=open]:!bg-[color:var(--nav-bg-active-navy)]"
        style={{
          color: colors.nav.fg,
          background: anyActive ? colors.nav.bgActiveNavy : "transparent",
          // Expose the K64 canonical as a CSS var so the
          // ``data-[state=open]`` selector can lock it in without a
          // JS handler racing the Radix state.
          "--nav-bg-active-navy": colors.nav.bgActiveNavy,
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = colors.nav.bgActiveNavy;
          // NAV-restyle · Feb-2026 — layer the blue hover glow.
          // Suppressed while the dropdown is OPEN (``data-state``)
          // so the open trigger reads as a static pinned pill.
          // Ruling R11 · Option A.
          if (e.currentTarget.getAttribute("data-state") !== "open") {
            e.currentTarget.style.boxShadow = colors.nav.hoverGlow;
          }
        }}
        onMouseLeave={(e) => {
          if (e.currentTarget.getAttribute("data-state") !== "open") {
            e.currentTarget.style.background = anyActive
              ? colors.nav.bgActiveNavy
              : "transparent";
          }
          e.currentTarget.style.boxShadow = "";
        }}
        data-testid={`admin-topbar-${group.key}`}
        data-active={anyActive ? "true" : "false"}
        aria-label={group.label}
      >
        {CatIcon ? <CatIcon size={16} className="opacity-90" /> : null}
        <span>{group.label}</span>
        <ChevronDown size={14} className="opacity-70 transition-transform duration-200 group-hover:translate-y-[1px]" />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="min-w-[280px] max-h-[70vh] overflow-y-auto p-1 border-0 shadow-xl [&_[role=menuitem]]:text-white [&_[role=menuitem]]:cursor-pointer [&_[role=menuitem]:focus]:bg-[#2A2F7A] [&_[role=menuitem]:focus]:text-white [&_[role=menuitem]:hover]:bg-[#2A2F7A] [&_[role=menuitem]:hover]:text-white [&_[role=menuitem]:hover]:shadow-[0_0_10px_#3B82F6] [&_[role=menuitem]:focus]:shadow-[0_0_10px_#3B82F6] [&_[role=menuitem]]:transition-shadow [&_[role=menuitem]]:duration-200 [&_[data-radix-menu-label]]:text-white/72 [&_[role=separator]]:bg-white/25"
        style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg }}
        data-testid={`admin-topbar-${group.key}-menu`}
        data-k52-navy-popover="true"
        collisionPadding={8}
      >
        {(group.sections || []).map((s, j, arr) => {
          const isLast = j === arr.length - 1;
          // Separator between non-first sections of DIFFERENT kinds
          // or labels — keeps the visual grouping tight.
          const needsLeadSep = j > 0;
          if (s.kind === "nested") {
            const subKey = `nested-${s.label}-${j}`;
            const subActive = !!nestedActive[s.label];
            return (
              <React.Fragment key={subKey}>
                {needsLeadSep ? (
                  <DropdownMenuSeparator className="h-[2px] bg-white/25" />
                ) : null}
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger
                    data-testid={`admin-topbar-${group.key}-nested-${slug(s.label)}`}
                    data-active={subActive ? "true" : "false"}
                    className="flex items-center gap-2 pl-3 cursor-pointer text-white data-[state=open]:bg-[#2A2F7A]"
                    style={subActive ? {
                      backgroundColor: colors.nav.bgActive,
                      color: colors.nav.fgActive,
                    } : undefined}
                  >
                    <span className="truncate font-semibold">{s.label}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuPortal>
                    <DropdownMenuSubContent
                      className="min-w-[260px] max-h-[70vh] overflow-y-auto p-1 border-0 shadow-xl [&_[role=menuitem]]:text-white [&_[role=menuitem]]:cursor-pointer [&_[role=menuitem]:focus]:bg-[#2A2F7A] [&_[role=menuitem]:focus]:text-white [&_[role=menuitem]:hover]:bg-[#2A2F7A] [&_[role=menuitem]:hover]:text-white [&_[role=menuitem]:hover]:shadow-[0_0_10px_#3B82F6] [&_[role=menuitem]:focus]:shadow-[0_0_10px_#3B82F6] [&_[role=menuitem]]:transition-shadow [&_[role=menuitem]]:duration-200 [&_[data-radix-menu-label]]:text-white/72 [&_[role=separator]]:bg-white/25"
                      style={{ backgroundColor: colors.nav.bg, color: colors.nav.fg }}
                      data-testid={`admin-topbar-${group.key}-nested-${slug(s.label)}-menu`}
                      data-k52-navy-popover="true"
                      collisionPadding={8}
                    >
                      {s.entries.map((e, k) => (
                        <React.Fragment key={e.to}>
                          {e.nestedDivider && k > 0 ? (
                            <>
                              <DropdownMenuSeparator className="h-[2px] bg-white/25" />
                              <DropdownMenuLabel
                                className="pl-3"
                                style={{
                                  color: colors.nav.fg,
                                  backgroundColor: colors.nav.bgActiveNavy,
                                }}
                              >
                                <span className="inline-block px-3 py-1.5 text-xs font-bold uppercase tracking-wide opacity-80">
                                  Governance
                                </span>
                              </DropdownMenuLabel>
                            </>
                          ) : null}
                          <EntryItem e={e} />
                        </React.Fragment>
                      ))}
                    </DropdownMenuSubContent>
                  </DropdownMenuPortal>
                </DropdownMenuSub>
              </React.Fragment>
            );
          }
          if (s.kind === "subsection") {
            return (
              <React.Fragment key={`sub-${s.label}-${j}`}>
                {needsLeadSep ? (
                  <DropdownMenuSeparator className="h-[2px] bg-white/25" />
                ) : null}
                <DropdownMenuLabel
                  className="pl-3"
                  style={{
                    color: colors.nav.fg,
                    backgroundColor: colors.nav.bgActiveNavy,
                  }}
                >
                  <span className="inline-block px-3 py-1.5 text-base font-bold uppercase">
                    {s.label}
                  </span>
                </DropdownMenuLabel>
                {s.entries.map((e) => <EntryItem key={e.to} e={e} />)}
              </React.Fragment>
            );
          }
          // flat
          return (
            <React.Fragment key={`flat-${j}`}>
              {needsLeadSep ? (
                <DropdownMenuSeparator className="h-[2px] bg-white/25" />
              ) : null}
              {s.entries.map((e) => <EntryItem key={e.to} e={e} />)}
            </React.Fragment>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}


// TOP-NAV-RESTRUCTURE · Feb-2026 — tiny kebab-slugger for testids.
function slug(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
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
      <Link to={e.to} className="flex items-center gap-2 cursor-pointer pl-6">
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
            <DropdownMenuLabel
              className="pl-3"
              style={{
                color: colors.nav.fg,
                backgroundColor: colors.nav.bgActiveNavy,
              }}
            >
              <span className="inline-block px-3 py-1.5 text-base font-bold uppercase">
                Primary
              </span>
            </DropdownMenuLabel>
            {fixedItems.map((it) => {
              const ItIcon = it.Icon;
              return (
                <DropdownMenuItem asChild key={it.to}
                  data-testid={`admin-topbar-mobile-primary-${it.key}`}
                >
                  <Link to={it.to} className="flex items-center gap-2 cursor-pointer pl-6">
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
                <DropdownMenuSubContent className="min-w-[240px] max-h-[70vh] overflow-y-auto" collisionPadding={8}>
                  {(g.sections || []).map((s, j) => {
                    if (s.kind === "nested") {
                      return (
                        <DropdownMenuSub key={`m-nested-${s.label}-${j}`}>
                          <DropdownMenuSubTrigger
                            data-testid={`admin-topbar-mobile-${g.key}-nested-${slug(s.label)}`}
                            className="flex items-center gap-2 font-semibold"
                          >
                            <span className="truncate">{s.label}</span>
                          </DropdownMenuSubTrigger>
                          <DropdownMenuPortal>
                            <DropdownMenuSubContent
                              className="min-w-[240px] max-h-[70vh] overflow-y-auto"
                              data-testid={`admin-topbar-mobile-${g.key}-nested-${slug(s.label)}-menu`}
                              collisionPadding={8}
                            >
                              {s.entries.map((e, k) => (
                                <React.Fragment key={e.to}>
                                  {e.nestedDivider && k > 0 ? (
                                    <>
                                      <DropdownMenuSeparator className="h-[2px] bg-white/25" />
                                      <DropdownMenuLabel
                                        className="pl-3"
                                        style={{
                                          color: colors.nav.fg,
                                          backgroundColor: colors.nav.bgActiveNavy,
                                        }}
                                      >
                                        <span className="inline-block px-3 py-1.5 text-xs font-bold uppercase tracking-wide opacity-80">
                                          Governance
                                        </span>
                                      </DropdownMenuLabel>
                                    </>
                                  ) : null}
                                  <EntryItem e={e} />
                                </React.Fragment>
                              ))}
                            </DropdownMenuSubContent>
                          </DropdownMenuPortal>
                        </DropdownMenuSub>
                      );
                    }
                    if (s.kind === "subsection") {
                      return (
                        <React.Fragment key={`m-sub-${s.label}-${j}`}>
                          <DropdownMenuLabel
                            className="pl-3"
                            style={{
                              color: colors.nav.fg,
                              backgroundColor: colors.nav.bgActiveNavy,
                            }}
                          >
                            <span className="inline-block px-3 py-1.5 text-base font-bold uppercase">
                              {s.label}
                            </span>
                          </DropdownMenuLabel>
                          {s.entries.map((e) => <EntryItem key={e.to} e={e} />)}
                        </React.Fragment>
                      );
                    }
                    return (
                      <React.Fragment key={`m-flat-${j}`}>
                        {s.entries.map((e) => <EntryItem key={e.to} e={e} />)}
                      </React.Fragment>
                    );
                  })}
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}


// Phase A1 Hotfix · Feb-2026 — AdminTopBar-level bell gate.
// Belt-and-braces companion to the internal ``AlertBell`` role
// check. Uses ``effectiveRole`` (respects the "test as..." preview
// role) and ``auth.loading`` (fail-closed while the user object
// resolves). Every role EXCEPT admin + super_admin renders null,
// matching the backend ``insufficient_role_for_alerts`` gate.
function AdminBellSlot() {
  const auth = useAuth();
  const { effectiveRole } = usePermissions();
  const role = String(effectiveRole || auth?.user?.role || "").toLowerCase();
  if (auth?.loading) return null;
  if (!auth?.user) return null;
  if (role !== "admin" && role !== "super_admin") return null;
  return <AlertBell />;
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
  // works in every real browser + jsdom.
  //
  // Phase Hygiene B · Feb-2026 — the inline ``useSyncExternalStore``
  // subscription was extracted into ``useIsNarrow(breakpoint)`` and
  // reused across the app (see ``@/hooks/useIsNarrow``). Retain the
  // ``data-narrow`` attribute so vitest snapshots + integration
  // tests can still lock the branch selection deterministically.
  const isNarrow = useIsNarrow(768);

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
      {/* Phase GLOBAL-SEARCH-UNIFY · Feb-2026 — unified ⌘K palette.
          Mounts once so the shortcut listener is a singleton at
          the top bar. Renders NOTHING until the operator opens it
          via ``⌘K`` / ``Ctrl+K``. */}
      <GlobalSearch />
      {!hasAnyNav ? (
        // No nav for this role (customer / customer_portal /
        // unknown). Right-cluster only — the customer portal mounts
        // its own <UniversalMenu> via <AppLayout>, so this branch
        // rarely renders in production but is kept for defensive
        // parity with pre-K75 behaviour.
        //
        // Feb-2026 · AdminTopBar cleanup — cluster now ends with
        // Settings → NotificationBell → SignOut; the UniversalMenu
        // mount was dropped so this fallback matches the two
        // primary branches exactly.
        <div
          className="px-4 h-11 flex items-center justify-end gap-2"
          data-testid="admin-topbar-tech-wrap"
        >
          <SettingsSprocket />
          {/* Feb-2026 · AdminTopBar bell cleanup — NotificationBell
              glyph flips to ``colors.nav.fg`` via ``tone="navy"`` so
              it reads on the navy strip. Red unread badge unchanged. */}
          <NotificationBell variant="inline" tone="navy" />
          <SignOutButton />
        </div>
      ) : (
        <>
          {/* Narrow (<768px) — hamburger + right cluster. CSS-gated so */}
          {/* mobile browsers that don't fire resize still see it. */}
          {/* Feb-2026 · Mobile Nav Overflow Fix — ``overflow-x-auto`` */}
          {/* contains the right-cluster's ~592px content within the */}
          {/* 44px bar on <400px viewports rather than blowing out the */}
          {/* document. Users can swipe the nav to reach the bell / */}
          {/* signout at the far right when the cluster exceeds width. */}
          {/* Children get ``flex-shrink-0`` so no icon gets squished. */}
          <div
            className="md:hidden px-4 h-11 flex items-center justify-between overflow-x-auto"
            style={{ WebkitOverflowScrolling: "touch",
                     scrollbarWidth: "none" }}
            data-testid="admin-topbar-narrow-wrap"
          >
            <div className="flex-shrink-0">
              <MobileMenu visible={visible} fixedItems={fixedItems} />
            </div>
            {/* Phase BANNER-RELOCATE · Feb-2026 — the visible
                universal search bar was relocated out of the
                admin top bar and into a navy hero banner slot in
                AppLayout (admin-hero-banner). The command-K palette
                still mounts above as a headless singleton. */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Phase U1 · Feb-2026 — "+ Add Job" quick-action.
                  Sits DIRECTLY to the LEFT of "+ Add Customer" per
                  spec; visually identical (same class list, same
                  gradient) and gated on the same admin/super_admin
                  role set as its neighbour. */}
              <AddJobButton />
              <AddCustomerButton />
              {/* Feb-2026 · Mobile Nav Duplicate Fix — the legacy
                  Row 1 mobile <header> in AppLayout used to host the
                  ``<RolePreviewSwitcher>`` picker.  Row 1 no longer
                  paints for admin/super_admin/manager/technician (to
                  end the double-nav-bar regression on mobile), so
                  the impersonation surface is re-mounted here in
                  the narrow-branch right-cluster to preserve
                  one-tap access.  The component self-gates via
                  ``canPreview`` (admin + super_admin per the
                  long-standing product decision in
                  ``hooks/usePermissions.jsx``) so it's a no-op
                  mount for manager / technician. */}
              <RolePreviewSwitcher />
              {/* Phase 8 · Feb-2026 — Marco wake-word toggle (mobile
                  mirror of the wide-branch mount). */}
              <MicToggleButton />
              {/* Feb-2026 · AdminTopBar bell cleanup — the parallel
                  ``AdminBellSlot`` (Proactive Intelligence AlertBell)
                  was pulled from the right cluster. The single
                  remaining bell surface is ``NotificationBell``
                  (below), which now flips its glyph to
                  ``colors.nav.fg`` via ``tone="navy"`` so it reads
                  on the navy strip. The red unread-count badge on
                  ``NotificationBell`` is unchanged — it keeps its
                  ``#DC2626`` / ``#FFFFFF`` styling regardless of
                  tone.  AlertBell / AdminBellSlot definitions
                  remain in this file (unused-but-preserved) so
                  a follow-up commit can re-mount them cleanly if
                  we ever bring back the Proactive Intelligence
                  surface. */}
              <SettingsSprocket />
              <NotificationBell variant="inline" tone="navy" />
              <SignOutButton />
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
            {/* Phase BANNER-RELOCATE · Feb-2026 — see narrow branch
                above; the visible search bar was relocated to the
                admin-hero-banner slot in AppLayout. */}
            <div className="shrink-0 flex items-center gap-2">
              {/* Phase U1 · Feb-2026 — mirror mount on the wide
                  branch. Order + styling match the narrow branch. */}
              <AddJobButton />
              <AddCustomerButton />
              {/* Phase T1.5 · Feb-2026 — tenant switcher.
                  Auto-hidden when the user has <2 memberships,
                  so single-tenant users never see this control. */}
              <TenantSwitcher />
              {/* Phase 8 · Feb-2026 — Marco wake-word toggle. */}
              <MicToggleButton />
              {/* Feb-2026 · AdminTopBar bell cleanup — see narrow
                  branch above for the full rationale. Mirror the
                  same cleanup on the wide branch: ``AdminBellSlot``
                  mount dropped, ``NotificationBell`` gains
                  ``tone="navy"`` so its glyph reads white on the
                  navy strip. Red unread badge unchanged. */}
              <SettingsSprocket />
              <NotificationBell variant="inline" tone="navy" />
              <SignOutButton />
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


// Phase U1 · Feb-2026 — "+ Add Job" quick-action, admin+ only.
// Mirrors AddCustomerButton verbatim (same class list, same
// gradient, same role gate) except for label + destination.
// The two buttons must remain visually indistinguishable — if
// you edit the class list on one, mirror the edit on the other.
function AddJobButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  const role = auth?.user?.role;
  if (role !== "admin" && role !== "super_admin") return null;
  return (
    <button
      type="button"
      onClick={() => navigate("/jobs/new")}
      className="inline-flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-semibold text-white shadow-sm hover:brightness-95"
      style={{ background: gradients.navyToGreen.css }}
      data-testid="admin-topbar-add-job"
      aria-label="Add job"
    >
      <PlusIcon size={14} /> Add Job
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
