/**
 * Phase 31 · Step 1 — shared checklist-type resolver (mobile).
 *
 * Mirror of `frontend/src/lib/checklistType.js`. Same keyword set,
 * same return values — kept in sync by hand because there is no
 * shared JS package between web and Expo in this repo.
 *
 * Python mirror: backend/routers/workstream.py :: get_checklist_type.
 */

export type ChecklistType = "pool" | "landscaping" | "generic";

export type ChecklistJobShape = {
  service_type?: string | null;
  job_type?: string | null;
  title?: string | null;
} | null | undefined;

const POOL_KEYWORDS = ["pool", "chem"];
const LANDSCAPING_KEYWORDS = [
  "landscap",
  "lawn",
  "mow",
  "garden",
  "trim",
  "blow",
];

export function getChecklistType(job: ChecklistJobShape): ChecklistType {
  if (!job) return "generic";
  const hay = [job.service_type, job.job_type, job.title]
    .filter((v): v is string => Boolean(v))
    .join(" ")
    .toLowerCase();
  if (POOL_KEYWORDS.some((k) => hay.includes(k))) return "pool";
  if (LANDSCAPING_KEYWORDS.some((k) => hay.includes(k))) return "landscaping";
  return "generic";
}

export default getChecklistType;
