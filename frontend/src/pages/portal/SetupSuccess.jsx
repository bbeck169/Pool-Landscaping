/**
 * Phase P30 · Feb-2026 — SetupSuccess landing page.
 *
 * Customer arrives here after Stripe's hosted Checkout Session
 * (mode=setup) redirects them back with ``?session_id=...``. The
 * server-side webhook (``checkout.session.completed`` with
 * ``metadata.source == "card_add_setup"``) is the source of truth
 * for the actual card attachment; this page is a friendly
 * confirmation screen only and does NOT verify the session
 * server-side (no such GET endpoint exists yet — flagged as a
 * P30 follow-up).
 *
 * Route: ``/portal/setup-success``  (unauthenticated — the
 * customer arrives from an email/SMS link and never signs in).
 *
 * Style matches ``PortalPaymentReturn.jsx`` — same wrapper, same
 * button treatment, same Lucide icon set.
 */
import React from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";


export default function SetupSuccess() {
  const params = new URLSearchParams(window.location.search);
  const session_id = params.get("session_id") || "";

  const wrapper = {
    maxWidth: 520, margin: "0 auto", padding: "3rem 1.5rem",
    textAlign: "center", color: colors.onSurface,
  };

  if (!session_id) {
    // No session_id in the query — either the customer landed here
    // directly (bookmark / typed URL) or the redirect stripped it.
    // Show a graceful "we couldn't confirm" message instead of an
    // error page — the webhook is still authoritative and their
    // card may already be saved.
    return (
      <div style={wrapper} data-testid="setup-success-missing-session">
        <AlertCircle size={48} color="#F59E0B" className="mx-auto" />
        <h1 className="text-2xl font-bold mt-3">
          We couldn't confirm this session
        </h1>
        <p className="text-sm mt-2" style={{ color: colors.muted }}>
          If you just added a card, it may already be saved on your
          account. If you have any questions, reply to the email or
          text we sent you.
        </p>
        <Link
          to="/portal"
          className="inline-block mt-6 px-5 py-2 rounded-xl text-sm font-semibold text-white"
          style={{ backgroundColor: "#1D4ED8" }}
          data-testid="setup-success-return-to-portal"
        >
          Return to Portal
        </Link>
      </div>
    );
  }

  return (
    <div style={wrapper} data-testid="setup-success-page">
      <CheckCircle2 size={48} color="#16A34A" className="mx-auto" />
      <h1 className="text-2xl font-bold mt-3">
        Thanks — your card is saved.
      </h1>
      <p className="text-sm mt-2" style={{ color: colors.muted }}>
        You're all set. We'll use this card for your future service
        billing. You can reply to the email or text we sent you if
        you'd like to make changes.
      </p>
      <Link
        to="/portal"
        className="inline-block mt-6 px-5 py-2 rounded-xl text-sm font-semibold text-white"
        style={{ backgroundColor: "#1D4ED8" }}
        data-testid="setup-success-return-to-portal"
      >
        Return to Portal
      </Link>
      {/* Hidden session-id echo so the QA harness + support debug
          can eyeball which session landed on the page without
          exposing it to the customer visibly. */}
      <div
        aria-hidden="true"
        data-testid="setup-success-session-id"
        style={{ display: "none" }}
      >
        {session_id}
      </div>
    </div>
  );
}
