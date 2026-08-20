import React, { useState, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth";
import { brandGradientCss, colors, font } from "@/theme";
import { PreviewDemoLogins } from "@/components/auth/PreviewDemoLogins";
import { api } from "@/api";
import { isPreviewOrDev } from "@/utils/env";

// Role -> home landing (mirrors the Expo app's tab targeting).
function landingFor(role) {
  if (role === "admin") return "/";
  if (role === "technician") return "/schedule/today";  // Phase 16C
  if (role === "customer") return "/portal/home";
  return "/";
}

export default function Login({ variant = "staff" } = {}) {
  const isCustomerVariant = variant === "customer";
  const navigate = useNavigate();
  const location = useLocation();
  const { login, me } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Feb 2026 · Demo-login P0 hotfix — the previous env gate read
  // the build-time env var REACT_APP_PUBLIC_ENV which was BAKED
  // INTO THE BUNDLE at build time. When the production deploy
  // re-used a bundle built with a preview ``.env`` present, the
  // tiles leaked to production. Fix: fetch the backend's runtime
  // ``APP_ENV`` from ``/api/config/public`` and gate on that.
  // Default null → hide (fail-closed). Only show tiles when the
  // backend explicitly reports a non-production env.
  //
  // Feb 2026 · Hotfix #2 (Option C) — the CUSTOMER-facing variant
  // at ``/portal/login`` NEVER renders the demo-tiles block, and
  // to keep DOM parity we also skip the ``/config/public`` fetch
  // entirely on that surface. Staff-facing ``/login`` is unchanged.
  //
  // Feb 2026 · P0 Hotfix #3 (belt-and-suspenders) — production
  // custom domain ``app.plofv.com`` was leaking the demo tiles
  // because its backend had ``APP_ENV=preview`` +
  // ``SHOW_DEMO_LOGINS=true`` seeded in ``.env``. Adding a
  // hostname-based outer gate via ``isPreviewOrDev()`` — no
  // amount of wrong-env server response can override it. Also
  // prefer the new ``/config/features.demo_logins_enabled`` flag
  // when the endpoint exists; fall back to the legacy
  // ``/config/public.app_env`` gate for backward-compat.
  const [demoServerAllowed, setDemoServerAllowed] = useState(null);
  useEffect(() => {
    if (isCustomerVariant) return; // customer surface never renders tiles
    let cancelled = false;
    // Try the new dedicated feature flag first — cleaner contract
    // and easier to reason about than shipping an env label to the
    // wire. Fall back to the legacy app_env gate if the endpoint
    // is missing (older backend still in the wild).
    api.get("/config/features")
      .then((r) => {
        if (cancelled) return;
        if (r && typeof r.demo_logins_enabled === "boolean") {
          setDemoServerAllowed(r.demo_logins_enabled);
          return;
        }
        // Legacy fallback — old backend, use ``app_env``.
        return api.get("/config/public").then((rr) => {
          if (cancelled) return;
          const v = String(rr?.app_env || "").toLowerCase();
          setDemoServerAllowed(v && v !== "production");
        });
      })
      .catch(() => {
        if (cancelled) return;
        setDemoServerAllowed(false); // fail-closed
      });
    return () => { cancelled = true; };
  }, [isCustomerVariant]);
  // Strict hostname gate — computed once per mount. No re-render
  // condition needed because the hostname doesn't change without a
  // full navigation.
  const hostAllowed = React.useMemo(() => isPreviewOrDev(), []);
  const showDemoTiles =
    !isCustomerVariant
    && hostAllowed
    && demoServerAllowed === true;
  // Phase 30 · Feb 2026 — the DEMO ACCOUNTS block has been removed from
  // the login UI unconditionally. Manual login with the seed emails
  // (admin@aquaterra.com / mike@aquaterra.com / customer@aquaterra.com)
  // still works — backend auth unchanged — but the visual list is gone.
  // The ``SHOW_DEMO_LOGINS`` env flag + ``/config/public.show_demo_logins``
  // field are intentionally left in place on the backend to avoid
  // breaking any other consumer that reads them; the frontend simply
  // ignores the value.

  const forced = location.state?.from;

  // Feb-2026 · Zombie-session hotfix — surface a friendly banner when
  // the user landed here via the api.js 401 interceptor
  // (?reason=expired). Query-string driven so it survives a full
  // page reload triggered by ``window.location.assign``.
  const expiredBanner = React.useMemo(() => {
    const params = new URLSearchParams(location.search || "");
    const reason = params.get("reason");
    // Feb-2026 · Door-hanger auto-login redemption reasons — the
    // /api/portal/auto-login interstitial 302s here with a specific
    // ``reason`` when the one-click ``?t=`` link is unusable.
    return reason === "expired" || reason === "link_expired";
  }, [location.search]);
  const isLinkExpired = React.useMemo(() => {
    const params = new URLSearchParams(location.search || "");
    return params.get("reason") === "link_expired";
  }, [location.search]);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email.trim().toLowerCase(), password);
      // Refresh /auth/me to normalize the user object; then land based on role.
      const user = await me().catch(() => null);
      const role = user?.role;
      // Multi-tenant: if the user belongs to >1 active tenant, show the picker.
      // Reset any stale tenant_slug from a previous session first.
      localStorage.removeItem("tenant_slug");
      localStorage.removeItem("tenant_name");
      try {
        const memberships = await (await import("@/api")).api.get("/tenants/memberships/mine");
        const list = Array.isArray(memberships) ? memberships : (memberships?.memberships || []);
        if (list.length > 1) {
          navigate("/tenant-picker", { replace: true });
          return;
        }
      } catch (_) {
        // fall through to normal landing
      }
      navigate(forced && role === "admin" ? forced : landingFor(role), { replace: true });
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full flex flex-col md:flex-row"
      style={{ fontFamily: font.family, backgroundColor: colors.surface }}
      data-testid={isCustomerVariant ? "portal-login-page" : "login-page"}
      data-login-variant={variant}
    >
      {/* Left hero panel */}
      <aside
        className="hidden md:flex md:w-1/2 lg:w-3/5 relative overflow-hidden"
        style={{ background: brandGradientCss }}
      >
        <div
          className="absolute inset-0 opacity-30"
          style={{
            backgroundImage:
              "url(https://images.unsplash.com/photo-1562016600-ece13e8ba570?crop=entropy&cs=srgb&fm=jpg&w=1600&q=85)",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        <div className="relative z-10 flex flex-col items-center justify-center gap-6 p-12 text-white text-center">
          {/* Phase 33 · Feb 2026 — logo + two-line brand header now
              stacked vertically, centered on the hero panel:
              [logo] → [Welcome to] → [Pool & Landscaping of Vistancia LLC].
              Preserves the 48px / 24px sizing set in Phase 30. */}
          <img
            src="/logo-full.png"
            alt="Pool & Landscaping of Vistancia"
            style={{ height: 140, maxWidth: "80%", objectFit: "contain" }}
            data-testid="login-logo-full"
          />
          <h1
            className="font-bold leading-none"
            data-testid="login-welcome-headline"
            style={{ fontSize: "3rem" }}
          >
            <span
              data-testid="login-welcome-line1"
              style={{ fontSize: "3rem", display: "block", lineHeight: 1.05 }}
            >
              Welcome to
            </span>
            <span
              data-testid="login-welcome-line2"
              style={{ fontSize: "1.5rem", display: "block", lineHeight: 1.15 }}
            >
              Pool &amp; Landscaping of Vistancia LLC
            </span>
          </h1>
        </div>
      </aside>

      {/* Right form panel */}
      <main className="flex-1 flex items-center justify-center px-6 py-10">
        <div className="w-full max-w-md">
          <p
            className="text-xs tracking-widest font-semibold mb-2"
            style={{ color: colors.muted }}
          >
            WELCOME BACK
          </p>
          <h2 className="text-3xl font-bold mb-8" style={{ color: colors.onSurface }}>
            Sign in to your console
          </h2>

          {expiredBanner && (
            <div
              className="text-sm px-3 py-2 rounded-lg mb-4"
              style={{
                backgroundColor: "#FEF3C7",
                color: "#78350F",
                border: "1px solid #FDE68A",
              }}
              role="status"
              data-testid="login-session-expired-banner"
            >
              {isLinkExpired
                ? "Your one-click link has expired. Please log in to continue."
                : "Your session has expired. Please sign in again."}
            </div>
          )}

          <form onSubmit={onSubmit} className="space-y-4" data-testid="login-form">
            <div>
              <label
                htmlFor="email"
                className="text-xs font-semibold tracking-wide mb-1 block"
                style={{ color: colors.onSurfaceSecondary }}
              >
                EMAIL
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                className="w-full px-4 py-3 rounded-xl outline-none transition focus:ring-2"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="login-email-input"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="text-xs font-semibold tracking-wide mb-1 block"
                style={{ color: colors.onSurfaceSecondary }}
              >
                PASSWORD
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPw ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-3 pr-16 rounded-xl outline-none transition focus:ring-2"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="login-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold"
                  style={{ color: colors.brand }}
                  data-testid="login-toggle-password"
                >
                  {showPw ? "HIDE" : "SHOW"}
                </button>
              </div>
              {/* Phase 34 · Feb 2026 — self-serve "Forgot password?"
                  link. Routes to /forgot-password (currently a stub;
                  backend endpoint is tracked in
                  /app/memory/todo_password_reset.md). Right-aligned,
                  subtle, matches the existing SHOW/HIDE + brand link
                  styling on this page. */}
              <div className="text-right mt-2">
                <Link
                  to="/forgot-password"
                  className="text-xs font-semibold hover:underline"
                  style={{ color: colors.brand }}
                  data-testid="login-forgot-password-link"
                >
                  Forgot password?
                </Link>
              </div>
            </div>

            {error && (
              <div
                className="text-sm px-3 py-2 rounded-lg"
                style={{
                  backgroundColor: "#FEE2E2",
                  color: colors.error,
                }}
                data-testid="login-error"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3 rounded-xl text-white font-semibold text-base transition active:scale-[0.99] disabled:opacity-60"
              style={{ background: brandGradientCss }}
              data-testid="login-submit-button"
            >
              {submitting ? "Signing in…" : "Sign in →"}
            </button>
          </form>

          <p
            className="mt-6 text-sm text-center"
            style={{ color: colors.onSurfaceSecondary }}
          >
            New customer?{" "}
            <Link
              to="/signup"
              className="font-semibold"
              style={{ color: colors.brand }}
              data-testid="login-goto-signup"
            >
              Create an account
            </Link>
          </p>

          {/* Feb 2026 · Demo-login P0 hotfix — gate now reads
              ``app_env`` from the backend at RUNTIME (see the
              ``showDemoTiles`` state above). The old build-time
              env-var gate was baked into the bundle and leaked to
              production. Fail-safe: if the backend fetch fails or
              returns nothing, ``appEnv`` stays null and the tiles
              are hidden. */}
          {showDemoTiles && (
            <PreviewDemoLogins
              onPick={(email) => {
                setEmail(email);
                setPassword("password123");
              }}
              disabled={submitting}
              onSubmitDirect={async (email) => {
                setSubmitting(true);
                setError("");
                try {
                  await login(email, "password123");
                  const user = await me().catch(() => null);
                  const role = user?.role;
                  localStorage.removeItem("tenant_slug");
                  localStorage.removeItem("tenant_name");
                  try {
                    const memberships = await (await import("@/api")).api.get("/tenants/memberships/mine");
                    const list = Array.isArray(memberships) ? memberships : (memberships?.memberships || []);
                    if (list.length > 1) {
                      navigate("/tenant-picker", { replace: true });
                      return;
                    }
                  } catch (_) {}
                  navigate(landingFor(role), { replace: true });
                } catch (err) {
                  setError(err.message || "Demo login failed");
                } finally {
                  setSubmitting(false);
                }
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}
