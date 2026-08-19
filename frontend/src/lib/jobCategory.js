/**
 * Feb-2026 · Shared classifier — Service vs Repair.
 *
 * Used by the ``<JobCountPill>`` badges on the admin Workstream page
 * (web) and the tech Schedule screen (mobile). The mobile app's
 * ``mobile/lib/jobCategory.ts`` MUST stay identical to this file —
 * both surfaces share the exact same regex + priority rules so ops
 * don't have to think twice about which surface is authoritative.
 *
 * Rules (locked with user directive):
 *   1. SERVICES ← ``service_type`` matches ``/service|maintenance|
 *      cleaning|pool|landscape/i``.
 *   2. REPAIRS  ← ``service_type`` matches ``/repair|fix|replace|
 *      install/i``.
 *   3. If a job matches BOTH regexes (e.g. "pool repair"), REPAIRS
 *      wins — the repair pattern is the more actionable / urgent
 *      signal for the pill dashboard.
 *   4. Anything else → ``null`` (skip; do NOT force a bucket).
 *
 * The historical ``JobTrackerTiles.classifyJob`` helper (which
 * silently defaulted everything to "service") is INTENTIONALLY not
 * reused — its default-to-service bias would inflate the SERVICES
 * pill on non-classifiable rows.
 */

const _SERVICES_RX = /(service|maintenance|cleaning|pool|landscape)/i;
const _REPAIRS_RX = /(repair|fix|replace|install)/i;

/**
 * Categorise a single job.
 *
 * @param {object} job — job document; only ``service_type`` is read.
 * @returns {"service" | "repair" | null}
 */
export function classifyJob(job) {
  const st = String((job && job.service_type) || "");
  if (!st) return null;
  // Repair wins on ambiguous matches — see rule #3 above.
  if (_REPAIRS_RX.test(st)) return "repair";
  if (_SERVICES_RX.test(st)) return "service";
  return null;
}

/**
 * A job is "completed" (i.e. NOT remaining) when its ``status`` is
 * ``completed``. Any other status (pending, in_progress, cancelled,
 * etc.) counts as remaining for the pill's countdown. Cancelled
 * jobs still count as "remaining" for parity with the schedule
 * screen's own progress-ring math — a tech who cancels a job still
 * sees the outstanding count go down when they mark it done, and
 * the pill mirrors that.
 */
function _isCompleted(job) {
  return String((job && job.status) || "").toLowerCase() === "completed";
}

/**
 * Aggregate a list of jobs into the totals + remaining counts each
 * pill needs.
 *
 * @param {Array<object>} jobs
 * @returns {{
 *   services: { total: number, remaining: number },
 *   repairs:  { total: number, remaining: number },
 * }}
 */
export function computePillCounts(jobs) {
  const out = {
    services: { total: 0, remaining: 0 },
    repairs:  { total: 0, remaining: 0 },
  };
  for (const j of jobs || []) {
    const cat = classifyJob(j);
    if (cat === "service") {
      out.services.total += 1;
      if (!_isCompleted(j)) out.services.remaining += 1;
    } else if (cat === "repair") {
      out.repairs.total += 1;
      if (!_isCompleted(j)) out.repairs.remaining += 1;
    }
  }
  return out;
}
