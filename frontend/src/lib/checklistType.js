/**
 * Phase 31 · Step 1 — shared checklist-type resolver (web).
 *
 * Pure function used by the (Step 2) tap-job flow to pick which
 * checklist form to render: pool, landscaping, or generic. Kept as a
 * standalone lib module so both the web modal and any React component
 * can import without pulling in feature-specific state.
 *
 * The Python mirror lives at backend/routers/workstream.py :: get_checklist_type
 * (see also service_reports.py :: _detect_template which uses the same
 * keyword set but returns the backend template key `landscape`, not the
 * client-facing `landscaping`).
 */

const POOL_KEYWORDS = ["pool", "chem"];
const LANDSCAPING_KEYWORDS = ["landscap", "lawn", "mow", "garden", "trim", "blow"];

/**
 * @param {object|null|undefined} job — job document; only `service_type`,
 *   `job_type`, and `title` are consulted.
 * @returns {"pool"|"landscaping"|"generic"}
 */
export function getChecklistType(job) {
  if (!job) return "generic";
  const hay = [job.service_type, job.job_type, job.title]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (POOL_KEYWORDS.some((k) => hay.includes(k))) return "pool";
  if (LANDSCAPING_KEYWORDS.some((k) => hay.includes(k))) return "landscaping";
  return "generic";
}

export default getChecklistType;
