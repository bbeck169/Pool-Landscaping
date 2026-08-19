import React from "react";
import { NavLink, Outlet, useNavigate, Navigate, useLocation } from "react-router-dom";
import { APIProvider } from "@vis.gl/react-google-maps";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import RolePreviewSwitcher from "@/components/RolePreviewSwitcher";
import AdminSidebar from "@/layouts/AdminSidebar";
import AdminTopBar from "@/layouts/AdminTopBar";
import UniversalMenu from "@/layouts/UniversalMenu";
import LandscapingClockWidget from "@/components/LandscapingClockWidget";
import AIDock from "@/components/AIDock/AIDock";
import PortalWalkthrough from "@/pages/portal/PortalWalkthrough";
import TosGate from "@/components/legal/TosGate";
import ProfileCompletionGate from "@/components/portal/ProfileCompletionGate";
import Breadcrumbs from "@/components/breadcrumbs/Breadcrumbs";
import { OnboardingLoginModal } from "@/pages/onboarding/OnboardingPage";
import { brandGradientCss, colors, font } from "@/theme";
import {
  LayoutDashboard,
  Briefcase,
  CalendarDays,
  FileText,
  Users,
  Wrench,
  MoreHorizontal,
  Magnet,
  Home as HomeIcon,
  Waves,
  Receipt,
  CreditCard,
  Files,
  MessageSquare,
  UserCircle,
  FolderClock,
  Calculator,
  BarChart3,
  DollarSign,
  Shield,
  Clock,
  Sparkles,
  DoorOpen,
  Wand2,
  Menu as MenuIcon,
  X as XIcon,
  LayoutGrid,
  GraduationCap,
  Film,
} from "lucide-react";

const ADMIN_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/schedule", label: "Schedule", icon: Briefcase },
  { to: "/dispatch", label: "Dispatch", icon: CalendarDays },
  { to: "/dispatch/map", label: "Dispatch Map", icon: MoreHorizontal },
  { to: "/quotes", label: "Quotes", icon: FileText },
  { to: "/invoices", label: "Invoices", icon: Receipt },
  { to: "/estimator", label: "Estimator", icon: Calculator },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/ops", label: "Ops", icon: Wrench },
  { to: "/ops/repair-calculator", label: "Repair Calculator" },
  {
    group: "Reports", icon: BarChart3,
    children: [
      { to: "/reports", label: "Reports Hub" },
      { to: "/reports/business-summary", label: "Business Summary" },
      { to: "/reports/forecast", label: "Revenue Forecast" },
      { to: "/reports/revenue-by-city", label: "Revenue by City" },
      { to: "/reports/revenue-by-crew", label: "Revenue by Crew" },
      { to: "/reports/revenue-by-customer", label: "Revenue by Customer" },
      { to: "/reports/gross-sales", label: "Gross Sales" },
      { to: "/reports/invoiced-items", label: "Invoiced Items" },
      { to: "/income-by-category", label: "Income by Category" },
    ],
  },
  {
    group: "Marketing", icon: Sparkles,
    children: [
      { to: "/marketing", label: "Studio Hub" },
      { to: "/marketing/campaigns", label: "Campaigns" },
      { to: "/marketing/posts", label: "Posts" },
      { to: "/marketing/queue", label: "Approval Queue" },
      { to: "/marketing/calendar", label: "Calendar" },
      { to: "/marketing/scheduling", label: "Scheduling" },
      { to: "/marketing/performance", label: "Performance" },
      { to: "/marketing/sequences", label: "Sequences" },
      { to: "/marketing/templates", label: "Templates" },
      { to: "/marketing/reviews", label: "Reviews" },
      { to: "/marketing/directories", label: "Directories" },
      { to: "/marketing/directories/nap-profile", label: "NAP Profile" },
      { to: "/marketing/directories/submissions", label: "Directory Submissions" },
      { to: "/marketing/brand", label: "Brand Memory" },
      { to: "/seo", label: "SEO Studio" },
      { to: "/seo/articles", label: "SEO Articles" },
      { to: "/seo/keywords", label: "Keywords" },
      { to: "/seo/audit", label: "Audit" },
      { to: "/seo/rank-grid", label: "Rank Grid" },
      { to: "/seo/wordpress", label: "WordPress" },
      { to: "/gbp", label: "Google Business Profile" },
      { to: "/ai-employees", label: "AI Employees" },
      { to: "/tasks", label: "Tasks" },
      { to: "/notifications", label: "Notifications" },
      { to: "/call-logs", label: "Call Logs" },
    ],
  },
  {
    group: "AI & Tools", icon: Wand2,
    children: [
      { to: "/landscape", label: "Landscape AI" },
      { to: "/cad", label: "CAD Studio" },
      { to: "/measure", label: "Satellite Measure" },
      { to: "/virtual-bid", label: "Virtual Bid" },
      { to: "/weather", label: "Weather" },
      { to: "/card", label: "Digital Card" },
    ],
  },
  {
    group: "D2D Sales", icon: DoorOpen,
    children: [
      { to: "/d2d", label: "Dashboard" },
      { to: "/d2d/map", label: "Canvassing Map" },
      { to: "/d2d/knocks", label: "Knocks" },
      { to: "/d2d/open-leads", label: "Open Leads" },
      { to: "/d2d/sold-leads", label: "Sold Leads (Zillow)" },
      { to: "/d2d/report", label: "Team Report" },
      { to: "/d2d/leaderboard", label: "Leaderboard" },
    ],
  },
  {
    group: "Finance", icon: DollarSign,
    children: [
      { to: "/invoices", label: "Invoices Ledger" },
      { to: "/payments", label: "Payments Ledger" },
      { to: "/auto-billing", label: "Auto-Billing" },
      { to: "/income-categories", label: "Income Categories" },
      { to: "/settings/late-fees", label: "Late Fees" },
      { to: "/settings/terms", label: "Terms" },
      { to: "/settings/legal", label: "Legal Docs" },
      { to: "/settings/integrations", label: "Integrations" },
      { to: "/settings/maps", label: "Map & Autocomplete" },
      { to: "/settings/ringcentral", label: "RingCentral" },
      { to: "/settings/citations", label: "Citation Builder" },
      { to: "/settings/rank-tracker", label: "Rank Tracker" },
      { to: "/settings/orphan-users", label: "Orphan Users", superOnly: true },
      { to: "/access-settings", label: "Access Settings" },
      { to: "/access-history", label: "Access History" },
      { to: "/impexp", label: "Import / Export" },
    ],
  },
];

// Tech nav — Phase 29: "All My Tools" hub replaces the old flat Huddle/Equipment
// slots. Techs get Schedule · D2D · Time Clock · Tools · Profile in both the
// sidebar and the mobile bottom bar. Everything else (Huddle, Equipment,
// Property Lookup, Onboarding, Calculators, Leaderboard, etc.) lives inside
// the Tools hub — one place, searchable.
const TECH_NAV = [
  { to: "/schedule", label: "Schedule",   icon: CalendarDays, end: true },
  { to: "/d2d",            label: "D2D",        icon: DoorOpen },
  { to: "/tech/time-clock",label: "Time Clock", icon: Clock },
  { to: "/tech/tools",     label: "Tools",      icon: LayoutGrid },
  // Tech Nav Fix · Feb 2026 — Training promoted from the hamburger menu
  // to the primary tech nav so techs can reach their CPO prep / algae
  // modules / landscape training in one tap. Route `/tests` renders
  // `TrainingList`; `/training` also redirects to `/tests` (App.js).
  { to: "/tests",          label: "Training",   icon: GraduationCap },
  { to: "/portal/profile", label: "Profile",    icon: UserCircle },
];

const CUSTOMER_NAV = [
  { to: "/portal/home", label: "Home", icon: HomeIcon, end: true },
  { to: "/portal/services", label: "Services", icon: Waves },
  { to: "/portal/request-service", label: "Request", icon: Magnet },
  { to: "/portal/invoices", label: "Invoices", icon: Receipt },
  { to: "/portal/estimates", label: "Estimates", icon: FileText },
  { to: "/portal/payments", label: "Payments", icon: CreditCard },
  { to: "/portal/photos", label: "Photos", icon: Waves },
  { to: "/portal/videos", label: "Videos", icon: Film },
  { to: "/portal/documents", label: "Documents", icon: Files },
  { to: "/portal/messages", label: "Messages", icon: MessageSquare },
  { to: "/portal/chats", label: "Chat Threads", icon: MessageSquare },
  { to: "/portal/profile", label: "Profile", icon: UserCircle },
  { to: "/portal/terms", label: "Terms of Service", icon: Shield },
];


// Feb-2026 · Sidebar-pivot follow-up — 7-item vertical quick-nav rail
// that replaces the removed horizontal QuickNavRow. Same order, same
// icons, same role gating semantics as the previous QuickNavRow so
// the ADMIN_NAV_V2 dropdowns in <AdminTopBar> keep serving the
// "…More" surface for deep admin routes.
const QUICK_NAV_RAIL = [
  { key: "dashboard", to: "/",           label: "Dashboard",  Icon: LayoutDashboard, roles: ["super_admin", "admin", "manager", "technician"], end: true },
  { key: "workstream", to: "/workstream", label: "Workstream", Icon: Wrench,         roles: ["super_admin", "admin", "manager"] },
  { key: "schedule",   to: "/schedule",   label: "Schedule",   Icon: CalendarDays,   roles: ["super_admin", "admin", "manager", "technician"] },
  { key: "invoices",   to: "/invoices",   label: "Invoices",   Icon: Receipt,        roles: ["super_admin", "admin", "manager"] },
  { key: "payments",   to: "/payments",   label: "Payments",   Icon: CreditCard,     roles: ["super_admin", "admin", "manager"] },
  { key: "customers",  to: "/customers",  label: "Customers",  Icon: Users,          roles: ["super_admin", "admin", "manager"] },
  { key: "estimates",  to: "/estimates",  label: "Estimates",  Icon: FileText,       roles: ["super_admin", "admin", "manager"] },
];

function QuickNavRail({ role }) {
  const items = QUICK_NAV_RAIL.filter((n) => n.roles.includes(role));
  if (items.length === 0) return null;
  return (
    <nav
      className="flex-1 flex flex-col items-stretch py-3 gap-1 overflow-y-auto"
      data-testid="quick-nav-rail"
      aria-label="Primary navigation"
    >
      {items.map(({ key, to, label, Icon, end }) => (
        <NavLink
          key={key}
          to={to}
          end={end}
          className={({ isActive }) =>
            `mx-2 rounded-xl flex flex-col items-center justify-center gap-1 py-2.5 text-[10px] font-semibold transition ${
              isActive ? "" : "hover:brightness-95"
            }`
          }
          style={({ isActive }) => ({
            backgroundColor: isActive ? colors.brandTertiary : "transparent",
            color: isActive ? colors.brand : colors.onSurfaceSecondary,
            border: `1px solid ${isActive ? colors.brand : "transparent"}`,
          })}
          data-testid={`rail-nav-${key}`}
          aria-label={label}
          title={label}
        >
          <Icon size={20} />
          <span className="leading-none text-center">{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function ProtectedShell() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ backgroundColor: colors.surface }}
        data-testid="app-boot-loading"
      >
        <div
          className="animate-spin w-8 h-8 rounded-full border-4"
          style={{ borderColor: colors.border, borderTopColor: colors.brand }}
        />
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  // Phase 17 · Feb 2026 — mount the Google Maps <APIProvider> once
  // at the shell so the JS API script only loads a single time and
  // is available to every admin-facing page (dispatch board today;
  // schedule + workforce heat-maps later). Non-admin roles never
  // trigger a load because AdminOnly gates the map-consuming routes.
  const mapsKey = process.env.REACT_APP_GOOGLE_MAPS_API_KEY || "";
  if (mapsKey) {
    return (
      <APIProvider apiKey={mapsKey} libraries={["marker", "geometry"]}>
        <AppLayout />
      </APIProvider>
    );
  }
  return <AppLayout />;
}

function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  // Close drawer on route change
  React.useEffect(() => { setDrawerOpen(false); }, [location.pathname]);

  // Detect impersonation: the JWT carries an `act` claim (RFC 8693) when admin
  // acts as a customer. We decode the payload client-side (no verification —
  // display only; the backend re-verifies every request).
  const impersonating = React.useMemo(() => {
    try {
      const token = localStorage.getItem("token");
      if (!token) return null;
      const payload = JSON.parse(atob(token.split(".")[1] || ""));
      return payload?.act ? { adminName: payload.act.name || "admin" } : null;
    } catch { return null; }
  }, []);

  const revertImpersonation = async () => {
    try {
      const { api } = await import("@/api");
      const r = await api.post("/auth/revert-impersonation");
      if (r?.access_token) {
        localStorage.setItem("token", r.access_token);
        if (r.user) localStorage.setItem("user", JSON.stringify(r.user));
        window.location.href = "/";
      }
    } catch (e) {
      alert(e.message);
    }
  };
  const { previewRole, setPreviewRole, isPreviewing, effectiveRole } = usePermissions();
  const nav = (() => {
    const r = effectiveRole || user.role;
    // Feb-2026 · sidebar items may carry ``superOnly: true`` to be
    // hidden from regular admins (still route-guarded by SuperAdminOnly).
    const isSuper = user.role === "super_admin";
    const filterSuper = (items) =>
      (items || []).map((it) => {
        if (it.children) {
          return { ...it, children: it.children.filter((c) => !c.superOnly || isSuper) };
        }
        return it;
      }).filter((it) => !it.superOnly || isSuper);
    if (r === "admin" || r === "super_admin") return filterSuper(ADMIN_NAV);
    if (r === "technician") return TECH_NAV;
    return CUSTOMER_NAV;
  })();
  const roleLabel = (effectiveRole || user.role).charAt(0).toUpperCase() + (effectiveRole || user.role).slice(1);

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <div
      className="min-h-screen flex flex-col md:flex-row"
      style={{ fontFamily: font.family, backgroundColor: colors.surfaceSecondary }}
      data-testid="app-shell"
    >
      {/* Feb-2026 · BUG E — global Terms of Service gate. Self-gates
          on the server-authoritative ``user.must_accept_tos`` flag so
          it renders null for super_admin and for anyone whose
          ``tos_version_accepted`` already matches CURRENT_TOS_VERSION.
          Mounted at the shell so it survives every route change. */}
      <TosGate />
      {/* Feb-2026 · Customer self-serve profile-completion gate.
          Sits at z-[70] so the ToS gate (z-[80]) always wins if both
          fire. Renders null unless ``user.customer_record_missing`` is
          true — see the gate for details. */}
      <ProfileCompletionGate />
      {/* Impersonation banner (Phase 4 partial fold-in) */}
      {/* Phase 15B — first-login onboarding modal (admin only, sessionStorage-guarded) */}
      {(effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin" ? <OnboardingLoginModal /> : null}
      {impersonating ? (
        <div
          className="fixed top-0 left-0 right-0 z-50 px-4 py-2 flex items-center justify-between text-sm font-semibold"
          style={{ backgroundColor: "#FEF3C7", color: "#92400E", borderBottom: "1px solid #FDE68A" }}
          data-testid="impersonation-banner"
        >
          <span>👤 Viewing as <strong>{user?.name || user?.email}</strong> · Admin session paused</span>
          <button
            onClick={revertImpersonation}
            className="text-xs font-bold px-3 py-1 rounded-md"
            style={{ backgroundColor: "#B45309", color: "#fff" }}
            data-testid="revert-impersonation"
          >
            Return to admin
          </button>
        </div>
      ) : null}
      {isPreviewing ? (
        <div
          className="fixed top-0 left-0 right-0 z-50 px-4 py-2 flex items-center justify-between text-sm font-semibold cursor-pointer"
          style={{ backgroundColor: "#FEF3C7", color: "#92400E", borderBottom: "1px solid #FDE68A" }}
          onClick={() => setPreviewRole(null)}
          data-testid="preview-banner"
        >
          <span>🔍 Preview mode — permissions as <strong>{previewRole}</strong>. Click to exit.</span>
          <button
            onClick={(e) => { e.stopPropagation(); setPreviewRole(null); }}
            className="text-xs font-bold px-3 py-1 rounded-md"
            style={{ backgroundColor: "#B45309", color: "#fff" }}
            data-testid="preview-banner-exit"
          >Exit preview</button>
        </div>
      ) : null}
      <div id="impersonation-banner-slot" style={{ height: impersonating ? 40 : 0 }} />
      <div id="preview-banner-slot" style={{ height: isPreviewing ? 40 : 0 }} />

      {/* Feb-2026 · Pivot — the 7 quick-access items move from the
          header row to a slim vertical rail in the same slot the
          sidebar used to occupy. Everything below inside the aside
          renders the new <QuickNavRail>; the legacy AdminSidebar /
          role-nav / user footer that used to live here is retired
          from the desktop rail (mobile drawer still uses
          AdminSidebar for the full IA — see below). */}
      <aside
        className={
          ["admin", "super_admin", "manager", "technician"].includes(effectiveRole || user.role)
            ? "hidden md:flex md:flex-col md:w-[88px] md:shrink-0 md:sticky md:top-0 md:h-screen"
            : "hidden"
        }
        style={{
          backgroundColor: colors.surface,
          borderRight: `1px solid ${colors.border}`,
        }}
        data-testid="side-nav"
      >
        <QuickNavRail role={effectiveRole || user.role} />
      </aside>


      {/* Main content */}
      <main
        className="flex-1 min-w-0 min-h-0 pb-20 md:pb-0"
        data-testid="app-main"
      >
        {/* Mobile top bar (<md) */}
        <header
          className="md:hidden px-4 py-3 flex items-center justify-between sticky top-0 z-30"
          style={{
            backgroundColor: colors.surface,
            borderBottom: `1px solid ${colors.border}`,
          }}
        >
          <div className="flex items-center gap-2">
            {((effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin") && (
              <button
                onClick={() => setDrawerOpen(true)}
                className="w-9 h-9 rounded-lg flex items-center justify-center"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid="mobile-nav-open"
                aria-label="Open navigation"
              >
                <MenuIcon size={18} />
              </button>
            )}
            <img
              src="/logo-icon.png"
              alt="Pool & Landscaping"
              className="w-8 h-8 rounded-lg object-contain"
              style={{ background: "#0EA5E9" }}
              data-testid="app-logo-icon-mobile"
            />
            <div>
              <div
                className="text-sm font-semibold leading-none"
                style={{ color: colors.onSurface }}
              >
                Pool & Landscaping
              </div>
              <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.muted }}>
                {roleLabel}
              </div>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="text-xs font-semibold px-3 py-1.5 rounded-md"
            style={{
              color: colors.error,
              border: `1px solid ${colors.border}`,
              backgroundColor: colors.surfaceSecondary,
            }}
            data-testid="shell-logout-button-mobile"
          >
            Sign out
          </button>
          {/* Phase 29C · role preview picker (mobile top-bar; admin only). */}
          <div className="ml-2"><RolePreviewSwitcher /></div>
        </header>

        {/* Mobile slide-out drawer (admin only) */}
        {((effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin") && drawerOpen && (
          <div
            className="fixed inset-0 z-50 md:hidden"
            data-testid="mobile-nav-drawer"
          >
            <div
              className="absolute inset-0"
              style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
              onClick={() => setDrawerOpen(false)}
              data-testid="mobile-nav-backdrop"
            />
            <aside
              className="absolute left-0 top-0 bottom-0 w-72 flex flex-col shadow-2xl"
              style={{
                backgroundColor: colors.surface,
                borderRight: `1px solid ${colors.border}`,
              }}
            >
              <div
                className="px-4 py-3 flex items-center justify-between"
                style={{ borderBottom: `1px solid ${colors.border}` }}
              >
                <div className="flex items-center gap-2">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-white"
                    style={{ background: brandGradientCss }}
                  >
                    <FolderClock size={16} />
                  </div>
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                    Pool & Landscaping
                  </div>
                </div>
                <button
                  onClick={() => setDrawerOpen(false)}
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                  }}
                  data-testid="mobile-nav-close"
                  aria-label="Close navigation"
                >
                  <XIcon size={16} />
                </button>
              </div>
              <div className="flex-1 py-3 overflow-y-auto" data-testid="mobile-nav-scroll">
                <AdminSidebar />
              </div>
            </aside>
          </div>
        )}

        {/* Phase 44 · persistent top navigation bar.
            Feb-2026 — extended to render for technicians too so the
            QuickNavRow (Dashboard + Schedule for techs) is reachable
            after the left sidebar was hidden. Customer / customer_admin
            keep their own <UniversalMenu> (mounted just below). */}
        {["admin", "super_admin", "manager", "technician"].includes(
          (effectiveRole || user.role)
        ) && (
          <AdminTopBar />
        )}

        {/* Phase 44 · universal top-right menu — visible for every
            authenticated role EXCEPT admin (admins already have the
            admin sidebar + AdminTopBar so a third hamburger is
            redundant). Fixed-positioned so it doesn't nudge layout on
            any page. */}
        {(effectiveRole || user.role) !== "admin" && <UniversalMenu />}

        {/* Phase 49.3 · Landscape Time Clock widget — auto-hides for
            non-landscaping users. Mount-site gate: admin / super_admin
            never see it (Feb-2026 follow-up — the bar is pure noise on
            the admin dashboard). Widget also self-guards, so both
            layers agree. */}
        {(effectiveRole || user.role) !== "admin"
          && (effectiveRole || user.role) !== "super_admin" && (
          <div className="px-4 md:px-8 pt-4">
            <LandscapingClockWidget />
          </div>
        )}

        {/* Slice P · Breadcrumb navigation — auto-derives from route
            metadata. Component hides itself on landing/auth pages. */}
        <Breadcrumbs />

        <Outlet />

        {/* Feb-2026 · Item 10 — Portal tour engine. Self-gates on
            role="customer" + has_seen_customer_tour so it renders
            null for everyone else. Mounted here so it survives
            route changes during the 12-step advance. */}
        <PortalWalkthrough />

        {/* Feb-2026 AE Dock — floating AI Employees drawer. Admin-only
            (self-guards on the ``user.role`` prop; renders null for
            non-admins). Mounted here so it's reachable from every
            authenticated route. */}
        <AIDock user={user} />

        {/* Bottom tab bar (<md) */}
        <nav
          className="md:hidden fixed bottom-0 left-0 right-0 flex items-stretch z-40"
          style={{
            backgroundColor: colors.surface,
            borderTop: `1px solid ${colors.border}`,
          }}
          data-testid="bottom-nav"
        >
          {nav.filter((n) => !n.group).slice(0, 5).map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className="flex-1 flex flex-col items-center justify-center py-2 text-[10px] font-semibold"
                style={({ isActive }) => ({
                  color: isActive ? colors.brand : colors.muted,
                })}
                data-testid={`btm-nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
              >
                <Icon size={20} />
                <span className="mt-0.5">{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </main>
    </div>
  );
}

export default ProtectedShell;
