/**
 * Feb-2026 · Phase A · Item 1 — public magic-link landing page for
 * customer estimate approve / decline.
 *
 * The signature/share-link generator emits URLs shaped like:
 *
 *     https://…/e/estimate?token=<jwt>
 *
 * This route (registered outside ``AppLayout`` in ``App.js``) reads
 * ``?token=`` and hands it to ``EstimateView``. The token-only branch
 * of EstimateView loads the estimate via
 * ``GET /api/portal/quotes/via-token`` and activates the Phase A
 * path-based approve / decline endpoints — no user login required.
 *
 * A companion route at ``/portal/estimates/:id?token=…`` accepts the
 * same token via the AppLayout auth bypass. We keep both alive
 * during Phase A and log a WARN when each is hit so we can retire
 * whichever path we don't want long-term (see the ``console.warn``
 * below plus the twin warn in ``PortalPages::PortalEstimateDetail``).
 */
import React from "react";
import { useSearchParams } from "react-router-dom";
import EstimateView from "@/components/EstimateView";


export default function PublicEstimateLanding() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  if (typeof window !== "undefined"
      && !window.__phaseA_public_estimate_warned) {
    // eslint-disable-next-line no-console
    console.warn(
      "[phase-a] /e/estimate hit with token — this is the "
      + "recommended magic-link surface.",
    );
    window.__phaseA_public_estimate_warned = true;
  }
  if (!token) {
    return (
      <div
        style={{ padding: 40, textAlign: "center", color: "#7F1D1D" }}
        data-testid="public-estimate-landing-missing-token"
      >
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 8 }}>
          Missing link token
        </h1>
        <p>
          This estimate link is incomplete. Please open the link
          exactly as it was sent to you.
        </p>
      </div>
    );
  }
  return (
    <div
      className="max-w-4xl mx-auto px-2 sm:px-4 lg:px-6 py-4"
      data-testid="public-estimate-landing"
    >
      <EstimateView token={token} isAdmin={false} />
    </div>
  );
}
