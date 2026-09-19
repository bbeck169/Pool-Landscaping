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
 *      cleaning|pool|landscap|inspection|weekly|monthly/i``. The
 *      ``landscap`` stem is intentional so both "Landscaping" and
 *      "Monthly Landscaping" match; "Inspection", "Weekly", and
 *      "Monthly" cover recurring service cadences.
 *   2. REPAIRS  ← ``service_type`` matches ``/repair|fix|replace|
 *      install/i``.
 *   3. If a job matches BOTH regexes (e.g. "pool repair"), REPAIRS
 *      wins — the repair pattern is the more actionable / urgent
 *      signal for the pill dashboard.
 *   4. Feb-2026 fallback: if neither regex matched AND the job's
 *      ``status`` is ``completed``, classify as ``"service"``. This
 *      keeps finished work from leaking out of the pill totals when
 *      the ``service_type`` string is idiosyncratic. Non-completed
 *      unmatched jobs stay ``null`` (rule #5 below).
 *   5. Anything else → ``null`` (skip; do NOT force a bucket).
 *
 * The historical ``JobTrackerTiles.classifyJob`` helper (which
 * silently defaulted everything to "service") is INTENTIONALLY not
 * reused — its default-to-service bias would inflate the SERVICES
 * pill on non-classifiable rows.
 */

const _SERVICES_RX = /(service|maintenance|cleaning|pool|landscap|inspection|weekly|monthly)/i;
const _REPAIRS_RX = /(repair|fix|replace|install)/i;

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
 * Categorise a single job.
 *
 * @param {object} job — job document; reads ``service_type`` (for
 *   regex matching) and ``status`` (for the completed fallback).
 * @returns {"service" | "repair" | null}
 */
export function classifyJob(job) {
  const st = String((job && job.service_type) || "");
  if (!st) return null;
  // Repair wins on ambiguous matches — see rule #3 above.
  if (_REPAIRS_RX.test(st)) return "repair";
  if (_SERVICES_RX.test(st)) return "service";
  // Feb-2026 · Rule #4 — completed jobs that didn't match either
  // regex fall through to the Services bucket so finished work
  // doesn't disappear from the pill totals. Non-completed unmatched
  // jobs stay ``null`` (unchanged).
  if (_isCompleted(job)) return "service";
  return null;
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
