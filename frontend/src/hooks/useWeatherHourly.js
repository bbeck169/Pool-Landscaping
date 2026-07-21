/**
 * useWeatherHourly — Feb-2026.
 *
 * Deduplicated hook for the 24h hourly forecast. All consumers on
 * the same page (weather widget + rain-flag badges on job cards)
 * share a single in-flight request and a single cached response
 * per ``(lat, lon)``. Refreshes every 5 minutes.
 *
 * The backend already caches responses for 5 minutes at the
 * ``weather_cache`` Mongo TTL, so re-mounts within TTL never
 * re-hit the upstream provider. This hook adds a client-side
 * dedupe on top so a single page render with N job cards + the
 * widget still issues exactly ONE ``/api/weather/hourly`` call.
 */
import React from "react";
import { api } from "@/api";
export { hasRainOnDate, maxRainChanceOnDate } from "./weatherHelpers";

const REFRESH_MS = 5 * 60 * 1000;

// Module-level cache & in-flight promise registry, keyed by
// ``lat,lon``. Wiped on process end / page reload — fine.
const _cache = new Map();      // key -> { data, fetchedAt }
const _inflight = new Map();   // key -> Promise<data | null>
const _subs = new Map();       // key -> Set<setter>

function _key(lat, lon) {
  return `${Number(lat).toFixed(3)},${Number(lon).toFixed(3)}`;
}

async function _fetch(lat, lon) {
  const key = _key(lat, lon);
  const existing = _inflight.get(key);
  if (existing) return existing;
  const p = (async () => {
    try {
      const r = await api.get(`/weather/hourly?lat=${lat}&lon=${lon}&hours=24`);
      if (r?.ok === false) return null;
      return r;
    } catch {
      return null;
    }
  })().then((data) => {
    _cache.set(key, { data, fetchedAt: Date.now() });
    _inflight.delete(key);
    const set = _subs.get(key);
    if (set) set.forEach((s) => s(data));
    return data;
  });
  _inflight.set(key, p);
  return p;
}

export default function useWeatherHourly(lat, lon, { enabled = true } = {}) {
  const key = enabled && lat != null && lon != null ? _key(lat, lon) : null;
  const [data, setData] = React.useState(() => {
    if (!key) return null;
    const hit = _cache.get(key);
    if (hit && Date.now() - hit.fetchedAt < REFRESH_MS) return hit.data;
    return null;
  });

  React.useEffect(() => {
    if (!key) return undefined;
    // Subscribe to future updates for this key.
    if (!_subs.has(key)) _subs.set(key, new Set());
    _subs.get(key).add(setData);

    // Kick a fetch if we don't have a fresh entry.
    const hit = _cache.get(key);
    if (!hit || Date.now() - hit.fetchedAt >= REFRESH_MS) {
      _fetch(lat, lon);
    } else {
      setData(hit.data);
    }

    // Refresh loop + tab-visibility.
    const iv = setInterval(() => _fetch(lat, lon), REFRESH_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") _fetch(lat, lon);
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(iv);
      document.removeEventListener("visibilitychange", onVis);
      _subs.get(key)?.delete(setData);
    };
  }, [key, lat, lon]);

  return data;
}

// ─── Pure helpers ─────────────────────────────────────────────────
// Re-exported at the top of this module from ``./weatherHelpers``
// so JobRainFlag can keep its existing import path unchanged.
