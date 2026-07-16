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
const LANDSCAPING_KEYWORDS = ["landscap", "lawn", "mow", "garden", "trim", "blow", "cleanup"];

/**
 * @param {object|null|undefined} job — job document; consults
 *   `checklist_kind` first (explicit override), then the assigned tech's
 *   `technician_department` (Phase 57), then keyword-derives from
 *   `service_type` / `job_type` / `title`. Default is "pool" per the
 *   Phase 57 fallback safety net (see HANDOFF).
 * @returns {"pool"|"landscaping"|"generic"}
 */
export function getChecklistType(job) {
  if (!job) return "generic";
  // Phase 57 · explicit override wins.
  const kind = (job.checklist_kind || "").toLowerCase();
  if (kind === "pool") return "pool";
  if (kind === "landscape" || kind === "landscaping") return "landscaping";
  // Phase 57 · assigned tech's department overrides keywords.
  const dept = (job.technician_department || "").toLowerCase();
  if (dept === "landscaping") return "landscaping";
  if (dept === "pool") return "pool";
  // Fallback: keyword sniff on service_type / job_type / title.
  const hay = [job.service_type, job.job_type, job.title]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (POOL_KEYWORDS.some((k) => hay.includes(k))) return "pool";
  if (LANDSCAPING_KEYWORDS.some((k) => hay.includes(k))) return "landscaping";
  // No signal at all — default to pool (safest for this business).
  return "pool";
}

export default getChecklistType;
