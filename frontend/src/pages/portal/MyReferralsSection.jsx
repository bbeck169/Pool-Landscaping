/**
 * Slice O.2 · Portal — My Referrals section.
 *
 * Renders below the Refer a Friend form when the customer has at least
 * one submitted referral. Shows total sent / conversions / rewards
 * earned + a per-row list with status pill.
 */
import React, { useEffect, useState } from "react";
import { Sparkles, Users, DollarSign } from "lucide-react";
import { api } from "@/api";
// DTP-2 · Feb-2026 — dark portal palette.
import { portalColors as colors } from "@/theme";

const STATUS_TONE = {
  new: { bg: "#DBEAFE", fg: "#1E3A8A", label: "Sent" },
  contacted: { bg: "#FEF3C7", fg: "#854D0E", label: "Contacted" },
  converted: { bg: "#DCFCE7", fg: "#166534", label: "Converted" },
};

function fmtMoney(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

export default function MyReferralsSection() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get("/customer-portal/referrals/my")
        .then((r) => { if (!cancelled) setData(r); })
        .catch(() => setData({ referrals: [], summary: null }));
    load();
    // Refresh when returning to the tab so rewards land promptly after
    // conversion without a full reload.
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => { cancelled = true; window.removeEventListener("focus", onFocus); };
  }, []);

  if (!data || !data.referrals || data.referrals.length === 0) return null;
  const s = data.summary || {};

  return (
    <div
      className="rounded-2xl p-6 my-4"
      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="portal-my-referrals-list"
    >
      <div className="flex items-center gap-2 mb-3">
        <Sparkles size={16} color={colors.brand} />
        <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>
          My Referrals
        </h3>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <SummaryTile icon={Users} label="Sent" value={s.total_referrals || 0} />
        <SummaryTile icon={Sparkles} label="Conversions" value={s.conversions || 0} />
        <SummaryTile
          icon={DollarSign}
          label="Rewards"
          value={fmtMoney(s.rewards_earned)}
          tone={s.rewards_earned > 0 ? "#166534" : colors.muted}
        />
      </div>

      <ul className="space-y-2">
        {data.referrals.map((r) => {
          const tone = STATUS_TONE[r.status] || STATUS_TONE.new;
          return (
            <li
              key={r.id}
              className="flex items-center gap-3 rounded-lg px-3 py-2"
              style={{ background: colors.surfaceSecondary }}
              data-testid={`portal-my-referral-${r.id}`}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {r.friend_name}
                </div>
                <div className="text-[11px]" style={{ color: colors.muted }}>
                  Sent {String(r.created_at || "").slice(0, 10)}
                  {r.service_of_interest ? ` · ${r.service_of_interest}` : ""}
                </div>
              </div>
              {r.reward_applied_at && r.reward_amount ? (
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded-full"
                  style={{ background: "#DCFCE7", color: "#166534" }}
                  title={`Credit applied ${String(r.reward_applied_at).slice(0, 10)}`}
                >
                  +{fmtMoney(r.reward_amount)}
                </span>
              ) : null}
              <span
                className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
                style={{ background: tone.bg, color: tone.fg }}
              >
                {tone.label}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SummaryTile({ icon: Icon, label, value, tone }) {
  return (
    <div
      className="rounded-lg p-2 text-center"
      style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
    >
      <div className="flex justify-center mb-1">
        <Icon size={14} color={tone || colors.brand} />
      </div>
      <div className="text-lg font-bold" style={{ color: tone || colors.onSurface }}>
        {value}
      </div>
      <div className="text-[10px] uppercase font-bold" style={{ color: colors.muted }}>
        {label}
      </div>
    </div>
  );
}
