import React from "react";
import { NavLink, Outlet, useNavigate, Navigate, useLocation } from "react-router-dom";
import MapsProviderGate from "../lib/maps/MapsProviderGate";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import RolePreviewSwitcher from "@/components/RolePreviewSwitcher";
import AdminSidebar from "@/layouts/AdminSidebar";
import AdminTopBar from "@/layouts/AdminTopBar";
import UniversalMenu from "@/layouts/UniversalMenu";
// K75 · Step B · Feb-2026 — user-editable Quick Access rail.
// Replaces the inline ``<QuickNavRail>`` (retained below as
// unused source in case a future revert needs it — grep-locked
// negative in the K75 pytest contract).
import QuickPinsRail from "@/components/nav/QuickPinsRail";
// Feb-2026 UI Polish Addendum — brand logo (multi-tenant aware).
// PLACEHOLDER — swap /app/frontend/public/brand/logo.png with the
// real brand asset. See TD-08 in /app/memory/TECH_DEBT.md for the
// pending admin-upload UI.
import BrandLogo from "@/components/branding/BrandLogo";
import LandscapingClockWidget from "@/components/LandscapingClockWidget";
import AIDock from "@/components/AIDock/AIDock";
import PortalWalkthrough from "@/pages/portal/PortalWalkthrough";
import TosGate from "@/components/legal/TosGate";
// Feb-2026 · Slice 2C — Customer portal per-service ToS gate. Sits
// beside the legacy TosGate (admin single-doc flow) and self-gates
// on ``role === "customer"`` so predicates don't overlap.
import OnboardingGate from "@/components/legal/OnboardingGate";
import ProfileCompletionGate from "@/components/portal/ProfileCompletionGate";
import AppBreadcrumbs from "@/components/nav/AppBreadcrumbs";
import { DynamicCrumbProvider }
  from "@/components/nav/dynamicCrumbContext";
import { OnboardingLoginModal } from "@/pages/onboarding/OnboardingPage";
// K37 · Scoped portal boundary for the authenticated shell. Placed
// around `<APIProvider>` so a bad Google Maps key or provider
// exception surfaces a visible fallback card instead of blanking
// the whole app.
import PortalErrorBoundary from "@/components/errors/PortalErrorBoundary";
import { colors, font, gradients } from "@/theme";
import PaymentMethodPromptBanner from "@/components/portal/PaymentMethodPromptBanner";
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


// Phase K75 · Step B · Feb-2026 — the pre-K75 hard-coded
// ``QUICK_NAV_RAIL`` array + inline ``QuickNavRail`` function
// were retired. The rail now renders ``<QuickPinsRail>`` from
// ``@/components/nav/QuickPinsRail``, which hydrates its item
// list from ``useQuickPins(role)`` — the K75 CRUD hook that
// GETs / PUTs against ``/api/users/me/quick-pins`` and falls
// back to the shared seed defaults in ``@/nav/defaultQuickPins``
// on first-run. The seed defaults mirror the retired array
// byte-for-byte so no user experiences a change until they
// customise their own pins.

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
    // Feb-2026 · Phase A · Item 1 — magic-link tokens on
    // ``/portal/estimates/:id?token=…`` bypass the auth redirect so
    // an anonymous customer can approve / decline the estimate
    // without signing in. The token is validated server-side inside
    // ``EstimateView`` → ``/portal/quotes/via-token`` load; the
    // guard here just lets the render proceed.
    const search = location.search || "";
    const hasToken = /[?&]token=[^&]+/.test(search);
    const isTokenableEstimatePath =
      /^\/portal\/estimates\/[^/]+/.test(location.pathname);
    if (hasToken && isTokenableEstimatePath) {
      return <Outlet />;
    }
    // K37 · Unauthenticated hits under `/portal/*` land on the
    // customer login surface, not the staff `/login` page. Every
    // other unauthenticated route continues to hit `/login` as
    // before. `state.from` is preserved so post-login redirect
    // logic (see `Login.jsx` + `LoginCustomer.jsx`) still returns
    // the user to their original destination.
    const isPortalPath = location.pathname.startsWith("/portal");
    return (
      <Navigate
        to={isPortalPath ? "/portal/login" : "/login"}
        state={{ from: location.pathname + (location.search || "") }}
        replace
      />
    );
  }
  // Phase 17 · Feb 2026 — mount the Google Maps <APIProvider> once
  // at the shell so the JS API script only loads a single time and
  // is available to every admin-facing page (dispatch board today;
  // schedule + workforce heat-maps later). Non-admin roles never
  // trigger a load because AdminOnly gates the map-consuming routes.
  //
  // K37 · Wrapped in a scoped `PortalErrorBoundary` so an invalid
  // key or provider throw surfaces a visible fallback card instead
  // of taking down the whole app. `resetKey={location.pathname}`
  // clears the error state when the user navigates elsewhere.
  //
  // K39a · Feb-2026 — the raw ``<APIProvider>`` is now behind
  // ``<MapsProviderGate>`` (``@/lib/maps``) so a runtime env flag
  // (``REACT_APP_MAPS_PROVIDER``) can swap Google for HERE without
  // touching the shell. Google remains the default; behaviour is
  // byte-identical under ``provider=google``.
  //
  // K39a AMENDMENT · Feb-2026 — the maps provider is STAFF-ONLY
  // infrastructure. Customer-portal users (``user.role ===
  // "customer"``) and unauthenticated requests to ``/portal/*``
  // routes must NEVER cause a maps runtime to mount at the shell:
  // no ``google.maps`` <script> tag, no HERE SDK dynamic import,
  // no <APIProvider>. If a future customer-portal page needs a
  // map (e.g. service-report location pin), it MUST mount its
  // own local <MapsProviderGate> inside that component with its
  // own local error boundary — shell-level mount is forbidden
  // for the customer portal, permanently. This makes the "bad
  // Maps key blanks Trina's portal" class of bug structurally
  // impossible for customers regardless of provider or key
  // validity.
  const mapsKey = process.env.REACT_APP_GOOGLE_MAPS_API_KEY || "";
  const isCustomer = (user?.role || "") === "customer";
  const shouldMountMaps = !isCustomer && Boolean(mapsKey);
  if (shouldMountMaps) {
    return (
      <PortalErrorBoundary label="portal-shell" resetKey={location.pathname}>
        <MapsProviderGate apiKey={mapsKey} libraries={["marker", "geometry"]}>
          <AppLayout />
        </MapsProviderGate>
      </PortalErrorBoundary>
    );
  }
  return (
    <PortalErrorBoundary label="portal-shell" resetKey={location.pathname}>
      <AppLayout />
    </PortalErrorBoundary>
  );
}

function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  // Close drawer on route change
  React.useEffect(() => { setDrawerOpen(false); }, [location.pathname]);

  // Phase K13 · Feb-2026 — the portal impersonation-token URL
  // strip + sessionStorage pin runs synchronously in
  // ``src/index.js`` BEFORE React mounts (so AuthProvider's initial
  // ``/auth/me`` fetch already sees the impersonation token).  No
  // per-route bootstrap is needed here.

  // Detect impersonation: the JWT carries an `act` claim (RFC 8693) when admin
  // acts as a customer. We decode the payload client-side (no verification —
  // display only; the backend re-verifies every request).
  const impersonating = React.useMemo(() => {
    try {
      // Phase K13 — prefer the portal-tab token on portal routes so the
      // banner renders inside the impersonation tab (not the admin tab).
      const onPortal = (location.pathname || "").startsWith("/portal");
      const token = onPortal
        ? (window.sessionStorage.getItem("portal_token") || localStorage.getItem("token"))
        : localStorage.getItem("token");
      if (!token) return null;
      const payload = JSON.parse(atob(token.split(".")[1] || ""));
      return payload?.act ? { adminName: payload.act.name || "admin" } : null;
    } catch { return null; }
  }, [location.pathname]);

  // Phase K13 · Feb-2026 — banner is portal-scoped.  Admin routes
  // never render it even when ``user.is_impersonated === true``.
  const showImpersonationBanner = impersonating
    && (location.pathname || "").startsWith("/portal");

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
      {showImpersonationBanner ? (
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
      <div id="impersonation-banner-slot" style={{ height: showImpersonationBanner ? 40 : 0 }} />
      <div id="preview-banner-slot" style={{ height: isPreviewing ? 40 : 0 }} />

      {/* Phase K11 · Feb-2026 — Payment-method persistent banner.
          Portal-scoped; renders when the customer has no card or a
          card expiring within 30 days.  Distinct blue tint so it
          never collides visually with the K13 impersonation banner. */}
      {(location.pathname || "").startsWith("/portal") ? (
        <PaymentMethodPromptBanner />
      ) : null}

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
          // Phase K50 · Feb-2026 — Pipedrive-inspired navy chrome.
          // Single-token source; do NOT reintroduce the sky-tinted
          // gradient this replaced (the previous
          // ``linear-gradient(180deg, rgba(2,132,199,0.06)…)`` is
          // preserved in git history if we ever want to revert).
          backgroundColor: colors.nav.bg,
          borderRight: `1px solid ${colors.nav.border}`,
        }}
        data-testid="side-nav"
      >
        {/* Feb-2026 · Brand mark crown — sits at the top of the rail
            so the app shell has consistent brand recognition. Tenant
            override wins via ``useTenantBrand``; falls back to the
            placeholder /brand/logo-icon.png. */}
        <div
          className="pt-3 pb-1 flex items-center justify-center"
          // Phase K51.1 · Feb-2026 — Logo container background parity.
          // The parent <aside> already paints navy chrome, but an
          // explicit ``colors.nav.bg`` here documents the intent and
          // keeps a transparent-PNG tenant logo blending seamlessly
          // into the surrounding chrome (no white "tile" artefact
          // around the mark).  Padding preserved.
          style={{ backgroundColor: colors.nav.bg }}
          data-testid="side-nav-logo-slot"
        >
          <BrandLogo variant="icon" testId="side-nav-logo" height={40} />
        </div>
        <QuickPinsRail role={effectiveRole || user.role} />
      </aside>


      {/* Main content */}
      <main
        className="flex-1 min-w-0 min-h-0 pb-20 md:pb-0"
        data-testid="app-main"
      >
        {/* Feb-2026 · Mobile Nav Duplicate Fix — Row 1 (this legacy
            mobile <header>) is now painted ONLY for roles that do
            NOT mount ``<AdminTopBar>``.  Roles that DO mount
            AdminTopBar get its narrow-branch mobile chrome and
            would otherwise see two stacked nav bars on <768px
            viewports (see AUDIT_WEB_MOBILE_NAV_DUPLICATE.md).
            The role list here MUST stay in lockstep with the
            AdminTopBar mount gate below (L~660) — invert the same
            set.  Customer / customer_portal / unknown / null roles
            still render this header because they never had a
            desktop TopBar surface. */}
        {(() => {
          const _effRole = effectiveRole || user.role || "";
          const _mountsAdminTopBar = ["admin", "super_admin", "manager", "technician"]
            .includes(_effRole);
          return !_mountsAdminTopBar;
        })() ? (
        <header
          className="md:hidden px-4 py-3 flex items-center justify-between sticky top-0 z-30"
          style={{
            backgroundColor: colors.nav.bg,
            borderBottom: `1px solid ${colors.nav.border}`,
          }}
        >
          <div className="flex items-center gap-2">
            {((effectiveRole || user.role) === "admin" || (effectiveRole || user.role) === "super_admin") && (
              <button
                onClick={() => setDrawerOpen(true)}
                className="w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-200 ease-out hover:scale-[1.02] hover:bg-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40 focus-visible:scale-[1.02]"
                style={{
                  // Phase K50 extension — hamburger sits on navy;
                  // render as transparent-with-white-border so the
                  // icon reads without an extra chip surface.
                  backgroundColor: "transparent",
                  border: `1px solid ${colors.nav.border}`,
                  color: colors.nav.fg,
                }}
                data-testid="mobile-nav-open"
                aria-label="Open navigation"
              >
                <MenuIcon size={18} />
              </button>
            )}
            {/* Feb-2026 UI Polish Addendum — logo wrapped in <Link to="/">
                for one-tap dashboard return. Tenant override wins via
                ``useTenantBrand``.  Phase K50 extension — the mobile
                nav is now navy, so any dark-fill tenant logo would
                disappear.  Apply an interim ``brightness(0) invert(1)``
                CSS filter that flattens the logo to a white silhouette;
                a proper white-asset swap is logged in Future Work. */}
            <div
              // Phase K51.1 · Feb-2026 — Logo container background
              // parity.  The mobile <header> already paints navy, but
              // making it explicit on the logo container documents the
              // intent and keeps a transparent-PNG tenant logo blending
              // into the chrome (no white "tile" artefact around the
              // mark).  The interim ``brightness(0) invert(1)`` filter
              // stays — it flattens dark-fill tenant logos to a white
              // silhouette so they read on navy.
              style={{
                backgroundColor: colors.nav.bg,
                filter: "brightness(0) invert(1)",
              }}
              data-testid="app-logo-mobile-white"
            >
              <BrandLogo variant="icon" testId="app-logo-icon-mobile" height={32} />
            </div>
            <div>
              <div
                className="text-sm font-semibold leading-none"
                style={{ color: colors.nav.fg }}
              >
                Pool & Landscaping
              </div>
              <div className="text-[10px] uppercase tracking-wide" style={{ color: colors.nav.fgMuted }}>
                {roleLabel}
              </div>
            </div>
          </div>
          <button
            onClick={onLogout}
            className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-md text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55 shadow-sm"
            // Phase K54 · Feb-2026 — solid destructive red per
            // ``colors.destructive`` in ``theme.js``.  Replaces the
            // K50 semi-transparent red tint so every Sign-out
            // surface in the app matches the shadcn ``destructive``
            // variant spec.  Border/tint styles are now driven by
            // Tailwind arbitrary values so no inline ``style`` is
            // needed on this button.
            data-testid="shell-logout-button-mobile"
          >
            Sign out
          </button>
          {/* Phase 29C · role preview picker (mobile top-bar; admin only). */}
          <div className="ml-2"><RolePreviewSwitcher /></div>
        </header>
        ) : null}

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
                    style={{ background: gradients.navyToGreen.css }}
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

        {/* Phase 44 · universal top-right menu — Feb-2026 cleanup:
            admin / super_admin / manager / technician now render
            <UniversalMenu variant="inline" /> INSIDE <AdminTopBar>
            (bell + hamburger sit in the header row instead of
            floating in the top-right corner and overlapping
            content). Only customer / customer-portal roles still
            get the floating instance here, since they don't mount
            <AdminTopBar>. */}
        {!["admin", "super_admin", "manager", "technician"].includes(
          effectiveRole || user.role
        ) && <UniversalMenu />}

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
            metadata. Component hides itself on landing/auth pages.
            Phase K2 · Feb-2026 — replaced the raw Slice-P shell with
            the shadcn-primitive-backed ``<AppBreadcrumbs>`` and
            wrapped both the breadcrumbs AND the outlet in
            ``<DynamicCrumbProvider>`` so pages can register live
            entity names via ``useSetDynamicCrumb`` and the crumbs
            re-render with the resolved name. */}
        <DynamicCrumbProvider>
          <AppBreadcrumbs
            variant={location.pathname.startsWith("/portal") ? "portal" : "admin"}
          />

          {/* Feb-2026 · Slice 2C — customer per-service ToS gate. Wraps
              the outlet so pending pool + landscaping ToS acceptances
              block route interaction. Self-gates on role === "customer";
              no-op for admin / super_admin / technician / manager. */}
          <OnboardingGate>
            <Outlet />
          </OnboardingGate>
        </DynamicCrumbProvider>

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
