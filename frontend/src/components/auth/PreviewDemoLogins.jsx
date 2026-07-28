/**
 * Feb 2026 — Preview-only demo logins section for the web login page.
 *
 * Visibility is gated by ``REACT_APP_PUBLIC_ENV === "preview"`` at
 * the CALL SITE (see ``pages/Login.jsx``), not inside this component,
 * so this file is safe to render from unit tests without needing to
 * mock ``process.env``.
 *
 * Mirrors the Expo mobile login's demo section:
 *   - Super Admin  · super@aquaterra.com
 *   - Admin        · manager@aquaterra.com
 *   - Customer     · customer@aquaterra.com
 *   - Pool Tech    · mike@aquaterra.com
 *
 * Every button uses password ``password123`` and auto-submits — the
 * ``onSubmitDirect`` prop performs the login round-trip so the user
 * never sees the credentials in the form fields (privacy on demo
 * screens shared with prospects).
 */
import React from "react";
import { colors } from "@/theme";

export const DEMO_ACCOUNTS = [
  {
    key: "super",
    role_label: "Super Admin",
    email: "super@aquaterra.com",
    tint: "#7c3aed",
  },
  {
    key: "admin",
    role_label: "Admin",
    email: "manager@aquaterra.com",
    tint: "#0284c7",
  },
  {
    key: "customer",
    role_label: "Customer",
    email: "customer@aquaterra.com",
    tint: "#059669",
  },
  {
    key: "tech",
    role_label: "Pool Tech",
    email: "mike@aquaterra.com",
    tint: "#d97706",
  },
];

export function PreviewDemoLogins({ onPick, onSubmitDirect, disabled }) {
  return (
    <section
      className="mt-8 pt-6"
      style={{ borderTop: `1px dashed ${colors.border}` }}
      data-testid="preview-demo-logins"
      aria-label="Demo logins for preview environment"
    >
      <div
        className="text-xs uppercase tracking-wide font-semibold mb-1"
        style={{ color: colors.muted }}
      >
        Demo Logins <span className="normal-case" style={{ color: "#d97706" }}>(Preview Only)</span>
      </div>
      <div className="text-xs mb-3" style={{ color: colors.onSurfaceSecondary }}>
        One-tap sign-in — every account uses <code>password123</code>. Hidden in production.
      </div>
      <div className="grid grid-cols-2 gap-2">
        {DEMO_ACCOUNTS.map((acc) => (
          <button
            key={acc.key}
            type="button"
            disabled={disabled}
            onClick={() => {
              onPick?.(acc.email);
              onSubmitDirect?.(acc.email);
            }}
            data-testid={`demo-login-${acc.key}`}
            className="px-3 py-2 rounded-lg text-sm font-medium text-left transition hover:brightness-95 disabled:opacity-60 disabled:cursor-not-allowed"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${acc.tint}`,
              color: acc.tint,
            }}
          >
            <div className="font-semibold">{acc.role_label}</div>
            <div className="text-xs opacity-80 truncate">{acc.email}</div>
          </button>
        ))}
      </div>
    </section>
  );
}

export default PreviewDemoLogins;
