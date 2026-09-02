/**
 * dateTimeFormat.ts — Phase K22 · Mobile port of K16 web helper.
 *
 * Canonical "completed at" formatter. One canonical string shape for
 * every worklog / service-report / completion timestamp the tenant
 * sees.  Format: ``"Sep 1, 2026 · 3:38 PM"``.
 *
 * Fallback ladder:
 *   1. ``iso`` (string) — parsed directly.
 *   2. Object with ``.completed_at`` / ``.completedAt`` — unwrapped.
 *   3. ``updated_at`` when ``status === "completed"`` — fallback.
 *   4. em-dash ``—`` on null / invalid.
 *
 * ``options.tz`` (optional) forces a specific IANA timezone; omit
 * for the viewer's local time.
 */

type CompletedAtObject = {
  completed_at?: string | null;
  completedAt?: string | null;
  updated_at?: string | null;
  updatedAt?: string | null;
  status?: string | null;
};

export function formatCompletedAt(
  iso: string | CompletedAtObject | null | undefined,
  options: { tz?: string } = {},
): string {
  // Object form: passed a job / report doc; unwrap.
  if (iso && typeof iso === "object") {
    const status = (iso.status || "").toLowerCase();
    const completedAt =
      iso.completed_at ||
      iso.completedAt ||
      (status === "completed" ? (iso.updated_at || iso.updatedAt) : null);
    return formatCompletedAt(completedAt, options);
  }

  if (!iso) return "\u2014"; // em-dash

  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "\u2014";

  const tz = options.tz || undefined;

  const datePart = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: tz,
  }).format(d);

  const timePart = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: tz,
  }).format(d);

  return `${datePart} \u00b7 ${timePart}`; // · (middle dot)
}
