/**
 * Feb-2026 · P37b — Reusable job-timer badges.
 *
 * Renders the P37 origin/termination badges next to the elapsed
 * timer wherever the job list / detail views display timer state.
 * Show-only badges — the underlying timer logic (elapsed, controls)
 * is unchanged.
 *
 * Badges only appear when the server sent the corresponding
 * ``timer_start_method`` / ``timer_stop_method`` value; older jobs
 * and manual starts (fields absent) render nothing.
 *
 * Data contract (matches ``backend/routers/jobs.py::job_arrive`` and
 * the service-report submit auto-stop hook):
 *   timer_start_method:
 *     - "gps_arrival"                 → "Started HH:MM via GPS arrival"
 *   timer_stop_method:
 *     - "service_report_submitted"    → "Stopped via service report"
 *     - "job_completed"               → "Stopped via job completion"
 */
import React from "react";


function _hhmm(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  } catch {
    return "";
  }
}


export function TimerStartBadge({ job }) {
  const method = job?.timer_start_method;
  if (method !== "gps_arrival") return null;
  const t = _hhmm(job?.timer_started_at);
  const label = t ? `Started ${t} via GPS arrival` : "Started via GPS arrival";
  return (
    <span
      data-testid={`timer-start-badge-${job.id}`}
      className="inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded"
      style={{ background: "#E0F2FE", color: "#075985" }}
    >
      {label}
    </span>
  );
}


export function TimerStopBadge({ job }) {
  const method = job?.timer_stop_method;
  if (!method) return null;

  let label = null;
  if (method === "service_report_submitted") {
    label = "Stopped via service report";
  } else if (method === "job_completed") {
    label = "Stopped via job completion";
  }
  if (!label) return null;
  return (
    <span
      data-testid={`timer-stop-badge-${job.id}`}
      className="inline-flex items-center px-2 py-0.5 text-xs font-semibold rounded"
      style={{ background: "#F1F5F9", color: "#334155" }}
    >
      {label}
    </span>
  );
}


export default function TimerBadges({ job }) {
  if (!job) return null;
  return (
    <>
      <TimerStartBadge job={job} />
      {job.timer_start_method && job.timer_stop_method ? " " : null}
      <TimerStopBadge job={job} />
    </>
  );
}
