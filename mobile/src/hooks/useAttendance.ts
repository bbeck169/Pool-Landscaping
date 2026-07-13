import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";

/**
 * Tech attendance state — reflects the current-day timesheet from
 * `GET /api/attendance/today`. Returns { loading, clockedIn, clockedOut, timesheet, refresh }.
 * For non-technician users, returns clockedIn=true so gates stay open.
 */
export function useAttendance() {
  const { user } = useAuth();
  const isTech = user?.role === "technician";
  const [loading, setLoading] = useState(isTech);
  const [state, setState] = useState<{
    clockedIn: boolean;
    clockedOut: boolean;
    timesheet: any;
  }>({ clockedIn: !isTech, clockedOut: false, timesheet: null });

  const refresh = useCallback(async () => {
    if (!isTech) {
      setState({ clockedIn: true, clockedOut: false, timesheet: null });
      setLoading(false);
      return;
    }
    try {
      const res = await api.get("/attendance/today");
      setState({
        clockedIn: !!res?.clocked_in && !res?.clocked_out,
        clockedOut: !!res?.clocked_out,
        timesheet: res?.timesheet || null,
      });
    } catch {
      // On error, stay locked to be safe.
      setState({ clockedIn: false, clockedOut: false, timesheet: null });
    } finally {
      setLoading(false);
    }
  }, [isTech]);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  return { loading, ...state, refresh, isTech };
}
