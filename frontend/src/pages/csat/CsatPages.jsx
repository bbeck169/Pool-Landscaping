import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { Star, TrendingUp, TrendingDown, Minus, Send, MessageCircle } from "lucide-react";

/* ─── shared bits ────────────────────────────────────────────────── */
const H = ({ title, sub, right }) => (
  <div className="flex items-start justify-between mb-6">
    <div>
      <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
      {sub && <p className="text-sm mt-1" style={{ color: colors.muted }}>{sub}</p>}
    </div>
    {right}
  </div>
);

const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);

const Tile = ({ label, value, sub, testId, tone }) => (
  <Card className="p-4" testId={testId}>
    <div className="text-xs uppercase tracking-wide" style={{ color: colors.muted }}>{label}</div>
    <div className="text-3xl font-bold mt-1" style={{ color: tone || colors.onSurface }}>{value}</div>
    {sub && <div className="text-xs mt-1" style={{ color: colors.muted }}>{sub}</div>}
  </Card>
);

const npsTone = (n) => {
  if (n == null) return colors.muted;
  if (n >= 9) return "#16A34A";
  if (n <= 6) return "#DC2626";
  return "#D97706";
};
const npsLabel = (n) => (n == null ? "—" : n >= 9 ? "Promoter" : n <= 6 ? "Detractor" : "Passive");

/* ─── /csat — dashboard ─────────────────────────────────────────── */
export function CsatDashboard() {
  const [data, setData] = useState({ summary: null, surveys: [] });
  const [filter, setFilter] = useState("all");
  const load = () => api.get("/csat").then(setData).catch(() => {});
  useEffect(() => { load(); }, []);

  const rows = useMemo(() => {
    if (!data.surveys) return [];
    if (filter === "responded") return data.surveys.filter((s) => s.responded_at);
    if (filter === "pending") return data.surveys.filter((s) => !s.responded_at);
    if (filter === "detractor") return data.surveys.filter((s) => (s.nps_score ?? 100) <= 6);
    if (filter === "promoter") return data.surveys.filter((s) => (s.nps_score ?? -1) >= 9);
    return data.surveys;
  }, [data, filter]);

  const s = data.summary || {};
  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="csat-dashboard">
      <H title="Customer Satisfaction"
         sub="NPS & CSAT survey responses. Detractors auto-open a follow-up task; promoters enroll in the review-request sequence."
      />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <Tile testId="csat-tile-nps" label="NPS" value={s.nps_score ?? 0}
              tone={npsTone(s.nps_score >= 30 ? 10 : s.nps_score <= -1 ? 0 : 7)}
              sub={`${s.total_responded || 0} responses`} />
        <Tile testId="csat-tile-csat" label="Avg CSAT" value={(s.csat_avg || 0).toFixed(1) + " ★"} sub="1-5 scale" />
        <Tile testId="csat-tile-promoters" label="Promoters" value={s.promoters || 0}
              tone="#16A34A" sub="9-10" />
        <Tile testId="csat-tile-passives" label="Passives" value={s.passives || 0}
              tone="#D97706" sub="7-8" />
        <Tile testId="csat-tile-detractors" label="Detractors" value={s.detractors || 0}
              tone="#DC2626" sub="0-6" />
      </div>
      <div className="flex items-center gap-3 mb-3">
        <div className="text-xs uppercase tracking-wide" style={{ color: colors.muted }}>Response rate</div>
        <div className="text-sm font-bold" style={{ color: colors.onSurface }}>{s.response_rate || 0}%</div>
        <div className="ml-6 text-xs" style={{ color: colors.muted }}>{s.total_sent || 0} sent • {s.total_responded || 0} responded</div>
      </div>
      <div className="flex gap-2 mb-4 flex-wrap" data-testid="csat-filter-row">
        {["all", "responded", "pending", "detractor", "promoter"].map((f) => (
          <button key={f} onClick={() => setFilter(f)}
                  className="px-3 py-1.5 rounded-full text-xs font-semibold"
                  style={{
                    background: filter === f ? brandGradientCss : colors.surface,
                    color: filter === f ? "#fff" : colors.onSurface,
                    border: `1px solid ${filter === f ? "transparent" : colors.border}`,
                  }}
                  data-testid={`csat-filter-${f}`}>{f.charAt(0).toUpperCase() + f.slice(1)}</button>
        ))}
      </div>
      <Card className="overflow-hidden">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wide"
             style={{ color: colors.muted, backgroundColor: colors.surfaceSecondary, borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-3">Customer</div>
          <div className="col-span-3">Job</div>
          <div className="col-span-1">NPS</div>
          <div className="col-span-1">CSAT</div>
          <div className="col-span-2">Sent</div>
          <div className="col-span-2">Status</div>
        </div>
        {rows.map((r) => (
          <a key={r.id} href={`/csat/detail/${r.id}`}
             className="grid grid-cols-12 gap-2 px-4 py-3 text-sm hover:brightness-95 transition"
             style={{ borderBottom: `1px solid ${colors.border}`, color: colors.onSurface }}
             data-testid={`csat-row-${r.id}`}>
            <div className="col-span-3 font-semibold truncate">{r.customer_name || "—"}</div>
            <div className="col-span-3 truncate" style={{ color: colors.muted }}>{r.job_title || "—"}</div>
            <div className="col-span-1 font-bold" style={{ color: npsTone(r.nps_score) }}>{r.nps_score ?? "—"}</div>
            <div className="col-span-1">{r.csat_score ? `${r.csat_score}★` : "—"}</div>
            <div className="col-span-2 text-xs" style={{ color: colors.muted }}>{(r.sent_at || "").slice(0, 10)}</div>
            <div className="col-span-2 text-xs font-semibold" style={{ color: r.responded_at ? "#16A34A" : colors.muted }}>
              {r.responded_at ? npsLabel(r.nps_score) : "Pending"}
            </div>
          </a>
        ))}
        {rows.length === 0 && (
          <div className="p-6 text-center text-sm" style={{ color: colors.muted }}>No surveys match this filter.</div>
        )}
      </Card>
    </div>
  );
}

/* ─── /csat/:sid — detail ─────────────────────────────────────────── */
export function CsatDetail() {
  const { sid } = useParams();
  const [row, setRow] = useState(null);
  useEffect(() => { api.get(`/csat/${sid}`).then(setRow).catch(() => {}); }, [sid]);
  if (!row) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="csat-detail">
      <a href="/csat" className="text-sm font-semibold" style={{ color: colors.brand }}>← All surveys</a>
      <H title={`Survey — ${row.customer_name || ""}`} sub={row.job_title || ""} />
      <Card className="p-5 mb-4">
        <div className="grid grid-cols-3 gap-4">
          <Tile label="NPS" value={row.nps_score ?? "—"} tone={npsTone(row.nps_score)}
                sub={npsLabel(row.nps_score)} testId="detail-nps" />
          <Tile label="CSAT" value={row.csat_score ? `${row.csat_score}★` : "—"} testId="detail-csat" />
          <Tile label="Status" value={row.responded_at ? "Responded" : "Pending"}
                tone={row.responded_at ? "#16A34A" : colors.muted}
                sub={(row.responded_at || row.sent_at || "").slice(0, 10)}
                testId="detail-status" />
        </div>
      </Card>
      {row.comment && (
        <Card className="p-4 mb-4" testId="detail-comment">
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: colors.muted }}>Comment</div>
          <div className="text-sm" style={{ color: colors.onSurface }}>{row.comment}</div>
        </Card>
      )}
      <Card className="p-4 text-xs" testId="detail-meta">
        <div style={{ color: colors.muted }}>Magic link: <code>{row.url}</code></div>
        <div className="mt-1" style={{ color: colors.muted }}>Channel: {row.channel} · Sent {row.sent_at}</div>
      </Card>
    </div>
  );
}

/* ─── /csat/:token — public survey (no auth) ─────────────────────── */
export function PublicCsat() {
  const { token } = useParams();
  const [meta, setMeta] = useState(null);
  const [nps, setNps] = useState(9);
  const [csatVal, setCsatVal] = useState(5);
  const [comment, setComment] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const BASE = process.env.REACT_APP_BACKEND_URL;

  useEffect(() => {
    fetch(`${BASE}/api/public/csat/${token}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then(setMeta)
      .catch(() => setError("Survey not found or expired."));
  }, [BASE, token]);

  if (error) return (
    <div className="min-h-screen flex items-center justify-center p-6" data-testid="public-csat-error">
      <Card className="p-8 max-w-md text-center">
        <div className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>Not available</div>
        <div className="text-sm" style={{ color: colors.muted }}>{error}</div>
      </Card>
    </div>
  );
  if (!meta) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  if (meta.responded_at || done) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6"
           style={{ background: brandGradientCss }} data-testid="public-csat-thanks">
        <Card className="p-10 max-w-md text-center">
          <div className="text-5xl mb-3">🎉</div>
          <div className="text-2xl font-bold mb-2" style={{ color: colors.onSurface }}>Thanks for your feedback!</div>
          <div className="text-sm" style={{ color: colors.muted }}>We appreciate you taking the time.</div>
        </Card>
      </div>
    );
  }

  const submit = async () => {
    setSubmitting(true);
    try {
      const r = await fetch(`${BASE}/api/public/csat/${token}/submit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nps_score: nps, csat_score: csatVal, comment }),
      });
      if (!r.ok) throw new Error("submit failed");
      setDone(true);
    } catch (e) {
      setError("Could not submit. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen p-6 flex items-center justify-center"
         style={{ background: brandGradientCss }} data-testid="public-csat-form">
      <Card className="p-6 md:p-8 max-w-lg w-full">
        <div className="text-center mb-6">
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: colors.muted }}>AquaTerra</div>
          <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>How did we do?</div>
          <div className="text-sm mt-1" style={{ color: colors.muted }}>
            {meta.customer_name ? `Hi ${meta.customer_name}, ` : ""}rate your recent service.
          </div>
        </div>

        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-semibold" style={{ color: colors.onSurface }}>
              How likely are you to recommend us? (0–10)
            </label>
            <div className="text-2xl font-bold" style={{ color: npsTone(nps) }} data-testid="nps-value">{nps}</div>
          </div>
          <input type="range" min="0" max="10" value={nps}
                 onChange={(e) => setNps(parseInt(e.target.value, 10))}
                 className="w-full accent-current"
                 style={{ accentColor: npsTone(nps) }}
                 data-testid="nps-slider" />
          <div className="flex justify-between text-[10px] mt-1" style={{ color: colors.muted }}>
            <span>Not likely</span><span>Extremely likely</span>
          </div>
        </div>

        <div className="mb-6">
          <label className="text-sm font-semibold block mb-2" style={{ color: colors.onSurface }}>
            Overall satisfaction
          </label>
          <div className="flex gap-2" data-testid="csat-stars">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => setCsatVal(n)} data-testid={`csat-star-${n}`}
                      className="p-1 transition"
                      style={{ color: n <= csatVal ? "#EAB308" : colors.border }}>
                <Star size={28} fill={n <= csatVal ? "#EAB308" : "none"} />
              </button>
            ))}
          </div>
        </div>

        <div className="mb-6">
          <label className="text-sm font-semibold block mb-2" style={{ color: colors.onSurface }}>
            Anything else? (optional)
          </label>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                    style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
                    data-testid="csat-comment" />
        </div>

        <button onClick={submit} disabled={submitting}
                className="w-full py-3 rounded-xl font-bold text-white"
                style={{ background: brandGradientCss, opacity: submitting ? 0.7 : 1 }}
                data-testid="csat-submit">
          {submitting ? "Submitting…" : "Submit feedback"}
        </button>
        {error && <div className="mt-3 text-sm text-center" style={{ color: colors.error }}>{error}</div>}
      </Card>
    </div>
  );
}
