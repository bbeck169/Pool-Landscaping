/**
 * Phase K39b · Feb-2026 — Mobile maps provider resolver.
 *
 * Resolves ``EXPO_PUBLIC_MAPS_PROVIDER`` (default "google") to the
 * active adapter. If ``here`` is requested but the credentials env
 * (``EXPO_PUBLIC_HERE_ACCESS_KEY_ID``) is empty, we log a single
 * warning and fall back to Google — same shape as the K39a web
 * resolver so the two stacks stay predictable.
 */
import { useMemo } from "react";

let _warned = false;

export function _computeProvider(env: NodeJS.ProcessEnv = process.env): "google" | "here" {
  const raw = (env.EXPO_PUBLIC_MAPS_PROVIDER || "google").toLowerCase();
  const wanted = raw === "here" ? "here" : "google";
  const hereKeyId = env.EXPO_PUBLIC_HERE_ACCESS_KEY_ID || "";
  if (wanted === "here" && !hereKeyId) {
    if (!_warned) {
      // eslint-disable-next-line no-console
      console.warn(
        "[maps] EXPO_PUBLIC_MAPS_PROVIDER=here but " +
          "EXPO_PUBLIC_HERE_ACCESS_KEY_ID is empty — falling back to " +
          "the Google adapter (react-native-maps).",
      );
      _warned = true;
    }
    return "google";
  }
  return wanted;
}

/**
 * Stable across a session — env vars are baked at build time on
 * Expo/EAS so we memoize the value.
 */
const _CACHED: "google" | "here" = _computeProvider();

export function useMapsProvider(): "google" | "here" {
  return useMemo(() => _CACHED, []);
}
