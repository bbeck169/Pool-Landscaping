import React from "react";
import { api } from "@/api";

/**
 * Feb-2026 · Phase P2 — poll live GPS positions for the Dispatch Board.
 *
 * Fetches ``GET /api/gps/live-positions`` every ``intervalMs`` (default
 * 30 s) while the caller is mounted. Automatically stops on unmount.
 * Failures are swallowed (dispatch board should keep working even if
 * the backend is down).
 *
 * Returns::
 *
 *   {
 *     positions: [{ user_id, user_name, lat, lon, staleness_s, ... }],
 *     asOf:      string | null,
 *     loading:   boolean,   // true only on the first fetch
 *     error:     string | null,
 *     refresh:   () => Promise<void>,
 *   }
 *
 * The hook is a no-op (returns empty positions) when ``enabled`` is
 * false — the dispatch board uses this to honor the "Show live techs"
 * toggle without unmounting the hook.
 */
export default function useLiveTechPositions({ enabled = true, intervalMs = 30000 } = {}) {
  const [positions, setPositions] = React.useState([]);
  const [asOf, setAsOf] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const timerRef = React.useRef(null);
  const mountedRef = React.useRef(true);

  const fetchOnce = React.useCallback(async () => {
    if (!enabled) return;
    try {
      const r = await api.get("/gps/live-positions");
      if (!mountedRef.current) return;
      setPositions(Array.isArray(r?.positions) ? r.positions : []);
      setAsOf(r?.as_of || null);
      setError(null);
    } catch (e) {
      if (!mountedRef.current) return;
      setError(e?.message || "failed");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [enabled]);

  React.useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setPositions([]);
      setLoading(false);
      return () => { mountedRef.current = false; };
    }
    setLoading(true);
    fetchOnce();
    timerRef.current = setInterval(fetchOnce, Math.max(5000, intervalMs));
    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, intervalMs, fetchOnce]);

  return { positions, asOf, loading, error, refresh: fetchOnce };
}
