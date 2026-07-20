/**
 * Public reviews widget — Phase 2 (Feb 2026).
 *
 * Full-page marketing surface at ``/reviews/:tenant_slug`` (no auth).
 * Reuses the ``/api/reviews/public/widget/{slug}`` JSON endpoint and
 * paints a branded, mobile-first list with average-star hero + reviews
 * grid.
 */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Star, Loader2, AlertTriangle } from "lucide-react";
import { fetchWidgetJson } from "@/api/reviews";
import { StarRatingDisplay } from "@/components/reviews/StarRatingDisplay";
import { PlatformIcon } from "@/components/reviews/PlatformIcon";

const wrap = {
  minHeight: "100vh",
  background: "linear-gradient(180deg,#F8FAFC 0%,#EFF6FF 60%,#F8FAFC 100%)",
  padding: "40px 16px",
  fontFamily: "'Inter','SF Pro Text',system-ui,sans-serif",
};

export default function PublicReviewsWidgetPage() {
  const { tenant_slug } = useParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetchWidgetJson(tenant_slug, 50)
      .then((d) => {
        if (d?.detail) return setErr(d.detail);
        setData(d);
      })
      .catch((e) => setErr(e.message));
  }, [tenant_slug]);

  return (
    <div style={wrap} data-testid="public-reviews-widget-page">
      <div style={{ maxWidth: 780, margin: "0 auto" }}>
        {err && (
          <div style={{ padding: 24, background: "#fff", borderRadius: 16,
                        textAlign: "center" }}>
            <AlertTriangle size={26} color="#B45309" />
            <div style={{ fontWeight: 700, marginTop: 8 }}>Reviews unavailable</div>
            <div style={{ color: "#64748B", fontSize: 14, marginTop: 4 }}>{err}</div>
          </div>
        )}
        {!err && !data && (
          <div style={{ padding: 32, textAlign: "center" }}>
            <Loader2 size={22} className="animate-spin" />
          </div>
        )}
        {data && (
          <>
            <div style={{ padding: "28px 24px", background: "#fff",
                          borderRadius: 24, marginBottom: 20,
                          boxShadow: "0 10px 40px -12px rgba(15,23,42,0.10)" }}>
              <div style={{ fontSize: 12, textTransform: "uppercase",
                             letterSpacing: 1, color: "#64748B",
                             marginBottom: 4 }}>Customer reviews</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: "#0F172A" }}>
                {data.tenant_name || "Our team"}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12,
                             marginTop: 16 }}>
                <div style={{ fontSize: 48, fontWeight: 700, color: "#0F172A", lineHeight: 1 }}>
                  {(data.avg_star || 0).toFixed(1)}
                </div>
                <div>
                  <StarRatingDisplay value={data.avg_star || 0} size={22} />
                  <div style={{ fontSize: 13, color: "#64748B", marginTop: 4 }}>
                    Based on {data.total_public || 0} public review{(data.total_public || 0) === 1 ? "" : "s"}
                  </div>
                </div>
              </div>
            </div>

            {(data.reviews || []).length ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}
                    data-testid="public-widget-reviews">
                {(data.reviews || []).map((r, i) => (
                  <div key={i} style={{ background: "#fff", padding: "18px 20px",
                                         borderRadius: 16, boxShadow: "0 4px 14px -8px rgba(15,23,42,0.10)" }}
                       data-testid={`public-widget-review-${i}`}>
                    <div style={{ display: "flex", justifyContent: "space-between",
                                   alignItems: "center", marginBottom: 8 }}>
                      <StarRatingDisplay value={r.star_rating || 0} size={16} />
                      <span style={{ fontSize: 12, color: "#64748B",
                                       textTransform: "capitalize",
                                       display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <PlatformIcon code={r.platform} size={13} /> {r.platform || ""}
                      </span>
                    </div>
                    {r.review_text ? (
                      <div style={{ fontSize: 15, color: "#0F172A",
                                     lineHeight: 1.55, marginBottom: 10 }}>
                        {r.review_text}
                      </div>
                    ) : (
                      <div style={{ fontSize: 14, color: "#94A3B8",
                                     fontStyle: "italic", marginBottom: 10 }}>
                        Rating only.
                      </div>
                    )}
                    <div style={{ fontSize: 12, color: "#64748B" }}>
                      — {r.reviewer_name || "Anonymous"}
                      {r.created_at ? ` · ${(r.created_at || "").slice(0, 10)}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: 32, textAlign: "center", background: "#fff",
                             borderRadius: 16, color: "#64748B" }}>
                <Star size={24} />
                <div style={{ marginTop: 8, fontWeight: 600, color: "#0F172A" }}>
                  No reviews yet — check back soon!
                </div>
              </div>
            )}

            <div style={{ marginTop: 32, textAlign: "center", fontSize: 11,
                           color: "#94A3B8" }}>
              Powered by AquaTerra CRM
            </div>
          </>
        )}
      </div>
    </div>
  );
}
