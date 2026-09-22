/**
 * Phase P19 · tenantTime.ts — tenant-timezone-aware "today" helpers.
 *
 * Centralizes the derivation of "which calendar day is it right now
 * in the tenant's configured timezone?" so Schedule, Dashboard, and
 * Dispatch surfaces all agree.
 *
 * Uses `Intl.DateTimeFormat("en-CA", { timeZone })` which produces
 * `YYYY-MM-DD` natively on Hermes and V8 — no polyfill needed.
 */

// Default fallback when tenant settings haven't been loaded yet.
const DEFAULT_TZ = "America/Phoenix";

// Module-level cache so screens that import `tenantTz()` without an
// active settings fetch still get the last-known value.
let _cachedTz: string = DEFAULT_TZ;

/**
 * Update the cached tenant timezone. Called from the settings screen
 * after a successful PATCH, and from any boot-time tenant fetch.
 */
export function setTenantTz(tz: string): void {
  _cachedTz = tz || DEFAULT_TZ;
}

/**
 * Returns the current tenant IANA timezone string.
 * Falls back to America/Phoenix if never set.
 */
export function tenantTz(): string {
  return _cachedTz || DEFAULT_TZ;
}

/**
 * Returns today's date as `YYYY-MM-DD` in the tenant's timezone.
 *
 * Uses `Intl.DateTimeFormat("en-CA")` which formats dates as
 * `YYYY-MM-DD` — the Canadian English locale is ISO-8601 by default.
 */
export function todayKeyInTenantTz(tz?: string): string {
  const zone = tz || tenantTz();
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: zone }).format(new Date());
  } catch {
    // Fallback for unknown timezone strings — use device local.
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
}
