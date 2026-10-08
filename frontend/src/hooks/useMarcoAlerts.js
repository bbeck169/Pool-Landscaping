/**
 * Feb-2026 · MARCO Proactive Alerts — polling hook.
 *
 * Fetches ``GET /ai/marco/alerts/count`` on an interval and exposes
 * ``{ total, bySeverity, byKind, loading, refresh }``. Only polls
 * when the current user has the admin+ role (admin / super_admin /
 * manager / owner — same role gate as the backend endpoint). Pauses
 * polling while the document is hidden to save background work.
 *
 * Props:
 *   enabled   — defaults to true; opts out when false
 *   intervalMs — poll cadence, defaults to 30 000 ms
 */
import React from "react";
import { api } from "@/api";

const _MARCO_ALERT_ROLES = new Set(
  ["admin", "super_admin", "manager", "owner"],
);

const DEFAULT_INTERVAL_MS = 30_000;

export default function useMarcoAlerts({
  user,
  enabled = true,
  intervalMs = DEFAULT_INTERVAL_MS,
} = {}) {
  const role = (user?.role || "").toLowerCase();
  const supported = _MARCO_ALERT_ROLES.has(role);
  const [count, setCount] = React.useState(0);
  const [unacked, setUnacked] = React.useState(0);
  const [bySeverity, setBySeverity] = React.useState({
    info: 0, warn: 0, error: 0,
  });
  const [byKind, setByKind] = React.useState({});
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  const refresh = React.useCallback(async () => {
    if (!supported || !enabled) return;
    setLoading(true);
    try {
      const r = await api.get("/ai/marco/alerts/count");
      setCount(r?.total ?? 0);
      setUnacked(r?.unacknowledged ?? 0);
      setBySeverity(r?.by_severity || { info: 0, warn: 0, error: 0 });
      setByKind(r?.by_kind || {});
      setError(null);
    } catch (e) {
      setError(e?.message || "failed to fetch alerts");
    } finally {
      setLoading(false);
    }
  }, [supported, enabled]);

  React.useEffect(() => {
    if (!supported || !enabled) return undefined;
    let active = true;
    let timer = null;

    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      if (!active) return;
      await refresh();
    };

    const schedule = () => {
      timer = setInterval(() => { tick(); }, intervalMs);
    };

    // First tick immediate — fills the badge on mount.
    tick();
    schedule();

    const onVis = () => {
      if (document.visibilityState === "visible" && active) {
        // Catch-up refresh when tab returns to foreground.
        tick();
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      active = false;
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [supported, enabled, intervalMs, refresh]);

  return {
    supported,
    count,
    unacknowledged: unacked,
    bySeverity,
    byKind,
    loading,
    error,
    refresh,
  };
}
