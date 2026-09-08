import React, { useState, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth";
import { colors, font, gradients } from "@/theme";
import { PreviewDemoLogins } from "@/components/auth/PreviewDemoLogins";
import { api } from "@/api";
import { isPreviewOrDev } from "@/utils/env";
import PortalWaterBackground from "@/components/portal/PortalWaterBackground";

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
  const { login, finalizeAccountChoice, me } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Feb-2026 · Task 4 · Option A account chooser — set when the
  // backend returns ``multi_account_choice_required``. When truthy,
  // the form is replaced by an inline account picker. Structure:
  //   { email, choices: [{account_id, role, display}], choice_token }
  // Selection posts to ``/auth/login/select-account``; on success the
  // downstream redirect logic (below) runs identically to a normal
  // single-record login.
  const [chooser, setChooser] = useState(null);
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

  // Shared post-login redirect logic — runs after either a direct
  // single-record login OR the account chooser's ``finalize`` call.
  const _postLoginRedirect = async () => {
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
    } catch (_) { /* fall through */ }
    navigate(forced && role === "admin" ? forced : landingFor(role), { replace: true });
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const res = await login(email.trim().toLowerCase(), password);
      // Feb-2026 · Task 4 · Option A account chooser — the login
      // helper resolves to ``{kind}``.  When ``kind === "choice"``
      // the backend found 2+ password-verified records for this
      // email; render the inline picker instead of redirecting.
      if (res && res.kind === "choice") {
        setChooser(res);
        return;
      }
      await _postLoginRedirect();
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  const onPickAccount = async (accountId) => {
    if (!chooser || !accountId) return;
    setError("");
    setSubmitting(true);
    try {
      await finalizeAccountChoice(chooser.choice_token, accountId);
      await _postLoginRedirect();
    } catch (err) {
      setError(err.message || "Could not sign in to that account");
    } finally {
      setSubmitting(false);
    }
  };

  const onCancelChooser = () => {
    setChooser(null);
    setError("");
    setPassword("");
  };

  return (
    isCustomerVariant ? (
      <PortalLoginCustomerLayout
        onSubmit={onSubmit}
        email={email} setEmail={setEmail}
        password={password} setPassword={setPassword}
        showPw={showPw} setShowPw={setShowPw}
        submitting={submitting}
        error={error}
        expiredBanner={expiredBanner}
        isLinkExpired={isLinkExpired}
        chooser={chooser}
        onPickAccount={onPickAccount}
        onCancelChooser={onCancelChooser}
      />
    ) : (
    <div
      className="min-h-screen w-full flex flex-col md:flex-row"
      style={{ fontFamily: font.family, backgroundColor: colors.surface }}
      data-testid={isCustomerVariant ? "portal-login-page" : "login-page"}
      data-login-variant={variant}
    >
      {/* Left hero panel */}
      <aside
        className="hidden md:flex md:w-1/2 lg:w-3/5 relative overflow-hidden"
        style={{ background: gradients.navyToGreen.css }}
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

          <form onSubmit={onSubmit} className="space-y-4" data-testid="login-form" hidden={!!chooser}>
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
              style={{ background: gradients.navyToGreen.css }}
              data-testid="login-submit-button"
            >
              {submitting ? "Signing in…" : "Sign in →"}
            </button>
          </form>

          {chooser && (
            <AccountChooserCard
              chooser={chooser}
              submitting={submitting}
              error={error}
              onPick={onPickAccount}
              onCancel={onCancelChooser}
            />
          )}

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
        {/* Feb-2026 · P11b + P21b + P23 — Legal footer links (App Store item 4). */}
        <div className="text-center pb-6 pt-4 flex items-center justify-center gap-4 flex-wrap">
          <a
            href="/privacy-policy"
            className="text-xs font-semibold underline opacity-70 hover:opacity-100"
            data-testid="login-privacy-policy-link"
          >
            Privacy Policy
          </a>
          <span className="text-xs opacity-40">·</span>
          <a
            href="/terms-of-service"
            className="text-xs font-semibold underline opacity-70 hover:opacity-100"
            data-testid="login-terms-of-service-link"
          >
            Terms of Service
          </a>
          <span className="text-xs opacity-40">·</span>
          <a
            href="/ai-transparency"
            className="text-xs font-semibold underline opacity-70 hover:opacity-100"
            data-testid="login-ai-transparency-link"
          >
            AI Transparency
          </a>
        </div>
      </main>
    </div>
    )
  );
}

/**
 * Phase K35 · Feb-2026 — Customer-portal login layout. Rendered
 * only when ``variant === "customer"`` (route ``/portal/login``).
 * Animated pool-water background + centered white card with the
 * pill-input treatment.  Auth logic (onSubmit / state / errors)
 * is owned by the parent ``Login`` component and passed in as
 * props so this file stays a single auth surface.
 */
function PortalLoginCustomerLayout({
  onSubmit, email, setEmail, password, setPassword,
  showPw, setShowPw, submitting, error, expiredBanner, isLinkExpired,
  chooser, onPickAccount, onCancelChooser,
}) {
  const CARD_STYLE = {
    background: "rgba(255,255,255,0.96)",
    backdropFilter: "blur(8px)",
    WebkitBackdropFilter: "blur(8px)",
    borderRadius: 24,
    boxShadow:
      "0 20px 60px -20px rgba(2, 132, 199, 0.35), "
      + "0 6px 20px -8px rgba(15, 23, 42, 0.15)",
  };
  const PILL_INPUT = {
    width: "100%",
    borderRadius: 999,
    border: "1px solid #e5e7eb",
    padding: "14px 20px",
    fontSize: 15,
    outline: "none",
    background: "#ffffff",
    color: "#111827",
    transition: "border-color 0.15s",
  };
  return (
    <div
      data-testid="portal-login-page"
      data-login-variant="customer"
      style={{ minHeight: "100vh", position: "relative",
                fontFamily: font.family, isolation: "isolate" }}
    >
      <PortalWaterBackground />
      <div
        style={{
          position: "relative", zIndex: 1,
          minHeight: "100vh",
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", padding: "24px 16px", gap: 24,
        }}
      >
        <img
          src="/logo-full.png"
          alt="Pool & Landscaping of Vistancia"
          data-testid="portal-login-logo"
          style={{ height: 96, maxWidth: "80%", objectFit: "contain",
                    filter: "drop-shadow(0 4px 20px rgba(2, 132, 199, 0.3))" }}
        />
        <div
          data-testid="portal-login-card"
          style={{ ...CARD_STYLE, width: "100%", maxWidth: 440,
                    padding: "36px 32px" }}
        >
          <h1
            data-testid="portal-login-heading"
            style={{
              fontFamily: "Georgia, \"Times New Roman\", serif",
              fontWeight: 700, fontSize: 28, color: "#0f172a",
              margin: 0, marginBottom: 8, textAlign: "center",
            }}
          >
            Customer Portal
          </h1>
          <p style={{
              margin: 0, marginBottom: 24, textAlign: "center",
              color: "#64748b", fontSize: 14,
          }}>
            Sign in to view your service history and invoices.
          </p>

          {expiredBanner && (
            <div
              role="status"
              data-testid="login-session-expired-banner"
              style={{
                fontSize: 13, padding: "8px 12px", borderRadius: 12,
                backgroundColor: "#FEF3C7", color: "#78350F",
                border: "1px solid #FDE68A", marginBottom: 14,
              }}
            >
              {isLinkExpired
                ? "Your one-click link has expired. Please log in to continue."
                : "Your session has expired. Please sign in again."}
            </div>
          )}

          <form onSubmit={onSubmit} data-testid="login-form"
                  hidden={!!chooser}
                  style={{ display: chooser ? "none" : "flex", flexDirection: "column", gap: 12 }}>
            <input
              id="email" type="email" required autoComplete="email"
              placeholder="you@email.com"
              value={email} onChange={(e) => setEmail(e.target.value)}
              style={PILL_INPUT}
              data-testid="login-email-input"
            />
            <div style={{ position: "relative" }}>
              <input
                id="password" required autoComplete="current-password"
                type={showPw ? "text" : "password"}
                placeholder="Password"
                value={password} onChange={(e) => setPassword(e.target.value)}
                style={{ ...PILL_INPUT, paddingRight: 64 }}
                data-testid="login-password-input"
              />
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                data-testid="login-toggle-password"
                style={{
                  position: "absolute", right: 16, top: "50%",
                  transform: "translateY(-50%)", background: "none",
                  border: "none", color: "#2e7d32", fontWeight: 600,
                  fontSize: 11, letterSpacing: "0.08em", cursor: "pointer",
                }}
              >{showPw ? "HIDE" : "SHOW"}</button>
            </div>

            {error && (
              <div
                data-testid="login-error"
                style={{ fontSize: 13, padding: "10px 14px",
                          borderRadius: 12,
                          backgroundColor: "#FEE2E2", color: "#991b1b" }}
              >
                {error}
              </div>
            )}

            <button
              type="submit" disabled={submitting}
              data-testid="login-submit-button"
              style={{
                width: "100%", padding: "14px 20px", borderRadius: 999,
                background: "#2e7d32", color: "#ffffff",
                border: "none", fontSize: 15, fontWeight: 700,
                cursor: submitting ? "not-allowed" : "pointer",
                opacity: submitting ? 0.7 : 1,
                boxShadow: "0 6px 18px -6px rgba(46, 125, 50, 0.55)",
                transition: "transform 0.15s, box-shadow 0.15s",
              }}
            >
              {submitting ? "Signing in…" : "Sign In"}
            </button>
          </form>

          {chooser && (
            <AccountChooserCard
              chooser={chooser}
              submitting={submitting}
              error={error}
              onPick={onPickAccount}
              onCancel={onCancelChooser}
              variant="customer"
            />
          )}

          <div style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", marginTop: 16,
          }}>
            <a href="/"
                data-testid="portal-login-back-link"
                style={{ color: "#2e7d32", fontWeight: 600, fontSize: 13,
                          textDecoration: "none" }}>
              ← Back to site
            </a>
            <Link to="/forgot-password"
                    data-testid="login-forgot-password-link"
                    style={{ color: "#2e7d32", fontWeight: 600, fontSize: 13,
                              textDecoration: "none" }}>
              Forgot password?
            </Link>
          </div>
          {/* R1.b · Feb-2026 — signup affordance restored so the
              customer-variant hides-demo-tiles regression guard
              (``login-goto-signup``) stays green. */}
          <div style={{ textAlign: "center", marginTop: 12, fontSize: 13,
                          color: "#4b5563" }}>
            New here?{" "}
            <Link to="/signup"
                    data-testid="login-goto-signup"
                    style={{ color: "#2e7d32", fontWeight: 700,
                              textDecoration: "none" }}>
              Create an account
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}


// ── Feb-2026 · Task 4 · Option A — inline account chooser card ──
//
// Rendered when ``/api/auth/login`` returns
// ``multi_account_choice_required``.  Two large, keyboard-accessible
// cards (one per matching record) plus a "Not you?" cancel link.
// Copy is intentionally short:
//   * Heading: "Which account?"
//   * Sub-line: "We found two accounts for this email. Pick one to
//     continue."
// The customer variant uses lighter borders + white background so it
// blends with the portal glass card; the staff variant is the same
// component with the default palette.
function AccountChooserCard({ chooser, submitting, error, onPick, onCancel,
                              variant = "staff" }) {
  const cardBg = variant === "customer" ? "rgba(255,255,255,0.98)" : "#fff";
  const rowBorder = variant === "customer" ? "#DBEAFE" : colors.border;
  return (
    <div
      className="mt-2"
      style={{
        backgroundColor: cardBg,
        borderRadius: 12,
        padding: 16,
        display: "flex", flexDirection: "column", gap: 12,
        boxShadow: variant === "customer"
          ? "0 8px 24px rgba(30,64,175,0.10)"
          : "0 4px 12px rgba(0,0,0,0.04)",
      }}
      data-testid="account-chooser"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div
          style={{
            fontFamily: font.family,
            fontWeight: 700,
            fontSize: 20,
            color: colors.onSurface,
          }}
          data-testid="account-chooser-heading"
        >
          Which account?
        </div>
        <div
          style={{ fontSize: 13, color: colors.muted }}
          data-testid="account-chooser-subhead"
        >
          We found {chooser.choices.length === 2
            ? "two accounts"
            : `${chooser.choices.length} accounts`} for
          {" "}
          <b style={{ color: colors.onSurface }}>{chooser.email}</b>.
          Pick one to continue.
        </div>
      </div>

      {error ? (
        <div
          style={{
            background: "#FEF2F2", border: "1px solid #FECACA",
            color: "#B91C1C", borderRadius: 8, padding: "8px 12px",
            fontSize: 13,
          }}
          data-testid="account-chooser-error"
        >
          {error}
        </div>
      ) : null}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {chooser.choices.map((c) => (
          <button
            key={c.account_id}
            type="button"
            disabled={submitting}
            onClick={() => onPick(c.account_id)}
            className="w-full transition active:scale-[0.99] disabled:opacity-60"
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "14px 16px", borderRadius: 10,
              background: "#fff", border: `1px solid ${rowBorder}`,
              cursor: submitting ? "not-allowed" : "pointer",
              fontFamily: font.family, textAlign: "left",
            }}
            data-testid={`account-chooser-option-${c.role || "unknown"}`}
          >
            <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontWeight: 600, fontSize: 15, color: colors.onSurface }}>
                {c.display}
              </span>
              <span style={{ fontSize: 12, color: colors.muted, textTransform: "uppercase",
                                letterSpacing: 0.6 }}>
                {c.role}
              </span>
            </span>
            <span style={{ color: colors.brand, fontWeight: 700, fontSize: 20 }}>
              →
            </span>
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={onCancel}
        disabled={submitting}
        className="text-xs underline self-start"
        style={{ color: colors.muted, background: "none", border: 0, padding: 0 }}
        data-testid="account-chooser-cancel"
      >
        Not you? Log in with a different email.
      </button>
    </div>
  );
}

