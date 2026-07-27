/**
 * Phase 34 · Feb 2026 · Honest-stub — self-serve "Forgot password?".
 *
 * WHY THIS PAGE IS CURRENTLY A STUB
 * ─────────────────────────────────
 * The full self-serve reset flow (``POST /api/auth/forgot-password`` +
 * ``POST /api/auth/reset-password``) is still on the backlog (Task O
 * in the Phase-34 queue, tracked in
 * ``/app/memory/todo_password_reset.md``). Before Task O ships, the
 * previous version of this page displayed a green "we've sent you a
 * link" toast that was misleading — no email actually went out. That
 * was reported by the PLOFV owner and is now fixed: no more false
 * success. Instead, the page tells the customer how to reach support
 * so they can be helped out of band.
 *
 * When Task O lands, restore the real form + wire the ``fetch`` call
 * — see the "SWAP-IN GUIDE" comment block at the bottom of this file.
 */
import React from "react";
import { Link } from "react-router-dom";
import { brandGradientCss, colors } from "@/theme";

const SUPPORT_EMAIL = "cs@plofv.com";
const SUPPORT_PHONE_DISPLAY = "(602) 887-4400";
const SUPPORT_PHONE_TEL = "+16028874400";

export default function ForgotPassword() {
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
        <div
          className="rounded-lg p-4 mb-6 text-sm leading-relaxed"
          style={{
            background: "#FEF3C7",
            border: "1px solid #FDE68A",
            color: "#92400E",
          }}
          data-testid="forgot-password-unavailable"
        >
          <p className="font-semibold mb-1">
            Password reset is temporarily unavailable.
          </p>
          <p>
            Please contact support at{" "}
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="font-semibold underline"
              style={{ color: "#92400E" }}
              data-testid="forgot-password-support-email"
            >
              {SUPPORT_EMAIL}
            </a>{" "}
            or{" "}
            <a
              href={`tel:${SUPPORT_PHONE_TEL}`}
              className="font-semibold underline"
              style={{ color: "#92400E" }}
              data-testid="forgot-password-support-phone"
            >
              {SUPPORT_PHONE_DISPLAY}
            </a>{" "}
            and we'll help you regain access.
          </p>
        </div>
        <div className="text-xs text-center">
          <Link
            to="/login"
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

/* ────────────────────────────────────────────────────────────────────
 * SWAP-IN GUIDE (Task O)
 *
 * When ``POST /api/auth/forgot-password`` ships, restore the real
 * form by:
 *   1. Reintroducing ``useState`` for ``email`` + ``submitted``.
 *   2. Replacing the honest-stub yellow banner with the previous
 *      email input + submit button.
 *   3. Wiring ``submit`` to:
 *
 *        const submit = async (e) => {
 *          e.preventDefault();
 *          try {
 *            await api.post('/auth/forgot-password', { email });
 *          } catch (err) {
 *            // never expose whether the account exists
 *          }
 *          setSubmitted(true);
 *        };
 *
 *   4. Showing the neutral confirmation "If an account exists for
 *      that email, a reset link has been sent." after submit.
 *
 * The historic implementation lives in git — check the commit that
 * added this file. Do NOT restore the fake-success behaviour.
 * ──────────────────────────────────────────────────────────────── */
