/**
 * Phase K16 · Feb-2026 — Shared "completed at" formatter.
 *
 * One canonical string shape for every worklog / service-report /
 * completion timestamp the tenant sees.  Format: ``"Sep 1, 2026 · 3:38 PM"``.
 *
 * Fallback ladder:
 *   1. ``iso`` (or object with ``.completed_at`` / ``.updated_at``).
 *   2. ``updated_at`` when ``status === "completed"``.
 *   3. em-dash ``—``.
 *
 * ``options.tz`` (optional) forces a specific IANA timezone; omit for
 * viewer's local time.
 */
export function formatCompletedAt(iso, options = {}) {
  // Object form: passed a job/report doc; unwrap.
  if (iso && typeof iso === "object") {
    const status = (iso.status || "").toLowerCase();
    const completedAt = iso.completed_at || iso.completedAt
      || (status === "completed" ? (iso.updated_at || iso.updatedAt) : null);
    return formatCompletedAt(completedAt, options);
  }
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const tz = options.tz || undefined;
  const datePart = new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: tz,
  }).format(d);
  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz,
  }).format(d);
  return `${datePart} · ${timePart}`;
}
