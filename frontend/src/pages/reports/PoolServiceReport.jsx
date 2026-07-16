/**
 * Phase 46.4 — Pool Service Report (Admin).
 *
 * Table view of per-tech pools serviced / skipped for a chosen week.
 * Wires to `GET /api/reports/pool-service?week_start=YYYY-MM-DD`.
 * Admin + super_admin only (backend also enforces).
 * CSV export runs client-side against the fetched rows so it always
 * matches what the admin is looking at.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Waves, Download, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function mondayOf(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = d.getDay(); // 0=Sun, 1=Mon…
  const diff = (day + 6) % 7; // days since Monday
  d.setDate(d.getDate() - diff);
  return d.toISOString().slice(0, 10);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function toCsv(rows) {
  const header = ["Tech Name", "Pools Serviced", "Skipped", "Total Assigned"];
  const body = rows.map((r) => [
    r.tech_name,
    r.pools_serviced,
    r.skipped,
    (r.pools_serviced || 0) + (r.skipped || 0),
  ]);
  return [header, ...body]
    .map((line) => line.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

export default function PoolServiceReport() {
  const [week, setWeek] = useState(() => mondayOf(todayIso()));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sortKey, setSortKey] = useState("pools_serviced");
  const [sortDir, setSortDir] = useState("desc");

  const load = async (ws) => {
    setLoading(true);
    setError(null);
    try {
      // Existing backend endpoint (jobs.py) expects `date_from` + `date_to`
      // and returns `{rows: [{technician_id, technician_name, completed, skipped}], total_completed, total_skipped}`.
      const start = new Date(ws + "T00:00:00");
      const end = new Date(start);
      end.setDate(end.getDate() + 6);
      const df = start.toISOString().slice(0, 10);
      const dt = end.toISOString().slice(0, 10);
      const res = await api.get(`/reports/pool-service?date_from=${df}&date_to=${dt}`);
      setData({
        week_start: res.week_start || df,
        week_end: res.week_end || dt,
        rows: (res.rows || []).map((r) => ({
          tech_id: r.technician_id,
          tech_name: r.technician_name,
          pools_serviced: r.completed || 0,
          skipped: r.skipped || 0,
        })),
      });
    } catch (e) {
      setError(e.message || "Failed to load");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(week);
  }, [week]);

  const rows = useMemo(() => {
    const src = data?.rows || [];
    const withTotals = src.map((r) => ({
      ...r,
      total: (r.pools_serviced || 0) + (r.skipped || 0),
    }));
    const sorted = [...withTotals].sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      if (typeof av === "string") {
        return sortDir === "asc"
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av));
      }
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return sorted;
  }, [data, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "tech_name" ? "asc" : "desc");
    }
  };

  const downloadCsv = () => {
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pool-service-report_${data?.week_start || week}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const SortIcon = ({ col }) => {
    if (sortKey !== col) return null;
    return sortDir === "asc"
      ? <ChevronUp size={12} style={{ display: "inline", verticalAlign: "middle" }} />
      : <ChevronDown size={12} style={{ display: "inline", verticalAlign: "middle" }} />;
  };

  const totals = useMemo(() => {
    return rows.reduce(
      (acc, r) => {
        acc.pools_serviced += r.pools_serviced || 0;
        acc.skipped += r.skipped || 0;
        return acc;
      },
      { pools_serviced: 0, skipped: 0 },
    );
  }, [rows]);

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="pool-service-report">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-xl flex items-center justify-center"
            style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
          >
            <Waves size={20} />
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              Pool Service Report
            </h1>
            <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
              Per-tech counts of pools serviced vs skipped for the selected week.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs font-semibold" style={{ color: colors.muted }}>
            Week starting
          </label>
          <input
            type="date"
            value={week}
            onChange={(e) => setWeek(mondayOf(e.target.value))}
            className="text-sm px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="pool-service-week-picker"
          />
          <button
            type="button"
            onClick={() => load(week)}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
            style={{ border: `1px solid ${colors.border}`, color: colors.onSurface, background: colors.surface }}
            data-testid="pool-service-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          <button
            type="button"
            onClick={downloadCsv}
            disabled={!rows.length}
            className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1.5 rounded-md"
            style={{
              background: rows.length ? colors.brand : colors.surfaceSecondary,
              color: rows.length ? "#fff" : colors.muted,
              border: `1px solid ${rows.length ? colors.brand : colors.border}`,
            }}
            data-testid="pool-service-csv"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {loading ? (
        <div className="rounded-2xl p-8 text-center text-sm" style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          Loading pool service data…
        </div>
      ) : error ? (
        <div className="rounded-2xl p-4 text-sm" style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }} data-testid="pool-service-error">
          {error}
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden" style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="px-4 py-3 text-xs font-semibold flex justify-between" style={{ background: colors.surfaceSecondary, color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
            <span>
              Week: {data?.week_start} → {data?.week_end}
            </span>
            <span data-testid="pool-service-totals">
              {totals.pools_serviced} serviced · {totals.skipped} skipped
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="pool-service-table">
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.border}` }}>
                  <th
                    className="text-left px-4 py-2.5 cursor-pointer select-none"
                    style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}
                    onClick={() => toggleSort("tech_name")}
                    data-testid="pool-service-sort-tech"
                  >
                    Tech Name <SortIcon col="tech_name" />
                  </th>
                  <th
                    className="text-right px-4 py-2.5 cursor-pointer select-none"
                    style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}
                    onClick={() => toggleSort("pools_serviced")}
                    data-testid="pool-service-sort-serviced"
                  >
                    Pools Serviced <SortIcon col="pools_serviced" />
                  </th>
                  <th
                    className="text-right px-4 py-2.5 cursor-pointer select-none"
                    style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}
                    onClick={() => toggleSort("skipped")}
                    data-testid="pool-service-sort-skipped"
                  >
                    Skipped <SortIcon col="skipped" />
                  </th>
                  <th
                    className="text-right px-4 py-2.5 cursor-pointer select-none"
                    style={{ color: colors.muted, fontWeight: 600, fontSize: 11, textTransform: "uppercase" }}
                    onClick={() => toggleSort("total")}
                    data-testid="pool-service-sort-total"
                  >
                    Total Assigned <SortIcon col="total" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-sm" style={{ color: colors.muted }} data-testid="pool-service-empty">
                      No pool jobs found for this week.
                    </td>
                  </tr>
                ) : (
                  rows.map((r) => (
                    <tr key={r.tech_id} data-testid={`pool-service-row-${r.tech_id}`} style={{ borderBottom: `1px solid ${colors.border}` }}>
                      <td className="px-4 py-2.5 font-semibold" style={{ color: colors.onSurface }}>
                        {r.tech_name}
                      </td>
                      <td className="px-4 py-2.5 text-right" style={{ color: colors.onSurface }}>
                        {r.pools_serviced}
                      </td>
                      <td className="px-4 py-2.5 text-right" style={{ color: r.skipped > 0 ? "#B45309" : colors.onSurface }}>
                        {r.skipped}
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold" style={{ color: colors.onSurface }}>
                        {r.total}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
