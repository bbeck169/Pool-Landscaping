/**
 * Phase 20B.4 · Admin referral tier editor + polished analytics dashboard.
 */
import React, { useEffect, useState } from 'react';
import { Trophy, Trash2, Save, TrendingUp, Users, LineChart } from 'lucide-react';
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/** ── /admin/referrals/settings ────────────────────────────────────────── */
export function ReferralTiers() {
  const [tiers, setTiers] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    api.get("/referrals/settings").then((r) => setTiers(r.tiers || []));
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/referrals/settings", { tiers });
      setTiers(r.tiers);
      setToast("Tiers saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };

  if (!tiers) return <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="admin-referral-tiers">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Trophy size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Referral Reward Tiers
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Reward referrers based on their cumulative approved conversion count.
        </p>
      </div>

      <div className="rounded-2xl p-4 space-y-3 mb-6"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="referral-tiers-list">
        <div className="grid grid-cols-12 gap-2 text-[10px] font-bold uppercase tracking-wider"
             style={{ color: colors.muted }}>
          <div className="col-span-3">Conversion range</div>
          <div className="col-span-3">Credit %</div>
          <div className="col-span-3">Months</div>
          <div className="col-span-3">Preview</div>
        </div>
        {tiers.map((t, i) => (
          <div key={i} className="grid grid-cols-12 gap-2 items-center"
               data-testid={`tier-row-${i}`}>
            <div className="col-span-3 flex items-center gap-1">
              <input type="number" min={1} value={t.conversion_min}
                     onChange={(e) => {
                       const next = [...tiers]; next[i].conversion_min = Number(e.target.value);
                       setTiers(next);
                     }}
                     className="w-1/2 p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
              <span className="text-xs" style={{ color: colors.muted }}>–</span>
              <input type="number" min={1} value={t.conversion_max}
                     onChange={(e) => {
                       const next = [...tiers]; next[i].conversion_max = Number(e.target.value);
                       setTiers(next);
                     }}
                     className="w-1/2 p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
            </div>
            <div className="col-span-3">
              <input type="number" min={1} max={100} value={t.credit_pct}
                     onChange={(e) => {
                       const next = [...tiers]; next[i].credit_pct = Number(e.target.value);
                       setTiers(next);
                     }}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
            </div>
            <div className="col-span-3">
              <input type="number" min={1} max={12} value={t.credit_months}
                     onChange={(e) => {
                       const next = [...tiers]; next[i].credit_months = Number(e.target.value);
                       setTiers(next);
                     }}
                     className="w-full p-2 text-sm rounded-lg"
                     style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
            </div>
            <div className="col-span-2 text-xs" style={{ color: colors.muted }}>
              {`${t.credit_pct}% off ${t.credit_months}mo`}
            </div>
            <button onClick={() => setTiers(tiers.filter((_, j) => j !== i))}
                    className="col-span-1 p-1 rounded"
                    style={{ color: "#DC2626" }}
                    data-testid={`tier-delete-${i}`}>
              <Trash2 size={14}/>
            </button>
          </div>
        ))}
        <button onClick={() => {
                  const last = tiers[tiers.length - 1] || { conversion_max: 0 };
                  setTiers([...tiers, {
                    conversion_min: (last.conversion_max || 0) + 1,
                    conversion_max: (last.conversion_max || 0) + 5,
                    credit_pct: 50, credit_months: 1,
                  }]);
                }}
                className="text-xs font-bold" style={{ color: colors.brand }}
                data-testid="tier-add">
          + Add tier
        </button>
      </div>

      <button onClick={save} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-bold disabled:opacity-60"
              style={{ background: brandGradientCss, color: "#fff" }}
              data-testid="tier-save">
        <Save size={14}/> {saving ? "Saving…" : "Save Tiers"}
      </button>

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg z-50"
             style={{ backgroundColor: colors.onSurface, color: "#fff" }}
             data-testid="tier-toast">
          {toast}
        </div>
      )}
    </div>
  );
}

/** ── /admin/referrals/analytics ──────────────────────────────────────── */
export default function ReferralAnalyticsV2() {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get("/referrals/admin/analytics/v2").then(setData);
  }, []);

  if (!data) return <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  const f = data.funnel;
  const funnelSteps = [
    { key: "invites",          label: "Invites",          value: f.invites },
    { key: "signups",          label: "Signups",          value: f.signups },
    { key: "converted",        label: "Converted",        value: f.converted },
    { key: "credits_redeemed", label: "Credits redeemed", value: f.credits_redeemed },
  ];
  const maxF = Math.max(1, ...funnelSteps.map((x) => x.value));

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-referral-analytics">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <TrendingUp size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Referral Analytics
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Funnel, revenue attribution, cohorts, and top referrers.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        {/* Funnel */}
        <div className="rounded-2xl p-5" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="ra-funnel">
          <div className="text-xs font-bold uppercase mb-3" style={{ color: colors.muted }}>Funnel</div>
          {funnelSteps.map((s) => (
            <div key={s.key} className="mb-2">
              <div className="flex items-center justify-between text-xs mb-1">
                <span style={{ color: colors.onSurface }}>{s.label}</span>
                <span className="font-bold" style={{ color: colors.brand }}>{s.value}</span>
              </div>
              <div className="w-full h-2 rounded-full overflow-hidden" style={{ backgroundColor: colors.background }}>
                <div className="h-full" style={{ width: `${(s.value / maxF) * 100}%`, background: brandGradientCss }} />
              </div>
            </div>
          ))}
        </div>

        {/* Revenue attribution */}
        <div className="rounded-2xl p-5"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="ra-revenue">
          <div className="text-xs font-bold uppercase mb-3" style={{ color: colors.muted }}>
            Revenue attributed
          </div>
          <div className="text-4xl font-bold mb-1" style={{ color: colors.brand }}>
            ${(data.revenue_attribution.total_usd || 0).toLocaleString()}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Cumulative from customers acquired via referrals.
          </div>
          <div className="mt-3 space-y-1 max-h-40 overflow-auto">
            {data.revenue_attribution.by_referrer_top10.map((r) => (
              <div key={r.customer_id} className="text-xs flex justify-between"
                   style={{ color: colors.muted }}>
                <span className="truncate">{r.customer_id.slice(0, 8)}</span>
                <b>${(r.revenue_usd || 0).toLocaleString()}</b>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Leaderboard */}
      <div className="rounded-2xl p-5 mb-6"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="ra-leaderboard">
        <div className="text-xs font-bold uppercase mb-3 flex items-center gap-1"
             style={{ color: colors.muted }}>
          <Users size={13}/> Top Referrers
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted }}>
              <th className="text-left text-xs uppercase pb-2">Customer</th>
              <th className="text-right text-xs uppercase pb-2">Converted</th>
              <th className="text-right text-xs uppercase pb-2">Revenue</th>
            </tr>
          </thead>
          <tbody>
            {data.leaderboard.rows.map((r) => (
              <tr key={r.customer_id} style={{ borderTop: `1px solid ${colors.border}` }}>
                <td className="py-2" style={{ color: colors.onSurface }}>{r.name}</td>
                <td className="py-2 text-right font-bold" style={{ color: colors.brand }}>
                  {r.converted_count}
                </td>
                <td className="py-2 text-right" style={{ color: colors.muted }}>
                  ${(r.revenue_attributed || 0).toLocaleString()}
                </td>
              </tr>
            ))}
            {data.leaderboard.rows.length === 0 && (
              <tr><td colSpan={3} className="py-4 text-center" style={{ color: colors.muted }}>
                No approved referrals yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Cohort curve */}
      <div className="rounded-2xl p-5"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="ra-cohort">
        <div className="text-xs font-bold uppercase mb-3 flex items-center gap-1"
             style={{ color: colors.muted }}>
          <LineChart size={13}/> Cohorts (by referrer's first-invite month)
        </div>
        <div className="text-xs space-y-1 max-h-40 overflow-auto">
          {data.cohort_curve.length === 0 && (
            <div style={{ color: colors.muted }}>No cohort data yet.</div>
          )}
          {data.cohort_curve.map((c) => (
            <div key={c.cohort} className="flex items-center gap-3">
              <span style={{ color: colors.muted, minWidth: 60 }}>{c.cohort}</span>
              <div className="flex-1 flex gap-1">
                {c.months.map((m) => (
                  <div key={m.month} className="px-2 py-0.5 rounded text-[10px]"
                       style={{ backgroundColor: colors.brand + "22", color: colors.brand }}>
                    {m.month}: {m.conversions}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
