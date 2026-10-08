/**
 * Feb-2026 · MARCO Proactive Alerts — in-chat panel.
 *
 * Renders INSIDE Marco's chat view (above the message history) as
 * a sticky top strip. Other 8 personas don't render this panel —
 * the caller gates on ``employee?.key === "marco_executive"``.
 *
 * Features:
 *   - Fetches ``GET /ai/marco/alerts`` on mount + on an
 *     ``ai-dock:alerts-refresh`` CustomEvent (fires after any
 *     ack/dismiss elsewhere).
 *   - Each row shows severity icon + title + body + ack / dismiss
 *     buttons.
 *   - Click an entity link navigates to the related record
 *     (invoice detail, job detail).
 *   - Empty state: "No alerts right now."
 *   - Collapse / expand toggle.
 */
import React from "react";
import {
  AlertTriangle, Info, AlertCircle, Check, X, ChevronDown,
  ChevronRight, ExternalLink,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";


const _SEV_ICON = {
  error: AlertCircle,
  warn: AlertTriangle,
  info: Info,
};


function _entityLink(entity_ref) {
  const t = entity_ref?.type;
  const id = entity_ref?.id;
  if (!t || !id) return null;
  if (t === "invoice") return `/quotes/${id}`;
  if (t === "job") return `/jobs/${id}`;
  if (t === "customer") return `/customers/${id}`;
  return null;
}


function _AlertRow({ alert, busyIds, onAck, onDismiss }) {
  const Icon = _SEV_ICON[alert.severity] || Info;
  const link = _entityLink(alert.entity_ref);
  const busy = busyIds.has(alert.id);
  const sevColor = alert.severity === "error" ? colors.danger
                     : alert.severity === "warn" ? (colors.warning || "#f59e0b")
                     : colors.brand;
  const acked = Boolean(alert.acknowledged_at);
  return (
    <div
      className="p-2 rounded-lg text-xs flex items-start gap-2"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
        opacity: acked ? 0.7 : 1,
      }}
      data-testid={`marco-alert-row-${alert.id}`}
      data-severity={alert.severity}
    >
      <Icon size={14} style={{ color: sevColor, flexShrink: 0, marginTop: 2 }} />
      <div className="flex-1 min-w-0">
        <div className="font-semibold" style={{ color: colors.onSurface }}>
          {alert.title}
          {acked ? (
            <span className="ml-1 text-[10px] uppercase"
                   style={{ color: colors.muted }}>
              · acknowledged
            </span>
          ) : null}
        </div>
        <div style={{ color: colors.onSurfaceSecondary, overflowWrap: "anywhere" }}>
          {alert.body}
        </div>
        {link ? (
          <a
            href={link}
            className="inline-flex items-center gap-1 mt-1 text-[11px] underline"
            style={{ color: colors.brand }}
            data-testid={`marco-alert-link-${alert.id}`}
          >
            View <ExternalLink size={10} />
          </a>
        ) : null}
      </div>
      <div className="flex flex-col gap-1" style={{ flexShrink: 0 }}>
        {!acked ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onAck(alert.id)}
            className="rounded px-2 py-1 text-[11px] flex items-center gap-1"
            style={{
              backgroundColor: colors.surfaceMuted,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
              cursor: busy ? "wait" : "pointer",
            }}
            title="Acknowledge"
            data-testid={`marco-alert-ack-${alert.id}`}
          >
            <Check size={10} /> Ack
          </button>
        ) : null}
        <button
          type="button"
          disabled={busy}
          onClick={() => onDismiss(alert.id)}
          className="rounded px-2 py-1 text-[11px] flex items-center gap-1"
          style={{
            backgroundColor: colors.surfaceMuted,
            color: colors.onSurfaceSecondary,
            border: `1px solid ${colors.border}`,
            cursor: busy ? "wait" : "pointer",
          }}
          title="Dismiss"
          data-testid={`marco-alert-dismiss-${alert.id}`}
        >
          <X size={10} /> Dismiss
        </button>
      </div>
    </div>
  );
}


export default function AlertsPanel({ onCountChange }) {
  const [alerts, setAlerts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);
  const [busyIds, setBusyIds] = React.useState(() => new Set());
  const [err, setErr] = React.useState(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get("/ai/marco/alerts?limit=100");
      setAlerts(Array.isArray(rows) ? rows : []);
      setErr(null);
    } catch (e) {
      setErr(e?.message || "failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
    const onBump = () => refresh();
    window.addEventListener("ai-dock:alerts-refresh", onBump);
    return () => window.removeEventListener("ai-dock:alerts-refresh", onBump);
  }, [refresh]);

  React.useEffect(() => {
    if (typeof onCountChange === "function") onCountChange(alerts.length);
  }, [alerts.length, onCountChange]);

  const _mark = (id) => setBusyIds((s) => {
    const n = new Set(s); n.add(id); return n;
  });
  const _unmark = (id) => setBusyIds((s) => {
    const n = new Set(s); n.delete(id); return n;
  });

  const handleAck = async (id) => {
    _mark(id);
    try {
      const updated = await api.post(
        `/ai/marco/alerts/${id}/acknowledge`, {});
      setAlerts((prev) => prev.map((a) =>
        a.id === id ? { ...a, ...updated } : a));
      try {
        window.dispatchEvent(new CustomEvent("ai-dock:alerts-refresh"));
      } catch (_e) { /* best effort */ }
    } catch (e) {
      setErr(e?.message || "ack failed");
    } finally {
      _unmark(id);
    }
  };

  const handleDismiss = async (id) => {
    _mark(id);
    // Optimistic — drop from local list immediately.
    const prior = alerts;
    setAlerts((prev) => prev.filter((a) => a.id !== id));
    try {
      await api.post(`/ai/marco/alerts/${id}/dismiss`, {});
      try {
        window.dispatchEvent(new CustomEvent("ai-dock:alerts-refresh"));
      } catch (_e) { /* best effort */ }
    } catch (e) {
      // Revert.
      setAlerts(prior);
      setErr(e?.message || "dismiss failed");
    } finally {
      _unmark(id);
    }
  };

  const activeCount = alerts.length;

  return (
    <div
      className="border-b"
      style={{ borderColor: colors.border,
                backgroundColor: colors.surfaceMuted }}
      data-testid="marco-alerts-panel"
    >
      <div className="px-3 py-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-1 text-xs font-semibold uppercase"
          style={{ color: colors.onSurfaceSecondary }}
          data-testid="marco-alerts-toggle"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          Alerts
          {activeCount > 0 ? (
            <span
              className="ml-1 inline-flex items-center justify-center rounded-full px-1.5 text-[10px] font-bold"
              style={{ backgroundColor: colors.danger, color: "#fff" }}
            >
              {activeCount}
            </span>
          ) : null}
        </button>
        <button
          type="button"
          onClick={refresh}
          disabled={loading}
          className="text-[11px] underline"
          style={{ color: colors.brand, cursor: loading ? "wait" : "pointer" }}
          data-testid="marco-alerts-refresh"
        >
          {loading ? "…" : "Refresh"}
        </button>
      </div>

      {!collapsed ? (
        <div className="px-3 pb-2 space-y-1">
          {err ? (
            <div className="text-[11px]" style={{ color: colors.danger }}>
              {err}
            </div>
          ) : null}
          {activeCount === 0 && !loading ? (
            <div className="text-xs" style={{ color: colors.muted }}
                 data-testid="marco-alerts-empty">
              No alerts right now.
            </div>
          ) : (
            alerts.map((a) => (
              <_AlertRow
                key={a.id}
                alert={a}
                busyIds={busyIds}
                onAck={handleAck}
                onDismiss={handleDismiss}
              />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
