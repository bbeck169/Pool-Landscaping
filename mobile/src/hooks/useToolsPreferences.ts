/**
 * Phase 42 · Tools Hub — per-user preferences (pins + recents).
 *
 * Persisted in AsyncStorage under a per-user scope so switching accounts
 * on a shared device doesn't leak one person's favorites into another's
 * view. Honest fallback: if AsyncStorage errors (rare, usually storage
 * full on a very cheap Android), we return empty arrays rather than
 * crashing — the tools hub stays functional, just without personalization.
 *
 * Contract:
 *   pins:    stable array of tile slugs, capped at MAX_PINS.
 *   recents: FIFO capped array of `{slug, at}` timestamps; markUsed()
 *            promotes an existing slug to the front rather than adding
 *            duplicates.
 */
import { useCallback, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

const MAX_PINS = 6;
const MAX_RECENTS = 5;

export type ToolRecent = { slug: string; at: string };

function scope(userId: string | undefined, key: string): string {
  // Empty scope for anonymous / not-yet-loaded auth — still functional but
  // that data won't survive login/logout cycles. `unknown` is stable so
  // the same-anonymous-session pins persist across mounts.
  const u = userId || "unknown";
  return `${key}::${u}`;
}

async function readJSON<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch { return fallback; }
}

async function writeJSON<T>(key: string, value: T): Promise<void> {
  try { await AsyncStorage.setItem(key, JSON.stringify(value)); }
  catch { /* storage full — best effort */ }
}

export function useToolsPreferences(userId: string | undefined) {
  const [pins, setPins] = useState<string[]>([]);
  const [recents, setRecents] = useState<ToolRecent[]>([]);
  const [loaded, setLoaded] = useState(false);

  const pinsKey = scope(userId, "tools-pins-v1");
  const recentsKey = scope(userId, "tools-recents-v1");

  // Load on mount / when the user changes.
  useEffect(() => {
    let alive = true;
    (async () => {
      const [p, r] = await Promise.all([
        readJSON<string[]>(pinsKey, []),
        readJSON<ToolRecent[]>(recentsKey, []),
      ]);
      if (!alive) return;
      setPins(Array.isArray(p) ? p.slice(0, MAX_PINS) : []);
      setRecents(Array.isArray(r) ? r.slice(0, MAX_RECENTS) : []);
      setLoaded(true);
    })();
    return () => { alive = false; };
  }, [pinsKey, recentsKey]);

  const togglePin = useCallback((slug: string) => {
    setPins((prev) => {
      const next = prev.includes(slug)
        ? prev.filter((s) => s !== slug)
        : [...prev, slug].slice(0, MAX_PINS);
      writeJSON(pinsKey, next);
      return next;
    });
  }, [pinsKey]);

  const markUsed = useCallback((slug: string) => {
    setRecents((prev) => {
      const now = new Date().toISOString();
      const dedup = prev.filter((r) => r.slug !== slug);
      const next = [{ slug, at: now }, ...dedup].slice(0, MAX_RECENTS);
      writeJSON(recentsKey, next);
      return next;
    });
  }, [recentsKey]);

  return { pins, recents, togglePin, markUsed, loaded, MAX_PINS, MAX_RECENTS };
}
