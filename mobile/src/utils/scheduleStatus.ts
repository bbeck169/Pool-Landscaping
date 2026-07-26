/**
 * Schedule-UI helper — left-border color by job status.
 *
 *   completed → red #DC2626
 *   everything else → blue #2563EB
 *
 * Mirrors the web's `getStatusBorderColor()` in CalendarSchedule.jsx.
 */
export function getStatusBorderColor(status?: string | null): string {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "#DC2626";
  return "#2563EB";
}
