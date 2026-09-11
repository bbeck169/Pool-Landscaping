/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot page.
 *
 * Current-state 3-tile snapshot at ``/reports/business-snapshot``.
 * Reads ``GET /api/reports/business-snapshot``, renders the three
 * tiles (Service Radius, # of Employees, BH/Week Capacity), and
 * offers a CSV export of the same envelope. No date range — the
 * snapshot is current-state.
 *
 * Loading skeleton, truthful empty-state (null/N/A rendered when
 * the source data doesn't carry a computed value — we never
 * fabricate distances), and an error toast on API failure.
 *
 * Section badge: "Others" per the Phase 5a.1 catalog placement
 * decision (locked A: flat grid + section badge).
 */
import React, { useEffect, useState, useCallback } from "react";
import { api } from "@/api";
import { toast } from "@/hooks/use-toast";
import { colors } from "@/theme";
import { MapPin, Users2, Clock } from "lucide-react";

function _n(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? v.toLocaleString() : String(v);
}

function _tsShort(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function _csv(res) {
  const rows = [
    ["metric", "value", "unit", "computed_at"],
    ["service_radius.max_miles",
     res?.service_radius?.max_miles ?? "",
     "miles", res?.computed_at || ""],
    ["service_radius.avg_last_30d_miles",
     res?.service_radius?.avg_last_30d_miles ?? "",
     "miles", res?.computed_at || ""],
    ["employee_count",
     res?.employee_count ?? "",
     "people", res?.computed_at || ""],
    ["bh_per_week_capacity",
     res?.bh_per_week_capacity ?? "",
     "hours", res?.computed_at || ""],
  ];
  return rows.map((r) => r.map((c) => {
    const s = String(c ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
}

function _download(name, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function BusinessSnapshot() {
  const [state, setState] = useState({ loading: true });

  const load = useCallback(async () => {
    setState({ loading: true });
    try {
      const res = await api.get(`/reports/business-snapshot`);
      setState({ loading: false, data: res });
    } catch (e) {
      const msg = e?.message || "Failed to load Business Snapshot";
      setState({ loading: false, error: msg });
      try {
        toast({
          title: "Business Snapshot failed",
          description: msg,
          variant: "destructive",
        });
      } catch {
        /* toast shim absent in some test envs */
      }
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const d = state.data || {};
  const isLoading = state.loading;
  const isError   = !!state.error;

  return (
    <div
      className="p-4 md:p-8 max-w-6xl mx-auto"
      data-testid="business-snapshot-page"
    >
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1
            className="text-3xl md:text-4xl font-bold"
            style={{ color: colors.onSurface }}
            data-testid="business-snapshot-title"
          >
            Business Snapshot
          </h1>
          <p
            className="text-sm mt-1"
            style={{ color: colors.muted }}
            data-testid="business-snapshot-subtitle"
          >
            Current-state view of your service reach, team size, and
            weekly labor capacity. Values reflect the moment this
            page was loaded.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => _download(
              `business-snapshot-${(d.computed_at || "").slice(0, 10) || "now"}.csv`,
              _csv(d),
            )}
            disabled={isLoading || isError}
            className="px-3 py-2 rounded-md text-sm font-semibold border transition disabled:opacity-50"
            style={{ background: "#FFFFFF", color: colors.onSurface,
                     borderColor: colors.border }}
            data-testid="business-snapshot-csv-btn"
          >
            Export CSV
          </button>
        </div>
      </div>

      {isError ? (
        <div
          className="rounded-xl p-6 text-sm"
          style={{ background: "#FEF2F2", border: "1px solid #FCA5A5",
                   color: "#7F1D1D" }}
          data-testid="business-snapshot-error"
        >
          Failed to load: {state.error}
        </div>
      ) : (
        <>
          <div
            className="grid grid-cols-1 md:grid-cols-3 gap-4"
            data-testid="business-snapshot-tiles"
          >
            <Tile
              icon={MapPin}
              testid="tile-service-radius"
              label="Service Radius"
              primary={isLoading ? "…" : `${_n(d?.service_radius?.max_miles)} mi`}
              secondary={isLoading
                ? " "
                : `Avg last 30d · ${_n(d?.service_radius?.avg_last_30d_miles)} mi`}
            />
            <Tile
              icon={Users2}
              testid="tile-employee-count"
              label="# of Employees"
              primary={isLoading ? "…" : _n(d?.employee_count)}
              secondary="Active technicians"
            />
            <Tile
              icon={Clock}
              testid="tile-bh-per-week"
              label="BH per Week Capacity"
              primary={isLoading ? "…" : _n(d?.bh_per_week_capacity)}
              secondary="Budgeted hours / week (total)"
            />
          </div>
          <p
            className="text-xs mt-6"
            style={{ color: colors.muted }}
            data-testid="business-snapshot-computed-at"
          >
            Computed at: {isLoading ? "…" : _tsShort(d.computed_at)}
          </p>
        </>
      )}
    </div>
  );
}

function Tile({ icon: Icon, testid, label, primary, secondary }) {
  return (
    <div
      className="rounded-2xl p-5 flex flex-col gap-3"
      style={{
        backgroundColor: colors.tile?.solidNavy || "#1B1F5C",
        border: `1px solid ${colors.border || "#E5E7EB"}`,
        color: "#FFFFFF",
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
        >
          <Icon size={20} />
        </div>
        <div className="text-sm font-semibold opacity-90">{label}</div>
      </div>
      <div
        className="text-3xl font-bold"
        data-testid={`${testid}-primary`}
      >
        {primary}
      </div>
      <div
        className="text-xs opacity-80"
        data-testid={`${testid}-secondary`}
      >
        {secondary}
      </div>
    </div>
  );
}
