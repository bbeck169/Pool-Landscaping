/**
 * Feb-2026 · Shared classifier — Service vs Repair (mobile port).
 *
 * MUST STAY IDENTICAL to ``frontend/src/lib/jobCategory.js``. Any
 * change here MUST be mirrored there (and vice-versa) so ops
 * doesn't have to reason about surface drift.
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
 */

const _SERVICES_RX = /(service|maintenance|cleaning|pool|landscap|inspection|weekly|monthly)/i;
const _REPAIRS_RX = /(repair|fix|replace|install)/i;

export type JobCategory = "service" | "repair" | null;

export interface JobLike {
  service_type?: string | null;
  status?: string | null;
}

export function classifyJob(job: JobLike | null | undefined): JobCategory {
  const st = String((job && job.service_type) || "");
  if (!st) return null;
  if (_REPAIRS_RX.test(st)) return "repair";
  if (_SERVICES_RX.test(st)) return "service";
  // Feb-2026 · Rule #4 — completed jobs that didn't match either
  // regex fall through to the Services bucket so finished work
  // doesn't disappear from the pill totals. Non-completed unmatched
  // jobs stay ``null`` (unchanged).
  if (_isCompleted(job)) return "service";
  return null;
}

function _isCompleted(job: JobLike): boolean {
  return String((job && job.status) || "").toLowerCase() === "completed";
}

export interface PillCounts {
  services: { total: number; remaining: number };
  repairs: { total: number; remaining: number };
}

export function computePillCounts(jobs: JobLike[] | null | undefined): PillCounts {
  const out: PillCounts = {
    services: { total: 0, remaining: 0 },
    repairs: { total: 0, remaining: 0 },
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
