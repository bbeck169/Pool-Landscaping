/**
 * K58 · Feb-2026 — shared mobile helper for resolving a job's map coords.
 *
 * Ladder (highest priority first — first hit wins):
 *   1. job.location_lat / job.location_lng   — /api/jobs canonical alias.
 *                                              After K58 Slice A this is
 *                                              populated from the resolver
 *                                              ladder on the backend, so
 *                                              this rung normally wins.
 *   2. job.latitude / job.longitude          — dual-key output from K58
 *                                              Slice A.  Belt-and-braces
 *                                              in case a future consumer
 *                                              drops the `location_*`
 *                                              alias.
 *   3. job.site_lat / job.site_lng           — legacy write-path emitted
 *                                              directly by the geocoding
 *                                              service.  Only reachable
 *                                              if the backend
 *                                              serializer drift ever
 *                                              re-appears — the mobile
 *                                              helper is defense-in-
 *                                              depth.
 *   4. job.property?.location?.{lat,lng}     — legacy nested shape.  No
 *                                              jobs in the current
 *                                              tenant populate this,
 *                                              but preserved for cross-
 *                                              tenant safety.
 *
 * Ancillary defensive tolerances (carried over from the pre-K58
 * ``resolveJobCoords`` in ``DailyRouteMap.native.tsx``):
 *   - Non-finite / NaN values are treated as absent.
 *   - The ``(0, 0)`` "null island" coord pair is treated as absent
 *     (upstream geocoders occasionally emit it as a "no result" marker
 *     and it must not be rendered as an Atlantic-Ocean pin).
 *   - String coord values that ``Number()`` can parse are accepted
 *     (e.g. legacy DB rows that stored coords as strings).
 *
 * Consumers:
 *   - mobile/src/components/schedule/ScheduleMap.native.tsx
 *   - mobile/src/components/schedule/DailyRouteMap.native.tsx
 *
 * See /app/memory/PHASE_K58_MAP_COORD_LADDER.md for the full ship story.
 */

export type JobLikeForCoords = {
  location_lat?: number | string | null;
  location_lng?: number | string | null;
  latitude?: number | string | null;
  longitude?: number | string | null;
  site_lat?: number | string | null;
  site_lng?: number | string | null;
  property?: {
    location?: {
      lat?: number | string | null;
      lng?: number | string | null;
      lon?: number | string | null;
    } | null;
  } | null;
  // Ancillary legacy shapes preserved for pre-K58 consumers.  Not part
  // of the K58 ladder but kept so callers that used to depend on the
  // richer ``resolveJobCoords`` don't regress.
  location?: { lat?: any; lng?: any; lon?: any } | null;
  service_address?: {
    coordinates?: {
      lat?: any; lng?: any; lon?: any;
      latitude?: any; longitude?: any;
    } | null;
  } | null;
};

export type JobCoords = { lat: number; lng: number } | null;

/**
 * ``resolveJobCoords`` — mobile-side coord resolver ladder.  Returns the
 * first valid { lat, lng } pair found, or ``null`` when no rung yields
 * a usable coord.
 */
export function resolveJobCoords(job: JobLikeForCoords | null | undefined): JobCoords {
  if (!job) return null;
  const trySet = (rawLat: unknown, rawLng: unknown): JobCoords => {
    const la = Number(rawLat);
    const lo = Number(rawLng);
    if (!Number.isFinite(la) || !Number.isFinite(lo)) return null;
    // "Null island" guard — treat (0, 0) as absent.
    if (la === 0 && lo === 0) return null;
    return { lat: la, lng: lo };
  };
  // Rung 1 — /api/jobs canonical alias.
  const rung1 = trySet(job.location_lat, job.location_lng);
  if (rung1) return rung1;
  // Rung 2 — K58 Slice A dual-key output.
  const rung2 = trySet(job.latitude, job.longitude);
  if (rung2) return rung2;
  // Rung 3 — legacy write-path.
  const rung3 = trySet(job.site_lat, job.site_lng);
  if (rung3) return rung3;
  // Rung 4 — legacy nested property.location.
  const p = job.property?.location;
  if (p) {
    const rung4 = trySet(p.lat, p.lng ?? p.lon);
    if (rung4) return rung4;
  }
  // Ancillary — job.location + service_address.coordinates.  Preserved
  // for tenants whose data still carries these legacy shapes.
  if (job.location) {
    const hit = trySet(job.location.lat, job.location.lng ?? job.location.lon);
    if (hit) return hit;
  }
  const sa = job.service_address?.coordinates;
  if (sa) {
    const hit = trySet(
      sa.lat ?? sa.latitude,
      sa.lng ?? sa.lon ?? sa.longitude,
    );
    if (hit) return hit;
  }
  return null;
}

/**
 * ``jobHasCoords`` — boolean convenience wrapper for filter predicates.
 * Semantics: identical to ``resolveJobCoords(job) !== null``.
 */
export function jobHasCoords(job: JobLikeForCoords | null | undefined): boolean {
  return resolveJobCoords(job) !== null;
}
