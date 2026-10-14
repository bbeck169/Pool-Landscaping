/**
 * Schedule-UI helper — left-border color by job status.
 *
 *   completed / closed / done → soft green #6EE7B7 (Oct-2026 mobile
 *               hotfix: completed cards recede; was coral-red #ff4542
 *               for "completed" only, web 85fd76f17)
 *   everything else → blue #2563EB
 *
 * Mirrors the web's `getStatusBorderColor()` in CalendarSchedule.jsx.
 */
export function getStatusBorderColor(status?: string | null): string {
  const s = (status || "").toLowerCase();
  if (s === "completed" || s === "closed" || s === "done") return "#6EE7B7";
  return "#2563EB";
}
