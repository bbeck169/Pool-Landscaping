/**
 * Landscape-tech clock-in gate utilities (mobile parity for web f5dd1eb0a).
 *
 * - `isLandscapeTech(user)` — true for techs in landscaping/landscape_tech/landscaper/both depts.
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

/**
 * Returns true when the user is a technician whose department is
 * one of the landscape-family values.  Pool techs, admins,
 * super_admins, managers, owners, and customers all return false.
 */
export function isLandscapeTech(
  user: { role?: string; department?: string } | null | undefined,
): boolean {
  if (!user) return false;
  const role = String(user.role || "").toLowerCase();
  const dept = String(user.department || "").toLowerCase();
  return role === "technician" && LANDSCAPE_DEPTS.has(dept);
}

/**
 * Hook that checks whether the current user is clocked in via
 * `GET /api/timeclock/mine-status`.
 *
 * Returns:
 * - `clockedIn`: `true` / `false` / `null` (initial, not yet fetched).
 * - `loading`: true while the request is in flight.
 * - `refetch()`: re-polls the endpoint (call after a successful punch).
 */
export function useClockInStatus() {
  const [clockedIn, setClockedIn] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { clockedIn, loading, refetch };
}
