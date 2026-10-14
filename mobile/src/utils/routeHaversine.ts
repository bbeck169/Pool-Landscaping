/**
 * Route header math — mobile port of the pure helpers in
 * `frontend/src/pages/schedule/ReorderRouteModal.jsx` (web e5d6fa01e).
 * Byte-for-byte semantics: same Earth radius, coord fallbacks,
 * 35 km/h duration estimate, and trivial / short / long buckets.
 */
const EARTH_M = 6371008.8;

export function haversineMeters(aLat?: number | null, aLng?: number | null, bLat?: number | null, bLng?: number | null): number {
  if (aLat == null || aLng == null || bLat == null || bLng == null) return 0;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLng = toRad(bLng - aLng);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(s)));
}

function jobCoord(j: any): [number, number] | null {
  const lat = j?.location_lat ?? j?.site_lat ?? j?.lat ?? j?.latitude;
  const lng = j?.location_lng ?? j?.site_lng ?? j?.lng ?? j?.longitude;
  return lat != null && lng != null ? [Number(lat), Number(lng)] : null;
}

/** Sum of leg distances; coord-less stops are skipped (chain continues). */
export function totalHaversineMeters(orderedJobs: any[]): number {
  if (!Array.isArray(orderedJobs) || orderedJobs.length < 2) return 0;
  let total = 0;
  let prev: [number, number] | null = null;
  for (const j of orderedJobs) {
    const c = jobCoord(j);
    if (c && prev) total += haversineMeters(prev[0], prev[1], c[0], c[1]);
    if (c) prev = c;
  }
  return total;
}

/** trivial < 5 mi · short 5–20 mi · long > 20 mi. */
export function classifyMiles(miles: number): "trivial" | "short" | "long" {
  if (miles < 5) return "trivial";
  if (miles <= 20) return "short";
  return "long";
}

/** ~35 km/h neighborhood driving (matches backend `_estimate_duration_s`). */
export function durationSecondsFromMeters(m: number): number {
  if (m <= 0) return 0;
  return Math.round(m / ((35 * 1000) / 3600));
}

export function formatRouteHeader(meters: number, overrideSeconds?: number | null): string {
  const miles = meters / 1609.344;
  const secs = overrideSeconds != null ? overrideSeconds : durationSecondsFromMeters(meters);
  const h = Math.floor(secs / 3600);
  const m = Math.round((secs % 3600) / 60);
  return `Estimated ~${h}h ${m}m · ${miles.toFixed(1)}mi · ${classifyMiles(miles)}`;
}
