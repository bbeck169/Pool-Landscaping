/**
 * Feb-2026 · F8 — Service-type classifier for schedule notes routing.
 *
 * Extracted from `<ServiceNotePill>` so:
 *   1. The pill's icon/color selection can be tested in isolation.
 *   2. Future consumers (route map, dispatch board, mobile) get one
 *      canonical classifier instead of forking the substring set.
 *   3. Backend + frontend vocab stays in sync — mirror
 *      `_POOL_KEYWORDS` / `_LANDSCAPE_KEYWORDS` in
 *      `routers/customers.py::_resolve_service_note` verbatim.
 *
 * Widened Feb-2026 so techs don't hit "why doesn't pool notes show on
 * my Filter Clean job?" — any service_type whose lowercase form
 * contains one of these tokens is treated as pool/landscape.
 *
 * Precedence: LANDSCAPE checked FIRST.  Rationale — the pool set
 * includes the generic "clean" token which appears verbatim in
 * common landscape service names ("Yard Cleanup", "Landscape
 * Cleanup").  Landscape tokens (yard/tree/hedge/mow/lawn) are all
 * strongly landscape-signal, so checking them first eliminates the
 * false-positive pool routing without ever masking a real pool job.
 * Kept in lockstep with the backend classifier in
 * `routers/customers.py::_classify_service_type`.
 */

export const POOL_KEYWORDS = Object.freeze([
  "pool",
  "chemical",
  "filter",
  "clean",
  "shock",
  "backwash",
  "algae",
]);

export const LANDSCAPE_KEYWORDS = Object.freeze([
  "landscap",
  "lawn",
  "yard",
  "tree",
  "trim",
  "mow",
  "hedge",
  "irrigation",
]);

/**
 * Return "pool" | "landscape" | "other" for a given service_type.
 * Case-insensitive substring match; empty / null input → "other".
 * Landscape checked before pool — see module comment for rationale.
 */
export function classifyServiceType(serviceType) {
  const s = String(serviceType || "").trim().toLowerCase();
  if (!s) return "other";
  for (const kw of LANDSCAPE_KEYWORDS) {
    if (s.includes(kw)) return "landscape";
  }
  for (const kw of POOL_KEYWORDS) {
    if (s.includes(kw)) return "pool";
  }
  return "other";
}
