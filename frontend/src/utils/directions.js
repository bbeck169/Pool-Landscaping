/**
 * Feb-2026 · Shared Google-Maps directions URL builder.
 *
 * Mirrors the ``_resolveDestination`` + ``_buildMapsUrl`` logic in
 * ``components/schedule/NavigateJobButton.jsx`` verbatim so the
 * schedule cards' new inline directions triggers (customer-name +
 * address as clickable buttons) produce the exact same URL shape
 * as the pre-Feb-2026 ``<NavigateJobButton />`` did.  Kept in a
 * standalone utils module so consumers don't have to import from a
 * UI component file.
 *
 * Preference order (matches NavigateJobButton):
 *   1. ``{lat, lng}`` when both are finite AND not ``(0, 0)``.
 *      Coord routing is more accurate than address-string parsing.
 *   2. ``job.address`` (trimmed) when non-empty.
 *   3. ``null`` — the caller should treat this as "not clickable"
 *      and render plain text instead of a broken button.
 *
 * URL shape: ``https://www.google.com/maps/dir/?api=1&destination=<encoded>``.
 * ``URLSearchParams`` handles the encoding of the ``,`` in coord
 * pairs + any address spaces / special chars automatically.
 */

/**
 * Pick the strongest available destination for a job.
 *
 * @param {object|null} job — schedule job row.  Expected to expose
 *   optional ``latitude``, ``longitude``, and ``address`` fields.
 * @returns {{kind: "coords"|"address", value: string}|null}
 */
export function resolveDestination(job) {
  if (!job || typeof job !== "object") return null;
  const lat = Number(job.latitude);
  const lng = Number(job.longitude);
  if (
    Number.isFinite(lat) && Number.isFinite(lng)
    && !(lat === 0 && lng === 0)
  ) {
    return { kind: "coords", value: `${lat},${lng}` };
  }
  const addr = (job.address || "").trim();
  if (addr) return { kind: "address", value: addr };
  return null;
}

/**
 * Compose a Google-Maps directions URL for a schedule job.
 *
 * @param {object|null} job
 * @returns {string|null} URL string or ``null`` when the job has
 *   neither usable coords nor an address.  Callers MUST treat
 *   ``null`` as non-clickable — see ``openDirections`` below.
 */
export function buildDirectionsUrl(job) {
  const dest = resolveDestination(job);
  if (!dest) return null;
  const q = new URLSearchParams();
  q.set("api", "1");
  q.set("destination", dest.value);
  return `https://www.google.com/maps/dir/?${q.toString()}`;
}

/**
 * Convenience click-handler helper for schedule-card directions
 * triggers.  Stops event propagation so the outer card's
 * "open-job" handler does NOT fire, then opens the directions
 * URL in a new tab.  ``noopener,noreferrer`` mirrors
 * ``NavigateJobButton``'s guard against ``window.opener`` leaks.
 *
 * Returns ``true`` when a URL was opened, ``false`` when the job
 * had no resolvable destination (so the caller can decide whether
 * to no-op or render a disabled affordance).
 */
export function openDirections(job, e) {
  if (e && typeof e.stopPropagation === "function") {
    e.stopPropagation();
  }
  const url = buildDirectionsUrl(job);
  if (!url) return false;
  window.open(url, "_blank", "noopener,noreferrer");
  return true;
}
