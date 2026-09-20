/**
 * G2 · Messages tab unread badge hook.
 *
 * Fetches `GET /api/messages/unread-count` on mount, every 60s, and
 * whenever the app comes back to the foreground. Returns a formatted
 * badge value for React Navigation's `tabBarBadge` prop:
 *   - `undefined` when count is 0 or unknown (hides badge)
 *   - numeric value 1–99
 *   - string `"99+"` when count exceeds 99
 *
 * All fetch errors are silently swallowed (console.warn for dev
 * diagnostics) — the tab bar must never crash.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { AppState, AppStateStatus } from "react-native";
import { api } from "@/src/api";

const POLL_INTERVAL_MS = 60_000;

type BadgeValue = number | string | undefined;

function formatBadge(count: number): BadgeValue {
  if (count <= 0) return undefined;
  if (count > 99) return "99+";
  return count;
}

export function useUnreadCount(enabled: boolean): BadgeValue {
  const [badge, setBadge] = useState<BadgeValue>(undefined);
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchCount = useCallback(async () => {
    if (!enabled) return;
    try {
      const data = await api.get("/messages/unread-count");
      if (!mountedRef.current) return;
      const count = typeof data?.unread_count === "number" ? data.unread_count : 0;
      setBadge(formatBadge(count));
    } catch (e: any) {
      // Silently skip — never crash the tab bar.
      // Log for dev diagnostics only.
      console.warn("[useUnreadCount] fetch failed:", e?.message || e);
    }
  }, [enabled]);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      setBadge(undefined);
      return;
    }

    // Initial fetch
    fetchCount();

    // Poll every 60s
    intervalRef.current = setInterval(fetchCount, POLL_INTERVAL_MS);

    // Refetch on app foreground
    const handleAppState = (state: AppStateStatus) => {
      if (state === "active") fetchCount();
    };
    const sub = AppState.addEventListener("change", handleAppState);

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      sub.remove();
    };
  }, [enabled, fetchCount]);

  return badge;
}
