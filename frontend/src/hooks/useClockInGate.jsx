import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";

/**
 * Phase 56.3 follow-up — Clock-in gate hook for landscape technicians.
 *
 * Wraps any navigation to a job detail page so strict landscape techs
 * (role=technician + department=landscaping) must be clocked in before
 * the app takes them there. Admins, super_admins, "All" role users
 * (admin+both), pool techs, and customers are exempt.
 *
 * Usage:
 *   const gate = useClockInGate(user);
 *   <button onClick={() => gate.openJob(jobId, ()=>navigate(`/jobs/${jobId}`))}>
 *   {gate.render()}
 */
export function useClockInGate(user) {
  const navigate = useNavigate();
  const role = String(user?.role || "").toLowerCase();
  const dept = String(user?.department || "").toLowerCase();
  // Only strict landscape techs are gated. Admin/super_admin/both are exempt.
  const gated = role === "technician" && dept === "landscaping";
  const [pendingJob, setPendingJob] = useState(null); // {jobId, cb}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const openJob = useCallback(async (jobId, cb) => {
    if (!gated) {
      // Non-gated — fast path.
      cb ? cb() : navigate(`/jobs/${jobId}`);
      return;
    }
    try {
      const s = await api.get("/timeclock/mine-status");
      if (s?.clocked_in) {
        cb ? cb() : navigate(`/jobs/${jobId}`);
        return;
      }
      setPendingJob({ jobId, cb: cb || (() => navigate(`/jobs/${jobId}`)) });
    } catch {
      // If the status probe fails (403 for unaligned users, network),
      // fall through — do not lock the user out over a transient error.
      cb ? cb() : navigate(`/jobs/${jobId}`);
    }
  }, [gated, navigate]);

  const clockInAndProceed = useCallback(async () => {
    if (!pendingJob) return;
    setBusy(true);
    setError("");
    try {
      // Best-effort GPS. `POST /timeclock/punch` accepts null coords
      // (geo_denied flag) so denied permissions do not block the punch.
      const coords = await new Promise((resolve) => {
        if (!navigator?.geolocation) return resolve({ denied: true });
        navigator.geolocation.getCurrentPosition(
          (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude,
                             accuracy_m: pos.coords.accuracy, denied: false }),
          () => resolve({ denied: true }),
          { enableHighAccuracy: false, timeout: 4000 },
        );
      });
      await api.post("/timeclock/punch", {
        punch_type: "in",
        source: "web",
        lat: coords.lat ?? null,
        lng: coords.lng ?? null,
        accuracy_m: coords.accuracy_m ?? null,
        geo_denied: !!coords.denied,
      });
      const cb = pendingJob.cb;
      setPendingJob(null);
      cb?.();
    } catch (e) {
      setError(e?.message || "Failed to clock in. Please try again.");
    } finally {
      setBusy(false);
    }
  }, [pendingJob]);

  const cancel = useCallback(() => {
    if (busy) return;
    setPendingJob(null);
    setError("");
  }, [busy]);

  return { openJob, pendingJob, clockInAndProceed, cancel, busy, error, gated };
}

/**
 * Renderer for the clock-in dialog. Consumers mount `<ClockInGateDialog gate={gate} />`
 * once inside their component tree so the dialog surfaces when needed.
 */
export function ClockInGateDialog({ gate }) {
  if (!gate?.pendingJob) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15, 23, 42, 0.55)" }}
      data-testid="clockin-gate-dialog"
    >
      <div
        className="rounded-2xl p-6 max-w-md w-full shadow-2xl"
        style={{ background: "#fff", border: "1px solid #E5E7EB" }}
      >
        <h3 className="text-lg font-bold mb-2" style={{ color: "#0F172A" }}>
          Clock in required
        </h3>
        <p className="text-sm mb-4" style={{ color: "#334155" }}>
          You must clock in before opening jobs. Clock in now?
        </p>
        {gate.error ? (
          <div className="text-xs mb-3" style={{ color: "#B91C1C" }} data-testid="clockin-gate-error">
            {gate.error}
          </div>
        ) : null}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={gate.cancel}
            disabled={gate.busy}
            className="px-3 py-1.5 rounded-md text-sm font-semibold"
            style={{ background: "transparent", border: "1px solid #CBD5E1", color: "#0F172A" }}
            data-testid="clockin-gate-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={gate.clockInAndProceed}
            disabled={gate.busy}
            className="px-3 py-1.5 rounded-md text-sm font-bold"
            style={{ background: "#16A34A", color: "#fff", border: 0 }}
            data-testid="clockin-gate-confirm"
          >
            {gate.busy ? "Clocking in…" : "Clock In & Open"}
          </button>
        </div>
      </div>
    </div>
  );
}
