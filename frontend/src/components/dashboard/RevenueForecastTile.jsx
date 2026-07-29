/**
 * Revenue Forecast tile · Feb-2026.
 *
 * Two-stat card: Booked jobs + Recurring subscriptions.  Combined
 * total is the prominent stat; a small caption underneath breaks down
 * "X booked jobs + Y active subscriptions × N cycles".
 */
import React, { useEffect, useState } from "react";
import { CalendarClock, RefreshCw } from "lucide-react";
import { colors, money } from "@/theme";
import { api } from "@/api";
import { Skeleton } from "@/components/ui-kit";

export default function RevenueForecastTile({ range }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!range?.start || !range?.end) return;
    setData(null);
    setErr("");
    api.get(`/admin/dashboard/revenue-forecast?start=${range.start}&end=${range.end}`)
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load."));
  }, [range?.start, range?.end]);

  const chip = (label, value, colorHex, testid) => (
    <div
      className="rounded-xl px-3 py-2 flex-1"
      style={{ background: colorHex + "12",
                border: `1px solid ${colorHex}30` }}
      data-testid={testid}
    >
      <div className="text-xs uppercase font-bold tracking-wide"
            style={{ color: colorHex }}>{label}</div>
      <div className="text-lg font-bold mt-0.5"
            style={{ color: colors.onSurface }}>{value}</div>
    </div>
  );

  return (
    <div
      className="rounded-2xl p-5"
      style={{ background: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="revenue-forecast-tile"
    >
      <div className="text-xs uppercase font-bold tracking-wide mb-3"
            style={{ color: colors.muted }}>Revenue Forecast</div>

      {err ? (
        <div className="rounded-xl p-3 text-sm"
              style={{ background: "#FEE2E2", color: "#7F1D1D" }}
              data-testid="revenue-forecast-error">{err}</div>
      ) : data === null ? (
        <Skeleton className="h-32 rounded-xl"
                    data-testid="revenue-forecast-loading" />
      ) : (
        <>
          <div className="mb-4">
            <div className="flex items-baseline gap-2">
              <div className="text-3xl font-black"
                    style={{ color: colors.onSurface }}
                    data-testid="revenue-forecast-combined">
                {money(data.combined_total)}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                projected in range
              </div>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 mb-3">
            {chip(
              <span className="inline-flex items-center gap-1">
                <CalendarClock size={11} /> Booked
              </span>,
              money(data.booked.amount),
              "#0891B2",
              "revenue-forecast-booked",
            )}
            {chip(
              <span className="inline-flex items-center gap-1">
                <RefreshCw size={11} /> Recurring
              </span>,
              money(data.recurring.amount),
              "#7C3AED",
              "revenue-forecast-recurring",
            )}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}
                data-testid="revenue-forecast-caption">
            Based on {data.booked.job_count} booked job
            {data.booked.job_count === 1 ? "" : "s"} +{" "}
            {data.recurring.subscription_count} active subscription
            {data.recurring.subscription_count === 1 ? "" : "s"} across{" "}
            {data.recurring.cycle_count} billing cycle
            {data.recurring.cycle_count === 1 ? "" : "s"}.
          </div>
        </>
      )}
    </div>
  );
}
