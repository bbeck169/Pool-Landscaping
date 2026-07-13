import React from "react";
import { NavLink, Outlet, useNavigate, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth";
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
} from "lucide-react";

const ADMIN_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/jobs", label: "Jobs", icon: Briefcase },
  { to: "/schedule", label: "Schedule", icon: CalendarDays },
  { to: "/quotes", label: "Quotes", icon: FileText },
  { to: "/invoices", label: "Invoices", icon: Receipt },
  { to: "/estimator", label: "Estimator", icon: Calculator },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/more", label: "More", icon: MoreHorizontal },
];

// Tech nav intentionally omits Landscape AI / CAD / Virtual Bid / Measure —
// same rule as the Expo mobile technician menu.
const TECH_NAV = [
  { to: "/jobs", label: "Jobs", icon: Briefcase, end: true },
  { to: "/schedule", label: "Schedule", icon: CalendarDays },
  { to: "/leads/new", label: "New Lead", icon: Magnet },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/more", label: "More", icon: MoreHorizontal },
];

const CUSTOMER_NAV = [
  { to: "/portal/home", label: "Home", icon: HomeIcon, end: true },
  { to: "/portal/services", label: "Services", icon: Waves },
  { to: "/portal/request-service", label: "Request", icon: Magnet },
  { to: "/portal/invoices", label: "Invoices", icon: Receipt },
  { to: "/portal/estimates", label: "Estimates", icon: FileText },
  { to: "/portal/payments", label: "Payments", icon: CreditCard },
  { to: "/portal/documents", label: "Documents", icon: Files },
  { to: "/portal/messages", label: "Messages", icon: MessageSquare },
  { to: "/portal/profile", label: "Profile", icon: UserCircle },
];

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
  const nav =
    user.role === "admin" ? ADMIN_NAV : user.role === "technician" ? TECH_NAV : CUSTOMER_NAV;
  const roleLabel = user.role.charAt(0).toUpperCase() + user.role.slice(1);

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
      <div id="impersonation-banner-slot" style={{ height: impersonating ? 40 : 0 }} />

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
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold shadow-sm"
            style={{ background: brandGradientCss }}
          >
            <FolderClock size={20} />
          </div>
          <div className="min-w-0">
            <div
              className="font-semibold text-sm truncate"
              style={{ color: colors.onSurface }}
            >
              AquaTerra
            </div>
            <div className="text-xs truncate" style={{ color: colors.muted }}>
              Pool &amp; Landscaping · Vistancia
            </div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {nav.map((item) => {
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
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center text-white"
              style={{ background: brandGradientCss }}
            >
              <FolderClock size={16} />
            </div>
            <div>
              <div
                className="text-sm font-semibold leading-none"
                style={{ color: colors.onSurface }}
              >
                AquaTerra
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
        </header>

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
          {nav.slice(0, 5).map((item) => {
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
