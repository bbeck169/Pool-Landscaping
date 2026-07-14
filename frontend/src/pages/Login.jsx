import React, { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth";
import { brandGradientCss, colors, font } from "@/theme";

const DEMO_ACCOUNTS = [
  { role: "Admin", email: "admin@aquaterra.com" },
  { role: "Technician", email: "mike@aquaterra.com" },
  { role: "Customer", email: "customer@aquaterra.com" },
];

// Role -> home landing (mirrors the Expo app's tab targeting).
function landingFor(role) {
  if (role === "admin") return "/";
  if (role === "technician") return "/jobs";
  if (role === "customer") return "/portal/home";
  return "/";
}

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, me } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const forced = location.state?.from;

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
      data-testid="login-page"
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
        <div className="relative z-10 flex flex-col justify-between p-12 text-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center text-xl font-bold">
              ~
            </div>
            <div className="font-semibold text-lg leading-tight">
              Pool &amp; Landscaping
              <div className="text-sm opacity-80 font-normal">of Vistancia</div>
            </div>
          </div>
          <div>
            <h1 className="text-4xl lg:text-5xl font-bold leading-tight mb-4">
              Run your crew like clockwork.
            </h1>
            <p className="text-base opacity-90 max-w-md">
              Schedule jobs, dispatch technicians, send quotes, and collect
              payments — all in one control room.
            </p>
          </div>
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

          <div className="mt-10">
            <p
              className="text-xs tracking-widest font-semibold mb-3"
              style={{ color: colors.muted }}
            >
              DEMO ACCOUNTS
            </p>
            <ul className="space-y-2" data-testid="login-demo-accounts">
              {DEMO_ACCOUNTS.map((a) => (
                <li key={a.email}>
                  <button
                    type="button"
                    onClick={() => {
                      setEmail(a.email);
                      setPassword("password123");
                    }}
                    className="w-full flex items-center justify-between px-4 py-3 rounded-xl text-left transition hover:brightness-95"
                    style={{
                      backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`login-demo-${a.role.toLowerCase()}`}
                  >
                    <span
                      className="font-semibold"
                      style={{ color: colors.onSurface }}
                    >
                      {a.role}
                    </span>
                    <span
                      className="text-xs font-mono"
                      style={{ color: colors.muted }}
                    >
                      {a.email}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </main>
    </div>
  );
}
