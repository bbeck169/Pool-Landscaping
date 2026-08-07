/**
 * Phase 34 · Task O · Feb 2026 — /reset-password?token=... landing.
 *
 * Second half of the self-serve reset flow started by
 * /forgot-password. Reads the ``token`` query param, collects a new
 * password + confirm field, POSTs to /auth/reset-password, and on
 * success redirects to /login with a toast.
 *
 * All feedback is surfaced inline (no silent success). Password
 * policy is enforced client-side to give fast feedback but the
 * backend re-validates and is the source of truth.
 */
import React, { useState, useEffect, useMemo } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { api } from "@/api";
import { brandGradientCss, colors } from "@/theme";
import { useToast } from "@/hooks/use-toast";

function scorePassword(pw) {
  const len = pw.length >= 8;
  const lo = /[a-z]/.test(pw);
  const up = /[A-Z]/.test(pw);
  const dg = /[0-9]/.test(pw);
  return { len, lo, up, dg, ok: len && lo && up && dg };
}

export default function ResetPassword() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { toast } = useToast();
  const strength = useMemo(() => scorePassword(pw), [pw]);
  const match = pw && pw === pw2;
  const canSubmit = !!token && strength.ok && match && !busy;

  useEffect(() => {
    if (!token) setError("Missing reset token. Please request a new reset link.");
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    try {
      await api.post("/auth/reset-password", { token, new_password: pw });
      toast({
        title: "Password reset",
        description: "Please sign in with your new password.",
      });
      setTimeout(() => navigate("/portal/login", { replace: true }), 400);
    } catch (err) {
      setError(err?.message || "Could not reset your password. The link may have expired.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="min-h-screen w-full flex items-center justify-center px-4"
      style={{ background: colors.background }}
      data-testid="reset-password-page"
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
          data-testid="reset-password-title"
        >
          Choose a new password
        </h1>
        <p className="text-sm mb-6" style={{ color: colors.muted }}>
          Pick something you'll remember. We'll sign you back in with the new
          password.
        </p>
        {error ? (
          <div
            className="rounded-lg p-3 mb-4 text-sm"
            style={{
              background: "#FEF2F2",
              border: "1px solid #FCA5A5",
              color: "#991B1B",
            }}
            data-testid="reset-password-error"
          >
            {error}
          </div>
        ) : null}
        <form onSubmit={submit} data-testid="reset-password-form" className="space-y-4">
          <div>
            <label
              className="block text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              NEW PASSWORD
            </label>
            <input
              type="password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              autoComplete="new-password"
              required
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="reset-password-new"
            />
            <ul
              className="mt-2 text-xs space-y-0.5"
              style={{ color: colors.muted }}
              data-testid="reset-password-strength"
            >
              <li style={{ color: strength.len ? "#059669" : undefined }}>
                {strength.len ? "✓" : "•"} At least 8 characters
              </li>
              <li style={{ color: strength.up ? "#059669" : undefined }}>
                {strength.up ? "✓" : "•"} An uppercase letter
              </li>
              <li style={{ color: strength.lo ? "#059669" : undefined }}>
                {strength.lo ? "✓" : "•"} A lowercase letter
              </li>
              <li style={{ color: strength.dg ? "#059669" : undefined }}>
                {strength.dg ? "✓" : "•"} A digit
              </li>
            </ul>
          </div>
          <div>
            <label
              className="block text-xs font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              CONFIRM PASSWORD
            </label>
            <input
              type="password"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
              autoComplete="new-password"
              required
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="reset-password-confirm"
            />
            {pw2 && !match ? (
              <p
                className="mt-1 text-xs"
                style={{ color: "#B91C1C" }}
                data-testid="reset-password-mismatch"
              >
                Passwords don't match.
              </p>
            ) : null}
          </div>
          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-60"
            style={{ background: brandGradientCss }}
            data-testid="reset-password-submit"
          >
            {busy ? "Updating…" : "Reset password"}
          </button>
        </form>
        <div className="mt-6 text-xs text-center">
          <Link
            to="/portal/login"
            style={{ color: colors.brand }}
            data-testid="reset-password-back-to-login"
          >
            Back to sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
