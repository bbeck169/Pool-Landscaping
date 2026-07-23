// Feb-2026 · Phase 20 P5 — Public NFC review card page.
//
// Unauthenticated. Renders the tenant's business card in the
// "leave us a review" variant + a tokenized rating link.
import React from "react";
import { useParams, Link } from "react-router-dom";
import { Star, Loader2 } from "lucide-react";

export default function NfcReviewCardPage() {
  const { slug } = useParams();
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const backend = process.env.REACT_APP_BACKEND_URL || "";
    fetch(`${backend}/api/public/nfc-review-card/${encodeURIComponent(slug)}`)
      .then(async (r) => {
        if (!r.ok) {
          if (r.status === 429) throw new Error("Too many requests — please wait a minute.");
          throw new Error(`HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e.message || e)));
  }, [slug]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-zinc-50"
           data-testid="nfc-error">
        <div className="max-w-md text-center">
          <div className="text-lg font-semibold text-zinc-900">Card unavailable</div>
          <div className="text-sm text-zinc-500 mt-1">{error}</div>
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-zinc-50"
           data-testid="nfc-loading">
        <Loader2 className="animate-spin" />
      </div>
    );
  }

  const card = data.business_card || {};
  const grad = `linear-gradient(135deg, ${card.gradient_from || "#0EA5E9"} 0%, ${card.gradient_to || "#16A34A"} 100%)`;
  const reviewLink = data.review_link || `/r/${data.nfc_review_token}`;

  return (
    <div className="min-h-screen bg-zinc-50 flex items-center justify-center p-4"
         data-testid="nfc-review-page">
      <div className="max-w-sm w-full rounded-2xl overflow-hidden shadow-xl bg-white">
        <div className="p-8 text-white text-center" style={{ background: grad }}>
          {card.logo_url ? (
            <img src={card.logo_url} alt=""
                 className="w-16 h-16 rounded-full mx-auto object-cover bg-white/40" />
          ) : (
            <div className="w-16 h-16 rounded-full mx-auto flex items-center justify-center"
                 style={{ backgroundColor: "rgba(255,255,255,0.25)", fontSize: 26, fontWeight: 700 }}>
              {(card.company_name || "?").slice(0, 1).toUpperCase()}
            </div>
          )}
          <div className="mt-3 text-xl font-semibold"
               data-testid="nfc-company-name">
            {card.company_name || "Business"}
          </div>
          {card.tagline ? (
            <div className="text-sm opacity-90 mt-1">{card.tagline}</div>
          ) : null}
        </div>
        <div className="p-6 text-center">
          <div className="text-sm text-zinc-500 mb-3">
            Had a good visit? We'd love your feedback.
          </div>
          <Link
            to={reviewLink}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-md text-sm font-semibold text-white hover:brightness-95"
            style={{ backgroundColor: card.gradient_from || "#0EA5E9" }}
            data-testid="nfc-leave-review-btn"
          >
            <Star size={14} /> Leave us a review
          </Link>
        </div>
      </div>
    </div>
  );
}
