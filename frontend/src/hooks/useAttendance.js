import { useCallback, useEffect, useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/auth";

/**
 * Web equivalent of the Expo `useAttendance` hook.
 * Reflects the current-day timesheet from `GET /api/attendance/today`.
 * For non-tech roles, returns `clockedIn=true` so gates stay open.
 */
export function useAttendance() {
  const { user } = useAuth();
  const isTech = user?.role === "technician";
  const [state, setState] = useState({
    loading: isTech,
    clockedIn: !isTech,
    clockedOut: false,
    timesheet: null,
  });

  const refresh = useCallback(async () => {
    if (!isTech) {
      setState({ loading: false, clockedIn: true, clockedOut: false, timesheet: null });
      return;
    }
    try {
      const res = await api.get("/attendance/today");
      setState({
        loading: false,
        clockedIn: !!res?.clocked_in && !res?.clocked_out,
        clockedOut: !!res?.clocked_out,
        timesheet: res?.timesheet || null,
      });
    } catch {
      setState({ loading: false, clockedIn: false, clockedOut: false, timesheet: null });
    }
  }, [isTech]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const clockIn = async () => {
    await api.post("/attendance/clock-in", {});
    await refresh();
  };
  const clockOut = async () => {
    await api.post("/attendance/clock-out", {});
    await refresh();
  };

  return { ...state, isTech, refresh, clockIn, clockOut };
}
