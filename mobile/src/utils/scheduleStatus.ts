/**
 * Schedule-UI helper — left-border color by job status.
 *
 *   completed → coral-red #ff4542 (web parity, 85fd76f17)
 *   everything else → blue #2563EB
 *
 * Mirrors the web's `getStatusBorderColor()` in CalendarSchedule.jsx.
 */
export function getStatusBorderColor(status?: string | null): string {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "#ff4542";
  return "#2563EB";
}
