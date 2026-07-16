import React from "react";
import { NavLink, Outlet, useNavigate, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import RolePreviewSwitcher from "@/components/RolePreviewSwitcher";
import AdminSidebar from "@/layouts/AdminSidebar";
import AdminTopBar from "@/layouts/AdminTopBar";
import UniversalMenu from "@/layouts/UniversalMenu";
import LandscapingClockWidget from "@/components/LandscapingClockWidget";
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
  LogOut,
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
  ChevronDown,
  Shield,
  Clock,
  Sparkles,
  DoorOpen,
  Wand2,
  Menu as MenuIcon,
  X as XIcon,
  LayoutGrid,
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
  { to: "/portal/profile", label: "Profile",    icon: UserCircle },
];

const CUSTOMER_NAV = [
  { to: "/portal/home", label: "Home", icon: HomeIcon, end: true },
  { to: "/portal/services", label: "Services", icon: Waves },
  { to: "/portal/book", label: "Book", icon: CalendarDays },
  { to: "/portal/request-service", label: "Request", icon: Magnet },
  { to: "/portal/invoices", label: "Invoices", icon: Receipt },
  { to: "/portal/estimates", label: "Estimates", icon: FileText },
  { to: "/portal/payments", label: "Payments", icon: CreditCard },
  { to: "/portal/photos", label: "Photos", icon: Waves },
  { to: "/portal/documents", label: "Documents", icon: Files },
  { to: "/portal/messages", label: "Messages", icon: MessageSquare },
  { to: "/portal/chats", label: "Chat Threads", icon: MessageSquare },
  { to: "/portal/profile", label: "Profile", icon: UserCircle },
  { to: "/portal/terms", label: "Terms of Service", icon: Shield },
];

function NavGroup({ item }) {
  const location = useLocation();
  const containsActive = item.children.some((c) =>
    location.pathname === c.to || location.pathname.startsWith(c.to + "/")
  );
  const [open, setOpen] = React.useState(containsActive);
  React.useEffect(() => {
    if (containsActive) setOpen(true);
  }, [containsActive]);
  const Icon = item.icon;
  return (
    <div className="space-y-0.5" data-testid={`nav-group-${item.group.toLowerCase()}`}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold hover:brightness-95 transition"
        style={{
          backgroundColor: "transparent",
          color: colors.onSurfaceSecondary,
        }}
        data-testid={`nav-group-toggle-${item.group.toLowerCase()}`}
      >
        <Icon size={18} />
        <span className="flex-1 text-left">{item.group}</span>
        <ChevronDown size={14} style={{
          transform: open ? "rotate(0deg)" : "rotate(-90deg)",
          transition: "transform 150ms",
        }} />
      </button>
      {open && (
        <div className="ml-4 pl-2 space-y-0.5"
             style={{ borderLeft: `2px solid ${colors.border}` }}>
          {item.children.map((c) => (
            <NavLink
              key={c.to}
              to={c.to}
              end
              className={({ isActive }) =>
                `block px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                  isActive ? "" : "hover:brightness-95"
                }`
              }
              style={({ isActive }) => ({
                backgroundColor: isActive ? colors.brandTertiary : "transparent",
                color: isActive ? colors.onBrandTertiary : colors.onSurfaceSecondary,
              })}
              data-testid={`nav-child-${c.label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              {c.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
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
    if (r === "admin" || r === "super_admin") return ADMIN_NAV;
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

      {/* Side nav (>=md) */}
      <aside
        className="hidden md:flex md:flex-col md:w-64 md:min-h-screen"
        style={{
          backgroundColor: colors.surface,
          borderRight: `1px solid ${colors.border}`,
        }}
        data-testid="side-nav"
      >
        <div
          className="px-5 py-5 flex items-center gap-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <img
            src="/logo-icon.png"
            alt="Pool & Landscaping"
            className="w-10 h-10 rounded-xl shadow-sm object-contain"
            style={{ background: "#0EA5E9" }}
            data-testid="app-logo-icon"
          />
          <div className="min-w-0">
            <div
              className="font-semibold text-sm truncate"
              style={{ color: colors.onSurface }}
              data-testid="app-brand-short"
            >
              Pool & Landscaping
            </div>
            <div className="text-xs truncate" style={{ color: colors.muted }}>
              of Vistancia
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto" data-testid="admin-sidebar-scroll">
          {((effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin") ? (
            <AdminSidebar />
          ) : nav.map((item, idx) => {
            if (item.group) {
              return <NavGroup key={`group-${item.group}`} item={item} />;
            }
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-semibold transition ${
                    isActive ? "" : "hover:brightness-95"
                  }`
                }
                style={({ isActive }) => ({
                  backgroundColor: isActive ? colors.brandTertiary : "transparent",
                  color: isActive ? colors.onBrandTertiary : colors.onSurfaceSecondary,
                })}
                data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div
          className="px-5 py-4"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: colors.muted }}>
            Signed in
          </div>
          <div
            className="text-sm font-semibold truncate"
            style={{ color: colors.onSurface }}
            data-testid="shell-user-name"
          >
            {user.name || user.email}
          </div>
          <div
            className="text-xs mb-3"
            style={{ color: colors.muted }}
            data-testid="shell-user-role"
          >
            {roleLabel}
          </div>
          <button
            onClick={onLogout}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition hover:brightness-95"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.error,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="shell-logout-button"
          >
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 min-w-0 pb-20 md:pb-0">
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

        {/* Phase 44 · Admin-only persistent top navigation bar. Renders
            below the mobile top bar (which is already sticky-top on
            <md) and above the page outlet. Additive — the sidebar
            remains the canonical IA. */}
        {((effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin") && (
          <AdminTopBar />
        )}

        {/* Phase 44 · universal top-right menu — visible for every
            authenticated role EXCEPT admin (admins already have the
            admin sidebar + AdminTopBar so a third hamburger is
            redundant). Fixed-positioned so it doesn't nudge layout on
            any page. */}
        {(effectiveRole || user.role) !== "admin" && <UniversalMenu />}

        {/* Phase 49.3 · Landscape Time Clock widget — auto-hides for
            non-landscaping users. Mounted here so it appears at the top
            of every landing / content page. */}
        <div className="px-4 md:px-8 pt-4">
          <LandscapingClockWidget />
        </div>

        <Outlet />

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
