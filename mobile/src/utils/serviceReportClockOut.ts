/**
 * Service report "Submit & Clock Out" — closes the tech's open workforce
 * time entry for THIS job.
 *
 * Backend contract (backend/routers/workforce.py:159-163, :311):
 *   POST /workforce/clock-out  { entry_id: str, lat: float, lng: float, notes?: str }
 *   404 "Time entry not found" · 400 "Already clocked out" · 422 bad body.
 * `entry_id` is resolved from GET /workforce/timesheets?status=open (same
 * source as app/time-clock.tsx), matched on job_id + user_id (admins see
 * every user's rows). One open entry per user (clock-in rejects a second).
 */
import * as Location from "expo-location";
import { api } from "@/src/api";

export type ClockOutResult =
  | { status: "closed"; entryId: string }
  | { status: "none" } // not clocked in to this job via workforce — nothing to close
  | { status: "failed"; message: string };

const errMsg = (e: any, fallback: string) => {
  const d = e?.response?.data?.detail ?? e?.detail;
  return typeof d === "string" && d ? d : String(e?.message || fallback);
};

export async function clockOutOpenEntryForJob(jobId: string, userId?: string | null): Promise<ClockOutResult> {
  let entry: any;
  try {
    const rows = await api.get("/workforce/timesheets?status=open");
    entry = (Array.isArray(rows) ? rows : []).find(
      (r: any) => r && !r.clock_out_at && r.job_id === jobId && (!userId || r.user_id === userId),
    );
  } catch (e) {
    return { status: "failed", message: `Couldn't look up your time entry: ${errMsg(e, "network error")}` };
  }
  if (!entry?.id) return { status: "none" };

  let lat: number;
  let lng: number;
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return { status: "failed", message: "Location permission is required to clock out." };
    const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
    lat = pos.coords.latitude;
    lng = pos.coords.longitude;
  } catch (e) {
    return { status: "failed", message: `Couldn't get your location: ${errMsg(e, "GPS unavailable")}` };
  }

  try {
    await api.post("/workforce/clock-out", { entry_id: entry.id, lat, lng });
    return { status: "closed", entryId: entry.id };
  } catch (e) {
    return { status: "failed", message: errMsg(e, "Clock-out failed.") };
  }
}
