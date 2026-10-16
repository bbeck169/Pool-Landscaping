/**
 * Landscape-tech clock-in gate utilities (mobile parity for web f5dd1eb0a).
 *
 * - `isPoolTech(user)` — true for techs in a pool-family dept (always bypass the gate).
 * - `isLandscapeTech(user)` — true for non-pool techs in landscaping/landscape_tech/landscaper/both depts.
 * - `useClockInStatus()` — polls GET /api/timeclock/mine-status; exposes clockedIn / loading / refetch.
 */
import { useState, useCallback, useEffect } from "react";
import { api } from "@/src/api";

const LANDSCAPE_DEPTS = new Set([
  "landscape",
  "landscaping",
  "landscape_tech",
  "landscaper",
  "both",
  "cross_trained",
]);

// Pool-family department values. Pool techs NEVER see the clock-in
// gate (hotfix): they route straight to their schedule.
const POOL_DEPTS = new Set([
  "pool",
  "pools",
  "pool_tech",
  "pool_technician",
  "pool_service",
]);

type GateUser = {
  role?: string;
  department?: string | null;
  service_category?: string | null;
  service_cat?: string | null;
  service_cats?: string[] | null;
} | null | undefined;

/** "Pool Tech" / "pool-tech" / " pool_tech " → "pool_tech". */
function norm(v: unknown): string {
  return String(v ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

/**
 * Category from the first populated discriminator, in precedence order
 * service_category → service_cat → service_cats[] → department.
 * Canonical backend field is `users.department` (Team PATCH writes it,
 * /auth/me returns it); the others are tolerated for field drift.
 * An array holding any landscape value counts as landscape (cross-trained).
 * Unknown / missing → null (caller keeps its current default).
 */
function techCategory(user: GateUser): "pool" | "landscape" | null {
  if (!user) return null;
  const arr = Array.isArray(user.service_cats) ? user.service_cats.map(norm).filter(Boolean) : [];
  const scalar = [user.service_category, user.service_cat].map(norm).find(Boolean);
  if (scalar) return POOL_DEPTS.has(scalar) ? "pool" : LANDSCAPE_DEPTS.has(scalar) ? "landscape" : null;
  if (arr.length) {
    if (arr.some((v) => LANDSCAPE_DEPTS.has(v))) return "landscape";
    return arr.some((v) => POOL_DEPTS.has(v)) ? "pool" : null;
  }
  const d = norm(user.department);
  return POOL_DEPTS.has(d) ? "pool" : LANDSCAPE_DEPTS.has(d) ? "landscape" : null;
}

const isTechnician = (user: GateUser) => String(user?.role || "").toLowerCase() === "technician";

/** True for technicians whose category resolves to a pool-family value. */
export function isPoolTech(user: GateUser): boolean {
  return isTechnician(user) && techCategory(user) === "pool";
}

/**
 * Returns true when the user is a technician whose category resolves to
 * a landscape-family value.  Pool techs, admins, super_admins, managers,
 * owners, and customers all return false.  Cross-trained ("both") techs
 * stay gated (web parity).
 */
export function isLandscapeTech(user: GateUser): boolean {
  return isTechnician(user) && techCategory(user) === "landscape";
}

/**
 * Hook that checks whether the current user is clocked in via
 * `GET /api/timeclock/mine-status`.
 *
 * Returns:
 * - `clockedIn`: `true` / `false` / `null` (initial, not yet fetched).
 * - `loading`: true while the request is in flight.
 * - `refetch()`: re-polls the endpoint (call after a successful punch).
 *
 * `enabled = false` (non-gated users, e.g. pool techs) skips the probe
 * entirely and reports clocked-in, so no 403 round trip is made.
 */
export function useClockInStatus(enabled: boolean = true) {
  const [clockedIn, setClockedIn] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    if (!enabled) {
      // Reset so a later enable (e.g. landscaper logs in) shows the
      // loader, never a stale "clocked in" pass-through.
      setClockedIn(null);
      setLoading(true);
      return;
    }
    setLoading(true);
    try {
      const resp = await api.get("/timeclock/mine-status");
      setClockedIn(!!resp?.clocked_in);
    } catch {
      // Fail-open: if we can't reach the endpoint, assume clocked-in
      // so the tech is never locked out of their normal workflow.
      setClockedIn(true);
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  if (!enabled) return { clockedIn: true as boolean | null, loading: false, refetch };
  return { clockedIn, loading, refetch };
}
