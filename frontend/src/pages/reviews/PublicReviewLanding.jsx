/**
 * Public review-request landing page — Phase 2 (Feb 2026).
 *
 * Mounted at ``/reviews/r/:token`` (unauthenticated). Consumes the
 * three public endpoints that shipped in Phase 1:
 *   - GET  /api/reviews/public/r/{token}                → landing payload
 *   - POST /api/reviews/public/r/{token}/rating         → submit stars
 *   - POST /api/reviews/public/r/{token}/platform-clicked → 4-5★ flow
 *   - POST /api/reviews/public/r/{token}/private-feedback → 1-3★ flow
 *
 * Deliberately isolated from AppLayout (rendered outside the router
 * shell in App.js) so it works without auth chrome.
 */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, AlertTriangle, Loader2, Star } from "lucide-react";
import {
  fetchPublicLanding, submitPublicRating,
  submitPublicPlatformClicked, submitPublicPrivateFeedback,
} from "@/api/reviews";
import { StarRatingInput } from "@/components/reviews/StarRatingInput";
import { StarRatingDisplay } from "@/components/reviews/StarRatingDisplay";
import { PlatformIcon } from "@/components/reviews/PlatformIcon";

const wrap = {
  minHeight: "100vh",
  background: "linear-gradient(135deg,#F8FAFC 0%,#EFF6FF 100%)",
  padding: "32px 16px",
  fontFamily: "'Inter','SF Pro Text',system-ui,sans-serif",
};
const card = {
  maxWidth: 640, margin: "0 auto", padding: "36px 28px",
  background: "#fff", borderRadius: 24,
  boxShadow: "0 10px 40px -12px rgba(15,23,42,0.15)",
};

export default function PublicReviewLanding() {
  const { token } = useParams();
  const [state, setState] = useState({ phase: "loading" }); // loading | landing | choose_platform | private | expired | already | ok | error
  const [error, setError] = useState(null);
  const [rating, setRating] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [landing, setLanding] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchPublicLanding(token)
      .then((d) => {
        if (cancelled) return;
        if (d?.detail) {
          setError(d.detail);
          setState({ phase: "error" });
          return;
        }
        setLanding(d);
        if (d.expired) return setState({ phase: "expired" });
        if (d.already_submitted) {
          setRating(d.star_rating_submitted || 0);
          return setState({ phase: "already" });
        }
        setState({ phase: "landing" });
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e.message);
        setState({ phase: "error" });
      });
    return () => { cancelled = true; };
  }, [token]);

  const onRatingChosen = async (n) => {
    setRating(n);
    setSubmitting(true);
    try {
      const r = await submitPublicRating(token, n);
      if (r.next_step === "choose_platform") setState({ phase: "choose_platform" });
      else setState({ phase: "private" });
    } catch (e) {
      setError(e.message);
      setState({ phase: "error" });
    } finally { setSubmitting(false); }
  };

  const onPlatformClick = async (platform_code, url) => {
    try {
      const r = await submitPublicPlatformClicked(token, platform_code);
      const redirect = r.redirect_url || url;
      setState({ phase: "ok" });
      // Give the state paint a beat, then open the review page in a new tab.
      setTimeout(() => { window.open(redirect, "_blank", "noopener"); }, 250);
    } catch (e) { setError(e.message); }
  };

  const onSubmitPrivate = async () => {
    if (!feedback.trim()) return setError("Please share a few words.");
    setSubmitting(true);
    try {
      await submitPublicPrivateFeedback(token, feedback.trim());
      setState({ phase: "ok", privateMode: true });
    } catch (e) { setError(e.message); }
    finally { setSubmitting(false); }
  };

  return (
    <div style={wrap} data-testid="public-review-landing">
      <div style={card}>
        <BrandHeader landing={landing} />

        {state.phase === "loading" && (
          <Center><Loader2 size={22} className="animate-spin" /> Loading…</Center>
        )}

        {state.phase === "expired" && (
          <Center>
            <AlertTriangle size={28} color="#B45309" />
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 12 }}>
              This link is no longer active
            </div>
            <div style={{ fontSize: 14, color: "#64748B", marginTop: 6 }}>
              Please contact us directly and we'll send a fresh link.
            </div>
          </Center>
        )}

        {state.phase === "already" && (
          <Center>
            <CheckCircle2 size={30} color="#16A34A" />
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 12 }}>
              Thanks — we already received your rating
            </div>
            <div style={{ marginTop: 8 }}>
              <StarRatingDisplay value={rating} size={26} showValue />
            </div>
          </Center>
        )}

        {state.phase === "error" && (
          <Center>
            <AlertTriangle size={28} color="#B91C1C" />
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 12 }}>Something went wrong</div>
            <div style={{ fontSize: 14, color: "#64748B", marginTop: 6 }}>{error || "Please try again."}</div>
          </Center>
        )}

        {state.phase === "landing" && landing && (
          <>
            <h1 style={{ fontSize: 26, fontWeight: 700, color: "#0F172A", margin: "12px 0 8px",
                          textAlign: "center" }}>
              How did we do{landing.customer_first_name ? `, ${landing.customer_first_name}` : ""}?
            </h1>
            {landing.tech_first_name ? (
              <p style={{ fontSize: 15, color: "#475569", textAlign: "center", margin: "0 0 24px" }}>
                {landing.tech_first_name} recently worked on your service — please share how it went.
              </p>
            ) : (
              <p style={{ fontSize: 15, color: "#475569", textAlign: "center", margin: "0 0 24px" }}>
                Tap a star to rate your recent service — takes ten seconds.
              </p>
            )}
            <div style={{ display: "flex", justifyContent: "center", marginBottom: 12 }}>
              <StarRatingInput value={rating}
                                 onChange={onRatingChosen}
                                 size={44}
                                 disabled={submitting}
                                 testid="public-review-stars" />
            </div>
            {submitting && (
              <Center><Loader2 size={18} className="animate-spin" /> Sending…</Center>
            )}
          </>
        )}

        {state.phase === "choose_platform" && landing && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "#0F172A", margin: "12px 0 8px",
                          textAlign: "center" }}>
              You rock — thank you! 🌟
            </h2>
            <p style={{ fontSize: 15, color: "#475569", textAlign: "center", margin: "0 0 20px" }}>
              Would you mind sharing that on one of these platforms?
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
                 data-testid="public-review-platforms">
              {(landing.platforms || []).map((p) => (
                <button key={p.platform}
                        onClick={() => onPlatformClick(p.platform, p.review_url)}
                        style={platformBtn}
                        data-testid={`public-review-platform-${p.platform}`}>
                  <PlatformIcon code={p.platform} size={20} />
                  <span style={{ marginLeft: 8, fontWeight: 600 }}>{p.display_name}</span>
                </button>
              ))}
            </div>
            {(!landing.platforms || landing.platforms.length === 0) ? (
              <div style={{ marginTop: 20, textAlign: "center", color: "#64748B", fontSize: 14 }}>
                Your workspace hasn't configured a public review platform yet.
              </div>
            ) : null}
          </>
        )}

        {state.phase === "private" && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "#0F172A", margin: "12px 0 8px",
                          textAlign: "center" }}>
              We're sorry it wasn't a 5-star experience
            </h2>
            <p style={{ fontSize: 15, color: "#475569", textAlign: "center", margin: "0 0 20px" }}>
              Tell us what happened so we can make it right. This goes straight to the owner.
            </p>
            <textarea rows={6} value={feedback}
                       onChange={(e) => setFeedback(e.target.value)}
                       placeholder="What happened…"
                       style={textAreaStyle}
                       data-testid="public-review-feedback" />
            {error && <div style={{ color: "#B91C1C", fontSize: 13, marginTop: 8 }}>{error}</div>}
            <div style={{ display: "flex", justifyContent: "center", marginTop: 16 }}>
              <button onClick={onSubmitPrivate} disabled={submitting}
                       style={{ ...primaryBtn, opacity: submitting ? 0.6 : 1 }}
                       data-testid="public-review-feedback-submit">
                {submitting ? "Sending…" : "Send private feedback"}
              </button>
            </div>
          </>
        )}

        {state.phase === "ok" && (
          <Center>
            <CheckCircle2 size={30} color="#16A34A" />
            <div style={{ fontSize: 18, fontWeight: 700, marginTop: 12 }}>
              {state.privateMode ? "Thanks — we'll be in touch shortly" : "Thank you!"}
            </div>
            <div style={{ fontSize: 14, color: "#64748B", marginTop: 6 }}>
              We appreciate you taking a moment.
            </div>
          </Center>
        )}

        <Footer landing={landing} />
      </div>
    </div>
  );
}

function BrandHeader({ landing }) {
  if (!landing) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
      {landing.tenant_logo_url ? (
        <img src={landing.tenant_logo_url} alt={landing.tenant_name || ""}
             style={{ height: 40, width: "auto", borderRadius: 8 }} />
      ) : (
        <div style={{ width: 40, height: 40, borderRadius: 12,
                       background: "#E0F2FE", color: "#0369A1",
                       display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
          <Star size={22} />
        </div>
      )}
      <div>
        <div style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1,
                       color: "#64748B" }}>Rate your service</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#0F172A" }}>
          {landing.tenant_name || "our team"}
        </div>
      </div>
    </div>
  );
}

function Footer({ landing }) {
  return (
    <div style={{ marginTop: 32, borderTop: "1px solid #E2E8F0",
                   paddingTop: 12, textAlign: "center",
                   fontSize: 11, color: "#94A3B8" }}>
      Powered by AquaTerra CRM · {landing?.tenant_name || ""}
    </div>
  );
}

function Center({ children }) {
  return (
    <div style={{ textAlign: "center", padding: "24px 0" }}>{children}</div>
  );
}

const platformBtn = {
  display: "flex", alignItems: "center", justifyContent: "center",
  padding: "14px 12px", background: "#F8FAFC",
  border: "1px solid #E2E8F0", borderRadius: 12,
  cursor: "pointer", fontSize: 15, color: "#0F172A",
  transition: "background 120ms",
};

const primaryBtn = {
  padding: "12px 24px", background: "#0EA5E9", color: "#fff",
  border: "none", borderRadius: 12, fontSize: 15, fontWeight: 600,
  cursor: "pointer",
};

const textAreaStyle = {
  width: "100%", padding: 12, borderRadius: 12,
  border: "1px solid #E2E8F0", fontFamily: "inherit",
  fontSize: 14, background: "#F8FAFC",
  resize: "vertical",
};
