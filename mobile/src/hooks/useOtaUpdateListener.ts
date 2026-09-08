/**
 * OTA Auto-Update Listener — background check + subtle "update ready" toast.
 *
 * Behaviour:
 *  1. On every app foreground transition, calls `checkForUpdateAsync()`.
 *  2. If an update is available, fetches it in the background via `fetchUpdateAsync()`.
 *  3. On next natural cold start, the new bundle is applied automatically
 *     (this is the default `expo-updates` behaviour when `checkAutomatically: "ON_LOAD"`).
 *  4. If the user taps "Restart now" on the optional toast, we call
 *     `Updates.reloadAsync()` to apply immediately.
 *  5. We NEVER call `reloadAsync()` automatically mid-session — that would
 *     blow away in-progress offline write queue state and infuriate a tech
 *     mid-route.
 *
 * Mount once inside `_layout.tsx` after `<AuthProvider>` so the user's
 * session context is available.
 */
import { useEffect, useRef, useCallback, useState } from "react";
import { AppState, type AppStateStatus, Alert } from "react-native";
import * as Updates from "expo-updates";

/** Minimum interval between background checks (ms). Avoids hammering
 *  the CDN if the user rapidly foreground-switches. */
const CHECK_COOLDOWN_MS = 5 * 60 * 1000; // 5 minutes

export function useOtaUpdateListener() {
  const lastCheckRef = useRef<number>(0);
  const [updateReady, setUpdateReady] = useState(false);

  const checkAndFetch = useCallback(async () => {
    // Guard: only works in production builds — dev client has no updates infra.
    if (__DEV__) return;
    if (!Updates.isEnabled) return;

    const now = Date.now();
    if (now - lastCheckRef.current < CHECK_COOLDOWN_MS) return;
    lastCheckRef.current = now;

    try {
      const check = await Updates.checkForUpdateAsync();
      if (!check.isAvailable) return;

      // Fetch the update bundle in the background.
      const fetch = await Updates.fetchUpdateAsync();
      if (fetch.isNew) {
        setUpdateReady(true);
        // Show a non-intrusive alert. The tech can choose to restart
        // now or ignore — the update will apply on next cold start.
        Alert.alert(
          "Update available",
          "A new version has been downloaded. Restart to apply?",
          [
            { text: "Later", style: "cancel" },
            {
              text: "Restart now",
              onPress: () => {
                Updates.reloadAsync().catch(() => {});
              },
            },
          ],
          { cancelable: true },
        );
      }
    } catch (e: any) {
      // Silently swallow — OTA check failure must never crash the app.
      // This fires in dev builds, Expo Go, and when the CDN is unreachable.
      console.log("[OTA] Check failed (non-fatal):", e?.message || e);
    }
  }, []);

  // Check on mount (cold start).
  useEffect(() => {
    checkAndFetch();
  }, [checkAndFetch]);

  // Check on foreground transitions.
  useEffect(() => {
    let prev: AppStateStatus = AppState.currentState;
    const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (prev.match(/inactive|background/) && next === "active") {
        checkAndFetch();
      }
      prev = next;
    });
    return () => sub.remove();
  }, [checkAndFetch]);

  return { updateReady };
}
