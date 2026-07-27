/**
 * Phase 34 · Feb 2026 — Self-serve "Forgot password?" landing page.
 *
 * IMPORTANT: This is currently a STUB. There is no ``POST /api/auth/
 * forgot-password`` endpoint on the backend — see
 * ``/app/memory/todo_password_reset.md`` for the outstanding work. The
 * submit handler here always shows the neutral confirmation message so
 * no email enumeration is possible; when the backend endpoint lands,
 * the ``fetch`` call is a one-line swap-in.
 */
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { brandGradientCss, colors } from "@/theme";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    // TODO — swap for ``await api.post('/auth/forgot-password', {email})``
    // once the backend endpoint ships. See /app/memory/todo_password_reset.md
    setSubmitted(true);
  };
  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4"
         style={{ background: colors.background }}
         data-testid="forgot-password-page">
      <div className="w-full max-w-md rounded-2xl p-8 shadow-xl"
           style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <div className="h-2 w-24 rounded-full mb-6"
             style={{ background: brandGradientCss }} />
        <h1 className="text-2xl font-bold mb-2"
            style={{ color: colors.onSurface }}
            data-testid="forgot-password-title">
          Forgot password?
        </h1>
        <p className="text-sm mb-6" style={{ color: colors.muted }}>
          Enter your account email. If it matches an existing account,
          we'll send you a reset link.
        </p>
        {submitted ? (
          <div className="rounded-lg p-4 mb-6 text-sm"
               style={{ background: colors.surfaceSecondary,
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
               data-testid="forgot-password-confirmation">
            If an account exists for that email, a reset link has been sent.
            Please check your inbox.
          </div>
        ) : (
          <form onSubmit={submit} data-testid="forgot-password-form">
            <label className="block text-xs font-semibold mb-2"
                   style={{ color: colors.muted }}>EMAIL</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
              className="w-full px-3 py-2 rounded-lg text-sm mb-4"
              style={{ backgroundColor: colors.surface,
                       color: colors.onSurface,
                       border: `1px solid ${colors.border}` }}
              data-testid="forgot-password-email"
              autoFocus
            />
            <button type="submit"
                    className="w-full py-2 rounded-lg text-sm font-semibold text-white"
                    style={{ background: brandGradientCss }}
                    data-testid="forgot-password-submit">
              Send reset link
            </button>
          </form>
        )}
        <div className="mt-6 text-xs text-center">
          <Link to="/login" style={{ color: colors.brand }}
                data-testid="forgot-password-back-to-login">
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
