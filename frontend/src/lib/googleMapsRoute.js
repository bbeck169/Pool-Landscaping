/**
 * Phase F1 · Feb-2026 — Google Maps multi-stop route URL builder
 * for bulk-selected schedule jobs.
 *
 * Sort: (scheduled_date ASC, route_index/route_order ASC,
 *        tech_user_id ASC) so cross-tech / cross-day selections
 * come out in schedule order. Google Maps consumer limit is 10
 * total stops (destination + 9 waypoints); we cap and let the
 * caller surface a warning toast.
 *
 * Returns:
 *   {
 *     url: string | null,           // ready to window.open (null if 0 valid stops)
 *     usedCount: number,            // stops actually placed on the URL
 *     droppedNoAddress: number,     // stops silently skipped (no lat/lng + no address)
 *     capped: boolean,              // true when input exceeded 10 stops
 *   }
 */

export function _resolveStop(job) {
  if (!job || typeof job !== "object") return null;
  const lat = Number(job.latitude);
  const lng = Number(job.longitude);
  if (Number.isFinite(lat) && Number.isFinite(lng) && !(lat === 0 && lng === 0)) {
    return `${lat},${lng}`;
  }
  const addr = (job.address || "").trim();
  return addr || null;
}

export function _sortForRoute(jobs) {
  return [...jobs].sort((a, b) => {
    const da = String(a.scheduled_date || "");
    const db = String(b.scheduled_date || "");
    if (da !== db) return da < db ? -1 : 1;
    const ra = a.route_index ?? a.route_order ?? 9999;
    const rb = b.route_index ?? b.route_order ?? 9999;
    if (ra !== rb) return ra - rb;
    const ta = String(a.tech_user_id || a.technician_id || "");
    const tb = String(b.tech_user_id || b.technician_id || "");
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });
}

export function buildMapsRouteUrl(jobs) {
  const sorted = _sortForRoute(jobs || []);
  const originalCount = sorted.length;
  const stops = [];
  let droppedNoAddress = 0;
  for (const j of sorted) {
    const s = _resolveStop(j);
    if (s) stops.push(s);
    else droppedNoAddress++;
  }
  const capped = stops.length > 10;
  const used = capped ? stops.slice(0, 10) : stops;
  if (used.length === 0) {
    return { url: null, usedCount: 0, droppedNoAddress, capped: false,
             originalCount };
  }
  const q = new URLSearchParams();
  q.set("api", "1");
  q.set("destination", used[used.length - 1]);
  const waypoints = used.slice(0, -1);
  if (waypoints.length) q.set("waypoints", waypoints.join("|"));
  return {
    url: `https://www.google.com/maps/dir/?${q.toString()}`,
    usedCount: used.length,
    droppedNoAddress,
    capped,
    originalCount,
  };
}

/**
 * Phase F1 · Feb-2026 — Bulk "Navigate route" orchestrator.
 *
 * Encapsulates the toast + window.open plumbing so the CalendarSchedule
 * click handler stays a one-liner and this behaviour is unit-testable
 * without mounting the schedule page.
 *
 * @param {object} args
 * @param {Array<object>} args.jobs        - Master pool (e.g. filteredJobs).
 * @param {Set<string>|Array<string>} args.selectedIds
 * @param {(msg: {text:string, kind:"info"|"err"}) => void} args.onToast
 * @param {(url:string) => void} args.onOpen  - Injected for tests.
 * @returns {object} the same shape as buildMapsRouteUrl (+ ``opened`` flag).
 */
export function runBulkNavigateRoute({ jobs, selectedIds, onToast, onOpen } = {}) {
  const ids = selectedIds instanceof Set
    ? selectedIds
    : new Set(Array.isArray(selectedIds) ? selectedIds : []);
  if (ids.size < 2) {
    return { url: null, usedCount: 0, droppedNoAddress: 0,
             capped: false, originalCount: 0, opened: false };
  }
  const pool = Array.isArray(jobs) ? jobs : [];
  const picked = pool.filter((j) => j && ids.has(j.id));
  const res = buildMapsRouteUrl(picked);
  if (!res.url) {
    if (typeof onToast === "function") {
      onToast({
        text: "None of the selected jobs have an address or GPS pin.",
        kind: "err",
      });
    }
    return { ...res, opened: false };
  }
  if (res.capped && typeof onToast === "function") {
    onToast({
      text: `Google Maps supports up to 10 stops. Using the first ${res.usedCount} of ${res.originalCount}.`,
      kind: "info",
    });
  } else if (res.droppedNoAddress > 0 && typeof onToast === "function") {
    onToast({
      text: `Skipped ${res.droppedNoAddress} job${res.droppedNoAddress === 1 ? "" : "s"} with no address.`,
      kind: "info",
    });
  }
  const open = typeof onOpen === "function"
    ? onOpen
    : (u) => window.open(u, "_blank", "noopener,noreferrer");
  open(res.url);
  return { ...res, opened: true };
}
