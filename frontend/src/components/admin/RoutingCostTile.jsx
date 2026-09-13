/**
 * RoutingCostTile · Feb-2026 · UX Polish Batch B
 *
 * Small admin-dashboard widget that surfaces per-tenant Google
 * Routes API v2 telemetry recorded by the traffic-aware routing
 * feature. Reads ``GET /api/reports/routing-cost-telemetry`` and
 * renders a compact tile with a window selector (7d / 30d / 90d).
 *
 * See /app/memory/FEATURE_SEND_TO_CUSTOMER_AND_COST_TELEMETRY.md § 2.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Route as RouteIcon } from "lucide-react";


const _WINDOWS = [7, 30, 90];


export default function RoutingCostTile() {
  const [windowDays, setWindowDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.get(`/reports/routing-cost-telemetry?window_days=${windowDays}`)
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setErr(e?.message || "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [windowDays]);

  const empty = !loading && !err && data && (data.total_calls || 0) === 0;
  const money = (n) => `$${(Number(n) || 0).toFixed(2)}`;

  return (
    <div
      className="bg-white rounded-lg border p-4"
      style={{ borderColor: colors.border }}
      data-testid="routing-cost-tile"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <RouteIcon size={16} style={{ color: colors.brand }} />
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Routing Cost
          </div>
        </div>
        <select
          value={windowDays}
          onChange={(e) => setWindowDays(Number(e.target.value))}
          className="text-xs border rounded px-1 py-0.5"
          data-testid="routing-cost-window-select"
        >
          {_WINDOWS.map((w) => (
            <option key={w} value={w}>{w}d</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="routing-cost-loading">Loading…</div>
      ) : err ? (
        <div className="text-xs text-red-600" data-testid="routing-cost-error">
          {String(err)}
        </div>
      ) : empty ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="routing-cost-empty">
          No routing telemetry recorded yet.
        </div>
      ) : (
        <div className="space-y-1.5 text-sm">
          <div className="flex justify-between"
               data-testid="routing-cost-aware-row">
            <span style={{ color: colors.muted }}>Traffic-aware calls</span>
            <span className="font-medium">{data.traffic_aware_calls}</span>
          </div>
          <div className="flex justify-between"
               data-testid="routing-cost-baseline-row">
            <span style={{ color: colors.muted }}>Baseline calls</span>
            <span className="font-medium">{data.traffic_unaware_calls}</span>
          </div>
          <div className="flex justify-between border-t pt-1.5 mt-1.5"
               style={{ borderColor: colors.border }}
               data-testid="routing-cost-extra-row"
               title="Estimated additional cost from traffic-aware SKU (~2x base tier).">
            <span style={{ color: colors.muted }}>Est. extra cost</span>
            <span className="font-semibold">{money(data.est_traffic_aware_cost_usd)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
