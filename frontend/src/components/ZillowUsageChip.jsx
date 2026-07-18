/**
 * Phase 56.9b Step 6 — Zillow usage chip + rate-limited banner.
 *
 * Mounts on all 4 Zillow-backed surfaces (Property Lookup, D2D
 * Canvassing Map, D2D Sold Leads, Virtual Bid). Reads /zillow/me/usage
 * and renders:
 *   • techs: "Zillow: X/20 today, Y/200 month" — yellow ≥80%, red at 100%
 *   • admin/super_admin: "Zillow: X used this month" (uncapped)
 *
 * When a 429 comes back from a guarded endpoint the caller can flip
 * `rateLimited` and this component renders the "Ask admin for more"
 * banner in place of the chip.
 */
import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const POLL_MS = 60_000;

export function ZillowUsageChip({ rateLimited, refreshKey, testid = "zillow-usage-chip" }) {
  const [caps, setCaps] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/zillow/me/usage");
      setCaps(r);
      setErr(null);
    } catch (e) {
      setErr(e?.message || "usage unavailable");
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load, refreshKey]);

  if (err || !caps) return null;

  const role = caps.role;
  const isTech = role === "technician";
  const { tech_today, tech_month, tech_daily_cap, tech_monthly_cap } = caps.usage || {};
  const dayPct = tech_daily_cap ? tech_today / tech_daily_cap : 0;
  const monthPct = tech_monthly_cap ? tech_month / tech_monthly_cap : 0;
  const capPct = Math.max(dayPct, monthPct);
  const budgetPct = caps.tenant_pct || 0;

  // Color rules: red at 100% cap or budget exhausted; yellow ≥80% cap or ≥90% budget.
  let bg = colors.surface;
  let fg = colors.onSurface;
  let borderColor = colors.border;
  if (rateLimited || capPct >= 1 || caps.reason === "tenant_budget_exhausted") {
    bg = "#FEE2E2"; fg = "#991B1B"; borderColor = "#FCA5A5";
  } else if (capPct >= 0.8 || caps.budget_warning) {
    bg = "#FEF3C7"; fg = "#92400E"; borderColor = "#FCD34D";
  }

  const chipLabel = isTech
    ? `Zillow: ${tech_today ?? 0}/${tech_daily_cap} today · ${tech_month ?? 0}/${tech_monthly_cap} mo`
    : `Zillow: ${caps.tenant_used ?? 0} / ${caps.tenant_budget} tenant · this month`;

  return (
    <div className="flex flex-col gap-2" data-testid={`${testid}-wrap`}>
      <div
        className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold whitespace-nowrap"
        style={{ backgroundColor: bg, color: fg, border: `1px solid ${borderColor}` }}
        data-testid={testid}
        title={caps.reset_at ? `Resets ${caps.reset_at}` : ""}
      >
        <Info size={12} />
        <span>{chipLabel}</span>
        {caps.budget_warning ? (
          <span className="ml-1" style={{ color: fg, opacity: 0.75 }}>
            · tenant {Math.round(budgetPct * 100)}%
          </span>
        ) : null}
      </div>
      {rateLimited || capPct >= 1 || caps.reason === "tenant_budget_exhausted" ? (
        <div
          className="rounded-lg p-2 text-xs flex items-start gap-2"
          style={{ backgroundColor: "#FEE2E2", color: "#991B1B", border: "1px solid #FCA5A5" }}
          data-testid={`${testid}-banner`}
        >
          <AlertTriangle size={14} className="mt-0.5" />
          <div className="flex-1">
            <div className="font-bold">Zillow lookup limit reached</div>
            <div>
              {caps.reason === "tenant_budget_exhausted"
                ? "Your tenant is out of Zillow budget for the month."
                : caps.reset_at
                ? `Try again after ${caps.reset_at.slice(0, 16).replace("T", " ")}.`
                : "Try again later."}{" "}
              <a
                href="mailto:admin@aquaterra.com?subject=Zillow%20lookup%20limit%20reached&body=I%20hit%20my%20Zillow%20lookup%20cap.%20Please%20increase%20my%20quota%20or%20raise%20the%20tenant%20budget."
                className="underline"
                style={{ color: "#991B1B" }}
                data-testid={`${testid}-ask-admin`}
              >
                Ask admin for more
              </a>
              .
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default ZillowUsageChip;
