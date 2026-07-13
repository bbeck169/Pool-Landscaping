import React from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useLocation,
} from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import { brandGradientCss, colors, font, money } from "@/theme";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";

function ProtectedRoute({ children }) {
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
  return children;
}

function ShellPlaceholder() {
  const { user, logout } = useAuth();
  return (
    <div
      className="min-h-screen"
      style={{
        fontFamily: font.family,
        backgroundColor: colors.surfaceSecondary,
      }}
      data-testid="shell-placeholder"
    >
      <header
        className="px-6 py-4 flex items-center justify-between"
        style={{
          backgroundColor: colors.surface,
          borderBottom: `1px solid ${colors.border}`,
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center text-white font-bold"
            style={{ background: brandGradientCss }}
          >
            ~
          </div>
          <div>
            <div className="font-semibold" style={{ color: colors.onSurface }}>
              Pool &amp; Landscaping of Vistancia
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Web console
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div
              className="text-sm font-semibold"
              style={{ color: colors.onSurface }}
              data-testid="shell-user-name"
            >
              {user?.name || user?.email}
            </div>
            <div
              className="text-xs uppercase tracking-wide"
              style={{ color: colors.muted }}
              data-testid="shell-user-role"
            >
              {user?.role}
            </div>
          </div>
          <button
            onClick={logout}
            className="text-sm font-semibold px-4 py-2 rounded-lg"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="shell-logout-button"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-16">
        <div
          className="rounded-2xl p-10"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <p
            className="text-xs tracking-widest font-semibold mb-2"
            style={{ color: colors.brand }}
          >
            PHASE 0 · SCAFFOLD READY
          </p>
          <h1
            className="text-3xl font-bold mb-4"
            style={{ color: colors.onSurface }}
          >
            Welcome, {user?.name || "there"}.
          </h1>
          <p className="text-base mb-8" style={{ color: colors.onSurfaceSecondary }}>
            You&apos;re signed in as{" "}
            <span className="font-semibold">{user?.role}</span>. Real screens will
            be built in <span className="font-semibold">Phase 1</span> — this is
            just the empty shell verifying auth + API wiring end-to-end.
          </p>

          <div
            className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8"
            data-testid="shell-info-cards"
          >
            {[
              { label: "User ID", value: user?.id?.slice(0, 8) + "…" },
              { label: "Email", value: user?.email },
              { label: "Role", value: user?.role },
            ].map((c) => (
              <div
                key={c.label}
                className="rounded-xl p-4"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                }}
              >
                <div
                  className="text-xs uppercase tracking-wide mb-1"
                  style={{ color: colors.muted }}
                >
                  {c.label}
                </div>
                <div
                  className="text-sm font-semibold break-all"
                  style={{ color: colors.onSurface }}
                >
                  {c.value}
                </div>
              </div>
            ))}
          </div>

          <div
            className="rounded-xl p-4 text-sm"
            style={{
              backgroundColor: colors.brandTertiary,
              color: colors.onBrandTertiary,
            }}
          >
            Sample formatter check: {money(1234.5)} · Backend base ={" "}
            <code>{process.env.REACT_APP_BACKEND_URL}</code>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <ShellPlaceholder />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
