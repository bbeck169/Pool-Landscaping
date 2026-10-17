/**
 * TD-64 Phase 2b · Time Clock designation (mobile mirror of web b1e97bba4).
 *
 * Mirrors backend/routers/timeclock_landscaping.py:288 _LANDSCAPE_DEPTS.
 * Keep in sync with frontend/src/lib/timeClockVisibility.js (drift-guarded
 * by __tests__/time-clock-visibility.test.ts).
 *
 * `show_time_clock` (from GET /api/auth/me) is the single source of truth —
 * the BE resolves users.department → technicians.department. The department
 * fallback only applies to a cached user that predates the /me refresh.
 */
export const LANDSCAPE_DEPTS = new Set<string>(["landscaping", "landscape_tech", "landscaper", "both"]);

type UserLike = {
  department?: string | null;
  effective_department?: string | null;
  show_time_clock?: boolean | null;
} | null | undefined;

export function shouldShowTimeClock(user: UserLike): boolean {
  if (!user) return false;
  if (typeof user.show_time_clock === "boolean") return user.show_time_clock;
  const d = (user.effective_department ?? user.department ?? "").toString().trim().toLowerCase();
  return LANDSCAPE_DEPTS.has(d);
}

/** Web route-guard semantics (TechPages / LandscapingTimeClock): only
 *  technicians without the designation are bounced; admins/managers never. */
export function isPoolTechWithoutTimeClock(user: (UserLike & { role?: string | null })): boolean {
  return String(user?.role || "").toLowerCase() === "technician" && !shouldShowTimeClock(user);
}

export default shouldShowTimeClock;
