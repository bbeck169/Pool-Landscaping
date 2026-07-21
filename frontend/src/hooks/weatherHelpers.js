/**
 * weatherHelpers — pure JS predicates used by ``JobRainFlag`` and
 * ``useWeatherHourly``. Extracted into a standalone module so the
 * unit test can import them without pulling in the CRA-only
 * ``@/api`` alias.
 */

/** Returns ``true`` when any hourly row for the given ``dateISO``
 *  (YYYY-MM-DD) has ``chance_of_rain >= threshold``. */
export function hasRainOnDate(hourlyPayload, dateISO, threshold = 60) {
  if (!hourlyPayload || !Array.isArray(hourlyPayload.hourly)) return false;
  if (!dateISO) return false;
  const prefix = String(dateISO).slice(0, 10);
  for (const h of hourlyPayload.hourly) {
    const t = String(h?.time || "");
    if (!t.startsWith(prefix)) continue;
    const p = Number(h?.chance_of_rain);
    if (Number.isFinite(p) && p >= threshold) return true;
  }
  return false;
}

/** Returns the max ``chance_of_rain`` across all hourly rows that
 *  fall on ``dateISO``, or ``null`` when nothing matches. */
export function maxRainChanceOnDate(hourlyPayload, dateISO) {
  if (!hourlyPayload || !Array.isArray(hourlyPayload.hourly)) return null;
  if (!dateISO) return null;
  const prefix = String(dateISO).slice(0, 10);
  let mx = null;
  for (const h of hourlyPayload.hourly) {
    if (!String(h?.time || "").startsWith(prefix)) continue;
    const p = Number(h?.chance_of_rain);
    if (Number.isFinite(p) && (mx == null || p > mx)) mx = p;
  }
  return mx;
}
