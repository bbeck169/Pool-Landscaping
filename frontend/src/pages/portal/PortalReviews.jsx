import React, { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Star, Send, ExternalLink, CheckCircle2, Sparkles } from "lucide-react";
import { api } from "@/api";
// DTP-2b · Feb-2026 — dark portal palette. PortalReviews mounts at
// both /portal/reviews (inside PortalThemeShell) and /r/review
// (public magic-link). Binding to ``portalColors`` keeps the two
// surfaces visually consistent — the magic-link landing renders
// dark navy too, matching the shell surface a returning customer
// sees.
import { portalColors as colors, gradients } from "@/theme";
import { useAuth } from "@/auth";
// Phase 18b · Feb-2026 — Portal white-card shell. Wraps the
// export(s) in this file so content renders inside the Phase
// 3d-portal white dashboard card on the deep-navy page bg.
import PortalPageShell from "@/components/portal/PortalPageShell";


/**
 * Feb-2026 · Slice 6 + M6 — Customer portal "Leave a Review" tab.
 *
 * Two modes:
 *   - Logged-in customer  → hits POST /customer-portal/reviews
 *   - Magic-link (?token=)→ verifies the token, hits POST /portal/reviews/via-token
 *
 * Rating-gated flow unchanged (< 4 star → private feedback thank-you,
 * ≥ 4 star → Google review CTA).
 */
export default function PortalReviews() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const [tokenCtx, setTokenCtx] = useState(null);
  const [tokenErr, setTokenErr] = useState("");
  const [tokenChecked, setTokenChecked] = useState(!token);

  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);   // { is_public, google_review_url }
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);

  useEffect(() => {
    if (!token) return;
    api.get(`/portal/review-token/verify?token=${encodeURIComponent(token)}`)
      .then((r) => setTokenCtx(r))
      .catch((e) => setTokenErr(e?.message || "This review link has expired."))
      .finally(() => setTokenChecked(true));
  }, [token]);

  const loadHistory = () => {
    if (!user || user.role !== "customer") return;
    api
      .get("/customer-portal/reviews/my")
      .then((rows) => setHistory(Array.isArray(rows) ? rows : []))
      .catch(() => setHistory([]));
  };

  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // Token mode bypasses auth entirely; logged-in-non-customer still
  // redirects (admins/techs don't leave reviews on the portal).
  if (!token && user && user.role !== "customer") {
    return <Navigate to="/" replace />;
  }

  const submit = async (e) => {
    e?.preventDefault?.();
    if (busy || rating < 1) return;
    setBusy(true);
    setError("");
    try {
      const payload = { rating, comment: comment.trim() };
      let r;
      if (token && tokenCtx) {
        r = await api.post("/portal/reviews/via-token",
                            { ...payload, token });
      } else {
        r = await api.post("/customer-portal/reviews", payload);
      }
      setResult(r);
      loadHistory();
    } catch (err) {
      const msg = err?.message || "";
      if (msg.includes("429") || msg.toLowerCase().includes("wait")) {
        setError(
          "You've just submitted a review. Please wait a few minutes before sending another.",
        );
      } else {
        setError(msg || "Something went wrong — please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setRating(0);
    setHover(0);
    setComment("");
    setResult(null);
    setError("");
  };

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="portal-reviews-page">
      {!token ? (
        <button
          onClick={() => navigate("/portal/home")}
          className="flex items-center gap-1 text-sm font-semibold mb-4"
          style={{ color: colors.muted }}
        >
          <ArrowLeft size={14} /> Home
        </button>
      ) : null}

      {token && !tokenChecked ? (
        <div className="text-sm" style={{ color: colors.muted }}>
          Verifying your review link…
        </div>
      ) : null}

      {token && tokenChecked && tokenErr ? (
        <div className="rounded-2xl p-6 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="portal-review-token-expired">
          <div className="mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-3"
               style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>
            <Star size={22} />
          </div>
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            This review link has expired
          </h2>
          <p className="text-sm mt-2" style={{ color: colors.onSurfaceSecondary }}>
            {tokenErr} Log in to your customer portal to leave a review.
          </p>
          <button onClick={() => navigate("/portal/login")}
                  className="mt-4 text-sm font-semibold"
                  style={{ color: colors.brand }}>
            Log in
          </button>
        </div>
      ) : null}

      {(!token || (tokenCtx && !tokenErr)) ? (
        <>
      <div className="mb-5">
        <h1
          className="text-2xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
        >
          Leave a Review
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          {tokenCtx?.customer_name
            ? `Hi ${tokenCtx.customer_name.split(" ")[0]} — rate your recent service with our team.`
            : "Rate your recent experience with our team."}
        </p>
        {tokenCtx?.service_context ? (
          <div className="mt-3 rounded-xl p-3 inline-flex items-center gap-2"
               style={{ backgroundColor: colors.brandTertiary,
                        color: colors.brand }}
               data-testid="portal-review-service-context">
            <Sparkles size={14} />
            <span className="text-xs font-semibold">
              Reviewing your {tokenCtx.service_context.service_type || "service"}
              {tokenCtx.service_context.completed_at ? (
                <> on {String(tokenCtx.service_context.completed_at).slice(0, 10)}</>
              ) : null}
            </span>
          </div>
        ) : null}
      </div>

      {result ? (
        <ReviewThankYou result={result} onReset={reset} />
      ) : (
        <form
          onSubmit={submit}
          className="rounded-2xl p-5"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          <div
            className="text-xs font-bold uppercase tracking-wide mb-2"
            style={{ color: colors.muted }}
          >
            YOUR RATING
          </div>
          <div
            className="flex items-center gap-1 mb-4"
            data-testid="portal-review-stars"
          >
            {[1, 2, 3, 4, 5].map((n) => {
              const on = (hover || rating) >= n;
              return (
                <button
                  key={n}
                  type="button"
                  onMouseEnter={() => setHover(n)}
                  onMouseLeave={() => setHover(0)}
                  onClick={() => setRating(n)}
                  className="p-1 rounded-lg transition"
                  aria-label={`Rate ${n} star${n > 1 ? "s" : ""}`}
                  data-testid={`portal-review-star-${n}`}
                  data-selected={rating === n ? "1" : "0"}
                >
                  <Star
                    size={30}
                    fill={on ? "#FBBF24" : "transparent"}
                    style={{
                      color: on ? "#FBBF24" : colors.border,
                    }}
                  />
                </button>
              );
            })}
            {rating > 0 ? (
              <span
                className="ml-2 text-sm font-semibold"
                style={{ color: colors.onSurface }}
              >
                {rating}/5
              </span>
            ) : null}
          </div>

          <div
            className="text-xs font-bold uppercase tracking-wide mb-2"
            style={{ color: colors.muted }}
          >
            COMMENTS (OPTIONAL)
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={4}
            maxLength={2000}
            placeholder={
              rating >= 4
                ? "What did we do well?"
                : rating > 0
                ? "How can we improve?"
                : "Tell us about your experience…"
            }
            className="w-full px-3 py-2 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="portal-review-comment"
          />

          {error ? (
            <div
              className="mt-3 text-sm"
              style={{ color: colors.error }}
              data-testid="portal-review-error"
            >
              {error}
            </div>
          ) : null}

          <div className="mt-4 flex items-center justify-end">
            <button
              type="submit"
              disabled={busy || rating < 1}
              className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
              style={{ background: gradients.navyToGreen.css }}
              data-testid="portal-review-submit"
            >
              <Send size={14} /> {busy ? "Sending…" : "Submit review"}
            </button>
          </div>
        </form>
      )}

      {/* History */}
      {history.length > 0 ? (
        <div className="mt-8" data-testid="portal-review-history">
          <h2
            className="text-sm font-bold uppercase tracking-wide mb-2"
            style={{ color: colors.muted }}
          >
            YOUR PAST REVIEWS
          </h2>
          <ul className="space-y-2">
            {history.map((row) => (
              <li
                key={row.id}
                className="rounded-xl p-3"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.divider}`,
                }}
                data-testid={`portal-review-history-row-${row.id}`}
              >
                <div className="flex items-center gap-2">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Star
                      key={n}
                      size={14}
                      fill={n <= (row.rating || 0) ? "#FBBF24" : "transparent"}
                      style={{
                        color: n <= (row.rating || 0) ? "#FBBF24" : colors.border,
                      }}
                    />
                  ))}
                  <span
                    className="text-xs ml-1"
                    style={{ color: colors.muted }}
                  >
                    {String(row.created_at || "").slice(0, 10)}
                  </span>
                  {row.is_public ? null : (
                    <span
                      className="ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                      style={{
                        backgroundColor: "#FEF3C7",
                        color: "#92400E",
                      }}
                    >
                      PRIVATE
                    </span>
                  )}
                </div>
                {row.comment ? (
                  <div
                    className="text-sm mt-1"
                    style={{ color: colors.onSurface }}
                  >
                    {row.comment}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      </>
      ) : null}
    </div>
  );
}


function ReviewThankYou({ result, onReset }) {
  const { is_public, google_review_url } = result || {};

  if (!is_public) {
    return (
      <div
        className="rounded-2xl p-6 text-center"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="portal-review-thankyou-private"
      >
        <div className="mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-3"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}>
          <CheckCircle2 size={24} />
        </div>
        <h2
          className="text-lg font-bold"
          style={{ color: colors.onSurface }}
        >
          Thanks — we've received your feedback.
        </h2>
        <p
          className="text-sm mt-2"
          style={{ color: colors.onSurfaceSecondary }}
        >
          A team member will follow up shortly to make things right.
        </p>
        <button
          onClick={onReset}
          className="mt-4 text-sm font-semibold"
          style={{ color: colors.brand }}
          data-testid="portal-review-write-another"
        >
          Write another
        </button>
      </div>
    );
  }

  return (
    <PortalPageShell>
    <div
      className="rounded-2xl p-6 text-center"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="portal-review-thankyou-google"
    >
      <div className="mx-auto w-12 h-12 rounded-full flex items-center justify-center mb-3"
           style={{ backgroundColor: "#DCFCE7", color: "#166534" }}>
        <CheckCircle2 size={24} />
      </div>
      <h2
        className="text-lg font-bold"
        style={{ color: colors.onSurface }}
      >
        Thanks for the great rating!
      </h2>
      {google_review_url ? (
        <>
          <p
            className="text-sm mt-2 mb-4"
            style={{ color: colors.onSurfaceSecondary }}
          >
            Would you mind sharing it on Google? It really helps our team
            reach more homeowners.
          </p>
          <a
            href={google_review_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-5 py-3 rounded-xl text-sm font-bold text-white"
            style={{ background: gradients.navyToGreen.css }}
            data-testid="portal-review-google-btn"
          >
            <ExternalLink size={16} /> Share on Google
          </a>
        </>
      ) : (
        <p
          className="text-sm mt-2"
          style={{ color: colors.onSurfaceSecondary }}
        >
          We really appreciate your feedback.
        </p>
      )}
      <div className="mt-4">
        <button
          onClick={onReset}
          className="text-sm font-semibold"
          style={{ color: colors.brand }}
        >
          Write another
        </button>
      </div>
    </div>
    </PortalPageShell>
  );
}
