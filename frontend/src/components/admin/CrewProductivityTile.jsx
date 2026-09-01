/**
 * Phase H5 · Feb-2026 — Crew Productivity Dashboard Tile.
 *
 * Weekly / monthly revenue-per-crew rollup. Uses the H5 endpoint
 * ``GET /api/admin/crew-productivity?range=this_week|last_week|this_month``
 * which attributes jobs via the F6a semantic (crew_id OR
 * technician_id ∈ crew.tech_ids). Rows are sorted server-side by
 * revenue DESC.
 *
 * No auto-poll (per H5 brief non-goals) — this is a report, not a
 * real-time queue. Refetches on range change.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Users, RefreshCw, ArrowRight, TrendingUp } from "lucide-react";

import { api } from "../../api";
import { colors } from "../../theme";

const RANGE_OPTIONS = [
  { value: "this_week", label: "This Week" },
  { value: "last_week", label: "Last Week" },
  { value: "this_month", label: "This Month" },
];

const RANGE_LABEL = {
  this_week: "This Week",
  last_week: "Last Week",
  this_month: "This Month",
};

function _fmtUsd(n) {
  const v = Number(n || 0);
  return v.toLocaleString(undefined, {
    style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}


function LoadingSkeleton() {
  return (
    <div
      className="space-y-2"
      data-testid="crew-productivity-tile-skeleton"
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-9 rounded-lg animate-pulse"
          style={{ background: colors.surfaceSecondary }}
        />
      ))}
    </div>
  );
}


function EmptyState({ rangeLabel }) {
  return (
    <div
      className="rounded-lg p-6 text-center text-sm"
      style={{
        background: colors.surfaceSecondary,
        color: colors.muted,
        border: `1px dashed ${colors.border}`,
      }}
      data-testid="crew-productivity-tile-empty"
    >
      No completed jobs for any crew {rangeLabel.toLowerCase()}.
    </div>
  );
}


export default function CrewProductivityTile() {
  const [range, setRange] = useState("this_week");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (r) => {
    setLoading(true);
    setErr("");
    try {
      const res = await api.get(
        `/admin/crew-productivity?range=${encodeURIComponent(r)}`,
      );
      setData(res || null);
    } catch (e) {
      setErr(e?.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(range);
  }, [range, load]);

  // ``rows`` is a filtered view — crews with zero revenue AND zero
  // jobs are demoted below the table so operators focus on the
  // productive crews first. They are still counted in totals via the
  // server response.
  const activeCrews = useMemo(
    () => (data?.crews || []).filter(
      (c) => (c.jobs_completed || 0) > 0 || (c.revenue_subtotal || 0) > 0,
    ),
    [data],
  );

  const totalJobs = data?.totals?.jobs_completed || 0;
  const totalRev = data?.totals?.revenue_subtotal || 0;

  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="crew-productivity-tile"
    >
      <header className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} style={{ color: colors.brand }} />
          <h3
            className="text-sm font-bold"
            style={{ color: colors.onSurface }}
            data-testid="crew-productivity-tile-title"
          >
            Crew Productivity ({RANGE_LABEL[range]})
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => setRange(e.target.value)}
            className="text-xs font-semibold px-2 py-1 rounded-md"
            style={{
              background: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="crew-productivity-tile-range"
          >
            {RANGE_OPTIONS.map((o) => (
              <option
                key={o.value}
                value={o.value}
                data-testid={`crew-productivity-range-option-${o.value}`}
              >
                {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => load(range)}
            aria-label="Refresh"
            className="p-1 rounded-md"
            style={{ color: colors.muted, background: "transparent" }}
            data-testid="crew-productivity-tile-refresh"
          >
            <RefreshCw size={12} style={{ opacity: loading ? 0.4 : 1 }} />
          </button>
        </div>
      </header>

      {err ? (
        <div
          className="p-3 text-sm rounded-lg"
          style={{
            background: "#FEE2E2",
            color: colors.error,
            border: "1px solid #FCA5A5",
          }}
          data-testid="crew-productivity-tile-error"
        >
          {err}
        </div>
      ) : null}

      {loading && !data ? <LoadingSkeleton /> : null}

      {!loading && !err && activeCrews.length === 0 ? (
        <EmptyState rangeLabel={RANGE_LABEL[range]} />
      ) : null}

      {activeCrews.length > 0 ? (
        <>
          <table
            className="w-full text-sm"
            data-testid="crew-productivity-tile-table"
          >
            <thead>
              <tr
                className="text-[10px] font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}
              >
                <th className="text-left py-2">Crew</th>
                <th className="text-right py-2">Members</th>
                <th className="text-right py-2">Jobs Done</th>
                <th className="text-right py-2">Revenue</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody data-testid="crew-productivity-tile-tbody">
              {activeCrews.map((c) => (
                <tr
                  key={c.crew_id}
                  className="border-t"
                  style={{ borderColor: colors.border }}
                  data-testid={`crew-productivity-row-${c.crew_id}`}
                >
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block w-2.5 h-2.5 rounded-full"
                        style={{ background: c.color || "#0284C7" }}
                      />
                      <span
                        className="font-semibold"
                        style={{ color: colors.onSurface }}
                      >
                        {c.crew_name}
                      </span>
                    </div>
                  </td>
                  <td className="text-right py-2 tabular-nums"
                      style={{ color: colors.muted }}>
                    <span className="inline-flex items-center gap-1 justify-end">
                      <Users size={11} />
                      {c.member_count ?? 0}
                    </span>
                  </td>
                  <td className="text-right py-2 tabular-nums"
                      style={{ color: colors.onSurface }}
                      data-testid={`crew-productivity-row-${c.crew_id}-jobs`}>
                    {c.jobs_completed ?? 0}
                  </td>
                  <td className="text-right py-2 tabular-nums font-semibold"
                      style={{ color: colors.onSurface }}
                      data-testid={`crew-productivity-row-${c.crew_id}-revenue`}>
                    {_fmtUsd(c.revenue_subtotal)}
                  </td>
                  <td className="text-right py-2">
                    <Link
                      to={`/schedule?crew=${encodeURIComponent(c.crew_id)}`}
                      className="inline-flex items-center gap-1 text-xs font-semibold"
                      style={{ color: colors.brand }}
                      data-testid={`crew-productivity-row-${c.crew_id}-schedule`}
                    >
                      Schedule <ArrowRight size={11} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr
                className="border-t"
                style={{
                  borderColor: colors.border,
                  color: colors.onSurface,
                }}
                data-testid="crew-productivity-tile-totals"
              >
                <td className="py-2 text-[10px] font-bold uppercase tracking-wider"
                    style={{ color: colors.muted }}>
                  Totals
                </td>
                <td />
                <td
                  className="text-right py-2 tabular-nums font-bold"
                  data-testid="crew-productivity-tile-totals-jobs"
                >
                  {totalJobs}
                </td>
                <td
                  className="text-right py-2 tabular-nums font-bold"
                  data-testid="crew-productivity-tile-totals-revenue"
                >
                  {_fmtUsd(totalRev)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </>
      ) : null}
    </section>
  );
}
