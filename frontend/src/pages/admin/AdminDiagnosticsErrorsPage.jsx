import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { AlertTriangle, RefreshCw } from "lucide-react";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Feb-2026 · Admin Diagnostics — Client-side errors log.
 *
 * Simple table view of the newest 100 errors recorded by the frontend
 * Error Boundary via ``POST /api/client-errors``. Admin+ / super_admin
 * only — the backend enforces the same gate, this page just presents.
 */
export default function AdminDiagnosticsErrorsPage() {
  const [rows, setRows] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [componentFilter, setComponentFilter] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const q = componentFilter
        ? `?component=${encodeURIComponent(componentFilter)}`
        : "";
      const r = await api.get(`/admin/client-errors${q}`);
      setRows(r?.errors || []);
    } catch (e) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [componentFilter]);

  React.useEffect(() => { load(); }, [load]);

  return (
    <SafeScrollContainer
      className="px-4 md:px-8 pt-6 space-y-4"
      data-testid="admin-diagnostics-errors-page"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1
            className="text-2xl font-semibold"
            style={{ color: colors.onSurface }}
            data-testid="admin-diagnostics-errors-title"
          >
            Client-side errors
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Errors captured by the frontend Error Boundary. Newest first.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-diagnostics-errors-refresh"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="flex items-center gap-2">
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>
          Component
        </label>
        <input
          value={componentFilter}
          onChange={(e) => setComponentFilter(e.target.value)}
          placeholder="e.g. DispatchBoard"
          className="h-9 px-3 rounded-lg text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
            minWidth: 180,
          }}
          data-testid="admin-diagnostics-errors-filter"
        />
      </div>

      {loading ? (
        <div
          className="text-sm py-6 text-center"
          style={{ color: colors.muted }}
          data-testid="admin-diagnostics-errors-loading"
        >
          Loading…
        </div>
      ) : error ? (
        <div
          className="rounded-lg px-3 py-3 text-sm flex items-center gap-2"
          style={{
            backgroundColor: "#FEE2E2",
            color: "#7F1D1D",
            border: `1px solid #FCA5A5`,
          }}
          data-testid="admin-diagnostics-errors-error"
        >
          <AlertTriangle size={16} /> {error}
        </div>
      ) : rows.length === 0 ? (
        <div
          className="rounded-lg px-4 py-6 text-sm text-center"
          style={{
            backgroundColor: colors.surface,
            color: colors.muted,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-diagnostics-errors-empty"
        >
          No client-side errors recorded.
        </div>
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="admin-diagnostics-errors-table"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ backgroundColor: colors.surfaceSecondary }}>
                  <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>When</th>
                  <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Component</th>
                  <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Message</th>
                  <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>User</th>
                  <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>UA</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`admin-diagnostics-errors-row-${r.id}`}
                  >
                    <td className="px-3 py-2 whitespace-nowrap" style={{ color: colors.onSurface }}>
                      {(r.created_at || "").slice(0, 19).replace("T", " ")}
                    </td>
                    <td className="px-3 py-2" style={{ color: colors.onSurface }}>
                      {r.component || "—"}
                    </td>
                    <td className="px-3 py-2" style={{ color: colors.onSurface, maxWidth: 480 }}>
                      <div className="font-mono text-xs" style={{ wordBreak: "break-word" }}>
                        {r.message}
                      </div>
                      {r.url ? (
                        <div className="text-[11px] mt-1 truncate" style={{ color: colors.muted }}>
                          {r.url}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs whitespace-nowrap" style={{ color: colors.muted }}>
                      {r.user_email || "anonymous"}
                    </td>
                    <td className="px-3 py-2 text-[11px]" style={{ color: colors.muted, maxWidth: 220 }}>
                      <div className="truncate">{r.user_agent || "—"}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </SafeScrollContainer>
  );
}
