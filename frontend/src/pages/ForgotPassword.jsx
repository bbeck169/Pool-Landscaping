/**
 * Phase 34 · Task O · Feb 2026 — self-serve "Forgot password?" page.
 *
 * Wired to ``POST /api/auth/forgot-password``. The backend returns a
 * neutral 200 whether or not the email matches an account, so this
 * page ALWAYS shows the same confirmation message after submit — no
 * account enumeration is possible. See ``/app/backend/routers/auth.py``
 * (``forgot_password``) for the enum-safe implementation.
 *
 * The earlier "temporarily unavailable" honest-stub has been removed
 * now that the backend endpoint is live.
 */
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { brandGradientCss, colors } from "@/theme";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { email });
    } catch (_err) {
      // Deliberately swallow — backend is enum-safe and never signals
      // whether the account exists. Any network hiccup just falls
      // through to the neutral confirmation.
    } finally {
      setSubmitted(true);
      setBusy(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center px-4"
      style={{ background: colors.background }}
      data-testid="forgot-password-page"
    >
      <div
        className="w-full max-w-md rounded-2xl p-8 shadow-xl"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <div
          className="h-2 w-24 rounded-full mb-6"
          style={{ background: brandGradientCss }}
        />
        <h1
          className="text-2xl font-bold mb-2"
          style={{ color: colors.onSurface }}
          data-testid="forgot-password-title"
        >
          Forgot password?
        </h1>
        <p className="text-sm mb-6" style={{ color: colors.muted }}>
          Enter your account email. If it matches an existing account, we'll
          send you a link to reset your password.
        </p>
        {submitted ? (
          <div
            className="rounded-lg p-4 mb-6 text-sm"
            style={{
              background: colors.surfaceSecondary || "#F1F5F9",
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="forgot-password-confirmation"
          >
            If an account exists for that email, a reset link has been sent.
            Please check your inbox — the link expires in 30 minutes.
          </div>
        ) : (
          <form onSubmit={submit} data-testid="forgot-password-form">
            <label
              className="block text-xs font-semibold mb-2"
              style={{ color: colors.muted }}
            >
              EMAIL
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
              autoComplete="email"
              className="w-full px-3 py-2 rounded-lg text-sm mb-4"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="forgot-password-email"
              autoFocus
            />
            <button
              type="submit"
              disabled={busy}
              className="w-full py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-60"
              style={{ background: brandGradientCss }}
              data-testid="forgot-password-submit"
            >
              {busy ? "Sending…" : "Send reset link"}
            </button>
          </form>
        )}
        <div className="mt-6 text-xs text-center">
          <Link
            to="/portal/login"
            style={{ color: colors.brand }}
            data-testid="forgot-password-back-to-login"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
