/**
 * Phase 31 · Step 1 — shared checklist-type resolver (web).
 *
 * Pure function used by the (Step 2) tap-job flow to pick which
 * checklist form to render: pool, landscaping, or generic. Kept as a
 * standalone lib module so both the web modal and any React component
 * can import without pulling in feature-specific state.
 *
 * The Python mirror lives at backend/routers/jobs.py :: _derive_checklist_kind
 * (see also service_reports.py :: _detect_template which uses the same
 * keyword set but returns the backend template key `landscape`, not the
 * client-facing `landscaping`).
 *
 * Sync note (Phase J1 · Feb-2026, updated Phase P36.1): the priority
 * chain here mirrors backend/routers/jobs.py :: _derive_checklist_kind.
 * Keep both files in lockstep — service_type/title signal wins over
 * tech department. Phase P36.1 flipped the no-signal fallback from
 * "pool" to "generic" to match the backend's "non_pool" default and
 * avoid dragging non-pool jobs (tree_service, hvac, pest_control, …)
 * through pool-only UI.
 */

const POOL_KEYWORDS = ["pool", "chem"];
const LANDSCAPING_KEYWORDS = ["landscap", "lawn", "mow", "garden", "trim", "blow", "cleanup"];

/**
 * @param {object|null|undefined} job — job document.
 *
 * Priority chain (Phase J1 · Feb-2026):
 *   1. explicit override via `checklist_kind` on the job
 *   2. **Job Title / Service Type keywords** — promoted above tech
 *      department so the work being performed drives the checklist
 *      choice (a landscaping job gets the landscape checklist even
 *      when assigned to a Pool tech, and vice versa)
 *   3. tech department (`technician_department`)
 *   4. `"pool"` fallback (safest default for this business — Phase 57)
 *
 * @returns {"pool"|"landscaping"|"generic"}
 */
export function getChecklistType(job) {
  if (!job) return "generic";
  // 1) Phase 57 · explicit override wins.
  const kind = (job.checklist_kind || "").toLowerCase();
  if (kind === "pool") return "pool";
  if (kind === "landscape" || kind === "landscaping") return "landscaping";
  // 2) Phase J1 · Job Title / Service Type / Job Type keywords —
  //    promoted above the tech-department block. Pool check preserved
  //    ahead of landscape (historical frontend order).
  const hay = [job.service_type, job.job_type, job.title]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (POOL_KEYWORDS.some((k) => hay.includes(k))) return "pool";
  if (LANDSCAPING_KEYWORDS.some((k) => hay.includes(k))) return "landscaping";
  // 3) Phase 57 · assigned tech's department — only consulted when the
  //    job itself gave no keyword signal.
  const dept = (job.technician_department || "").toLowerCase();
  if (dept === "landscaping") return "landscaping";
  if (dept === "pool") return "pool";
  // 4) Phase P36.1 · fallback: no signal at all — default to
  //    ``"generic"`` (mirrors the backend's ``"non_pool"`` default).
  //    Pre-P36.1 this was ``"pool"`` which caused non-pool jobs
  //    (tree_service, hvac, pest_control, irrigation, …) to render
  //    the pool chemistry form; the backend chemistry gate then
  //    rejected their close with ``chemistry_core_readings_missing``.
  return "generic";
}

export default getChecklistType;
