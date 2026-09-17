/**
 * Feb-2026 · P0 Timezone Fix — Tenant-timezone-aware "today" helpers.
 *
 * Bug context: ``new Date().toISOString().slice(0, 10)`` returns the UTC
 * date, not the tenant-local date. For a Phoenix (UTC-7) tenant, that
 * flips to tomorrow's date at 5 PM local (00:00 UTC) — jobs scheduled
 * for today disappear from the "Today's Schedule" surface prematurely.
 *
 * Source-of-truth ladder for the tenant IANA tz:
 *   1. server response ``data.tz`` from ``/schedule/today`` (authoritative)
 *   2. tenant context ``tenant.timezone`` (not yet exposed in FE hooks)
 *   3. backend default ``"America/Phoenix"`` (constant below)
 *
 * All helpers rely on ``Intl.DateTimeFormat`` (zero-dep, stdlib in every
 * modern browser). No ``date-fns-tz`` runtime add.
 */

export const TENANT_TZ_FALLBACK = "America/Phoenix";

/**
 * Return the "today" date for the given IANA tz as ``yyyy-mm-dd``.
 * When ``tz`` is missing or unrecognised, falls back to
 * ``TENANT_TZ_FALLBACK``.
 */
export function getTenantTodayISO(tz) {
  return getTenantISODate(new Date(), tz);
}

/**
 * Return the tenant-local ``yyyy-mm-dd`` for an arbitrary ``Date``
 * (or ISO string / epoch millis).  Uses ``Intl.DateTimeFormat`` with
 * ``en-CA`` for the ISO shape, which is spec-mandated to emit
 * ``YYYY-MM-DD`` — no locale drift.
 */
export function getTenantISODate(input, tz) {
  const d = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(d.getTime())) return "";
  const zone = tz || TENANT_TZ_FALLBACK;
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric", month: "2-digit", day: "2-digit",
    }).format(d);
  } catch {
    // Unknown timezone id — fall back rather than throw.
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: TENANT_TZ_FALLBACK,
      year: "numeric", month: "2-digit", day: "2-digit",
    }).format(d);
  }
}

/**
 * Add ``delta`` days to an ``yyyy-mm-dd`` string, staying anchored in
 * the tenant tz.  We build the noon-local Date via the tz offset so
 * DST-crossing arithmetic doesn't slip a day.
 */
export function shiftTenantISODate(iso, delta, tz) {
  if (!iso || typeof iso !== "string") return "";
  // Anchor at 12:00 UTC on the given date — 12h buffer keeps us on
  // the same calendar day for every IANA tz (-12 → +14).
  const anchor = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(anchor.getTime())) return "";
  anchor.setUTCDate(anchor.getUTCDate() + delta);
  return getTenantISODate(anchor, tz);
}

/**
 * Equality check: is ``iso`` the tenant-local "today"?
 */
export function isTenantTodayISO(iso, tz) {
  if (!iso) return false;
  return iso === getTenantTodayISO(tz);
}
