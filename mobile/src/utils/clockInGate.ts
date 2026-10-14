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
  "landscaping",
  "landscape_tech",
  "landscaper",
  "both",
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

type GateUser = { role?: string; department?: string } | null | undefined;

/** "Pool Tech" / "pool-tech" / " pool_tech " → "pool_tech". */
function normDept(user: GateUser): string {
  return String(user?.department || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
}

/** True for technicians whose `users.department` is a pool-family value. */
export function isPoolTech(user: GateUser): boolean {
  if (!user) return false;
  const role = String(user.role || "").toLowerCase();
  return role === "technician" && POOL_DEPTS.has(normDept(user));
}

/**
 * Returns true when the user is a technician whose department is
 * one of the landscape-family values.  Pool techs, admins,
 * super_admins, managers, owners, and customers all return false.
 * Cross-trained ("both") techs stay gated (web parity).
 */
export function isLandscapeTech(user: GateUser): boolean {
  if (!user || isPoolTech(user)) return false;
  const role = String(user.role || "").toLowerCase();
  return role === "technician" && LANDSCAPE_DEPTS.has(normDept(user));
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
