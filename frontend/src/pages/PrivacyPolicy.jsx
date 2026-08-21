/**
 * Feb-2026 · P11b — Privacy Policy placeholder route.
 *
 * TODO(P11c or user): replace this placeholder body with the real
 * privacy policy once legal review is complete.  Until then, this
 * lightweight route exists so App Store review sees a working
 * ``/privacy-policy`` link from the Settings footer and the Login
 * page footer.  The `<!-- ... -->` comment below is intentional so
 * the placeholder is greppable from a shipped bundle.
 */
import React from "react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";


export default function PrivacyPolicy() {
  /* <!-- TODO(P11c or user): swap placeholder for finalized policy --> */
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: colors.background }}
      data-testid="privacy-policy-page"
    >
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <h1
          className="text-3xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
        >
          Privacy Policy
        </h1>
        <div
          className="mt-6 rounded-2xl p-6"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <p
            className="text-sm"
            style={{ color: colors.onSurface, lineHeight: 1.6 }}
          >
            Our privacy policy is being finalized and will be published
            here shortly.  Contact your service provider or reach us at
            <a
              href="mailto:support@lumino.app"
              style={{ color: colors.brand, marginLeft: 4 }}
              data-testid="privacy-policy-contact-link"
            >
              support@lumino.app
            </a>{" "}
            for immediate questions about how your personal information
            is collected, used, and protected.
          </p>
          <p
            className="text-sm mt-4"
            style={{ color: colors.muted, lineHeight: 1.6 }}
          >
            You can delete your account at any time from your customer
            portal Settings.  Deleting your account anonymizes your
            profile — your service history is preserved for your service
            provider, but your name, email, phone, and address are
            permanently removed.
          </p>
        </div>
        <div className="mt-6">
          <Link
            to="/"
            className="text-sm font-semibold"
            style={{ color: colors.brand }}
            data-testid="privacy-policy-home-link"
          >
            ← Back to home
          </Link>
        </div>
      </div>
    </div>
  );
}
