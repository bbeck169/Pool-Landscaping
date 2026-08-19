/**
 * Feb-2026 · Shared classifier — Service vs Repair (mobile port).
 *
 * MUST STAY IDENTICAL to ``frontend/src/lib/jobCategory.js``. Any
 * change here MUST be mirrored there (and vice-versa) so ops
 * doesn't have to reason about surface drift. See that file's
 * header for the locked rule set.
 */

const _SERVICES_RX = /(service|maintenance|cleaning|pool|landscape)/i;
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
