/**
 * Phase 34 · Task T · Feb 2026 — Portal Review Submit page.
 *
 * Reads a magic-link token from the URL (``?token=…``), collects a
 * 1-5 star rating + optional comment, POSTs to
 * ``/api/reviews/public/r/{token}/rating`` (existing gated backend
 * endpoint — no bearer required, token IS the auth), then branches:
 *
 *   * 4-5 stars → Google modal with the tenant's seeded review URL.
 *     Firing a lightweight ``POST /api/reviews/public/r/{token}/google-clicked``
 *     when the customer taps through so we populate
 *     ``google_click_at`` for analytics.
 *   * 1-3 stars → private-feedback thank-you screen (no Google CTA).
 *
 * Backend already implements the gating in
 * ``/app/backend/routers/reviews.py``:
 * ``next_step="choose_platform"`` for high, ``"private_feedback"``
 * for low. This page consumes the response verbatim.
 */
import React, { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { api } from "@/api";
import { brandGradientCss, colors } from "@/theme";
import { Star, ExternalLink } from "lucide-react";

async function _postRating(token, rating, comment) {
  return api.post(`/reviews/public/r/${encodeURIComponent(token)}/rating`, { rating, comment });
}
async function _logGoogleClicked(token) {
  try { await api.post(`/reviews/public/r/${encodeURIComponent(token)}/google-clicked`, {}); }
  catch (_) { /* best-effort analytics */ }
}

export default function PortalReviewSubmit() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { next_step, choose_platform, ... }
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!token) { setError("Missing review token. Please use the link from your email or text."); return; }
    if (!rating) { setError("Please pick a rating."); return; }
    setBusy(true); setError("");
    try {
      const r = await _postRating(token, rating, comment);
      setResult(r || {});
    } catch (err) {
      setError(err?.message || "Could not submit — please try again.");
    } finally { setBusy(false); }
  };

  const isGooglePrompt = result?.next_step === "choose_platform" && rating >= 4;
  const isInternalThanks = result && !isGooglePrompt;
  const platforms = result?.choose_platform || [];
  const google = platforms.find((p) => (p.platform || "").toLowerCase() === "google");
  const googleUrl = google?.url || result?.google_review_url || "";

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
          style={{ background: colors.background }}
          data-testid="review-submit-page">
      <div className="w-full max-w-lg rounded-3xl p-8 shadow-xl"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="h-2 w-24 rounded-full mb-6" style={{ background: brandGradientCss }} />
        {!result ? (
          <>
            <h1 className="text-2xl font-black mb-2" style={{ color: colors.onSurface }}
                data-testid="review-submit-title">
              How was your service?
            </h1>
            <p className="text-sm mb-6" style={{ color: colors.muted }}>
              A minute of your time helps us serve you better.
            </p>
            {error ? (
              <div className="rounded-lg p-3 mb-4 text-sm"
                    style={{ background: "#FEF2F2", border: "1px solid #FCA5A5", color: "#991B1B" }}
                    data-testid="review-error">{error}</div>
            ) : null}
            <form onSubmit={submit} data-testid="review-submit-form" className="space-y-4">
              <div className="flex items-center gap-2" data-testid="review-star-row">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} type="button"
                            aria-label={`${n} star${n > 1 ? "s" : ""}`}
                            onClick={() => setRating(n)}
                            className="p-1 rounded-full hover:brightness-110"
                            data-testid={`review-rating-star-${n}`}>
                    <Star size={38}
                          color={n <= rating ? "#F59E0B" : "#CBD5E1"}
                          fill={n <= rating ? "#F59E0B" : "transparent"} />
                  </button>
                ))}
              </div>
              <textarea rows={4} value={comment}
                          onChange={(e) => setComment(e.target.value)}
                          maxLength={2000}
                          placeholder="Anything else you'd like us to know?"
                          className="w-full px-3 py-2 rounded-lg text-sm"
                          style={{ backgroundColor: colors.surface, color: colors.onSurface,
                                    border: `1px solid ${colors.border}` }}
                          data-testid="review-text" />
              <button type="submit" disabled={busy || !rating}
                        className="w-full py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-60"
                        style={{ background: brandGradientCss }}
                        data-testid="review-submit">
                {busy ? "Sending…" : "Submit review"}
              </button>
            </form>
          </>
        ) : isGooglePrompt ? (
          <div data-testid="review-google-prompt-modal">
            <h1 className="text-2xl font-black mb-2" style={{ color: colors.onSurface }}>
              Thanks for the {rating}-star review!
            </h1>
            <p className="text-sm mb-6" style={{ color: colors.muted }}>
              Would you mind sharing your review on Google too? It only takes a moment
              and helps other customers find us.
            </p>
            {googleUrl ? (
              <a href={googleUrl}
                  target="_blank" rel="noopener noreferrer"
                  onClick={() => _logGoogleClicked(token)}
                  className="w-full inline-flex items-center justify-center gap-2 py-3 rounded-lg text-sm font-semibold text-white mb-3"
                  style={{ background: "linear-gradient(135deg, #0284C7, #4F46E5)" }}
                  data-testid="review-google-cta">
                Post on Google <ExternalLink size={14} />
              </a>
            ) : null}
            <button type="button" onClick={() => setResult({ next_step: "done" })}
                      className="w-full text-center text-sm"
                      style={{ color: colors.muted }}
                      data-testid="review-google-maybe-later">Maybe later</button>
          </div>
        ) : (
          <div data-testid="review-internal-thanks">
            <h1 className="text-2xl font-black mb-2" style={{ color: colors.onSurface }}>
              Thanks for the honest feedback — we'll be in touch.
            </h1>
            <p className="text-sm" style={{ color: colors.muted }}
                data-testid="review-internal-thanks-copy">
              Your feedback goes directly to our management team so we can make things right.
            </p>
          </div>
        )}
        <div className="mt-6 text-xs text-center">
          <Link to="/portal/home" style={{ color: colors.brand }}
                 data-testid="review-back-to-portal">Back to portal</Link>
        </div>
      </div>
    </div>
  );
}
